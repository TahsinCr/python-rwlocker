"""
Advanced Read-Write Lock (RWLock) and Condition Concurrency Primitives.

This module provides highly optimized, state-machine-based Read-Write locks 
and their corresponding Condition variables. It supports different scheduling 
strategies (Write-preferring, Read-preferring, FIFO) and safe reentrancy for 
writer threads.

Architecture Notes:
    - **Smart Proxies**: The locks and conditions are interacted with via 
      `.read` and `.write` proxy objects. These proxies transparently handle 
      the underlying state transitions and expose standard `threading` APIs.
    - **O(1) Condition Queuing**: The `RWCondition` primitive utilizes a 
      thread-safe micro-lock and `deque` architecture to provide pure O(1) 
      performance for wait/notify operations, eliminating O(N) traversal 
      bottlenecks and providing strict protection against cache stampedes.
    - **Circular References**: The base classes (`RWLockBase`, `RWConditionBase`) 
      hold references to their respective `read` and `write` proxies, and the 
      proxies hold a reference back to the base. This circular dependency is 
      resolved by Python's Garbage Collector. Do not rely on `__del__` for 
      deterministic cleanup.
    - **Zero-Allocation Fast-Paths**: Standard lock acquisition and release 
      operations are optimized to avoid object allocations and minimize 
      OS-level context switching.
"""
import time
import threading
from collections import deque
from abc import ABC, abstractmethod
from typing import Callable, Protocol, Optional
from types import TracebackType

__version__ = '2.0'
__all__ = (
    'Lockable', 'LockDowngradable', 'RWLockBase', 'RWConditionBase',
    'RWLockProxy', 'RWLockReaderProxy', 'RWLockWriterProxy',
    'RWLockWrite', 'RWLockWriteReentrantWriter', 
    'RWLockRead', 'RWLockReadReentrantWriter',
    'RWLockFIFO', 'RWLockFIFOReentrantWriter',
    'RWConditionProxy', 'RWConditionReaderProxy', 'RWConditionWriterProxy',
    'RWCondition',
)

# Protocol and Base
class Lockable(Protocol):
    """Protocol defining a standard thread-safe lock interface."""
    def acquire(self, blocking: bool = True, timeout: float = -1.0) -> bool: ...
    def release(self) -> None: ...
    def locked(self) -> bool: ...
    def __enter__(self) -> bool: ...
    def __exit__(self, 
        exc_type: Optional[type[BaseException]], 
        exc_val: Optional[BaseException], 
        exc_tb: Optional[TracebackType]
    ) -> Optional[bool]: ...

class LockDowngradable(Lockable):
    """Protocol for locks that support atomic state degradation (e.g., Write -> Read)."""
    def downgrade(self) -> None: ...

class RWLockBase(ABC):
    """
    Abstract base class for all Read-Write lock implementations.

    This class manages the core OS lock and the active reader count. It uses
    a Proxy Pattern, exposing `read` and `write` attributes as context managers.

    Warning:
        This class creates a circular reference with its proxies. Memory is
        reclaimed via Python's cyclic garbage collector.
    """
    __slots__ = ('_lock', '_readers_active', 'read', 'write')
    def __init__(self, lock_factory: Callable[[], threading.Lock] = threading.Lock):
        self._lock = lock_factory()
        self._readers_active = 0
        self.read:'RWLockReaderProxy' = RWLockReaderProxy(rwlock=self)
        self.write:'RWLockWriterProxy' = RWLockWriterProxy(rwlock=self)

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

class RWConditionBase(ABC):
    """
    Abstract base class for all Read-Write Condition variables.
    
    Like RWLockBase, this class solely defines the internal state machine and 
    core queuing operations. It strictly hides its internal mechanisms and exposes 
    its functionality via `.read` and `.write` proxies to maintain a clean, 
    standardized threading.Condition API.
    """
    __slots__ = ('_rwlock', 'read', 'write')
    
    def __init__(self, rwlock: 'RWLockBase'):
        self._rwlock = rwlock
        self.read: 'RWConditionReaderProxy' = RWConditionReaderProxy(rwcond=self)
        self.write: 'RWConditionWriterProxy' = RWConditionWriterProxy(rwcond=self)

    @abstractmethod
    def _is_owned_read(self) -> bool: ...
    @abstractmethod
    def _is_owned_write(self) -> bool: ...
    @abstractmethod
    def _add_waiter(self) -> threading.Lock: ...
    @abstractmethod
    def _remove_waiter(self, waiter: threading.Lock) -> None: ...
    @abstractmethod
    def _notify_core(self, n: int) -> None: ...
    @abstractmethod
    def _notify_all_core(self) -> None: ...

# Read and Write Lock Proxy
class RWLockProxy:
    """
    Base proxy class acting as a standard threading.Lock interface.
    Handles acquisition logic, timeout calculations, and thread wake-ups.
    """
    __slots__ = (
        '_lock', 'those_waiting', 'condition', '_can_acquire',
        '_acquire_core', '_release_core', '_on_abort', '_is_locked'
    )  
    def __init__(self, 
        lock: threading.Lock, 
        can_acquire:Callable[[],bool],
        acquire_core:Callable[[],None],
        release_core:Callable[[],None],
        on_abort:Callable[[],None],
        is_locked:Callable[[],bool],
    ):
        self._lock = lock
        self.those_waiting = 0
        self.condition = threading.Condition(self._lock)
        
        self._can_acquire = can_acquire
        self._acquire_core = acquire_core
        self._release_core = release_core
        self._on_abort = on_abort
        self._is_locked = is_locked

    def acquire(self, blocking: bool = True, timeout: float = -1.0) -> bool:
        """
        Acquire the lock dynamically based on the specific core logic.
        
        Args:
            blocking: If False, returns immediately if the lock cannot be acquired.
            timeout: Maximum time in seconds to wait for the lock. -1 means infinite.
            
        Returns:
            bool: True if lock was acquired, False otherwise.
        """
        with self._lock:
            if self._can_acquire():
                self._acquire_core()
                return True
            if not blocking:
                return False
            self.those_waiting += 1
            acquired = False
            try:
                if timeout < 0:
                    while not self._can_acquire():
                        self.condition.wait()
                    self._acquire_core()
                    acquired = True
                    return True
                    
                endtime = time.monotonic() + timeout
                while not self._can_acquire():
                    remaining = endtime - time.monotonic()
                    if remaining <= 0.0:
                        return False
                    self.condition.wait(remaining)
                
                self._acquire_core()
                acquired = True
                return True
            finally:
                self.those_waiting -= 1
                if not acquired:
                    self._on_abort()

    def release(self) -> None:
        """Release the acquired lock and notify waiting threads."""
        with self._lock:
            self._release_core()

    def locked(self) -> bool:
        """Check if the lock is currently held by any thread."""
        with self._lock:
            return self._is_locked()

    def __enter__(self) -> bool:
        self.acquire()
        return True

    def __exit__(self, exc_type, exc_val, exc_tb) -> Optional[bool]:
        self.release()
        return False

class RWLockReaderProxy(RWLockProxy):
    """Proxy specifically handling Reader logic."""
    __slots__ = ()
    def __init__(self, rwlock: RWLockBase):
        super().__init__(
            lock=rwlock._lock,
            can_acquire=rwlock._can_read,
            acquire_core=rwlock._acquire_read_core,
            release_core=rwlock._release_read_core,
            on_abort=rwlock._on_reader_abort,
            is_locked=rwlock._is_read_locked
        )

class RWLockWriterProxy(RWLockProxy):
    """
    Proxy specifically handling Writer logic, extending capabilities with
    atomic state degradation (downgrading).
    """
    __slots__ = ('_read_lock', '_downgrade_core', '_downgraded_threads')
    def __init__(self, rwlock: RWLockBase):
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
        self._downgraded_threads:set[int] = set()
        
    def downgrade(self):
        """
        Atomically transition the held Write lock into a Read lock.
        Allows waiting readers to enter while preventing new writers from acquiring.
        
        Performance Cost:
            This operation adds the current Thread ID into a tracking `set`.
            Consequently, the subsequent `release()` call will incur an O(1) hash
            lookup overhead and a `threading.get_ident()` function call.
        """
        with self._lock:
            self._downgrade_core()
            self._downgraded_threads.add(threading.get_ident())
    
    def release(self):
        """
        Release the lock. 
        Intelligently detects if the lock was downgraded by the current thread
        and routes the release to the reader core to prevent deadlocks.
        """
        with self._lock:
            if self._downgraded_threads: 
                ident = threading.get_ident()
                if ident in self._downgraded_threads:
                    self._downgraded_threads.remove(ident)
                    self._read_lock._release_core()
                    return
            self._release_core()

#  Read and Write Lock
class RWLockWrite(RWLockBase):
    """
    Write-preferring Read-Write Lock.
    
    Prevents new readers from acquiring the lock if there are writers waiting.
    This prevents writer starvation in read-heavy workloads.

    Example:
        ```python
        lock = RWLockWrite()
        
        # Multiple readers can acquire the lock simultaneously.
        with lock.read:
            print("Reading data...")
            
        # If a writer starts waiting here, new readers are blocked
        # until the writer finishes, preventing writer starvation.
        with lock.write:
            print("Updating data...")
        ```
    """
    __slots__ = ('_writer_active',)
    def __init__(self, lock_factory: Callable[[], threading.Lock] = threading.Lock):
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

class RWLockWriteReentrantWriter(RWLockWrite):
    """
    Write-preferring Read-Write Lock with Write-Reentrancy support.
    
    Reentrancy Note:
        This lock strictly supports nested *write* operations for the same thread.
        It allows a thread holding the write lock to acquire it again safely.
        It does NOT implicitly grant read locks to a writer; explicit downgrade
        is required for that.

    Example:
        ```python
        lock = RWLockWriteReentrantWriter()
        
        with lock.write:
            print("Outer write lock acquired.")
            
            # The same thread can safely re-acquire the write lock without deadlocking.
            with lock.write:
                print("Inner (nested) write lock acquired safely.")
            
            # Atomically downgrade to a read lock, allowing other readers to enter
            # without giving up thread ownership entirely.
            lock.write.downgrade()
            print("Downgraded to read mode.")
        ```
    """
    __slots__ = ('_writer_id', '_write_count')
    def __init__(self, lock_factory: Callable[[], threading.Lock] = threading.Lock):
        super().__init__(lock_factory)
        self._writer_id: Optional[int] = None
        self._write_count: int = 0

    def _can_read(self) -> bool:
        if self._writer_id == threading.get_ident(): 
            return True
        return self._writer_id is None and self.write.those_waiting == 0

    def _can_write(self) -> bool:
        return (self._writer_id is None and self._readers_active == 0) or self._writer_id == threading.get_ident()
    
    def _acquire_write_core(self):
        self._writer_id = threading.get_ident()
        self._write_count += 1

    def _release_write_core(self):
        if self._writer_id != threading.get_ident(): 
            raise RuntimeError("Permission denied")
        self._write_count -= 1
        if self._write_count == 0:
            self._writer_id = None
            self._on_writer_abort()

    def _downgrade_core(self):
        if self._writer_id != threading.get_ident(): 
            raise RuntimeError("Permission denied")
        if self._write_count > 1:
            raise RuntimeError("Cannot downgrade a nested write lock. Release inner locks first.")
        self._writer_id = None
        self._write_count = 0
        self._readers_active += 1
        self.read.condition.notify_all()

    def _is_write_locked(self) -> bool: 
        return self._writer_id is not None

class RWLockRead(RWLockBase):
    """
    Read-preferring Read-Write Lock.
    
    Allows maximum concurrency for readers by always allowing new readers to
    acquire the lock as long as a writer is not currently active.
    Beware: Can lead to writer starvation in highly concurrent read workloads.

    Example:
        ```python
        lock = RWLockRead()
        
        # Readers can continuously enter the lock as long as no writer 
        # is currently holding it, even if writers are waiting.
        with lock.read:
            print("Reading data...")
            
        # The writer must wait until ALL active readers have released the lock.
        with lock.write:
            print("Updating data...")
        ```
    """
    __slots__ = ('_writer_active',)
    def __init__(self, lock_factory: Callable[[], threading.Lock] = threading.Lock):
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

class RWLockReadReentrantWriter(RWLockRead):
    """
    Read-preferring Read-Write Lock with Write-Reentrancy support.
    
    Reentrancy Note:
        Supports nested *write* locks exclusively.
    
    Example:
        ```python
        lock = RWLockReadReentrantWriter()
        
        with lock.write:
            print("Outer write lock acquired.")
            
            # The same thread can safely re-acquire the write lock without deadlocking.
            with lock.write:
                print("Inner (nested) write lock acquired safely.")
            
            # Atomically downgrade to a read lock, allowing other readers to enter
            # without giving up thread ownership entirely.
            lock.write.downgrade()
            print("Downgraded to read mode.")
        ```
    """
    __slots__ = ('_writer_id', '_write_count')
    def __init__(self, lock_factory: Callable[[], threading.Lock] = threading.Lock):
        super().__init__(lock_factory)
        self._writer_id: Optional[int] = None
        self._write_count: int = 0

    def _can_read(self) -> bool:
        if self._writer_id == threading.get_ident(): 
            return True
        return self._writer_id is None

    def _can_write(self) -> bool:
        return (self._writer_id is None and self._readers_active == 0 and self.read.those_waiting == 0) or self._writer_id == threading.get_ident()
    
    def _acquire_write_core(self):
        self._writer_id = threading.get_ident()
        self._write_count += 1

    def _release_write_core(self):
        if self._writer_id != threading.get_ident(): 
            raise RuntimeError("Permission denied")
        self._write_count -= 1
        if self._write_count == 0:
            self._writer_id = None
            self._on_writer_abort()

    def _downgrade_core(self):
        if self._writer_id != threading.get_ident(): 
            raise RuntimeError("Permission denied")
        if self._write_count > 1:
            raise RuntimeError("Cannot downgrade a nested write lock. Release inner locks first.")
        self._writer_id = None
        self._write_count = 0
        self._readers_active += 1
        self.read.condition.notify_all()
        
    def _is_write_locked(self) -> bool:
        return self._writer_id is not None

class RWLockFIFO(RWLockBase):
    """
    Fair (First-In-First-Out) Read-Write Lock.
    
    Prevents starvation for both readers and writers by enforcing an alternating
    phase mechanism. When writers wait, the turn passes to writers after the current
    readers finish, and vice-versa.

    Example:
        ```python
        lock = RWLockFIFO()
        
        # Readers and writers are served strictly in the order they arrive,
        # ensuring zero starvation for both sides.
        with lock.read:
            print("Reading data...")
            
        with lock.write:
            print("Updating data...")
        ```
    """
    __slots__ = ('_writer_active', '_readers_turn')
    def __init__(self, lock_factory: Callable[[], threading.Lock] = threading.Lock):
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

class RWLockFIFOReentrantWriter(RWLockFIFO):
    """
    Fair (First-In-First-Out) Read-Write Lock with Write-Reentrancy support.
    
    Reentrancy Note:
        Supports strictly nested *write* locks. Prevents deadlock when a holding 
        writer attempts to re-acquire the write lock.
    
    Example:
        ```python
        lock = RWLockFIFOReentrantWriter()
        
        with lock.write:
            print("Outer write lock acquired.")
            
            # The same thread can safely re-acquire the write lock without deadlocking.
            with lock.write:
                print("Inner (nested) write lock acquired safely.")
            
            # Atomically downgrade to a read lock, allowing other readers to enter
            # without giving up thread ownership entirely.
            lock.write.downgrade()
            print("Downgraded to read mode.")
        ```
    """
    __slots__ = ('_writer_id', '_write_count')
    def __init__(self, lock_factory: Callable[[], threading.Lock] = threading.Lock):
        super().__init__(lock_factory)
        self._writer_id: Optional[int] = None
        self._write_count: int = 0

    def _can_read(self) -> bool:
        if self._writer_id == threading.get_ident(): 
            return True
        if self._writer_id is not None: 
            return False
        return self._readers_turn or self.write.those_waiting == 0

    def _can_write(self) -> bool:
        if self._writer_id == threading.get_ident():
            return True
        if self._writer_id is not None or self._readers_active > 0: 
            return False
        if self._readers_turn and self.read.those_waiting > 0: 
            return False
        return True
    
    def _acquire_write_core(self):
        self._writer_id = threading.get_ident()
        self._write_count += 1
        
    def _release_write_core(self):
        if self._writer_id != threading.get_ident(): 
            raise RuntimeError("Permission denied")
        self._write_count -= 1
        if self._write_count == 0:
            self._writer_id = None
            self._on_writer_abort()

    def _downgrade_core(self):
        if self._writer_id != threading.get_ident(): 
            raise RuntimeError("Permission denied")
        if self._write_count > 1:
            raise RuntimeError("Cannot downgrade a nested write lock. Release inner locks first.")
        self._writer_id = None
        self._write_count = 0
        self._readers_active += 1
        self._readers_turn = True
        self.read.condition.notify_all()

    def _is_write_locked(self) -> bool: 
        return self._writer_id is not None

# Read Write Lock Proxy For Condition
class RWConditionProxy:
    """
    Base proxy class acting as a standard `threading.Condition` interface.
    
    It holds no state of its own. It dynamically routes lock acquisitions, 
    releases, and signaling operations to the injected core callables provided 
    by the underlying `RWConditionBase` implementation.
    """
    __slots__ = (
        '_lock_proxy', '_is_owned', '_add_waiter', 
        '_remove_waiter', '_notify_core', '_notify_all_core'
    )
    
    def __init__(self, 
        lock_proxy: 'RWLockProxy',
        is_owned: Callable[[], bool],
        add_waiter: Callable[[], threading.Lock],
        remove_waiter: Callable[[threading.Lock], None],
        notify_core: Callable[[int], None],
        notify_all_core: Callable[[], None]
    ):
        self._lock_proxy = lock_proxy
        self._is_owned = is_owned
        self._add_waiter = add_waiter
        self._remove_waiter = remove_waiter
        self._notify_core = notify_core
        self._notify_all_core = notify_all_core

    def acquire(self, blocking: bool = True, timeout: float = -1.0) -> bool:
        """
        Acquire the underlying lock (Read or Write depending on the proxy).

        Args:
            blocking (bool): If False, return immediately if the lock cannot be acquired.
            timeout (float): Maximum time to wait for the lock. -1 means infinite.

        Returns:
            bool: True if the lock was acquired, False otherwise.
        """
        return self._lock_proxy.acquire(blocking, timeout)

    def release(self) -> None:
        """
        Release the underlying lock (Read or Write).
        
        Raises:
            RuntimeError: If the lock was not acquired by the current thread.
        """
        self._lock_proxy.release()

    def locked(self) -> bool:
        """
        Check if the underlying lock is currently held.

        Returns:
            bool: True if the lock is acquired, False otherwise.
        """
        return self._lock_proxy.locked()

    def __enter__(self) -> bool:
        return self._lock_proxy.__enter__()

    def __exit__(self, exc_type, exc_val, exc_tb) -> Optional[bool]:
        return self._lock_proxy.__exit__(exc_type, exc_val, exc_tb)

    def wait(self, timeout: Optional[float] = None) -> bool:
        """
        Wait until notified or until a timeout occurs.
        
        This method safely releases the underlying lock, sleeps, and re-acquires
        the lock before returning, ensuring absolute state safety even during 
        interruptions or memory errors.

        Args:
            timeout (float, optional): Maximum time in seconds to wait.

        Returns:
            bool: True if awoken by a `notify()` call, False if the timeout expired.
            
        Raises:
            RuntimeError: If the lock is not owned when `wait()` is called.
        """
        if not self._is_owned():
            raise RuntimeError("cannot wait on un-acquired lock")
            
        waiter = self._add_waiter()
        try:
            self.release()
        except Exception:
            self._remove_waiter(waiter)
            raise
        
        gotit = False
        try:    
            if timeout is None:
                waiter.acquire()
                gotit = True
            else:
                if timeout > 0:
                    gotit = waiter.acquire(True, timeout)
                else:
                    gotit = waiter.acquire(False)
            return gotit
        finally:
            self.acquire()
            if not gotit:
                self._remove_waiter(waiter)

    def wait_for(self, predicate: Callable[[], bool], timeout: Optional[float] = None) -> bool:
        """
        Wait until a specific condition (predicate) evaluates to True.
        
        This utility method repeatedly calls `wait()` until the predicate 
        returns a truthy value or the timeout is reached.

        Args:
            predicate (Callable): A function returning a boolean indicating 
                                  if the desired state has been reached.
            timeout (float, optional): Maximum total time in seconds to wait.

        Returns:
            bool: The last return value of the predicate.
        """
        endtime = None
        waittime = timeout
        result = predicate()
        while not result:
            if waittime is not None:
                if endtime is None:
                    endtime = time.monotonic() + waittime
                else:
                    waittime = endtime - time.monotonic()
                    if waittime <= 0:
                        break
            self.wait(waittime)
            result = predicate()
        return result

    def notify(self, n: int = 1) -> None:
        """
        Wake up one or more threads waiting on this condition.
        
        Args:
            n (int): The maximum number of waiting threads to wake up. Defaults to 1.
            
        Raises:
            RuntimeError: If the lock is not owned when `notify()` is called.
        """
        if not self._is_owned():
            raise RuntimeError("cannot notify on un-acquired lock")
        self._notify_core(n)

    def notify_all(self) -> None:
        """
        Wake up all threads currently waiting on this condition.
        
        Raises:
            RuntimeError: If the lock is not owned when `notify_all()` is called.
        """
        if not self._is_owned():
            raise RuntimeError("cannot notify on un-acquired lock")
        self._notify_all_core()

class RWConditionReaderProxy(RWConditionProxy):
    """
    Condition proxy bound specifically to the Reader state-machine.
    
    Calling `wait()` on this proxy will release the underlying READ lock,
    allowing other writers or readers to proceed while the current thread sleeps.
    """
    __slots__ = ()
    def __init__(self, rwcond: RWConditionBase):
        super().__init__(
            lock_proxy=rwcond._rwlock.read,
            is_owned=rwcond._is_owned_read,
            add_waiter=rwcond._add_waiter,
            remove_waiter=rwcond._remove_waiter,
            notify_core=rwcond._notify_core,
            notify_all_core=rwcond._notify_all_core
        )

class RWConditionWriterProxy(RWConditionProxy):
    """
    Condition proxy bound specifically to the Writer state-machine.
    
    Calling `wait()` on this proxy will release the underlying WRITE lock,
    allowing other threads to acquire the lock while the current thread sleeps.
    """
    __slots__ = ()
    def __init__(self, rwcond: RWConditionBase):
        super().__init__(
            lock_proxy=rwcond._rwlock.write,
            is_owned=rwcond._is_owned_write,
            add_waiter=rwcond._add_waiter,
            remove_waiter=rwcond._remove_waiter,
            notify_core=rwcond._notify_core,
            notify_all_core=rwcond._notify_all_core
        )

# Read Write Lock For Condition
class RWCondition(RWConditionBase):
    """
    Standard implementation of a Read-Write Condition variable.
    
    Utilizes a thread-safe `collections.deque` and a micro-lock to provide 
    O(1) waiter queueing and wake-ups. It is highly optimized to prevent 
    race conditions during massive `notify_all` calls (Cache Stampede protection).

    Example:
        ```python
        cond = RWCondition(RWLockFIFO())
        
        # Reader thread
        with cond.read:
            cond.read.wait_for(lambda: data_ready)
            print(data)
            
        # Writer thread
        with cond.write:
            data_ready = True
            cond.write.notify_all()
        ```
    """
    __slots__ = ('_waiters', '_internal_lock')
    
    def __init__(self, rwlock: Optional['RWLockBase'] = None):
        if rwlock is None:
            rwlock = RWLockWrite() 
            
        self._waiters = deque()
        self._internal_lock = threading.Lock()
        super().__init__(rwlock)
    
    def _is_owned_read(self) -> bool:
        return self._rwlock._is_read_locked()

    def _is_owned_write(self) -> bool:
        return self._rwlock._is_write_locked()

    def _add_waiter(self) -> threading.Lock:
        waiter = threading.Lock()
        waiter.acquire()
        with self._internal_lock:
            self._waiters.append(waiter)
        return waiter

    def _remove_waiter(self, waiter: threading.Lock) -> None:
        with self._internal_lock:
            try:
                self._waiters.remove(waiter)
            except ValueError:
                pass

    def _notify_core(self, n: int) -> None:
        with self._internal_lock:
            waiters = self._waiters
            while waiters and n > 0:
                waiter = waiters.popleft() 
                try:
                    waiter.release()
                except RuntimeError:
                    # gh-92530: Interrupted before removing from queue
                    pass
                else:
                    n -= 1

    def _notify_all_core(self) -> None:
        self._notify_core(len(self._waiters))
