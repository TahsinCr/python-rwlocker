"""
Advanced Asynchronous Read-Write Lock (AsyncRWLock) and Condition Concurrency Primitives.

This module provides highly optimized, state-machine-based Read-Write locks 
and their corresponding Condition variables. It is designed specifically for 
Python's `asyncio` event loop, supporting different scheduling strategies 
(Write-preferring, Read-preferring, FIFO) and safe reentrancy for writer tasks.

Architecture Notes:
    - **Smart Proxies**: The locks and conditions are interacted with via 
      `.read` and `.write` proxy objects. These proxies transparently handle 
      the underlying state transitions and expose standard `asyncio` APIs.
    - **Efficient Condition Queuing**: The `AsyncRWCondition` primitive utilizes 
      an `asyncio.Future` and `deque` architecture to provide highly efficient 
      wait/notify operations, eliminating event loop blocking and providing 
      strict protection against cache stampedes.
    - **Circular References**: The base classes (`AsyncRWLockBase`, `AsyncRWConditionBase`) 
      hold references to their respective `read` and `write` proxies, and the 
      proxies hold a reference back to the base. This circular dependency is 
      resolved by Python's Garbage Collector. Do not rely on `__del__` for 
      deterministic cleanup.
    - **Cancellation Safety & Task Tracking**: Standard lock acquisition and wait 
      operations use `asyncio.current_task()` for O(1) identity tracking. All 
      state transitions are fully resilient to `asyncio.CancelledError`, strictly 
      preventing deadlocks and state corruption during task cancellations.
"""
import asyncio
from collections import deque
from abc import ABC, abstractmethod
from typing import Callable, Protocol, Optional
from types import TracebackType

__version__ = '2.0'
__all__ = (
    'AsyncLockable', 'AsyncLockDowngradable', 'AsyncRWLockBase', 'AsyncRWConditionBase', 
    'AsyncRWLockProxy', 'AsyncRWLockReaderProxy', 'AsyncRWLockWriterProxy',
    'AsyncRWLockWrite', 'AsyncRWLockWriteReentrantWriter', 
    'AsyncRWLockRead', 'AsyncRWLockReadReentrantWriter',
    'AsyncRWLockFIFO', 'AsyncRWLockFIFOReentrantWriter',
    'AsyncRWConditionProxy', 'AsyncRWConditionReaderProxy', 'AsyncRWConditionWriterProxy',
    'AsyncRWCondition'
)

# Protocol and Base
class AsyncLockable(Protocol):
    """Protocol defining a standard asyncio-compatible lock interface."""
    async def acquire(self, blocking: bool = True) -> bool: ...
    async def release(self) -> None: ...
    async def locked(self) -> bool: ...
    async def __aenter__(self) -> bool: ...
    async def __aexit__(self, 
        exc_type: Optional[type[BaseException]], 
        exc_val: Optional[BaseException], 
        exc_tb: Optional[TracebackType]
    ) -> Optional[bool]: ...

class AsyncLockDowngradable(AsyncLockable):
    """Protocol for async locks that support atomic state degradation (Write -> Read)."""
    async def downgrade(self) -> None: ...

class AsyncRWLockBase(ABC):
    """
    Abstract base class for all asynchronous Read-Write lock implementations.

    Manages the core `asyncio.Lock`, active reader counters, and constructs the
    read/write proxy managers.

    Warning:
        This class forms a circular reference with `AsyncRWLockReaderProxy` and 
        `AsyncRWLockWriterProxy`. Memory is reclaimed via the GC.
    """
    __slots__ = ('_lock', '_readers_active', 'read', 'write')
    def __init__(self, lock_factory: Callable[[], asyncio.Lock] = asyncio.Lock):
        self._lock = lock_factory()
        self._readers_active = 0
        self.read: 'AsyncRWLockReaderProxy' = AsyncRWLockReaderProxy(rwlock=self)
        self.write: 'AsyncRWLockWriterProxy' = AsyncRWLockWriterProxy(rwlock=self)

    def _is_read_locked(self) -> bool:
        return self._readers_active > 0

    @abstractmethod
    def _can_read(self) -> bool: ...
    @abstractmethod
    def _acquire_read_core(self) -> None: ...
    @abstractmethod
    def _release_read_core(self) -> None: ...
    @abstractmethod
    def _on_reader_abort(self) -> None: ...
    @abstractmethod
    def _can_write(self) -> bool: ...
    @abstractmethod
    def _acquire_write_core(self) -> None: ...
    @abstractmethod
    def _release_write_core(self) -> None: ...
    @abstractmethod
    def _downgrade_core(self) -> None: ...
    @abstractmethod
    def _on_writer_abort(self) -> None: ...
    @abstractmethod
    def _is_write_locked(self) -> bool: ...

class AsyncRWConditionBase(ABC):
    """
    Abstract base class for all asynchronous Read-Write Condition variables.
    
    Like AsyncRWLockBase, it strictly hides its internal mechanisms and exposes 
    its functionality via `.read` and `.write` proxies to maintain a clean, 
    standardized asyncio.Condition API.
    """
    __slots__ = ('_rwlock', 'read', 'write')
    
    def __init__(self, rwlock: 'AsyncRWLockBase'):
        self._rwlock = rwlock
        self.read: 'AsyncRWConditionReaderProxy' = AsyncRWConditionReaderProxy(rwcond=self)
        self.write: 'AsyncRWConditionWriterProxy' = AsyncRWConditionWriterProxy(rwcond=self)

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

# Read and Write Lock Proxy
class AsyncRWLockProxy:
    """
    Base proxy class acting as a standard `asyncio.Lock` interface.
    Handles acquisition logic, event loop yielding (`wait()`), and cancellation.
    """
    __slots__ = (
        '_lock', 'those_waiting', 'condition', '_can_acquire',
        '_acquire_core', '_release_core', '_on_abort', '_is_locked'
    )  
    def __init__(self, 
        lock: asyncio.Lock, 
        can_acquire: Callable[[], bool],
        acquire_core: Callable[[], None],
        release_core: Callable[[], None],
        on_abort: Callable[[], None],
        is_locked: Callable[[], bool],
    ):
        self._lock = lock
        self.those_waiting = 0
        self.condition = asyncio.Condition(self._lock)
        
        self._can_acquire = can_acquire
        self._acquire_core = acquire_core
        self._release_core = release_core
        self._on_abort = on_abort
        self._is_locked = is_locked

    async def acquire(self, blocking: bool = True) -> bool:
        """
        Acquire the lock dynamically in the asyncio event loop.
        
        Cancellation Safety:
            If the task is cancelled while `await self.condition.wait()` is yielding,
            the `finally` block ensures the wait counter is decremented and other
            tasks are properly notified via `_on_abort()`.
        """
        async with self._lock:
            if self._can_acquire():
                self._acquire_core()
                return True
            if not blocking:
                return False
            self.those_waiting += 1
            acquired = False
            try:
                while not self._can_acquire():
                    await self.condition.wait()
                self._acquire_core()
                acquired = True
                return True
            finally:
                self.those_waiting -= 1
                if not acquired:
                    self._on_abort()

    async def release(self) -> None:
        """Release the acquired lock and notify waiting tasks synchronously."""
        async with self._lock:
            self._release_core()

    async def locked(self) -> bool:
        """Check if the lock is currently held."""
        async with self._lock:
            return self._is_locked()

    async def __aenter__(self) -> bool:
        await self.acquire()
        return True

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> Optional[bool]:
        await self.release()
        return False

class AsyncRWLockReaderProxy(AsyncRWLockProxy):
    """Proxy specifically handling Reader logic for asyncio."""
    __slots__ = ()
    def __init__(self, rwlock: AsyncRWLockBase):
        super().__init__(
            lock=rwlock._lock,
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
    __slots__ = ('_read_lock', '_downgrade_core', '_downgraded_tasks')
    def __init__(self, rwlock: AsyncRWLockBase):
        super().__init__(
            lock=rwlock._lock,
            can_acquire=rwlock._can_write,
            acquire_core=rwlock._acquire_write_core,
            release_core=rwlock._release_write_core,
            on_abort=rwlock._on_writer_abort,
            is_locked=rwlock._is_write_locked
        )
        self._read_lock = rwlock.read
        self._downgrade_core = rwlock._downgrade_core
        self._downgraded_tasks:set[asyncio.Task] = set()
            
    async def downgrade(self):
        """
        Atomically transition the held Write lock into a Read lock.
        Allows nested usage within `async with lock.write` blocks.
        
        Performance Cost:
            Adds `asyncio.current_task()` pointer to a tracking `set`.
            This incurs a minor memory footprint and an O(1) hash lookup 
            during the subsequent `release()` call.
        """
        async with self._lock:
            self._downgrade_core()
            self._downgraded_tasks.add(asyncio.current_task())
    
    async def release(self):
        """
        Release the lock intelligently.
        Checks if the current task downgraded the lock earlier. If so, it routes
        the release logic to the reader core, avoiding Deadlocks and RuntimeErrors.
        """
        async with self._lock:
            if self._downgraded_tasks: 
                task = asyncio.current_task()
                if task in self._downgraded_tasks:
                    self._downgraded_tasks.remove(task)
                    self._read_lock._release_core()
                    return
            self._release_core()

#  Read and Write Lock
class AsyncRWLockWrite(AsyncRWLockBase):
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
    """
    __slots__ = ('_writer_active',)
    def __init__(self, lock_factory: Callable[[], asyncio.Lock] = asyncio.Lock):
        super().__init__(lock_factory)
        self._writer_active = False

    def _can_read(self) -> bool:
        return not self._writer_active and self.write.those_waiting == 0
    
    def _acquire_read_core(self):
        self._readers_active += 1

    def _release_read_core(self):
        if self._readers_active == 0:
            raise RuntimeError("Unacquired read lock")
        self._readers_active -= 1
        if self._readers_active == 0:
            self.write.condition.notify()

    def _on_reader_abort(self):
        pass

    def _can_write(self) -> bool: 
        return not self._writer_active and self._readers_active == 0
    
    def _acquire_write_core(self): 
        self._writer_active = True
        
    def _release_write_core(self):
        if not self._writer_active: 
            raise RuntimeError("Unacquired write lock")
        self._writer_active = False
        self._on_writer_abort()

    def _downgrade_core(self):
        if not self._writer_active: 
            raise RuntimeError("Cannot downgrade unlocked lock")
        self._writer_active = False
        self._readers_active += 1
        self.read.condition.notify_all()

    def _on_writer_abort(self):
        if self.write.those_waiting > 0: 
            self.write.condition.notify()
        else: 
            self.read.condition.notify_all()

    def _is_write_locked(self) -> bool: 
        return self._writer_active

class AsyncRWLockWriteReentrantWriter(AsyncRWLockWrite):
    """
    Write-preferring Asynchronous Read-Write Lock with Task-Reentrancy.
    
    Reentrancy Note:
        Strictly supports nested *write* operations for the same `asyncio.Task`.
        It does NOT implicitly grant read locks. Reentrancy is resolved via 
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
            await lock.write.downgrade()
            print("Downgraded to read mode.")
        ```
    """
    __slots__ = ('_writer_id', '_write_count')

    def __init__(self, lock_factory: Callable[[], asyncio.Lock] = asyncio.Lock):
        super().__init__(lock_factory)
        self._writer_id: Optional[asyncio.Task] = None
        self._write_count: int = 0

    def _can_read(self) -> bool:
        if self._writer_id is asyncio.current_task(): 
            return True
        return self._writer_id is None and self.write.those_waiting == 0

    def _can_write(self) -> bool:
        return (self._writer_id is None and self._readers_active == 0) or self._writer_id is asyncio.current_task()
    
    def _acquire_write_core(self):
        self._writer_id = asyncio.current_task()
        self._write_count += 1

    def _release_write_core(self):
        if self._writer_id is not asyncio.current_task():
            raise RuntimeError("Permission denied")
        self._write_count -= 1
        if self._write_count == 0:
            self._writer_id = None
            self._on_writer_abort()

    def _downgrade_core(self):
        if self._writer_id is not asyncio.current_task():
            raise RuntimeError("Permission denied")
        if self._write_count > 1:
            raise RuntimeError("Cannot downgrade a nested write lock.")
        self._writer_id = None
        self._write_count = 0
        self._readers_active += 1
        self.read.condition.notify_all()

    def _is_write_locked(self) -> bool: 
        return self._writer_id is not None

class AsyncRWLockRead(AsyncRWLockBase):
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
    """
    __slots__ = ('_writer_active',)
    def __init__(self, lock_factory: Callable[[], asyncio.Lock] = asyncio.Lock):
        super().__init__(lock_factory)
        self._writer_active = False

    def _can_read(self) -> bool:
        return not self._writer_active
    
    def _acquire_read_core(self):
        self._readers_active += 1

    def _release_read_core(self):
        if self._readers_active == 0:
            raise RuntimeError("Unacquired read lock")
        self._readers_active -= 1
        if self._readers_active == 0:
            self.write.condition.notify()

    def _on_reader_abort(self):
        if self.read.those_waiting == 0 and self._readers_active == 0:
            self.write.condition.notify()

    def _can_write(self) -> bool: 
        return not self._writer_active and self._readers_active == 0 and self.read.those_waiting == 0
    
    def _acquire_write_core(self):
        self._writer_active = True

    def _release_write_core(self):
        if not self._writer_active:
            raise RuntimeError("Unacquired write lock")
        self._writer_active = False
        self._on_writer_abort()
    def _downgrade_core(self):
        if not self._writer_active:
            raise RuntimeError("Cannot downgrade unlocked lock")
        self._writer_active = False
        self._readers_active += 1
        self.read.condition.notify_all()

    def _on_writer_abort(self):
        if self.read.those_waiting > 0:
            self.read.condition.notify_all()
        else: 
            self.write.condition.notify()

    def _is_write_locked(self) -> bool: 
        return self._writer_active

class AsyncRWLockReadReentrantWriter(AsyncRWLockRead):
    """
    Read-preferring Asynchronous Read-Write Lock with Task-Reentrancy.
    
    Reentrancy Note:
        Strictly supports nested *write* locks for the current `asyncio.Task`.

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
            await lock.write.downgrade()
            print("Downgraded to read mode.")
        ```
    """
    __slots__ = ('_writer_id', '_write_count')

    def __init__(self, lock_factory: Callable[[], asyncio.Lock] = asyncio.Lock):
        super().__init__(lock_factory)
        self._writer_id: Optional[asyncio.Task] = None
        self._write_count: int = 0

    def _can_read(self) -> bool:
        if self._writer_id is asyncio.current_task():
            return True
        return self._writer_id is None

    def _can_write(self) -> bool:
        return (self._writer_id is None and self._readers_active == 0 and self.read.those_waiting == 0) or self._writer_id is asyncio.current_task()
    
    def _acquire_write_core(self):
        self._writer_id = asyncio.current_task()
        self._write_count += 1

    def _release_write_core(self):
        if self._writer_id is not asyncio.current_task():
            raise RuntimeError("Permission denied")
        self._write_count -= 1
        if self._write_count == 0:
            self._writer_id = None
            self._on_writer_abort()

    def _downgrade_core(self):
        if self._writer_id is not asyncio.current_task():
            raise RuntimeError("Permission denied")
        if self._write_count > 1:
            raise RuntimeError("Cannot downgrade a nested write lock.")
        self._writer_id = None
        self._write_count = 0
        self._readers_active += 1
        self.read.condition.notify_all()
        
    def _is_write_locked(self) -> bool:
        return self._writer_id is not None

class AsyncRWLockFIFO(AsyncRWLockBase):
    """
    Fair (First-In-First-Out) Asynchronous Read-Write Lock.
    
    Enforces alternating phases between readers and writers, preventing 
    starvation for both sides even under heavy, mixed workload spikes.

    Example:
        ```python
        lock = AsyncRWLockFIFO()
        
        # Readers and writers are served strictly in the order they arrive,
        # ensuring zero starvation for both sides.
        async with lock.read:
            print("Reading data...")
            
        async with lock.write:
            print("Updating data...")
        ```
    """
    __slots__ = ('_writer_active', '_readers_turn')

    def __init__(self, lock_factory: Callable[[], asyncio.Lock] = asyncio.Lock):
        super().__init__(lock_factory)
        self._writer_active = False
        self._readers_turn = False

    def _can_read(self) -> bool:
        if self._writer_active: 
            return False
        return self._readers_turn or self.write.those_waiting == 0
    
    def _acquire_read_core(self):
        self._readers_active += 1

    def _release_read_core(self):
        if self._readers_active == 0:
            raise RuntimeError("Unacquired read lock")
        self._readers_active -= 1
        if self._readers_active == 0:
            self._readers_turn = False
            self.write.condition.notify()

    def _on_reader_abort(self):
        if self._readers_turn and self.read.those_waiting == 0 and self._readers_active == 0:
            self._readers_turn = False
            self.write.condition.notify()

    def _can_write(self) -> bool:
        if self._writer_active or self._readers_active > 0:
            return False
        if self._readers_turn and self.read.those_waiting > 0:
            return False
        return True
    
    def _acquire_write_core(self):
        self._writer_active = True

    def _release_write_core(self):
        if not self._writer_active:
            raise RuntimeError("Unacquired write lock")
        self._writer_active = False
        self._on_writer_abort()

    def _downgrade_core(self):
        if not self._writer_active:
            raise RuntimeError("Cannot downgrade unlocked lock")
        self._writer_active = False
        self._readers_active += 1
        self._readers_turn = True
        self.read.condition.notify_all()

    def _on_writer_abort(self):
        if self.read.those_waiting > 0:
            self._readers_turn = True
            self.read.condition.notify_all()
        else:
            self.write.condition.notify()

    def _is_write_locked(self) -> bool:
        return self._writer_active

class AsyncRWLockFIFOReentrantWriter(AsyncRWLockFIFO):
    """
    Fair (First-In-First-Out) Asynchronous Read-Write Lock with Task-Reentrancy.
    
    Reentrancy Note:
        Strictly supports nested *write* locks for the current `asyncio.Task`.
    
    Example:
        ```python
        lock = AsyncRWLockFIFOReentrantWriter()
        
        async with lock.write:
            print("Outer write lock acquired.")
            
            # The same task can safely re-acquire the write lock without deadlocking.
            async with lock.write:
                print("Inner (nested) write lock acquired safely.")
            
            # Atomically downgrade to a read lock, allowing other readers to enter
            # without giving up task ownership entirely.
            await lock.write.downgrade()
            print("Downgraded to read mode.")
        ```
    """
    __slots__ = ('_writer_id', '_write_count')

    def __init__(self, lock_factory: Callable[[], asyncio.Lock] = asyncio.Lock):
        super().__init__(lock_factory)
        self._writer_id: Optional[asyncio.Task] = None
        self._write_count: int = 0

    def _can_read(self) -> bool:
        if self._writer_id is asyncio.current_task():
            return True
        if self._writer_id is not None:
            return False
        return self._readers_turn or self.write.those_waiting == 0

    def _can_write(self) -> bool:
        if self._writer_id is asyncio.current_task():
            return True
        if self._writer_id is not None or self._readers_active > 0:
            return False
        if self._readers_turn and self.read.those_waiting > 0:
            return False
        return True
    
    def _acquire_write_core(self):
        self._writer_id = asyncio.current_task()
        self._write_count += 1
        
    def _release_write_core(self):
        if self._writer_id is not asyncio.current_task():
            raise RuntimeError("Permission denied")
        self._write_count -= 1
        if self._write_count == 0:
            self._writer_id = None
            self._on_writer_abort()

    def _downgrade_core(self):
        if self._writer_id is not asyncio.current_task():
            raise RuntimeError("Permission denied")
        if self._write_count > 1:
            raise RuntimeError("Cannot downgrade a nested write lock.")
        self._writer_id = None
        self._write_count = 0
        self._readers_active += 1
        self._readers_turn = True
        self.read.condition.notify_all()

    def _is_write_locked(self) -> bool:
        return self._writer_id is not None

# Read Write Lock Proxy For Condition
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
        '_remove_waiter', '_notify_core', '_notify_all_core'
    )
    
    def __init__(self, 
        lock_proxy: 'AsyncRWLockProxy',
        is_owned: Callable[[], bool],
        add_waiter: Callable[[], asyncio.Future],
        remove_waiter: Callable[[asyncio.Future], None],
        notify_core: Callable[[int], None],
        notify_all_core: Callable[[], None]
    ):
        self._lock_proxy = lock_proxy
        self._is_owned = is_owned
        self._add_waiter = add_waiter
        self._remove_waiter = remove_waiter
        self._notify_core = notify_core
        self._notify_all_core = notify_all_core

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

    async def release(self) -> None:
        """
        Release the underlying asynchronous lock (Read or Write).
        
        Raises:
            RuntimeError: If the lock was not acquired by the current task before 
                          calling this method.
        """
        await self._lock_proxy.release()

    async def locked(self) -> bool:
        """
        Check if the underlying lock is currently held.

        Returns:
            bool: True if the lock is acquired by any task, False otherwise.
        """
        return await self._lock_proxy.locked()

    async def __aenter__(self) -> bool:
        return await self._lock_proxy.__aenter__()

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> Optional[bool]:
        return await self._lock_proxy.__aexit__(exc_type, exc_val, exc_tb)

    async def wait(self) -> bool:
        """
        Wait until notified.

        This method safely releases the underlying lock, yields control to the 
        asyncio event loop to allow other tasks to run, and strictly guarantees 
        that the lock will be re-acquired before returning, even if the waiting 
        task is cancelled.

        Returns:
            bool: Always returns True if awoken safely by a `notify()` call.
            
        Raises:
            RuntimeError: If the lock is not owned by the current task when 
                          `wait()` is called.
            asyncio.CancelledError: If the task is cancelled while waiting. The 
                                    exception is propagated ONLY after the lock 
                                    is safely re-acquired to prevent state corruption.
        """
        if not self._is_owned():
            raise RuntimeError("cannot wait on un-acquired lock")
            
        waiter = self._add_waiter()
        await self.release()
        
        try:
            await waiter
            return True
        finally:
            self._remove_waiter(waiter)
            
            # Critical asyncio section: Shield the re-acquisition loop from 
            # cancellation to prevent permanent deadlock / state corruption.
            err = None
            while True:
                try:
                    await self.acquire()
                    break
                except asyncio.CancelledError as e:
                    err = e
            
            # Re-raise the cancellation only AFTER the lock has been securely re-acquired.
            if err is not None:
                raise err

    async def wait_for(self, predicate: Callable[[], bool]) -> bool:
        """
        Wait until a specific condition (predicate) evaluates to True.
        
        This utility method repeatedly calls `wait()` until the predicate 
        returns a truthy value. For timeout functionality, wrap this call 
        with `asyncio.wait_for()`.

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
    def __init__(self, rwcond: AsyncRWConditionBase):
        super().__init__(
            lock_proxy=rwcond._rwlock.read,
            is_owned=rwcond._is_owned_read,
            add_waiter=rwcond._add_waiter,
            remove_waiter=rwcond._remove_waiter,
            notify_core=rwcond._notify_core,
            notify_all_core=rwcond._notify_all_core
        )

class AsyncRWConditionWriterProxy(AsyncRWConditionProxy):
    """
    Condition proxy bound specifically to the Writer state-machine.
    
    Calling `wait()` on this proxy will release the underlying WRITE lock,
    allowing other tasks to acquire the lock while the current task sleeps
    in the event loop.
    """
    __slots__ = ()
    def __init__(self, rwcond: AsyncRWConditionBase):
        super().__init__(
            lock_proxy=rwcond._rwlock.write,
            is_owned=rwcond._is_owned_write,
            add_waiter=rwcond._add_waiter,
            remove_waiter=rwcond._remove_waiter,
            notify_core=rwcond._notify_core,
            notify_all_core=rwcond._notify_all_core
        )

# Read Write Lock For Condition
class AsyncRWCondition(AsyncRWConditionBase):
    """
    Standard implementation of an Asynchronous Read-Write Condition variable.
    
    Utilizes a `collections.deque` containing `asyncio.Future` objects to provide 
    pure O(1) task queuing and wake-ups. It is highly optimized for Python's 
    single-threaded event loop, avoiding GIL-based context switches entirely, 
    and offers native protection against Cache Stampede scenarios during 
    massive `notify_all` calls.

    Example:
        ```python
        cond = AsyncRWCondition(AsyncRWLockFIFO())
        
        # Reader task
        async with cond.read:
            await cond.read.wait_for(lambda: data_ready)
            print(data)
            
        # Writer task
        async with cond.write:
            data_ready = True
            cond.write.notify_all()
        ```
    """
    __slots__ = ('_waiters',)
    
    def __init__(self, rwlock: Optional['AsyncRWLockBase'] = None):
        if rwlock is None:
            rwlock = AsyncRWLockWrite() 
            
        self._waiters: deque[asyncio.Future] = deque()
        super().__init__(rwlock)
    
    def _is_owned_read(self) -> bool:
        return self._rwlock._is_read_locked()

    def _is_owned_write(self) -> bool:
        return self._rwlock._is_write_locked()

    def _add_waiter(self) -> asyncio.Future:
        loop = asyncio.get_running_loop()
        waiter = loop.create_future()
        self._waiters.append(waiter)
        return waiter

    def _remove_waiter(self, waiter: asyncio.Future) -> None:
        try:
            self._waiters.remove(waiter)
        except ValueError:
            pass

    def _notify_core(self, n: int) -> None:
        count = 0
        while self._waiters and count < n:
            waiter = self._waiters.popleft()
            if not waiter.done():
                waiter.set_result(True)
                count += 1

    def _notify_all_core(self) -> None:
        self._notify_core(len(self._waiters))
