"""Prepare model-ready data for the PPO trading pipeline.

This script replaces the original Colab data-preparation block. It downloads
raw market data, computes features, applies labels, performs a time-based
train/validation split, and saves local CSV/parquet outputs.
"""

from __future__ import annotations

import gc
import logging
import time
import warnings

import pandas as pd
import yfinance as yf

from src.config import (
    DATA_PATH,
    INTERVAL,
    PARQUET_FULL_PATH,
    PARQUET_TRAIN_PATH,
    PARQUET_VAL_PATH,
    PERIOD_DAYS,
    SYMBOLS,
    TRAIN_PATH,
    USE_REGIME,
    USE_SENTIMENT,
    VAL_PATH,
)
from src.data_download import download_stock_data, save_raw_symbol_data
from src.features import (
    build_model_dataset,
    compute_enhanced_features,
    initialize_sentiment_pipeline,
    split_train_validation,
    summarize_dataset,
)


def prepare_feature_frames(
    symbols: list[str],
    interval: str = INTERVAL,
    period_days: int = PERIOD_DAYS,
) -> list[pd.DataFrame]:
    """Download raw bars and compute feature frames for all requested symbols."""
    feature_frames: list[pd.DataFrame] = []

    sentiment_pipeline = initialize_sentiment_pipeline(USE_SENTIMENT)

    for idx, ticker in enumerate(symbols, start=1):
        logging.info("[%s/%s] Processing %s", idx, len(symbols), ticker)

        raw = download_stock_data(
            ticker=ticker,
            interval=interval,
            period_days=period_days,
            max_retries=5,
            sleep_base=3,
        )

        if raw is None or raw.empty:
            logging.warning("[%s] No data returned.", ticker)
            continue

        try:
            save_raw_symbol_data(raw, ticker)

            features = compute_enhanced_features(
                raw,
                use_regime=USE_REGIME,
                use_sentiment=USE_SENTIMENT,
                sentiment_pipeline=sentiment_pipeline,
            )

            if features is not None and not features.empty:
                logging.info("[%s] Feature rows: %s", ticker, len(features))
                feature_frames.append(features)
            else:
                logging.warning("[%s] Feature set was empty.", ticker)

        except Exception as exc:
            logging.error("[%s] Feature engineering failed: %s", ticker, exc)

        finally:
            try:
                del raw
            except NameError:
                pass

            try:
                del features
            except NameError:
                pass

            gc.collect()
            time.sleep(0.5)

    return feature_frames


def save_processed_outputs(
    full_df: pd.DataFrame,
    train_df: pd.DataFrame,
    val_df: pd.DataFrame,
) -> None:
    """Save full/train/validation datasets to configured local paths."""
    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)

    full_df.to_csv(DATA_PATH, index=False)
    train_df.to_csv(TRAIN_PATH, index=False)
    val_df.to_csv(VAL_PATH, index=False)

    logging.info("Saved CSV: %s", DATA_PATH)
    logging.info("Saved CSV: %s", TRAIN_PATH)
    logging.info("Saved CSV: %s", VAL_PATH)

    full_df.to_parquet(PARQUET_FULL_PATH, index=False)
    train_df.to_parquet(PARQUET_TRAIN_PATH, index=False)
    val_df.to_parquet(PARQUET_VAL_PATH, index=False)

    logging.info("Saved Parquet: %s", PARQUET_FULL_PATH)
    logging.info("Saved Parquet: %s", PARQUET_TRAIN_PATH)
    logging.info("Saved Parquet: %s", PARQUET_VAL_PATH)


def main() -> None:
    """Run the full local data preparation pipeline."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        force=True,
    )

    warnings.filterwarnings("ignore", category=FutureWarning)

    logging.info("yfinance version: %s", getattr(yf, "__version__", "unknown"))
    logging.info("pandas version: %s", pd.__version__)
    logging.info("Preparing data for %s symbols.", len(SYMBOLS))

    feature_frames = prepare_feature_frames(SYMBOLS)

    if not feature_frames:
        logging.warning("No usable data found for any ticker.")
        return

    final_df = build_model_dataset(feature_frames)

    logging.info("Combined dataset shape: %s", final_df.shape)

    summarize_dataset(final_df)

    train_df, val_df = split_train_validation(final_df)

    save_processed_outputs(final_df, train_df, val_df)

    logging.info("Data preparation complete.")


if __name__ == "__main__":
    main()