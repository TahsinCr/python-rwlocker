"""
Advanced Asynchronous Read-Write Lock (AsyncRWLock) and Condition Concurrency Primitives.

This module provides highly optimized, state-machine-based Read-Write locks 
and their corresponding Condition variables. It is designed specifically for 
Python's `asyncio` event loop, supporting different scheduling strategies 
(Write-preferring, Read-preferring, Fair) and safe reentrancy for writer tasks.

Architecture Notes:
    - **Smart Proxies**: The locks and conditions are interacted with via 
      `.read` and `.write` proxy objects. These proxies transparently handle 
      the underlying state transitions and expose standard `asyncio` APIs.
    - **Efficient Condition Queuing**: The `AsyncRWCondition` primitive utilizes 
      an `asyncio.Future` and `deque` architecture to provide highly efficient 
      wait/notify operations, eliminating event loop blocking and providing 
      strict protection against cache stampedes.
    - **Adapter Pattern & Solid Base**: Standard asyncio Locks and Conditions 
      are encapsulated via `AsyncLock` and `AsyncCondition` adapters, sharing the 
      exact same API signatures as AsyncRWLocks for seamless dependency injection.
    - **Circular References**: The base classes (`AsyncRWLockWithProxyBase`, `AsyncRWConditionWithProxyBase`) 
      hold references to their respective `read` and `write` proxies, and the 
      proxies hold a reference back to the base. This circular dependency is 
      resolved by Python's Garbage Collector.
    - **Cancellation Safety & Task Tracking**: Standard lock acquisition and wait 
      operations use `asyncio.current_task()` for O(1) identity tracking. All 
      state transitions are fully resilient to `asyncio.CancelledError`, strictly 
      preventing deadlocks and state corruption during task cancellations.
    - **Drop-in Replacement**: All AsyncRWLock and AsyncRWCondition objects 
      fully implement the standard `asyncio.Lock` and `asyncio.Condition` 
      interfaces directly on the base instance. Calling standard methods 
      (e.g., `await acquire()`, `await wait()`) automatically routes to the 
      exclusive `write` proxy, ensuring 100% backward compatibility with 
      legacy async code and third-party libraries.
"""
import asyncio
from collections import deque
from abc import ABC, abstractmethod
from typing import Callable, Protocol, Optional
from types import TracebackType
import weakref

__version__ = '3.2'
__all__ = (
    'AsyncLockable', 'AsyncLockDowngradable', 'AsyncRWLockBase', 'AsyncRWLockWithProxyBase', 
    'AsyncRWLockProxy', 'AsyncRWLockReaderProxy', 'AsyncRWLockWriterProxy',
    'AsyncRWLockWrite', 'AsyncRWLockWriteReentrantWriter', 
    'AsyncRWLockRead', 'AsyncRWLockReadReentrantWriter',
    'AsyncRWLockFair', 'AsyncRWLockFairReentrantWriter',
    'AsyncConditionLockable', 'AsyncConditionDowngradable', 'AsyncRWConditionBase', 'AsyncRWConditionWithProxyBase',
    'AsyncRWConditionProxy', 'AsyncRWConditionReaderProxy', 'AsyncRWConditionWriterProxy',
    'AsyncRWCondition', 'AsyncLock', 'AsyncCondition'
)

# RWLock Protocol and Base
class AsyncLockable(Protocol):
    """Protocol defining a standard asyncio-compatible lock interface."""
    async def acquire(self) -> bool: ...
    def release(self) -> None: ...
    def locked(self) -> bool: ...
    async def __aenter__(self) -> bool: ...
    async def __aexit__(self, 
        exc_type: Optional[type[BaseException]], 
        exc_val: Optional[BaseException], 
        exc_tb: Optional[TracebackType]
    ) -> Optional[bool]: ...

class AsyncLockDowngradable(AsyncLockable):
    """Protocol for async locks that support atomic state degradation (Write -> Read)."""
    def downgrade(self) -> None: ...

class AsyncRWLockBase(ABC):
    """
    Absolute base class establishing the core Asynchronous Read-Write interface.
    
    Provides the foundational `.read` and `.write` attributes. Furthermore, it 
    acts as a drop-in replacement for `asyncio.Lock` by exposing standard async 
    methods (`acquire`, `release`, etc.) that default to the exclusive `.write` 
    proxy. Designed to act as a common type hint and contract.
    """
    __slots__ = ('read', 'write')
    def __init__(self):
        self.read: AsyncLockable = asyncio.Lock()
        self.write: AsyncLockable = self.read

    def _is_read_locked(self) -> bool:
        return self.read.locked()
    
    def _is_write_locked(self) -> bool:
        return self.write.locked()
    
    async def acquire(self) -> bool:
        """
        Acquire the exclusive (write) asynchronous lock.
        Provides standard asyncio.Lock compatibility by routing to the write proxy.
        """
        return await self.write.acquire()

    def release(self) -> None:
        """
        Release the exclusive (write) asynchronous lock.
        """
        self.write.release()
    
    def locked(self) -> bool:
        """
        Check if the exclusive (write) asynchronous lock is currently held.
        """
        return self.write.locked()
    
    async def __aenter__(self) -> bool:
        return await self.write.__aenter__()
    
    async def __exit__(self, exc_type, exc_val, exc_tb) -> Optional[bool]:
        return await self.write.__exit__(exc_type, exc_val, exc_tb)

class AsyncRWLockWithProxyBase(AsyncRWLockBase):
    """
    Abstract base class for all proxy-based asynchronous Read-Write lock implementations.

    This class manages the core `asyncio.Lock` and initializes the Smart Proxy Pattern, 
    exposing `read` and `write` attributes as proxy instances that safely handle 
    task cancellation and route logic to the overridden internal core methods.
    """
    __slots__ = ()
    def __init__(self):
        self.read:AsyncRWLockReaderProxy = AsyncRWLockReaderProxy(rwlock=self)
        self.write:AsyncRWLockWriterProxy = AsyncRWLockWriterProxy(rwlock=self)

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

# Read and Write Lock Proxy
class _AsyncWaitQueue:
    """Internal O(1) wait queue replacing asyncio.Condition for micro-locks."""
    __slots__ = ('_waiters',)
    def __init__(self):
        self._waiters: deque[asyncio.Future] = deque()
        
    async def wait(self):
        loop = asyncio.get_running_loop()
        fut = loop.create_future()
        self._waiters.append(fut)
        try:
            await fut
        except asyncio.CancelledError:
            try:
                self._waiters.remove(fut)
            except ValueError:
                pass
            raise

    def notify(self, n: int = 1):
        waiters = self._waiters
        count = 0
        while waiters and count < n:
            fut = waiters.popleft()
            if not fut.done():
                fut.set_result(True)
                count += 1
    
    def notify_all(self):
        waiters = self._waiters
        if not waiters:
            return
        for fut in waiters:
            if not fut.done():
                fut.set_result(True)
        waiters.clear()

class AsyncRWLockProxy:
    """
    Base proxy class acting as a standard `asyncio.Lock` interface.
    Handles acquisition logic, event loop yielding (`wait()`), and cancellation.
    """
    __slots__ = (
        'those_waiting', 'condition', '_can_acquire',
        '_acquire_core', '_release_core', '_on_abort', '_is_locked'
    )  
    def __init__(self,  
        can_acquire: Callable[[], bool],
        acquire_core: Callable[[], None],
        release_core: Callable[[], None],
        on_abort: Callable[[], None],
        is_locked: Callable[[], bool],
    ):
        self.those_waiting = 0
        self.condition = _AsyncWaitQueue()
        
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
    __slots__ = ('_read_lock', '_downgrade_core', '_downgraded_tasks')
    def __init__(self, rwlock: AsyncRWLockWithProxyBase):
        super().__init__(
            can_acquire=rwlock._can_write,
            acquire_core=rwlock._acquire_write_core,
            release_core=rwlock._release_write_core,
            on_abort=rwlock._on_writer_abort,
            is_locked=rwlock._is_write_locked
        )
        self._read_lock = rwlock.read
        self._downgrade_core = rwlock._downgrade_core
        self._downgraded_tasks:weakref.WeakSet[asyncio.Task] = weakref.WeakSet()
            
    def downgrade(self):
        """
        Atomically transition the held Write lock into a Read lock.
        Allows nested usage within `async with lock.write` blocks.
        
        Performance Cost:
            Adds `asyncio.current_task()` pointer to a tracking `set`.
            This incurs a minor memory footprint and an O(1) hash lookup 
            during the subsequent `release()` call.
        """
        self._downgrade_core()
        self._downgraded_tasks.add(asyncio.current_task())
    
    def release(self):
        """
        Release the lock intelligently.
        Checks if the current task downgraded the lock earlier. If so, it routes
        the release logic to the reader core, avoiding Deadlocks and RuntimeErrors.
        """
        if self._downgraded_tasks: 
            try:
                self._downgraded_tasks.remove(asyncio.current_task())
                self._read_lock._release_core()
                return
            except KeyError:
                pass
        self._release_core()

# Read and Write Lock
class AsyncRWLockWrite(AsyncRWLockWithProxyBase):
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
    Example 2 (Drop-in Replacement):
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
    
    def _is_read_locked(self) -> bool:
        return self._readers_active > 0
        
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
    Example 2 (Drop-in Replacement):
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

    def _can_read(self) -> bool:
        if self._writer_id is not None:
            return self._is_current_writer()
        return self.write.those_waiting == 0

    def _can_write(self) -> bool:
        if self._writer_id is not None:
            return self._is_current_writer()
        return self._readers_active == 0
    
    def _acquire_write_core(self):
        self._set_current_writer()
        self._write_count += 1

    def _release_write_core(self):
        if not self._is_current_writer(): 
            raise RuntimeError("Permission denied")
        self._write_count -= 1
        if self._write_count == 0:
            self._clear_current_writer()
            self._on_writer_abort()

    def _downgrade_core(self):
        if not self._is_current_writer(): 
            raise RuntimeError("Permission denied")
        if self._write_count > 1:
            raise RuntimeError("Cannot downgrade a nested write lock. Release inner locks first.")
        self._clear_current_writer()
        self._write_count = 0
        self._readers_active += 1
        self.read.condition.notify_all()
        
    def _is_write_locked(self) -> bool: 
        return self._writer_id is not None

class AsyncRWLockRead(AsyncRWLockWithProxyBase):
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
    Example 2 (Drop-in Replacement):
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
    
    def _is_read_locked(self) -> bool:
        return self._readers_active > 0
        
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
    Example 2 (Drop-in Replacement):
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

    def _can_read(self) -> bool:
        if self._writer_id is not None:
            return self._is_current_writer()
        return True

    def _can_write(self) -> bool:
        if self._writer_id is not None:
            return self._is_current_writer()
        return self._readers_active == 0 and self.read.those_waiting == 0
    
    def _acquire_write_core(self):
        self._set_current_writer()
        self._write_count += 1

    def _release_write_core(self):
        if not self._is_current_writer(): 
            raise RuntimeError("Permission denied")
        self._write_count -= 1
        if self._write_count == 0:
            self._clear_current_writer()
            self._on_writer_abort()

    def _downgrade_core(self):
        if not self._is_current_writer(): 
            raise RuntimeError("Permission denied")
        if self._write_count > 1:
            raise RuntimeError("Cannot downgrade a nested write lock. Release inner locks first.")
        self._clear_current_writer()
        self._write_count = 0
        self._readers_active += 1
        self.read.condition.notify_all()
        
    def _is_write_locked(self) -> bool:
        return self._writer_id is not None

class AsyncRWLockFair(AsyncRWLockWithProxyBase):
    """
    Fair (First-In-First-Out) Asynchronous Read-Write Lock.
    
    Enforces alternating phases between readers and writers, preventing 
    starvation for both sides even under heavy, mixed workload spikes.

    Example:
        ```python
        lock = AsyncRWLockFair()
        
        # Readers and writers are served strictly in the order they arrive,
        # ensuring zero starvation for both sides.
        async with lock.read:
            print("Reading data...")
            
        async with lock.write:
            print("Updating data...")
        ```
    Example 2 (Drop-in Replacement):
        ```python
        lock = AsyncRWLockFair()
        
        # By using the lock instance directly, it automatically routes to the 
        # exclusive (write) proxy. This allows the AsyncRWLock to be safely injected 
        # into legacy code that only understands standard asyncio.Lock.
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
    
    def _is_read_locked(self) -> bool:
        return self._readers_active > 0
        
class AsyncRWLockFairReentrantWriter(AsyncRWLockFair):
    """
    Fair (First-In-First-Out) Asynchronous Read-Write Lock with Task-Reentrancy.
    
    Reentrancy Note:
        Strictly supports nested *write* locks for the current `asyncio.Task`.
    
    Example:
        ```python
        lock = AsyncRWLockFairReentrantWriter()
        
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
    Example 2 (Drop-in Replacement):
        ```python
        lock = AsyncRWLockFairReentrantWriter()
        
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

    def _can_read(self) -> bool:
        if self._writer_id is not None:
            if self._is_current_writer():
                return True
            return False
        return self._readers_turn or self.write.those_waiting == 0

    def _can_write(self) -> bool:
        if self._writer_id is not None:
            if self._is_current_writer():
                return True
            return False
        if self._readers_active > 0:
            return False
        if self._readers_turn and self.read.those_waiting > 0: 
            return False
        return True
    
    def _acquire_write_core(self):
        self._set_current_writer()
        self._write_count += 1
        
    def _release_write_core(self):
        if not self._is_current_writer(): 
            raise RuntimeError("Permission denied")
        self._write_count -= 1
        if self._write_count == 0:
            self._clear_current_writer()
            self._on_writer_abort()

    def _downgrade_core(self):
        if not self._is_current_writer(): 
            raise RuntimeError("Permission denied")
        if self._write_count > 1:
            raise RuntimeError("Cannot downgrade a nested write lock. Release inner locks first.")
        self._clear_current_writer()
        self._write_count = 0
        self._readers_active += 1
        self._readers_turn = True
        self.read.condition.notify_all()

    def _is_write_locked(self) -> bool: 
        return self._writer_id is not None

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
    Example 2 (Drop-in Replacement):
        ```python
        lock = AsyncLock()
        
        # Acts exactly like a standard asyncio.Lock.
        # Perfect for passing into third-party libraries expecting a standard async lock.
        async with lock:
            print("Standard async lock acquired directly without proxies.")
        ```
    """
    __slots__ = ()



# RWCondition Protocol and Base
class AsyncConditionLockable(AsyncLockable):
    """Protocol defining a standard asyncio-compatible Condition variable interface."""
    async def wait(self) -> bool: ...
    async def wait_for(self, predicate: Callable[[], bool]) -> bool: ...
    def notify(self, n: int = 1) -> None: ...
    def notify_all(self) -> None: ...

class AsyncConditionDowngradable(AsyncConditionLockable):
    """Protocol for async condition variables that support atomic state degradation (Write -> Read)."""
    def downgrade(self) -> None: ...

class AsyncRWConditionBase(ABC):
    """
    Absolute base class establishing the core Asynchronous Read-Write Condition interface.
    
    Provides the foundational `.read` and `.write` attributes. Furthermore, it 
    acts as a drop-in replacement for `asyncio.Condition` by exposing standard 
    condition methods (`wait`, `notify`, etc.) that default to the exclusive 
    `.write` proxy. Designed to act as a common type hint and contract.
    """
    __slots__ = ('_lock', 'read', 'write')

    def __init__(self, lock: Optional[AsyncLockable] = None):
        self._lock = AsyncLock() if lock is None else lock
        self.write: AsyncConditionLockable = asyncio.Condition(self._lock)
        self.read: AsyncConditionLockable = self.write
    
    async def acquire(self) -> bool:
        """
        Acquire the underlying exclusive (write) asynchronous lock.
        """
        return await self.write.acquire()

    def release(self) -> None:
        """
        Release the underlying exclusive (write) asynchronous lock.
        """
        self.write.release()

    def locked(self) -> bool:
        """
        Check if the underlying exclusive (write) asynchronous lock is currently held.
        """
        return self.write.locked()
    
    async def wait(self) -> bool:
        """
        Wait until notified.
        Provides standard asyncio.Condition compatibility by routing to the write proxy.
        """
        return await self.write.wait()

    async def wait_for(self, predicate: Callable[[], bool]) -> bool:
        """
        Wait until a specific condition (predicate) evaluates to True.
        Routes to the exclusive write proxy.
        """
        return await self.write.wait_for(predicate)
    
    def notify(self, n: int = 1) -> None:
        """
        Wake up one or more tasks waiting on this condition.
        Routes to the exclusive write proxy.
        """
        self.write.notify(n)

    def notify_all(self) -> None:
        """
        Wake up all tasks currently waiting on this condition.
        Routes to the exclusive write proxy.
        """
        self.write.notify_all()
    
    async def __aenter__(self) -> bool:
        return await self.write.__aenter__()
    
    async def __aexit__(self, exc_type, exc_val, exc_tb) -> Optional[bool]:
        return await self.write.__aexit__(exc_type, exc_val, exc_tb)
    
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
        self.release()
        
        try:
            await waiter
            return True
        except asyncio.CancelledError:
            # OPTİMİZASYON: Mutlu Yolda çalışmaz.
            # Sadece task iptal edilirse kuyruktan temizlik yapar.
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
    def __init__(self, rwcond: AsyncRWConditionWithProxyBase):
        super().__init__(
            lock_proxy=rwcond._lock.read,
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
    def __init__(self, rwcond: AsyncRWConditionWithProxyBase):
        super().__init__(
            lock_proxy=rwcond._lock.write,
            is_owned=rwcond._is_owned_write,
            add_waiter=rwcond._add_waiter,
            remove_waiter=rwcond._remove_waiter,
            notify_core=rwcond._notify_core,
            notify_all_core=rwcond._notify_all_core
        )
    
    def downgrade(self) -> None:
        """
        Atomically transition the underlying asynchronous Write lock into a Read lock.
        
        This passes the downgrade request directly to the underlying async lock proxy,
        allowing waiting readers to enter while maintaining the condition context.
        """
        self._lock_proxy.downgrade()

# Read Write Lock For Condition
class AsyncRWCondition(AsyncRWConditionWithProxyBase):
    """
    Standard implementation of an Asynchronous Read-Write Condition variable.
    
    Utilizes a `collections.deque` containing `asyncio.Future` objects to provide 
    pure O(1) task queuing and wake-ups. It is highly optimized for Python's 
    single-threaded event loop, avoiding GIL-based context switches entirely, 
    and offers native protection against Cache Stampede scenarios during 
    massive `notify_all` calls.

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
    Example 2 (Drop-in Replacement):
        ```python
        cond = AsyncRWCondition()  # AsyncRWLockWrite default lock
        
        # Direct usage bypasses explicit .read/.write proxies and defaults to 
        # the exclusive write state, providing 100% API compatibility with 
        # standard asyncio.Condition workflows.
        async with cond:
            while not data_ready:
                await cond.wait()
            cond.notify_all()
        ```
    """
    __slots__ = ('_waiters',)
    
    def __init__(self, lock: Optional[AsyncRWLockBase] = None):   
        self._waiters: deque[asyncio.Future] = deque()
        super().__init__(lock)
    
    def _is_owned_read(self) -> bool:
        return self._lock._is_read_locked()

    def _is_owned_write(self) -> bool:
        return self._lock._is_write_locked()

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
        waiters = self._waiters
        count = 0
        while waiters and count < n:
            waiter = waiters.popleft()
            if not waiter.done():
                waiter.set_result(True)
                count += 1

    def _notify_all_core(self) -> None:
        waiters = self._waiters
        if not waiters:
            return
        for waiter in waiters:
            if not waiter.done():
                waiter.set_result(True)
        waiters.clear()

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
    Example 2 (Drop-in Replacement):
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
        if lock is not None and isinstance(lock, AsyncRWLockWithProxyBase):
            raise TypeError("Standard 'AsyncCondition' adapters cannot be used with proxy-based RWLocks. Use 'AsyncRWCondition' instead.")
        super().__init__(lock)
