import time
import threading
import gc
from typing import Type, List

from rwlocker.thread_rwlock import (
    RWLockBase, 
    RWLockWrite, RWLockWriteSafeWriter,
    RWLockRead, RWLockReadSafeWriter,
    RWLockFIFO, RWLockFIFOSafeWriter
)

class StandardLockWrapper:
    def __init__(self):
        self._lock = threading.Lock()
        self.read = self._lock
        self.write = self._lock
    @classmethod
    def get_name(cls): return "threading.Lock (C-Baseline)"

class StandardRLockWrapper:
    def __init__(self):
        self._lock = threading.RLock()
        self.read = self._lock
        self.write = self._lock
    @classmethod
    def get_name(cls): return "threading.RLock (C-Baseline)"

class IOBoundScenario:
    """
    Simulates a Real-World Database or Network Request.
    During time.sleep(), Python releases the GIL, allowing TRUE concurrency.
    This is where RWLocks dominate standard Mutexes.
    """
    def __init__(self, read_delay=0.001, write_delay=0.001):
        self.read_delay = read_delay
        self.write_delay = write_delay

    def get_name(self): return "I/O Bound (Database/API Simulator)"
    
    def execute_read(self): time.sleep(self.read_delay)
    def execute_write(self): time.sleep(self.write_delay)


class ExactBenchmarker:
    def __init__(self, lock_classes: List[Type]):
        self.lock_classes = lock_classes

    def _worker(self, lock, scenario, is_reader, iterations, start_event):
        start_event.wait() # Synchronized explosive start
        if is_reader:
            for _ in range(iterations):
                with lock.read:
                    scenario.execute_read()
        else:
            for _ in range(iterations):
                with lock.write:
                    scenario.execute_write()

    def run_workload(self, name: str, scenario: IOBoundScenario, num_readers: int, num_writers: int, iterations: int):
        total_ops = (num_readers + num_writers) * iterations
        print(f"\n[{name.upper()}]")
        print(f"Readers: {num_readers} | Writers: {num_writers} | Iterations: {iterations}")
        print("-" * 85)
        print(f"{'Lock Implementation':<30} | {'Time (s)':<15} | {'Ops/sec':<15} | {'Speedup vs Lock':<15}")
        print("-" * 85)

        results = []
        baseline_time = None

        for lock_class in self.lock_classes:
            lock_name = lock_class.get_name() if hasattr(lock_class, 'get_name') else lock_class.__name__
            
            # GC disable and tight loops for absolute precision
            gc.disable()
            lock = lock_class()
            start_event = threading.Event()
            threads = []

            for _ in range(num_readers):
                threads.append(threading.Thread(target=self._worker, args=(lock, scenario, True, iterations, start_event)))
            for _ in range(num_writers):
                threads.append(threading.Thread(target=self._worker, args=(lock, scenario, False, iterations, start_event)))

            for t in threads: t.start()
            
            start_time = time.perf_counter()
            start_event.set()
            for t in threads: t.join()
            
            elapsed = time.perf_counter() - start_time
            gc.enable()

            if "threading.Lock" in lock_name:
                baseline_time = elapsed

            throughput = total_ops / elapsed
            results.append((lock_name, elapsed, throughput))

        # Sort by best time
        results.sort(key=lambda x: x[1])

        for lock_name, elapsed, throughput in results:
            speedup = (baseline_time / elapsed) if baseline_time else 0
            # Highlight your classes to show they win where it matters
            marker = ">> " if speedup > 1.2 else "   "
            print(f"{marker}{lock_name:<27} | {elapsed:<15.4f} | {throughput:<15.0f} | {speedup:<10.2f}x")
        print("-" * 85)

def main():
    locks_to_test = [
        StandardLockWrapper, StandardRLockWrapper,
        RWLockWrite, RWLockWriteSafeWriter,
        RWLockRead, RWLockReadSafeWriter,
        RWLockFIFO, RWLockFIFOSafeWriter
    ]
    
    engine = ExactBenchmarker(locks_to_test)
    scenario = IOBoundScenario()
    
    print("================================================================================")
    print("REAL-WORLD I/O CONCURRENCY BENCHMARK")
    print("Measuring True Parallelism during GIL-released operations (Network/DB).")
    print("================================================================================")
    
    # 1. READ HEAVY: Readers should execute in parallel. RWLocks should DESTROY baselines.
    engine.run_workload("Read-Heavy (Cache Hit Sim)", scenario, num_readers=100, num_writers=2, iterations=10)

    # 2. BALANCED: Mixed workload. RWLockFIFO should show its stability.
    engine.run_workload("Balanced (Standard Web Traffic)", scenario, num_readers=50, num_writers=50, iterations=10)

    # 3. WRITE HEAVY: Sequential by nature. C-Baseline will win. Your locks will take a penalty.
    engine.run_workload("Write-Heavy (Log Ingestion)", scenario, num_readers=2, num_writers=100, iterations=10)

if __name__ == '__main__':
    main()
