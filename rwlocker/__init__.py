"""
Advanced Read-Write Lock (RWLock) Concurrency Primitives.

This package provides a comprehensive, highly optimized, state-machine-based 
suite of Read-Write locks for both Synchronous (`threading`) and Asynchronous 
(`asyncio`) Python applications. 

Designed for high-performance systems (e.g., telemetry processing, data streams), 
it guarantees strict data safety while maximizing read concurrency.

Key Architectural Features:
    - **Multiple Scheduling Strategies**: Choose between Write-preferring, 
      Read-preferring, and Fair (FIFO) algorithms to prevent starvation based 
      on your specific workload.
    - **Smart Proxies**: Locks are interacted with via `.read` and `.write` attributes. 
      These proxies intelligently route `release()` operations, even after complex 
      state transitions, preventing deadlocks natively.
    - **Atomic Downgrading**: Transition from a Write lock to a Read lock seamlessly. 
      The `.downgrade()` operation ensures no other writer can hijack the lock 
      during the transition.
    - **Zero-Allocation Fast-Paths**: Standard lock acquisition and release are 
      optimized to avoid runtime object creation, minimizing CPU cycles and 
      Garbage Collection (GC) pressure.
    - **Cancellation Safety (Async)**: Asynchronous locks are fully resilient to 
      `asyncio.CancelledError`, ensuring event loop integrity during task aborts.

Important Usage Notes & Gotchas:
    - **Reentrancy (`SafeWriter` variants)**: Reentrancy is STRICTLY supported for 
      nested *write* operations by the same Thread/Task. It does NOT implicitly 
      grant read locks. You must use `.downgrade()` if you need to read.
    - **Downgrade Performance Cost**: Calling `.downgrade()` registers the current 
      Thread/Task ID into a tracking set. This adds a minor O(1) hash lookup cost 
      during the subsequent `release()` operation. Standard operations remain O(0).
    - **Circular References**: Base lock classes hold references to their proxies, 
      and proxies hold references back to the base. Memory is reclaimed via 
      Python's cyclic GC. Do not rely on `__del__` for cleanup.

Basic Example:
    >>> lock = RWLockFIFOSafeWriter()
    >>> with lock.write:
    ...     # Exclusive write access
    ...     lock.write.downgrade()
    ...     # Atomically downgraded to read access

    >>> async_lock = AsyncRWLockWrite()
    >>> async with async_lock.read:
    ...     # Shared read access
    ...     pass
"""

from .thread_rwlock import *
from .async_rwlock import *
