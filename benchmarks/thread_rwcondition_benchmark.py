import threading
import queue
import time

from benchmarks.benchmark_base import BenchmarkerBase, BenchmarkConfig, BenchmarkDataHandler
from benchmarks.benchmark_scenario import (
    BaseScenario, IOBoundScenario, CPUBoundScenario
)
from rwlocker.thread_rwlock import (
    RWLockWrite, RWLockRead, RWLockReaderPhaseFair, RWLockFair,
    RWConditionBase, RWCondition
)

class StandardConditionWrapper:
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

class RWConditionReaderPhaseFairWrapper:
    def __init__(self):
        self._cond = RWCondition(RWLockReaderPhaseFair())
        self.read = self._cond.read
        self.write = self._cond.write
    @classmethod
    def get_name(cls): return "RWCondition (ReaderPhaseFair)"

class RWConditionFairWrapper:
    def __init__(self):
        self._cond = RWCondition(RWLockFair())
        self.read = self._cond.read
        self.write = self._cond.write
    @classmethod
    def get_name(cls): return "RWCondition (Fair)"


class ThreadConditionBenchmarker(BenchmarkerBase):
    def _reader_worker(
        self, 
        cond:RWConditionBase, 
        scenario:BaseScenario,
        num_writers:int,
        start_barrier:threading.Barrier,
        worker_id:int,
        errors:queue.SimpleQueue,
    ):
        try:
            start_barrier.wait()
            target_epoch = scenario.iterations * num_writers
            expected = 1
            while expected <= target_epoch:
                with cond.read:
                    cond.read.wait_for(lambda: scenario.epoch >= expected)
                    expected = scenario.epoch + 1 
                    scenario.execute_read(worker_id)
        except BaseException as exc:
            errors.put(exc)

    def _writer_worker(
        self, 
        cond:RWConditionBase, 
        scenario:BaseScenario, 
        start_barrier:threading.Barrier,
        worker_id:int,
        errors:queue.SimpleQueue,
    ):
        try:
            start_barrier.wait()
            for _ in range(scenario.iterations):
                with cond.write:
                    scenario.execute_write(worker_id)
                    scenario.epoch += 1
                    cond.write.notify_all()
        except BaseException as exc:
            errors.put(exc)

    def _create_workers(
        self, 
        target_obj:RWConditionBase, 
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
                target=self._reader_worker, 
                args=(target_obj, scenario, num_writers, start_barrier, worker_id, errors)
            ))
            worker_id += 1
        for _ in range(num_writers):
            threads.append(threading.Thread(
                target=self._writer_worker, 
                args=(target_obj, scenario, start_barrier, worker_id, errors)
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
    conditions:list[RWConditionBase],
    data_handler:BenchmarkDataHandler=None,
    config:BenchmarkConfig | None = None,
):
    engine = ThreadConditionBenchmarker(conditions, data_handler=data_handler, config=config)
    
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
        conditions=[
            StandardConditionWrapper,
            RWConditionWriteWrapper, 
            RWConditionReadWrapper,
            RWConditionReaderPhaseFairWrapper,
            RWConditionFairWrapper
        ]
    )
