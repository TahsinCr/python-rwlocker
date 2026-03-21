import time
import asyncio

class BaseScenario:
    """Base class for all benchmark scenarios."""
    def __init__(self):
        self.epoch = 0
    
    def get_name(self): return "Base Scenario"
    def execute_read(self): pass
    def execute_write(self): pass

    def reset(self):
        self.epoch = 0

class AsyncBaseScenario(BaseScenario):
    """Base class for all asynchronous benchmark scenarios."""
    async def execute_read(self): pass
    async def execute_write(self): pass

class IOBoundScenario(BaseScenario):
    """
    Simulates a Real-World Database or Network Request.
    During time.sleep(), Python releases the GIL, allowing TRUE concurrency.
    """
    def __init__(self, read_delay=0.001, write_delay=0.001):
        self.read_delay = read_delay
        self.write_delay = write_delay
        self.epoch = 0

    def get_name(self):
        return "I/O Bound (Database/API Simulator)"
    
    def execute_read(self):
        time.sleep(self.read_delay)

    def execute_write(self):
        time.sleep(self.write_delay)

    def reset(self):
        self.epoch = 0

class AsyncIOBoundScenario(AsyncBaseScenario):
    """
    Simulates a Real-World Async Database or Network Request.
    During await asyncio.sleep(), the event loop switches tasks.
    """
    def __init__(self, read_delay=0.001, write_delay=0.001):
        self.read_delay = read_delay
        self.write_delay = write_delay
        self.epoch = 0

    def get_name(self):
        return "Async I/O Bound (Database/API Simulator)"
    
    async def execute_read(self):
        await asyncio.sleep(self.read_delay)

    async def execute_write(self):
        await asyncio.sleep(self.write_delay)

    def reset(self):
        self.epoch = 0

class CPUBoundScenario(BaseScenario):
    """
    Simulates a Real-World CPU-Bound Data Processing Task.
    In Free-Threading (No-GIL) Python, this achieves TRUE PARALLELISM across all cores.
    """
    def __init__(self, read_workload=20_000, write_workload=20_000):
        self.read_workload = read_workload
        self.write_workload = write_workload
        self.epoch = 0

    def get_name(self):
        return "CPU Bound (True Parallelism Simulator)"
    
    def execute_read(self):
        _ = sum(i * i for i in range(self.read_workload))

    def execute_write(self):
        _ = sum(i * i for i in range(self.write_workload))

    def reset(self):
        self.epoch = 0
