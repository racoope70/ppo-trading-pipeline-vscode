"""Analyze a precomputed LEAN dynamic signal payload.

Purpose:
    - Validate signal payload structure.
    - Summarize BUY/SELL/HOLD counts.
    - Confirm timestamps are weekday market-hour aligned.
    - Summarize target-weight changes and estimated turnover.
    - Provide a clean local diagnostic before longer execution simulations.

Default input:
    quantconnect/test_payloads/unh_xom_dynamic_signals_250marketbars.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd


DEFAULT_PAYLOAD_PATH = Path(
    "quantconnect/test_payloads/unh_xom_dynamic_signals_250marketbars.json"
)

EXPECTED_MARKET_HOURS_UTC = {10, 11, 12, 13, 14, 15, 16}


def load_payload(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"Payload file not found: {path}")

    with path.open("r") as file:
        payload = json.load(file)

    if "signals" not in payload:
        raise ValueError("Payload is missing required key: signals")

    if not isinstance(payload["signals"], list):
        raise TypeError("Payload key 'signals' must be a list")

    return payload


def signals_to_dataframe(payload: dict) -> pd.DataFrame:
    rows = payload.get("signals", [])

    if not rows:
        raise ValueError("Payload contains no signal rows.")

    df = pd.DataFrame(rows)

    required_columns = {
        "timestamp",
        "symbol",
        "prefix",
        "signal",
        "confidence",
        "action",
        "target_weight",
    }

    missing_columns = required_columns - set(df.columns)

    if missing_columns:
        raise ValueError(f"Signal payload missing columns: {sorted(missing_columns)}")

    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    df["symbol"] = df["symbol"].astype(str).str.upper()
    df["signal"] = df["signal"].astype(str).str.upper()
    df["confidence"] = pd.to_numeric(df["confidence"], errors="coerce")
    df["action"] = pd.to_numeric(df["action"], errors="coerce")
    df["target_weight"] = pd.to_numeric(df["target_weight"], errors="coerce")

    if df["timestamp"].isna().any():
        bad_count = int(df["timestamp"].isna().sum())
        raise ValueError(f"Found {bad_count} rows with invalid timestamps.")

    df = df.sort_values(["symbol", "timestamp"]).reset_index(drop=True)

    return df


def add_diagnostics(df: pd.DataFrame) -> pd.DataFrame:
    output = df.copy()

    output["date"] = output["timestamp"].dt.date.astype(str)
    output["hour_utc"] = output["timestamp"].dt.hour
    output["weekday"] = output["timestamp"].dt.weekday
    output["is_weekday"] = output["weekday"] < 5
    output["is_expected_hour"] = output["hour_utc"].isin(EXPECTED_MARKET_HOURS_UTC)

    output["previous_target_weight"] = (
        output.groupby("symbol")["target_weight"].shift(1).fillna(0.0)
    )
    output["target_weight_change"] = (
        output["target_weight"] - output["previous_target_weight"]
    )
    output["abs_target_weight_change"] = output["target_weight_change"].abs()

    output["position_side"] = "FLAT"
    output.loc[output["target_weight"] > 0, "position_side"] = "LONG"
    output.loc[output["target_weight"] < 0, "position_side"] = "SHORT"

    output["is_trade_event"] = output["abs_target_weight_change"] > 0.0001

    return output


def print_header(title: str) -> None:
    print("\n" + "=" * 80)
    print(title)
    print("=" * 80)


def summarize_payload(payload: dict, df: pd.DataFrame) -> None:
    print_header("DYNAMIC SIGNAL PAYLOAD SUMMARY")

    print(f"Producer: {payload.get('producer')}")
    print(f"Description: {payload.get('description')}")
    print(f"Interval: {payload.get('interval')}")
    print(f"Generated UTC: {payload.get('generated_utc')}")
    print(f"Symbols: {payload.get('symbols')}")
    print(f"Selected models: {payload.get('selected_models')}")
    print(f"Rows: {len(df)}")
    print(f"First timestamp: {df['timestamp'].min()}")
    print(f"Last timestamp: {df['timestamp'].max()}")


def summarize_structure(df: pd.DataFrame) -> None:
    print_header("STRUCTURE CHECKS")

    rows_by_symbol = df.groupby("symbol").size().rename("rows")
    print("\nRows by symbol:")
    print(rows_by_symbol.to_string())

    duplicate_count = int(df.duplicated(subset=["symbol", "timestamp"]).sum())
    print(f"\nDuplicate symbol/timestamp rows: {duplicate_count}")

    invalid_weekday_count = int((~df["is_weekday"]).sum())
    invalid_hour_count = int((~df["is_expected_hour"]).sum())

    print(f"Rows outside Monday-Friday: {invalid_weekday_count}")
    print(f"Rows outside expected UTC hours {sorted(EXPECTED_MARKET_HOURS_UTC)}: {invalid_hour_count}")

    if invalid_weekday_count == 0 and invalid_hour_count == 0:
        print("Market-hour alignment check: PASSED")
    else:
        print("Market-hour alignment check: REVIEW NEEDED")


def summarize_signals(df: pd.DataFrame) -> None:
    print_header("SIGNAL COUNTS")

    counts = (
        df.groupby(["symbol", "signal"])
        .size()
        .rename("count")
        .reset_index()
        .sort_values(["symbol", "signal"])
    )

    print(counts.to_string(index=False))

    side_counts = (
        df.groupby(["symbol", "position_side"])
        .size()
        .rename("count")
        .reset_index()
        .sort_values(["symbol", "position_side"])
    )

    print("\nTarget side counts:")
    print(side_counts.to_string(index=False))


def summarize_weights(df: pd.DataFrame) -> None:
    print_header("TARGET WEIGHT AND TURNOVER DIAGNOSTICS")

    summary = (
        df.groupby("symbol")
        .agg(
            rows=("target_weight", "size"),
            min_target_weight=("target_weight", "min"),
            max_target_weight=("target_weight", "max"),
            mean_abs_target_weight=("target_weight", lambda x: x.abs().mean()),
            trade_events=("is_trade_event", "sum"),
            estimated_turnover=("abs_target_weight_change", "sum"),
            avg_abs_weight_change=("abs_target_weight_change", "mean"),
        )
        .reset_index()
    )

    print(summary.to_string(index=False))

    combined_turnover = float(df["abs_target_weight_change"].sum())
    combined_trade_events = int(df["is_trade_event"].sum())

    print(f"\nCombined estimated turnover: {combined_turnover:.4f}")
    print(f"Combined trade events: {combined_trade_events}")


def summarize_daily_activity(df: pd.DataFrame) -> None:
    print_header("DAILY ACTIVITY")

    daily = (
        df.groupby(["date", "symbol"])
        .agg(
            rows=("target_weight", "size"),
            trade_events=("is_trade_event", "sum"),
            avg_abs_target_weight=("target_weight", lambda x: x.abs().mean()),
            turnover=("abs_target_weight_change", "sum"),
        )
        .reset_index()
    )

    print("\nFirst 20 daily rows:")
    print(daily.head(20).to_string(index=False))

    print("\nLast 20 daily rows:")
    print(daily.tail(20).to_string(index=False))


def save_outputs(df: pd.DataFrame, payload_path: Path) -> None:
    output_dir = Path("reports/dynamic_signal_analysis")
    output_dir.mkdir(parents=True, exist_ok=True)

    base_name = payload_path.stem

    detail_path = output_dir / f"{base_name}_detail.csv"
    summary_path = output_dir / f"{base_name}_summary.csv"

    df.to_csv(detail_path, index=False)

    summary = (
        df.groupby("symbol")
        .agg(
            rows=("target_weight", "size"),
            first_timestamp=("timestamp", "min"),
            last_timestamp=("timestamp", "max"),
            buy_count=("signal", lambda x: int((x == "BUY").sum())),
            sell_count=("signal", lambda x: int((x == "SELL").sum())),
            hold_count=("signal", lambda x: int((x == "HOLD").sum())),
            min_target_weight=("target_weight", "min"),
            max_target_weight=("target_weight", "max"),
            trade_events=("is_trade_event", "sum"),
            estimated_turnover=("abs_target_weight_change", "sum"),
        )
        .reset_index()
    )

    summary.to_csv(summary_path, index=False)

    print_header("SAVED OUTPUTS")
    print(f"Detail CSV: {detail_path}")
    print(f"Summary CSV: {summary_path}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Analyze precomputed LEAN dynamic signal payload."
    )
    parser.add_argument(
        "--payload",
        type=Path,
        default=DEFAULT_PAYLOAD_PATH,
        help=f"Path to dynamic signal JSON payload. Default: {DEFAULT_PAYLOAD_PATH}",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    payload_path = args.payload

    payload = load_payload(payload_path)
    df = signals_to_dataframe(payload)
    df = add_diagnostics(df)

    summarize_payload(payload, df)
    summarize_structure(df)
    summarize_signals(df)
    summarize_weights(df)
    summarize_daily_activity(df)
    save_outputs(df, payload_path)


if __name__ == "__main__":
    main()