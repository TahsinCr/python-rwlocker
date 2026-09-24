import threading
import time
from typing import Any, Dict, Optional
from rwlocker.thread_rwlock import RWLockRead

class InMemoryCache:
    """A thread-safe cache optimized for 99% read / 1% write workloads."""
    
    def __init__(self):
        self._lock = RWLockRead()
        self._cache: Dict[str, Any] = {}

    def get(self, key: str) -> Optional[Any]:
        """
        Multiple threads can execute this concurrently.
        Readers NEVER block other readers, maximizing throughput.
        """
        with self._lock.read:
            value = self._cache.get(key)
        # Keep simulated latency outside the lock.
        time.sleep(0.001)
        return value

    def set(self, key: str, value: Any) -> None:
        """
        Acquires an exclusive write lock.
        Safely waits for active readers to finish, then blocks new readers 
        only for the duration of the update.
        """
        with self._lock.write:
            self._cache[key] = value

if __name__ == "__main__":
    cache = InMemoryCache()
    cache.set("system_status", "BOOTING")

    def reader_worker(worker_id: int):
        for _ in range(3):
            val = cache.get("system_status")
            print(f"Reader {worker_id} saw: {val}")
            time.sleep(0.05)

    def writer_worker():
        time.sleep(0.08) # Wait a bit, then update
        print("\n---> Writer updating cache to 'ONLINE' (Readers Paused) <---\n")
        cache.set("system_status", "ONLINE")

    # Launch 5 concurrent readers and 1 writer
    threads = [threading.Thread(target=reader_worker, args=(i,)) for i in range(5)]
    threads.append(threading.Thread(target=writer_worker))

    for t in threads: t.start()
    for t in threads: t.join()
