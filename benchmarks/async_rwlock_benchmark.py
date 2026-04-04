import asyncio
import time

from benchmarks.benchmark_base import AsyncBenchmarkerBase, BenchmarkConfig, BenchmarkDataHandler
from benchmarks.benchmark_scenario import (
    BaseScenario, AsyncIOBoundScenario
)
from rwlocker.async_rwlock import (
    AsyncRWLockBase, AsyncRWLockWrite, AsyncRWLockWriteReentrantWriter,
    AsyncRWLockRead, AsyncRWLockReadReentrantWriter,
    AsyncRWLockReaderPhaseFair, AsyncRWLockReaderPhaseFairReentrantWriter,
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
        start_event:asyncio.Event,
        worker_id:int,
    ):
        await start_event.wait()
        if is_reader:
            for _ in range(scenario.iterations):
                async with lock.read:
                    await scenario.execute_read(worker_id)
        else:
            for _ in range(scenario.iterations):
                async with lock.write:
                    await scenario.execute_write(worker_id)

    def _create_workers(
        self,
        target_obj:AsyncRWLockBase, 
        scenario:BaseScenario, 
        num_readers:int, 
        num_writers:int, 
        start_event:asyncio.Event,
    ):
        tasks = []
        worker_id = 0
        for _ in range(num_readers):
            tasks.append(asyncio.create_task(
                self._worker(target_obj, scenario, True, start_event, worker_id)
            ))
            worker_id += 1
        for _ in range(num_writers):
            tasks.append(asyncio.create_task(
                self._worker(target_obj, scenario, False, start_event, worker_id)
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
    locks:list[AsyncRWLockBase],
    data_handler:BenchmarkDataHandler=None,
    config:BenchmarkConfig | None = None,
):
    engine = AsyncLockBenchmarker(locks, data_handler=data_handler, config=config)
    
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
        locks=[
            AsyncStandardLockWrapper,
            AsyncRWLockWrite, AsyncRWLockWriteReentrantWriter,
            AsyncRWLockRead, AsyncRWLockReadReentrantWriter,
            AsyncRWLockReaderPhaseFair, AsyncRWLockReaderPhaseFairReentrantWriter,
            AsyncRWLockFair, AsyncRWLockFairReentrantWriter
        ]
    ))
