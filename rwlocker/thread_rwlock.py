"""
Advanced Read-Write Lock (RWLock) and Condition Concurrency Primitives.

This module provides highly optimized, state-machine-based Read-Write locks
and their corresponding Condition variables. It supports different scheduling
strategies (Write-preferring, Read-preferring, Reader-Phase Fair, Strict Fair)
and safe reentrancy for writer threads.
"""
from __future__ import annotations

import time
import threading
from abc import abstractmethod
from typing import Callable, Optional

from .base import (
    RWLockBase,
    RWConditionBase,
    ConditionDowngradable,
    ConditionLockable,
    LockDowngradable,
    Lockable,
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
    ThreadWaitQueue,
    ThreadConditionQueue
)

__version__ = '3.4.2'
__all__ = (
    'Lockable', 'LockDowngradable', 
    'RWLockBase', 'RWLockWithProxyBase',
    'RWLockProxy', 'RWLockReaderProxy', 'RWLockWriterProxy',
    'RWLockWrite', 'RWLockWriteReentrantWriter', 
    'RWLockRead', 'RWLockReadReentrantWriter',
    'RWLockReaderPhaseFair', 'RWLockReaderPhaseFairReentrantWriter',
    'RWLockFair', 'RWLockFairReentrantWriter',
    'Lock',

    'ConditionLockable', 'ConditionDowngradable', 
    'RWConditionBase', 'RWConditionWithProxyBase',
    'RWConditionProxy', 'RWConditionReaderProxy', 'RWConditionWriterProxy',
    'RWCondition', 'Condition'
)


# Read Write Lock Proxy
class RWLockProxy:
    """
    Base proxy class acting as a standard threading.Lock interface.
    Handles acquisition logic, timeout calculations, and thread wake-ups.
    """
    __slots__ = (
        '_lock', 'those_waiting', 'condition', '_can_acquire',
        '_acquire_core', '_release_core', '_on_abort', '_is_locked', '_waiter_seq',
        '_before_acquire'
    )  
    def __init__(self, 
        lock: threading.Lock, 
        can_acquire:Callable[...,bool],
        acquire_core:Callable[...,None],
        release_core:Callable[[],None],
        on_abort:Callable[...,None],
        is_locked:Callable[[],bool],
        before_acquire: Optional[Callable[[], None]] = None,
    ):
        self._lock = lock
        self.those_waiting = 0
        self.condition = ThreadWaitQueue(self._lock, threading.Lock)
        
        self._can_acquire = can_acquire
        self._acquire_core = acquire_core
        self._release_core = release_core
        self._on_abort = on_abort
        self._is_locked = is_locked
        self._waiter_seq = 0
        self._before_acquire = before_acquire

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
                if timeout < 0:
                    while not self._can_acquire(True, waiter_seq):
                        self.condition.wait()
                    self._acquire_core(True, waiter_seq)
                    acquired = True
                    return True
                    
                endtime = time.monotonic() + timeout
                while not self._can_acquire(True, waiter_seq):
                    remaining = endtime - time.monotonic()
                    if remaining <= 0.0:
                        return False
                    self.condition.wait(remaining)
                
                self._acquire_core(True, waiter_seq)
                acquired = True
                return True
            finally:
                self.those_waiting -= 1
                if not acquired:
                    self._on_abort(waiter_seq)

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
    def __init__(self, rwlock: RWLockWithProxyBase):
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
    __slots__ = ('_read_lock', '_downgrade_core', '_downgraded_thread_id')
    def __init__(self, rwlock: RWLockWithProxyBase):
        super().__init__(
            lock=rwlock._lock,
            can_acquire=rwlock._can_write,
            acquire_core=rwlock._acquire_write_core,
            release_core=rwlock._release_write_core,
            on_abort=rwlock._on_writer_abort,
            is_locked=rwlock._is_write_locked,
            before_acquire=rwlock._check_write_acquire_allowed,
        )
        self._read_lock = rwlock.read
        self._downgrade_core = rwlock._downgrade_core
        self._downgraded_thread_id: Optional[int] = None

    def acquire(self, blocking: bool = True, timeout: float = -1.0) -> bool:
        acquired = super().acquire(blocking, timeout)
        if acquired:
            self._downgraded_thread_id = None
        return acquired
        
    def downgrade(self):
        """
        Atomically transition the held Write lock into a Read lock.
        Allows waiting readers to enter while preventing new writers from acquiring.
        
        Performance Cost:
            This operation stores the current thread id in a single downgrade
            marker. The following `release()` performs one additional identity
            check before routing to the correct read/write release path.
        """
        with self._lock:
            self._downgrade_core()
            self._downgraded_thread_id = threading.get_ident()
    
    def release(self):
        """
        Release the lock. 
        Intelligently detects if the lock was downgraded by the current thread
        and routes the release to the reader core to prevent deadlocks.
        """
        with self._lock:
            if self._downgraded_thread_id == threading.get_ident():
                self._downgraded_thread_id = None
                try:
                    self._read_lock._release_core()
                    return
                except RuntimeError:
                    pass
            self._release_core()


# Read Write Locks
class RWLockWithProxyBase(RWLockBase):
    """
    Abstract base class for all proxy-based Read-Write lock implementations.

    This class manages the core OS lock and initializes the Smart Proxy Pattern, 
    exposing `read` and `write` attributes as proxy instances that route logic 
    to the overridden internal core methods (`_acquire_read_core`, etc.).
    """
    __slots__ = ("_reader_owners", "_writer_owner")
    def __init__(self, lock: Optional[Lockable] = None):
        self._lock = threading.Lock() if lock is None else lock
        self._reader_owners = {}
        self._writer_owner = None
        self.read:RWLockReaderProxy = RWLockReaderProxy(rwlock=self)
        self.write:RWLockWriterProxy = RWLockWriterProxy(rwlock=self)

    def _current_reader_owner(self):
        return threading.current_thread()

    def _record_reader_acquire(self) -> None:
        owner = self._current_reader_owner()
        self._reader_owners[owner] = self._reader_owners.get(owner, 0) + 1

    def _record_reader_release(self) -> None:
        owner = self._current_reader_owner()
        count = self._reader_owners.get(owner, 0)
        if count == 0:
            raise RuntimeError("Read lock is not held by the current thread")
        if count == 1:
            del self._reader_owners[owner]
        else:
            self._reader_owners[owner] = count - 1

    def _is_current_reader(self) -> bool:
        return self._reader_owners.get(self._current_reader_owner(), 0) > 0

    def _is_current_writer(self) -> bool:
        if hasattr(self, "_writer_id"):
            return self._writer_id == threading.get_ident()
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


class RWLockWrite(_RWLockWriteMixin, RWLockWithProxyBase):
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
    Example 2 (Direct Lock Interface):
        ```python
        lock = RWLockWrite()
        
        # By using the lock instance directly, it automatically routes to the 
        # exclusive (write) proxy. This allows the RWLock to be safely injected 
        # into legacy code that only understands standard threading.Lock.
        with lock:
            print("Exclusive write lock acquired via direct standard API.")
        ```
    """
    __slots__ = ('_writer_active', '_readers_active')
    def __init__(self, lock: Optional[Lockable] = None):
        super().__init__(lock)
        self._writer_active = False
        self._readers_active = 0

class RWLockWriteReentrantWriter(
    _RWLockWriteReentrantWriterMixin,
    RWLockWrite,
):
    """
    Write-preferring Read-Write Lock with Write-Reentrancy support.
    
    Reentrancy Note:
        The owning thread can acquire nested write locks and a read lock. Other
        readers can join only after an explicit downgrade opens shared access.

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
    Example 2 (Direct Lock Interface):
        ```python
        lock = RWLockWriteReentrantWriter()
        
        # By using the lock instance directly, it automatically routes to the 
        # exclusive (write) proxy. This allows the RWLock to be safely injected 
        # into legacy code that only understands standard threading.Lock.
        with lock:
            print("Exclusive write lock acquired via direct standard API.")
        ```
    """
    __slots__ = ('_writer_id', '_write_count')
    def __init__(self, lock: Optional[Lockable] = None):
        super().__init__(lock)
        self._writer_id: Optional[int] = None
        self._write_count: int = 0

    def _is_current_writer(self) -> bool:
        return self._writer_id == threading.get_ident()

    def _set_current_writer(self) -> None:
        self._writer_id = threading.get_ident()

    def _clear_current_writer(self) -> None:
        self._writer_id = None


class RWLockRead(_RWLockReadMixin, RWLockWithProxyBase):
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
    Example 2 (Direct Lock Interface):
        ```python
        lock = RWLockRead()
        
        # By using the lock instance directly, it automatically routes to the 
        # exclusive (write) proxy. This allows the RWLock to be safely injected 
        # into legacy code that only understands standard threading.Lock.
        with lock:
            print("Exclusive write lock acquired via direct standard API.")
        ```
    """
    __slots__ = ('_writer_active', '_readers_active')
    def __init__(self, lock: Optional[Lockable] = None):
        super().__init__(lock)
        self._writer_active = False
        self._readers_active = 0

class RWLockReadReentrantWriter(
    _RWLockReadReentrantWriterMixin,
    RWLockRead,
):
    """
    Read-preferring Read-Write Lock with Write-Reentrancy support.
    
    Reentrancy Note:
        The owning thread can nest write acquisitions and acquire read locks.
        Read-to-write upgrades are rejected to avoid self-deadlocks.
    
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
    Example 2 (Direct Lock Interface):
        ```python
        lock = RWLockReadReentrantWriter()
        
        # By using the lock instance directly, it automatically routes to the 
        # exclusive (write) proxy. This allows the RWLock to be safely injected 
        # into legacy code that only understands standard threading.Lock.
        with lock:
            print("Exclusive write lock acquired via direct standard API.")
        ```
    """
    __slots__ = ('_writer_id', '_write_count')
    def __init__(self, lock: Optional[Lockable] = None):
        super().__init__(lock)
        self._writer_id: Optional[int] = None
        self._write_count: int = 0

    def _is_current_writer(self) -> bool:
        return self._writer_id == threading.get_ident()

    def _set_current_writer(self) -> None:
        self._writer_id = threading.get_ident()

    def _clear_current_writer(self) -> None:
        self._writer_id = None


class RWLockReaderPhaseFair(_RWLockReaderPhaseFairMixin, RWLockWithProxyBase):
    """
    Reader-phase fair Read-Write Lock.

    This lock alternates between reader and writer phases to reduce starvation,
    but once a reader phase is opened, readers arriving during that phase are
    still allowed to join it. This makes it more throughput-friendly than
    strict fair locks under read-heavy contention.

    Example:
        ```python
        lock = RWLockReaderPhaseFair()

        with lock.read:
            print("Reading data...")

        with lock.write:
            print("Updating data...")
        ```
    Example 2 (Direct Lock Interface):
        ```python
        lock = RWLockReaderPhaseFair()

        with lock:
            print("Exclusive write lock acquired via direct standard API.")
        ```
    """
    __slots__ = ('_writer_active', '_readers_turn', '_readers_active')
    def __init__(self, lock: Optional[Lockable] = None):
        super().__init__(lock)
        self._writer_active = False
        self._readers_turn = False
        self._readers_active = 0

class RWLockReaderPhaseFairReentrantWriter(
    _RWLockReaderPhaseFairReentrantWriterMixin,
    RWLockReaderPhaseFair,
):
    """
    Reader-phase fair Read-Write Lock with write reentrancy support.

    Example:
        ```python
        lock = RWLockReaderPhaseFairReentrantWriter()

        with lock.write:
            with lock.write:
                print("Nested write lock acquired safely.")
            lock.write.downgrade()
            print("Downgraded to read mode.")
        ```
    Example 2 (Direct Lock Interface):
        ```python
        lock = RWLockReaderPhaseFairReentrantWriter()

        with lock:
            print("Exclusive write lock acquired via direct standard API.")
        ```
    """
    __slots__ = ('_writer_id', '_write_count')
    def __init__(self, lock: Optional[Lockable] = None):
        super().__init__(lock)
        self._writer_id: Optional[int] = None
        self._write_count: int = 0

    def _is_current_writer(self) -> bool:
        return self._writer_id == threading.get_ident()

    def _set_current_writer(self) -> None:
        self._writer_id = threading.get_ident()

    def _clear_current_writer(self) -> None:
        self._writer_id = None


class RWLockFair(_RWLockFairMixin, RWLockReaderPhaseFair):
    """
    Strict fair Read-Write Lock.

    This lock opens reader phases only for the readers already queued when the
    phase starts. Readers arriving later must wait for the next turn, which
    gives more deterministic writer latency than `RWLockReaderPhaseFair`.

    Example:
        ```python
        lock = RWLockFair()

        with lock.read:
            print("Reading data...")

        with lock.write:
            print("Updating data...")
        ```
    Example 2 (Direct Lock Interface):
        ```python
        lock = RWLockFair()

        with lock:
            print("Exclusive write lock acquired via direct standard API.")
        ```
    """
    __slots__ = ('_reader_phase_cutoff', '_reader_phase_pending')
    def __init__(self, lock: Optional[Lockable] = None):
        super().__init__(lock)
        self._reader_phase_cutoff = 0
        self._reader_phase_pending = 0

class RWLockFairReentrantWriter(
    _RWLockFairReentrantWriterMixin,
    RWLockFair,
):
    """
    Strict fair Read-Write Lock with write reentrancy support.

    Example:
        ```python
        lock = RWLockFairReentrantWriter()

        with lock.write:
            with lock.write:
                print("Nested write lock acquired safely.")
            lock.write.downgrade()
            print("Downgraded to read mode.")
        ```
    Example 2 (Direct Lock Interface):
        ```python
        lock = RWLockFairReentrantWriter()

        with lock:
            print("Exclusive write lock acquired via direct standard API.")
        ```
    """
    __slots__ = ('_writer_id', '_write_count')
    def __init__(self, lock: Optional[Lockable] = None):
        super().__init__(lock)
        self._writer_id: Optional[int] = None
        self._write_count: int = 0

    def _is_current_writer(self) -> bool:
        return self._writer_id == threading.get_ident()

    def _set_current_writer(self) -> None:
        self._writer_id = threading.get_ident()

    def _clear_current_writer(self) -> None:
        self._writer_id = None


# Standart Lock Adapter
class Lock(RWLockBase):
    """
    Adapter class for the standard `threading.Lock`.
    
    Wraps the standard lock to conform to the `RWLockBase` interface, exposing 
    it via both `.read` and `.write` attributes. Useful for dependency injection 
    where an RWLock signature is required, but a simple standard lock is sufficient.

    Example:
        ```python
        lock = Lock()
        
        # Both .read and .write point to the same standard threading.Lock
        with lock.read:
            print("Reading with standard lock...")
            
        with lock.write:
            print("Writing with standard lock...")
        ```
    Example 2 (Direct Lock Interface):
        ```python
        lock = Lock()
        
        # Acts exactly like a standard threading.Lock.
        # Perfect for passing into third-party libraries expecting a standard lock.
        with lock:
            print("Standard lock acquired directly without proxies.")
        ```
    """
    __slots__ = ()

    def __init__(self, lock: Optional[Lockable] = None):
        super().__init__(threading.Lock() if lock is None else lock)



# Read Write Condition Proxy
class RWConditionProxy:
    """
    Base proxy class acting as a standard `threading.Condition` interface.
    
    It holds no state of its own. It dynamically routes lock acquisitions, 
    releases, and signaling operations to the injected core callables provided 
    by the underlying `RWConditionBase` implementation.
    """
    __slots__ = (
        '_lock_proxy', '_is_owned', '_add_waiter', 
        '_remove_waiter', '_notify_core', '_notify_all_core',
        '_get_owned_depth'
    )
    
    def __init__(self, 
        lock_proxy: RWLockProxy,
        is_owned: Callable[[], bool],
        add_waiter: Callable[[], threading.Lock],
        remove_waiter: Callable[[threading.Lock], None],
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
        
        This method releases the underlying lock while waiting and reacquires
        it before returning. Nested lock acquisitions are rejected because this
        condition does not restore recursive lock depth.

        Args:
            timeout (float, optional): Maximum time in seconds to wait.

        Returns:
            bool: True if awoken by a `notify()` call, False if the timeout expired.
            
        Raises:
            RuntimeError: If the lock is not owned or has nested acquisitions.
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
    def __init__(self, rwcond: RWConditionWithProxyBase):
        super().__init__(
            lock_proxy=rwcond._lock.read,
            is_owned=rwcond._is_owned_read,
            add_waiter=rwcond._add_waiter,
            remove_waiter=rwcond._remove_waiter,
            notify_core=rwcond._notify_core,
            notify_all_core=rwcond._notify_all_core,
            get_owned_depth=getattr(rwcond, "_get_owned_lock_depth", None)
        )

class RWConditionWriterProxy(RWConditionProxy):
    """
    Condition proxy bound specifically to the Writer state-machine.
    
    Calling `wait()` on this proxy will release the underlying WRITE lock,
    allowing other threads to acquire the lock while the current thread sleeps.
    """
    __slots__ = ()
    def __init__(self, rwcond: RWConditionWithProxyBase):
        super().__init__(
            lock_proxy=rwcond._lock.write,
            is_owned=rwcond._is_owned_write,
            add_waiter=rwcond._add_waiter,
            remove_waiter=rwcond._remove_waiter,
            notify_core=rwcond._notify_core,
            notify_all_core=rwcond._notify_all_core,
            get_owned_depth=getattr(rwcond, "_get_owned_lock_depth", None)
        )
    
    def downgrade(self):
        """
        Atomically transition the underlying Write lock into a Read lock.
        
        This passes the downgrade request directly to the underlying lock proxy,
        allowing waiting readers to enter while maintaining the condition context.
        """
        self._lock_proxy.downgrade()


# Read Write Condition
class RWConditionWithProxyBase(RWConditionBase):
    """
    Abstract base class for proxy-based Read-Write Condition variables.
    
    This class solely defines the internal state machine and core queuing 
    operations. It strictly hides its internal mechanisms and exposes its 
    functionality via `.read` and `.write` proxies to maintain a clean, 
    standardized threading.Condition API.
    """
    __slots__ = ()
    def __init__(self, lock: Optional[RWLockBase] = None):
        self._lock = RWLockWrite() if lock is None else lock
        self.read: RWConditionReaderProxy = RWConditionReaderProxy(rwcond=self)
        self.write: RWConditionWriterProxy = RWConditionWriterProxy(rwcond=self)
    
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

class RWCondition(_RWConditionMixin, RWConditionWithProxyBase):
    """
    Standard implementation of a Read-Write Condition variable.
    
    Utilizes a thread-safe `collections.deque` and a micro-lock to provide 
    Amortized O(1) waiter enqueue/dequeue and O(N) notifications. Each waiter
    is signalled individually during `notify_all()`.

    Example:
        ```python
        cond = RWCondition() # RWLockWrite default lock
        
        # Reader thread
        with cond.read:
            cond.read.wait_for(lambda: data_ready)
            print(data)
            
        # Writer thread
        with cond.write:
            data_ready = True
            cond.write.notify_all()
        ```
    Example 2 (Direct Lock Interface):
        ```python
        cond = RWCondition() # RWLockWrite default lock
        
        # Direct usage bypasses explicit .read/.write proxies and defaults to 
        # the exclusive write state, providing lock-style compatibility with
        # standard threading.Condition workflows.
        with cond:
            while not data_ready:
                cond.wait()
            cond.notify_all()
        ```
    """
    __slots__ = ('_queue',)
    
    def __init__(self, lock: Optional[RWLockBase] = None):
        self._queue = ThreadConditionQueue(threading.Lock(), threading.Lock)
        super().__init__(lock)


# Standart Condition Adapter
class Condition(RWConditionBase):
    """
    Adapter class for the standard `threading.Condition`.
    
    Wraps the standard condition to conform to the `RWConditionBase` interface.
    Both `.read` and `.write` attributes point to the same standard condition instance.
    Cannot be initialized with proxy-based complex RWLocks.

    Example:
        ```python
        cond = Condition()
        
        # Both .read and .write point to the same standard threading.Condition
        with cond.read:
            cond.read.wait_for(lambda: data_ready)
            
        with cond.write:
            data_ready = True
            cond.write.notify_all()
        ```
    Example 2 (Direct Lock Interface):
        ```python
        cond = Condition()
        
        # Functions identically to threading.Condition.
        with cond:
            cond.wait_for(lambda: data_ready)
            cond.notify()
        ```
    """
    __slots__ = ()
    def __init__(self, lock: Optional[Lockable] = None):
        lock = threading.Lock() if lock is None else lock
        condition = threading.Condition(lock)
        super().__init__(lock, condition)
