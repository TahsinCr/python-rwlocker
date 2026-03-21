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

`rwlocker`, on the other hand, is based on a **Shared** reading logic. While writer locks are exclusive, reader locks allow thousands of threads or tasks to access data simultaneously without blocking each other. It unleashes the true potential of the system, especially during I/O (Network/Disk/Database) operations where the GIL (Global Interpreter Lock) is released.

### 🚀 What about Condition Variables?
Standard `Condition` structures in the library wake up all waiting threads/tasks with an O(N) time complexity (scanning them one by one) when `notify_all()` is called. This creates a **"Cache Stampede"** that locks up the processor in scenarios where hundreds of readers wake up simultaneously. `rwlocker` operates entirely on a `deque` (Thread) and `dict` (Asyncio) based queue architecture. It eliminates stampedes at the architectural level by waking up waiting tasks with pure **O(1) time complexity** without blocking the OS or event-loop.

### ✨ Key Features

* **Both Thread and Asyncio Support:** You can manage both standard OS threads (`rwlocker.thread_rwlock`) and event-loop based tasks (`rwlocker.async_rwlock`) using the exact same API logic.
* **Smart Proxy Architecture:** Intuitive usage of `with` and `async with` context managers via `.read` and `.write` proxies.
* **Atomic Downgrading:** The ability to instantly downgrade a Write lock to a Read lock (`downgrade()`) without completely releasing the lock, preventing other writers from slipping in.
* **Safe Reentrancy:** O(1) memory pointer tracking allowing the same thread or task to repeatedly acquire a write lock without causing a Deadlock.
* **Cancellation Safety:** Full resilience against task cancellations (`CancelledError`) in the `asyncio` environment. Cancelled tasks do not corrupt the system state and safely wake up waiting tasks.
* **O(1) Condition Queuing (Stampede Protection):** Unlike standard libraries, it does not perform O(N) scanning on `notify_all()` calls. It wakes up hundreds of tasks instantly without choking the CPU.
* **Smart Signaling:** The ability to accurately wake up only the exact number of tasks you need, such as `notify(n=5)`, without creating a "Thundering Herd" in the system.
* **Flawless Cancellation Shielding:** If a task is cancelled from the outside (`CancelledError`) while waiting in an asynchronous `Condition.wait()`, the lock state is never corrupted. The lock is safely re-acquired and passed on to other waiters.
* **100% Drop-in Replacement:** You can inject your advanced locks (`RWLockFair`, etc.) directly into third-party libraries (SQLAlchemy, requests, FastAPI, etc.) expecting standard `threading.Lock` or `asyncio.Lock` instances without making any code changes. Standard API calls (e.g., `lock.acquire()`) are automatically and safely routed to the `.write` (exclusive) proxy.
* **"Happy Path" Performance Isolation:** A next-generation, OS-Interrupt-resilient micro-queue architecture that completely bypasses O(N) cost cleanup operations upon successful lock wake-ups, completing the process with zero CPU overhead.
* **Standard Adapters:** `Lock`, `Condition`, `AsyncLock`, and `AsyncCondition` standard wrapper classes for dependency injections where advanced RWLock features are not required but the same architectural signature (`.read`, `.write`) is desired.

### 🛡️ Lock Strategies

You can select the right lock strategy based on your system's bottleneck profile. Each strategy has a `ReentrantWriter` variant that allows for reentrancy.

| Strategy Type | Class Name (Thread / Async) | Description | When to Use? |
| --- | --- | --- | --- |
| **Writer-Preferring** | `RWLockWrite` / `AsyncRWLockWrite` | Forbids new readers from entering if there is a waiting writer. Prevents writer starvation. | To prevent writers from being overwhelmed in read-heavy systems. |
| **Reader-Preferring** | `RWLockRead` / `AsyncRWLockRead` | Continuously allows new readers in, even if writers are waiting. Provides maximum parallelism. | In cache structures where write operations are very rare or non-critical. |
| **Fair** | `RWLockFair` / `AsyncRWLockFair` | Grants access alternately between readers and writers (interleaving). Prevents starvation for both sides. | In high-frequency, bidirectional traffic (MAVLink, WebSockets, etc.). |
> 💡 **Condition Compatibility:** The `RWCondition` and `AsyncRWCondition` classes in the library are designed to encapsulate all the lock strategies mentioned above (Dependency Injection). You can choose the lock that best fits your system and transform it into a state machine running at pure O(1) speed.
<br/>

## ⚙️ Architectural Limitations

Engineering facts developers need to know when using this library:

1. **The CPU-Bound vs I/O-Bound Reality:**
`rwlocker` derives its power from the moments when Python's GIL (Global Interpreter Lock) is released (Network requests, Database queries, File I/O, etc.). If you are looking for a lock for purely heavy mathematical computations (CPU-Bound) that do not involve I/O yields like `time.sleep()`, you will not achieve true parallelism due to the GIL, and the C-based standard `threading.Lock` will be slightly faster. **RWLock's true battlefield is I/O operations.**
2. **Circular References:**
Lock classes establish a circular reference graph (Lock -> Proxy -> Lock) when creating smart proxy objects (`.read` and `.write`). This design is intentional. Memory cleanup (Garbage Collection) is safely handled by Python's Cyclic GC engine, not by `__del__`.
3. **Strict Nested Write Locks:**
In `ReentrantWriter` variants, only "Write" locks can be nested. If a writer wants to acquire a reader lock, it cannot do so implicitly; it must explicitly call the `.downgrade()` method. This is a strict architectural decision made to prevent deadlocks at the structural level.
4. **The Cost of Fairness:**
If you use the `Fair` strategy, the system forces a strict order-based context switch between readers and writers to guarantee that no one starves (No Starvation). Especially in **`RWCondition`** uses and write-heavy scenarios, this effort to maintain fair order causes a certain slowdown compared to the standard, rule-less C-based `Condition` object (this is why Fair scores 0.50x in benchmarks). This is not a bug or a lack of optimization; it is the engineering price paid to ensure "fairness".
5. **Condition Memory vs CPU Trade-off:**
While a standard `threading.Condition` keeps a simple C-level counter in the background, `rwlocker` stores a tiny `Lock` or `asyncio.Future` object in memory for each waiting task/thread to guarantee O(1) wake-up speed. This completely resolves CPU bottlenecks (Cache Stampede), but in extreme cases where tens of thousands of tasks are waiting, it creates a small memory footprint in RAM.
6. **Drop-in Security Assumption:**
If you use the lock objects directly like a standard lock without specifying the `.read` or `.write` proxies (e.g., `with lock:` or `await cond.wait()`), the system automatically acquires the **Write (Exclusive)** lock to ensure backward compatibility and absolute data security. This is a "Secure by Default" approach established to prevent external libraries from corrupting data.

<br/>

## 📊 Performance and Benchmark Results

The benchmarks below demonstrate `rwlocker`'s true potential during Network and Database I/O operations where Python's GIL (Global Interpreter Lock) is released or context-switched. 

**🖥️ Test Environment:** All tests were executed on an **Intel Core i7-12700H (2.4GHz)** processor running **EndeavourOS (Arch-based Linux)**, using **Python 3.14.3** and the experimental **Free-Threading (3.14.3t)** interpreters.

**🧪 Methodology:** To ensure absolute precision and zero margin of error, all reader and writer entities (threads or async tasks) are spawned in advance and held at a starting line using a synchronization `Event`. Once the event triggers, they execute simultaneously. The workloads strictly follow an `IOBoundScenario` that enforces a precise `time.sleep(0.001)` or `asyncio.sleep(0.001)` delay to accurately simulate real network/database I/O latency.

### 1. Read-Write Lock (RWLock) Benchmarks

Standard locks force threads to queue single-file even if they are only reading data. `rwlocker` unleashes concurrent read access.

**Synchronous (Thread) RWLock Performance:**
In the Read-Heavy scenario, standard C-based locks choke the system, whereas `rwlocker` achieves up to **~35x speedup**. Even in Write-Heavy workloads where parallelism isn't inherently possible, `rwlocker` matches or slightly outperforms the C-baseline thanks to its zero-allocation fast-paths.
<p align="center">
  <img src="./figures/sync_rwlock.svg" alt="Sync RWLock Benchmark" width="100%"/>
</p>
<br>

**Asynchronous (Asyncio) RWLock Performance:**
Since asynchronous tasks run concurrently on a single event loop, interpreter modes (GIL on/off) do not drastically change the results. Thus, the async metrics showcase the highest performing baseline. Here, `rwlocker` achieves **~30x faster throughput** by allowing thousands of reader tasks to await I/O simultaneously without blocking one another.
<p align="center">
  <img src="./figures/async_rwlock.svg" alt="Async RWLock Benchmark" width="100%"/>
</p>
<br>

### 2. Condition Variable (RWCondition) Benchmarks

Standard `Condition` variables iterate through all sleeping threads/tasks one by one `O(N)` during a broadcast (`notify_all`), causing massive CPU spikes and "Cache Stampedes". `rwlocker` completely eradicates this with its pure `O(1)` queueing architecture.

**Synchronous (Thread) RWCondition Performance:**
When 100 sleeping readers are awakened simultaneously, `rwlocker` processes them instantly without locking the OS. This architectural leap results in a mind-blowing **~45x speedup** compared to the standard library's `threading.Condition`.
<p align="center">
  <img src="./figures/sync_rwcondition.svg" alt="Sync RWCondition Benchmark" width="100%"/>
</p>
<br>

**Asynchronous (Asyncio) RWCondition Performance:**
In event-driven caching systems, waking up hundreds of waiting web requests simultaneously is a major bottleneck. The `AsyncRWCondition` completely bypasses standard asyncio constraints, reaching up to **~45x higher throughput** during massive broadcast scenarios, completely saving the loop from freezing.
<p align="center">
  <img src="./figures/async_rwcondition.svg" alt="Async RWCondition Benchmark" width="100%"/>
</p>
<br>

*(Note: All lock, adapter, and condition classes have passed a massive suite of **315 different unit tests** covering reentrancy, deadlock, timeout, OS interrupts, O(N) leaks, and cancellation safety scenarios with 0 errors, and this entire test suite was completed in just **13.2 seconds**.)*

<br/>

## 🚀 Getting Started

### 🛠️ Dependencies

* No external dependencies.
* Only Python Standard Library (`threading`, `asyncio`, `typing`, `collections`).
* Fully compatible with Python 3.9+.

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

Prevents readers from waiting for each other in a web server handling thousands of requests.

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
            # Since we downgraded, we must now release the READ lock.
            self._lock.read.release()

    def _dispatch_audit_event(self, balance: float):
        print(f"Audit Report Dispatched. New Balance: {balance}")


```

#### 3. JWT Token Refresh (Thundering Herd Solution)

Prevents hundreds of tasks waking up simultaneously to refresh an expired token (Thundering Herd stampede) from crashing the auth server.

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

Data arrives from a sensor 100 times per second (Write), and 200 WebSockets read this data (Read). The Fair architecture prevents both sides from starving.

```python
import asyncio
from typing import Dict
from rwlocker.async_rwlock import AsyncRWLockFair

class TelemetryDispatcher:
    def __init__(self):
        # Fair prevents read and write intensities from choking each other.
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

If thousands of tasks try to fetch an expired token from the database simultaneously, the DB crashes. With `AsyncRWCondition`, while 1 task updates the data, the other 999 tasks safely sleep without choking the CPU (at O(1) speed) and are awakened all at once afterward.

```python
import asyncio
from rwlocker.async_rwlock import AsyncRWLockRead, AsyncRWCondition

class GlobalConfigCache:
    def __init__(self):
        # We use a Read-Pref lock because reading is extremely dense
        self._cond = AsyncRWCondition(AsyncRWLockRead())
        self._config = {}
        self._is_refreshing = False

    async def get_config(self) -> dict:
        """Called by thousands of concurrent requests."""
        async with self._cond.read:
            # If a DB update is in progress, sleep and wait safely instead of hammering the DB.
            # The wait_for method automatically handles Spurious Wakeup scenarios.
            await self._cond.read.wait_for(lambda: not self._is_refreshing)
            return self._config

    async def force_refresh_from_db(self) -> None:
        """Runs exclusively when triggered via a webhook."""
        async with self._cond.write:
            self._is_refreshing = True
            
            await asyncio.sleep(0.5) # Slow Database query simulation
            self._config = {"theme": "dark", "version": 2}
            self._is_refreshing = False
            
            # Wakes up THOUSANDS of waiting reader tasks at O(1) speed. No stampede!
            self._cond.write.notify_all()
```


#### 6. Precise Job Queue (Thread Condition & Targeted Wake-up)

When 3 new jobs arrive in the system, instead of waking up all 50 idle worker threads ("Thundering Herd" problem), it performs targeted wake-ups by calling just `notify(n=3)`.

```python
from collections import deque
import threading
from rwlocker.thread_rwlock import RWLockFair, RWCondition

class ImageProcessingQueue:
    def __init__(self):
        # Fair strategy to prevent Producers and Consumers from crushing each other
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
        with self._cond.read:
            # Wait safely if there are no jobs in the queue
            self._cond.read.wait_for(lambda: len(self._queue) > 0)
            job = self._queue.popleft()

        # Perform the heavy processing AFTER releasing the lock.
        print(f"Processing: {job}")

```

#### 7. 100% Drop-in Replacement Compatibility

Inject the power of `rwlocker` into your system without changing your legacy code or third-party libraries that expect a standard `threading.Lock` or `asyncio.Lock`.

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

> ⚠️ **Important Developer Note:** The `rwlocker` architecture is highly sensitive to *deadlock*, *OS-Interrupts*, and *reentrancy* scenarios. Before opening a PR, please ensure that all **315+ unit tests** in the project pass flawlessly and that your code complies with **Python 3.9+** standards.

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
