# **Change Log**
All notable changes to this project will be documented in this file.

## **[2.0] - 02.03.2026**
Add highly optimized **O(1)** `RWCondition` and `AsyncRWCondition` primitives with flawless cancellation shielding. Also rename all `*SafeWriter` classes to `*ReentrantWriter` and expand test coverage for the v2.0 release.

### Added
* **Condition Variables for Thread & Async Environments**:
    * Introduced `RWCondition` (Thread) and `AsyncRWCondition` (Asyncio) primitives.
    * Condition variables can now wrap any specific scheduling strategy (`Write-Pref`, `Read-Pref`, `FIFO`, and `Reentrant` variants) via Dependency Injection.
    * Standard Condition's O(N) wake-up traversal has been completely bypassed.
    * `RWCondition` utilizes a `deque` with micro-locks, and `AsyncRWCondition` utilizes a native `deque` of `asyncio.Future` objects to provide **pure O(1) time complexity** for `wait()`, `notify()`, and `notify_all()` operations.
* **Condition Smart Proxies & Downgrade Safety**:
    * Implemented `.read` and `.write` proxies for Condition objects (`RWConditionProxy`, `AsyncRWConditionProxy`).
    * The Smart Proxy intelligently routes the release operations back to the correct state even if an **Atomic Downgrade** was performed while holding a lock inside a condition block.
* **Flawless Cancellation Shielding (Asyncio)**:
    * Re-engineered the `AsyncRWConditionProxy.wait()` method to be absolutely resilient to `asyncio.CancelledError`. Tasks that are cancelled while sleeping now securely re-acquire the lock before throwing the error to prevent any state corruption.
* **Advanced Benchmark Suite for Conditions**:
    * Added comprehensive "Cache Stampede Simulators" (`PubSubScenario` & `ReaderWriterConditionScenario`) to measure event loop queuing, task wake-up latency, and stampede protection.
    * Demonstrated up to **70x FASTER** throughput compared to standard `asyncio.Condition` and `threading.Condition` in (1 Writer, 100 Readers) workloads.
* **Expanded Test Coverage**:
    * Test suite expanded from 135 to **252 unit tests**.
    * Added deep validation for state ownership, `notify(n)` precision, lock release safety, and timeout precision on both synchronous and asynchronous Condition proxies.

### Updated
* **Reentrant Class Naming Convention**:
    * Renamed all `*SafeWriter` classes to `*ReentrantWriter` (e.g., `RWLockWriteSafeWriter` -> `RWLockWriteReentrantWriter`) to better reflect their strictly nested, reentrant nature in the software engineering domain.
* **Documentation & README**:
    * Added "Condition Memory vs CPU Trade-off" and "The Cost of Fairness" sections to the Architecture Limitations.
    * Expanded usage examples to cover Event-Driven Cache Refreshes, Precise Job Queues, and Condition-Based Atomic Downgrading patterns.

<br>


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