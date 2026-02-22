[![Contributors][contributors-shield]][contributors-url]
[![Forks][forks-shield]][forks-url]
[![Stargazers][stars-shield]][stars-url]
[![Issues][issues-shield]][issues-url]
[![MIT License][license-shield]][license-url]
[![LinkedIn][linkedin-shield]][linkedin-url]

[English][lang-en-url] | [Türkçe][lang-tr-url]



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

### ✨ Key Features

* **Both Thread and Asyncio Support:** You can manage both standard OS threads (`rwlocker.thread_rwlock`) and event-loop based tasks (`rwlocker.async_rwlock`) using the exact same API logic.
* **Smart Proxy Architecture:** Intuitive usage of `with` and `async with` context managers via `.read` and `.write` proxies.
* **Atomic Downgrading:** The ability to instantly downgrade a Write lock to a Read lock (`downgrade()`) without completely releasing the lock, preventing other writers from slipping in.
* **Safe Reentrancy:** O(1) memory pointer tracking allowing the same thread or task to repeatedly acquire a write lock without causing a Deadlock.
* **Cancellation Safety:** Full resilience against task cancellations (`CancelledError`) in the `asyncio` environment. Cancelled tasks do not corrupt the system state and safely wake up waiting tasks.

### 🛡️ Lock Strategies

You can select the right lock strategy based on your system's bottleneck profile. Each strategy has a `SafeWriter` variant that allows for reentrancy.

| Strategy Type | Class Name (Thread / Async) | Description | When to Use? |
| --- | --- | --- | --- |
| **Writer-Preferring** | `RWLockWrite` / `AsyncRWLockWrite` | Forbids new readers from entering if there is a waiting writer. Prevents writer starvation. | To prevent writers from being overwhelmed in read-heavy systems. |
| **Reader-Preferring** | `RWLockRead` / `AsyncRWLockRead` | Continuously allows new readers in, even if writers are waiting. Provides maximum parallelism. | In cache structures where write operations are very rare or non-critical. |
| **Fair (FIFO)** | `RWLockFIFO` / `AsyncRWLockFIFO` | Grants access alternately between readers and writers (interleaving). Prevents starvation for both sides. | In high-frequency, bidirectional traffic (MAVLink, WebSockets, etc.). |
<br/>

## ⚙️ Architectural Limitations

Engineering facts developers need to know when using this library:

1. **The CPU-Bound vs I/O-Bound Reality:**
`rwlocker` derives its power from the moments when Python's GIL (Global Interpreter Lock) is released (Network requests, Database queries, File I/O, etc.). If you are looking for a lock for purely heavy mathematical computations (CPU-Bound) that do not involve I/O yields like `time.sleep()`, you will not achieve true parallelism due to the GIL, and the C-based standard `threading.Lock` will be slightly faster. **RWLock's true battlefield is I/O operations.**
2. **Circular References:**
Lock classes establish a circular reference graph (Lock -> Proxy -> Lock) when creating smart proxy objects (`.read` and `.write`). This design is intentional. Memory cleanup (Garbage Collection) is safely handled by Python's Cyclic GC engine, not by `__del__`.
3. **Strict Nested Write Locks:**
In `SafeWriter` variants, only "Write" locks can be nested. If a writer wants to acquire a reader lock, it cannot do so implicitly; it must explicitly call the `.downgrade()` method. This is a strict architectural decision made to prevent deadlocks at the structural level.


<br/>

## 📊 Performance and Benchmark Results

`rwlocker` unlocks the system's true potential during Network and Database I/O operations where Python's GIL (Global Interpreter Lock) is released. In aggressive scenario tests conducted with zero OS sleep interference, it overwhelmingly outperformed standard locks.

**Summary of Performance Outputs:**

* **🚀 Read-Heavy Scenario (100 Readers, 2 Writers):**
While standard locks queue readers single-file and choke the system, `rwlocker` allows readers to access the data simultaneously. This achieves **~37x FASTER** speed and throughput in **Threading** and **~30x FASTER** in **Asyncio**.
* **⚖️ Balanced Scenario (50 Readers, 50 Writers):**
Thanks to the Fair (FIFO) state machine, read operations are squeezed in parallel between write queues. It increases performance by **2x** compared to standard locks without creating a system bottleneck.
* **🛡️ Write-Heavy Scenario (2 Readers, 100 Writers):**
Even though write operations inherently cannot be executed concurrently (in parallel), thanks to `rwlocker`'s zero-allocation smart proxy architecture, it runs **7-8% faster** than standard `C`-based locks. Even the O(1) cost "SafeWriter" (reentrancy) feature adds almost no overhead to performance.

*(Note: All lock classes have passed 135 different unit tests covering reentrancy, deadlock, timeout, and cancellation safety scenarios with 0 errors.)*


<br/>

## 🚀 Getting Started

### 🛠️ Dependencies

* No external dependencies.
* Only Python Standard Library (`threading`, `asyncio`, `typing`).
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
from rwlocker.thread_rwlock import RWLockWriteSafeWriter

class TransactionLedger:
    def __init__(self):
        self._lock = RWLockWriteSafeWriter()
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

#### 4. High-Frequency Telemetry (Fair FIFO Distribution)

Data arrives from a sensor 100 times per second (Write), and 200 WebSockets read this data (Read). The FIFO architecture prevents both sides from starving.

```python
import asyncio
from typing import Dict
from rwlocker.async_rwlock import AsyncRWLockFIFO

class TelemetryDispatcher:
    def __init__(self):
        # FIFO (Fair Lock) prevents read and write intensities from choking each other.
        self._lock = AsyncRWLockFIFO()
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

> ⚠️ **Important Developer Note:** The `rwlocker` architecture is highly sensitive to *deadlock* and *reentrancy* scenarios. Before opening a PR, please ensure that all **135+ unit tests** in the project pass flawlessly and that your code complies with **Python 3.9+** standards.

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

[examples-url]: https://github.com/TahsinCr/python-rwlocker/wiki

[license-url]: https://github.com/TahsinCr/python-rwlocker/blob/master/LICENSE

[changelog-url]:https://github.com/TahsinCr/python-rwlocker/blob/master/CHANGELOG.md



<!-- Contacts URL -->

[linkedin-url]: https://linkedin.com/in/TahsinCr

[x-url]: https://twitter.com/TahsinCrs



<!-- File URL -->

[lang-tr-url]: https://github.com/TahsinCr/python-rwlocker/blob/master/README_tr.md

[lang-en-url]: https://github.com/TahsinCr/python-rwlocker/blob/master/README.md
