"""Synchronous and asyncio read-write locks and condition variables.

Runtime-specific modules are loaded on first access so thread-only and
async-only imports do not eagerly initialize the other implementation.
Direct operations on a read-write lock use its exclusive write proxy; shared
access is available through ``.read`` and exclusive access through ``.write``.
"""

from importlib import import_module

__version__ = "3.4.1"

_THREAD_EXPORTS = (
    "Lockable", "LockDowngradable", "RWLockBase", "RWLockWithProxyBase",
    "RWLockProxy", "RWLockReaderProxy", "RWLockWriterProxy", "RWLockWrite",
    "RWLockWriteReentrantWriter", "RWLockRead", "RWLockReadReentrantWriter",
    "RWLockReaderPhaseFair", "RWLockReaderPhaseFairReentrantWriter", "RWLockFair",
    "RWLockFairReentrantWriter", "Lock", "ConditionLockable",
    "ConditionDowngradable", "RWConditionBase", "RWConditionWithProxyBase",
    "RWConditionProxy", "RWConditionReaderProxy", "RWConditionWriterProxy",
    "RWCondition", "Condition",
)

_ASYNC_EXPORTS = (
    "AsyncLockable", "AsyncLockDowngradable", "AsyncRWLockBase",
    "AsyncRWLockWithProxyBase", "AsyncRWLockProxy", "AsyncRWLockReaderProxy",
    "AsyncRWLockWriterProxy", "AsyncRWLockWrite", "AsyncRWLockWriteReentrantWriter",
    "AsyncRWLockRead", "AsyncRWLockReadReentrantWriter", "AsyncRWLockReaderPhaseFair",
    "AsyncRWLockReaderPhaseFairReentrantWriter", "AsyncRWLockFair",
    "AsyncRWLockFairReentrantWriter", "AsyncLock", "AsyncConditionLockable",
    "AsyncConditionDowngradable", "AsyncRWConditionBase", "AsyncRWConditionWithProxyBase",
    "AsyncRWConditionProxy", "AsyncRWConditionReaderProxy", "AsyncRWConditionWriterProxy",
    "AsyncRWCondition", "AsyncCondition",
)

__all__ = _THREAD_EXPORTS + _ASYNC_EXPORTS


def __getattr__(name: str):
    if name in _THREAD_EXPORTS:
        module_name = ".thread_rwlock"
    elif name in _ASYNC_EXPORTS:
        module_name = ".async_rwlock"
    else:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(module_name, __name__), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
