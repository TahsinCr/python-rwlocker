import sys
import json
import asyncio
from typing import List
from pathlib import Path

import rwlocker
from benchmarks.benchmark_base import BenchmarkConfig, BenchmarkDataHandler
from benchmarks.benchmark_scenario import (
    BaseScenario, AsyncBaseScenario, 
    IOBoundScenario, AsyncIOBoundScenario
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
    rwlocker.RWLockWrite, 
    rwlocker.RWLockWriteReentrantWriter,
    rwlocker.RWLockRead, 
    rwlocker.RWLockReadReentrantWriter,
    rwlocker.RWLockReaderPhaseFair, 
    rwlocker.RWLockReaderPhaseFairReentrantWriter,
    rwlocker.RWLockFair, 
    rwlocker.RWLockFairReentrantWriter
]

conditions = [
    thread_rwcondition_benchmark.StandardConditionWrapper,
    thread_rwcondition_benchmark.RWConditionWriteWrapper, 
    thread_rwcondition_benchmark.RWConditionReadWrapper, 
    thread_rwcondition_benchmark.RWConditionReaderPhaseFairWrapper,
    thread_rwcondition_benchmark.RWConditionFairWrapper
]

async_locks = [
    async_rwlock_benchmark.AsyncStandardLockWrapper,
    rwlocker.AsyncRWLockWrite, rwlocker.AsyncRWLockWriteReentrantWriter,
    rwlocker.AsyncRWLockRead, rwlocker.AsyncRWLockReadReentrantWriter,
    rwlocker.AsyncRWLockReaderPhaseFair, rwlocker.AsyncRWLockReaderPhaseFairReentrantWriter,
    rwlocker.AsyncRWLockFair, rwlocker.AsyncRWLockFairReentrantWriter
]

async_conditions = [
    async_rwcondition_benchmark.AsyncStandardConditionWrapper,
    async_rwcondition_benchmark.AsyncRWConditionWriteWrapper, 
    async_rwcondition_benchmark.AsyncRWConditionReadWrapper, 
    async_rwcondition_benchmark.AsyncRWConditionReaderPhaseFairWrapper,
    async_rwcondition_benchmark.AsyncRWConditionFairWrapper
]

class BenchmarkDataCollector:
    """
    A modular utility to collect benchmark data silently and export to JSON.
    Designed to be called via subprocess or orchestrators for different Python environments.
    """
    def __init__(self, filepath: Path, config: BenchmarkConfig | None = None):
        self.filepath = filepath
        self.data_handler = BenchmarkDataHandler()
        self.config = config or BenchmarkConfig.interactive()

    def collect(self, sync_scenarios: List[BaseScenario], async_scenarios: List[AsyncBaseScenario]):
        print(f"[{self.filepath}] Data collection has begun...")
        thread_rwlock_benchmark.benchmark(sync_scenarios, locks, data_handler=self.data_handler, config=self.config)
        asyncio.run(async_rwlock_benchmark.benchmark(async_scenarios, async_locks, data_handler=self.data_handler, config=self.config))
        thread_rwcondition_benchmark.benchmark(sync_scenarios, conditions, data_handler=self.data_handler, config=self.config)
        asyncio.run(async_rwcondition_benchmark.benchmark(async_scenarios, async_conditions, data_handler=self.data_handler, config=self.config))
        print(f"[{self.filepath}] Data collection is complete.")
        self._save_to_file()

    def _save_to_file(self):
        with open(self.filepath, 'w', encoding='utf-8') as f:
            json.dump(self.data_handler.history, f, indent=4, ensure_ascii=False)
        print(f"[{self.filepath}] Data has been successfully saved.")


if __name__ == '__main__':
    if len(sys.argv) > 1:
        target_path = Path(sys.argv[1])
    else:
        target_path = Path.cwd().joinpath('figures','test_data.json')
        
    collector = BenchmarkDataCollector(target_path)
    collector.collect(
        sync_scenarios=[
            IOBoundScenario()
        ], 
        async_scenarios=[
            AsyncIOBoundScenario()
        ]
    )
