import unittest
from unittest.mock import patch

from benchmarks.benchmark_base import AsyncBenchmarkerBase, BenchmarkConfig, BenchmarkDataHandler, BenchmarkerBase
from benchmarks.benchmark_scenario import BaseScenario


class _Scenario(BaseScenario):
    def __init__(self):
        super().__init__(iterations=3)
        self.reset_calls = 0

    def reset(self):
        super().reset()
        self.reset_calls += 1


class _BaselineA:
    @classmethod
    def get_name(cls):
        return "threading.Lock (C-Baseline)"


class _BaselineB:
    @classmethod
    def get_name(cls):
        return "threading.RLock (C-Baseline)"


class _Target:
    @classmethod
    def get_name(cls):
        return "RWLockWrite"


class _NamedTarget:
    @classmethod
    def get_name(cls):
        return "CustomTarget"


class _SyncBenchmarker(BenchmarkerBase):
    def __init__(self, measurements, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.measurements = {target: list(values) for target, values in measurements.items()}
        self.call_order = []

    def _run_target_trial(self, target_class, scenario, num_readers, num_writers, config):
        del scenario, num_readers, num_writers, config
        self.call_order.append(target_class)
        return self.measurements[target_class].pop(0)


class _AsyncBenchmarker(AsyncBenchmarkerBase):
    def __init__(self, measurements, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.measurements = {target: list(values) for target, values in measurements.items()}
        self.call_order = []

    async def _run_target_trial(self, target_class, scenario, num_readers, num_writers, config):
        del scenario, num_readers, num_writers, config
        self.call_order.append(target_class)
        return self.measurements[target_class].pop(0)


class BenchmarkerBaseTests(unittest.TestCase):
    def test_benchmark_config_profiles_balance_speed_and_reliability(self):
        self.assertEqual(BenchmarkConfig().trials, 3)
        self.assertEqual(BenchmarkConfig.interactive().trials, 2)
        self.assertEqual(BenchmarkConfig.reporting().trials, 10)
        self.assertEqual(BenchmarkConfig.interactive().warmup_trials, 1)
        self.assertEqual(BenchmarkConfig.reporting().warmup_trials, 2)
        self.assertEqual(BenchmarkConfig().gc_collect_scope, "round")

    def test_run_workload_uses_median_and_skips_warmup(self):
        config = BenchmarkConfig(
            trials=3,
            warmup_trials=1,
            rotate_targets=False,
            collect_garbage=False,
            disable_gc_during_trial=False,
        )
        measurements = {
            _BaselineA: [11.0, 5.0, 3.0, 1.0],
            _Target: [99.0, 7.0, 9.0, 11.0],
        }
        benchmarker = _SyncBenchmarker(
            measurements,
            [_BaselineA, _Target],
            config=config,
            data_handler=BenchmarkDataHandler(),
        )
        scenario = _Scenario()

        data = benchmarker.run_workload("demo", scenario, num_readers=2, num_writers=1)

        self.assertEqual(scenario.reset_calls, 8)
        self.assertEqual(data["baseline_time"], 3.0)
        self.assertEqual(data["results"][0]["name"], "threading.Lock (C-Baseline)")
        self.assertEqual(data["results"][0]["elapsed"], 3.0)
        self.assertEqual(data["results"][0]["trial_elapsed"], [5.0, 3.0, 1.0])
        self.assertEqual(data["results"][0]["variance"], 4.0)
        self.assertEqual(data["results"][0]["mad"], 2.0)
        self.assertEqual(data["results"][0]["p25"], 2.0)
        self.assertIn("mean_ci95_bootstrap", data["results"][0])
        self.assertEqual(data["results"][1]["name"], "RWLockWrite")
        self.assertEqual(data["results"][1]["elapsed"], 9.0)

    def test_condition_operation_count_matches_reader_epochs(self):
        from benchmarks.thread_rwcondition_benchmark import ThreadConditionBenchmarker
        from benchmarks.async_rwcondition_benchmark import AsyncConditionBenchmarker
        scenario = _Scenario()
        expected = 2 * 3 * 4 + 4 * 3
        thread_benchmarker = ThreadConditionBenchmarker([], config=BenchmarkConfig.faster())
        async_benchmarker = AsyncConditionBenchmarker([], config=BenchmarkConfig.faster())
        self.assertEqual(thread_benchmarker._operation_count(scenario, 2, 4), expected)
        self.assertEqual(async_benchmarker._operation_count(scenario, 2, 4), expected)

    def test_run_workload_uses_fastest_baseline_candidate(self):
        config = BenchmarkConfig(
            trials=1,
            warmup_trials=0,
            rotate_targets=False,
            collect_garbage=False,
            disable_gc_during_trial=False,
        )
        measurements = {
            _BaselineA: [4.0],
            _BaselineB: [2.0],
            _Target: [6.0],
        }
        benchmarker = _SyncBenchmarker(
            measurements,
            [_BaselineA, _BaselineB, _Target],
            config=config,
            data_handler=BenchmarkDataHandler(),
        )

        data = benchmarker.run_workload("demo", _Scenario(), num_readers=1, num_writers=1)

        self.assertEqual(data["baseline_time"], 2.0)
        self.assertEqual([item["name"] for item in data["results"]], [
            "threading.RLock (C-Baseline)",
            "threading.Lock (C-Baseline)",
            "RWLockWrite",
        ])

    def test_run_workload_rotates_target_order_between_rounds(self):
        config = BenchmarkConfig(
            trials=2,
            warmup_trials=0,
            rotate_targets=True,
            collect_garbage=False,
            disable_gc_during_trial=False,
        )
        measurements = {
            _BaselineA: [1.0, 1.0],
            _BaselineB: [1.0, 1.0],
            _NamedTarget: [1.0, 1.0],
        }
        benchmarker = _SyncBenchmarker(
            measurements,
            [_BaselineA, _BaselineB, _NamedTarget],
            config=config,
            data_handler=BenchmarkDataHandler(),
        )

        benchmarker.run_workload("demo", _Scenario(), num_readers=1, num_writers=1)

        self.assertEqual(
            benchmarker.call_order,
            [_BaselineA, _BaselineB, _NamedTarget, _BaselineB, _NamedTarget, _BaselineA],
        )

    def test_run_workload_collects_garbage_once_per_round_by_default(self):
        config = BenchmarkConfig(
            trials=2,
            warmup_trials=1,
            rotate_targets=False,
            collect_garbage=True,
            gc_collect_scope="round",
            disable_gc_during_trial=False,
        )
        measurements = {
            _BaselineA: [1.0, 1.0, 1.0],
            _Target: [1.0, 1.0, 1.0],
        }
        benchmarker = _SyncBenchmarker(
            measurements,
            [_BaselineA, _Target],
            config=config,
            data_handler=BenchmarkDataHandler(),
        )

        with patch("benchmarks.benchmark_base.gc.collect") as collect_mock:
            benchmarker.run_workload("demo", _Scenario(), num_readers=1, num_writers=1)

        self.assertEqual(collect_mock.call_count, 3)

    def test_run_workload_can_collect_garbage_per_target_when_requested(self):
        config = BenchmarkConfig(
            trials=2,
            warmup_trials=1,
            rotate_targets=False,
            collect_garbage=True,
            gc_collect_scope="target",
            disable_gc_during_trial=False,
        )
        measurements = {
            _BaselineA: [1.0, 1.0, 1.0],
            _Target: [1.0, 1.0, 1.0],
        }
        benchmarker = _SyncBenchmarker(
            measurements,
            [_BaselineA, _Target],
            config=config,
            data_handler=BenchmarkDataHandler(),
        )

        with patch("benchmarks.benchmark_base.gc.collect") as collect_mock:
            benchmarker.run_workload("demo", _Scenario(), num_readers=1, num_writers=1)

        self.assertEqual(collect_mock.call_count, 6)


class AsyncBenchmarkerBaseTests(unittest.IsolatedAsyncioTestCase):
    async def test_async_run_workload_uses_fastest_baseline_candidate(self):
        config = BenchmarkConfig(
            trials=2,
            warmup_trials=1,
            rotate_targets=True,
            collect_garbage=False,
            disable_gc_during_trial=False,
        )
        measurements = {
            _BaselineA: [9.0, 4.0, 2.0],
            _BaselineB: [8.0, 3.0, 1.0],
            _Target: [7.0, 6.0, 5.0],
        }
        benchmarker = _AsyncBenchmarker(
            measurements,
            [_BaselineA, _BaselineB, _Target],
            config=config,
            data_handler=BenchmarkDataHandler(),
        )
        scenario = _Scenario()

        data = await benchmarker.run_workload("demo", scenario, num_readers=1, num_writers=1)

        self.assertEqual(scenario.reset_calls, 9)
        self.assertEqual(data["baseline_time"], 2.0)
        self.assertEqual(
            benchmarker.call_order,
            [_BaselineA, _BaselineB, _Target, _BaselineB, _Target, _BaselineA, _Target, _BaselineA, _BaselineB],
        )
