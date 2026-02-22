# **Change Log**
All notable changes to this project will be documented in this file.

## **[1.0] - 22.02.2026**

### Added
* **Thread Read-Write Locks (`rwlocker.thread_rwlock`)**:
    * `RWLockWrite`: Write-preferring read-write lock to prevent writer starvation.
    * `RWLockRead`: Read-preferring read-write lock for maximum concurrency in read-heavy workloads.
    * `RWLockFIFO`: Fair read-write lock guaranteeing alternating access between readers and writers.
    * `RWLockWriteSafeWriter`, `RWLockReadSafeWriter`, `RWLockFIFOSafeWriter`: Reentrant variants of the above locks, safely supporting strictly nested write locks for the same thread.
* **Async Read-Write Locks (`rwlocker.async_rwlock`)**:
    * `AsyncRWLockWrite`: Write-preferring async read-write lock.
    * `AsyncRWLockRead`: Read-preferring async read-write lock.
    * `AsyncRWLockFIFO`: Fair async read-write lock.
    * `AsyncRWLockWriteSafeWriter`, `AsyncRWLockReadSafeWriter`, `AsyncRWLockFIFOSafeWriter`: Reentrant async variants utilizing `asyncio.current_task()` for O(1) identity tracking.
* **Core Architectural Features**:
    * **Smart Proxies (`.read`, `.write`)**: Added proxy objects to handle state transitions transparently via context managers (`with` and `async with`).
    * **Atomic Downgrading (`downgrade()`)**: Introduced the ability to transition a held write lock atomically into a read lock without fully releasing it, preventing intervening writers.
    * **Zero-Allocation Fast-Paths**: Optimized standard lock acquisition and release in synchronous locks to minimize object allocation and OS-level context switching.
    * **Cancellation Safety**: Implemented robust handling for `CancelledError` in all `AsyncRWLock` variants, ensuring safe state recovery and waiter notification upon task cancellation.
    * **Comprehensive Test Suite**: Added a full suite of unit tests covering reentrancy, deadlocks, timeouts, and cancellation scenarios.
* **Documentation & Tooling**:
    * Added `README.md` and `README_TR.md` with detailed usage examples, architectural notes, and benchmark results.
    * Included comprehensive inline docstrings for all classes and methods.

<br>