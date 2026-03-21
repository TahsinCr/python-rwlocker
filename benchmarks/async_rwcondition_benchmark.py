import asyncio

from benchmarks.benchmark_base import AsyncBenchmarkerBase, BenchmarkDataHandler
from benchmarks.benchmark_scenario import (
    BaseScenario, AsyncIOBoundScenario
)
from rwlocker.async_rwlock import (
    AsyncRWLockWrite, AsyncRWLockRead, AsyncRWLockFair,
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
        iterations:int, 
        start_event:asyncio.Event
    ):
        await start_event.wait()
        target_epoch = iterations * num_writers
        expected = 1
        while expected <= target_epoch:
            async with cond.read:
                await cond.read.wait_for(lambda: scenario.epoch >= expected)
                expected = scenario.epoch + 1 
                await scenario.execute_read()

    async def _writer_worker(
        self, 
        cond:AsyncRWConditionBase, 
        scenario:BaseScenario, 
        iterations:int, 
        start_event:asyncio.Event
    ):
        await start_event.wait()
        for _ in range(iterations):
            async with cond.write:
                await scenario.execute_write()
                scenario.epoch += 1
                cond.write.notify_all()

    def _create_workers(
        self, 
        target_obj:AsyncRWConditionBase, 
        scenario:BaseScenario, 
        num_readers:int, 
        num_writers:int, 
        iterations:int, 
        start_event:asyncio.Event
    ):
        tasks = []
        for _ in range(num_readers):
            tasks.append(asyncio.create_task(
                self._reader_worker(target_obj, scenario, num_writers, iterations, start_event)
            ))
        for _ in range(num_writers):
            tasks.append(asyncio.create_task(
                self._writer_worker(target_obj, scenario, iterations, start_event)
            ))
        return tasks


async def benchmark(scenarios:list[BaseScenario], conditions:list[AsyncRWConditionBase], data_handler:BenchmarkDataHandler=None):
    engine = AsyncConditionBenchmarker(conditions, data_handler=data_handler)
    
    if not data_handler:
        print("=" * 60)
        print("REAL-WORLD ASYNC CONDITION VARIABLE CONCURRENCY BENCHMARK")
        print("=" * 60)
    
    for scenario in scenarios:
        await engine.run_workload(
            "Read-Heavy (2 Writer, 100 Readers)", 
            scenario, num_readers=100, num_writers=2, iterations=10
        )

        await engine.run_workload(
            "Balanced (50 Writers, 50 Readers)", 
            scenario, num_readers=50, num_writers=50, iterations=10
        )

        await engine.run_workload(
            "Write-Heavy (100 Writers, 2 Readers)", 
            scenario, num_readers=2, num_writers=100, iterations=10
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
            AsyncRWConditionFairWrapper
        ]
    ))
