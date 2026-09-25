"""
Advanced Asynchronous Read-Write Lock (AsyncRWLock) and Condition Concurrency Primitives.

This module provides highly optimized, state-machine-based Read-Write locks
and their corresponding Condition variables. It is designed specifically for
Python's `asyncio` event loop, supporting different scheduling strategies
(Write-preferring, Read-preferring, Reader-Phase Fair, Strict Fair) and safe
reentrancy for writer tasks.
"""
from __future__ import annotations

import asyncio
from abc import abstractmethod
from typing import Callable, Optional

from .base import (
    AsyncRWLockBase,
    AsyncRWConditionBase,
    AsyncConditionDowngradable,
    AsyncConditionLockable,
    AsyncLockDowngradable,
    AsyncLockable,
)
from .mixins import (
    _RWConditionMixin,
    _RWLockFairMixin,
    _RWLockFairReentrantWriterMixin,
    _RWLockReadMixin,
    _RWLockReadReentrantWriterMixin,
    _RWLockReaderPhaseFairMixin,
    _RWLockReaderPhaseFairReentrantWriterMixin,
    _RWLockWriteMixin,
    _RWLockWriteReentrantWriterMixin,
)
from .queues import (
    AsyncWaitQueue,
    AsyncConditionQueue
)

__version__ = '3.4.2'
__all__ = (
    'AsyncLockable', 'AsyncLockDowngradable', 
    'AsyncRWLockBase', 'AsyncRWLockWithProxyBase', 
    'AsyncRWLockProxy', 'AsyncRWLockReaderProxy', 'AsyncRWLockWriterProxy',
    'AsyncRWLockWrite', 'AsyncRWLockWriteReentrantWriter', 
    'AsyncRWLockRead', 'AsyncRWLockReadReentrantWriter',
    'AsyncRWLockReaderPhaseFair', 'AsyncRWLockReaderPhaseFairReentrantWriter',
    'AsyncRWLockFair', 'AsyncRWLockFairReentrantWriter',
    'AsyncLock',

    'AsyncConditionLockable', 'AsyncConditionDowngradable', 
    'AsyncRWConditionBase', 'AsyncRWConditionWithProxyBase',
    'AsyncRWConditionProxy', 'AsyncRWConditionReaderProxy', 'AsyncRWConditionWriterProxy',
    'AsyncRWCondition', 'AsyncCondition'
)


# Read Write Lock Proxy
class AsyncRWLockProxy:
    """
    Base proxy class acting as a standard `asyncio.Lock` interface.
    Handles acquisition logic, event loop yielding (`wait()`), and cancellation.
    """
    __slots__ = (
        'those_waiting', 'condition', '_can_acquire',
        '_acquire_core', '_release_core', '_on_abort', '_is_locked', '_waiter_seq',
        '_before_acquire'
    )  
    def __init__(self,  
        can_acquire: Callable[..., bool],
        acquire_core: Callable[..., None],
        release_core: Callable[[], None],
        on_abort: Callable[..., None],
        is_locked: Callable[[], bool],
        before_acquire: Optional[Callable[[], None]] = None,
    ):
        self.those_waiting = 0
        self.condition = AsyncWaitQueue(lambda: asyncio.get_running_loop().create_future())
        
        self._can_acquire = can_acquire
        self._acquire_core = acquire_core
        self._release_core = release_core
        self._on_abort = on_abort
        self._is_locked = is_locked
        self._waiter_seq = 0
        self._before_acquire = before_acquire

    async def acquire(self, blocking: bool = True) -> bool:
        """
        Acquire the lock dynamically in the asyncio event loop.
        
        Cancellation Safety:
            If the task is cancelled while `await self.condition.wait()` is yielding,
            the `finally` block ensures the wait counter is decremented and other
            tasks are properly notified via `_on_abort()`.
        """
        if self._before_acquire is not None:
            self._before_acquire()
        if self._can_acquire(False, None):
            self._acquire_core(False, None)
            return True
        if not blocking:
            return False
        self._waiter_seq += 1
        waiter_seq = self._waiter_seq
        self.those_waiting += 1
        acquired = False
        try:
            while not self._can_acquire(True, waiter_seq):
                await self.condition.wait()
            self._acquire_core(True, waiter_seq)
            acquired = True
            return True
        finally:
            self.those_waiting -= 1
            if not acquired:
                self._on_abort(waiter_seq)

    def release(self) -> None:
        """Release the acquired lock and notify waiting tasks synchronously."""
        self._release_core()

    def locked(self) -> bool:
        """Check if the lock is currently held."""
        return self._is_locked()

    async def __aenter__(self) -> bool:
        await self.acquire()
        return True

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> Optional[bool]:
        self.release()
        return False

class AsyncRWLockReaderProxy(AsyncRWLockProxy):
    """Proxy specifically handling Reader logic for asyncio."""
    __slots__ = ()
    def __init__(self, rwlock: AsyncRWLockWithProxyBase):
        super().__init__(
            can_acquire=rwlock._can_read,
            acquire_core=rwlock._acquire_read_core,
            release_core=rwlock._release_read_core,
            on_abort=rwlock._on_reader_abort,
            is_locked=rwlock._is_read_locked
        )

class AsyncRWLockWriterProxy(AsyncRWLockProxy):
    """
    Proxy specifically handling Writer logic, extending capabilities with
    atomic state degradation (Smart Proxy).
    """
    __slots__ = ('_read_lock', '_downgrade_core', '_downgraded_task')
    def __init__(self, rwlock: AsyncRWLockWithProxyBase):
        super().__init__(
            can_acquire=rwlock._can_write,
            acquire_core=rwlock._acquire_write_core,
            release_core=rwlock._release_write_core,
            on_abort=rwlock._on_writer_abort,
            is_locked=rwlock._is_write_locked,
            before_acquire=rwlock._check_write_acquire_allowed,
        )
        self._read_lock = rwlock.read
        self._downgrade_core = rwlock._downgrade_core
        self._downgraded_task: Optional[asyncio.Task] = None

    async def acquire(self, blocking: bool = True) -> bool:
        acquired = await super().acquire(blocking)
        if acquired:
            self._downgraded_task = None
        return acquired
            
    def downgrade(self):
        """
        Atomically transition the held Write lock into a Read lock.
        Allows nested usage within `async with lock.write` blocks.
        
        Performance Cost:
            Stores only the current `asyncio.Task` in a single downgrade marker.
        """
        self._downgrade_core()
        self._downgraded_task = asyncio.current_task()
    
    def release(self):
        """
        Release the lock intelligently.
        Checks if the current task downgraded the lock earlier. If so, it routes
        the release logic to the reader core, avoiding Deadlocks and RuntimeErrors.
        """
        current_task = asyncio.current_task()
        if self._downgraded_task is current_task:
            self._downgraded_task = None
            try:
                self._read_lock._release_core()
                return
            except RuntimeError:
                pass
        self._release_core()


# Read Write Locks
class AsyncRWLockWithProxyBase(AsyncRWLockBase):
    """
    Abstract base class for all proxy-based asynchronous Read-Write lock implementations.

    This class manages the core `asyncio.Lock` and initializes the Smart Proxy Pattern, 
    exposing `read` and `write` attributes as proxy instances that safely handle 
    task cancellation and route logic to the overridden internal core methods.
    """
    __slots__ = ("_reader_owners", "_writer_owner")
    def __init__(self):
        self._reader_owners = {}
        self._writer_owner = None
        self.read:AsyncRWLockReaderProxy = AsyncRWLockReaderProxy(rwlock=self)
        self.write:AsyncRWLockWriterProxy = AsyncRWLockWriterProxy(rwlock=self)

    def _current_reader_owner(self):
        return asyncio.current_task()

    def _record_reader_acquire(self) -> None:
        owner = self._current_reader_owner()
        self._reader_owners[owner] = self._reader_owners.get(owner, 0) + 1

    def _record_reader_release(self) -> None:
        owner = self._current_reader_owner()
        count = self._reader_owners.get(owner, 0)
        if count == 0:
            raise RuntimeError("Read lock is not held by the current task")
        if count == 1:
            del self._reader_owners[owner]
        else:
            self._reader_owners[owner] = count - 1

    def _is_current_reader(self) -> bool:
        return self._reader_owners.get(self._current_reader_owner(), 0) > 0

    def _is_current_writer(self) -> bool:
        if hasattr(self, "_writer_id"):
            return self._writer_id is self._current_reader_owner()
        return self._writer_owner is self._current_reader_owner()

    def _check_write_acquire_allowed(self) -> None:
        if self._is_current_reader() and not self._is_current_writer():
            raise RuntimeError(
                "Read-to-write upgrade is not supported; release the read lock "
                "before acquiring the write lock"
            )

    @abstractmethod
    def _can_read(self, waiting: bool = False, waiter_seq: Optional[int] = None) -> bool: ...
    @abstractmethod
    def _acquire_read_core(self, waiting: bool = False, waiter_seq: Optional[int] = None) -> None: ...
    @abstractmethod
    def _release_read_core(self) -> None: ...
    @abstractmethod
    def _on_reader_abort(self, waiter_seq: Optional[int] = None) -> None: ...
    @abstractmethod
    def _can_write(self, waiting: bool = False, waiter_seq: Optional[int] = None) -> bool: ...
    @abstractmethod
    def _acquire_write_core(self, waiting: bool = False, waiter_seq: Optional[int] = None) -> None: ...
    @abstractmethod
    def _release_write_core(self) -> None: ...
    @abstractmethod
    def _downgrade_core(self) -> None: ...
    @abstractmethod
    def _on_writer_abort(self, waiter_seq: Optional[int] = None) -> None: ...


class AsyncRWLockWrite(_RWLockWriteMixin, AsyncRWLockWithProxyBase):
    """
    Write-preferring Asynchronous Read-Write Lock.
    
    Prevents new readers from acquiring the lock if there are writers waiting,
    mitigating writer starvation.

    Example:
        ```python
        lock = AsyncRWLockWrite()
        
        # Multiple readers can acquire the lock simultaneously.
        async with lock.read:
            print("Reading data...")
            
        # If a writer starts waiting here, new readers are blocked
        # until the writer finishes, preventing writer starvation.
        async with lock.write:
            print("Updating data...")
        ```
    Example 2 (Direct Lock Interface):
        ```python
        lock = AsyncRWLockWrite()
        
        # By using the lock instance directly, it automatically routes to the 
        # exclusive (write) proxy. This allows the AsyncRWLock to be safely injected 
        # into legacy code that only understands standard asyncio.Lock.
        async with lock:
            print("Exclusive write lock acquired via direct standard API.")
        ```
    """
    __slots__ = ('_writer_active', '_readers_active')
    def __init__(self):
        super().__init__()
        self._writer_active = False
        self._readers_active = 0

class AsyncRWLockWriteReentrantWriter(
    _RWLockWriteReentrantWriterMixin,
    AsyncRWLockWrite,
):
    """
    Write-preferring Asynchronous Read-Write Lock with Task-Reentrancy.
    
    Reentrancy Note:
        The owning task can acquire nested write locks and a read lock. Other
        readers can join only after an explicit downgrade opens shared access.
        Reentrancy is resolved via
        O(1) memory pointer comparison (`is` operator) of the asyncio Task.
    
    Example:
        ```python
        lock = AsyncRWLockWriteReentrantWriter()
        
        async with lock.write:
            print("Outer write lock acquired.")
            
            # The same task can safely re-acquire the write lock without deadlocking.
            async with lock.write:
                print("Inner (nested) write lock acquired safely.")
            
            # Atomically downgrade to a read lock, allowing other readers to enter
            # without giving up task ownership entirely.
            lock.write.downgrade()
            print("Downgraded to read mode.")
        ```
    Example 2 (Direct Lock Interface):
        ```python
        lock = AsyncRWLockWriteReentrantWriter()
        
        # By using the lock instance directly, it automatically routes to the 
        # exclusive (write) proxy. This allows the AsyncRWLock to be safely injected 
        # into legacy code that only understands standard asyncio.Lock.
        async with lock:
            print("Exclusive write lock acquired via direct standard API.")
        ```
    """
    __slots__ = ('_writer_id', '_write_count')

    def __init__(self):
        super().__init__()
        self._writer_id: Optional[asyncio.Task] = None
        self._write_count: int = 0

    def _is_current_writer(self) -> bool:
        return self._writer_id is asyncio.current_task()

    def _set_current_writer(self) -> None:
        self._writer_id = asyncio.current_task()

    def _clear_current_writer(self) -> None:
        self._writer_id = None


class AsyncRWLockRead(_RWLockReadMixin, AsyncRWLockWithProxyBase):
    """
    Read-preferring Asynchronous Read-Write Lock.
    
    Allows maximum concurrency for readers by always allowing new readers,
    potentially leading to writer starvation under heavy read loads.

    Example:
        ```python
        lock = AsyncRWLockRead()
        
        # Readers can continuously enter the lock as long as no writer 
        # is currently holding it, even if writers are waiting.
        async with lock.read:
            print("Reading data...")
            
        # The writer must wait until ALL active readers have released the lock.
        async with lock.write:
            print("Updating data...")
        ```
    Example 2 (Direct Lock Interface):
        ```python
        lock = AsyncRWLockRead()
        
        # By using the lock instance directly, it automatically routes to the 
        # exclusive (write) proxy. This allows the AsyncRWLock to be safely injected 
        # into legacy code that only understands standard asyncio.Lock.
        async with lock:
            print("Exclusive write lock acquired via direct standard API.")
        ```
    """
    __slots__ = ('_writer_active', '_readers_active')
    def __init__(self):
        super().__init__()
        self._writer_active = False
        self._readers_active = 0

class AsyncRWLockReadReentrantWriter(_RWLockReadReentrantWriterMixin, AsyncRWLockRead):
    """
    Read-preferring Asynchronous Read-Write Lock with Task-Reentrancy.
    
    Reentrancy Note:
        The owning task can nest write acquisitions and acquire read locks.
        Read-to-write upgrades are rejected to avoid self-deadlocks.

    Example:
        ```python
        lock = AsyncRWLockReadReentrantWriter()
        
        async with lock.write:
            print("Outer write lock acquired.")
            
            # The same task can safely re-acquire the write lock without deadlocking.
            async with lock.write:
                print("Inner (nested) write lock acquired safely.")
            
            # Atomically downgrade to a read lock, allowing other readers to enter
            # without giving up task ownership entirely.
            lock.write.downgrade()
            print("Downgraded to read mode.")
        ```
    Example 2 (Direct Lock Interface):
        ```python
        lock = AsyncRWLockReadReentrantWriter()
        
        # By using the lock instance directly, it automatically routes to the 
        # exclusive (write) proxy. This allows the AsyncRWLock to be safely injected 
        # into legacy code that only understands standard asyncio.Lock.
        async with lock:
            print("Exclusive write lock acquired via direct standard API.")
        ```
    """
    __slots__ = ('_writer_id', '_write_count')

    def __init__(self):
        super().__init__()
        self._writer_id: Optional[asyncio.Task] = None
        self._write_count: int = 0

    def _is_current_writer(self) -> bool:
        return self._writer_id is asyncio.current_task()

    def _set_current_writer(self) -> None:
        self._writer_id = asyncio.current_task()

    def _clear_current_writer(self) -> None:
        self._writer_id = None


class AsyncRWLockReaderPhaseFair(_RWLockReaderPhaseFairMixin, AsyncRWLockWithProxyBase):
    """
    Reader-phase fair Asynchronous Read-Write Lock.

    This lock alternates between reader and writer phases, but readers arriving
    during an already open reader phase may still join that phase. It generally
    offers higher read-heavy throughput than strict fair locking.

    Example:
        ```python
        lock = AsyncRWLockReaderPhaseFair()

        async with lock.read:
            print("Reading data...")

        async with lock.write:
            print("Updating data...")
        ```
    Example 2 (Direct Lock Interface):
        ```python
        lock = AsyncRWLockReaderPhaseFair()

        async with lock:
            print("Exclusive write lock acquired via direct standard API.")
        ```
    """
    __slots__ = ('_writer_active', '_readers_turn', '_readers_active')

    def __init__(self):
        super().__init__()
        self._writer_active = False
        self._readers_turn = False
        self._readers_active = 0

class AsyncRWLockReaderPhaseFairReentrantWriter(_RWLockReaderPhaseFairReentrantWriterMixin, AsyncRWLockReaderPhaseFair):
    """
    Reader-phase fair Asynchronous Read-Write Lock with task reentrancy.

    Example:
        ```python
        lock = AsyncRWLockReaderPhaseFairReentrantWriter()

        async with lock.write:
            async with lock.write:
                print("Nested write lock acquired safely.")
            lock.write.downgrade()
            print("Downgraded to read mode.")
        ```
    Example 2 (Direct Lock Interface):
        ```python
        lock = AsyncRWLockReaderPhaseFairReentrantWriter()

        async with lock:
            print("Exclusive write lock acquired via direct standard API.")
        ```
    """
    __slots__ = ('_writer_id', '_write_count')

    def __init__(self):
        super().__init__()
        self._writer_id: Optional[asyncio.Task] = None
        self._write_count: int = 0

    def _is_current_writer(self) -> bool:
        return self._writer_id is asyncio.current_task()

    def _set_current_writer(self) -> None:
        self._writer_id = asyncio.current_task()

    def _clear_current_writer(self) -> None:
        self._writer_id = None


class AsyncRWLockFair(_RWLockFairMixin, AsyncRWLockReaderPhaseFair):
    """
    Strict fair Asynchronous Read-Write Lock.

    This lock opens a reader phase only for the readers already queued when the
    phase begins. Readers arriving later wait for the next turn, producing more
    deterministic writer latency than `AsyncRWLockReaderPhaseFair`.

    Example:
        ```python
        lock = AsyncRWLockFair()

        async with lock.read:
            print("Reading data...")

        async with lock.write:
            print("Updating data...")
        ```
    Example 2 (Direct Lock Interface):
        ```python
        lock = AsyncRWLockFair()

        async with lock:
            print("Exclusive write lock acquired via direct standard API.")
        ```
    """
    __slots__ = ('_reader_phase_cutoff', '_reader_phase_pending')

    def __init__(self):
        super().__init__()
        self._reader_phase_cutoff = 0
        self._reader_phase_pending = 0

class AsyncRWLockFairReentrantWriter(_RWLockFairReentrantWriterMixin, AsyncRWLockFair):
    """
    Strict fair Asynchronous Read-Write Lock with task reentrancy.

    Example:
        ```python
        lock = AsyncRWLockFairReentrantWriter()

        async with lock.write:
            async with lock.write:
                print("Nested write lock acquired safely.")
            lock.write.downgrade()
            print("Downgraded to read mode.")
        ```
    Example 2 (Direct Lock Interface):
        ```python
        lock = AsyncRWLockFairReentrantWriter()

        async with lock:
            print("Exclusive write lock acquired via direct standard API.")
        ```
    """
    __slots__ = ('_writer_id', '_write_count')

    def __init__(self):
        super().__init__()
        self._writer_id: Optional[asyncio.Task] = None
        self._write_count: int = 0

    def _is_current_writer(self) -> bool:
        return self._writer_id is asyncio.current_task()

    def _set_current_writer(self) -> None:
        self._writer_id = asyncio.current_task()

    def _clear_current_writer(self) -> None:
        self._writer_id = None


# Standart Lock Adapter
class AsyncLock(AsyncRWLockBase):
    """
    Adapter class for the standard `asyncio.Lock`.
    
    Wraps the standard asyncio lock to conform to the `AsyncRWLockBase` interface, 
    exposing it via both `.read` and `.write` attributes. Useful for dependency 
    injection where an AsyncRWLock signature is required, but a standard lock is sufficient.

    Example:
        ```python
        lock = AsyncLock()
        
        # Both .read and .write point to the same standard asyncio.Lock
        async with lock.read:
            print("Reading with standard async lock...")
            
        async with lock.write:
            print("Writing with standard async lock...")
        ```
    Example 2 (Direct Lock Interface):
        ```python
        lock = AsyncLock()
        
        # Acts exactly like a standard asyncio.Lock.
        # Perfect for passing into third-party libraries expecting a standard async lock.
        async with lock:
            print("Standard async lock acquired directly without proxies.")
        ```
    """
    __slots__ = ()
    def __init__(self):
        super().__init__(asyncio.Lock())
    


# Read Write Condition Proxy
class AsyncRWConditionProxy:
    """
    Base proxy class acting as a standard `asyncio.Condition` interface.
    
    It holds no state of its own. It dynamically routes lock acquisitions, 
    releases, and signaling operations to the injected core callables provided 
    by the underlying `AsyncRWConditionBase` implementation. It is engineered 
    to be fully resilient to `asyncio.CancelledError`.
    """
    __slots__ = (
        '_lock_proxy', '_is_owned', '_add_waiter', 
        '_remove_waiter', '_notify_core', '_notify_all_core',
        '_get_owned_depth'
    )
    
    def __init__(self, 
        lock_proxy: 'AsyncRWLockProxy',
        is_owned: Callable[[], bool],
        add_waiter: Callable[[], asyncio.Future],
        remove_waiter: Callable[[asyncio.Future], None],
        notify_core: Callable[[int], None],
        notify_all_core: Callable[[], None],
        get_owned_depth: Optional[Callable[[], int]] = None
    ):
        self._lock_proxy = lock_proxy
        self._is_owned = is_owned
        self._add_waiter = add_waiter
        self._remove_waiter = remove_waiter
        self._notify_core = notify_core
        self._notify_all_core = notify_all_core
        self._get_owned_depth = get_owned_depth

    async def acquire(self, blocking: bool = True) -> bool:
        """
        Acquire the underlying asynchronous lock (Read or Write depending on the proxy).

        Args:
            blocking (bool): If False, return immediately if the lock cannot be acquired.
                             Defaults to True.

        Returns:
            bool: True if the lock was successfully acquired, False otherwise.
        """
        return await self._lock_proxy.acquire(blocking)

    def release(self) -> None:
        """
        Release the underlying asynchronous lock (Read or Write).
        
        Raises:
            RuntimeError: If the lock was not acquired by the current task before 
                          calling this method.
        """
        self._lock_proxy.release()

    def locked(self) -> bool:
        """
        Check if the underlying lock is currently held.

        Returns:
            bool: True if the lock is acquired by any task, False otherwise.
        """
        return self._lock_proxy.locked()

    async def __aenter__(self) -> bool:
        return await self._lock_proxy.__aenter__()

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> Optional[bool]:
        return await self._lock_proxy.__aexit__(exc_type, exc_val, exc_tb)

    async def wait(self) -> bool:
        """
        Wait until notified.

        This method releases the underlying lock while waiting and reacquires
        it before returning. Nested lock acquisitions are rejected because this
        condition does not restore recursive lock depth.

        Returns:
            bool: Always returns True if awoken safely by a `notify()` call.
            
        Raises:
            RuntimeError: If the lock is not owned by the current task or has
                          nested acquisitions.
            asyncio.CancelledError: If the task is cancelled while waiting. The 
                                    exception is propagated ONLY after the lock 
                                    is safely re-acquired to prevent state corruption.
        """
        if not self._is_owned():
            raise RuntimeError("cannot wait on un-acquired lock")
        if self._get_owned_depth is not None and self._get_owned_depth() != 1:
            raise RuntimeError(
                "Condition.wait() requires exactly one lock acquisition; "
                "nested acquisitions are not supported"
            )
            
        waiter = self._add_waiter()
        try:
            self.release()
        except BaseException:
            self._remove_waiter(waiter)
            raise
        
        try:
            await waiter
            return True
        except asyncio.CancelledError:
            self._remove_waiter(waiter)
            raise
        finally:
            # Critical asyncio section: Shield the re-acquisition loop from 
            # cancellation to prevent permanent deadlock / state corruption.
            err = None
            while True:
                try:
                    await self.acquire()
                    break
                except asyncio.CancelledError as e:
                    err = e
            
            # Re-raise cancellation only after the lock has been re-acquired.
            if err is not None:
                raise err

    async def wait_for(self, predicate: Callable[[], bool]) -> bool:
        """
        Wait until a specific condition (predicate) evaluates to True.
        
        This utility method repeatedly calls `wait()` until the predicate
        returns a truthy value. For timeout functionality, wrap a coroutine
        that acquires the condition, calls `wait_for()`, and releases it with
        `asyncio.wait_for()`. This keeps lock ownership in the same task because
        `asyncio.wait_for()` runs the wrapped coroutine in a task of its own.

        Args:
            predicate (Callable): A synchronous function returning a boolean 
                                  indicating if the desired state has been reached.

        Returns:
            bool: The last truthy return value of the predicate.
            
        Raises:
            RuntimeError: If the lock is not owned when called.
        """
        result = predicate()
        while not result:
            await self.wait()
            result = predicate()
        return result

    def notify(self, n: int = 1) -> None:
        """
        Wake up one or more tasks waiting on this condition.
        
        Args:
            n (int): The maximum number of waiting tasks to wake up. Defaults to 1.
                     Tasks that have already been cancelled are ignored and do not
                     count towards this limit.
            
        Raises:
            RuntimeError: If the lock is not owned by the current task when 
                          `notify()` is called.
        """
        if not self._is_owned():
            raise RuntimeError("cannot notify on un-acquired lock")
        self._notify_core(n)

    def notify_all(self) -> None:
        """
        Wake up all tasks currently waiting on this condition.
        
        Raises:
            RuntimeError: If the lock is not owned by the current task when 
                          `notify_all()` is called.
        """
        if not self._is_owned():
            raise RuntimeError("cannot notify on un-acquired lock")
        self._notify_all_core()

class AsyncRWConditionReaderProxy(AsyncRWConditionProxy):
    """
    Condition proxy bound specifically to the Reader state-machine.
    
    Calling `wait()` on this proxy will release the underlying READ lock,
    allowing other writers or readers to proceed while the current task sleeps
    in the event loop.
    """
    __slots__ = ()
    def __init__(self, rwcond: AsyncRWConditionWithProxyBase):
        super().__init__(
            lock_proxy=rwcond._lock.read,
            is_owned=rwcond._is_owned_read,
            add_waiter=rwcond._add_waiter,
            remove_waiter=rwcond._remove_waiter,
            notify_core=rwcond._notify_core,
            notify_all_core=rwcond._notify_all_core,
            get_owned_depth=getattr(rwcond, "_get_owned_lock_depth", None)
        )

class AsyncRWConditionWriterProxy(AsyncRWConditionProxy):
    """
    Condition proxy bound specifically to the Writer state-machine.
    
    Calling `wait()` on this proxy will release the underlying WRITE lock,
    allowing other tasks to acquire the lock while the current task sleeps
    in the event loop.
    """
    __slots__ = ()
    def __init__(self, rwcond: AsyncRWConditionWithProxyBase):
        super().__init__(
            lock_proxy=rwcond._lock.write,
            is_owned=rwcond._is_owned_write,
            add_waiter=rwcond._add_waiter,
            remove_waiter=rwcond._remove_waiter,
            notify_core=rwcond._notify_core,
            notify_all_core=rwcond._notify_all_core,
            get_owned_depth=getattr(rwcond, "_get_owned_lock_depth", None)
        )
    
    def downgrade(self) -> None:
        """
        Atomically transition the underlying asynchronous Write lock into a Read lock.
        
        This passes the downgrade request directly to the underlying async lock proxy,
        allowing waiting readers to enter while maintaining the condition context.
        """
        self._lock_proxy.downgrade()


# Read Write Condition
class AsyncRWConditionWithProxyBase(AsyncRWConditionBase):
    """
    Abstract base class for proxy-based Asynchronous Read-Write Condition variables.
    
    This class solely defines the internal state machine and core queuing 
    operations. It strictly hides its internal mechanisms and exposes its 
    functionality via `.read` and `.write` proxies to maintain a clean, 
    standardized `asyncio.Condition` API resilient to task cancellations.
    """
    __slots__ = ()
    def __init__(self, lock: Optional[AsyncRWLockBase] = None):
        self._lock = AsyncRWLockWrite() if lock is None else lock
        self.read: AsyncRWConditionReaderProxy = AsyncRWConditionReaderProxy(rwcond=self)
        self.write: AsyncRWConditionWriterProxy = AsyncRWConditionWriterProxy(rwcond=self)

    @abstractmethod
    def _is_owned_read(self) -> bool: ...
    @abstractmethod
    def _is_owned_write(self) -> bool: ...
    @abstractmethod
    def _add_waiter(self) -> asyncio.Future: ...
    @abstractmethod
    def _remove_waiter(self, waiter: asyncio.Future) -> None: ...
    @abstractmethod
    def _notify_core(self, n: int) -> None: ...
    @abstractmethod
    def _notify_all_core(self) -> None: ...

class AsyncRWCondition(_RWConditionMixin, AsyncRWConditionWithProxyBase):
    """
    Standard implementation of an Asynchronous Read-Write Condition variable.
    
    Uses a `collections.deque` of `asyncio.Future` objects. Queue insertion and
    FIFO removal are amortized O(1); `notify_all()` signals each waiter and is
    O(N).

    Example:
        ```python
        cond = AsyncRWCondition()  # AsyncRWLockWrite default lock
        
        # Reader task
        async with cond.read:
            await cond.read.wait_for(lambda: data_ready)
            print(data)
            
        # Writer task
        async with cond.write:
            data_ready = True
            cond.write.notify_all()
        ```
    Example 2 (Direct Lock Interface):
        ```python
        cond = AsyncRWCondition()  # AsyncRWLockWrite default lock
        
        # Direct usage bypasses explicit .read/.write proxies and defaults to 
        # the exclusive write state, providing lock-style compatibility with
        # standard asyncio.Condition workflows.
        async with cond:
            while not data_ready:
                await cond.wait()
            cond.notify_all()
        ```
    """
    __slots__ = ('_queue',)
    
    def __init__(self, lock: Optional[AsyncRWLockBase] = None):
        self._queue = AsyncConditionQueue(lambda: asyncio.get_running_loop().create_future())
        super().__init__(lock)
    

# Standart Condition Adapter
class AsyncCondition(AsyncRWConditionBase):
    """
    Adapter class for the standard `asyncio.Condition`.
    
    Wraps the standard asyncio condition to conform to the `AsyncRWConditionBase` 
    interface. Both `.read` and `.write` attributes point to the same standard 
    condition instance. Cannot be initialized with proxy-based complex AsyncRWLocks.

    Example:
        ```python
        cond = AsyncCondition()
        
        # Both .read and .write point to the same standard asyncio.Condition
        async with cond.read:
            await cond.read.wait_for(lambda: data_ready)
            
        async with cond.write:
            data_ready = True
            cond.write.notify_all()
        ```
    Example 2 (Direct Lock Interface):
        ```python
        cond = AsyncCondition()
        
        # Functions identically to asyncio.Condition.
        async with cond:
            await cond.wait_for(lambda: data_ready)
            cond.notify()
        ```
    """
    __slots__ = ()
    def __init__(self, lock: Optional[AsyncLockable] = None):
        lock = asyncio.Lock() if lock is None else lock
        condition = asyncio.Condition(lock)
        super().__init__(lock, condition)
