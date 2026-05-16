"""Export selected PPO dynamic signals into a LEAN-friendly JSON file.

Purpose:
    - Read execution_realism_analysis.csv from the requested run directory, or from the newest run if --run-dir is omitted.
    - Select the best moderate-scenario PPO model per ticker.
    - Convert saved *_predictions_compat.csv files into a market-hours-aligned
      dynamic signal payload for QuantConnect/LEAN Object Store.

Default tickers:
    AAPL, PFE, UNH, XOM

Output:
    quantconnect/test_payloads/selected_dynamic_signals_4ticker_250marketbars.json

Notes:
    This generalizes src/export_dynamic_lean_signals.py, which was originally
    focused only on UNH/XOM.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd


BACKTESTS_DIR = Path("reports/backtests")
DEFAULT_OUTPUT_PATH = Path(
    "quantconnect/test_payloads/selected_dynamic_signals_4ticker_250marketbars.json"
)

DEFAULT_SYMBOLS = ["AAPL", "PFE", "UNH", "XOM"]

LEAN_START_DATE = datetime(2026, 2, 10, tzinfo=timezone.utc)
MARKET_HOURS_UTC = [10, 11, 12, 13, 14, 15, 16]

MAX_ROWS_PER_SYMBOL = 250
MAX_ABS_WEIGHT = 0.25
MIN_CONFIDENCE = 0.10


def find_latest_training_run() -> Path:
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


def market_bar_timestamps(start_date: datetime, count: int) -> list[datetime]:
    timestamps = []
    day = start_date

    while len(timestamps) < count:
        if day.weekday() < 5:
            for hour in MARKET_HOURS_UTC:
                if len(timestamps) >= count:
                    break

                timestamps.append(
                    datetime(
                        day.year,
                        day.month,
                        day.day,
                        hour,
                        0,
                        tzinfo=timezone.utc,
                    )
                )

        day += timedelta(days=1)

    return timestamps


def window_to_prefix(symbol: str, window: str) -> str:
    """Map walkforward window label to artifact prefix.

    Current walkforward labels are:
        0-3500      -> window1
        500-4000    -> window2
        1000-4500   -> window3

    If future windows are added, this function intentionally fails loudly
    unless updated.
    """
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
    path = run_dir / "execution_realism_analysis.csv"

    if not path.exists():
        raise FileNotFoundError(
            f"Missing execution realism file: {path}\n"
            "Run first: python -m src.analyze_execution_realism"
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
    }

    missing_columns = required_columns - set(df.columns)

    if missing_columns:
        raise ValueError(
            f"execution_realism_analysis.csv missing columns: {sorted(missing_columns)}"
        )

    return df


def select_best_models(
    execution: pd.DataFrame,
    symbols: list[str],
    scenario: str = "moderate",
) -> dict[str, dict]:
    """Select best model per symbol by execution edge under chosen scenario."""
    selected = {}

    scenario_df = execution[
        execution["Scenario"].astype(str).str.lower().eq(scenario.lower())
    ].copy()

    if scenario_df.empty:
        raise ValueError(f"No rows found for execution scenario: {scenario}")

    scenario_df["Execution_Edge_vs_BuyHold"] = pd.to_numeric(
        scenario_df["Execution_Edge_vs_BuyHold"],
        errors="coerce",
    )

    scenario_df = scenario_df.dropna(subset=["Execution_Edge_vs_BuyHold"])

    for symbol in symbols:
        candidates = scenario_df[
            scenario_df["Ticker"].astype(str).str.upper().eq(symbol.upper())
        ].copy()

        if candidates.empty:
            raise ValueError(f"No execution-realism candidates found for {symbol}")

        best = candidates.sort_values(
            "Execution_Edge_vs_BuyHold",
            ascending=False,
        ).iloc[0]

        window = str(best["Window"])
        prefix = window_to_prefix(symbol.upper(), window)

        selected[symbol.upper()] = {
            "symbol": symbol.upper(),
            "prefix": prefix,
            "window": window,
            "scenario": str(best["Scenario"]),
            "execution_edge_vs_buyhold": float(best["Execution_Edge_vs_BuyHold"]),
            "execution_winner": str(best["Execution_Winner"]),
            "final_equity": float(best["Final_Equity"]),
            "sharpe_est": float(best["Sharpe_Est"]),
            "max_drawdown_pct": float(best["Max_Drawdown_%"]),
        }

    return selected


def action_to_signal(action: float) -> str:
    if action > 0.10:
        return "BUY"

    if action < -0.30:
        return "SELL"

    return "HOLD"


def action_to_target_weight(signal: str, action: float, confidence: float) -> float:
    if confidence < MIN_CONFIDENCE:
        return 0.0

    clipped_action = max(min(float(action), 1.0), -1.0)

    if signal == "BUY":
        return min(abs(clipped_action), MAX_ABS_WEIGHT)

    if signal == "SELL":
        return -min(abs(clipped_action), MAX_ABS_WEIGHT)

    return 0.0


def load_prediction_file(
    run_dir: Path,
    symbol: str,
    prefix: str,
    max_rows: int,
) -> pd.DataFrame:
    path = run_dir / f"{prefix}_predictions_compat.csv"

    if not path.exists():
        raise FileNotFoundError(f"Missing prediction file for {symbol}: {path}")

    df = pd.read_csv(path)

    if "Action" not in df.columns:
        raise ValueError(f"Missing Action column in {path}")

    df = df.copy()
    df["Action"] = pd.to_numeric(df["Action"], errors="coerce").fillna(0.0)

    if "Signal" not in df.columns:
        df["Signal"] = df["Action"].apply(action_to_signal)

    df["Signal"] = df["Signal"].astype(str).str.upper()
    df["confidence"] = df["Action"].abs()

    return df.tail(max_rows).reset_index(drop=True)


def build_payload(
    run_dir: Path,
    selected_models: dict[str, dict],
    max_rows_per_symbol: int,
) -> dict:
    timestamps = market_bar_timestamps(
        start_date=LEAN_START_DATE,
        count=max_rows_per_symbol,
    )

    all_signals = []

    for symbol, metadata in selected_models.items():
        prefix = metadata["prefix"]
        df = load_prediction_file(
            run_dir=run_dir,
            symbol=symbol,
            prefix=prefix,
            max_rows=max_rows_per_symbol,
        )

        if len(df) < max_rows_per_symbol:
            raise ValueError(
                f"{symbol} has fewer rows than requested: "
                f"{len(df)} < {max_rows_per_symbol}"
            )

        for idx, row in df.iterrows():
            action = float(row["Action"])
            signal = str(row["Signal"]).upper()
            confidence = abs(action)
            target_weight = action_to_target_weight(signal, action, confidence)
            timestamp = timestamps[idx]

            all_signals.append(
                {
                    "timestamp": timestamp.isoformat(),
                    "symbol": symbol,
                    "prefix": prefix,
                    "window": metadata["window"],
                    "scenario": metadata["scenario"],
                    "signal": signal,
                    "confidence": confidence,
                    "action": action,
                    "target_weight": target_weight,
                }
            )

    selected_model_prefixes = {
        symbol: metadata["prefix"]
        for symbol, metadata in selected_models.items()
    }

    payload = {
        "producer": "ppo_research_pipeline",
        "description": (
            "Precomputed market-hours dynamic PPO signals for selected "
            "execution-adjusted ticker set"
        ),
        "interval": "1h_market_bars",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "symbols": list(selected_models.keys()),
        "selected_models": selected_model_prefixes,
        "selection_metadata": selected_models,
        "selection_rule": (
            "Best selected-scenario row by Execution_Edge_vs_BuyHold from "
            "execution_realism_analysis.csv"
        ),
        "market_hours_utc": MARKET_HOURS_UTC,
        "rows_per_symbol": max_rows_per_symbol,
        "max_abs_weight": MAX_ABS_WEIGHT,
        "min_confidence": MIN_CONFIDENCE,
        "signals": all_signals,
    }

    return payload


def save_payload(payload: dict, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("w") as file:
        json.dump(payload, file, indent=2)

def sha256_file(path: Path) -> str:
    """Return SHA256 hash for a file."""
    digest = hashlib.sha256()

    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)

    return digest.hexdigest()


def build_manifest(
    payload: dict,
    output_path: Path,
    run_dir: Path,
    scenario: str,
    payload_sha256: str,
) -> dict:
    """Build a reproducibility manifest for an exported signal payload."""
    signals = pd.DataFrame(payload["signals"])

    manifest = {
        "producer": "ppo_research_pipeline",
        "artifact_type": "dynamic_signal_payload_manifest",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "source_run_dir": str(run_dir),
        "payload_path": str(output_path),
        "payload_sha256": payload_sha256,
        "scenario": scenario,
        "symbols": payload.get("symbols", []),
        "selected_models": payload.get("selected_models", {}),
        "selection_rule": payload.get("selection_rule"),
        "rows_per_symbol": payload.get("rows_per_symbol"),
        "signal_rows": int(len(signals)),
        "first_timestamp": str(signals["timestamp"].min()) if not signals.empty else None,
        "last_timestamp": str(signals["timestamp"].max()) if not signals.empty else None,
        "market_hours_utc": payload.get("market_hours_utc", []),
        "max_abs_weight": payload.get("max_abs_weight"),
        "min_confidence": payload.get("min_confidence"),
        "export_config": {
            "interval": payload.get("interval"),
            "rows_per_symbol": payload.get("rows_per_symbol"),
            "scenario": scenario,
        },
        "required_source_files": [
            "summary_test_mode.csv",
            "execution_realism_analysis.csv",
            "*_predictions_compat.csv",
        ],
    }

    return manifest


def manifest_path_for_payload(output_path: Path) -> Path:
    """Return sidecar manifest path for an exported payload."""
    return output_path.with_suffix(".manifest.json")


def save_manifest(manifest: dict, manifest_path: Path) -> None:
    """Save payload manifest JSON."""
    manifest_path.parent.mkdir(parents=True, exist_ok=True)

    with manifest_path.open("w") as file:
        json.dump(manifest, file, indent=2)

def print_summary(
    payload: dict,
    output_path: Path,
    run_dir: Path,
    manifest_path: Path | None = None,
) -> None:
    signals = pd.DataFrame(payload["signals"])

    print("=" * 80)
    print("SELECTED DYNAMIC LEAN SIGNAL EXPORT")
    print("=" * 80)
    print("Using training run:", run_dir)
    print("Saved dynamic LEAN signals to:", output_path)
    if manifest_path is not None:
        print("Saved payload manifest to:", manifest_path)
    print("Symbols:", payload["symbols"])
    print("Selected models:", payload["selected_models"])
    print("Signal rows:", len(signals))
    print("Rows per symbol:", payload["rows_per_symbol"])
    print("First timestamp:", signals["timestamp"].min())
    print("Last timestamp:", signals["timestamp"].max())

    print("\nSelection metadata:")
    metadata = pd.DataFrame(payload["selection_metadata"]).T
    print(metadata.to_string())

    print("\nSignal counts:")
    counts = signals.groupby(["symbol", "signal"]).size()
    print(counts)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export selected execution-adjusted PPO dynamic signals."
    )

    parser.add_argument(
        "--run-dir",
        type=Path,
        default=None,
        help=(
            "Optional PPO run directory containing summary_test_mode.csv, "
            "execution_realism_analysis.csv, and *_predictions_compat.csv files. "
            "If omitted, the newest run under reports/backtests is used."
        ),
    )

    parser.add_argument(
        "--symbols",
        type=str,
        default=",".join(DEFAULT_SYMBOLS),
        help="Comma-separated ticker list. Default: AAPL,PFE,UNH,XOM",
    )

    parser.add_argument(
        "--scenario",
        type=str,
        default="moderate",
        help="Execution realism scenario to use. Default: moderate",
    )

    parser.add_argument(
        "--rows",
        type=int,
        default=MAX_ROWS_PER_SYMBOL,
        help=f"Rows per symbol to export. Default: {MAX_ROWS_PER_SYMBOL}",
    )

    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help=f"Output JSON path. Default: {DEFAULT_OUTPUT_PATH}",
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()

    symbols = [
        item.strip().upper()
        for item in args.symbols.split(",")
        if item.strip()
    ]

    if not symbols:
        raise ValueError("No symbols provided.")

    run_dir = resolve_training_run(args.run_dir)
    execution = load_execution_realism(run_dir)

    selected_models = select_best_models(
        execution=execution,
        symbols=symbols,
        scenario=args.scenario,
    )

    payload = build_payload(
        run_dir=run_dir,
        selected_models=selected_models,
        max_rows_per_symbol=args.rows,
    )

    save_payload(payload, args.output)

    payload_sha256 = sha256_file(args.output)
    manifest_path = manifest_path_for_payload(args.output)
    manifest = build_manifest(
        payload=payload,
        output_path=args.output,
        run_dir=run_dir,
        scenario=args.scenario,
        payload_sha256=payload_sha256,
    )
    save_manifest(manifest, manifest_path)

    print_summary(payload, args.output, run_dir, manifest_path)


if __name__ == "__main__":
    main()