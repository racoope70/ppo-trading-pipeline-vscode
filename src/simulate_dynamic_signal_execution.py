"""Simulate local execution from a precomputed dynamic LEAN signal payload.

Purpose:
    - Read the market-hours dynamic signal payload.
    - Simulate target-weight portfolio rebalancing locally.
    - Estimate turnover, transaction costs, drawdown, and equity curve.
    - Produce a longer execution-aware result outside QuantConnect.

Default input:
    quantconnect/test_payloads/unh_xom_dynamic_signals_250marketbars.json

Notes:
    This is not broker-accurate execution.
    This is a local research simulator to evaluate behavior over the full
    precomputed signal window after QuantConnect data availability blocked the
    longer UNH/XOM historical run.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd


DEFAULT_PAYLOAD_PATH = Path(
    "quantconnect/test_payloads/unh_xom_dynamic_signals_250marketbars.json"
)

OUTPUT_DIR = Path("reports/dynamic_signal_execution")

STARTING_EQUITY = 100_000.00
TOTAL_COST_BPS = 5.0


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


def simulate_execution(
    signals: pd.DataFrame,
    starting_equity: float = STARTING_EQUITY,
    total_cost_bps: float = TOTAL_COST_BPS,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Simulate target-weight changes and cost drag.

    This first version does not use actual price returns yet.
    It evaluates turnover/cost behavior from target-weight changes.

    Equity changes only from estimated transaction costs in this version.
    A later version can join actual UNH/XOM bar returns and mark-to-market PnL.
    """
    cost_rate = total_cost_bps / 10_000.0

    current_weights = {
        symbol: 0.0 for symbol in sorted(signals["symbol"].unique())
    }

    equity = float(starting_equity)
    peak_equity = equity

    equity_rows = []
    trade_rows = []

    grouped = signals.groupby("timestamp", sort=True)

    for timestamp, group in grouped:
        timestamp_turnover = 0.0
        timestamp_cost = 0.0

        for _, row in group.iterrows():
            symbol = str(row["symbol"])
            previous_weight = float(current_weights.get(symbol, 0.0))
            target_weight = float(row["target_weight"])

            weight_change = target_weight - previous_weight
            abs_weight_change = abs(weight_change)

            notional_traded = equity * abs_weight_change
            transaction_cost = notional_traded * cost_rate

            if abs_weight_change > 0.0001:
                trade_rows.append(
                    {
                        "timestamp": timestamp,
                        "symbol": symbol,
                        "signal": row["signal"],
                        "action": float(row["action"]),
                        "confidence": float(row["confidence"]),
                        "previous_weight": previous_weight,
                        "target_weight": target_weight,
                        "weight_change": weight_change,
                        "abs_weight_change": abs_weight_change,
                        "notional_traded": notional_traded,
                        "transaction_cost": transaction_cost,
                    }
                )

            timestamp_turnover += abs_weight_change
            timestamp_cost += transaction_cost
            current_weights[symbol] = target_weight

        equity -= timestamp_cost
        peak_equity = max(peak_equity, equity)

        drawdown_pct = 0.0
        if peak_equity > 0:
            drawdown_pct = (peak_equity - equity) / peak_equity * 100.0

        gross_exposure = sum(abs(weight) for weight in current_weights.values())
        net_exposure = sum(current_weights.values())

        equity_rows.append(
            {
                "timestamp": timestamp,
                "equity": equity,
                "turnover": timestamp_turnover,
                "transaction_cost": timestamp_cost,
                "gross_exposure": gross_exposure,
                "net_exposure": net_exposure,
                "drawdown_pct": drawdown_pct,
                **{
                    f"{symbol}_weight": weight
                    for symbol, weight in current_weights.items()
                },
            }
        )

    equity_curve = pd.DataFrame(equity_rows)
    trade_ledger = pd.DataFrame(trade_rows)

    return equity_curve, trade_ledger


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

    summary = pd.DataFrame(
        [
            {
                "Starting_Equity": starting_equity,
                "Final_Equity": final_equity,
                "Net_Return_%": net_return_pct,
                "Total_Transaction_Costs": total_costs,
                "Total_Turnover": total_turnover,
                "Trade_Events": trade_events,
                "Max_Drawdown_%": max_drawdown,
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

    summary_path = OUTPUT_DIR / f"{base_name}_execution_summary.csv"
    equity_path = OUTPUT_DIR / f"{base_name}_equity_curve.csv"
    trades_path = OUTPUT_DIR / f"{base_name}_trade_ledger.csv"

    summary.to_csv(summary_path, index=False)
    equity_curve.to_csv(equity_path, index=False)
    trade_ledger.to_csv(trades_path, index=False)

    print_header("SAVED OUTPUTS")
    print(f"Summary: {summary_path}")
    print(f"Equity curve: {equity_path}")
    print(f"Trade ledger: {trades_path}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Simulate execution from a dynamic signal payload."
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

    equity_curve, trade_ledger = simulate_execution(
        signals=signals,
        starting_equity=args.starting_equity,
        total_cost_bps=args.cost_bps,
    )

    summary = summarize_results(
        equity_curve=equity_curve,
        trade_ledger=trade_ledger,
        starting_equity=args.starting_equity,
    )

    print_header("DYNAMIC SIGNAL EXECUTION SIMULATION")
    print(f"Payload: {args.payload}")
    print(f"Signal rows: {len(signals)}")
    print(f"Starting equity: {args.starting_equity:,.2f}")
    print(f"Cost bps: {args.cost_bps:.2f}")

    print_header("SUMMARY")
    print(summary.to_string(index=False))

    if not trade_ledger.empty:
        print_header("TRADE LEDGER SAMPLE")
        print(trade_ledger.head(20).to_string(index=False))

    save_outputs(args.payload, summary, equity_curve, trade_ledger)


if __name__ == "__main__":
    main()