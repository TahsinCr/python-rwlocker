import asyncio
import rwlocker
from benchmarks.benchmark_scenario import (
    IOBoundScenario, AsyncIOBoundScenario, CPUBoundScenario
)
from benchmarks import (
    thread_rwlock_benchmark, 
    async_rwlock_benchmark,
    thread_rwcondition_benchmark, 
    async_rwcondition_benchmark
)

locks = [
    thread_rwlock_benchmark.StandardLockWrapper,
    thread_rwlock_benchmark.StandardRLockWrapper,
    rwlocker.RWLockWrite, rwlocker.RWLockWriteReentrantWriter,
    rwlocker.RWLockRead, rwlocker.RWLockReadReentrantWriter,
    rwlocker.RWLockFair, rwlocker.RWLockFairReentrantWriter
]

async_locks = [
    async_rwlock_benchmark.AsyncStandardLockWrapper,
    rwlocker.AsyncRWLockWrite, rwlocker.AsyncRWLockWriteReentrantWriter,
    rwlocker.AsyncRWLockRead, rwlocker.AsyncRWLockReadReentrantWriter,
    rwlocker.AsyncRWLockFair, rwlocker.AsyncRWLockFairReentrantWriter
]

conditions = [
    thread_rwcondition_benchmark.StandardConditionWrapper,
    thread_rwcondition_benchmark.RWConditionWriteWrapper, 
    thread_rwcondition_benchmark.RWConditionReadWrapper, 
    thread_rwcondition_benchmark.RWConditionFairWrapper
]

async_conditions = [
    async_rwcondition_benchmark.AsyncStandardConditionWrapper,
    async_rwcondition_benchmark.AsyncRWConditionWriteWrapper, 
    async_rwcondition_benchmark.AsyncRWConditionReadWrapper, 
    async_rwcondition_benchmark.AsyncRWConditionFairWrapper
]

scenarios = [
    IOBoundScenario()
]

async_scenarios = [
    AsyncIOBoundScenario()
]

if __name__ == '__main__':
    thread_rwlock_benchmark.benchmark(scenarios=scenarios, locks=locks)
    asyncio.run(async_rwlock_benchmark.benchmark(
        scenarios=async_scenarios, locks=async_locks
    ))
    thread_rwcondition_benchmark.benchmark(scenarios=scenarios, conditions=conditions)
    asyncio.run(async_rwcondition_benchmark.benchmark(
        scenarios=async_scenarios, conditions=async_conditions
    ))
