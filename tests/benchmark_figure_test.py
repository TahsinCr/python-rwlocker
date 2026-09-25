import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


HAS_PLOT_DEPENDENCIES = all(
    importlib.util.find_spec(name) is not None
    for name in ("pandas", "matplotlib", "seaborn")
)
if HAS_PLOT_DEPENDENCIES:
    from benchmark_figure_script import BenchmarkPlotter


class BenchmarkFigureTests(unittest.TestCase):
    @unittest.skipUnless(HAS_PLOT_DEPENDENCIES, "install rwlocker[benchmark] to run plotting tests")
    def test_sync_speedup_uses_baseline_from_each_environment(self):
        with tempfile.TemporaryDirectory() as directory:
            data_dir = Path(directory)
            history = [{
                "scenario_name": "IOBoundScenario",
                "readers": 2,
                "writers": 1,
                "iterations": 3,
                "target_type": "Lock Implementation",
                "results": [
                    {
                        "name": "threading.Lock (C-Baseline)",
                        "elapsed": 2.0,
                        "throughput": 3.0,
                        "speedup": 1.0,
                    },
                    {
                        "name": "RWLockFair",
                        "elapsed": 1.0,
                        "throughput": 6.0,
                        "speedup": 2.0,
                    },
                ],
            }]
            (data_dir / "python3.14_standard.json").write_text(
                json.dumps(history), encoding="utf-8"
            )
            threaded_history = json.loads(json.dumps(history))
            threaded_history[0]["results"][0]["elapsed"] = 8.0
            threaded_history[0]["results"][1]["elapsed"] = 2.0
            (data_dir / "python3.14t_gil_off.json").write_text(
                json.dumps(threaded_history), encoding="utf-8"
            )

            plotter = BenchmarkPlotter(data_dir)
            for environment, expected in (
                ("Standard\nPython", 2.0),
                ("Free-Threading\n(GIL Off)", 4.0),
            ):
                target = plotter.df[
                    (plotter.df["Environment"] == environment)
                    & (plotter.df["Name"].str.contains("RWLockFair"))
                ]
                self.assertEqual(len(target), 1)
                self.assertAlmostEqual(target.iloc[0]["Speedup"], expected)


if __name__ == "__main__":
    unittest.main()
