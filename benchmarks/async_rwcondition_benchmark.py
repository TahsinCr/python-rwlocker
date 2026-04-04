import asyncio
import time

from benchmarks.benchmark_base import AsyncBenchmarkerBase, BenchmarkConfig, BenchmarkDataHandler
from benchmarks.benchmark_scenario import (
    BaseScenario, AsyncIOBoundScenario
)
from rwlocker.async_rwlock import (
    AsyncRWLockWrite, AsyncRWLockRead, AsyncRWLockReaderPhaseFair, AsyncRWLockFair,
    AsyncRWConditionBase, AsyncRWCondition
)

class AsyncStandardConditionWrapper:
    """
    Standard asyncio.Condition baseline using a standard asyncio.Lock.
    Suffers from linear wakeups and lacks Read/Write distinction.
    """
    def __init__(self):
        self._cond = asyncio.Condition(asyncio.Lock())
        self.read = self._cond
        self.write = self._cond
    @classmethod
    def get_name(cls): return "asyncio.Condition (C-Baseline)"

class AsyncRWConditionWriteWrapper:
    def __init__(self):
        self._cond = AsyncRWCondition(AsyncRWLockWrite())
        self.read = self._cond.read
        self.write = self._cond.write
    @classmethod
    def get_name(cls): return "AsyncRWCondition (Write-Pref)"

class AsyncRWConditionReadWrapper:
    def __init__(self):
        self._cond = AsyncRWCondition(AsyncRWLockRead())
        self.read = self._cond.read
        self.write = self._cond.write
    @classmethod
    def get_name(cls): return "AsyncRWCondition (Read-Pref)"

class AsyncRWConditionReaderPhaseFairWrapper:
    def __init__(self):
        self._cond = AsyncRWCondition(AsyncRWLockReaderPhaseFair())
        self.read = self._cond.read
        self.write = self._cond.write
    @classmethod
    def get_name(cls): return "AsyncRWCondition (ReaderPhaseFair)"

class AsyncRWConditionFairWrapper:
    def __init__(self):
        self._cond = AsyncRWCondition(AsyncRWLockFair())
        self.read = self._cond.read
        self.write = self._cond.write
    @classmethod
    def get_name(cls): return "AsyncRWCondition (Fair)"


class AsyncConditionBenchmarker(AsyncBenchmarkerBase):
    async def _reader_worker(
        self, 
        cond:AsyncRWConditionBase, 
        scenario:BaseScenario,
        num_writers:int,
        start_event:asyncio.Event,
        worker_id:int,
    ):
        await start_event.wait()
        target_epoch = scenario.iterations * num_writers
        expected = 1
        while expected <= target_epoch:
            async with cond.read:
                await cond.read.wait_for(lambda: scenario.epoch >= expected)
                expected = scenario.epoch + 1 
                await scenario.execute_read(worker_id)

    async def _writer_worker(
        self, 
        cond:AsyncRWConditionBase, 
        scenario:BaseScenario, 
        start_event:asyncio.Event,
        worker_id:int,
    ):
        await start_event.wait()
        for _ in range(scenario.iterations):
            async with cond.write:
                await scenario.execute_write(worker_id)
                scenario.epoch += 1
                cond.write.notify_all()

    def _create_workers(
        self, 
        target_obj:AsyncRWConditionBase, 
        scenario:BaseScenario, 
        num_readers:int, 
        num_writers:int, 
        start_event:asyncio.Event,
    ):
        tasks = []
        worker_id = 0
        for _ in range(num_readers):
            tasks.append(asyncio.create_task(
                self._reader_worker(target_obj, scenario, num_writers, start_event, worker_id)
            ))
            worker_id += 1
        for _ in range(num_writers):
            tasks.append(asyncio.create_task(
                self._writer_worker(target_obj, scenario, start_event, worker_id)
            ))
            worker_id += 1
        return tasks

    async def _run_target_trial(
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
        start_event = asyncio.Event()
        tasks = self._create_workers(target_obj, scenario, num_readers, num_writers, start_event)

        await asyncio.sleep(0)
        start_time = time.perf_counter()
        start_event.set()
        await asyncio.gather(*tasks)
        return max(time.perf_counter() - start_time, 0.0001)


async def benchmark(
    scenarios:list[BaseScenario],
    conditions:list[AsyncRWConditionBase],
    data_handler:BenchmarkDataHandler=None,
    config:BenchmarkConfig | None = None,
):
    engine = AsyncConditionBenchmarker(conditions, data_handler=data_handler, config=config)
    
    for scenario in scenarios:
        if not data_handler:
            print("=" * 60)
            print(f"Senario: {scenario.get_name()}")
            print("=" * 60)
        
        await engine.run_workload(
            "Read-Heavy", 
            scenario, num_readers=100, num_writers=2
        )

        await engine.run_workload(
            "Balance", 
            scenario, num_readers=50, num_writers=50
        )

        await engine.run_workload(
            "Write-Heavy", 
            scenario, num_readers=2, num_writers=100
        )

if __name__ == '__main__':
    asyncio.run(benchmark(
        scenarios=[
            AsyncIOBoundScenario()
        ],
        conditions=[
            AsyncStandardConditionWrapper,
            AsyncRWConditionWriteWrapper, 
            AsyncRWConditionReadWrapper,
            AsyncRWConditionReaderPhaseFairWrapper, 
            AsyncRWConditionFairWrapper
        ]
    ))
