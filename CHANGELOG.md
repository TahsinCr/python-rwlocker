# **Change Log**
All notable changes to this project will be documented in this file.

## **[3.4.2] - 25.09.2026**
The **"RWLock Ownership Safety"** patch closes self-deadlocks in recursive reader acquisition and read-to-write upgrades.

### Fixed
* Allow a current reader to acquire the read lock recursively while writers are waiting, without letting new readers bypass the selected strategy.
* Reject read-to-write upgrades immediately with `RuntimeError` in synchronous and asynchronous locks.
* Remove condition waiters if synchronous lock release is interrupted by any `BaseException`.
* Correct reentrant-writer documentation and describe ownership constraints in all README translations.
* Increase async benchmark figure height to twice the original layout so bar-end labels have enough vertical separation.

### Validation
* All 510 tests passed on Python 3.14.7 (15 skipped); the sdist and wheel built, and `twine check` passed for both.

## **[3.4.1] - 25.09.2026**
The **"Condition Wait Safety & Release Metadata"** patch release closes a deadlock edge case in reentrant condition waits, corrects per-interpreter benchmark speedups, and aligns package metadata and CI checks with the published installation instructions.

### Fixed
* **Condition Wait with Nested Ownership**:
    * Synchronous and asynchronous condition waits now reject nested read/write acquisitions before registering a waiter or releasing the lock. This prevents a wait from sleeping while recursive ownership still holds the lock.
    * The error also covers a read wait entered while the same owner still holds the write side. Recursive depth restoration is not supported by these condition proxies.
    * Added regression coverage for nested read, nested write, and combined write/read ownership in both runtimes.
* **Benchmark Reporting**:
    * Normalize each synchronous speedup against the baseline collected in the same interpreter environment.
    * Pass the benchmark's operation count directly to result handlers instead of deriving it from rounded throughput and elapsed time.
* **Package Metadata and Documentation**:
    * Correct the 3.4 PyPI metadata: mark the project Beta rather than Production/Stable, and define the documented `benchmark` extra for pandas, matplotlib, and seaborn.
    * Clarify wait behavior in the thread docstring and qualify fairness descriptions that previously implied starvation could never occur.

### CI
* Build source and wheel distributions, run `twine check`, install and inspect the wheel metadata/import, and verify that the optional benchmark dependencies load.

### Validation
* All 472 tests passed on Python 3.14.7 (15 skipped); the plotting regression ran and passed with the `benchmark` extra installed.
* The 3.4.1 source and wheel distributions built locally, and `twine check` passed for both artifacts.

## **[3.4] - 24.09.2026**
The **"Correctness, Packaging & Benchmark Reporting"** update. This release fixes ownership and injected-lock handling, improves Python-version and package metadata, makes benchmark collection reproducible and more informative, repairs examples, and revises documentation to describe measured behavior accurately.

### Fixed
* **Python Compatibility and Lock Construction**:
    * Deferred forward-reference annotations in the synchronous and asynchronous modules so supported Python versions can import the package.
    * Forwarded supplied lock objects through every synchronous RWLock constructor instead of silently replacing them.
    * Track read ownership and reject unmatched or cross-owner read releases; condition ownership checks use the current thread/task where that information is available.
* **Examples and Concurrency Edge Cases**:
    * Fixed invalidation races in the auth-token example and corrected cleanup/error handling in the image queue, transaction ledger, and synchronous ledger condition examples.
    * Made the global configuration cache and remaining examples consistent with the lock and condition APIs.
    * Corrected async CPU-bound benchmark scenarios to run CPU work outside the event loop.

### Updated
* **Benchmark Reliability**:
    * Added configurable interactive and reporting profiles; reporting collection now defaults to 10 measured trials after 2 warmups.
    * Store individual trial durations, variance, median absolute deviation, quartiles, and a deterministic bootstrap 95% confidence interval with collected results.
    * Calculate condition operation counts from actual reader and writer work, and label workload throughput separately from primitive or notification cost.
    * Plot all collected async interpreter environments and compare synchronous results within their matching interpreter environment.
* **Package and CI**:
    * Declare Python 3.9–3.14 in the CI matrix and add a package import check.
    * Include `py.typed` in built distributions; the runtime package remains dependency-free.
* **Documentation and Historical Corrections**:
    * Describe condition queue operations accurately: enqueue/FIFO dequeue are amortized O(1), while broadcast and arbitrary waiter removal are O(N).
    * Clarify that lock-style compatibility is not universal drop-in compatibility, fairness outcomes depend on workload, and benchmark ratios describe end-to-end workloads.
    * Remove absolute correctness, zero-error, and zero-overhead claims; document writer reentrancy and benchmark limitations consistently across English, Turkish, Russian, and PyPI READMEs.
    * Note that previously published aggregate benchmark JSON files do not contain raw per-trial data and cannot be retroactively expanded.

### Validation
* The local suite passed 435 tests on Python 3.10 and Python 3.14; Python 3.9 is covered by CI configuration but was not available for local execution.
* Benchmark figures were regenerated from the available interpreter datasets. CI results on remote runners and package publication are separate release steps and are not claimed here.

## **[3.3] - 04.04.2026**
The **"Fairness, Protocol Isolation & Benchmark Reliability"** update. This version re-introduces carefully scoped internal mixins without changing the public monolithic API, formalizes the distinction between Reader-Phase Fair and Strict Fair scheduling, isolates protocol and queue infrastructure to reduce cross-runtime import cost, hardens downgrade routing in both Thread and Async implementations, and substantially upgrades the benchmark/reporting toolchain and documentation surface.

### Added
* **Reader-Phase Fair Scheduling Family**:
    * Added `RWLockReaderPhaseFair` / `AsyncRWLockReaderPhaseFair` and their `ReentrantWriter` variants as first-class public scheduling strategies.
    * These variants explicitly preserve the "reader phase may continue to admit later readers" behavior, separating it from strict fair semantics.
    * This makes the lock family easier to reason about by giving the old phase-oriented behavior an honest, descriptive public name.
* **Shared Base & Protocol Module (`rwlocker/base.py`)**:
    * Introduced a central base module to house `Lockable`, `ConditionLockable`, and their async counterparts together with the shared `RWLockBase`, `AsyncRWLockBase`, `RWConditionBase`, and `AsyncRWConditionBase` abstractions.
    * Added a minimal async future protocol used by queue implementations.
    * This removes duplicated protocol and base-class declarations from `thread_rwlock.py` and `async_rwlock.py` while keeping the runtime-specific modules independent from one another.
* **Runtime-Agnostic Queue Module (`rwlocker/queues.py`)**:
    * Added reusable `ThreadWaitQueue`, `AsyncWaitQueue`, `ThreadConditionQueue`, and `AsyncConditionQueue` primitives as a dedicated internal infrastructure layer.
    * The queue module is now built around injected primitives/factories rather than direct top-level `threading` / `asyncio` imports, reducing cross-runtime import coupling.
* **Reintroduced Internal State-Machine Mixins (`rwlocker/mixins.py`)**:
    * Re-added internal mixins to centralize identical non-public logic shared by thread and async lock families.
    * The mixins only contain internal `_` helpers and state-machine rules; all user-facing methods remain in the concrete monolithic modules.
    * Follow-up performance measurements showed that the mixin-based indirection affected hot paths only at a negligible level relative to the reliability and maintenance gains, so the shared internal structure was restored.
    * This restores maintainability benefits without moving public API methods behind mixin indirection.
* **Dedicated Benchmark Base Test Suite**:
    * Added `tests/benchmark_base_test.py` to validate baseline selection, warmup handling, target rotation, aggregation, and garbage-collection behavior in the benchmark framework.

### Updated
* **Strict Fair vs Reader-Phase Fair Semantics**:
    * Reworked the Fair family so `RWLockFair` / `AsyncRWLockFair` represent the strict fair contract.
    * A reader phase in strict fair mode now snapshots the waiting readers at phase start and prevents late-reader barging ahead of queued writers.
    * The older throughput-leaning phase behavior remains available via `ReaderPhaseFair`.
* **Downgrade Routing and Release Safety (Thread & Async)**:
    * Replaced multi-entry downgrade tracking with a single downgrade-owner marker in async writer proxies.
    * Preserved the thread-side single downgrade owner model and hardened it further.
    * A successful new write acquisition now clears stale downgrade state, preventing incorrect release routing after flows such as:
      `write.acquire() -> downgrade() -> read.release() -> write.acquire() -> write.release()`
* **Async Base Lock Compatibility**:
    * Corrected the base async context-manager exit path by implementing `__aexit__` correctly.
    * This restores proper drop-in replacement behavior for `async with lock:` and `async with cond:`.
* **Condition Infrastructure**:
    * `RWCondition` and `AsyncRWCondition` now use the new queue layer for waiter management while preserving the same external API.
    * Thread-side condition waiters continue to use a dedicated micro-lock for queue integrity, while async conditions stay event-loop-native.
* **Cleaner Internal DRY Boundaries**:
    * Shared reentrant-writer logic, fair-phase logic, and condition queue hooks were consolidated into mixins only where thread and async behavior truly matched.
    * Runtime-specific owner tracking, cancellation behavior, and public method surfaces remain in the concrete modules.
* **Base-Class Extraction from Monolithic Modules**:
    * The shared `RWLockBase` / `RWConditionBase` hierarchy, together with the async base hierarchy, was moved out of the monolithic thread and async modules into `rwlocker/base.py`.
    * This keeps the public API intact while reducing duplication and making the concrete modules more focused on runtime-specific proxy and state-machine behavior.
* **Benchmark Framework Overhaul**:
    * The benchmark system was reorganized around reusable base classes and scenario objects.
    * `BenchmarkConfig` now exposes clear profiles such as `faster()`, `interactive()`, and `reporting()`.
    * Benchmark handlers were generalized so results can be printed or collected structurally for figure generation.
* **Benchmark Console Output**:
    * Reworked terminal printing to be more compact and readable with better column sizing, baseline highlighting, wrapped long names, and optional ANSI colors.
    * Baseline rows are now clearly marked with `BL`, and metadata such as `Ops` is surfaced more cleanly.
* **Benchmark Coverage for the Expanded Lock Family**:
    * Thread and async benchmark scripts now include the `ReaderPhaseFair` and `Fair` families together with their reentrant variants.
    * Condition benchmarks were expanded in the same spirit so all primary scheduling strategies can be compared consistently.
* **Benchmark Plot Generation**:
    * Refined the figure-generation pipeline and plotting style handling.
    * Plot configuration, label formatting, category mapping, and annotation logic were cleaned up for more legible generated charts.

### Fixed
* **Late Reader Barging in Strict Fair Locks**:
    * Fixed the core behavioral bug where late readers could still slip into what was supposed to be a strict fair reader phase.
    * Strict fair locks now reserve the phase for the readers already queued at phase start.
* **Downgrade Poisoning Bug After Manual Read Release**:
    * Fixed both thread and async cases where manually releasing the downgraded read side could poison a future `write.release()` call.
    * Regression tests now cover this path explicitly.
* **Async Condition Cancellation / Waiter Cleanup Safety**:
    * Hardened async condition waiting so waiter cleanup remains correct if release fails or a task is cancelled while waiting.
    * This prevents stale waiters and protects the lock state from corruption under `CancelledError`.
* **Massive `notify_all()` Reliability Under RWCondition**:
    * Reworked the condition/fairness interaction so large thread wake-up storms remain stable even under Fair locks.
    * Thread condition tests that stress `notify_all()` with 100 waiters now pass reliably instead of hanging or timing out.
* **Async Benchmark Execution Bug**:
    * Fixed async benchmark workers so scenarios that return synchronously no longer trigger `TypeError: 'NoneType' object can't be awaited`.
* **Backward-Compatible Queue Patch Hook**:
    * Restored the private `_ThreadWaitQueue` compatibility alias used by existing tests and local patch hooks.
* **Read-Preference Writer Wakeup Edge Case**:
    * Eliminated unnecessary writer wakeups in read-preferring paths when readers should continue to dominate.
* **Condition Test Stability**:
    * Updated thread condition tests to fail fast with time-bounded joins instead of appearing to hang indefinitely.

### Documentation
* **README & PyPI Documentation Refresh**:
    * Updated `README.md`, `README_tr.md`, `README_ru.md`, and `README-pypi.md` to reflect the 3.3 API, benchmark methodology, and lock-family distinctions.
* **Concrete Class Examples Completed**:
    * Added or corrected example blocks for concrete `RWLock*`, `AsyncRWLock*`, `RWCondition*`, and `AsyncRWCondition*` classes, including the Fair variants that previously lacked the same level of example coverage.
* **Package-Level Documentation Corrections**:
    * Updated the root package documentation to describe `Reader-Phase Fair` and `Strict Fair` separately.
    * Corrected outdated class-name references and aligned downgrade behavior notes with the new single-marker routing model.
* **Async Downgrade Documentation Accuracy**:
    * Removed incorrect `await lock.write.downgrade()`-style guidance.
    * Async downgrade remains a synchronous state transition, and the docs now reflect that consistently.

### Testing
* **Expanded Lock Regression Tests**:
    * Added or strengthened tests for:
      - late reader barging behavior,
      - reader-phase `notify_all()` usage,
      - downgrade-started reader phases,
      - stale downgrade marker cleanup,
      - cross-thread / cross-task release protection,
      - cancellation safety in async wait paths.
* **Expanded Condition Stress Tests**:
    * Strengthened condition tests around timeout handling, `notify(n)`, `notify_all()`, and downgrade release safety for both thread and async variants.
* **Validation Result**:
    * The full local test suite now runs cleanly at **412 tests** for version 3.3.

<br>

## **[3.2] - 22.03.2026**
The **"Speed and Memory Safety"** update. This version strictly prioritizes raw execution speed by reversing the DRY-oriented mixin architecture, introduces O(1) memory optimizations for thread state downgrades, completely eliminates a critical memory leak in async task tracking via weak references, and refines type hinting for standard adapters.

### Updated
* **Removal of State-Machine Mixins (`mixins.py`)**:
    * Completely removed the `mixins.py` module that was introduced in version 3.1.
    * Re-inlined all core scheduling algorithms (`_can_read`, `_can_write`, `_acquire_read_core`, etc.) directly back into their respective Thread and Async lock classes.
    * **Reasoning:** While the mixin architecture made the codebase significantly cleaner by following DRY principles, the Method Resolution Order (MRO) indirection and the overhead of extra class hierarchy jumps caused a **~2-3% performance penalty** in highly concurrent `RWLock` and `RWCondition` workloads. In a low-level concurrency primitive library, raw execution speed inherently outweighs code aesthetics.
* **O(1) Memory Optimization for Thread Downgrades**:
    * Replaced the `_downgraded_threads` hash set with a single `_downgraded_thread_id` variable in `RWLockWriterProxy`.
    * Since a write lock is strictly exclusive, only one thread can ever hold and downgrade it at any given time. Maintaining a dynamic set was structurally redundant and incurred unnecessary allocation overhead.

### Fixed
* **Memory Leak Prevention in Async Downgrades**:
    * Upgraded the `_downgraded_tasks` tracker in `AsyncRWLockWriterProxy` to utilize a `weakref.WeakSet` instead of a standard `set`.
    * `asyncio.Task` objects are highly volatile and frequently destroyed. Keeping strong references inside the lock proxy could lead to severe memory leaks (zombie tasks). The `WeakSet` guarantees they are cleanly garbage-collected by Python.
* **Standard Adapter Type Hinting**:
    * Corrected the `__init__` constructor type hints for standard `Condition` and `AsyncCondition` adapters.
    * They now correctly accept the `Lockable` and `AsyncLockable` protocols, fixing an issue where they falsely restricted inputs to proxy-based `RWLockBase` structures, ignoring standard standard library locks.

<br>

## **[3.1] - 21.03.2026**
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
    * Queue cleanup releases references to signalled waiters. Broadcasting still signals each waiter and takes O(N) time.

<br>

## **[3.0] - 04.03.2026**
The **"Lock-Style Interface and Queue-Based Conditions"** update. This version added direct lock-style methods and internal queues. Its original complexity and API-parity claims were overstated; see the Unreleased corrections above.

### Added
* **Wait Queues (`_ThreadWaitQueue`, `_AsyncWaitQueue`)**:
    * Replaced standard `threading.Condition` and `asyncio.Condition` wait handling with internal queues. Enqueue and FIFO dequeue are amortized O(1); broadcasting and arbitrary waiter removal are O(N).
    * These queues operate directly under the parent lock’s protection, eliminating nested lock overhead and minimizing OS-level context switching.
* **Lock-Style Interface Compatibility**:
    * `RWLockBase`, `RWConditionBase`, `AsyncRWLockBase`, and `AsyncRWConditionBase` now expose direct lock-style methods alongside `.read` and `.write` proxies; signatures and observable behavior do not fully match every standard primitive.
    * Calling standard methods directly on the core object (e.g., `lock.acquire()`, `await cond.wait()`, `__enter__`, `__aenter__`) now automatically and safely routes to the exclusive `.write` proxy.
    * Check each integration before passing a custom lock to code written for standard `threading.Lock` or `asyncio.Lock` instances.
* **Standard Adapters (`Lock`, `Condition`, `AsyncLock`, `AsyncCondition`)**:
    * Added specific adapter classes that encapsulate standard `threading` and `asyncio` primitives while conforming strictly to the `RWLockBase` API signature (`.read` and `.write` attributes). Ideal for dependency injection workflows.

### Updated
* **Class Naming Standardization (FIFO to Fair)**:
    * Renamed all `FIFO` scheduling classes to `Fair` (e.g., `RWLockFIFO` -> `RWLockFair`, `AsyncRWLockFIFO` -> `AsyncRWLockFair` and their Reentrant variants) to better align with standard computer science terminology for phase-ordered, starvation-free scheduling.
* **"Happy Path" Performance Isolation (Thread & Async)**:
    * Re-engineered the wait logic in both environments to completely skip O(N) `remove()` operations upon successful wake-ups.
    * **Async Environment:** `_AsyncWaitQueue.wait()` and `AsyncRWConditionProxy.wait()` now utilize `except asyncio.CancelledError` for cleanup, avoiding arbitrary waiter removal on successful wake-ups.
    * **Thread Environment:** `_ThreadWaitQueue.wait()` implements a strict `gotit` boolean flag, executing the cleanup block `if not gotit` only upon timeouts or external OS interrupts, bypassing list traversal on standard wake-ups.
* **Condition Broadcasts**:
    * Updated `notify_all()` across both Thread and Async wait queues (`_ThreadWaitQueue`, `_AsyncWaitQueue`, `RWCondition`, `AsyncRWCondition`).
    * Each waiter is signalled individually, so `notify_all()` takes O(N) time. FIFO deque operations are amortized O(1), while removing an arbitrary waiter takes O(N).
* **Dot-Lookup Elimination (Micro-optimization)**:
    * Applied local variable caching (`waiters = self._waiters`) inside highly concurrent loops (`notify`, `notify_all`) to bypass Python Virtual Machine (PVM) attribute lookup overhead.
* **Documentation**:
    * Appended "Drop-in Replacement" details to the Architecture Notes.
    * Added comprehensive `Example 2 (Drop-in Replacement)` blocks inside docstrings for every single primitive, guiding developers on direct standard API usage.
* **Adapter Test Suites**: 
    * Integrated the newly introduced standard adapter classes (`Lock`, `AsyncLock`, `Condition`, `AsyncCondition`) into the testing pipeline to check the adapters against their documented lock-style interface.

### Fixed
* **Thread Timeout and OS-Interrupt Resilience**:
    * Hardened the `_ThreadWaitQueue.wait(timeout)` mechanics. Used a `finally` reacquisition path with a `gotit` flag to restore lock state after timeouts or interrupts.
* **Precise Partial Notifications (`notify_core`)**:
    * Distinctly separated the partial wake-up logic (`notify(n)`) from the broadcast logic (`notify_all`). Ensured `notify(n)` correctly decrements `n` only on successful, non-interrupted, or non-cancelled thread/task wake-ups using `else` blocks and `.done()` validations.
* **Test Infrastructure Overhaul**: 
    * Completely redesigned and fortified the testing architecture to handle the new drop-in replacement patterns and micro-queue structures. 
    * The testing suite has been expanded to a massive **266 unit tests**, validating concurrency safety, cancellation shielding, and edge cases, running in **8.5 seconds** in that recorded environment.

<br>

## **[2.0] - 02.03.2026**
Add queue-backed `RWCondition` and `AsyncRWCondition` primitives with cancellation cleanup. Also rename all `*SafeWriter` classes to `*ReentrantWriter` and expand test coverage for the v2.0 release.

### Added
* **Condition Variables for Thread & Async Environments**:
    * Introduced `RWCondition` (Thread) and `AsyncRWCondition` (Asyncio) primitives.
    * Condition variables can now wrap any specific scheduling strategy (`Write-Pref`, `Read-Pref`, `FIFO`, and `Reentrant` variants) via Dependency Injection.
    * Waiter signalling is handled by the internal FIFO queue; each waiter is still signalled individually.
    * `RWCondition` utilizes a `deque` with micro-locks, and `AsyncRWCondition` utilizes a native `deque` of `asyncio.Future` objects to provide amortized O(1) FIFO enqueue/dequeue. `notify_all()` and arbitrary waiter removal take O(N).
* **Condition Smart Proxies & Downgrade Safety**:
    * Implemented `.read` and `.write` proxies for Condition objects (`RWConditionProxy`, `AsyncRWConditionProxy`).
    * The Smart Proxy intelligently routes the release operations back to the correct state even if an **Atomic Downgrade** was performed while holding a lock inside a condition block.
* **Cancellation Cleanup (Asyncio)**:
    * Re-engineered `AsyncRWConditionProxy.wait()` to reacquire the lock before propagating `asyncio.CancelledError` when a waiting task is cancelled.
* **Advanced Benchmark Suite for Conditions**:
    * Added comprehensive "Cache Stampede Simulators" (`PubSubScenario` & `ReaderWriterConditionScenario`) to measure event loop queuing, task wake-up latency, and stampede protection.
    * Observed up to **70x** end-to-end workload throughput against standard condition baselines in a (1 Writer, 100 Readers) workload. This compares different lock semantics and does not isolate notification speed.
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
