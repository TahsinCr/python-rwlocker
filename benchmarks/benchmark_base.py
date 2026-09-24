from __future__ import annotations

import gc
import os
import re
import shutil
import sys
import time
import threading
import asyncio
import statistics
import random
from dataclasses import dataclass
from typing import List, Type

from .benchmark_scenario import BaseScenario

def aggregate(trial_data: List[float]) -> float:
    if not trial_data: return 0.0001
    if len(trial_data) == 1: return trial_data[0]
    
    valid_runs = sorted(trial_data)
    
    mid = len(valid_runs) // 2
    if len(valid_runs) % 2 == 0 and len(valid_runs) > 1:
        return (valid_runs[mid - 1] + valid_runs[mid]) / 2.0
    return valid_runs[mid]


def _benchmark_statistics(trial_data: List[float]) -> dict:
    values = sorted(trial_data)
    median = statistics.median(values)
    deviations = [abs(value - median) for value in values]
    mean = statistics.mean(values)
    variance = statistics.variance(values) if len(values) > 1 else 0.0
    quartiles = statistics.quantiles(values, n=4, method="inclusive") if len(values) > 1 else [values[0]] * 3

    rng = random.Random(0)
    bootstrap_means = sorted(
        statistics.mean(rng.choices(values, k=len(values)))
        for _ in range(2000)
    ) if len(values) > 1 else [values[0]]
    low = bootstrap_means[int(0.025 * (len(bootstrap_means) - 1))]
    high = bootstrap_means[int(0.975 * (len(bootstrap_means) - 1))]
    return {
        "trial_elapsed": trial_data,
        "mean": mean,
        "variance": variance,
        "mad": statistics.median(deviations),
        "p25": quartiles[0],
        "p75": quartiles[2],
        "mean_ci95_bootstrap": [low, high],
    }


@dataclass(frozen=True)
class BenchmarkConfig:
    trials: int = 3
    warmup_trials: int = 1
    rotate_targets: bool = True
    collect_garbage: bool = True
    gc_collect_scope: str = "round"
    disable_gc_during_trial: bool = True

    def __post_init__(self):
        if self.trials < 1:
            raise ValueError("trials must be at least 1")
        if self.warmup_trials < 0:
            raise ValueError("warmup_trials cannot be negative")
        if self.gc_collect_scope not in {"round", "target", "none"}:
            raise ValueError("gc_collect_scope must be one of: 'round', 'target', 'none'")

    @classmethod
    def faster(cls) -> "BenchmarkConfig":
        return cls(trials=1, warmup_trials=0)

    @classmethod
    def interactive(cls) -> "BenchmarkConfig":
        return cls(trials=2, warmup_trials=1)

    @classmethod
    def reporting(cls) -> "BenchmarkConfig":
        return cls(trials=10, warmup_trials=2)


class BenchmarkDataHandler:
    """Base handler for processing and storing benchmark output data as dicts."""
    def __init__(self):
        self.history = []

    def process(self, name: str, num_readers: int, num_writers: int, iterations: int, target_type: str, results: list, baseline_time: float) -> dict:
        results.sort(key=lambda x: x[1])
        
        formatted_results = []
        for target_name, elapsed, throughput, trial_elapsed in results:
            speedup = (baseline_time / elapsed) if baseline_time else 0.0
            formatted_results.append({
                "name": target_name,
                "elapsed": elapsed,
                "throughput": throughput,
                "speedup": speedup,
                **_benchmark_statistics(trial_elapsed),
            })
            
        data = {
            "scenario_name": name,
            "readers": num_readers,
            "writers": num_writers,
            "iterations": iterations,
            "total_operations": int(round(results[0][2] * results[0][1])) if results else 0,
            "target_type": target_type,
            "baseline_time": baseline_time,
            "results": formatted_results
        }
        self.history.append(data)
        return data

class BenchmarkPrintHandler(BenchmarkDataHandler):
    """Handler that prints benchmark results with compact, terminal-friendly tables."""

    _RESET = "\033[0m"
    _BOLD = "\033[1m"
    _DIM = "\033[2m"
    _CYAN = "\033[36m"
    _GREEN = "\033[32m"
    _YELLOW = "\033[33m"
    _RED = "\033[31m"
    _NAME_SEGMENT_RE = re.compile(
        r"[A-Z]+(?=[A-Z][a-z]|$)|[A-Z]?[a-z]+|\d+|[^A-Za-z0-9]+"
    )

    def __init__(self, use_color: bool | None = None):
        super().__init__()
        self._use_color = self._detect_color_support() if use_color is None else use_color

    def _detect_color_support(self) -> bool:
        if os.environ.get("NO_COLOR"):
            return False
        return hasattr(sys.stdout, "isatty") and sys.stdout.isatty()

    def _style(self, text: str, *codes: str) -> str:
        if not self._use_color or not codes:
            return text
        return f"{''.join(codes)}{text}{self._RESET}"

    def _format_throughput(self, throughput: float) -> str:
        return f"{throughput:,.0f}"

    def _format_ops(self, count: int) -> str:
        return f"{count:,}"

    def _layout(self, target_type: str, results: list[dict]) -> tuple[int, int, int, int, int]:
        terminal_width = shutil.get_terminal_size(fallback=(92, 24)).columns
        minimum_total_width = 78
        total_width = max(minimum_total_width, terminal_width)

        time_width = 10
        ops_width = 11
        speed_width = 10
        separators_width = len(" |  |  | ")
        name_width = total_width - time_width - ops_width - speed_width - separators_width
        name_width = max(26, min(name_width, 52))

        longest_name = max(
            [len(target_type), *(len(res["name"]) for res in results)],
            default=name_width,
        )
        name_width = min(max(name_width, min(longest_name, 52)), 52)
        total_width = name_width + time_width + ops_width + speed_width + separators_width
        return total_width, name_width, time_width, ops_width, speed_width

    def _find_baseline_row(self, results: list[dict], baseline_time: float | None) -> dict | None:
        if baseline_time is None:
            return None
        for res in results:
            if self._is_baseline_name(res["name"]) and abs(res["elapsed"] - baseline_time) < 1e-12:
                return res
        return None

    def _is_baseline_name(self, target_name: str) -> bool:
        return "(C-Baseline)" in target_name or target_name.startswith("threading.") or target_name.startswith("asyncio.")

    def _wrap_name(self, text: str, width: int) -> list[str]:
        if width <= 0:
            return [""]
        if len(text) <= width:
            return [text]

        segments = [segment for segment in self._NAME_SEGMENT_RE.findall(text) if segment]
        if not segments:
            return [text[i:i + width] for i in range(0, len(text), width)]

        lines: list[str] = []
        current = ""
        for segment in segments:
            segment = segment if current else segment.lstrip()
            if not segment:
                continue
            candidate = f"{current}{segment}"
            if current and len(candidate) > width:
                lines.append(current.rstrip())
                current = segment.lstrip()
                while len(current) > width:
                    lines.append(current[:width].rstrip())
                    current = current[width:].lstrip()
                continue
            current = candidate

        if current:
            lines.append(current.rstrip())
        return lines or [text]

    def _format_row(
        self,
        name: str,
        elapsed: float,
        throughput: float,
        speedup: float,
        name_width: int,
        time_width: int,
        ops_width: int,
        speed_width: int,
        baseline_time: float | None,
        best_elapsed: float,
    ) -> list[str]:
        is_baseline = self._is_baseline_name(name)
        is_fastest = abs(elapsed - best_elapsed) < 1e-12

        prefix = "BL " if is_baseline else "   "
        wrapped_name = self._wrap_name(name, name_width - len(prefix))

        speedup_text = f"{speedup:>7.2f}x"
        if speedup >= 1.0:
            speedup_text = self._style(speedup_text, self._GREEN if speedup >= 1.05 else self._YELLOW)
        else:
            speedup_text = self._style(speedup_text, self._RED)

        formatted_lines: list[str] = []
        for index, name_line in enumerate(wrapped_name):
            line_prefix = prefix if index == 0 else " " * len(prefix)
            display_name = f"{line_prefix}{name_line}".ljust(name_width)
            if is_baseline:
                display_name = self._style(display_name, self._CYAN, self._BOLD)
            elif is_fastest:
                display_name = self._style(display_name, self._GREEN, self._BOLD)

            if index == 0:
                formatted_lines.append(
                    f"{display_name}"
                    f" | {elapsed:>{time_width}.4f}"
                    f" | {self._format_throughput(throughput):>{ops_width}}"
                    f" | {speedup_text:>{speed_width}}"
                )
            else:
                formatted_lines.append(
                    f"{display_name}"
                    f" | {'':>{time_width}}"
                    f" | {'':>{ops_width}}"
                    f" | {'':>{speed_width}}"
                )
        return formatted_lines

    def _format_metadata_line(self, readers: int, writers: int, iterations: int, total_ops: int) -> str:
        return (
            f"{self._style('Readers:', self._DIM)} {readers}"
            f" | {self._style('Writers:', self._DIM)} {writers}"
            f" | {self._style('Iterations:', self._DIM)} {iterations}"
            f" | {self._style('Ops:', self._DIM)} {self._format_ops(total_ops)}"
        )

    def process(self, name: str, num_readers: int, num_writers: int, iterations: int, target_type: str, results: list, baseline_time: float) -> dict:
        data = super().process(name, num_readers, num_writers, iterations, target_type, results, baseline_time)

        total_width, name_width, time_width, ops_width, speed_width = self._layout(data["target_type"], data["results"])
        divider = "-" * total_width
        best_elapsed = min((res["elapsed"] for res in data["results"]), default=0.0001)
        total_ops = data["total_operations"]

        print()
        print(self._style(f"[{data['scenario_name'].upper()}]", self._BOLD))
        print(self._format_metadata_line(data["readers"], data["writers"], data["iterations"], total_ops))
        print(divider)
        print(
            f"{data['target_type']:<{name_width}}"
            f" | {'Time (s)':>{time_width}}"
            f" | {'Ops/sec':>{ops_width}}"
            f" | {'Speedup':>{speed_width}}"
        )
        print(divider)

        for res in data["results"]:
            for line in self._format_row(
                name=res["name"],
                elapsed=res["elapsed"],
                throughput=res["throughput"],
                speedup=res["speedup"],
                name_width=name_width,
                time_width=time_width,
                ops_width=ops_width,
                speed_width=speed_width,
                baseline_time=baseline_time,
                best_elapsed=best_elapsed,
            ):
                print(line)
        print(divider)

        return data


class BenchmarkerBase:
    """Base class for synchronous (Thread) benchmarkers."""
    def __init__(
        self,
        target_classes: List[Type],
        data_handler: BenchmarkDataHandler = None,
        config: BenchmarkConfig | None = None,
    ):
        self.target_classes = target_classes
        self.data_handler = data_handler or BenchmarkPrintHandler()
        self.config = config or BenchmarkConfig()

    def _resolve_config(self, trials: int | None = None) -> BenchmarkConfig:
        if trials is None or trials == self.config.trials:
            return self.config
        return BenchmarkConfig(
            trials=trials,
            warmup_trials=self.config.warmup_trials,
            rotate_targets=self.config.rotate_targets,
            collect_garbage=self.config.collect_garbage,
            gc_collect_scope=self.config.gc_collect_scope,
            disable_gc_during_trial=self.config.disable_gc_during_trial,
        )

    def _ordered_targets_for_round(self, round_index: int, config: BenchmarkConfig) -> list[Type]:
        targets = list(self.target_classes)
        if not config.rotate_targets or len(targets) < 2:
            return targets
        offset = round_index % len(targets)
        return targets[offset:] + targets[:offset]

    def _is_baseline_target(self, target_name: str) -> bool:
        return "(C-Baseline)" in target_name or target_name.startswith("threading.") or target_name.startswith("asyncio.")

    def _operation_count(self, scenario: BaseScenario, num_readers: int, num_writers: int) -> int:
        return (num_readers + num_writers) * scenario.iterations

    def _collect_garbage(self, config: BenchmarkConfig) -> None:
        if config.collect_garbage and config.gc_collect_scope != "none":
            gc.collect()

    def _prepare_trial_gc(self, config: BenchmarkConfig) -> bool:
        gc_was_enabled = gc.isenabled()
        if config.disable_gc_during_trial and gc_was_enabled:
            gc.disable()
        return gc_was_enabled

    def _restore_trial_gc(self, gc_was_enabled: bool, config: BenchmarkConfig) -> None:
        if config.disable_gc_during_trial and gc_was_enabled:
            gc.enable()

    def _run_target_trial(
        self,
        target_class: Type,
        scenario: BaseScenario,
        num_readers: int,
        num_writers: int,
        config: BenchmarkConfig,
    ) -> float:
        raise NotImplementedError

    def run_workload(self, name: str, scenario:BaseScenario, num_readers: int, num_writers: int, trials: int | None = None):
        config = self._resolve_config(trials)
        iterations = scenario.iterations
        total_ops = self._operation_count(scenario, num_readers, num_writers)
        target_type = "Condition Implementation" if "Condition" in self.__class__.__name__ else "Lock Implementation"
        baseline_candidates, results = [], []
        measured_trials: dict[Type, list[float]] = {target_class: [] for target_class in self.target_classes}

        total_rounds = config.warmup_trials + config.trials
        for round_index in range(total_rounds):
            if config.gc_collect_scope == "round":
                self._collect_garbage(config)
            for target_class in self._ordered_targets_for_round(round_index, config):
                if hasattr(scenario, 'reset'):
                    scenario.reset()
                if config.gc_collect_scope == "target":
                    self._collect_garbage(config)
                gc_was_enabled = self._prepare_trial_gc(config)
                try:
                    elapsed = self._run_target_trial(target_class, scenario, num_readers, num_writers, config)
                finally:
                    self._restore_trial_gc(gc_was_enabled, config)
                if round_index >= config.warmup_trials:
                    measured_trials[target_class].append(elapsed)

        for target_class in self.target_classes:
            target_name = target_class.get_name() if hasattr(target_class, 'get_name') else target_class.__name__
            final_elapsed = aggregate(measured_trials[target_class])
            if self._is_baseline_target(target_name):
                baseline_candidates.append(final_elapsed)
            results.append((target_name, final_elapsed, total_ops / final_elapsed, measured_trials[target_class]))
        baseline_time = min(baseline_candidates) if baseline_candidates else None
        return self.data_handler.process(name, num_readers, num_writers, iterations, target_type, results, baseline_time)

    def _create_workers(self, target_obj: object, scenario: BaseScenario, num_readers: int, num_writers: int, start_barrier: threading.Barrier) -> list:
        raise NotImplementedError

class AsyncBenchmarkerBase(BenchmarkerBase):
    """Base class for asynchronous (Asyncio) benchmarkers."""

    async def _run_target_trial(
        self,
        target_class: Type,
        scenario: BaseScenario,
        num_readers: int,
        num_writers: int,
        config: BenchmarkConfig,
    ) -> float:
        raise NotImplementedError

    async def run_workload(self, name: str, scenario:BaseScenario, num_readers: int, num_writers: int, trials: int | None = None):
        config = self._resolve_config(trials)
        iterations = scenario.iterations
        total_ops = self._operation_count(scenario, num_readers, num_writers)
        target_type = "Condition Implementation" if "Condition" in self.__class__.__name__ else "Lock Implementation"
        baseline_candidates, results = [], []
        measured_trials: dict[Type, list[float]] = {target_class: [] for target_class in self.target_classes}

        total_rounds = config.warmup_trials + config.trials
        for round_index in range(total_rounds):
            if config.gc_collect_scope == "round":
                self._collect_garbage(config)
            for target_class in self._ordered_targets_for_round(round_index, config):
                if hasattr(scenario, 'reset'):
                    scenario.reset()
                if config.gc_collect_scope == "target":
                    self._collect_garbage(config)
                gc_was_enabled = self._prepare_trial_gc(config)
                try:
                    elapsed = await self._run_target_trial(target_class, scenario, num_readers, num_writers, config)
                finally:
                    self._restore_trial_gc(gc_was_enabled, config)
                if round_index >= config.warmup_trials:
                    measured_trials[target_class].append(elapsed)

        for target_class in self.target_classes:
            target_name = target_class.get_name() if hasattr(target_class, 'get_name') else target_class.__name__
            final_elapsed = aggregate(measured_trials[target_class])
            if self._is_baseline_target(target_name):
                baseline_candidates.append(final_elapsed)
            results.append((target_name, final_elapsed, total_ops / final_elapsed, measured_trials[target_class]))
        baseline_time = min(baseline_candidates) if baseline_candidates else None
        return self.data_handler.process(name, num_readers, num_writers, iterations, target_type, results, baseline_time)
