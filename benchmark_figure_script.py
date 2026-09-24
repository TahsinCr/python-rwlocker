import os
import sys
import json
import subprocess
from pathlib import Path

try:
    import pandas as pd
    import seaborn as sns
    import matplotlib.pyplot as plt
except ImportError:
    print("Missing required libraries: 'pandas', 'seaborn', 'matplotlib'.")
    print("Please install them using: pip install pandas seaborn matplotlib")
    sys.exit(1)

standard_python = os.environ.get("RWLOCKER_PYTHON_STANDARD", sys.executable)
free_threaded_python = os.environ.get("RWLOCKER_PYTHON_FREE_THREADED")
environments = [{
    "name": f"{Path(standard_python).name}_standard",
    "executable": standard_python,
    "env_vars": {},
}]
if free_threaded_python:
    environments.extend([
        {
            "name": f"{Path(free_threaded_python).name}_gil_on",
            "executable": free_threaded_python,
            "env_vars": {"PYTHON_GIL": "1"},
        },
        {
            "name": f"{Path(free_threaded_python).name}_gil_off",
            "executable": free_threaded_python,
            "env_vars": {"PYTHON_GIL": "0"},
        },
    ])

class BenchmarkOrchestrator:
    """
    Triggers collect_benchmark_data.py across different Python interpreters
    and environments (e.g., Free-Threading GIL on/off).
    """
    def __init__(self, base_dir: Path):
        self.base_dir = base_dir
        self.target_script = Path.cwd().joinpath("collect_benchmark_data_script.py")

    def collect_all_data(self):
        self.base_dir.mkdir(parents=True, exist_ok=True)
        for env_config in environments:
            env_name = env_config["name"]
            executable = str(Path(env_config["executable"]).expanduser())
            env_vars = env_config["env_vars"]
            
            output_file = self.base_dir.joinpath(f"{env_name}.json")
            print(f"[{env_name}] Collecting data -> {output_file}")
            
            current_env = os.environ.copy()
            current_env.update(env_vars)
            
            command = [executable, str(self.target_script), str(output_file)]
            
            try:
                subprocess.run(command, cwd=Path.cwd(), env=current_env, check=True)
            except subprocess.CalledProcessError as e:
                print(f"[{env_name}] Execution failed: {e}")
            except FileNotFoundError:
                print(f"'{executable}' command not found. Skipping...")


class BenchmarkPlotter:
    """
    Reads JSON results from the figures directory and generates highly detailed,
    modern, and beautiful Seaborn SVG plots for GitHub Readme.
    """
    # Moved style dictionary to a class constant for clarity and reuse.
    _PLOT_STYLE_RC = {
        "figure.facecolor": "none",
        "axes.facecolor": "none",
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.spines.left": False,
        "grid.linestyle": "--",
        "grid.alpha": 0.2,
        "grid.color": "#9ca3af",
        "axes.edgecolor": "#9ca3af",
        "text.color": "#9ca3af",
        "axes.labelcolor": "#9ca3af",
        "xtick.color": "#9ca3af",
        "ytick.color": "#9ca3af",
        "font.family": "DejaVu Sans",
        "hatch.linewidth": 2.0
    }
    _SYNC_ENV_PALETTE = ["#3b82f6", "#10b981", "#ef4444"]

    def __init__(self, base_dir: Path):
        self.base_dir = base_dir
        self.df = self._load_and_process_data()

    def _get_display_env(self, env_name: str) -> str:
        """Maps internal environment name to a display-friendly string."""
        if "standard" in env_name.lower():
            return "Standard\nPython"
        if "gil_off" in env_name.lower():
            return "Free-Threading\n(GIL Off)"
        if "gil_on" in env_name.lower():
            return "Free-Threading\n(GIL On)"
        return env_name

    def _format_lock_name(self, name: str) -> str:
        """Formats lock names for better plot readability."""
        name = name.replace("ReentrantWriter", "\n(Reentrant)").replace(" (", "\n(")
        return name.replace("RWLockReaderPhaseFair", "RWLock\nReaderPhaseFair")

    def _get_plot_category(self, name: str, target_type: str) -> str:
        """Determines the plot category (Sync/Async, Lock/Cond)."""
        is_async = "Async" in name or "asyncio" in name
        if target_type == "Lock Implementation":
            return "AsyncLock" if is_async else "SyncLock"
        return "AsyncCond" if is_async else "SyncCond"

    def _load_and_process_data(self) -> pd.DataFrame:
        """Loads all JSON data, processes it into a DataFrame, and recalculates speedups."""
        rows = []
        json_files = list(self.base_dir.glob("*.json"))
        if not json_files:
            return pd.DataFrame()

        for json_file in json_files:
            display_env = self._get_display_env(json_file.stem)
            with open(json_file, "r", encoding="utf-8") as f:
                history = json.load(f)
            
            for entry in history:
                if not entry.get("results"):
                    continue
                    
                cat = self._get_plot_category(entry["results"][0]["name"], entry["target_type"])
                worker_type = "Tasks" if "Async" in cat else "Threads"
                readers = entry.get("readers", 0)
                writers = entry.get("writers", 0)
                iterations = entry.get("iterations", 0)
                
                scenario_str = f"{entry['scenario_name']} [{worker_type}: {readers} Reader | {writers} Writer]"
                
                for res in entry["results"]:
                    rows.append({
                        "Environment": display_env,
                        "Category": cat,
                        "Scenario": scenario_str,
                        "Name": self._format_lock_name(res["name"]),
                        "Throughput": res["throughput"],
                        "Elapsed": res["elapsed"],
                        "Speedup": res["speedup"]
                    })
        
        df = pd.DataFrame(rows)
        
        # Recalculate speedup for sync categories relative to the standard Python baseline
        for category in ["SyncLock", "SyncCond"]:
            for scenario in df["Scenario"].unique():
                mask = (df["Category"] == category) & (df["Scenario"] == scenario)
                if not mask.any():
                    continue
                
                # Compare implementations within the same interpreter environment.
                environment = df.loc[mask, "Environment"].iloc[0]
                baseline_mask = mask & (df["Environment"] == environment) & df["Name"].str.contains("Baseline")
                    
                if baseline_mask.any():
                    baseline_time = df.loc[baseline_mask, "Elapsed"].values[0]
                    df.loc[mask, "Speedup"] = baseline_time / df.loc[mask, "Elapsed"]

        return df

    def _annotate_plot(self, g: sns.FacetGrid, y_col: str):
        """Adds detailed text annotations to each bar in the plot."""
        
        for scenario, ax in g.axes_dict.items():
            sub_df = g.data[g.data["Scenario"] == scenario]
            local_y_order = sub_df[y_col].unique()
            max_width = 0
            
            for container in ax.containers:
                for patch in container:
                    val = patch.get_width()
                    if pd.isna(val) or val <= 0:
                        continue
                    max_width = max(max_width, val)
                    
                    y_center = patch.get_y() + patch.get_height() / 2.
                    try:
                        y_idx = int(round(y_center))
                        if not (0 <= y_idx < len(local_y_order)): continue
                        y_val = local_y_order[y_idx]
                    except (IndexError, ValueError):
                        continue

                    is_baseline = "Baseline" in str(y_val) or "threading." in str(y_val) or "asyncio." in str(y_val)

                    # Style baseline bars with hatching
                    if is_baseline:
                        orig_color = patch.get_facecolor()
                        patch.set_facecolor('none')
                        patch.set_edgecolor(orig_color)
                        patch.set_hatch('////')
                        patch.set_linewidth(1.5)
                        patch.set_alpha(1.0)
                    
                    # Find the exact data row to get annotation text.
                    # The fuzzy match is a pragmatic way to handle floating point inaccuracies
                    # and the difficulty of mapping a patch back to a hue+y value.
                    row_candidates = sub_df[sub_df[y_col] == y_val]
                    if not row_candidates.empty:
                        diffs = (row_candidates["Throughput"] - val).abs()
                        best_match_idx = diffs.idxmin()
                        
                        if diffs.loc[best_match_idx] < (val * 0.05) + 1e-5:
                            data_row = row_candidates.loc[best_match_idx]
                            
                            text = (
                                f"  {data_row['Speedup']:.2f}x  |  {data_row['Elapsed']:.3f}s\n"
                                f"  {int(data_row['Throughput']):,} Ops/sec"
                            )
                            ax.text(val, y_center, text, 
                                    va='center', ha='left', fontsize=15, color='#9ca3af', fontweight='bold')
            
            if max_width > 0:
                ax.set_xlim(0, max_width * 1.55)
            
            ax.tick_params(axis='y', labelsize=17)
            for label in ax.get_yticklabels():
                label.set_fontweight("bold")
                
            ax.tick_params(axis='x', labelsize=15)
            for label in ax.get_xticklabels():
                label.set_fontweight("bold")

    def _create_plot(self, df: pd.DataFrame, x: str, y: str, hue: str, filename: str, palette: list, height: float, aspect: float):
        """Creates, annotates, and saves a single figure."""
        sns.set_theme(style="darkgrid", palette=palette, rc=self._PLOT_STYLE_RC)
        
        # --- Data Ordering ---
        scenario_keywords = ["Read-Heavy", "Balance", "Write-Heavy"]
        col_order = []
        for keyword in scenario_keywords:
            for s in df["Scenario"].unique():
                if keyword in s and s not in col_order:
                    col_order.append(s)
        col_order += [s for s in df["Scenario"].unique() if s not in col_order]
        
        df["Scenario"] = pd.Categorical(df["Scenario"], categories=col_order, ordered=True)

        # Sort dynamically by Max Throughput (highest to lowest) per scenario
        df["Max_TP"] = df.groupby(["Scenario", y])["Throughput"].transform('max')

        hue_order = None
        if hue == "Environment":
            expected_envs = ["Standard\nPython", "Free-Threading\n(GIL Off)", "Free-Threading\n(GIL On)"]
            hue_order = [e for e in expected_envs if e in df[hue].unique()]
            hue_order += [e for e in df[hue].unique() if e not in hue_order]
            df[hue] = pd.Categorical(df[hue], categories=hue_order, ordered=True)
            df = df.sort_values(by=["Scenario", "Max_TP", hue], ascending=[True, False, True])
        else:
            df = df.sort_values(by=["Scenario", "Max_TP"], ascending=[True, False])
            global_max_tp = df.groupby(y)["Throughput"].max().sort_values(ascending=False)
            hue_order = global_max_tp.index.tolist()
        
        # --- Plotting ---
        plot_kwargs = {"linewidth": 0, "width": 0.7}
        if hue == "Environment":
            plot_kwargs["width"] = 0.82
            try:
                if int(sns.__version__.split(".")[1]) >= 13:
                    plot_kwargs["gap"] = 0.20
            except (ValueError, IndexError):
                pass
        else:
            plot_kwargs["dodge"] = False

        g = sns.FacetGrid(
            df, col="Scenario", col_wrap=1, sharex=False, sharey=False,
            height=height, aspect=aspect, col_order=col_order
        )
        
        g.map_dataframe(
            sns.barplot, x=x, y=y, hue=hue,
            palette=palette, hue_order=hue_order, **plot_kwargs
        )
        
        # --- Styling and Annotation ---
        g.set_axis_labels("Throughput (Ops/sec)", "", fontsize=18, fontweight="bold")
        g.set_titles("{col_name}")
        for ax in g.axes.flat:
            title = ax.get_title()
            ax.set_title("")  # Küçük kopyayı engellemek için varsayılan (orta) başlığı temizle
            ax.set_title(title, fontweight="bold", size=24, loc="left", x=-0.03)
        g.fig.subplots_adjust(hspace=2.0 / height)
        
        self._annotate_plot(g, y)

        if hue == "Environment":
            g.add_legend()
            sns.move_legend(g, "lower center", bbox_to_anchor=(0.45, 1.02), ncol=3, 
                            title="Python Interpreter Mode", frameon=False, fontsize=20, title_fontsize=24)

        # --- Saving ---
        out_path = self.base_dir.joinpath(filename)
        g.savefig(out_path, format="svg", bbox_inches="tight", transparent=True)
        svg_lines = out_path.read_text(encoding="utf-8").splitlines()
        out_path.write_text("\n".join(line.rstrip() for line in svg_lines) + "\n", encoding="utf-8")
        plt.close(g.fig)
        print(f"Exported plot: {out_path}")

    def plot_all(self):
        """Generates all benchmark plots based on the loaded data."""
        if self.df.empty:
            print("No JSON data found to plot.")
            return
            
        print("Generating Seaborn SVG plots...")
        
        # --- Async plots show every available interpreter environment. ---
        async_df = self.df[self.df["Category"].str.startswith("Async")]
        if not async_df.empty:
            plot_configs_async = [
                {"category": "AsyncLock", "filename": "async_rwlock.svg", "palette_name": "crest", "height": 9.0, "aspect": 11.0/9.0},
                {"category": "AsyncCond", "filename": "async_rwcondition.svg", "palette_name": "flare", "height": 5.5, "aspect": 11.0/5.5},
            ]
            
            for config in plot_configs_async:
                df_plot = async_df[async_df["Category"] == config["category"]].copy()
                if df_plot.empty: continue
                
                palette = self._SYNC_ENV_PALETTE
                self._create_plot(df_plot, x="Throughput", y="Name", hue="Environment", filename=config["filename"],
                                  palette=palette, height=config["height"], aspect=config["aspect"])

        # --- Sync Plots (compare across all environments) ---
        plot_configs_sync = [
            {"category": "SyncLock", "filename": "sync_rwlock.svg", "height": 20.0, "aspect": 11.0/20.0},
            {"category": "SyncCond", "filename": "sync_rwcondition.svg", "height": 12.0, "aspect": 11.0/12.0},
        ]

        for config in plot_configs_sync:
            df_plot = self.df[self.df["Category"] == config["category"]]
            if df_plot.empty: continue
            
            self._create_plot(df_plot, x="Throughput", y="Name", hue="Environment", filename=config["filename"],
                              palette=self._SYNC_ENV_PALETTE, height=config["height"], aspect=config["aspect"])


if __name__ == "__main__":
    base_dir = Path.cwd().joinpath("figures")

    # orchestrator = BenchmarkOrchestrator(base_dir)
    # orchestrator.collect_all_data()

    plotter = BenchmarkPlotter(base_dir)
    plotter.plot_all()
