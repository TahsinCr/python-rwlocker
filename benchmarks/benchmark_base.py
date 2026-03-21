import gc
import time
import threading
import asyncio
from typing import List, Type

from .benchmark_scenario import BaseScenario

class BenchmarkDataHandler:
    """Base handler for processing and storing benchmark output data as dicts."""
    def __init__(self):
        self.history = []

    def process(self, name: str, num_readers: int, num_writers: int, iterations: int, target_type: str, results: list, baseline_time: float) -> dict:
        results.sort(key=lambda x: x[1])
        
        formatted_results = []
        for target_name, elapsed, throughput in results:
            speedup = (baseline_time / elapsed) if baseline_time else 0.0
            formatted_results.append({
                "name": target_name,
                "elapsed": elapsed,
                "throughput": throughput,
                "speedup": speedup
            })
            
        data = {
            "scenario_name": name,
            "readers": num_readers,
            "writers": num_writers,
            "iterations": iterations,
            "target_type": target_type,
            "baseline_time": baseline_time,
            "results": formatted_results
        }
        self.history.append(data)
        return data

class BenchmarkPrintHandler(BenchmarkDataHandler):
    """Handler that prints benchmark results to the console while preserving the exact style."""
    def process(self, name: str, num_readers: int, num_writers: int, iterations: int, target_type: str, results: list, baseline_time: float) -> dict:
        data = super().process(name, num_readers, num_writers, iterations, target_type, results, baseline_time)
        
        print(f"\n[{data['scenario_name'].upper()}]")
        print(f"Readers: {data['readers']} | Writers: {data['writers']} | Iterations: {data['iterations']}")
        print("-" * 88)
        print(f"{data['target_type']:<32} | {'Time (s)':<15} | {'Ops/sec':<15} | {'Speedup vs Base':<15}")
        print("-" * 88)
        
        for res in data["results"]:
            marker = ">> " if res["speedup"] > 1.2 else "   "
            print(f"{marker}{res['name']:<29} | {res['elapsed']:<15.4f} | {res['throughput']:<15.0f} | {res['speedup']:<10.2f}x")
        print("-" * 88)
        
        return data


class BenchmarkerBase:
    """Base class for synchronous (Thread) benchmarkers."""
    def __init__(self, target_classes: List[Type], data_handler: BenchmarkDataHandler = None):
        self.target_classes = target_classes
        self.data_handler = data_handler or BenchmarkPrintHandler()

    def run_workload(self, name: str, scenario:BaseScenario, num_readers: int, num_writers: int, iterations: int):
        total_ops = (num_readers + num_writers) * iterations
        target_type = "Condition Implementation" if "Condition" in self.__class__.__name__ else "Lock Implementation"
        results, baseline_time = [], None

        for target_class in self.target_classes:
            target_name = target_class.get_name() if hasattr(target_class, 'get_name') else target_class.__name__
            gc.disable()
            if hasattr(scenario, 'reset'): scenario.reset()
            
            target_obj, start_event = target_class(), threading.Event()
            threads = self._create_workers(target_obj, scenario, num_readers, num_writers, iterations, start_event)

            for t in threads: t.start()
            start_time = time.perf_counter()
            start_event.set()
            for t in threads: t.join()
            
            elapsed = time.perf_counter() - start_time
            gc.enable()
            if "Baseline" in target_name or "threading." in target_name: baseline_time = elapsed
            results.append((target_name, elapsed, total_ops / elapsed))
        return self.data_handler.process(name, num_readers, num_writers, iterations, target_type, results, baseline_time)

    def _create_workers(self, target_obj: object, scenario: BaseScenario, num_readers: int, num_writers: int, iterations: int, start_event: threading.Event) -> list:
        raise NotImplementedError


class AsyncBenchmarkerBase(BenchmarkerBase):
    """Base class for asynchronous (Asyncio) benchmarkers."""

    async def run_workload(self, name: str, scenario:BaseScenario, num_readers: int, num_writers: int, iterations: int):
        total_ops = (num_readers + num_writers) * iterations
        target_type = "Condition Implementation" if "Condition" in self.__class__.__name__ else "Lock Implementation"
        results, baseline_time = [], None

        for target_class in self.target_classes:
            target_name = target_class.get_name() if hasattr(target_class, 'get_name') else target_class.__name__
            gc.disable()
            if hasattr(scenario, 'reset'): scenario.reset()
            
            target_obj, start_event = target_class(), asyncio.Event()
            tasks = self._create_workers(target_obj, scenario, num_readers, num_writers, iterations, start_event)

            await asyncio.sleep(0)
            start_time = time.perf_counter()
            start_event.set()
            await asyncio.gather(*tasks)
            
            elapsed = time.perf_counter() - start_time
            gc.enable()
            if "Baseline" in target_name or "asyncio." in target_name: baseline_time = elapsed
            results.append((target_name, elapsed, total_ops / elapsed))
        return self.data_handler.process(name, num_readers, num_writers, iterations, target_type, results, baseline_time)
