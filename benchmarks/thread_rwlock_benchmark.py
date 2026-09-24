from __future__ import annotations

import threading
import queue

from benchmarks.benchmark_base import BenchmarkerBase, BenchmarkConfig, BenchmarkDataHandler
from benchmarks.benchmark_scenario import (
    BaseScenario, IOBoundScenario, CPUBoundScenario
)
import time
from rwlocker.thread_rwlock import (
    RWLockBase, RWLockWrite, RWLockWriteReentrantWriter,
    RWLockRead, RWLockReadReentrantWriter,
    RWLockReaderPhaseFair, RWLockReaderPhaseFairReentrantWriter,
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
        start_barrier:threading.Barrier,
        worker_id:int,
        errors:queue.SimpleQueue,
    ):
        try:
            start_barrier.wait()
            if is_reader:
                for _ in range(scenario.iterations):
                    with lock.read:
                        scenario.execute_read(worker_id)
            else:
                for _ in range(scenario.iterations):
                    with lock.write:
                        scenario.execute_write(worker_id)
        except BaseException as exc:
            errors.put(exc)

    def _create_workers(
        self, 
        target_obj:RWLockBase, 
        scenario:BaseScenario, 
        num_readers:int, 
        num_writers:int, 
        start_barrier:threading.Barrier,
        errors:queue.SimpleQueue,
    ):
        threads = []
        worker_id = 0
        for _ in range(num_readers):
            threads.append(threading.Thread(
                target=self._worker, 
                args=(target_obj, scenario, True, start_barrier, worker_id, errors)
            ))
            worker_id += 1
        for _ in range(num_writers):
            threads.append(threading.Thread(
                target=self._worker, 
                args=(target_obj, scenario, False, start_barrier, worker_id, errors)
            ))
            worker_id += 1
        return threads

    def _run_target_trial(
        self,
        target_class:type,
        scenario:BaseScenario,
        num_readers:int,
        num_writers:int,
        config:BenchmarkConfig,
    ) -> float:
        del config
        total_workers = num_readers + num_writers
        if total_workers == 0:
            return 0.0001
        target_obj = target_class()
        timer = {"start": 0.0}
        errors:queue.SimpleQueue = queue.SimpleQueue()

        def mark_start() -> None:
            timer["start"] = time.perf_counter()

        start_barrier = threading.Barrier(total_workers + 1, action=mark_start)
        threads = self._create_workers(target_obj, scenario, num_readers, num_writers, start_barrier, errors)

        for thread in threads:
            thread.start()

        try:
            start_barrier.wait()
            for thread in threads:
                thread.join()
        finally:
            for thread in threads:
                if thread.is_alive():
                    thread.join()

        if not errors.empty():
            raise RuntimeError(f"{target_class.__name__} worker failed") from errors.get()

        return max(time.perf_counter() - timer["start"], 0.0001)


def benchmark(
    scenarios:list[BaseScenario],
    locks:list[RWLockBase],
    data_handler:BenchmarkDataHandler=None,
    config:BenchmarkConfig | None = None,
):
    engine = ThreadLockBenchmarker(locks, data_handler=data_handler, config=config)
    
    for scenario in scenarios:
        if not data_handler:
            print("=" * 60)
            print(f"Senario: {scenario.get_name()}")
            print("=" * 60)
        
        engine.run_workload(
            "Read-Heavy",
            scenario, num_readers=100, num_writers=2
        )

        engine.run_workload(
            "Balance", 
            scenario, num_readers=50, num_writers=50
        )

        engine.run_workload(
            "Write-Heavy", 
            scenario, num_readers=2, num_writers=100
        )


if __name__ == '__main__':
    benchmark(
        scenarios=[
            IOBoundScenario()
        ],
        locks=[
            StandardLockWrapper,
            StandardRLockWrapper,
            RWLockWrite,
            RWLockWriteReentrantWriter,
            RWLockRead,
            RWLockReadReentrantWriter,
            RWLockReaderPhaseFair,
            RWLockReaderPhaseFairReentrantWriter,
            RWLockFair,
            RWLockFairReentrantWriter
        ]
    )
