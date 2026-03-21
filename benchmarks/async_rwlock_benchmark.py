import asyncio

from benchmarks.benchmark_base import AsyncBenchmarkerBase, BenchmarkDataHandler
from benchmarks.benchmark_scenario import (
    BaseScenario, AsyncIOBoundScenario
)
from rwlocker.async_rwlock import (
    AsyncRWLockBase, AsyncRWLockWrite, AsyncRWLockWriteReentrantWriter,
    AsyncRWLockRead, AsyncRWLockReadReentrantWriter,
    AsyncRWLockFair, AsyncRWLockFairReentrantWriter
)

class AsyncStandardLockWrapper:
    def __init__(self):
        self._lock = asyncio.Lock()
        self.read = self._lock
        self.write = self._lock
    @classmethod
    def get_name(cls): return "asyncio.Lock (C-Baseline)"


class AsyncLockBenchmarker(AsyncBenchmarkerBase):
    async def _worker(
        self, 
        lock:AsyncRWLockBase, 
        scenario:BaseScenario, 
        is_reader:bool, 
        iterations:int, 
        start_event:asyncio.Event
    ):
        await start_event.wait()
        if is_reader:
            for _ in range(iterations):
                async with lock.read:
                    await scenario.execute_read()
        else:
            for _ in range(iterations):
                async with lock.write:
                    await scenario.execute_write()

    def _create_workers(
        self,
        target_obj:AsyncRWLockBase, 
        scenario:BaseScenario, 
        num_readers:int, 
        num_writers:int, 
        iterations:int, 
        start_event:asyncio.Event
    ):
        tasks = []
        for _ in range(num_readers):
            tasks.append(asyncio.create_task(
                self._worker(target_obj, scenario, True, iterations, start_event)
            ))
        for _ in range(num_writers):
            tasks.append(asyncio.create_task(
                self._worker(target_obj, scenario, False, iterations, start_event)
            ))
        return tasks


async def benchmark(scenarios:list[BaseScenario], locks:list[AsyncRWLockBase], data_handler:BenchmarkDataHandler=None):    
    engine = AsyncLockBenchmarker(locks, data_handler=data_handler)
    
    if not data_handler:
        print("=" * 60)
        print("REAL-WORLD ASYNC I/O CONCURRENCY BENCHMARK")
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
        locks=[
            AsyncStandardLockWrapper,
            AsyncRWLockWrite, AsyncRWLockWriteReentrantWriter,
            AsyncRWLockRead, AsyncRWLockReadReentrantWriter,
            AsyncRWLockFair, AsyncRWLockFairReentrantWriter
        ]
    ))
