"""
Reusable queue primitives for the RWLock family.

This module stays runtime-agnostic at import time. Thread and asyncio specific
primitives are injected by callers, so importing only the thread stack does not
also pull asyncio into memory, and vice versa.
"""
from abc import ABC
from collections import deque
from typing import Callable, Deque, TypeVar, Generic

from .base import Lockable, AsyncFuturable

__all__ = (
    "ThreadWaitQueue", 
    "AsyncWaitQueue",
    "ThreadConditionQueue", 
    "AsyncConditionQueue"
)

T = TypeVar("T")

class WakeQueueBase(ABC, Generic[T]):
    """Bounded wakeup logic shared by waiter queues."""
    __slots__ = ("_waiters",)

    def __init__(self) -> None:
        self._waiters: Deque[T] = deque()

    def has_waiters(self) -> bool:
        return bool(self._waiters)
    
    def _wake_waiter(self, waiter: T) -> bool:
        raise NotImplementedError

    def _append_waiter(self, waiter: T) -> T:
        self._waiters.append(waiter)
        return waiter

    def _discard_waiter(self, waiter: T) -> None:
        try:
            self._waiters.remove(waiter)
        except ValueError:
            pass

    def _notify_unlocked(self, n: int = 1) -> None:
        waiters = self._waiters
        while waiters and n > 0:
            if self._wake_waiter(waiters.popleft()):
                n -= 1

    def _notify_all_unlocked(self) -> None:
        waiters = self._waiters
        if not waiters:
            return
        for waiter in waiters:
            self._wake_waiter(waiter)
        waiters.clear()


class ThreadWaitQueue(WakeQueueBase[Lockable]):
    """O(1) wait queue for proxy-based thread locks."""
    __slots__ = ("_lock", "_waiter_factory")

    def __init__(self, lock: Lockable, waiter_factory: Callable[..., Lockable]):
        super().__init__()
        self._lock = lock
        self._waiter_factory = waiter_factory

    def _wake_waiter(self, waiter: Lockable) -> bool:
        try:
            waiter.release()  # type: ignore[union-attr]
        except RuntimeError:
            return False
        return True

    def wait(self, timeout: float = -1.0) -> bool:
        waiter = self._waiter_factory()
        waiter.acquire()
        self._append_waiter(waiter)
        self._lock.release()
        gotit = False
        try:
            if timeout < 0:
                waiter.acquire()
                gotit = True
            else:
                gotit = waiter.acquire(timeout=timeout)
            return gotit
        finally:
            self._lock.acquire()
            if not gotit:
                self._discard_waiter(waiter)

    def notify(self, n: int = 1) -> None:
        self._notify_unlocked(n)

    def notify_all(self) -> None:
        self._notify_all_unlocked()

class AsyncWaitQueue(WakeQueueBase[AsyncFuturable]):
    """O(1) wait queue for proxy-based asyncio locks."""
    __slots__ = ("_waiter_factory",)

    def __init__(self, waiter_factory: Callable[..., AsyncFuturable]):
        super().__init__()
        self._waiter_factory = waiter_factory

    def _wake_waiter(self, waiter: AsyncFuturable) -> bool:
        if waiter.done():
            return False
        waiter.set_result(True)
        return True

    async def wait(self) -> None:
        waiter = self._append_waiter(self._waiter_factory())
        try:
            await waiter
        except BaseException:
            self._discard_waiter(waiter)
            raise

    def notify(self, n: int = 1) -> None:
        self._notify_unlocked(n)

    def notify_all(self) -> None:
        self._notify_all_unlocked()


class ThreadConditionQueue(WakeQueueBase[Lockable]):
    """O(1) waiter queue for thread-based RWCondition implementations."""
    __slots__ = ("_lock", "_waiter_factory")

    def __init__(
        self,
        lock:Lockable,
        waiter_factory: Callable[..., Lockable],
    ):
        super().__init__()
        self._lock = lock
        self._waiter_factory = waiter_factory

    def _create_waiter(self) -> Lockable:
        waiter = self._waiter_factory()
        waiter.acquire()
        return waiter

    def _wake_waiter(self, waiter: object) -> bool:
        try:
            waiter.release()
        except RuntimeError:
            return False
        return True

    def add_waiter(self) -> Lockable:
        waiter = self._create_waiter()
        with self._lock:
            return self._append_waiter(waiter)

    def remove_waiter(self, waiter: Lockable) -> None:
        with self._lock:
            self._discard_waiter(waiter)

    def notify(self, n: int) -> None:
        with self._lock:
            self._notify_unlocked(n)

    def notify_all(self) -> None:
        with self._lock:
            self._notify_all_unlocked()

class AsyncConditionQueue(WakeQueueBase[AsyncFuturable]):
    """O(1) waiter queue for asyncio RWCondition implementations."""

    __slots__ = ("_waiter_factory",)

    def __init__(self, waiter_factory: Callable[[], AsyncFuturable]):
        super().__init__()
        self._waiter_factory = waiter_factory

    def _create_waiter(self) -> AsyncFuturable:
        return self._waiter_factory()

    def _wake_waiter(self, waiter: object) -> bool:
        if waiter.done():
            return False
        waiter.set_result(True)
        return True

    def add_waiter(self) -> AsyncFuturable:
        return self._append_waiter(self._create_waiter())

    def remove_waiter(self, waiter: AsyncFuturable) -> None:
        self._discard_waiter(waiter)

    def notify(self, n: int) -> None:
        self._notify_unlocked(n)

    def notify_all(self) -> None:
        self._notify_all_unlocked()
