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

environments = [
    {
        "name": "3.14.3_standard",
        "executable": "/bin/python3.14",
        "env_vars": {}
    },
    {
        "name": "3.14.3t_gil_on",
        "executable": "~/.pyenv/versions/3.14.3t/bin/python",
        "env_vars": {"PYTHON_GIL": "1"}
    },
    {
        "name": "3.14.3t_gil_off",
        "executable": "~/.pyenv/versions/3.14.3t/bin/python",
        "env_vars": {"PYTHON_GIL": "0"}
    }
]

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
    def __init__(self, base_dir: Path):
        self.base_dir = base_dir
        self.df = self._load_data()

    def _load_data(self) -> pd.DataFrame:
        rows = []
        for json_file in self.base_dir.glob("*.json"):
            env_name = json_file.stem
            
            display_env = env_name
            if "standard" in env_name.lower():
                display_env = "Standard\nPython"
            elif "gil_off" in env_name.lower():
                display_env = "Free-Threading\n(GIL Off)"
            elif "gil_on" in env_name.lower():
                display_env = "Free-Threading\n(GIL On)"
                
            with open(json_file, "r", encoding="utf-8") as f:
                history = json.load(f)
                
            for entry in history:
                scenario = entry["scenario_name"]
                target_type = entry["target_type"]
                for res in entry["results"]:
                    name = res["name"]
                    
                    is_async = "Async" in name or "asyncio" in name
                    if target_type == "Lock Implementation":
                        category = "AsyncLock" if is_async else "SyncLock"
                    else:
                        category = "AsyncCond" if is_async else "SyncCond"
                        
                    name = name.replace("ReentrantWriter", "\n(Reentrant)").replace(" (", "\n(")
                        
                    rows.append({
                        "Environment": display_env,
                        "Category": category,
                        "Scenario": scenario,
                        "Name": name,
                        "Throughput": res["throughput"],
                        "Elapsed": res["elapsed"],
                        "Speedup": res["speedup"]
                    })
                    
        df = pd.DataFrame(rows)
        for category in ["SyncLock", "SyncCond"]:
            for scenario in df["Scenario"].unique():
                mask = (df["Category"] == category) & (df["Scenario"] == scenario)
                if not mask.any(): continue
                
                baseline_mask = mask & (df["Environment"] == "Standard\nPython") & df["Name"].str.contains("Baseline")
                if not baseline_mask.any():
                    baseline_mask = mask & df["Name"].str.contains("Baseline")
                    
                if baseline_mask.any():
                    global_baseline_time = df[baseline_mask]["Elapsed"].values[0]
                    df.loc[mask, "Speedup"] = global_baseline_time / df.loc[mask, "Elapsed"]

        return df

    def _create_catplot(self, df: pd.DataFrame, x: str, y: str, hue: str, filename: str, palette: list, height: float=4.5, aspect: float=2.5):
        df = df.copy()
        
        sns.set_theme(
            style="darkgrid", 
            palette=palette,
            rc={
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
                "font.family": "sans-serif",
                "hatch.linewidth": 2.0
            }
        )
        
        if hue == "Environment":
            order = df[y].unique()
            expected_envs = ["Standard\nPython", "Free-Threading\n(GIL Off)", "Free-Threading\n(GIL On)"]
            hue_order = [e for e in expected_envs if e in df[hue].unique()] + [e for e in df[hue].unique() if e not in expected_envs]
            df[hue] = pd.Categorical(df[hue], categories=hue_order, ordered=True)
            df = df.sort_values(by=["Scenario", y, hue])
        else:
            df = df.sort_values(by=["Scenario", x], ascending=[True, False])
            order = df[y].unique()
            hue_order = order

        scenario_order = [
            "Read-Heavy (2 Writer, 100 Readers)",
            "Balanced (50 Writers, 50 Readers)",
            "Write-Heavy (100 Writers, 2 Readers)"
        ]
        col_order = [s for s in scenario_order if s in df["Scenario"].unique()]
        
        plot_kwargs = {"linewidth": 0}
        if hue == "Environment":
            plot_kwargs["width"] = 0.82
            try:
                if int(sns.__version__.split(".")[1]) >= 13:
                    plot_kwargs["gap"] = 0.20
            except Exception:
                pass
        else:
            plot_kwargs["width"] = 0.7

        g = sns.catplot(
            data=df, 
            x=x, y=y, hue=hue, col="Scenario", 
            kind="bar", 
            sharex=False, 
            col_wrap=1,
            height=height, aspect=aspect,
            palette=palette,
            order=order,
            hue_order=hue_order,
            legend=True if hue == "Environment" else False,
            margin_titles=True,
            col_order=col_order,
            **plot_kwargs
        )
        
        g.set_axis_labels("Throughput (Ops/sec) ➔", "", fontsize=18, fontweight="bold")
        g.set_titles("{col_name}", fontweight="bold", size=24)
        
    
        g.fig.subplots_adjust(hspace=2.0 / height)
        
        for scenario, ax in g.axes_dict.items():
            sub_df = df[df["Scenario"] == scenario]
            max_width = 0
            
            for container in ax.containers:
                for patch in container:
                    val = patch.get_width()
                    if pd.isna(val) or val <= 0: continue
                    max_width = max(max_width, val)
                    
                    y_center = patch.get_y() + patch.get_height() / 2.
                    y_idx = int(round(y_center))
                    if not (0 <= y_idx < len(order)): continue
                    y_val = order[y_idx]
                    
                    is_baseline = "Baseline" in str(y_val)
                    if is_baseline:
                        orig_color = patch.get_facecolor()
                        patch.set_facecolor('none')
                        patch.set_edgecolor(orig_color)
                        patch.set_hatch('////')
                        patch.set_linewidth(1.5)
                        patch.set_alpha(1.0)
                    
                    row_candidates = sub_df[sub_df[y] == y_val]
                    if not row_candidates.empty:
                        diffs = (row_candidates["Throughput"] - val).abs()
                        best_match_idx = diffs.idxmin()
                        
                        if diffs[best_match_idx] < (val * 0.05) + 1e-5:
                            data_row = row_candidates.loc[best_match_idx]
                            text = f"  {data_row['Speedup']:.2f}x  |  {data_row['Elapsed']:.3f}s\n  {int(data_row['Throughput']):,} Ops/sec"
                            ax.text(val, y_center, text, 
                                    va='center', ha='left', fontsize=15, color='#9ca3af', fontweight='bold')
            
            if max_width > 0:
                ax.set_xlim(0, max_width * 1.55)
            
            for label in ax.get_yticklabels():
                label.set_fontweight("600")
                label.set_fontsize(17)
                
            for label in ax.get_xticklabels():
                label.set_fontweight("600")
                label.set_fontsize(15)

        if hue == "Environment":
            sns.move_legend(g, "lower center", bbox_to_anchor=(0.45, 1.02), ncol=3, title="Python Interpreter Mode", frameon=False, fontsize=20, title_fontsize=24)

        out_path = self.base_dir.joinpath(filename)
        g.savefig(out_path, format="svg", bbox_inches="tight", transparent=True)
        plt.close(g.fig)
        print(f"Exported plot: {out_path}")

    def plot_all(self):
        if self.df.empty:
            print("No JSON data found to plot.")
            return
            
        print("Generating Seaborn SVG plots...")
        
        async_df = self.df[self.df["Category"].str.startswith("Async")]
        if not async_df.empty:
            best_env = async_df.groupby("Environment")["Throughput"].mean().idxmax()
            
            df_async_lock = async_df[(async_df["Environment"] == best_env) & (async_df["Category"] == "AsyncLock")]
            async_lock_pal = sns.color_palette("crest", n_colors=len(df_async_lock["Name"].unique()))
            self._create_catplot(df_async_lock, x="Throughput", y="Name", hue="Name", filename="async_rwlock.svg", palette=async_lock_pal, height=7.0, aspect=11.0/7)
            
            df_async_cond = async_df[(async_df["Environment"] == best_env) & (async_df["Category"] == "AsyncCond")]
            async_cond_pal = sns.color_palette("flare", n_colors=len(df_async_cond["Name"].unique()))
            self._create_catplot(df_async_cond, x="Throughput", y="Name", hue="Name", filename="async_rwcondition.svg", palette=async_cond_pal, height=4.5, aspect=11.0/4.5)

        sync_env_palette = ["#3b82f6", "#10b981", "#ef4444"]
        
        df_sync_lock = self.df[self.df["Category"] == "SyncLock"]
        if not df_sync_lock.empty:
            self._create_catplot(df_sync_lock, x="Throughput", y="Name", hue="Environment", filename="sync_rwlock.svg", palette=sync_env_palette, height=16.0, aspect=11.0/16.0)

        df_sync_cond = self.df[self.df["Category"] == "SyncCond"]
        if not df_sync_cond.empty:
            self._create_catplot(df_sync_cond, x="Throughput", y="Name", hue="Environment", filename="sync_rwcondition.svg", palette=sync_env_palette, height=9.6, aspect=11.0/9.6)


if __name__ == "__main__":
    base_dir = Path.cwd().joinpath("figures")

    orchestrator = BenchmarkOrchestrator(base_dir)
    orchestrator.collect_all_data()

    plotter = BenchmarkPlotter(base_dir)
    plotter.plot_all()
