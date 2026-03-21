import threading

from benchmarks.benchmark_base import BenchmarkerBase, BenchmarkDataHandler
from benchmarks.benchmark_scenario import (
    BaseScenario, IOBoundScenario, CPUBoundScenario
)
from rwlocker.thread_rwlock import (
    RWLockBase, RWLockWrite, RWLockWriteReentrantWriter,
    RWLockRead, RWLockReadReentrantWriter,
    RWLockFair, RWLockFairReentrantWriter
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


class ThreadLockBenchmarker(BenchmarkerBase):
    def _worker(
        self, 
        lock:RWLockBase, 
        scenario:BaseScenario, 
        is_reader:bool, 
        iterations:int, 
        start_event:threading.Event
    ):
        start_event.wait() 
        if is_reader:
            for _ in range(iterations):
                with lock.read:
                    scenario.execute_read()
        else:
            for _ in range(iterations):
                with lock.write:
                    scenario.execute_write()

    def _create_workers(
        self, 
        target_obj:RWLockBase, 
        scenario:BaseScenario, 
        num_readers:int, 
        num_writers:int, 
        iterations:int, 
        start_event:threading.Event
    ):
        threads = []
        for _ in range(num_readers):
            threads.append(threading.Thread(
                target=self._worker, 
                args=(target_obj, scenario, True, iterations, start_event)
            ))
        for _ in range(num_writers):
            threads.append(threading.Thread(
                target=self._worker, 
                args=(target_obj, scenario, False, iterations, start_event)
            ))
        return threads


def benchmark(scenarios:list[BaseScenario], locks:list[RWLockBase], data_handler:BenchmarkDataHandler=None):
    engine = ThreadLockBenchmarker(locks, data_handler=data_handler)
    
    if not data_handler:
        print("=" * 60)
        print("REAL-WORLD I/O CONCURRENCY BENCHMARK")
        print("=" * 60)
    
    for scenario in scenarios:
        engine.run_workload(
            "Read-Heavy (2 Writer, 100 Readers)",
            scenario, num_readers=100, num_writers=2, iterations=10
        )

        engine.run_workload(
            "Balanced (50 Writers, 50 Readers)", 
            scenario, num_readers=50, num_writers=50, iterations=10
        )

        engine.run_workload(
            "Write-Heavy (100 Writers, 2 Readers)", 
            scenario, num_readers=2, num_writers=100, iterations=10
        )


if __name__ == '__main__':
    benchmark(
        scenarios=[
            IOBoundScenario(),
            CPUBoundScenario()
        ],
        locks=[
            StandardLockWrapper,
            StandardRLockWrapper,
            RWLockWrite,
            RWLockWriteReentrantWriter,
            RWLockRead,
            RWLockReadReentrantWriter,
            RWLockFair,
            RWLockFairReentrantWriter
        ]
    )
