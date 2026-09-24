import asyncio
import rwlocker
from benchmarks.benchmark_scenario import (
    IOBoundScenario, AsyncIOBoundScenario,
    PureOverheadScenario, AsyncPureOverheadScenario
)
from benchmarks.benchmark_base import BenchmarkConfig
from benchmarks import (
    thread_rwlock_benchmark, 
    async_rwlock_benchmark,
    thread_rwcondition_benchmark, 
    async_rwcondition_benchmark
)

locks = [
    thread_rwlock_benchmark.StandardRLockWrapper,
    thread_rwlock_benchmark.StandardLockWrapper,
    rwlocker.RWLockWrite, rwlocker.RWLockWriteReentrantWriter,
    rwlocker.RWLockRead, rwlocker.RWLockReadReentrantWriter,
    rwlocker.RWLockReaderPhaseFair, rwlocker.RWLockReaderPhaseFairReentrantWriter,
    rwlocker.RWLockFair, rwlocker.RWLockFairReentrantWriter
]

async_locks = [
    async_rwlock_benchmark.AsyncStandardLockWrapper,
    rwlocker.AsyncRWLockWrite, rwlocker.AsyncRWLockWriteReentrantWriter,
    rwlocker.AsyncRWLockRead, rwlocker.AsyncRWLockReadReentrantWriter,
    rwlocker.AsyncRWLockReaderPhaseFair, rwlocker.AsyncRWLockReaderPhaseFairReentrantWriter,
    rwlocker.AsyncRWLockFair, rwlocker.AsyncRWLockFairReentrantWriter
]

conditions = [
    thread_rwcondition_benchmark.StandardConditionWrapper,
    thread_rwcondition_benchmark.RWConditionWriteWrapper, 
    thread_rwcondition_benchmark.RWConditionReadWrapper,
    thread_rwcondition_benchmark.RWConditionReaderPhaseFairWrapper, 
    thread_rwcondition_benchmark.RWConditionFairWrapper
]

async_conditions = [
    async_rwcondition_benchmark.AsyncStandardConditionWrapper,
    async_rwcondition_benchmark.AsyncRWConditionWriteWrapper, 
    async_rwcondition_benchmark.AsyncRWConditionReadWrapper,
    async_rwcondition_benchmark.AsyncRWConditionReaderPhaseFairWrapper,
    async_rwcondition_benchmark.AsyncRWConditionFairWrapper
]

scenarios = [
    PureOverheadScenario(iterations=10)
]

async_scenarios = [
    AsyncPureOverheadScenario(iterations=10)
]

benchmark_config = BenchmarkConfig.interactive()

if __name__ == '__main__':
    thread_rwlock_benchmark.benchmark(scenarios=scenarios, locks=locks, config=benchmark_config)
    asyncio.run(async_rwlock_benchmark.benchmark(
        scenarios=async_scenarios, locks=async_locks, config=benchmark_config
    ))
    thread_rwcondition_benchmark.benchmark(scenarios=scenarios, conditions=conditions, config=benchmark_config)
    asyncio.run(async_rwcondition_benchmark.benchmark(
        scenarios=async_scenarios, conditions=async_conditions, config=benchmark_config
    ))
