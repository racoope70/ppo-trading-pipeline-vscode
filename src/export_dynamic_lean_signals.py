"""Export precomputed UNH/XOM PPO signals into a LEAN-friendly JSON file.

This script does not retrain models and does not run live inference.
It converts saved *_predictions_compat.csv files into a dynamic signal file
that QuantConnect/LEAN can read from Object Store.

Output:
    quantconnect/test_payloads/unh_xom_dynamic_signals_250rows.json
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd


BACKTESTS_DIR = Path("reports/backtests")
OUTPUT_PATH = Path("quantconnect/test_payloads/unh_xom_dynamic_signals_250rows.json")

SELECTED_MODELS = {
    "UNH": "ppo_UNH_window1",
    "XOM": "ppo_XOM_window2",
}

LEAN_START_TIME = datetime(2026, 2, 10, 9, 30, tzinfo=timezone.utc)
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


def load_prediction_file(run_dir: Path, symbol: str, prefix: str) -> pd.DataFrame:
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

    return df.tail(MAX_ROWS_PER_SYMBOL).reset_index(drop=True)


def main() -> None:
    run_dir = find_latest_training_run()
    print("Using training run:", run_dir)

    all_signals = []

    for symbol, prefix in SELECTED_MODELS.items():
        df = load_prediction_file(run_dir, symbol, prefix)

        for idx, row in df.iterrows():
            action = float(row["Action"])
            signal = str(row["Signal"]).upper()
            confidence = abs(action)
            target_weight = action_to_target_weight(signal, action, confidence)

            timestamp = LEAN_START_TIME + timedelta(hours=idx)

            all_signals.append(
                {
                    "timestamp": timestamp.isoformat().replace("+00:00", "+00:00"),
                    "symbol": symbol,
                    "prefix": prefix,
                    "signal": signal,
                    "confidence": confidence,
                    "action": action,
                    "target_weight": target_weight,
                }
            )

    payload = {
        "producer": "ppo_research_pipeline",
        "description": "Precomputed dynamic PPO signals for UNH/XOM LEAN test",
        "interval": "1h",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "symbols": list(SELECTED_MODELS.keys()),
        "selected_models": SELECTED_MODELS,
        "max_abs_weight": MAX_ABS_WEIGHT,
        "min_confidence": MIN_CONFIDENCE,
        "signals": all_signals,
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    with OUTPUT_PATH.open("w") as file:
        json.dump(payload, file, indent=2)

    print("Saved dynamic LEAN signals to:", OUTPUT_PATH)
    print("Signal rows:", len(all_signals))
    print("First timestamp:", all_signals[0]["timestamp"])
    print("Last timestamp:", all_signals[-1]["timestamp"])

    counts = pd.DataFrame(all_signals).groupby(["symbol", "signal"]).size()
    print("\nSignal counts:")
    print(counts)


if __name__ == "__main__":
    main()