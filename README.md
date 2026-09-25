[![Contributors][contributors-shield]][contributors-url]
[![Forks][forks-shield]][forks-url]
[![Stargazers][stars-shield]][stars-url]
[![Issues][issues-shield]][issues-url]
[![MIT License][license-shield]][license-url]
[![LinkedIn][linkedin-shield]][linkedin-url]

[English][lang-en-url] | [Türkçe][lang-tr-url] | [Русский][lang-ru-url]



<!-- About -->
<div align="center">


<h3 align="center">Python RWLocker</h3>

<p align="center">

Advanced, High-Performance, and State-Machine Based Synchronous/Asynchronous Read-Write Locks.

[Changelog][changelog-url] · [Report Bug][issues-url] · [Request Feature][issues-url]
 
</p>

</div>

<br/>

## 📋 About the Project

### 🚀 Why RWLocker?

Standard locks in Python (`Lock`, `RLock`) are **Exclusive** locks. Even if 100 readers (e.g., threads fetching data from a database) arrive at the gate, they are forced to execute these operations sequentially, one by one.

`rwlocker`, on the other hand, is based on a **Shared** reading logic. While writer locks are exclusive, reader locks allow multiple threads or tasks to access data concurrently when their critical sections permit shared access. This can improve throughput when shared critical sections spend time in I/O or otherwise yield, but it does not guarantee a speedup for every workload.

### 🚀 What about Condition Variables?
`rwlocker` conditions keep waiters in `collections.deque` queues. Enqueue and FIFO dequeue are amortized O(1); notifying N waiters is O(N), because each waiter must be signalled. Removing a timed-out or cancelled waiter can also take O(N). The queue operations do not block the event loop while a task is waiting.

### ✨ Key Features

* **Both Thread and Asyncio Support:** You can manage both standard OS threads (`rwlocker.thread_rwlock`) and event-loop based tasks (`rwlocker.async_rwlock`) using corresponding synchronous and asynchronous interfaces.
* **Smart Proxy Architecture:** Intuitive usage of `with` and `async with` context managers via `.read` and `.write` proxies.
* **Atomic Downgrading:** The ability to instantly downgrade a Write lock to a Read lock (`downgrade()`) without completely releasing the lock, preventing other writers from slipping in.
* **Writer Reentrancy:** `ReentrantWriter` variants allow the owning thread or task to acquire nested write locks and a read lock; other readers join only after `.downgrade()` opens shared access. A current reader may reacquire `.read` while writers wait; acquiring `.write` while holding `.read` raises `RuntimeError` to prevent self-deadlock.
* **Queued Condition Waiters:** Waiters are stored in FIFO deques. Normal enqueue/dequeue operations are amortized O(1); notifying all waiters and removing an arbitrary timed-out waiter are O(N).
* **Async Cancellation Cleanup:** Cancellation removes a task's waiter and condition waits reacquire the associated lock before propagating cancellation.
* **Lock-Style Interface:** Direct lock operations use the exclusive `.write` proxy. Shared locking is available through `.read`; some signatures and observable behavior differ from the standard lock classes, so compatibility should be checked for each integration.
* **Uncontended Fast Paths:** An uncontended acquisition does not allocate a waiter object. Contended acquisition and notification still perform normal Python and scheduler work.
* **Standard Adapters:** Provides lock and condition wrappers with the same high-level `.read` and `.write` access shape for Dependency Injection workflows that do not need the RWLock scheduling strategies.
    * *Lock Adapters:* `Lock` (Thread), `AsyncLock` (Asyncio)
    * *Condition Adapters:* `Condition` (Thread), `AsyncCondition` (Asyncio)

### 🛡️ Lock Strategies

You can select the right lock strategy based on your system's bottleneck profile. Each strategy has a `ReentrantWriter` variant that allows for reentrancy.

| Strategy Type | Class Name (Thread / Async) | Description | When to Use? |
| --- | --- | --- | --- |
| **Writer-Preferring** | `RWLockWrite` / `AsyncRWLockWrite` | Forbids new readers from entering if there is a waiting writer. Prioritizes waiting writers and can reduce writer starvation while they continue making progress. | To prevent writers from being overwhelmed in read-heavy systems. |
| **Reader-Preferring** | `RWLockRead` / `AsyncRWLockRead` | Continuously allows new readers in, even if writers are waiting. Provides maximum parallelism. | In cache structures where write operations are very rare or non-critical. |
| **Reader-Phase Fair** | `RWLockReaderPhaseFair` / `AsyncRWLockReaderPhaseFair` | Alternates between reader and writer phases, but late readers may still join an already-open reader phase for higher read throughput. | When you want bounded fairness without fully freezing each reader batch. |
| **Fair** | `RWLockFair` / `AsyncRWLockFair` | Freezes each reader phase at phase start so late readers cannot cut in front of an already-queued writer. Designed to reduce starvation when lock holders continue to make progress. | In bidirectional traffic where ordered writer access matters. |
> 💡 **Condition Compatibility:** `RWCondition` and `AsyncRWCondition` accept the lock strategies above. Choose a strategy based on its reader/writer scheduling behavior.
<br/>

## ⚙️ Architectural Limitations

Engineering facts developers need to know when using this library:

Set `RWLOCKER_PYTHON_STANDARD` and `RWLOCKER_PYTHON_FREE_THREADED` to choose interpreters for benchmark collection.

1. **The CPU-Bound vs I/O-Bound Reality:**
`rwlocker` derives its power from the moments when Python's GIL (Global Interpreter Lock) is released (Network requests, Database queries, File I/O, etc.). If you are looking for a lock for purely heavy mathematical computations (CPU-Bound) that do not involve I/O yields like `time.sleep()`, you will not achieve true parallelism due to the GIL, and a standard `threading.Lock` may have lower acquisition overhead. These locks are most useful when read sections can overlap while waiting for I/O or other operations that yield.
2. **Circular References:**
Lock classes establish a circular reference graph (Lock -> Proxy -> Lock) when creating smart proxy objects (`.read` and `.write`). This design is intentional. Memory cleanup (Garbage Collection) is safely handled by Python's Cyclic GC engine, not by `__del__`.
3. **Reentrant Writer Behavior:**
`ReentrantWriter` variants allow the owning thread/task to acquire nested write locks and a read lock. Other readers can join only after `.downgrade()` opens shared access. A current reader may reacquire `.read` while writers wait; acquiring `.write` while holding `.read` raises `RuntimeError` to prevent self-deadlock.
4. **The Cost of Fairness:**
The `Fair` strategy schedules queued readers and writers in phases to reduce starvation while participants continue making progress. This ordering can reduce throughput in some workloads. In the recorded condition workload, the Fair variant was slower than the exclusive-lock standard `threading.Condition` baseline; that comparison includes different locking semantics and does not isolate fairness overhead.
5. **Condition Queue Costs:**
Each waiting thread/task has a waiter object. `notify_all()` signals every waiter and therefore takes O(N) time; arbitrary timeout/cancellation removal also takes O(N). Memory use grows with the number of waiters. `Condition.wait()` requires exactly one lock acquisition; nested acquisition depths raise `RuntimeError` because recursive depth is not saved and restored.
6. **Exclusive Fallback:**
Direct lock operations (such as `with lock:`) use the exclusive write proxy. This is a concurrency default, not a security boundary; use `.read` and `.write` explicitly when access mode matters.

<br/>

## 📊 Performance and Benchmark Results

The charts below report end-to-end results for the included network/database-style I/O workloads. They compare complete workloads and do not isolate lock acquisition or notification cost.

**🖥️ Test Environment:** All tests were executed on an **Intel Core i7-12700H (2.4GHz)** processor running **EndeavourOS (Arch-based Linux)**, using **Python 3.14.3** and the experimental **Free-Threading (3.14.3t)** interpreters.

**🧪 Methodology:** Workers are created before the timed run and released through a synchronization barrier/event. I/O-bound scenarios use a 1 ms sleep per operation for 10 iterations. Results are workload measurements and can vary with scheduling, interpreter, and machine load; they do not have zero measurement error. Reporting runs store each elapsed time, variance, median absolute deviation, quartiles, and a bootstrap 95% confidence interval for the mean.

### 1. Read-Write Lock (RWLock) Benchmarks

Standard locks force threads to queue single-file even if they are only reading data. `rwlocker` unleashes concurrent read access.

**Synchronous (Thread) RWLock Performance:**
In the committed read-heavy workload data, shared readers complete sooner than readers serialized by a standard exclusive lock (up to ~35x in the recorded run). This measures workload completion time from different locking semantics, not primitive acquisition speed. The write-heavy results are workload-specific and are not evidence of a general speed advantage.
<p align="center">
  <img src="./figures/sync_rwlock.svg" alt="Sync RWLock Benchmark" width="100%"/>
</p>
<br>

**Asynchronous (Asyncio) RWLock Performance:**
Asynchronous tasks run on one event loop in this benchmark. The plots show the available interpreter environments rather than selecting the best result. Read-heavy throughput reflects the ability of multiple readers to await I/O concurrently.
<p align="center">
  <img src="./figures/async_rwlock.svg" alt="Async RWLock Benchmark" width="100%"/>
</p>
<br>

### 2. Condition Variable (RWCondition) Benchmarks

These condition benchmarks measure end-to-end read/write workload throughput, including shared-read concurrency, predicate checks, scheduling, and the simulated I/O. They do not isolate `notify_all()` overhead. The queue signals each waiter, so `notify_all()` is O(N).

**Synchronous (Thread) RWCondition Performance:**
The recorded ~45x result compares the complete RWCondition workload with the exclusive-lock `threading.Condition` baseline. It does not mean that `notify_all()` itself is 45x faster.
<p align="center">
  <img src="./figures/sync_rwcondition.svg" alt="Sync RWCondition Benchmark" width="100%"/>
</p>
<br>

**Asynchronous (Asyncio) RWCondition Performance:**
The async condition result is also an end-to-end workload comparison, not a measurement of isolated notification cost. The event loop still processes each waiter.
<p align="center">
  <img src="./figures/async_rwcondition.svg" alt="Async RWCondition Benchmark" width="100%"/>
</p>
<br>

The test suite covers lock strategies, conditions, timeouts, reentrancy, and cancellation. Passing tests are useful regression evidence, but do not by themselves prove correctness for every schedule or workload.

<br/>

## 🚀 Getting Started

### 🛠️ Dependencies

* No runtime dependencies.
* Optional benchmark plotting: `pip install rwlocker[benchmark]`.
* Only Python Standard Library (`threading`, `asyncio`, `typing`, `collections`).
* Supports Python 3.9–3.14; these versions are included in the CI test matrix.

### 📦 Installation

The library has zero external dependencies and works directly with Python's core libraries.

1. Clone the repository
    ```sh
    git clone https://github.com/TahsinCr/python-rwlocker.git
    ```

2. Install via PIP
    ```sh
    pip install rwlocker
    ```

<br/>

### 💻 Usage Examples

#### 1. High-Concurrency In-Memory Cache (Read-Heavy)

Allows independent readers to proceed concurrently in a web server workload.

```python
import threading
import time
from typing import Any, Dict, Optional
from rwlocker.thread_rwlock import RWLockRead

class InMemoryCache:
    def __init__(self):
        self._lock = RWLockRead()
        self._cache: Dict[str, Any] = {}

    def get(self, key: str) -> Optional[Any]:
        # Readers NEVER block each other, maximizing throughput!
        with self._lock.read:
            time.sleep(0.01) # Network or Serialization (I/O) simulation
            return self._cache.get(key)

    def set(self, key: str, value: Any) -> None:
        # Acquires an exclusive write lock. Safely pauses new readers.
        with self._lock.write:
            self._cache[key] = value

# USAGE
cache = InMemoryCache()
cache.set("status", "ONLINE")

# These 50 threads can read simultaneously without waiting.
threads = [threading.Thread(target=cache.get, args=("status",)) for _ in range(50)]
for t in threads: t.start()


```

#### 2. Atomic State Downgrading in Financial Ledgers

Perfect for updating data (Write) and immediately reading/auditing the same data (Read) without letting another writer slip in between.

```python
import uuid
from rwlocker.thread_rwlock import RWLockWriteReentrantWriter

class TransactionLedger:
    def __init__(self):
        self._lock = RWLockWriteReentrantWriter()
        self._balance = 1000.0

    def process_payment(self, amount: float):
        self._lock.write.acquire()
        try:
            # PHASE 1: Exclusive Write (Update balance)
            self._balance += amount
            
            # ATOMIC DOWNGRADE: Write Lock is downgraded to Read Lock.
            # Waiting readers are allowed in, but other WRITERS are strictly blocked.
            self._lock.write.downgrade()
            
            # PHASE 2: Shared Read (Broadcast to other services over network)
            self._dispatch_audit_event(self._balance)
            
        finally:
            # The writer proxy routes release to read after downgrade and
            # still releases write correctly if an earlier operation failed.
            self._lock.write.release()

    def _dispatch_audit_event(self, balance: float):
        print(f"Audit Report Dispatched. New Balance: {balance}")


```

#### 3. JWT Token Refresh (Thundering Herd Solution)

Coordinates concurrent tasks that need to refresh an expired token.

```python
import asyncio
from rwlocker.async_rwlock import AsyncRWLockWrite

class AuthTokenManager:
    def __init__(self):
        self._lock = AsyncRWLockWrite()
        self._token = "valid_token"
        self._is_expired = False

    async def get_valid_token(self) -> str:
        # Fast Path: If the token is valid, 500 tasks pass through here concurrently without waiting.
        async with self._lock.read:
            if not self._is_expired:
                return self._token
                
        # Slow Path: Token expired. Acquire write lock.
        async with self._lock.write:
            # Double-checked locking: While we were waiting for the lock, 
            # another task might have entered and refreshed the token.
            if self._is_expired:
                print("Refreshing token...")
                await asyncio.sleep(0.5)  # API Request
                self._token = "new_valid_token"
                self._is_expired = False
                
            return self._token


```

#### 4. High-Frequency Telemetry (Fair Distribution)

Data arrives from a sensor 100 times per second (Write), and 200 WebSockets read this data (Read). The Fair architecture is intended to reduce starvation risk while lock holders continue making progress.

```python
import asyncio
from typing import Dict
from rwlocker.async_rwlock import AsyncRWLockFair

class TelemetryDispatcher:
    def __init__(self):
        # Fair schedules queued readers and writers in phases while holders continue making progress.
        self._lock = AsyncRWLockFair()
        self._state = {"alt": 0.0, "lat": 0.0, "lon": 0.0}

    async def ingest_sensor_data(self, new_data: Dict[str, float]):
        """Writes incoming data from high-frequency UDP stream."""
        async with self._lock.write:
            self._state.update(new_data)
            await asyncio.sleep(0.001)

    async def broadcast_to_clients(self):
        """Reads data concurrently for dozens of websocket clients."""
        async with self._lock.read:
            # Safely copy the state quickly to minimize lock holding time
            current_state = self._state.copy()
            
        # Perform slow network I/O operations while the lock is released
        await self._network_send(current_state)

    async def _network_send(self, data):
        await asyncio.sleep(0.05) # Network latency simulation


```

#### 5. Event-Driven Cache Refresh (Thundering Herd Protection)

Condition waiters sleep without blocking the event loop. `notify_all()` signals each waiter and has O(N) cost; total workload throughput also depends on reader concurrency and task scheduling.

```python
import asyncio
from rwlocker.async_rwlock import AsyncRWLockRead, AsyncRWCondition

class GlobalConfigCache:
    def __init__(self):
        # We use a Read-Pref lock because reading is extremely dense
        self._cond = AsyncRWCondition(AsyncRWLockRead())
        self._config = {"theme": "light", "version": 1}
        self._is_refreshing = False

    async def get_config(self) -> dict:
        """Called by concurrent requests."""
        async with self._cond.read:
            # If a DB update is in progress, sleep and wait safely instead of hammering the DB.
            # The wait_for method automatically handles Spurious Wakeup scenarios.
            await self._cond.read.wait_for(lambda: not self._is_refreshing)
            return dict(self._config)

    async def force_refresh_from_db(self) -> None:
        """Serializes refresh requests triggered via a webhook."""
        async with self._cond.write:
            await self._cond.write.wait_for(lambda: not self._is_refreshing)
            self._is_refreshing = True

        try:
            # Simulate a slow database query without holding the lock.
            await asyncio.sleep(0.5)
            async with self._cond.write:
                self._config = {"theme": "dark", "version": self._config["version"] + 1}
                self._is_refreshing = False
                # Signals each queued waiter (O(N)).
                self._cond.write.notify_all()
        except BaseException:
            async with self._cond.write:
                if self._is_refreshing:
                    self._is_refreshing = False
                    self._cond.write.notify_all()
            raise
```


#### 6. Precise Job Queue (Thread Condition & Targeted Wake-up)

When 3 new jobs arrive in the system, instead of waking up all 50 idle worker threads ("Thundering Herd" problem), it performs targeted wake-ups by calling just `notify(n=3)`.

```python
from collections import deque
import threading
from rwlocker.thread_rwlock import RWLockFair, RWCondition

class ImageProcessingQueue:
    def __init__(self):
        # Fair strategy to schedule waiting producers and consumers in phases
        self._cond = RWCondition(RWLockFair())
        self._queue = deque()

    def add_jobs(self, jobs: list[str]):
        """Producer: Adds new jobs to the queue."""
        with self._cond.write:
            self._queue.extend(jobs)
            
            # SMART SIGNAL: Only wake up as many Threads as there are new jobs.
            # Other sleeping Threads in the system won't waste CPU cycles.
            self._cond.write.notify(n=len(jobs))

    def consume_job(self):
        """Consumer: Sleeps until a job arrives, then picks it up."""
        with self._cond.write:
            # Wait safely if there are no jobs in the queue
            self._cond.write.wait_for(lambda: len(self._queue) > 0)
            job = self._queue.popleft()

        # Perform the heavy processing AFTER releasing the lock.
        print(f"Processing: {job}")

```

#### 7. Lock-Style Interface Compatibility

Direct lock methods route to the exclusive `.write` proxy. Check method signatures and observable semantics before passing an instance to code written for standard lock or condition classes; `.read` and `.write` expose the modes explicitly.

```python
import threading
from rwlocker.thread_rwlock import RWLockFair, Lock

# Scenario: A third-party function expects a standard threading.Lock
def third_party_worker(standard_lock: threading.Lock, data: list):
    # The external library doesn't know about ".write" or ".read" proxies.
    # It directly uses "with lock:".
    with standard_lock:
        data.append("Processed")
        print("Lock acquired via standard API!")

# METHOD 1: You can pass an advanced RWLock object directly!
# RWLockFair detects these calls and automatically switches to the 
# .write (exclusive) mode because it is the safest assumption.
advanced_lock = RWLockFair()
third_party_worker(advanced_lock, [])

# METHOD 2: If you only need standard lock behavior, 
# you can use standard adapters that share the same signature.
simple_adapter_lock = Lock()
third_party_worker(simple_adapter_lock, [])
```

*For more examples, please check the [examples][examples-url] directory.*

See the [open issues][issues-url] for a full list of proposed features (and known issues).

<br/>

## 🤝 Contributing

The open-source community is the perfect place to push the boundaries of such low-level, high-performance libraries. Any contributions you make to render `rwlocker` faster, safer, or more capable are greatly appreciated!

We are especially looking forward to your contributions in the following areas:

* ⚡ **Performance Optimizations:** Algorithmic approaches that will further reduce overhead costs.
* 🏗️ **Scenario-Specific Enhancements:** Creating and developing variants of lock engines optimized for different scenarios.
* 🐛 **Edge-Case Testing:** New and rigorous unit tests to detect deadlock or starvation scenarios.

If you have a great idea or solution, please follow the steps below to create a **Pull Request (PR)**. You can also open an Issue with the "enhancement" tag to suggest a new feature.

Don't forget to give the project a **Star (⭐)** on the top right if you found it useful. Thanks for your support!

### 🛠️ Contribution Steps

1. **Fork** the project to your own account.
2. Create your Feature Branch:
```sh
git checkout -b feature/AmazingFeature

```


3. **Commit** your changes (Make sure to use descriptive messages):
```sh
git commit -m 'feat: Added a new O(1) cost optimization for AsyncRWLock'

```


4. **Push** to the Branch:
```sh
git push origin feature/AmazingFeature

```


5. Open a **Pull Request** on this repository.

> ⚠️ **Important Developer Note:** The `rwlocker` architecture is highly sensitive to *deadlock*, *OS-Interrupts*, and *reentrancy* scenarios. Before opening a PR, run the test suite on the supported Python versions listed in CI and review concurrency changes for scheduling-dependent behavior.

<br/>

## 🙏 Acknowledgments and License

This project is fully open-source under the **MIT License** ([License][license-url]).

Thanks to the entire Python open-source community for helping us face the deepest realities of the Python C-API during the development of testing and benchmark architectures.

* **PyPI:** [RWLocker on PyPI][pypi-project-url]
* **Source Code:** [Tahsincr/python-rwlocker][project-url]

If you find any bugs or want to make an architectural contribution, feel free to open an Issue or submit a Pull Request on GitHub!

<br/>


## 📫 Contact

X: [@TahsinCrs][x-url]

Linkedin: [@TahsinCr][linkedin-url]

Email: TahsinCrs@gmail.com


<!-- IMAGES URL -->

[contributors-shield]: https://img.shields.io/github/contributors/TahsinCr/python-rwlocker.svg?style=for-the-badge

[forks-shield]: https://img.shields.io/github/forks/TahsinCr/python-rwlocker.svg?style=for-the-badge

[stars-shield]: https://img.shields.io/github/stars/TahsinCr/python-rwlocker.svg?style=for-the-badge

[issues-shield]: https://img.shields.io/github/issues/TahsinCr/python-rwlocker.svg?style=for-the-badge

[license-shield]: https://img.shields.io/github/license/TahsinCr/python-rwlocker.svg?style=for-the-badge

[linkedin-shield]: https://img.shields.io/badge/-LinkedIn-black.svg?style=for-the-badge&logo=linkedin&colorB=555



<!-- Github Project URL -->

[project-url]: https://github.com/TahsinCr/python-rwlocker

[pypi-project-url]: https://pypi.org/project/rwlocker

[contributors-url]: https://github.com/TahsinCr/python-rwlocker/graphs/contributors

[stars-url]: https://github.com/TahsinCr/python-rwlocker/stargazers

[forks-url]: https://github.com/TahsinCr/python-rwlocker/network/members

[issues-url]: https://github.com/TahsinCr/python-rwlocker/issues

[examples-url]: https://github.com/TahsinCr/python-rwlocker/tree/main/examples

[license-url]: https://github.com/TahsinCr/python-rwlocker/blob/main/LICENSE

[changelog-url]:https://github.com/TahsinCr/python-rwlocker/blob/main/CHANGELOG.md



<!-- Contacts URL -->

[linkedin-url]: https://linkedin.com/in/TahsinCr

[x-url]: https://twitter.com/TahsinCrs



<!-- File URL -->

[lang-tr-url]: https://github.com/TahsinCr/python-rwlocker/blob/main/README_tr.md

[lang-en-url]: https://github.com/TahsinCr/python-rwlocker/blob/main/README.md

[lang-ru-url]: https://github.com/TahsinCr/python-rwlocker/blob/main/README_ru.md
