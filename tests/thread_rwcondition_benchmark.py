import time
import threading
import gc
from typing import Type, List

from rwlocker.thread_rwlock import (
    RWLockWrite, RWLockRead, RWLockFair,
    RWCondition
)

class StandardConditionWrapper:
    """
    Standard threading.Condition baseline using a standard C-level Mutex.
    Suffers from O(N) traversal on notify_all() and lacks Read/Write distinction.
    """
    def __init__(self):
        self._cond = threading.Condition(threading.Lock())
        self.read = self._cond
        self.write = self._cond
    @classmethod
    def get_name(cls): return "threading.Condition (C-Baseline)"

class RWConditionWriteWrapper:
    def __init__(self):
        self._cond = RWCondition(RWLockWrite())
        self.read = self._cond.read
        self.write = self._cond.write
    @classmethod
    def get_name(cls): return "RWCondition (Write-Pref)"

class RWConditionReadWrapper:
    def __init__(self):
        self._cond = RWCondition(RWLockRead())
        self.read = self._cond.read
        self.write = self._cond.write
    @classmethod
    def get_name(cls): return "RWCondition (Read-Pref)"

class RWConditionFairWrapper:
    def __init__(self):
        self._cond = RWCondition(RWLockFair())
        self.read = self._cond.read
        self.write = self._cond.write
    @classmethod
    def get_name(cls): return "RWCondition (Fair)"


class ReaderWriterConditionScenario:
    """
    Simulates a Real-World Reader/Writer Condition Request.
    Tests the efficiency of wait() and notify_all() under load, specifically
    targeting the Cache Stampede vulnerability of standard Condition variables.
    """
    def __init__(self, read_delay=0.001, write_delay=0.001):
        self.read_delay = read_delay
        self.write_delay = write_delay
        self.epoch = 0

    def get_name(self): return "Reader/Writer Broadcast (Cache Stampede Simulator)"
    
    def execute_read(self): time.sleep(self.read_delay)
    def execute_write(self): time.sleep(self.write_delay)
    def reset(self): self.epoch = 0


class ConditionBenchmarker:
    def __init__(self, lock_classes: List[Type]):
        self.lock_classes = lock_classes

    def _reader_worker(self, cond, scenario, num_writers, iterations, start_event):
        start_event.wait() # Synchronized explosive start
        target_epoch = iterations * num_writers
        expected = 1
        
        while expected <= target_epoch:
            with cond.read:
                # Wait safely for the state to advance
                cond.read.wait_for(lambda: scenario.epoch >= expected)
                
                # Catch up to the latest epoch in case multiple writers fired rapidly
                expected = scenario.epoch + 1 
                scenario.execute_read()

    def _writer_worker(self, cond, scenario, iterations, start_event):
        start_event.wait() # Synchronized explosive start
        for _ in range(iterations):
            with cond.write:
                scenario.execute_write()
                scenario.epoch += 1
                cond.write.notify_all() # The critical operation being benchmarked

    def run_workload(self, name: str, scenario: ReaderWriterConditionScenario, num_readers: int, num_writers: int, iterations: int):
        total_ops = (num_readers + num_writers) * iterations
        print(f"\n[{name.upper()}]")
        print(f"Readers: {num_readers} | Writers: {num_writers} | Iterations: {iterations}")
        print("-" * 85)
        print(f"{'Condition Implementation':<30} | {'Time (s)':<15} | {'Ops/sec':<15} | {'Speedup vs C-Base':<15}")
        print("-" * 85)

        results = []
        baseline_time = None

        for lock_class in self.lock_classes:
            lock_name = lock_class.get_name() if hasattr(lock_class, 'get_name') else lock_class.__name__
            
            # GC disable and tight loops for absolute precision
            gc.disable()
            scenario.reset()
            cond = lock_class()
            start_event = threading.Event()
            threads = []

            for _ in range(num_readers):
                threads.append(threading.Thread(target=self._reader_worker, args=(cond, scenario, num_writers, iterations, start_event)))
            for _ in range(num_writers):
                threads.append(threading.Thread(target=self._writer_worker, args=(cond, scenario, iterations, start_event)))

            for t in threads: t.start()
            
            start_time = time.perf_counter()
            start_event.set()
            for t in threads: t.join()
            
            elapsed = time.perf_counter() - start_time
            gc.enable()

            if "threading.Condition" in lock_name:
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
    conditions_to_test = [
        StandardConditionWrapper,
        RWConditionWriteWrapper, 
        RWConditionReadWrapper, 
        RWConditionFairWrapper
    ]
    
    engine = ConditionBenchmarker(conditions_to_test)
    scenario = ReaderWriterConditionScenario()
    
    print("=====================================================================================")
    print("REAL-WORLD CONDITION VARIABLE CONCURRENCY BENCHMARK")
    print("Measuring O(1) Queueing, Wake-up Latency, and Cache Stampede Protection.")
    print("=====================================================================================")
    
    # 1. MASSIVE BROADCAST: Tests O(1) notify_all() efficiency vs standard C-level O(N).
    # RWCondition should completely obliterate the baseline here due to cache stampede protection.
    engine.run_workload("Massive Broadcast (1 Writer, 100 Readers)", scenario, num_readers=100, num_writers=1, iterations=10)

    # 2. BALANCED: Mixed signaling. Measures Lock Proxy and Downgrade-ready architecture overhead.
    engine.run_workload("Balanced (50 Writers, 50 Readers)", scenario, num_readers=50, num_writers=50, iterations=10)

    # 3. WRITE HEAVY: Heavy notification overhead. C-Baseline Mutex might win purely on C-level speed, 
    # but RWConditions will hold their ground nicely.
    engine.run_workload("Multi-Writer / Write-Heavy (100 Writers, 2 Readers)", scenario, num_readers=2, num_writers=100, iterations=10)

if __name__ == '__main__':
    main()
