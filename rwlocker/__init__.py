"""
Advanced Read-Write Lock (RWLock) and Condition Concurrency Primitives.

This package provides a comprehensive, highly optimized, state-machine-based 
suite of Read-Write locks and Condition variables for both Synchronous 
(`threading`) and Asynchronous (`asyncio`) Python applications. 

Designed for high-performance systems (e.g., telemetry processing, data streams), 
it guarantees strict data safety while maximizing read concurrency and 
preventing CPU/Event-Loop bottlenecks.

Key Architectural Features:
    - **Multiple Scheduling Strategies**: Choose between Write-preferring, 
      Read-preferring, and Fair (FIFO) algorithms to prevent starvation based 
      on your specific workload.
    - **O(1) Condition Queuing (Stampede Protection)**: Condition variables 
      (`RWCondition`, `AsyncRWCondition`) utilize pure O(1) waiter queues 
      to completely eliminate O(N) cache stampedes and event-loop blocking 
      during massive `notify_all()` calls.
    - **Smart Proxies**: Locks and conditions are interacted with via `.read` 
      and `.write` attributes. These proxies intelligently route `release()` 
      operations, even after complex state transitions, preventing deadlocks.
    - **Atomic Downgrading**: Transition from a Write lock to a Read lock seamlessly. 
      The `.downgrade()` operation ensures no other writer can hijack the lock 
      during the transition.
    - **Adapter Pattern & Solid Base**: Standard locks and conditions are 
      encapsulated via `Lock`, `Condition`, `AsyncLock`, and `AsyncCondition` 
      adapters, sharing the exact same API signatures for seamless dependency injection.
    - **Zero-Allocation Fast-Paths**: Standard synchronous lock acquisition 
      and release are optimized to avoid runtime object creation.
    - **Flawless Cancellation Shielding (Async)**: Asynchronous locks and 
      condition `wait()` operations are strictly resilient to `asyncio.CancelledError`, 
      ensuring safe state recovery during task aborts.

Important Usage Notes & Gotchas:
    - **Reentrancy (`ReentrantWriter` variants)**: Reentrancy is STRICTLY supported for 
      nested *write* operations by the same Thread/Task. It does NOT implicitly 
      grant read locks. You must use `.downgrade()` if you need to read.
    - **Downgrade Performance Cost**: Calling `.downgrade()` registers the current 
      Thread/Task ID into a tracking set. This adds a minor O(1) hash lookup cost 
      during the subsequent `release()` operation. Standard operations remain O(0).
    - **Circular References**: Base lock classes hold references to their proxies, 
      and proxies hold references back to the base. Memory is reclaimed via 
      Python's cyclic GC. Do not rely on `__del__` for cleanup.

Basic Example:
    >>> lock = RWLockFIFOReentrantWriter()
    >>> with lock.write:
    ...     # Exclusive write access
    ...     lock.write.downgrade()
    ...     # Atomically downgraded to shared read access
    
    >>> cond = RWCondition(RWLockWrite())
    >>> with cond.read:
    ...     # Sleep at O(1) cost without blocking other readers
    ...     cond.read.wait_for(lambda: True)

    >>> async_cond = AsyncRWCondition(AsyncRWLockRead())
    >>> async with async_cond.write:
    ...     # Wake up thousands of tasks instantly without event-loop lag
    ...     async_cond.write.notify_all()
"""

from .thread_rwlock import *
from .async_rwlock import *

__version__ = '3.2'
