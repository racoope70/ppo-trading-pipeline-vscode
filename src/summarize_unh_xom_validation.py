"""Create a compact UNH/XOM validation comparison summary.

Purpose:
    Compare the major validation checkpoints for the selected UNH/XOM PPO
    candidates:

    1. Original PPO walkforward result
    2. Execution-realism analysis under moderate costs
    3. QuantConnect one-day dynamic signal test
    4. Local mark-to-market dynamic signal simulation

Output:
    reports/validation_summary/unh_xom_validation_comparison.csv
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd


BACKTESTS_DIR = Path("reports/backtests")
DYNAMIC_EXECUTION_DIR = Path("reports/dynamic_signal_execution")
OUTPUT_DIR = Path("reports/validation_summary")

SELECTED_MODELS = {
    "UNH": {
        "prefix": "ppo_UNH_window1",
        "window": "0-3500",
    },
    "XOM": {
        "prefix": "ppo_XOM_window2",
        "window": "500-4000",
    },
}

QC_ONE_DAY_RESULT = {
    "Stage": "QuantConnect one-day dynamic signal test",
    "Scope": "UNH/XOM combined",
    "Rows_or_DataPoints": 29,
    "Final_Equity": 100279.97,
    "Net_Return_%": 0.27997,
    "Net_PnL": 279.97,
    "Sharpe_Est": None,
    "Max_Drawdown_%": None,
    "Total_Turnover": 0.9007,
    "Trade_Events": 5,
    "Transaction_Costs": 4.00,
    "Notes": (
        "LEAN loaded 250-marketbar signal payload and created orders, "
        "but QuantConnect only supplied Feb 10 hourly data for UNH/XOM."
    ),
}


def find_latest_training_run() -> Path:
    summaries = sorted(
        BACKTESTS_DIR.glob("ppo_walkforward_results_*/summary_test_mode.csv")
    )

    if not summaries:
        raise FileNotFoundError(
            "No summary_test_mode.csv files found under reports/backtests."
        )

    return summaries[-1].parent


def load_summary(run_dir: Path) -> pd.DataFrame:
    path = run_dir / "summary_test_mode.csv"

    if not path.exists():
        raise FileNotFoundError(f"Missing summary file: {path}")

    return pd.read_csv(path)


def load_execution_realism(run_dir: Path) -> pd.DataFrame:
    path = run_dir / "execution_realism_analysis.csv"

    if not path.exists():
        raise FileNotFoundError(
            f"Missing execution realism file. Run first: python -m src.analyze_execution_realism\nMissing: {path}"
        )

    return pd.read_csv(path)


def load_local_mtm_summary() -> pd.DataFrame:
    path = (
        DYNAMIC_EXECUTION_DIR
        / "unh_xom_dynamic_signals_250marketbars_mtm_execution_summary.csv"
    )

    if not path.exists():
        raise FileNotFoundError(
            f"Missing local MTM summary. Run first: python -m src.simulate_dynamic_signal_execution\nMissing: {path}"
        )

    return pd.read_csv(path)


def selected_walkforward_rows(summary: pd.DataFrame) -> list[dict]:
    rows = []

    for symbol, config in SELECTED_MODELS.items():
        match = summary[
            (summary["Ticker"].astype(str).str.upper() == symbol)
            & (summary["Window"].astype(str) == config["window"])
        ]

        if match.empty:
            raise ValueError(
                f"Could not find selected walkforward row for {symbol} window {config['window']}"
            )

        row = match.iloc[0]

        rows.append(
            {
                "Stage": "Original PPO walkforward",
                "Scope": symbol,
                "Selected_Prefix": config["prefix"],
                "Window": config["window"],
                "Rows_or_DataPoints": None,
                "Final_Equity": float(row["PPO_Portfolio"]),
                "BuyHold": float(row["BuyHold"]),
                "Net_Return_%": (float(row["PPO_Portfolio"]) / 100000.0 - 1.0) * 100.0,
                "Net_PnL": float(row["PPO_Portfolio"]) - 100000.0,
                "Sharpe_Est": float(row["Sharpe"]),
                "Max_Drawdown_%": float(row["Drawdown_%"]),
                "Total_Turnover": None,
                "Trade_Events": None,
                "Transaction_Costs": None,
                "Winner": str(row["Winner"]),
                "Notes": "Original PPO walkforward summary before separate execution realism adjustment.",
            }
        )

    return rows


def selected_execution_realism_rows(execution: pd.DataFrame) -> list[dict]:
    rows = []

    moderate = execution[
        execution["Scenario"].astype(str).str.lower().eq("moderate")
    ].copy()

    for symbol, config in SELECTED_MODELS.items():
        match = moderate[
            (moderate["Ticker"].astype(str).str.upper() == symbol)
            & (moderate["Window"].astype(str) == config["window"])
        ]

        if match.empty:
            raise ValueError(
                f"Could not find selected execution-realism row for {symbol} window {config['window']}"
            )

        row = match.iloc[0]

        rows.append(
            {
                "Stage": "Execution realism analysis",
                "Scope": symbol,
                "Selected_Prefix": config["prefix"],
                "Window": config["window"],
                "Rows_or_DataPoints": None,
                "Final_Equity": float(row["Final_Equity"]),
                "BuyHold": float(row["BuyHold"]),
                "Net_Return_%": float(row["Total_Return_%"]),
                "Net_PnL": float(row["Final_Equity"]) - 100000.0,
                "Execution_Edge_vs_BuyHold": float(row["Execution_Edge_vs_BuyHold"]),
                "Sharpe_Est": float(row["Sharpe_Est"]),
                "Max_Drawdown_%": float(row["Max_Drawdown_%"]),
                "Total_Turnover": float(row["Total_Turnover"]),
                "Trade_Events": int(row["Trade_Events"]),
                "Transaction_Costs": float(row["Total_Cost_$"]),
                "Winner": str(row["Execution_Winner"]),
                "Notes": "Moderate execution scenario with 5 bps cost assumption.",
            }
        )

    return rows


def local_mtm_row(local_mtm: pd.DataFrame) -> dict:
    row = local_mtm.iloc[0]

    return {
        "Stage": "Local mark-to-market dynamic signal simulation",
        "Scope": "UNH/XOM combined",
        "Selected_Prefix": "ppo_UNH_window1 + ppo_XOM_window2",
        "Window": "250 market bars",
        "Rows_or_DataPoints": int(row["Rows"]),
        "Final_Equity": float(row["Final_Equity"]),
        "BuyHold": None,
        "Net_Return_%": float(row["Net_Return_%"]),
        "Net_PnL": float(row["Net_PnL"]),
        "Gross_PnL_Before_Costs": float(row["Gross_PnL_Before_Costs"]),
        "Sharpe_Est": float(row["Sharpe_Est"]),
        "Max_Drawdown_%": float(row["Max_Drawdown_%"]),
        "Total_Turnover": float(row["Total_Turnover"]),
        "Trade_Events": int(row["Trade_Events"]),
        "Transaction_Costs": float(row["Total_Transaction_Costs"]),
        "Winner": "PPO",
        "Notes": (
            "Local longer-window simulation using bar_index alignment, "
            "saved Close returns, and 5 bps transaction costs."
        ),
    }


def quantconnect_one_day_row() -> dict:
    row = QC_ONE_DAY_RESULT.copy()
    row["Selected_Prefix"] = "ppo_UNH_window1 + ppo_XOM_window2"
    row["Window"] = "Feb 10 one-day LEAN data"
    row["BuyHold"] = None
    row["Gross_PnL_Before_Costs"] = None
    row["Execution_Edge_vs_BuyHold"] = None
    row["Winner"] = None
    return row


def build_comparison() -> pd.DataFrame:
    run_dir = find_latest_training_run()

    summary = load_summary(run_dir)
    execution = load_execution_realism(run_dir)
    local_mtm = load_local_mtm_summary()

    rows = []
    rows.extend(selected_walkforward_rows(summary))
    rows.extend(selected_execution_realism_rows(execution))
    rows.append(quantconnect_one_day_row())
    rows.append(local_mtm_row(local_mtm))

    comparison = pd.DataFrame(rows)

    preferred_columns = [
        "Stage",
        "Scope",
        "Selected_Prefix",
        "Window",
        "Rows_or_DataPoints",
        "Final_Equity",
        "BuyHold",
        "Net_PnL",
        "Net_Return_%",
        "Gross_PnL_Before_Costs",
        "Execution_Edge_vs_BuyHold",
        "Sharpe_Est",
        "Max_Drawdown_%",
        "Total_Turnover",
        "Trade_Events",
        "Transaction_Costs",
        "Winner",
        "Notes",
    ]

    for col in preferred_columns:
        if col not in comparison.columns:
            comparison[col] = None

    return comparison[preferred_columns]


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    comparison = build_comparison()

    output_path = OUTPUT_DIR / "unh_xom_validation_comparison.csv"
    comparison.to_csv(output_path, index=False)

    print("=" * 80)
    print("UNH/XOM VALIDATION COMPARISON")
    print("=" * 80)
    print(comparison.to_string(index=False))
    print("\nSaved comparison CSV to:", output_path)


if __name__ == "__main__":
    main()