"""Run a deeper execution-realism review for PPO walk-forward predictions.

This script uses existing *_predictions_compat.csv files from the newest PPO
training run. It does not retrain models.

It simulates a simple target-position equity curve using the PPO Action column,
then applies execution-friction assumptions:

- commission / transaction cost in basis points
- slippage in basis points
- spread cost in basis points

This is still not a broker-accurate simulator. It is a research diagnostic that
answers a more realistic question than the raw backtest:

    Does the PPO window still look attractive after position changes,
    execution friction, and cost-adjusted drawdown?
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


BACKTESTS_DIR = Path("reports/backtests")
INITIAL_CAPITAL = 100_000.0

# Cost scenarios are expressed in basis points per notional traded.
# total_bps = commission_bps + slippage_bps + spread_bps
COST_SCENARIOS = [
    {"Scenario": "light", "Commission_Bps": 0.5, "Slippage_Bps": 0.5, "Spread_Bps": 0.5},
    {"Scenario": "moderate", "Commission_Bps": 1.0, "Slippage_Bps": 2.0, "Spread_Bps": 2.0},
    {"Scenario": "harsh", "Commission_Bps": 2.0, "Slippage_Bps": 5.0, "Spread_Bps": 3.0},
]


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

    ticker = parts[1]
    window = parts[2]
    prefix = "_".join(parts[:3])

    return ticker, window, prefix


def load_summary(summary_path: Path) -> pd.DataFrame:
    """Load summary file and create the same prefix key as prediction files."""
    summary = pd.read_csv(summary_path)

    required = {
        "Ticker",
        "Window",
        "PPO_Portfolio",
        "BuyHold",
        "Sharpe",
        "Drawdown_%",
        "Winner",
    }
    missing = required - set(summary.columns)

    if missing:
        raise ValueError(
            f"Summary file missing required columns: {sorted(missing)}. "
            f"File: {summary_path}"
        )

    summary = summary.copy()
    summary["window_number"] = summary.groupby("Ticker").cumcount() + 1
    summary["prefix"] = (
        "ppo_"
        + summary["Ticker"].astype(str)
        + "_window"
        + summary["window_number"].astype(str)
    )

    return summary


def find_price_column(df: pd.DataFrame) -> str:
    """Find the best available price column in a prediction file."""
    candidates = [
        "Close",
        "close",
        "Adj Close",
        "Adj_Close",
        "Price",
        "price",
        "Last",
        "last",
    ]

    for col in candidates:
        if col in df.columns:
            return col

    numeric_cols = [
        col
        for col in df.columns
        if pd.api.types.is_numeric_dtype(df[col])
        and col not in {"Action", "Prediction", "Target"}
    ]

    raise ValueError(
        "Could not find a price column. Expected one of "
        f"{candidates}. Numeric columns found: {numeric_cols}"
    )


def find_datetime_column(df: pd.DataFrame) -> str | None:
    """Find a datetime column when available."""
    candidates = ["Datetime", "datetime", "Date", "date", "timestamp", "Timestamp"]

    for col in candidates:
        if col in df.columns:
            return col

    return None


def max_drawdown_pct(equity: pd.Series) -> float:
    """Calculate max drawdown as a positive percentage."""
    if equity.empty:
        return 0.0

    running_max = equity.cummax()
    drawdown = equity / running_max - 1.0

    return float(abs(drawdown.min()) * 100.0)


def sharpe_from_returns(returns: pd.Series, periods_per_year: int = 252 * 6) -> float:
    """Calculate annualized Sharpe from hourly-style returns.

    The default assumes roughly 6 market hours per trading day and 252 trading
    days per year. This is a simple approximation for diagnostics.
    """
    returns = returns.replace([np.inf, -np.inf], np.nan).dropna()

    if returns.empty:
        return 0.0

    std = returns.std(ddof=0)
    if std == 0 or np.isnan(std):
        return 0.0

    return float((returns.mean() / std) * np.sqrt(periods_per_year))


def prepare_prediction_frame(file_path: Path) -> pd.DataFrame:
    """Load one prediction file and standardize core columns."""
    df = pd.read_csv(file_path)

    if "Action" not in df.columns:
        raise ValueError(f"Action column missing from {file_path}")

    price_col = find_price_column(df)
    datetime_col = find_datetime_column(df)

    working = df.copy()
    working["price"] = pd.to_numeric(working[price_col], errors="coerce")
    working["action"] = pd.to_numeric(working["Action"], errors="coerce").fillna(0.0)

    # Actions are treated as target portfolio weights. Keep them bounded.
    working["target_weight"] = working["action"].clip(-1.0, 1.0)

    if datetime_col:
        working["datetime"] = pd.to_datetime(working[datetime_col], errors="coerce")
    else:
        working["datetime"] = pd.RangeIndex(start=0, stop=len(working), step=1)

    working = working.dropna(subset=["price"]).reset_index(drop=True)

    if len(working) < 2:
        raise ValueError(f"Not enough valid rows after cleaning: {file_path}")

    return working


def simulate_execution(
    df: pd.DataFrame,
    scenario: dict[str, float | str],
    initial_capital: float = INITIAL_CAPITAL,
) -> dict[str, float | int | str]:
    """Simulate a simple cost-adjusted equity curve.

    Assumption:
    - target_weight is applied to the next-bar return.
    - turnover is abs(change in target weight).
    - cost is turnover * previous equity * total cost rate.
    """
    total_bps = (
        float(scenario["Commission_Bps"])
        + float(scenario["Slippage_Bps"])
        + float(scenario["Spread_Bps"])
    )
    cost_rate = total_bps / 10_000.0

    prices = df["price"].astype(float)
    target_weight = df["target_weight"].astype(float)

    price_returns = prices.pct_change().fillna(0.0)

    # Use yesterday/current previous position for next bar return.
    position = target_weight.shift(1).fillna(0.0)

    # Turnover happens when target weight changes.
    turnover = target_weight.diff().abs().fillna(target_weight.abs())

    equity_values: list[float] = []
    costs: list[float] = []
    gross_pnl_values: list[float] = []
    net_pnl_values: list[float] = []

    equity = initial_capital

    for idx in range(len(df)):
        gross_pnl = equity * float(position.iloc[idx]) * float(price_returns.iloc[idx])
        trade_cost = equity * float(turnover.iloc[idx]) * cost_rate
        net_pnl = gross_pnl - trade_cost
        equity = equity + net_pnl

        equity_values.append(equity)
        costs.append(trade_cost)
        gross_pnl_values.append(gross_pnl)
        net_pnl_values.append(net_pnl)

    equity_series = pd.Series(equity_values)
    net_returns = equity_series.pct_change().fillna(0.0)

    total_cost = float(np.sum(costs))
    gross_pnl_total = float(np.sum(gross_pnl_values))
    net_pnl_total = float(np.sum(net_pnl_values))
    final_equity = float(equity_series.iloc[-1])
    total_return_pct = (final_equity / initial_capital - 1.0) * 100.0

    trade_events = int((turnover > 0).sum())
    average_turnover = float(turnover.mean())
    total_turnover = float(turnover.sum())

    return {
        "Scenario": str(scenario["Scenario"]),
        "Total_Cost_Bps": total_bps,
        "Final_Equity": final_equity,
        "Total_Return_%": total_return_pct,
        "Max_Drawdown_%": max_drawdown_pct(equity_series),
        "Sharpe_Est": sharpe_from_returns(net_returns),
        "Total_Cost_$": total_cost,
        "Gross_PnL_$": gross_pnl_total,
        "Net_PnL_$": net_pnl_total,
        "Trade_Events": trade_events,
        "Total_Turnover": total_turnover,
        "Average_Turnover": average_turnover,
    }


def simulate_prediction_file(file_path: Path) -> pd.DataFrame:
    """Run all execution-cost scenarios for one prediction file."""
    ticker, window, prefix = infer_ticker_window(file_path)
    df = prepare_prediction_frame(file_path)

    rows = []

    for scenario in COST_SCENARIOS:
        metrics = simulate_execution(df, scenario)
        metrics.update(
            {
                "Ticker": ticker,
                "Window_Number": window.replace("window", ""),
                "Prefix": prefix,
                "Rows": len(df),
                "Start_Price": float(df["price"].iloc[0]),
                "End_Price": float(df["price"].iloc[-1]),
                "Buy_Count": int((df.get("Signal", pd.Series(dtype=str)) == "BUY").sum())
                if "Signal" in df.columns
                else np.nan,
                "Sell_Count": int((df.get("Signal", pd.Series(dtype=str)) == "SELL").sum())
                if "Signal" in df.columns
                else np.nan,
                "Hold_Count": int((df.get("Signal", pd.Series(dtype=str)) == "HOLD").sum())
                if "Signal" in df.columns
                else np.nan,
            }
        )
        rows.append(metrics)

    return pd.DataFrame(rows)


def add_summary_context(execution_df: pd.DataFrame, summary_df: pd.DataFrame) -> pd.DataFrame:
    """Join execution results to the original walk-forward summary."""
    merged = execution_df.merge(
        summary_df[
            [
                "prefix",
                "Ticker",
                "Window",
                "PPO_Portfolio",
                "BuyHold",
                "Sharpe",
                "Drawdown_%",
                "Winner",
            ]
        ],
        how="left",
        left_on="Prefix",
        right_on="prefix",
        suffixes=("", "_summary"),
    )

    merged["Execution_Edge_vs_BuyHold"] = merged["Final_Equity"] - merged["BuyHold"]
    merged["Execution_Winner"] = np.where(
        merged["Execution_Edge_vs_BuyHold"] > 0,
        "PPO",
        "Buy & Hold",
    )

    return merged


def main() -> None:
    """Run execution-realism analysis for the newest PPO training run."""
    summary_path = find_latest_summary()
    run_dir = summary_path.parent

    print("=" * 80)
    print("PPO EXECUTION REALISM ANALYSIS")
    print("=" * 80)
    print("Using newest summary:", summary_path)
    print("Using run folder:", run_dir)

    summary = load_summary(summary_path)

    prediction_files = sorted(run_dir.glob("*_predictions_compat.csv"))

    if not prediction_files:
        raise FileNotFoundError(
            f"No *_predictions_compat.csv files found in {run_dir}."
        )

    execution_results = pd.concat(
        [simulate_prediction_file(file_path) for file_path in prediction_files],
        ignore_index=True,
    )

    merged = add_summary_context(execution_results, summary)

    output_path = run_dir / "execution_realism_analysis.csv"
    merged.to_csv(output_path, index=False)

    display_cols = [
        "Ticker",
        "Window",
        "Scenario",
        "Total_Cost_Bps",
        "PPO_Portfolio",
        "BuyHold",
        "Final_Equity",
        "Execution_Edge_vs_BuyHold",
        "Execution_Winner",
        "Total_Return_%",
        "Max_Drawdown_%",
        "Sharpe_Est",
        "Total_Cost_$",
        "Trade_Events",
        "Total_Turnover",
    ]

    print("\nExecution realism summary:")
    print(
        merged[display_cols]
        .sort_values(["Scenario", "Ticker", "Execution_Edge_vs_BuyHold"], ascending=[True, True, False])
        .to_string(index=False)
    )

    print("\nBest by ticker under moderate execution assumptions:")
    moderate = merged[merged["Scenario"] == "moderate"].copy()

    best_moderate = (
        moderate.sort_values(
            ["Ticker", "Execution_Edge_vs_BuyHold"],
            ascending=[True, False],
        )
        .groupby("Ticker")
        .head(1)
    )

    print(
        best_moderate[
            [
                "Ticker",
                "Window",
                "PPO_Portfolio",
                "BuyHold",
                "Final_Equity",
                "Execution_Edge_vs_BuyHold",
                "Execution_Winner",
                "Max_Drawdown_%",
                "Sharpe_Est",
                "Total_Cost_$",
                "Trade_Events",
                "Total_Turnover",
            ]
        ].to_string(index=False)
    )

    print("\nSaved execution realism analysis to:", output_path)

    print("\nInterpretation guide:")
    print("- This simulates target-weight changes from the Action column.")
    print("- Costs are applied to notional turnover.")
    print("- Final_Equity is not expected to match the original PPO_Portfolio exactly.")
    print("- Use this as an execution-risk diagnostic, not a final broker simulator.")
    print("- Models that fail under the moderate scenario need caution before deployment.")


if __name__ == "__main__":
    main()