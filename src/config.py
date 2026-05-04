"""Configuration values for the PPO trading pipeline.

This module stores runtime settings, ticker lists, file paths, model artifact
locations, and PPO hyperparameter buckets. Paths are resolved through src.paths
so the project can run locally without Google Colab or Google Drive
dependencies.

Important:
    This file should not create timestamped run folders on import.
    Run-specific folders are created by train.py and predict.py when those
    scripts actually execute.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from src.paths import (
    BACKTESTS_DIR,
    PPO_MODELS_DIR,
    PROCESSED_DATA_DIR,
)

INTERVAL = "1h"
PERIOD_DAYS = 720

LOCAL_OUT = "multi_stock_feature_engineered_dataset.csv"
LOCAL_TRAIN = "train.csv"
LOCAL_VAL = "val.csv"

PARQ_FULL = "features_full.parquet"
PARQ_TRAIN = "train.parquet"
PARQ_VAL = "val.parquet"

DATA_PATH = PROCESSED_DATA_DIR / LOCAL_OUT
TRAIN_PATH = PROCESSED_DATA_DIR / LOCAL_TRAIN
VAL_PATH = PROCESSED_DATA_DIR / LOCAL_VAL

PARQUET_FULL_PATH = PROCESSED_DATA_DIR / PARQ_FULL
PARQUET_TRAIN_PATH = PROCESSED_DATA_DIR / PARQ_TRAIN
PARQUET_VAL_PATH = PROCESSED_DATA_DIR / PARQ_VAL

FWD_HORIZON = 10
UP_THR = 0.02
DN_THR = -0.02
VAL_FRACTION = 0.20

USE_SENTIMENT = False
USE_REGIME = True
ENABLE_SENTIMENT = False
ENABLE_SLO = True
ENABLE_WAVELET = True

LIVE_MODE = False
SIM_LATENCY_MS = 0
BROKER = "log"
ENABLE_PLOTS = False

TICKER_LIST = [
    "AAPL", "TSLA", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "BRK-B", "JPM", "JNJ",
    "XOM", "V", "PG", "UNH", "MA", "HD", "LLY", "MRK", "PEP", "KO",
    "BAC", "ABBV", "AVGO", "PFE", "COST", "CSCO", "TMO", "ABT", "ACN", "WMT",
    "MCD", "ADBE", "DHR", "CRM", "NKE", "INTC", "QCOM", "NEE", "AMD", "TXN",
    "AMGN", "UPS", "LIN", "PM", "UNP", "BMY", "LOW", "RTX", "CVX", "IBM",
    "GE", "SBUX", "ORCL",
]

TEST_MODE = True
TEST_TICKERS = ["AAPL"]

SYMBOLS = TEST_TICKERS if TEST_MODE else TICKER_LIST

WINDOW_SIZE = 3500
STEP_SIZE = 500
TIMESTEPS = 10_000
MIN_ROWS_BUFFER = 50
TOP_N_WINDOWS = 3

INITIAL_BALANCE = 100_000
TRANSACTION_COST = 0.0002
SLIPPAGE = 0.0003

RANDOM_SEED = 42
MAX_WORKERS = 1

MODEL_DIR = PPO_MODELS_DIR
FINAL_MODEL_DIR = PPO_MODELS_DIR

RESULTS_BASE_DIR = BACKTESTS_DIR
RESULTS_DIR = RESULTS_BASE_DIR

SUMMARY_PATH = RESULTS_BASE_DIR / "summary.csv"
SUMMARY_TEST_MODE_PATH = RESULTS_BASE_DIR / "summary_test_mode.csv"
SKIP_AGG_PATH = RESULTS_BASE_DIR / "skipped_windows_global.csv"


def make_run_tag() -> str:
    """Create a timestamp tag for a single training or prediction run."""
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def make_results_dir(
    run_tag: str | None = None,
    prefix: str = "ppo_walkforward_results",
) -> Path:
    """Create and return a timestamped results directory."""
    tag = run_tag or make_run_tag()
    results_dir = RESULTS_BASE_DIR / f"{prefix}_{tag}"
    results_dir.mkdir(parents=True, exist_ok=True)
    return results_dir

FAST = {
    "lr": 5e-5,
    "n_steps": 1024,
    "batch": 128,
    "clip": 0.25,
    "ent": 0.015,
}

SLOW = {
    "lr": 1.5e-5,
    "n_steps": 2048,
    "batch": 64,
    "clip": 0.16,
    "ent": 0.0075,
}

FAST_NAMES = {
    "TSLA", "NVDA", "AMD", "AVGO", "AAPL", "MSFT", "AMZN", "GOOGL", "META", "ADBE", "CRM",
    "INTC", "QCOM", "TXN", "ORCL", "NEE", "GE", "XOM", "CVX", "LLY", "NKE", "SBUX",
}

SLOW_NAMES = {
    "BRK-B", "JPM", "BAC", "JNJ", "UNH", "MRK", "PFE", "ABBV", "ABT", "AMGN", "PG", "PEP", "KO",
    "V", "MA", "WMT", "MCD", "TMO", "DHR", "ACN", "IBM", "LIN", "PM", "RTX", "UPS", "UNP", "COST", "HD", "LOW",
}


def pick_params(symbol: str) -> dict:
    """Return PPO hyperparameter bucket for a symbol."""
    return FAST if symbol in FAST_NAMES else SLOW