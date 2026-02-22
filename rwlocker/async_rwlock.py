"""
Advanced Asynchronous Read-Write Lock (AsyncRWLock) Concurrency Primitives.

This module provides highly optimized, state-machine-based Read-Write locks
designed specifically for Python's `asyncio` event loop. It guarantees safe
task scheduling, cancellation safety, and eliminates thundering herd problems.

Architecture Notes:
    - **Smart Proxies**: The locks are interacted with via `.read` and `.write` 
      proxy objects. The writer proxy acts as a "Smart Proxy" that can transparently 
      handle its release even if the lock was dynamically downgraded to a read lock.
    - **Task-Based Tracking**: SafeWriter locks and downgrade operations use 
      `asyncio.current_task()` as a C-level pointer for O(1) identity tracking.
    - **Circular References**: `AsyncRWLockBase` holds references to its proxies, 
      and proxies back to the base. This circular dependency is resolved safely by 
      Python's cyclic Garbage Collector. Do not use `__del__` for cleanup.
    - **Cancellation Safety**: The `acquire` loop is fully resilient to `CancelledError`. 
      If a task is cancelled while waiting, the lock safely aborts the attempt and 
      notifies other waiting tasks without corrupting the state.
"""
import asyncio
from abc import ABC, abstractmethod
from typing import Callable, Protocol, Optional
from types import TracebackType

__all__ = (
    'AsyncLockable', 'AsyncLockDowngradable', 'AsyncRWLockBase', 
    'AsyncRWLockProxy', 'AsyncRWLockReaderProxy', 'AsyncRWLockWriterProxy',
    'AsyncRWLockWrite', 'AsyncRWLockWriteSafeWriter', 
    'AsyncRWLockRead', 'AsyncRWLockReadSafeWriter',
    'AsyncRWLockFIFO', 'AsyncRWLockFIFOSafeWriter'
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

class AsyncRWLockWriteSafeWriter(AsyncRWLockWrite):
    """
    Write-preferring Asynchronous Read-Write Lock with Task-Reentrancy.
    
    Reentrancy Note:
        Strictly supports nested *write* operations for the same `asyncio.Task`.
        It does NOT implicitly grant read locks. Reentrancy is resolved via 
        O(1) memory pointer comparison (`is` operator) of the asyncio Task.
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

class AsyncRWLockReadSafeWriter(AsyncRWLockRead):
    """
    Read-preferring Asynchronous Read-Write Lock with Task-Reentrancy.
    
    Reentrancy Note:
        Strictly supports nested *write* locks for the current `asyncio.Task`.
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

class AsyncRWLockFIFOSafeWriter(AsyncRWLockFIFO):
    """
    Fair (First-In-First-Out) Asynchronous Read-Write Lock with Task-Reentrancy.
    
    Reentrancy Note:
        Strictly supports nested *write* locks for the current `asyncio.Task`.
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
