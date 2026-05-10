"""Analyze turnover and simple transaction-cost pressure for PPO prediction files.

This helper reviews the newest PPO walk-forward training run that contains
summary_test_mode.csv and *_predictions_compat.csv files.

It does not retrain models. It uses existing prediction files to estimate:

- BUY / SELL / HOLD counts
- signal changes
- approximate trade frequency
- action turnover
- simple cost-adjusted portfolio estimates

The goal is to identify which PPO windows may remain attractive after basic
execution-cost pressure.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

import pandas as pd


BACKTESTS_DIR = Path("reports/backtests")
COST_BPS_LEVELS = [1, 5, 10]  # 0.01%, 0.05%, 0.10% per turnover unit


def find_latest_summary() -> Path:
    """Return the newest summary_test_mode.csv from PPO walk-forward runs."""
    summaries = sorted(
        BACKTESTS_DIR.glob("ppo_walkforward_results_*/summary_test_mode.csv")
    )

    if not summaries:
        raise FileNotFoundError(
            "No summary_test_mode.csv files found under reports/backtests. "
            "Run python -m src.train first."
        )

    return summaries[-1]


def infer_ticker_window(file_path: Path) -> tuple[str, str, str]:
    """Infer ticker, window number, and model prefix from prediction filename."""
    name = file_path.name.replace("_predictions_compat.csv", "")
    parts = name.split("_")

    if len(parts) < 3:
        return "UNKNOWN", "UNKNOWN", name

    # Expected format: ppo_XOM_window3_predictions_compat.csv
    ticker = parts[1]
    window = parts[2]
    prefix = "_".join(parts[:3])

    return ticker, window, prefix


def load_summary(summary_path: Path) -> pd.DataFrame:
    """Load summary file and add prefix key used to join prediction diagnostics."""
    summary = pd.read_csv(summary_path)

    required = {"Ticker", "Window", "PPO_Portfolio", "BuyHold", "Sharpe", "Drawdown_%", "Winner"}
    missing = required - set(summary.columns)
    if missing:
        raise ValueError(
            f"Summary file missing required columns: {sorted(missing)}. "
            f"File: {summary_path}"
        )

    summary = summary.copy()
    summary["window_number"] = (
        summary.groupby("Ticker").cumcount() + 1
    )
    summary["prefix"] = (
        "ppo_"
        + summary["Ticker"].astype(str)
        + "_window"
        + summary["window_number"].astype(str)
    )

    return summary


def count_signal_changes(signals: Iterable[str]) -> int:
    """Count how many times the signal changes from one row to the next."""
    series = pd.Series(list(signals)).astype(str)

    if series.empty:
        return 0

    return int(series.ne(series.shift()).sum() - 1)


def analyze_prediction_file(file_path: Path) -> dict[str, float | int | str]:
    """Calculate turnover-style diagnostics for one prediction file."""
    df = pd.read_csv(file_path)

    ticker, window, prefix = infer_ticker_window(file_path)

    if "Signal" not in df.columns:
        raise ValueError(f"Signal column missing from {file_path}")

    if "Action" not in df.columns:
        raise ValueError(f"Action column missing from {file_path}")

    signal_series = df["Signal"].astype(str)
    action_series = pd.to_numeric(df["Action"], errors="coerce").fillna(0.0)

    rows = len(df)
    buy_count = int((signal_series == "BUY").sum())
    sell_count = int((signal_series == "SELL").sum())
    hold_count = int((signal_series == "HOLD").sum())

    signal_changes = count_signal_changes(signal_series)

    # Approximate action turnover:
    # If action moves from -1 to +1, turnover is 2 units.
    # If action moves from 0 to +1, turnover is 1 unit.
    action_turnover = float(action_series.diff().abs().fillna(action_series.abs()).sum())

    # Normalize turnover for easier comparison across files.
    action_turnover_per_100_rows = (
        action_turnover / rows * 100 if rows else 0.0
    )

    trade_signal_count = buy_count + sell_count
    trade_signal_rate = trade_signal_count / rows if rows else 0.0
    signal_change_rate = signal_changes / rows if rows else 0.0

    avg_abs_action = float(action_series.abs().mean()) if rows else 0.0
    max_abs_action = float(action_series.abs().max()) if rows else 0.0

    return {
        "Ticker": ticker,
        "Window_Number": window.replace("window", ""),
        "Prefix": prefix,
        "Rows": rows,
        "BUY": buy_count,
        "SELL": sell_count,
        "HOLD": hold_count,
        "Trade_Signal_Count": trade_signal_count,
        "Trade_Signal_Rate": trade_signal_rate,
        "Signal_Changes": signal_changes,
        "Signal_Change_Rate": signal_change_rate,
        "Action_Turnover": action_turnover,
        "Action_Turnover_Per_100_Rows": action_turnover_per_100_rows,
        "Avg_Abs_Action": avg_abs_action,
        "Max_Abs_Action": max_abs_action,
    }


def add_cost_estimates(df: pd.DataFrame) -> pd.DataFrame:
    """Add simple cost-adjusted portfolio estimates.

    Cost model:
    cost dollars = initial_capital * action_turnover * cost_rate

    This is intentionally simple. It is not a full execution simulator.
    It is a first-pass stress test to identify whether a model is obviously
    too active to trust without deeper execution modeling.
    """
    result = df.copy()

    result["PPO_Return_%"] = (
        (result["PPO_Portfolio"] - 100_000.0) / 100_000.0 * 100.0
    )
    result["BuyHold_Return_%"] = (
        (result["BuyHold"] - 100_000.0) / 100_000.0 * 100.0
    )
    result["PPO_Edge_vs_BuyHold"] = result["PPO_Portfolio"] - result["BuyHold"]

    for bps in COST_BPS_LEVELS:
        cost_rate = bps / 10_000.0
        cost_col = f"Estimated_Cost_{bps}bps"
        adj_col = f"Cost_Adjusted_Portfolio_{bps}bps"
        edge_col = f"Cost_Adjusted_Edge_{bps}bps"
        winner_col = f"Cost_Adjusted_Winner_{bps}bps"

        result[cost_col] = 100_000.0 * result["Action_Turnover"] * cost_rate
        result[adj_col] = result["PPO_Portfolio"] - result[cost_col]
        result[edge_col] = result[adj_col] - result["BuyHold"]
        result[winner_col] = result[edge_col].apply(
            lambda x: "PPO" if x > 0 else "Buy & Hold"
        )

    return result


def classify_turnover(row: pd.Series) -> str:
    """Classify rough turnover pressure."""
    turnover_per_100 = row["Action_Turnover_Per_100_Rows"]

    if turnover_per_100 >= 60:
        return "Very high"
    if turnover_per_100 >= 35:
        return "High"
    if turnover_per_100 >= 15:
        return "Moderate"
    return "Low"


def main() -> None:
    """Run turnover and cost analysis on the newest PPO training run."""
    summary_path = find_latest_summary()
    run_dir = summary_path.parent

    print("=" * 80)
    print("PPO TURNOVER AND COST ANALYSIS")
    print("=" * 80)
    print("Using newest summary:", summary_path)
    print("Using run folder:", run_dir)

    summary = load_summary(summary_path)

    prediction_files = sorted(run_dir.glob("*_predictions_compat.csv"))
    if not prediction_files:
        raise FileNotFoundError(
            f"No *_predictions_compat.csv files found in {run_dir}."
        )

    diagnostics = pd.DataFrame(
        analyze_prediction_file(file_path) for file_path in prediction_files
    )

    merged = summary.merge(
        diagnostics,
        how="left",
        left_on="prefix",
        right_on="Prefix",
        suffixes=("", "_diag"),
    )

    merged = add_cost_estimates(merged)
    merged["Turnover_Class"] = merged.apply(classify_turnover, axis=1)

    output_path = run_dir / "turnover_cost_analysis.csv"
    merged.to_csv(output_path, index=False)

    display_cols = [
        "Ticker",
        "Window",
        "PPO_Portfolio",
        "BuyHold",
        "Sharpe",
        "Drawdown_%",
        "Winner",
        "BUY",
        "SELL",
        "HOLD",
        "Signal_Changes",
        "Action_Turnover_Per_100_Rows",
        "Turnover_Class",
        "Cost_Adjusted_Portfolio_1bps",
        "Cost_Adjusted_Winner_1bps",
        "Cost_Adjusted_Portfolio_5bps",
        "Cost_Adjusted_Winner_5bps",
        "Cost_Adjusted_Portfolio_10bps",
        "Cost_Adjusted_Winner_10bps",
    ]

    print("\nCost-adjusted summary:")
    print(
        merged[display_cols]
        .sort_values(["Ticker", "Sharpe"], ascending=[True, False])
        .to_string(index=False)
    )

    print("\nBest by ticker after 5bps cost estimate:")
    best_5bps = (
        merged.sort_values(
            ["Ticker", "Cost_Adjusted_Edge_5bps"],
            ascending=[True, False],
        )
        .groupby("Ticker")
        .head(1)
    )
    print(
        best_5bps[
            [
                "Ticker",
                "Window",
                "Sharpe",
                "PPO_Portfolio",
                "BuyHold",
                "Action_Turnover_Per_100_Rows",
                "Turnover_Class",
                "Cost_Adjusted_Portfolio_5bps",
                "Cost_Adjusted_Edge_5bps",
                "Cost_Adjusted_Winner_5bps",
            ]
        ].to_string(index=False)
    )

    print("\nSaved turnover analysis to:", output_path)

    print("\nInterpretation guide:")
    print("- 1bps is a light transaction-cost stress test.")
    print("- 5bps is a moderate stress test.")
    print("- 10bps is a harsher stress test.")
    print("- Very high turnover models need deeper slippage/execution review.")


if __name__ == "__main__":
    main()