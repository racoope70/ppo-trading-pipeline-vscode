"""Diagnostics for the PPO trading pipeline.

This module checks the local project setup, processed datasets, saved model
artifacts, reports, and latest prediction outputs. It does not download data,
train models, run inference, or place orders.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from src.artifacts import get_artifact_paths, list_model_prefixes
from src.config import (
    DATA_PATH,
    FINAL_MODEL_DIR,
    RESULTS_DIR,
    SYMBOLS,
    TEST_MODE,
    TIMESTEPS,
    WINDOW_SIZE,
    STEP_SIZE,
)
from src.paths import (
    BACKTESTS_DIR,
    DATA_DIR,
    FIGURES_DIR,
    LOGS_DIR,
    MODELS_DIR,
    PPO_MODELS_DIR,
    PROCESSED_DATA_DIR,
    RAW_DATA_DIR,
    REPORTS_DIR,
)


def print_section(title: str) -> None:
    """Print a simple section header."""
    print(f"\n{title}")
    print("-" * len(title))


def exists_label(path: Path) -> str:
    """Return a compact existence label."""
    return "OK" if path.exists() else "MISSING"


def has_report_outputs(path: Path) -> bool:
    """Return whether a report folder contains meaningful output files."""
    expected_files = [
        path / "summary.csv",
        path / "summary_test_mode.csv",
        path / "latest_predictions.csv",
    ]

    if any(file.exists() for file in expected_files):
        return True

    patterns = [
        "*_latest_signal.json",
        "*_predictions.csv",
        "*_predictions_compat.csv",
    ]

    return any(any(path.glob(pattern)) for pattern in patterns)


def get_latest_nonempty_report_dir() -> Path | None:
    """Return the newest report folder that contains generated outputs."""
    run_dirs = sorted(
        [
            path
            for path in BACKTESTS_DIR.glob("ppo_walkforward_results_*")
            if path.is_dir()
        ],
        reverse=True,
    )

    for path in run_dirs:
        if has_report_outputs(path):
            return path

    return None


def check_path(path: Path, label: str) -> bool:
    """Print whether a path exists."""
    exists = path.exists()
    print(f"{label}: {exists_label(path)} | {path}")
    return exists


def check_config() -> None:
    """Print important runtime configuration values."""
    print_section("Configuration")

    print(f"TEST_MODE: {TEST_MODE}")
    print(f"SYMBOLS: {SYMBOLS}")
    print(f"TIMESTEPS: {TIMESTEPS}")
    print(f"WINDOW_SIZE: {WINDOW_SIZE}")
    print(f"STEP_SIZE: {STEP_SIZE}")
    print(f"DATA_PATH: {DATA_PATH}")
    print(f"FINAL_MODEL_DIR: {FINAL_MODEL_DIR}")
    print(f"CURRENT RESULTS_DIR: {RESULTS_DIR}")


def check_project_paths() -> None:
    """Check expected project directories."""
    print_section("Project paths")

    paths = {
        "DATA_DIR": DATA_DIR,
        "RAW_DATA_DIR": RAW_DATA_DIR,
        "PROCESSED_DATA_DIR": PROCESSED_DATA_DIR,
        "MODELS_DIR": MODELS_DIR,
        "PPO_MODELS_DIR": PPO_MODELS_DIR,
        "REPORTS_DIR": REPORTS_DIR,
        "BACKTESTS_DIR": BACKTESTS_DIR,
        "FIGURES_DIR": FIGURES_DIR,
        "LOGS_DIR": LOGS_DIR,
    }

    for label, path in paths.items():
        check_path(path, label)


def check_processed_data() -> None:
    """Check prepared data files and summarize the main dataset."""
    print_section("Processed data")

    expected_files = [
        PROCESSED_DATA_DIR / "multi_stock_feature_engineered_dataset.csv",
        PROCESSED_DATA_DIR / "train.csv",
        PROCESSED_DATA_DIR / "val.csv",
        PROCESSED_DATA_DIR / "features_full.parquet",
        PROCESSED_DATA_DIR / "train.parquet",
        PROCESSED_DATA_DIR / "val.parquet",
    ]

    for path in expected_files:
        check_path(path, path.name)

    if not DATA_PATH.exists():
        print("Dataset summary skipped because DATA_PATH does not exist.")
        return

    try:
        df = pd.read_csv(DATA_PATH)

        print("\nDataset summary")
        print(f"Rows: {len(df):,}")
        print(f"Columns: {len(df.columns):,}")

        if "Symbol" in df.columns:
            print("\nSymbol counts")
            print(df["Symbol"].value_counts().to_string())

        if "Datetime" in df.columns:
            datetimes = pd.to_datetime(df["Datetime"], utc=True, errors="coerce")
            print(f"\nDatetime range: {datetimes.min()} to {datetimes.max()}")

        if "Target" in df.columns:
            print("\nTarget counts")
            print(df["Target"].value_counts().sort_index().to_string())

    except Exception as exc:
        print(f"Could not summarize processed dataset: {exc}")


def check_model_artifacts() -> None:
    """Check saved PPO model artifacts."""
    print_section("Model artifacts")

    check_path(FINAL_MODEL_DIR, "FINAL_MODEL_DIR")

    prefixes = list_model_prefixes(FINAL_MODEL_DIR)

    if not prefixes:
        print("No PPO model prefixes found.")
        return

    print(f"Model prefixes found: {len(prefixes)}")
    for prefix in prefixes:
        print(f"  {prefix}")

    print("\nArtifact completeness")

    for prefix in prefixes:
        paths = get_artifact_paths(prefix, FINAL_MODEL_DIR)

        required = {
            "model": paths.model_path,
            "vecnorm": paths.vecnorm_path,
            "features": paths.features_path,
            "probability_config": paths.probability_config_path,
            "model_info": paths.model_info_path,
        }

        missing = [name for name, path in required.items() if not path.exists()]

        if missing:
            print(f"{prefix}: MISSING {missing}")
        else:
            print(f"{prefix}: COMPLETE")


def check_reports() -> None:
    """Check generated report and backtest outputs."""
    print_section("Reports")

    check_path(BACKTESTS_DIR, "BACKTESTS_DIR")

    latest = get_latest_nonempty_report_dir()

    if latest is None:
        print("No non-empty walk-forward report folders found.")
        return

    print(f"Latest non-empty report folder: {latest}")

    csv_files = sorted(latest.glob("*.csv"))
    json_files = sorted(latest.glob("*.json"))

    print(f"CSV files found: {len(csv_files)}")
    for path in csv_files[:10]:
        print(f"  {path.name}")

    if len(csv_files) > 10:
        print(f"  ... {len(csv_files) - 10} more CSV files")

    print(f"JSON files found: {len(json_files)}")
    for path in json_files[:10]:
        print(f"  {path.name}")

    print("\nKey report files")
    for path in [
        latest / "summary.csv",
        latest / "summary_test_mode.csv",
        latest / "latest_predictions.csv",
    ]:
        check_path(path, path.name)


def inspect_latest_signal() -> None:
    """Print the latest saved prediction signal if available."""
    print_section("Latest signal")

    latest = get_latest_nonempty_report_dir()

    if latest is None:
        print("No non-empty walk-forward report folders found.")
        return

    print(f"Latest non-empty report folder: {latest}")
    signal_files = sorted(latest.glob("*_latest_signal.json"), reverse=True)

    if not signal_files:
        print("No latest signal JSON files found.")
        return

    signal_path = signal_files[0]
    print(f"Signal file: {signal_path}")

    try:
        with signal_path.open("r") as file:
            payload = json.load(file)

        keys = [
            "symbol",
            "prefix",
            "timestamp",
            "price",
            "signal",
            "confidence",
            "action",
            "p_long",
            "p_short",
            "created_at_utc",
        ]

        for key in keys:
            if key in payload:
                print(f"{key}: {payload[key]}")

    except Exception as exc:
        print(f"Could not read signal JSON: {exc}")


def aggregate_run_summaries(
    output_path: Path | None = None,
) -> Path | None:
    """Aggregate summary CSV files across all walk-forward result folders."""
    print_section("Summary aggregation")

    output_path = output_path or (BACKTESTS_DIR / "all_runs_summary.csv")

    summary_files = sorted(BACKTESTS_DIR.glob("ppo_walkforward_results_*/summary*.csv"))

    if not summary_files:
        print("No summary CSV files found.")
        return None

    frames = []

    for path in summary_files:
        try:
            frame = pd.read_csv(path)
            frame["RunFolder"] = str(path.parent)
            frame["SummaryFile"] = path.name
            frames.append(frame)
        except Exception as exc:
            print(f"Could not read {path}: {exc}")

    if not frames:
        print("No readable summary files found.")
        return None

    combined = pd.concat(frames, ignore_index=True)

    if {"Ticker", "Window"}.issubset(combined.columns):
        combined = combined.drop_duplicates(
            subset=["Ticker", "Window"],
            keep="last",
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    combined.to_csv(output_path, index=False)

    print(f"Saved aggregated summary: {output_path}")
    print(f"Rows: {len(combined):,}")

    return output_path


def main() -> None:
    """Run project diagnostics."""
    print("\nPPO Pipeline Diagnostics")
    print("=" * 80)

    check_config()
    check_project_paths()
    check_processed_data()
    check_model_artifacts()
    check_reports()
    inspect_latest_signal()
    aggregate_run_summaries()

    print("\nDiagnostics complete.")


if __name__ == "__main__":
    main()