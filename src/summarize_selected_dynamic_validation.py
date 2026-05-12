"""Create a generalized selected-ticker validation comparison summary.

Purpose:
    Compare the major validation checkpoints for selected PPO candidates:

    1. Original PPO walkforward result
    2. Execution-realism analysis under moderate costs
    3. QuantConnect one-day UNH/XOM dynamic signal test
    4. UNH/XOM local mark-to-market dynamic signal simulation
    5. Four-ticker selected local mark-to-market dynamic signal simulation

Output:
    reports/validation_summary/selected_dynamic_validation_comparison.csv

Notes:
    This generalizes the earlier UNH/XOM-only comparison summary.
    It reads the selected model prefixes from the selected dynamic payload:
        quantconnect/test_payloads/selected_dynamic_signals_4ticker_250marketbars.json
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


BACKTESTS_DIR = Path("reports/backtests")
DYNAMIC_EXECUTION_DIR = Path("reports/dynamic_signal_execution")
OUTPUT_DIR = Path("reports/validation_summary")

SELECTED_PAYLOAD_PATH = Path(
    "quantconnect/test_payloads/selected_dynamic_signals_4ticker_250marketbars.json"
)

UNH_XOM_MTM_SUMMARY_PATH = (
    DYNAMIC_EXECUTION_DIR
    / "unh_xom_dynamic_signals_250marketbars_mtm_execution_summary.csv"
)

SELECTED_4TICKER_MTM_SUMMARY_PATH = (
    DYNAMIC_EXECUTION_DIR
    / "selected_dynamic_signals_4ticker_250marketbars_mtm_execution_summary.csv"
)

QC_ONE_DAY_RESULT = {
    "Stage": "QuantConnect one-day dynamic signal test",
    "Scope": "UNH/XOM combined",
    "Selected_Prefix": "ppo_UNH_window1 + ppo_XOM_window2",
    "Window": "Feb 10 one-day LEAN data",
    "Rows_or_DataPoints": 29,
    "Final_Equity": 100279.97,
    "BuyHold": None,
    "Net_PnL": 279.97,
    "Net_Return_%": 0.27997,
    "Gross_PnL_Before_Costs": None,
    "Execution_Edge_vs_BuyHold": None,
    "Sharpe_Est": None,
    "Max_Drawdown_%": None,
    "Total_Turnover": 0.9007,
    "Trade_Events": 5,
    "Transaction_Costs": 4.00,
    "Winner": None,
    "Notes": (
        "LEAN loaded the dynamic signal payload and created orders, "
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


def load_csv(path: Path, description: str) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Missing {description}: {path}")

    return pd.read_csv(path)


def load_selected_payload(path: Path = SELECTED_PAYLOAD_PATH) -> dict:
    if not path.exists():
        raise FileNotFoundError(
            f"Missing selected dynamic payload: {path}\n"
            "Run first: python -m src.export_selected_dynamic_lean_signals"
        )

    with path.open("r") as file:
        payload = json.load(file)

    if "selected_models" not in payload:
        raise ValueError("Selected payload missing selected_models.")

    if "selection_metadata" not in payload:
        raise ValueError("Selected payload missing selection_metadata.")

    return payload


def selected_payload_models(payload: dict) -> dict[str, dict]:
    selected_models = payload.get("selected_models", {})
    metadata = payload.get("selection_metadata", {})

    output = {}

    for symbol, prefix in selected_models.items():
        symbol = str(symbol).upper()
        meta = metadata.get(symbol, {})

        output[symbol] = {
            "symbol": symbol,
            "prefix": str(prefix),
            "window": str(meta.get("window", "")),
            "scenario": str(meta.get("scenario", "")),
            "execution_edge_vs_buyhold": meta.get("execution_edge_vs_buyhold"),
            "execution_winner": meta.get("execution_winner"),
            "final_equity": meta.get("final_equity"),
            "sharpe_est": meta.get("sharpe_est"),
            "max_drawdown_pct": meta.get("max_drawdown_pct"),
        }

    return output


def original_walkforward_rows(
    summary: pd.DataFrame,
    selected_models: dict[str, dict],
) -> list[dict]:
    rows = []

    for symbol, config in selected_models.items():
        window = config["window"]

        match = summary[
            (summary["Ticker"].astype(str).str.upper() == symbol)
            & (summary["Window"].astype(str) == window)
        ]

        if match.empty:
            raise ValueError(
                f"Could not find original walkforward row for {symbol} window {window}"
            )

        row = match.iloc[0]
        final_equity = float(row["PPO_Portfolio"])

        rows.append(
            {
                "Stage": "Original PPO walkforward",
                "Scope": symbol,
                "Selected_Prefix": config["prefix"],
                "Window": window,
                "Rows_or_DataPoints": None,
                "Final_Equity": final_equity,
                "BuyHold": float(row["BuyHold"]),
                "Net_PnL": final_equity - 100000.0,
                "Net_Return_%": (final_equity / 100000.0 - 1.0) * 100.0,
                "Gross_PnL_Before_Costs": None,
                "Execution_Edge_vs_BuyHold": None,
                "Sharpe_Est": float(row["Sharpe"]),
                "Max_Drawdown_%": float(row["Drawdown_%"]),
                "Total_Turnover": None,
                "Trade_Events": None,
                "Transaction_Costs": None,
                "Winner": str(row["Winner"]),
                "Notes": (
                    "Original PPO walkforward result before separate "
                    "execution-realism adjustment."
                ),
            }
        )

    return rows


def execution_realism_rows(
    execution: pd.DataFrame,
    selected_models: dict[str, dict],
    scenario: str = "moderate",
) -> list[dict]:
    rows = []

    scenario_df = execution[
        execution["Scenario"].astype(str).str.lower().eq(scenario.lower())
    ].copy()

    if scenario_df.empty:
        raise ValueError(f"No execution-realism rows found for scenario: {scenario}")

    for symbol, config in selected_models.items():
        window = config["window"]

        match = scenario_df[
            (scenario_df["Ticker"].astype(str).str.upper() == symbol)
            & (scenario_df["Window"].astype(str) == window)
        ]

        if match.empty:
            raise ValueError(
                f"Could not find execution-realism row for {symbol} window {window}"
            )

        row = match.iloc[0]
        final_equity = float(row["Final_Equity"])

        rows.append(
            {
                "Stage": "Execution realism analysis",
                "Scope": symbol,
                "Selected_Prefix": config["prefix"],
                "Window": window,
                "Rows_or_DataPoints": None,
                "Final_Equity": final_equity,
                "BuyHold": float(row["BuyHold"]),
                "Net_PnL": final_equity - 100000.0,
                "Net_Return_%": float(row["Total_Return_%"]),
                "Gross_PnL_Before_Costs": None,
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


def mtm_summary_row(
    path: Path,
    stage: str,
    scope: str,
    selected_prefix: str,
    window: str,
    notes: str,
) -> dict:
    df = load_csv(path, description=stage)

    if df.empty:
        raise ValueError(f"{stage} summary is empty: {path}")

    row = df.iloc[0]

    return {
        "Stage": stage,
        "Scope": scope,
        "Selected_Prefix": selected_prefix,
        "Window": window,
        "Rows_or_DataPoints": int(row["Rows"]),
        "Final_Equity": float(row["Final_Equity"]),
        "BuyHold": None,
        "Net_PnL": float(row["Net_PnL"]),
        "Net_Return_%": float(row["Net_Return_%"]),
        "Gross_PnL_Before_Costs": float(row["Gross_PnL_Before_Costs"]),
        "Execution_Edge_vs_BuyHold": None,
        "Sharpe_Est": float(row["Sharpe_Est"]),
        "Max_Drawdown_%": float(row["Max_Drawdown_%"]),
        "Total_Turnover": float(row["Total_Turnover"]),
        "Trade_Events": int(row["Trade_Events"]),
        "Transaction_Costs": float(row["Total_Transaction_Costs"]),
        "Winner": "PPO",
        "Notes": notes,
    }


def quantconnect_one_day_row() -> dict:
    return QC_ONE_DAY_RESULT.copy()


def preferred_columns() -> list[str]:
    return [
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


def build_comparison() -> pd.DataFrame:
    run_dir = find_latest_training_run()

    summary = load_csv(run_dir / "summary_test_mode.csv", "walkforward summary")
    execution = load_csv(
        run_dir / "execution_realism_analysis.csv",
        "execution realism analysis",
    )

    selected_payload = load_selected_payload()
    selected_models = selected_payload_models(selected_payload)

    selected_prefix_text = " + ".join(
        selected_models[symbol]["prefix"]
        for symbol in sorted(selected_models.keys())
    )

    rows = []

    rows.extend(original_walkforward_rows(summary, selected_models))
    rows.extend(execution_realism_rows(execution, selected_models))
    rows.append(quantconnect_one_day_row())

    rows.append(
        mtm_summary_row(
            path=UNH_XOM_MTM_SUMMARY_PATH,
            stage="UNH/XOM local mark-to-market dynamic signal simulation",
            scope="UNH/XOM combined",
            selected_prefix="ppo_UNH_window1 + ppo_XOM_window2",
            window="250 market bars",
            notes=(
                "Local longer-window UNH/XOM simulation using bar_index alignment, "
                "saved Close returns, and 5 bps transaction costs."
            ),
        )
    )

    rows.append(
        mtm_summary_row(
            path=SELECTED_4TICKER_MTM_SUMMARY_PATH,
            stage="Four-ticker selected local mark-to-market dynamic signal simulation",
            scope="/".join(sorted(selected_models.keys())),
            selected_prefix=selected_prefix_text,
            window="250 market bars",
            notes=(
                "Generalized selected-ticker local simulation using payload-selected "
                "model prefixes, bar_index alignment, saved Close returns, and "
                "5 bps transaction costs."
            ),
        )
    )

    comparison = pd.DataFrame(rows)

    columns = preferred_columns()
    for col in columns:
        if col not in comparison.columns:
            comparison[col] = None

    return comparison[columns]


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    comparison = build_comparison()

    output_path = OUTPUT_DIR / "selected_dynamic_validation_comparison.csv"
    comparison.to_csv(output_path, index=False)

    print("=" * 80)
    print("SELECTED DYNAMIC VALIDATION COMPARISON")
    print("=" * 80)
    print(comparison.to_string(index=False))
    print("\nSaved comparison CSV to:", output_path)


if __name__ == "__main__":
    main()