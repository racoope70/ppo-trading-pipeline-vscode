"""Select quality-filtered PPO tickers from execution-realism analysis.

Purpose:
    - Read execution_realism_analysis.csv from a requested run directory, or
      from the newest run if --run-dir is omitted.
    - Select the best scenario row per ticker by Execution_Edge_vs_BuyHold.
    - Apply a quality filter for PPO-favored candidates.
    - Save selected and excluded ticker diagnostics for downstream workflow use.

Default quality filter:
    Execution_Winner == "PPO"
    Execution_Edge_vs_BuyHold > 0

Optional quality filters:
    --min-sharpe
    --max-drawdown
    --max-turnover

Example:
    python -m src.select_quality_tickers \
      --run-dir reports/backtests/ppo_walkforward_results_20260512_8ticker_combined \
      --scenario moderate \
      --output-dir reports/validation_summary
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd


BACKTESTS_DIR = Path("reports/backtests")
DEFAULT_OUTPUT_DIR = Path("reports/validation_summary")


def find_latest_training_run() -> Path:
    """Return the newest PPO walk-forward run directory."""
    summaries = sorted(
        BACKTESTS_DIR.glob("ppo_walkforward_results_*/summary_test_mode.csv")
    )

    if not summaries:
        raise FileNotFoundError(
            "No summary_test_mode.csv files found under reports/backtests."
        )

    return summaries[-1].parent


def resolve_training_run(run_dir: Path | None) -> Path:
    """Return requested PPO run directory or newest available run directory."""
    if run_dir is None:
        return find_latest_training_run()

    run_dir = run_dir.expanduser()

    if run_dir.is_file():
        if run_dir.name != "summary_test_mode.csv":
            raise ValueError(
                "--run-dir was given as a file, but it must be summary_test_mode.csv. "
                f"Received: {run_dir}"
            )
        return run_dir.parent

    summary_path = run_dir / "summary_test_mode.csv"

    if not summary_path.exists():
        raise FileNotFoundError(
            f"summary_test_mode.csv not found in run directory: {run_dir}"
        )

    return run_dir


def window_to_prefix(symbol: str, window: str) -> str:
    """Map walk-forward window label to artifact prefix."""
    mapping = {
        "0-3500": 1,
        "500-4000": 2,
        "1000-4500": 3,
    }

    window = str(window)

    if window not in mapping:
        raise ValueError(
            f"Unsupported window label for prefix mapping: {window}. "
            "Update window_to_prefix()."
        )

    return f"ppo_{symbol}_window{mapping[window]}"


def load_execution_realism(run_dir: Path) -> pd.DataFrame:
    """Load execution-realism analysis for a run directory."""
    path = run_dir / "execution_realism_analysis.csv"

    if not path.exists():
        raise FileNotFoundError(
            f"Missing execution realism file: {path}\n"
            "Run first: python -m src.analyze_execution_realism --run-dir <run_dir>"
        )

    df = pd.read_csv(path)

    required_columns = {
        "Ticker",
        "Window",
        "Scenario",
        "Execution_Edge_vs_BuyHold",
        "Execution_Winner",
        "Final_Equity",
        "Sharpe_Est",
        "Max_Drawdown_%",
        "Total_Turnover",
        "Trade_Events",
        "Total_Cost_$",
    }

    missing_columns = required_columns - set(df.columns)

    if missing_columns:
        raise ValueError(
            f"execution_realism_analysis.csv missing columns: {sorted(missing_columns)}"
        )

    return df


def select_best_by_ticker(execution: pd.DataFrame, scenario: str) -> pd.DataFrame:
    """Select the best row per ticker for a scenario by execution edge."""
    scenario_df = execution[
        execution["Scenario"].astype(str).str.lower().eq(scenario.lower())
    ].copy()

    if scenario_df.empty:
        raise ValueError(f"No rows found for scenario: {scenario}")

    numeric_columns = [
        "Execution_Edge_vs_BuyHold",
        "Final_Equity",
        "Sharpe_Est",
        "Max_Drawdown_%",
        "Total_Turnover",
        "Trade_Events",
        "Total_Cost_$",
    ]

    for column in numeric_columns:
        scenario_df[column] = pd.to_numeric(scenario_df[column], errors="coerce")

    scenario_df = scenario_df.dropna(subset=["Execution_Edge_vs_BuyHold"])
    scenario_df["Ticker"] = scenario_df["Ticker"].astype(str).str.upper()

    best = (
        scenario_df.sort_values(
            ["Ticker", "Execution_Edge_vs_BuyHold"],
            ascending=[True, False],
        )
        .groupby("Ticker", as_index=False)
        .head(1)
        .copy()
    )

    best["Prefix"] = best.apply(
        lambda row: window_to_prefix(
            symbol=str(row["Ticker"]).upper(),
            window=str(row["Window"]),
        ),
        axis=1,
    )

    return best.sort_values("Ticker").reset_index(drop=True)


def apply_quality_filter(
    best: pd.DataFrame,
    min_edge: float,
    require_ppo_winner: bool,
    min_sharpe: float | None,
    max_drawdown: float | None,
    max_turnover: float | None,
) -> pd.DataFrame:
    """Apply quality filter and attach pass/fail reason."""
    filtered = best.copy()

    pass_mask = filtered["Execution_Edge_vs_BuyHold"] > min_edge
    reasons = []

    for _, row in filtered.iterrows():
        row_reasons = []

        if float(row["Execution_Edge_vs_BuyHold"]) <= min_edge:
            row_reasons.append(f"edge <= {min_edge:g}")

        if require_ppo_winner and str(row["Execution_Winner"]) != "PPO":
            row_reasons.append("winner != PPO")

        if min_sharpe is not None and float(row["Sharpe_Est"]) <= min_sharpe:
            row_reasons.append(f"sharpe <= {min_sharpe:g}")

        if max_drawdown is not None and float(row["Max_Drawdown_%"]) > max_drawdown:
            row_reasons.append(f"drawdown > {max_drawdown:g}")

        if max_turnover is not None and float(row["Total_Turnover"]) > max_turnover:
            row_reasons.append(f"turnover > {max_turnover:g}")

        reasons.append("PASS" if not row_reasons else "; ".join(row_reasons))

    if require_ppo_winner:
        pass_mask = pass_mask & filtered["Execution_Winner"].astype(str).eq("PPO")

    if min_sharpe is not None:
        pass_mask = pass_mask & (filtered["Sharpe_Est"] > min_sharpe)

    if max_drawdown is not None:
        pass_mask = pass_mask & (filtered["Max_Drawdown_%"] <= max_drawdown)

    if max_turnover is not None:
        pass_mask = pass_mask & (filtered["Total_Turnover"] <= max_turnover)

    filtered["Quality_Pass"] = pass_mask
    filtered["Quality_Reason"] = reasons

    return filtered


def save_outputs(
    filtered: pd.DataFrame,
    run_dir: Path,
    scenario: str,
    output_dir: Path,
) -> tuple[Path, Path]:
    """Save selected ticker diagnostics to CSV and JSON."""
    output_dir.mkdir(parents=True, exist_ok=True)

    csv_path = output_dir / "quality_filtered_tickers.csv"
    json_path = output_dir / "quality_filtered_tickers.json"

    filtered.to_csv(csv_path, index=False)

    selected = filtered[filtered["Quality_Pass"]].copy()
    excluded = filtered[~filtered["Quality_Pass"]].copy()

    payload = {
        "source_run_dir": str(run_dir),
        "scenario": scenario,
        "selected_symbols": selected["Ticker"].astype(str).tolist(),
        "selected_models": dict(zip(selected["Ticker"], selected["Prefix"])),
        "excluded_symbols": excluded["Ticker"].astype(str).tolist(),
        "selected_count": int(len(selected)),
        "excluded_count": int(len(excluded)),
        "rows": filtered.to_dict(orient="records"),
    }

    with json_path.open("w") as file:
        json.dump(payload, file, indent=2)

    return csv_path, json_path


def print_summary(filtered: pd.DataFrame, run_dir: Path, scenario: str) -> None:
    """Print selected and excluded ticker diagnostics."""
    selected = filtered[filtered["Quality_Pass"]].copy()
    excluded = filtered[~filtered["Quality_Pass"]].copy()

    display_cols = [
        "Ticker",
        "Prefix",
        "Window",
        "Scenario",
        "Execution_Winner",
        "Execution_Edge_vs_BuyHold",
        "Final_Equity",
        "Sharpe_Est",
        "Max_Drawdown_%",
        "Total_Turnover",
        "Trade_Events",
        "Quality_Reason",
    ]

    print("=" * 80)
    print("QUALITY-FILTERED PPO TICKER SELECTION")
    print("=" * 80)
    print("Run directory:", run_dir)
    print("Scenario:", scenario)

    print("\nSelected symbols:")
    print(selected["Ticker"].astype(str).tolist())

    print("\nSelected models:")
    if selected.empty:
        print("None")
    else:
        print(pd.Series(dict(zip(selected["Ticker"], selected["Prefix"]))).to_string())

    print("\nExcluded symbols:")
    print(excluded["Ticker"].astype(str).tolist())

    print("\nFull selection table:")
    print(filtered[display_cols].to_string(index=False))


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Select quality-filtered tickers from execution-realism analysis."
    )

    parser.add_argument(
        "--run-dir",
        type=Path,
        default=None,
        help=(
            "Optional PPO run directory containing summary_test_mode.csv and "
            "execution_realism_analysis.csv. If omitted, newest run is used."
        ),
    )

    parser.add_argument(
        "--scenario",
        type=str,
        default="moderate",
        help="Execution-realism scenario to evaluate. Default: moderate.",
    )

    parser.add_argument(
        "--min-edge",
        type=float,
        default=0.0,
        help="Minimum Execution_Edge_vs_BuyHold required. Default: 0.",
    )

    parser.add_argument(
        "--allow-buyhold-winner",
        action="store_true",
        help="Do not require Execution_Winner == PPO.",
    )

    parser.add_argument(
        "--min-sharpe",
        type=float,
        default=None,
        help="Optional minimum Sharpe_Est threshold.",
    )

    parser.add_argument(
        "--max-drawdown",
        type=float,
        default=None,
        help="Optional maximum Max_Drawdown_% threshold.",
    )

    parser.add_argument(
        "--max-turnover",
        type=float,
        default=None,
        help="Optional maximum Total_Turnover threshold.",
    )

    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Output directory. Default: {DEFAULT_OUTPUT_DIR}",
    )

    return parser.parse_args()


def main() -> None:
    """Run quality-filtered ticker selection."""
    args = parse_args()

    run_dir = resolve_training_run(args.run_dir)
    execution = load_execution_realism(run_dir)

    best = select_best_by_ticker(
        execution=execution,
        scenario=args.scenario,
    )

    filtered = apply_quality_filter(
        best=best,
        min_edge=args.min_edge,
        require_ppo_winner=not args.allow_buyhold_winner,
        min_sharpe=args.min_sharpe,
        max_drawdown=args.max_drawdown,
        max_turnover=args.max_turnover,
    )

    print_summary(filtered=filtered, run_dir=run_dir, scenario=args.scenario)

    csv_path, json_path = save_outputs(
        filtered=filtered,
        run_dir=run_dir,
        scenario=args.scenario,
        output_dir=args.output_dir,
    )

    print("\nSaved outputs:")
    print("CSV:", csv_path)
    print("JSON:", json_path)


if __name__ == "__main__":
    main()