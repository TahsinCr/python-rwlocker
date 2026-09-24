import time
import asyncio
import hashlib

class BaseScenario:
    """Base class for all benchmark scenarios."""
    def __init__(self, iterations=10):
        self.epoch = 0
        self.iterations = iterations
    
    def get_name(self): return "Base Scenario"
    def execute_read(self, worker_id: int): pass
    def execute_write(self, worker_id: int): pass

    def reset(self):
        self.epoch = 0

class AsyncBaseScenario(BaseScenario):
    """Base class for all asynchronous benchmark scenarios."""
    async def execute_read(self, worker_id: int): pass
    async def execute_write(self, worker_id: int): pass



class IOBoundScenario(BaseScenario):
    """
    Simulates a Real-World Database or Network Request.
    During time.sleep(), Python releases the GIL, allowing TRUE concurrency.
    """
    def __init__(self, read_delay=0.001, write_delay=0.001, iterations=10):
        super().__init__(iterations)
        self.read_delay = read_delay
        self.write_delay = write_delay
        self.epoch = 0

    def get_name(self):
        return "I/O Bound (Database/API Simulator)"
    
    def execute_read(self, worker_id: int):
        time.sleep(self.read_delay)

    def execute_write(self, worker_id: int):
        time.sleep(self.write_delay)

    def reset(self):
        self.epoch = 0

class AsyncIOBoundScenario(AsyncBaseScenario):
    """
    Simulates a Real-World Async Database or Network Request.
    During await asyncio.sleep(), the event loop switches tasks.
    """
    def __init__(self, read_delay=0.001, write_delay=0.001, iterations=10):
        super().__init__(iterations)
        self.read_delay = read_delay
        self.write_delay = write_delay
        self.epoch = 0

    def get_name(self):
        return "Async I/O Bound (Database/API Simulator)"
    
    async def execute_read(self, worker_id: int):
        await asyncio.sleep(self.read_delay)

    async def execute_write(self, worker_id: int):
        await asyncio.sleep(self.write_delay)

    def reset(self):
        self.epoch = 0



class CPUBoundScenario(BaseScenario):
    """
    Simulates a Real-World CPU-Bound Data Processing Task.
    In Free-Threading (No-GIL) Python, this achieves TRUE PARALLELISM across all cores.
    """
    def __init__(self, read_workload=20_000, write_workload=20_000, iterations=10):
        super().__init__(iterations)
        self.read_workload = read_workload
        self.write_workload = write_workload
        self.epoch = 0

    def get_name(self):
        return "CPU Bound (True Parallelism Simulator)"
    
    def execute_read(self, worker_id: int):
        _ = sum(i * i for i in range(self.read_workload))

    def execute_write(self, worker_id: int):
        _ = sum(i * i for i in range(self.write_workload))

    def reset(self):
        self.epoch = 0

class AsyncCPUBoundScenario(CPUBoundScenario):
    """
    Simulates a Real-World CPU-Bound Data Processing Task.
    Runs CPU work in the default executor so the event loop remains responsive.
    Multiple workers can run in parallel on free-threaded Python builds.
    """
    async def execute_read(self, worker_id: int):
        await asyncio.to_thread(super().execute_read, worker_id)

    async def execute_write(self, worker_id: int):
        await asyncio.to_thread(super().execute_write, worker_id)



class PureOverheadScenario(BaseScenario):
    def __init__(self, iterations=10_000):
        super().__init__(iterations)
        self.shared_counter = 0

    def get_name(self):
        return "Pure Overhead (High Contention & Zero-Sleep)"
    
    def execute_read(self, worker_id: int):
        _ = self.shared_counter

    def execute_write(self, worker_id: int):
        self.shared_counter += 1

    def reset(self):
        self.epoch = 0
        self.shared_counter = 0

class AsyncPureOverheadScenario(PureOverheadScenario): 
    async def execute_read(self, worker_id: int):
        super().execute_read(worker_id)

    async def execute_write(self, worker_id: int):
        super().execute_write(worker_id)



class BankTransactionScenario(BaseScenario):
    """
    A highly complex scenario combining CPU (Hashing), Memory (State Dict), 
    and I/O (Sleep) load across hundreds of shared items.
    """
    def __init__(self, num_accounts=1000, io_delay=0.0001, iterations=50):
        super().__init__(iterations)
        self.num_accounts = num_accounts
        self.io_delay = io_delay
        self.accounts = {i: 1000.0 for i in range(self.num_accounts)}
        
    def get_name(self):
        return "Bank Transactions (Mixed CPU + I/O + Memory)"
    
    def _execute_read(self, worker_id: int):
        acc_id = (worker_id + self.epoch) % self.num_accounts
        balance = self.accounts[acc_id]
        _ = hashlib.md5(f"audit_{acc_id}_{balance}".encode()).hexdigest()     
        
    def execute_read(self, worker_id: int):
        self._execute_read(worker_id)
        if self.io_delay > 0:
            time.sleep(self.io_delay)

    def _execute_write(self, worker_id: int):
        from_acc = worker_id % self.num_accounts
        to_acc = (worker_id + 1) % self.num_accounts
        amount = 10.0
        _ = hashlib.md5(f"transfer_{from_acc}_{to_acc}_{amount}".encode()).hexdigest()
        self.accounts[from_acc] -= amount
        self.accounts[to_acc] += amount

    def execute_write(self, worker_id: int):
        self._execute_write(worker_id)
        if self.io_delay > 0:
            time.sleep(self.io_delay)
            
    def reset(self):
        super().reset()
        self.accounts = {i: 1000.0 for i in range(self.num_accounts)}

class AsyncBankTransactionScenario(BankTransactionScenario):
    """Async equivalent of the complex Bank Transaction scenario."""  
    async def execute_read(self, worker_id: int):
        self._execute_read(worker_id)
        if self.io_delay > 0:
            await asyncio.sleep(self.io_delay)

    async def execute_write(self, worker_id: int):
        self._execute_write(worker_id)
        if self.io_delay > 0:
            await asyncio.sleep(self.io_delay)
