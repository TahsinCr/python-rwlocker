import asyncio
import time
import gc
from typing import Type, List

from rwlocker.async_rwlock import (
    AsyncRWLockBase, 
    AsyncRWLockWrite, AsyncRWLockWriteReentrantWriter,
    AsyncRWLockRead, AsyncRWLockReadReentrantWriter,
    AsyncRWLockFIFO, AsyncRWLockFIFOReentrantWriter
)

class AsyncStandardLockWrapper:
    def __init__(self):
        self._lock = asyncio.Lock()
        self.read = self._lock
        self.write = self._lock
    @classmethod
    def get_name(cls): return "asyncio.Lock (Baseline)"

class AsyncIOBoundScenario:
    """
    Simulates a Real-World Async Database or Network Request.
    During await asyncio.sleep(), the event loop switches tasks.
    This is where AsyncRWLocks dominate standard asyncio.Lock.
    """
    def __init__(self, read_delay=0.001, write_delay=0.001):
        self.read_delay = read_delay
        self.write_delay = write_delay

    def get_name(self): return "Async I/O Bound (Database/API Simulator)"
    
    async def execute_read(self): await asyncio.sleep(self.read_delay)
    async def execute_write(self): await asyncio.sleep(self.write_delay)


class AsyncExactBenchmarker:
    def __init__(self, lock_classes: List[Type]):
        self.lock_classes = lock_classes

    async def _worker(self, lock, scenario, is_reader, iterations, start_event):
        await start_event.wait() # Synchronized explosive start
        if is_reader:
            for _ in range(iterations):
                async with lock.read:
                    await scenario.execute_read()
        else:
            for _ in range(iterations):
                async with lock.write:
                    await scenario.execute_write()

    async def run_workload(self, name: str, scenario: AsyncIOBoundScenario, num_readers: int, num_writers: int, iterations: int):
        total_ops = (num_readers + num_writers) * iterations
        print(f"\n[{name.upper()}]")
        print(f"Readers: {num_readers} | Writers: {num_writers} | Iterations: {iterations}")
        print("-" * 88)
        print(f"{'Lock Implementation':<32} | {'Time (s)':<15} | {'Ops/sec':<15} | {'Speedup vs Lock':<15}")
        print("-" * 88)

        results = []
        baseline_time = None

        for lock_class in self.lock_classes:
            lock_name = lock_class.get_name() if hasattr(lock_class, 'get_name') else lock_class.__name__
            
            # GC disable and tight loops for absolute precision
            gc.disable()
            lock = lock_class()
            start_event = asyncio.Event()
            tasks = []

            for _ in range(num_readers):
                tasks.append(asyncio.create_task(self._worker(lock, scenario, True, iterations, start_event)))
            for _ in range(num_writers):
                tasks.append(asyncio.create_task(self._worker(lock, scenario, False, iterations, start_event)))

            # Yield control back to event loop to ensure all tasks hit start_event.wait()
            await asyncio.sleep(0)
            
            start_time = time.perf_counter()
            start_event.set()
            await asyncio.gather(*tasks)
            
            elapsed = time.perf_counter() - start_time
            gc.enable()

            if "asyncio.Lock" in lock_name:
                baseline_time = elapsed

            throughput = total_ops / elapsed
            results.append((lock_name, elapsed, throughput))

        # Sort by best time
        results.sort(key=lambda x: x[1])

        for lock_name, elapsed, throughput in results:
            speedup = (baseline_time / elapsed) if baseline_time else 0
            # Highlight your classes to show they win where it matters
            marker = ">> " if speedup > 1.2 else "   "
            print(f"{marker}{lock_name:<29} | {elapsed:<15.4f} | {throughput:<15.0f} | {speedup:<10.2f}x")
        print("-" * 88)

async def main():
    locks_to_test = [
        AsyncStandardLockWrapper,
        AsyncRWLockWrite, AsyncRWLockWriteReentrantWriter,
        AsyncRWLockRead, AsyncRWLockReadReentrantWriter,
        AsyncRWLockFIFO, AsyncRWLockFIFOReentrantWriter
    ]
    
    engine = AsyncExactBenchmarker(locks_to_test)
    scenario = AsyncIOBoundScenario()
    
    print("================================================================================")
    print("REAL-WORLD ASYNC I/O CONCURRENCY BENCHMARK")
    print("Measuring True Task Parallelism during awaited I/O operations (Network/DB).")
    print("================================================================================")
    
    # 1. READ HEAVY: Readers should execute in parallel. RWLocks should DESTROY baselines.
    await engine.run_workload("Read-Heavy (Cache Hit Sim)", scenario, num_readers=100, num_writers=2, iterations=10)

    # 2. BALANCED: Mixed workload. RWLockFIFO should show its stability.
    await engine.run_workload("Balanced (Standard Web Traffic)", scenario, num_readers=50, num_writers=50, iterations=10)

    # 3. WRITE HEAVY: Sequential by nature. Baseline will win. Your locks will take a penalty.
    await engine.run_workload("Write-Heavy (Log Ingestion)", scenario, num_readers=2, num_writers=100, iterations=10)

if __name__ == '__main__':
    asyncio.run(main())
