import threading

from benchmarks.benchmark_base import BenchmarkerBase, BenchmarkDataHandler
from benchmarks.benchmark_scenario import (
    BaseScenario, IOBoundScenario, CPUBoundScenario
)
from rwlocker.thread_rwlock import (
    RWLockWrite, RWLockRead, RWLockFair,
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
        iterations:int, 
        start_event:threading.Event
    ):
        start_event.wait()
        target_epoch = iterations * num_writers
        expected = 1
        while expected <= target_epoch:
            with cond.read:
                cond.read.wait_for(lambda: scenario.epoch >= expected)
                expected = scenario.epoch + 1 
                scenario.execute_read()

    def _writer_worker(
        self, 
        cond:RWConditionBase, 
        scenario:BaseScenario, 
        iterations:int, 
        start_event:threading.Event
    ):
        start_event.wait()
        for _ in range(iterations):
            with cond.write:
                scenario.execute_write()
                scenario.epoch += 1
                cond.write.notify_all()

    def _create_workers(
        self, 
        target_obj:RWConditionBase, 
        scenario:BaseScenario, 
        num_readers:int, 
        num_writers:int, 
        iterations:int, 
        start_event:threading.Event
    ):
        threads = []
        for _ in range(num_readers):
            threads.append(threading.Thread(
                target=self._reader_worker, 
                args=(target_obj, scenario, num_writers, iterations, start_event)
            ))
        for _ in range(num_writers):
            threads.append(threading.Thread(
                target=self._writer_worker, 
                args=(target_obj, scenario, iterations, start_event)
            ))
        return threads


def benchmark(scenarios:list[BaseScenario], conditions:list[RWConditionBase], data_handler:BenchmarkDataHandler=None):    
    engine = ThreadConditionBenchmarker(conditions, data_handler=data_handler)
    
    if not data_handler:
        print("=" * 60)
        print("REAL-WORLD CONDITION VARIABLE CONCURRENCY BENCHMARK")
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
        conditions=[
            StandardConditionWrapper,
            RWConditionWriteWrapper, 
            RWConditionReadWrapper, 
            RWConditionFairWrapper
        ]
    )
