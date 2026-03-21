# **Change Log**
All notable changes to this project will be documented in this file.

## **[3.1] - 20.03.2026**
The **"Micro-Optimizations & Memory Safety"** update. This version introduces targeted performance improvements to internal state checks, cleans up the codebase by removing duplicates, and resolves a critical memory leak in asynchronous broadcast queues.

### Added
* **Advanced Test Scenarios**:
    * Introduced `test_exception_handling_in_context_manager` to guarantee `with`/`async with` blocks strictly release locks upon raised exceptions.
    * Added `test_writer_downgrade_wakes_readers` to validate atomic downgrades automatically signaling sleeping readers.
    * Embedded `test_task_cancellation_during_wait` in `AsyncRWLock` to ensure task cancellations (`CancelledError`) cleanly pop from queues without leaving zombie waiters.
    * Appended `test_massive_notify_all_cache_stampede_resilience` for Conditions to stress-test 100+ concurrent wake-ups with zero drop rates.
* **Automated Benchmark Orchestration & Visualization**:
    * Introduced `collect_benchmark_data_script.py` to silently execute benchmarks and export pure data as structured JSON files.
    * Created `benchmark_figure_script.py` with a `BenchmarkOrchestrator` to automatically trigger data collection across multiple Python interpreters (Standard, Free-Threading GIL On, Free-Threading GIL Off) via `subprocess`.
    * Implemented an advanced `BenchmarkPlotter` using `pandas` and `seaborn` that dynamically ingests JSON results and renders highly detailed, adaptive, and transparent SVG charts optimized for GitHub themes.
* **Documentation & Internationalization**:
    * Embedded the newly generated, highly detailed SVG benchmark graphics directly into the README files to visually demonstrate the massive performance leaps.
    * Introduced full Russian language support (`README_ru.md`), providing a meticulous and technically accurate translation of the entire documentation.
    * Expanded the "Performance and Benchmark Results" sections to include comprehensive testing methodology and hardware environment details for absolute transparency.

### Updated
* **Reentrant Lock Fast-Paths (Thread & Async)**:
    * Optimized the core `_can_read` and `_can_write` checks for all Reentrant lock variations.
    * Previously, these locks constantly called expensive system-level functions (`threading.get_ident()` or `asyncio.current_task()`) even when no writer was active. We now bypass these calls entirely when the lock is free.
    * This results in a significant speed boost for Reentrant locks during heavy read workloads.
* **O(1) Efficiency for Downgraded Locks**:
    * Improved the cleanup process inside the `.write.release()` method for locks that have been downgraded.
    * Replaced a double condition check (`if item in set: set.remove(item)`) with a more efficient, single-step `try/except` block. This reduces the computational overhead of hash lookups.
* **Unified Core Logic with State-Machine Mixins**:
    * Extracted the core scheduling algorithms (like `_can_read` and `_can_write`) that were identical across Thread and Async lock variations.
    * Created a new `mixins.py` module to house these shared behaviors.
    * This change removes hundreds of lines of duplicated code, making the library much easier to maintain without mixing OS-level Threads and Asyncio tasks.
* **Modular Benchmark Framework & Data Handlers**:
    * Completely overhauled the `benchmarks` directory to strictly follow DRY principles using Object-Oriented design.
    * Introduced `benchmark_base.py` containing `BenchmarkerBase` and `AsyncBenchmarkerBase` template classes.
    * Extracted all performance scenarios into a centralized `benchmark_scenario.py` module (`IOBoundScenario`, `CPUBoundScenario`, etc.).
    * **Advanced Data Handling**: Replaced hardcoded console output with a Dependency Injection architecture (`BenchmarkDataHandler` and `BenchmarkPrintHandler`). This allows benchmark outputs to be easily captured as structural dictionaries (`dict`) for JSON/CSV reporting or natively printed to the console.
    * This drastically reduces boilerplate code and makes future performance testing highly extensible.

### Fixed
* **Critical Memory Leak in Async Wait Queues**:
    * Fixed a bug in `_AsyncWaitQueue.notify_all()` that left completed `asyncio.Future` objects lingering in memory.
    * Added a strict `waiters.clear()` step after broadcasting. This completely stops O(N) performance slowdowns and prevents memory usage from infinitely ballooning when `notify_all()` is called frequently.

<br>

## **[3.0] - 04.03.2026**
The **"Zero Friction & Drop-in Replacement"** update. This version marks a major architectural leap by bypassing internal library overheads, introducing true O(1) broadcast clearing, and achieving 100% API parity with Python's standard concurrency primitives.

### Added
* **High-Performance Micro-Queues (`_ThreadWaitQueue`, `_AsyncWaitQueue`)**:
    * Replaced heavy standard `threading.Condition` and `asyncio.Condition` internals with lean, custom-built O(1) wait queues.
    * These queues operate directly under the parent lock’s protection, eliminating nested lock overhead and minimizing OS-level context switching.
* **100% Drop-in Replacement Architecture**:
    * `RWLockBase`, `RWConditionBase`, `AsyncRWLockBase`, and `AsyncRWConditionBase` now natively implement the complete standard `Lockable` and `ConditionLockable` (and their async counterparts) protocols directly.
    * Calling standard methods directly on the core object (e.g., `lock.acquire()`, `await cond.wait()`, `__enter__`, `__aenter__`) now automatically and safely routes to the exclusive `.write` proxy.
    * This allows custom locks (Fair, Read-Pref, Write-Pref) to be seamlessly passed into third-party libraries (e.g., SQLAlchemy, requests) expecting standard `threading.Lock` or `asyncio.Lock` instances.
* **Standard Adapters (`Lock`, `Condition`, `AsyncLock`, `AsyncCondition`)**:
    * Added specific adapter classes that encapsulate standard `threading` and `asyncio` primitives while conforming strictly to the `RWLockBase` API signature (`.read` and `.write` attributes). Ideal for dependency injection workflows.

### Updated
* **Class Naming Standardization (FIFO to Fair)**:
    * Renamed all `FIFO` scheduling classes to `Fair` (e.g., `RWLockFIFO` -> `RWLockFair`, `AsyncRWLockFIFO` -> `AsyncRWLockFair` and their Reentrant variants) to better align with standard computer science terminology for phase-ordered, starvation-free scheduling.
* **"Happy Path" Performance Isolation (Thread & Async)**:
    * Re-engineered the wait logic in both environments to completely skip O(N) `remove()` operations upon successful wake-ups.
    * **Async Environment:** `_AsyncWaitQueue.wait()` and `AsyncRWConditionProxy.wait()` now utilize `except asyncio.CancelledError` for cleanup, ensuring zero execution cost on successful executions.
    * **Thread Environment:** `_ThreadWaitQueue.wait()` implements a strict `gotit` boolean flag, executing the cleanup block `if not gotit` only upon timeouts or external OS interrupts, bypassing list traversal on standard wake-ups.
* **Pure O(1) Broadcast / Cache Stampede Eradication**:
    * Upgraded `notify_all()` and `_notify_all_core()` methods across both Thread and Async wait queues (`_ThreadWaitQueue`, `_AsyncWaitQueue`, `RWCondition`, `AsyncRWCondition`).
    * Replaced the hallowed O(N) `while` loop and `popleft()` element extraction with a high-speed `for` loop iteration followed by a C-level `deque.clear()` operation, resolving CPU locking during massive (100+ tasks/threads) wake-ups.
* **Dot-Lookup Elimination (Micro-optimization)**:
    * Applied local variable caching (`waiters = self._waiters`) inside highly concurrent loops (`notify`, `notify_all`) to bypass Python Virtual Machine (PVM) attribute lookup overhead.
* **Documentation**:
    * Appended "Drop-in Replacement" details to the Architecture Notes.
    * Added comprehensive `Example 2 (Drop-in Replacement)` blocks inside docstrings for every single primitive, guiding developers on direct standard API usage.
* **Adapter Test Suites**: 
    * Integrated the newly introduced standard adapter classes (`Lock`, `AsyncLock`, `Condition`, `AsyncCondition`) into the testing pipeline to ensure 100% behavioral compliance with the standard Python library.

### Fixed
* **Thread Timeout and OS-Interrupt Resilience**:
    * Hardened the `_ThreadWaitQueue.wait(timeout)` mechanics. Replaced standard exception wrapping with an absolute `finally: self._lock.acquire()` guarantee coupled with the `gotit` flag. This prevents infinite deadlocks even if the Operating System violently interrupts the thread (e.g., `KeyboardInterrupt`) precisely during a timeout expiration.
* **Precise Partial Notifications (`notify_core`)**:
    * Distinctly separated the partial wake-up logic (`notify(n)`) from the broadcast logic (`notify_all`). Ensured `notify(n)` correctly decrements `n` only on successful, non-interrupted, or non-cancelled thread/task wake-ups using `else` blocks and `.done()` validations.
* **Test Infrastructure Overhaul**: 
    * Completely redesigned and fortified the testing architecture to handle the new drop-in replacement patterns and micro-queue structures. 
    * The testing suite has been expanded to a massive **266 unit tests**, validating concurrency safety, cancellation shielding, and edge cases, executing flawlessly in a blistering **8.5 seconds**.

<br>

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