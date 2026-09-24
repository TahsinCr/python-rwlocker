"""
Shared protocol definitions for rwlocker.

This module centralizes the structural interfaces used by both the thread and
asyncio implementations so runtime-specific modules do not need to duplicate
them. Keeping these protocols separate also helps isolate import costs between
the thread and async stacks.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from types import TracebackType
from typing import Callable, Optional, Protocol

__all__ = (
    "Lockable",
    "LockDowngradable",
    "AsyncLockable",
    "AsyncLockDowngradable",
    "ConditionLockable",
    "ConditionDowngradable",
    "AsyncConditionLockable",
    "AsyncConditionDowngradable",
    "AsyncFuturable"
)

# protocols
class Lockable(Protocol):
    """Standard thread-safe lock interface."""

    def acquire(self, blocking: bool = True, timeout: float = -1.0) -> bool: ...
    def release(self) -> None: ...
    def locked(self) -> bool: ...
    def __enter__(self) -> bool: ...
    def __exit__(
        self,
        exc_type: Optional[type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[TracebackType],
    ) -> Optional[bool]: ...

class LockDowngradable(Lockable, Protocol):
    """Thread lock that supports atomic state degradation."""

    def downgrade(self) -> None: ...


class AsyncLockable(Protocol):
    """Standard asyncio-compatible lock interface."""

    async def acquire(self) -> bool: ...
    def release(self) -> None: ...
    def locked(self) -> bool: ...
    async def __aenter__(self) -> bool: ...
    async def __aexit__(
        self,
        exc_type: Optional[type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[TracebackType],
    ) -> Optional[bool]: ...

class AsyncLockDowngradable(AsyncLockable, Protocol):
    """Async lock that supports atomic state degradation."""
    def downgrade(self) -> None: ...


class ConditionLockable(Lockable, Protocol):
    """Standard thread-safe condition interface."""

    def wait(self, timeout: Optional[float] = None) -> bool: ...
    def wait_for(
        self,
        predicate: Callable[[], bool],
        timeout: Optional[float] = None,
    ) -> bool: ...
    def notify(self, n: int = 1) -> None: ...
    def notify_all(self) -> None: ...

class ConditionDowngradable(ConditionLockable, Protocol):
    """Thread condition that supports atomic state degradation."""
    def downgrade(self) -> None: ...


class AsyncConditionLockable(AsyncLockable, Protocol):
    """Standard asyncio-compatible condition interface."""

    async def wait(self) -> bool: ...
    async def wait_for(self, predicate: Callable[[], bool]) -> bool: ...
    def notify(self, n: int = 1) -> None: ...
    def notify_all(self) -> None: ...

class AsyncConditionDowngradable(AsyncConditionLockable, Protocol):
    """Async condition that supports atomic state degradation."""
    def downgrade(self) -> None: ...


class AsyncFuturable(Protocol):
    """Minimal primitive used by async queues for parking and wakeup."""
    def done(self) -> bool: ...
    def set_result(self, result: bool) -> None: ...
    def __await__(self) -> object: ...


# bases
class RWLockBase(ABC):
    """
    Base class establishing the core Read-Write interface.
    
    Provides the foundational `.read` and `.write` attributes. Furthermore, it 
    exposes lock-style methods (`acquire`, `release`, etc.) that default to the exclusive `.write`.
    proxy. Designed to act as a common type hint and contract for both standard 
    adapters and proxy-based complex state machines.
    """
    __slots__ = ('_lock', 'read', 'write')
    def __init__(self, lock: Lockable):
        self._lock = lock
        self.read:Lockable = self._lock
        self.write:Lockable = self._lock
    
    def _is_write_locked(self) -> bool:
        return self.write.locked()

    def _is_read_locked(self) -> bool:
        return self.read.locked()
    
    def acquire(self, blocking: bool = True, timeout: float = -1.0) -> bool:
        """
        Acquire the exclusive (write) lock.
        Provides standard threading.Lock compatibility by routing to the write proxy.
        """
        return self.write.acquire(blocking, timeout)

    def release(self) -> None:
        """
        Release the exclusive (write) lock.
        """
        self.write.release()

    def locked(self) -> bool:
        """
        Check if the exclusive (write) lock is currently held.
        """
        return self.write.locked()
    
    def __enter__(self) -> bool:
        return self.write.__enter__()
    
    def __exit__(self, exc_type, exc_val, exc_tb) -> Optional[bool]:
        return self.write.__exit__(exc_type, exc_val, exc_tb)

class AsyncRWLockBase(ABC):
    """
    Base class establishing the core Asynchronous Read-Write interface.
    
    Provides the foundational `.read` and `.write` attributes. Furthermore, it 
    exposes lock-style methods (`acquire`, `release`, etc.) that default to the exclusive `.write`.
    proxy. Designed to act as a common type hint and contract.
    """
    __slots__ = ('read', 'write')
    def __init__(self, lock: AsyncLockable):
        self.read: AsyncLockable = lock
        self.write: AsyncLockable = lock

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
    
    async def __aexit__(self, exc_type, exc_val, exc_tb) -> Optional[bool]:
        return await self.write.__aexit__(exc_type, exc_val, exc_tb)

class RWConditionBase(ABC):
    """
    Base class establishing the core Read-Write Condition interface.
    
    Provides the foundational `.read` and `.write` attributes. Furthermore, it 
    exposes condition-style methods (`wait`, `notify`, etc.) that default to the exclusive
    `.write` proxy. Designed to act as a common type hint and contract.
    """
    __slots__ = ('_lock', 'read', 'write')
    def __init__(self, lock: Lockable, condition: ConditionLockable):
        self._lock = lock
        self.write: ConditionLockable = condition
        self.read: ConditionLockable = condition
    
    def acquire(self, blocking: bool = True, timeout: float = -1.0):
        """
        Acquire the underlying exclusive (write) lock.
        """
        return self.write.acquire(blocking, timeout)

    def release(self):
        """
        Release the underlying exclusive (write) lock.
        """
        self.write.release()

    def locked(self) -> bool:
        """
        Check if the underlying exclusive (write) lock is currently held.
        """
        return self.write.locked()
    
    def wait(self, timeout: Optional[float] = None) -> bool:
        """
        Wait until notified or until a timeout occurs.
        Provides standard threading.Condition compatibility by routing to the write proxy.
        """
        return self.write.wait(timeout)

    def wait_for(self, predicate: Callable[[], bool], timeout: Optional[float] = None) -> bool:
        """
        Wait until a specific condition (predicate) evaluates to True.
        Routes to the exclusive write proxy.
        """
        return self.write.wait_for(predicate, timeout)

    def notify(self, n: int = 1) -> None:
        """
        Wake up one or more threads waiting on this condition.
        Routes to the exclusive write proxy.
        """
        self.write.notify(n)

    def notify_all(self) -> None:
        """
        Wake up all threads currently waiting on this condition.
        Routes to the exclusive write proxy.
        """
        self.write.notify_all()
    
    def __enter__(self):
        return self.write.__enter__()
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        return self.write.__exit__(exc_type, exc_val, exc_tb)

class AsyncRWConditionBase(ABC):
    """
    Base class establishing the core Asynchronous Read-Write Condition interface.
    
    Provides the foundational `.read` and `.write` attributes. Furthermore, it 
    exposes condition-style methods (`wait`, `notify`, etc.) that default to the exclusive
    `.write` proxy. Designed to act as a common type hint and contract.
    """
    __slots__ = ('_lock', 'read', 'write')

    def __init__(self, lock: AsyncLockable, condition: AsyncConditionLockable):
        self._lock = lock
        self.write: AsyncConditionLockable = condition
        self.read: AsyncConditionLockable = condition
    
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
