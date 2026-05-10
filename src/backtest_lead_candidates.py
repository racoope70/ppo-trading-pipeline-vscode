"""Execution-aware backtest for lead PPO candidates.

This script focuses on the current lead candidates from the 4-ticker 150k run:

- UNH
- XOM

It uses saved *_predictions_compat.csv files from the newest PPO training run.
It does not retrain models.

Compared with analyze_execution_realism.py, this helper creates a more detailed
trade-level ledger and equity curve for the selected candidates.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


BACKTESTS_DIR = Path("reports/backtests")
INITIAL_CAPITAL = 100_000.0

LEAD_SYMBOLS = ["UNH", "XOM"]

# Use the moderate execution assumptions from the execution-realism review.
COMMISSION_BPS = 1.0
SLIPPAGE_BPS = 2.0
SPREAD_BPS = 2.0
TOTAL_COST_BPS = COMMISSION_BPS + SLIPPAGE_BPS + SPREAD_BPS
COST_RATE = TOTAL_COST_BPS / 10_000.0


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


def load_summary(summary_path: Path) -> pd.DataFrame:
    """Load walk-forward summary and create prediction-file prefixes."""
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
    """Find the best available price column."""
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

    raise ValueError(
        "Could not find a usable price column. "
        f"Available columns: {list(df.columns)}"
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
    """Calculate annualized Sharpe from hourly-style returns."""
    returns = returns.replace([np.inf, -np.inf], np.nan).dropna()

    if returns.empty:
        return 0.0

    std = returns.std(ddof=0)
    if std == 0 or np.isnan(std):
        return 0.0

    return float((returns.mean() / std) * np.sqrt(periods_per_year))


def prepare_prediction_frame(file_path: Path) -> pd.DataFrame:
    """Load prediction file and standardize columns."""
    df = pd.read_csv(file_path)

    if "Action" not in df.columns:
        raise ValueError(f"Action column missing from {file_path}")

    price_col = find_price_column(df)
    datetime_col = find_datetime_column(df)

    working = df.copy()
    working["price"] = pd.to_numeric(working[price_col], errors="coerce")
    working["action"] = pd.to_numeric(working["Action"], errors="coerce").fillna(0.0)
    working["target_weight"] = working["action"].clip(-1.0, 1.0)

    if "Signal" in working.columns:
        working["signal"] = working["Signal"].astype(str)
    else:
        working["signal"] = np.where(
            working["target_weight"] > 0.05,
            "BUY",
            np.where(working["target_weight"] < -0.05, "SELL", "HOLD"),
        )

    if datetime_col:
        working["datetime"] = pd.to_datetime(working[datetime_col], errors="coerce")
    else:
        working["datetime"] = pd.RangeIndex(start=0, stop=len(working), step=1)

    working = working.dropna(subset=["price"]).reset_index(drop=True)

    if len(working) < 2:
        raise ValueError(f"Not enough valid rows after cleaning: {file_path}")

    return working


def choose_best_lead_prefixes(summary: pd.DataFrame) -> pd.DataFrame:
    """Choose best UNH and XOM windows based on moderate execution logic.

    The previous execution-realism review identified:
    - UNH window 0-3500
    - XOM window 500-4000

    This function keeps that selection dynamic by ranking lead symbols by
    PPO winner first, then Sharpe, then PPO portfolio.
    """
    lead = summary[summary["Ticker"].isin(LEAD_SYMBOLS)].copy()

    if lead.empty:
        raise ValueError(f"No lead symbols found in summary: {LEAD_SYMBOLS}")

    # Keep PPO winners first.
    lead["ppo_winner_flag"] = lead["Winner"].astype(str).str.upper().eq("PPO").astype(int)

    selected = (
        lead.sort_values(
            ["Ticker", "ppo_winner_flag", "Sharpe", "PPO_Portfolio"],
            ascending=[True, False, False, False],
        )
        .groupby("Ticker")
        .head(1)
        .copy()
    )

    return selected


def simulate_candidate(
    file_path: Path,
    symbol: str,
    window: str,
    prefix: str,
    original_ppo: float,
    buyhold: float,
    raw_sharpe: float,
    raw_drawdown: float,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Simulate equity curve and trade ledger for one candidate."""
    df = prepare_prediction_frame(file_path)

    prices = df["price"].astype(float)
    target_weight = df["target_weight"].astype(float)
    price_returns = prices.pct_change().fillna(0.0)

    position = target_weight.shift(1).fillna(0.0)
    new_position = target_weight
    turnover = new_position.sub(position).abs()

    equity = INITIAL_CAPITAL
    equity_rows = []
    ledger_rows = []

    open_trade = None

    for idx in range(len(df)):
        dt = df.loc[idx, "datetime"]
        price = float(prices.iloc[idx])
        signal = str(df.loc[idx, "signal"])
        prev_weight = float(position.iloc[idx])
        target_w = float(new_position.iloc[idx])
        weight_change = float(turnover.iloc[idx])

        gross_pnl = equity * prev_weight * float(price_returns.iloc[idx])
        notional_traded = equity * weight_change
        transaction_cost = notional_traded * COST_RATE
        net_pnl = gross_pnl - transaction_cost
        equity_before = equity
        equity = equity + net_pnl

        equity_rows.append(
            {
                "Datetime": dt,
                "Symbol": symbol,
                "Window": window,
                "Prefix": prefix,
                "Price": price,
                "Signal": signal,
                "Previous_Weight": prev_weight,
                "Target_Weight": target_w,
                "Weight_Change": weight_change,
                "Notional_Traded": notional_traded,
                "Gross_PnL": gross_pnl,
                "Transaction_Cost": transaction_cost,
                "Net_PnL": net_pnl,
                "Equity_Before": equity_before,
                "Equity_After": equity,
            }
        )

        # Trade ledger logic:
        # A trade starts when exposure moves from flat/small to meaningful.
        # It closes when sign changes or exposure drops near zero.
        prev_abs = abs(prev_weight)
        target_abs = abs(target_w)
        prev_sign = np.sign(prev_weight)
        target_sign = np.sign(target_w)

        entering = prev_abs < 0.05 and target_abs >= 0.05
        exiting = prev_abs >= 0.05 and target_abs < 0.05
        flipping = prev_abs >= 0.05 and target_abs >= 0.05 and prev_sign != target_sign

        if entering and open_trade is None:
            open_trade = {
                "Symbol": symbol,
                "Window": window,
                "Prefix": prefix,
                "Entry_Datetime": dt,
                "Entry_Price": price,
                "Entry_Weight": target_w,
                "Direction": "LONG" if target_w > 0 else "SHORT",
                "Entry_Equity": equity,
                "Entry_Index": idx,
                "Costs": transaction_cost,
            }
        elif open_trade is not None:
            open_trade["Costs"] += transaction_cost

        if open_trade is not None and (exiting or flipping or idx == len(df) - 1):
            direction = open_trade["Direction"]
            entry_price = float(open_trade["Entry_Price"])
            entry_equity = float(open_trade["Entry_Equity"])

            if direction == "LONG":
                raw_trade_return = (price / entry_price) - 1.0
            else:
                raw_trade_return = (entry_price / price) - 1.0

            trade_pnl = equity - entry_equity
            holding_bars = idx - int(open_trade["Entry_Index"])

            ledger_rows.append(
                {
                    "Symbol": symbol,
                    "Window": window,
                    "Prefix": prefix,
                    "Direction": direction,
                    "Entry_Datetime": open_trade["Entry_Datetime"],
                    "Exit_Datetime": dt,
                    "Entry_Price": entry_price,
                    "Exit_Price": price,
                    "Entry_Weight": open_trade["Entry_Weight"],
                    "Exit_Weight": target_w,
                    "Holding_Bars": holding_bars,
                    "Raw_Trade_Return": raw_trade_return,
                    "Trade_PnL": trade_pnl,
                    "Trade_Costs": open_trade["Costs"],
                    "Entry_Equity": entry_equity,
                    "Exit_Equity": equity,
                    "Exit_Reason": "flip" if flipping else "flat_or_end",
                }
            )

            if flipping:
                open_trade = {
                    "Symbol": symbol,
                    "Window": window,
                    "Prefix": prefix,
                    "Entry_Datetime": dt,
                    "Entry_Price": price,
                    "Entry_Weight": target_w,
                    "Direction": "LONG" if target_w > 0 else "SHORT",
                    "Entry_Equity": equity,
                    "Entry_Index": idx,
                    "Costs": transaction_cost,
                }
            else:
                open_trade = None

    equity_df = pd.DataFrame(equity_rows)
    ledger_df = pd.DataFrame(ledger_rows)

    equity_series = equity_df["Equity_After"]
    returns = equity_series.pct_change().fillna(0.0)

    if ledger_df.empty:
        win_rate = 0.0
        avg_trade_pnl = 0.0
        avg_holding_bars = 0.0
        total_trade_costs = float(equity_df["Transaction_Cost"].sum())
        trade_count = 0
    else:
        win_rate = float((ledger_df["Trade_PnL"] > 0).mean())
        avg_trade_pnl = float(ledger_df["Trade_PnL"].mean())
        avg_holding_bars = float(ledger_df["Holding_Bars"].mean())
        total_trade_costs = float(ledger_df["Trade_Costs"].sum())
        trade_count = int(len(ledger_df))

    summary_row = pd.DataFrame(
        [
            {
                "Symbol": symbol,
                "Window": window,
                "Prefix": prefix,
                "Original_PPO_Portfolio": original_ppo,
                "BuyHold": buyhold,
                "Raw_Sharpe": raw_sharpe,
                "Raw_Drawdown_%": raw_drawdown,
                "Execution_Final_Equity": float(equity_series.iloc[-1]),
                "Execution_Return_%": float((equity_series.iloc[-1] / INITIAL_CAPITAL - 1.0) * 100.0),
                "Execution_Edge_vs_BuyHold": float(equity_series.iloc[-1] - buyhold),
                "Execution_Winner": "PPO" if float(equity_series.iloc[-1] - buyhold) > 0 else "Buy & Hold",
                "Execution_Max_Drawdown_%": max_drawdown_pct(equity_series),
                "Execution_Sharpe_Est": sharpe_from_returns(returns),
                "Trade_Count": trade_count,
                "Win_Rate": win_rate,
                "Avg_Trade_PnL": avg_trade_pnl,
                "Avg_Holding_Bars": avg_holding_bars,
                "Total_Notional_Traded": float(equity_df["Notional_Traded"].sum()),
                "Total_Transaction_Costs": total_trade_costs,
                "Total_Cost_Bps": TOTAL_COST_BPS,
            }
        ]
    )

    return summary_row, equity_df, ledger_df


def main() -> None:
    """Run lead-candidate trade ledger backtest."""
    summary_path = find_latest_summary()
    run_dir = summary_path.parent
    summary = load_summary(summary_path)

    print("=" * 80)
    print("LEAD CANDIDATE EXECUTION-AWARE BACKTEST")
    print("=" * 80)
    print("Using newest summary:", summary_path)
    print("Using run folder:", run_dir)
    print("Lead symbols:", LEAD_SYMBOLS)
    print("Total cost bps:", TOTAL_COST_BPS)

    selected = choose_best_lead_prefixes(summary)

    summary_frames = []
    equity_frames = []
    ledger_frames = []

    for _, row in selected.iterrows():
        symbol = str(row["Ticker"])
        window = str(row["Window"])
        prefix = str(row["prefix"])
        file_path = run_dir / f"{prefix}_predictions_compat.csv"

        if not file_path.exists():
            raise FileNotFoundError(f"Prediction file not found: {file_path}")

        print(f"\nBacktesting {symbol} | {window} | {prefix}")

        summary_row, equity_df, ledger_df = simulate_candidate(
            file_path=file_path,
            symbol=symbol,
            window=window,
            prefix=prefix,
            original_ppo=float(row["PPO_Portfolio"]),
            buyhold=float(row["BuyHold"]),
            raw_sharpe=float(row["Sharpe"]),
            raw_drawdown=float(row["Drawdown_%"]),
        )

        summary_frames.append(summary_row)
        equity_frames.append(equity_df)
        ledger_frames.append(ledger_df)

    final_summary = pd.concat(summary_frames, ignore_index=True)
    final_equity = pd.concat(equity_frames, ignore_index=True)

    if ledger_frames:
        final_ledger = pd.concat(ledger_frames, ignore_index=True)
    else:
        final_ledger = pd.DataFrame()

    summary_output = run_dir / "lead_candidate_backtest_summary.csv"
    equity_output = run_dir / "lead_candidate_equity_curve.csv"
    ledger_output = run_dir / "lead_candidate_trade_ledger.csv"

    final_summary.to_csv(summary_output, index=False)
    final_equity.to_csv(equity_output, index=False)
    final_ledger.to_csv(ledger_output, index=False)

    print("\nLead candidate summary:")
    print(
        final_summary[
            [
                "Symbol",
                "Window",
                "Original_PPO_Portfolio",
                "BuyHold",
                "Execution_Final_Equity",
                "Execution_Edge_vs_BuyHold",
                "Execution_Winner",
                "Execution_Max_Drawdown_%",
                "Execution_Sharpe_Est",
                "Trade_Count",
                "Win_Rate",
                "Avg_Holding_Bars",
                "Total_Notional_Traded",
                "Total_Transaction_Costs",
            ]
        ].to_string(index=False)
    )

    print("\nSaved outputs:")
    print("Summary:", summary_output)
    print("Equity curve:", equity_output)
    print("Trade ledger:", ledger_output)

    print("\nInterpretation guide:")
    print("- This is still a research backtest, not broker-accurate live execution.")
    print("- It is designed to inspect trade-level behavior for UNH and XOM.")
    print("- Review trade count, win rate, holding bars, costs, drawdown, and edge vs Buy & Hold.")
    print("- If UNH/XOM survive this review, the next step is QuantConnect LEAN testing.")


if __name__ == "__main__":
    main()