"""Simulate local execution from a precomputed dynamic LEAN signal payload.

Purpose:
    - Read the market-hours dynamic signal payload.
    - Load matching Close-price series from saved *_predictions_compat.csv files.
    - Simulate target-weight portfolio rebalancing locally.
    - Apply mark-to-market PnL using prior weights and symbol returns.
    - Estimate turnover, transaction costs, drawdown, and equity curve.

Default input:
    quantconnect/test_payloads/unh_xom_dynamic_signals_250marketbars.json

Notes:
    This is not broker-accurate execution.
    This is a local research simulator to evaluate behavior over the full
    precomputed signal window after QuantConnect data availability blocked the
    longer UNH/XOM historical run.

    To avoid lookahead bias:
    - Per-bar return is applied using weights held from the previous timestamp.
    - Then transaction costs are applied for changing into the new target weights.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd


DEFAULT_PAYLOAD_PATH = Path(
    "quantconnect/test_payloads/unh_xom_dynamic_signals_250marketbars.json"
)

BACKTESTS_DIR = Path("reports/backtests")
OUTPUT_DIR = Path("reports/dynamic_signal_execution")

SELECTED_MODELS = {
    "UNH": "ppo_UNH_window1",
    "XOM": "ppo_XOM_window2",
}

STARTING_EQUITY = 100_000.00
TOTAL_COST_BPS = 5.0


def find_latest_training_run() -> Path:
    summaries = sorted(
        BACKTESTS_DIR.glob("ppo_walkforward_results_*/summary_test_mode.csv")
    )

    if not summaries:
        raise FileNotFoundError(
            "No summary_test_mode.csv files found under reports/backtests."
        )

    return summaries[-1].parent


def load_payload(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"Payload file not found: {path}")

    with path.open("r") as file:
        payload = json.load(file)

    if "signals" not in payload:
        raise ValueError("Payload missing required key: signals")

    return payload


def payload_to_dataframe(payload: dict) -> pd.DataFrame:
    df = pd.DataFrame(payload.get("signals", []))

    if df.empty:
        raise ValueError("Signal payload contains no rows.")

    required_columns = {
        "timestamp",
        "symbol",
        "signal",
        "action",
        "confidence",
        "target_weight",
    }

    missing_columns = required_columns - set(df.columns)
    if missing_columns:
        raise ValueError(f"Payload missing columns: {sorted(missing_columns)}")

    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    df["symbol"] = df["symbol"].astype(str).str.upper()
    df["signal"] = df["signal"].astype(str).str.upper()
    df["action"] = pd.to_numeric(df["action"], errors="coerce").fillna(0.0)
    df["confidence"] = pd.to_numeric(df["confidence"], errors="coerce").fillna(0.0)
    df["target_weight"] = pd.to_numeric(df["target_weight"], errors="coerce").fillna(0.0)

    if df["timestamp"].isna().any():
        raise ValueError("One or more payload timestamps could not be parsed.")

    return df.sort_values(["timestamp", "symbol"]).reset_index(drop=True)


def load_symbol_returns(
    run_dir: Path,
    signals: pd.DataFrame,
    selected_models: dict[str, str],
) -> pd.DataFrame:
    """Load Close returns from prediction compatibility CSVs.

    The payload timestamps are synthetic market-bar timestamps created for
    QuantConnect/LEAN alignment. The prediction CSVs have their original
    historical Datetime values. For local simulation, we align by row order:
    the last N prediction rows are matched to the N signal rows per symbol.
    """
    frames = []

    for symbol, prefix in selected_models.items():
        signal_rows = (
            signals[signals["symbol"] == symbol]
            .sort_values("timestamp")
            .reset_index(drop=True)
        )

        if signal_rows.empty:
            raise ValueError(f"No signal rows found for {symbol}")

        prediction_path = run_dir / f"{prefix}_predictions_compat.csv"

        if not prediction_path.exists():
            raise FileNotFoundError(
                f"Prediction compatibility file not found for {symbol}: "
                f"{prediction_path}"
            )

        prices = pd.read_csv(prediction_path)

        required_columns = {"Datetime", "Close"}
        missing_columns = required_columns - set(prices.columns)

        if missing_columns:
            raise ValueError(
                f"{prediction_path} missing required columns: {sorted(missing_columns)}"
            )

        prices = prices.copy()
        prices["source_datetime"] = pd.to_datetime(
            prices["Datetime"],
            utc=True,
            errors="coerce",
        )
        prices["close"] = pd.to_numeric(prices["Close"], errors="coerce")

        prices = prices.dropna(subset=["source_datetime", "close"])

        if len(prices) < len(signal_rows):
            raise ValueError(
                f"Not enough price rows for {symbol}: "
                f"need {len(signal_rows)}, found {len(prices)}"
            )

        aligned_prices = prices.tail(len(signal_rows)).reset_index(drop=True)
        aligned_prices["symbol"] = symbol
        aligned_prices["timestamp"] = signal_rows["timestamp"].values

        aligned_prices["symbol_return"] = aligned_prices["close"].pct_change().fillna(0.0)

        frames.append(
            aligned_prices[
                [
                    "timestamp",
                    "symbol",
                    "source_datetime",
                    "close",
                    "symbol_return",
                ]
            ]
        )

    return pd.concat(frames, ignore_index=True).sort_values(
        ["timestamp", "symbol"]
    ).reset_index(drop=True)


def simulate_execution(
    signals: pd.DataFrame,
    returns: pd.DataFrame,
    starting_equity: float = STARTING_EQUITY,
    total_cost_bps: float = TOTAL_COST_BPS,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Simulate mark-to-market returns, target changes, and cost drag.

    Order of operations at each timestamp:
        1. Apply PnL from previous weights using current symbol returns.
        2. Rebalance from previous weights to current target weights.
        3. Subtract transaction costs based on notional traded.
    """
    cost_rate = total_cost_bps / 10_000.0

    symbols = sorted(signals["symbol"].unique())

    current_weights = {symbol: 0.0 for symbol in symbols}

    equity = float(starting_equity)
    peak_equity = equity

    signal_lookup = {
        timestamp: group.copy()
        for timestamp, group in signals.groupby("timestamp", sort=True)
    }

    return_lookup = {
        timestamp: group.copy()
        for timestamp, group in returns.groupby("timestamp", sort=True)
    }

    all_timestamps = sorted(signal_lookup.keys())

    equity_rows = []
    trade_rows = []

    for timestamp in all_timestamps:
        signal_group = signal_lookup[timestamp]
        return_group = return_lookup.get(timestamp)

        if return_group is None:
            raise ValueError(f"Missing return rows for timestamp: {timestamp}")

        symbol_returns = {
            str(row["symbol"]): float(row["symbol_return"])
            for _, row in return_group.iterrows()
        }

        symbol_closes = {
            str(row["symbol"]): float(row["close"])
            for _, row in return_group.iterrows()
        }

        source_datetimes = {
            str(row["symbol"]): row["source_datetime"]
            for _, row in return_group.iterrows()
        }

        # 1. Mark-to-market using weights held from prior timestamp.
        portfolio_return = 0.0
        pnl_by_symbol = {}

        for symbol in symbols:
            prior_weight = float(current_weights.get(symbol, 0.0))
            symbol_return = float(symbol_returns.get(symbol, 0.0))
            pnl_contribution = prior_weight * symbol_return
            portfolio_return += pnl_contribution
            pnl_by_symbol[symbol] = equity * pnl_contribution

        gross_pnl = equity * portfolio_return
        equity_before_costs = equity + gross_pnl

        # 2. Rebalance into new target weights.
        timestamp_turnover = 0.0
        timestamp_cost = 0.0

        for _, row in signal_group.iterrows():
            symbol = str(row["symbol"])
            previous_weight = float(current_weights.get(symbol, 0.0))
            target_weight = float(row["target_weight"])

            weight_change = target_weight - previous_weight
            abs_weight_change = abs(weight_change)

            notional_traded = equity_before_costs * abs_weight_change
            transaction_cost = notional_traded * cost_rate

            if abs_weight_change > 0.0001:
                trade_rows.append(
                    {
                        "timestamp": timestamp,
                        "symbol": symbol,
                        "source_datetime": source_datetimes.get(symbol),
                        "close": symbol_closes.get(symbol),
                        "signal": row["signal"],
                        "action": float(row["action"]),
                        "confidence": float(row["confidence"]),
                        "previous_weight": previous_weight,
                        "target_weight": target_weight,
                        "weight_change": weight_change,
                        "abs_weight_change": abs_weight_change,
                        "symbol_return": float(symbol_returns.get(symbol, 0.0)),
                        "notional_traded": notional_traded,
                        "transaction_cost": transaction_cost,
                    }
                )

            timestamp_turnover += abs_weight_change
            timestamp_cost += transaction_cost
            current_weights[symbol] = target_weight

        # 3. Subtract costs after rebalancing.
        equity = equity_before_costs - timestamp_cost
        peak_equity = max(peak_equity, equity)

        drawdown_pct = 0.0
        if peak_equity > 0:
            drawdown_pct = (peak_equity - equity) / peak_equity * 100.0

        gross_exposure = sum(abs(weight) for weight in current_weights.values())
        net_exposure = sum(current_weights.values())

        row = {
            "timestamp": timestamp,
            "equity": equity,
            "portfolio_return_before_costs": portfolio_return,
            "gross_pnl_before_costs": gross_pnl,
            "transaction_cost": timestamp_cost,
            "turnover": timestamp_turnover,
            "gross_exposure": gross_exposure,
            "net_exposure": net_exposure,
            "drawdown_pct": drawdown_pct,
        }

        for symbol in symbols:
            row[f"{symbol}_weight"] = current_weights[symbol]
            row[f"{symbol}_return"] = symbol_returns.get(symbol, 0.0)
            row[f"{symbol}_close"] = symbol_closes.get(symbol)
            row[f"{symbol}_pnl_contribution"] = pnl_by_symbol.get(symbol, 0.0)
            row[f"{symbol}_source_datetime"] = source_datetimes.get(symbol)

        equity_rows.append(row)

    equity_curve = pd.DataFrame(equity_rows)
    trade_ledger = pd.DataFrame(trade_rows)

    return equity_curve, trade_ledger


def calculate_sharpe(equity_curve: pd.DataFrame) -> float:
    returns = equity_curve["equity"].pct_change().dropna()

    if returns.empty:
        return 0.0

    std = returns.std()

    if std == 0 or pd.isna(std):
        return 0.0

    # Approximate annualization for hourly market bars:
    # 252 trading days * 7 bars per day.
    annualization = (252 * 7) ** 0.5

    return float((returns.mean() / std) * annualization)


def summarize_results(
    equity_curve: pd.DataFrame,
    trade_ledger: pd.DataFrame,
    starting_equity: float,
) -> pd.DataFrame:
    final_equity = float(equity_curve["equity"].iloc[-1])
    total_costs = float(equity_curve["transaction_cost"].sum())
    total_turnover = float(equity_curve["turnover"].sum())
    max_drawdown = float(equity_curve["drawdown_pct"].max())
    trade_events = int(len(trade_ledger))
    net_return_pct = (final_equity / starting_equity - 1.0) * 100.0
    sharpe_est = calculate_sharpe(equity_curve)

    gross_pnl_before_costs = float(equity_curve["gross_pnl_before_costs"].sum())
    net_pnl = final_equity - starting_equity

    summary = pd.DataFrame(
        [
            {
                "Starting_Equity": starting_equity,
                "Final_Equity": final_equity,
                "Net_PnL": net_pnl,
                "Net_Return_%": net_return_pct,
                "Gross_PnL_Before_Costs": gross_pnl_before_costs,
                "Total_Transaction_Costs": total_costs,
                "Total_Turnover": total_turnover,
                "Trade_Events": trade_events,
                "Max_Drawdown_%": max_drawdown,
                "Sharpe_Est": sharpe_est,
                "Rows": int(len(equity_curve)),
            }
        ]
    )

    return summary


def print_header(title: str) -> None:
    print("\n" + "=" * 80)
    print(title)
    print("=" * 80)


def save_outputs(
    payload_path: Path,
    summary: pd.DataFrame,
    equity_curve: pd.DataFrame,
    trade_ledger: pd.DataFrame,
) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    base_name = payload_path.stem

    summary_path = OUTPUT_DIR / f"{base_name}_mtm_execution_summary.csv"
    equity_path = OUTPUT_DIR / f"{base_name}_mtm_equity_curve.csv"
    trades_path = OUTPUT_DIR / f"{base_name}_mtm_trade_ledger.csv"

    summary.to_csv(summary_path, index=False)
    equity_curve.to_csv(equity_path, index=False)
    trade_ledger.to_csv(trades_path, index=False)

    print_header("SAVED OUTPUTS")
    print(f"Summary: {summary_path}")
    print(f"Equity curve: {equity_path}")
    print(f"Trade ledger: {trades_path}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Simulate mark-to-market execution from a dynamic signal payload."
    )
    parser.add_argument(
        "--payload",
        type=Path,
        default=DEFAULT_PAYLOAD_PATH,
        help=f"Path to signal payload. Default: {DEFAULT_PAYLOAD_PATH}",
    )
    parser.add_argument(
        "--starting-equity",
        type=float,
        default=STARTING_EQUITY,
        help="Starting equity for the simulation.",
    )
    parser.add_argument(
        "--cost-bps",
        type=float,
        default=TOTAL_COST_BPS,
        help="Total transaction cost in basis points applied to notional traded.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    payload = load_payload(args.payload)
    signals = payload_to_dataframe(payload)

    run_dir = find_latest_training_run()

    returns = load_symbol_returns(
        run_dir=run_dir,
        signals=signals,
        selected_models=SELECTED_MODELS,
    )

    equity_curve, trade_ledger = simulate_execution(
        signals=signals,
        returns=returns,
        starting_equity=args.starting_equity,
        total_cost_bps=args.cost_bps,
    )

    summary = summarize_results(
        equity_curve=equity_curve,
        trade_ledger=trade_ledger,
        starting_equity=args.starting_equity,
    )

    print_header("DYNAMIC SIGNAL MARK-TO-MARKET EXECUTION SIMULATION")
    print(f"Payload: {args.payload}")
    print(f"Using training run: {run_dir}")
    print(f"Signal rows: {len(signals)}")
    print(f"Return rows: {len(returns)}")
    print(f"Starting equity: {args.starting_equity:,.2f}")
    print(f"Cost bps: {args.cost_bps:.2f}")

    print_header("SUMMARY")
    print(summary.to_string(index=False))

    if not trade_ledger.empty:
        print_header("TRADE LEDGER SAMPLE")
        print(trade_ledger.head(20).to_string(index=False))

    print_header("EQUITY CURVE SAMPLE")
    print(equity_curve.head(10).to_string(index=False))

    save_outputs(args.payload, summary, equity_curve, trade_ledger)


if __name__ == "__main__":
    main()