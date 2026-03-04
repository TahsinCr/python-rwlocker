import asyncio
import time
import gc
from typing import Type, List

from rwlocker.async_rwlock import (
    AsyncRWLockWrite, AsyncRWLockRead, AsyncRWLockFair,
    AsyncRWCondition
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
    def get_name(cls): return "asyncio.Condition (Baseline)"

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


class AsyncReaderWriterConditionScenario:
    """
    Simulates a Real-World Async Reader/Writer Condition Request.
    Tests the efficiency of wait() and notify_all() under load within the 
    event loop, specifically targeting the O(N) Cache Stampede vulnerability.
    """
    def __init__(self, read_delay=0.001, write_delay=0.001):
        self.read_delay = read_delay
        self.write_delay = write_delay
        self.epoch = 0

    def get_name(self): return "Async Reader/Writer Broadcast (Stampede Simulator)"
    
    async def execute_read(self): await asyncio.sleep(self.read_delay)
    async def execute_write(self): await asyncio.sleep(self.write_delay)
    def reset(self): self.epoch = 0


class AsyncConditionBenchmarker:
    def __init__(self, condition_classes: List[Type]):
        self.condition_classes = condition_classes

    async def _reader_worker(self, cond, scenario, num_writers, iterations, start_event):
        await start_event.wait() # Synchronized explosive start
        target_epoch = iterations * num_writers
        expected = 1
        
        while expected <= target_epoch:
            async with cond.read:
                # wait_for automatically handles the predicate loop
                await cond.read.wait_for(lambda: scenario.epoch >= expected)
                
                # Catch up to the latest epoch in case multiple writers fired rapidly
                expected = scenario.epoch + 1 
                await scenario.execute_read()

    async def _writer_worker(self, cond, scenario, iterations, start_event):
        await start_event.wait() # Synchronized explosive start
        for _ in range(iterations):
            async with cond.write:
                await scenario.execute_write()
                scenario.epoch += 1
                cond.write.notify_all() # The critical operation being benchmarked

    async def run_workload(self, name: str, scenario: AsyncReaderWriterConditionScenario, num_readers: int, num_writers: int, iterations: int):
        total_ops = (num_readers + num_writers) * iterations
        print(f"\n[{name.upper()}]")
        print(f"Readers: {num_readers} | Writers: {num_writers} | Iterations: {iterations}")
        print("-" * 88)
        print(f"{'Condition Implementation':<32} | {'Time (s)':<15} | {'Ops/sec':<15} | {'Speedup vs Base':<15}")
        print("-" * 88)

        results = []
        baseline_time = None

        for cond_class in self.condition_classes:
            cond_name = cond_class.get_name() if hasattr(cond_class, 'get_name') else cond_class.__name__
            
            # GC disable and tight loops for absolute precision
            gc.disable()
            scenario.reset()
            cond = cond_class()
            start_event = asyncio.Event()
            tasks = []

            for _ in range(num_readers):
                tasks.append(asyncio.create_task(self._reader_worker(cond, scenario, num_writers, iterations, start_event)))
            for _ in range(num_writers):
                tasks.append(asyncio.create_task(self._writer_worker(cond, scenario, iterations, start_event)))

            # Yield control back to event loop to ensure all tasks hit start_event.wait()
            await asyncio.sleep(0)
            
            start_time = time.perf_counter()
            start_event.set()
            await asyncio.gather(*tasks)
            
            elapsed = time.perf_counter() - start_time
            gc.enable()

            if "asyncio.Condition" in cond_name:
                baseline_time = elapsed

            throughput = total_ops / elapsed
            results.append((cond_name, elapsed, throughput))

        # Sort by best time
        results.sort(key=lambda x: x[1])

        for cond_name, elapsed, throughput in results:
            speedup = (baseline_time / elapsed) if baseline_time else 0
            # Highlight your classes to show they win where it matters
            marker = ">> " if speedup > 1.2 else "   "
            print(f"{marker}{cond_name:<29} | {elapsed:<15.4f} | {throughput:<15.0f} | {speedup:<10.2f}x")
        print("-" * 88)


async def main():
    conditions_to_test = [
        AsyncStandardConditionWrapper,
        AsyncRWConditionWriteWrapper, 
        AsyncRWConditionReadWrapper, 
        AsyncRWConditionFairWrapper
    ]
    
    engine = AsyncConditionBenchmarker(conditions_to_test)
    scenario = AsyncReaderWriterConditionScenario()
    
    print("========================================================================================")
    print("REAL-WORLD ASYNC CONDITION VARIABLE CONCURRENCY BENCHMARK")
    print("Measuring Event Loop Queueing, Task Wake-up Latency, and Stampede Protection.")
    print("========================================================================================")
    
    # 1. MASSIVE BROADCAST: Tests O(1) notify_all() efficiency vs standard.
    # AsyncRWCondition should dominate the baseline due to its efficient structure.
    await engine.run_workload("Massive Broadcast (1 Writer, 100 Readers)", scenario, num_readers=100, num_writers=1, iterations=10)

    # 2. BALANCED: Mixed signaling. Measures Lock Proxy and Event Loop overhead.
    await engine.run_workload("Balanced (50 Writers, 50 Readers)", scenario, num_readers=50, num_writers=50, iterations=10)

    # 3. WRITE HEAVY: Heavy notification overhead. 
    await engine.run_workload("Multi-Writer / Write-Heavy (100 Writers, 2 Readers)", scenario, num_readers=2, num_writers=100, iterations=10)

if __name__ == '__main__':
    asyncio.run(main())
