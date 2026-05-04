"""Feature engineering utilities for the PPO trading pipeline.

This module converts normalized OHLCV data into model-ready features,
labels, and train/validation splits. It is designed to be deterministic
and independent of Google Colab or Google Drive.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd
import pywt

from src.config import (
    DN_THR,
    FWD_HORIZON,
    UP_THR,
    USE_REGIME,
    USE_SENTIMENT,
    VAL_FRACTION,
)


def denoise_wavelet(
    series: pd.Series,
    wavelet: str = "db1",
    level: int = 2,
) -> pd.Series:
    """Apply simple wavelet denoising to a price series."""
    clean_series = pd.Series(series).astype(float).ffill().bfill()
    values = clean_series.to_numpy(copy=True)

    try:
        coeffs = pywt.wavedec(values, wavelet, mode="symmetric", level=level)

        for idx in range(1, len(coeffs)):
            coeffs[idx] = np.zeros_like(coeffs[idx])

        reconstructed = pywt.waverec(coeffs, wavelet, mode="symmetric")
        return pd.Series(reconstructed[: len(values)], index=series.index)

    except Exception as exc:
        logging.warning("Wavelet denoising failed (%s); using raw values.", exc)
        return pd.Series(values, index=series.index)


def initialize_sentiment_pipeline(use_sentiment: bool = USE_SENTIMENT):
    """Initialize FinBERT sentiment pipeline when enabled.

    Sentiment is optional. The pipeline is loaded lazily to keep the default
    local workflow lightweight.
    """
    if not use_sentiment:
        return None

    try:
        import torch
        from transformers import pipeline

        device_id = 0 if torch.cuda.is_available() else -1
        sentiment_pipeline = pipeline(
            "sentiment-analysis",
            model="ProsusAI/finbert",
            device=device_id,
        )

        logging.info("FinBERT sentiment enabled.")
        return sentiment_pipeline

    except Exception as exc:
        logging.warning("Could not initialize FinBERT. Sentiment disabled. Error: %s", exc)
        return None


def score_sentiment(
    texts: list[str],
    sentiment_pipeline=None,
) -> list[float]:
    """Score sentiment text as positive, negative, or neutral values."""
    if sentiment_pipeline is None:
        return [0.0] * len(texts)

    try:
        outputs = sentiment_pipeline(
            texts,
            truncation=True,
            max_length=256,
            batch_size=32,
        )

        scores = []

        for result in outputs:
            label = result["label"].lower()
            score = float(result["score"])

            if label == "positive":
                scores.append(score)
            elif label == "negative":
                scores.append(-score)
            else:
                scores.append(0.0)

        return scores

    except Exception as exc:
        logging.error("Sentiment scoring error: %s", exc)
        return [0.0] * len(texts)


def add_regime_features(df: pd.DataFrame) -> pd.DataFrame:
    """Add a simple volatility/trend regime classification."""
    data = df.copy()

    data["Vol20"] = data["Close"].pct_change().rolling(20).std()
    data["Ret20"] = data["Close"].pct_change(20)

    vol_high = (data["Vol20"] > data["Vol20"].median()).astype(int)
    trend_high = (data["Ret20"].abs() > data["Ret20"].abs().median()).astype(int)

    data["Regime4"] = vol_high * 2 + trend_high

    return data


def compute_enhanced_features(
    df: pd.DataFrame,
    use_regime: bool = USE_REGIME,
    use_sentiment: bool = USE_SENTIMENT,
    sentiment_pipeline=None,
) -> pd.DataFrame:
    """Compute technical, denoised, regime, sentiment, and proxy Greek features."""
    data = df.copy()

    if isinstance(data.columns, pd.MultiIndex):
        data.columns = data.columns.get_level_values(0)

    data = data.loc[:, ~data.columns.duplicated()]

    required_cols = {"Open", "High", "Low", "Close", "Volume", "Symbol"}
    missing = required_cols - set(data.columns)

    if missing:
        raise ValueError(f"Missing required columns for feature engineering: {missing}")

    data["SMA_20"] = data["Close"].rolling(20).mean()
    data["STD_20"] = data["Close"].rolling(20).std()
    data["Upper_Band"] = data["SMA_20"] + 2 * data["STD_20"]
    data["Lower_Band"] = data["SMA_20"] - 2 * data["STD_20"]

    data["Lowest_Low"] = data["Low"].rolling(14).min()
    data["Highest_High"] = data["High"].rolling(14).max()
    stoch_denom = (data["Highest_High"] - data["Lowest_Low"]).replace(0, np.nan)
    data["Stoch"] = ((data["Close"] - data["Lowest_Low"]) / stoch_denom) * 100

    data["ROC"] = data["Close"].pct_change(10)
    data["OBV"] = (
        np.sign(data["Close"].diff()).fillna(0) * data["Volume"].fillna(0)
    ).cumsum()

    typical_price = (data["High"] + data["Low"] + data["Close"]) / 3
    sma_typical_price = typical_price.rolling(20).mean()
    mean_deviation = (typical_price - sma_typical_price).abs().rolling(20).mean()
    data["CCI"] = (typical_price - sma_typical_price) / (0.015 * mean_deviation)

    data["EMA_10"] = data["Close"].ewm(span=10, adjust=False).mean()
    data["EMA_50"] = data["Close"].ewm(span=50, adjust=False).mean()

    ema_12 = data["Close"].ewm(span=12, adjust=False).mean()
    ema_26 = data["Close"].ewm(span=26, adjust=False).mean()
    data["MACD_Line"] = ema_12 - ema_26
    data["MACD_Signal"] = data["MACD_Line"].ewm(span=9, adjust=False).mean()

    delta = data["Close"].diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / loss.replace(0, np.nan)
    data["RSI"] = 100 - (100 / (1 + rs))

    true_range = pd.concat(
        [
            data["High"] - data["Low"],
            (data["High"] - data["Close"].shift()).abs(),
            (data["Low"] - data["Close"].shift()).abs(),
        ],
        axis=1,
    ).max(axis=1)

    data["ATR"] = true_range.rolling(14).mean()
    data["Volatility"] = data["Close"].pct_change().rolling(20).std()

    data["Denoised_Close"] = denoise_wavelet(data["Close"].ffill())

    if use_regime:
        data = add_regime_features(data)

    if use_sentiment and len(data):
        headline = f"{data['Symbol'].iloc[0]} is expected to perform well in the market."
        score = score_sentiment([headline], sentiment_pipeline=sentiment_pipeline)[0]
        data["SentimentScore"] = float(score)
    else:
        data["SentimentScore"] = 0.0

    data["Delta"] = data["Close"].pct_change(1).fillna(0)
    data["Gamma"] = data["Delta"].diff().fillna(0)

    data = data.dropna().reset_index(drop=True)

    ordered_cols = [col for col in data.columns if col != "Symbol"] + ["Symbol"]

    return data[ordered_cols]


def filter_regular_trading_hours(df: pd.DataFrame) -> pd.DataFrame:
    """Keep only regular U.S. market hours: Monday-Friday, 09:30-16:00 New York."""
    data = df.copy()

    data["Datetime"] = pd.to_datetime(data["Datetime"], utc=True).dt.tz_convert(
        "America/New_York"
    )

    dt = data["Datetime"]

    regular_hours_mask = (
        (dt.dt.weekday < 5)
        & (dt.dt.time >= pd.to_datetime("09:30").time())
        & (dt.dt.time < pd.to_datetime("16:00").time())
    )

    return data[regular_hours_mask].reset_index(drop=True)


def relabel_targets(
    df: pd.DataFrame,
    forward_horizon: int = FWD_HORIZON,
    up_threshold: float = UP_THR,
    down_threshold: float = DN_THR,
) -> pd.DataFrame:
    """Create future return and -1/0/1 target labels."""
    data = df.copy()

    data["Return"] = (data["Close"].shift(-forward_horizon) - data["Close"]) / data[
        "Close"
    ]

    data["Target"] = np.select(
        [
            data["Return"] > up_threshold,
            data["Return"] < down_threshold,
        ],
        [
            1,
            -1,
        ],
        default=0,
    )

    return data


def remove_unusable_forward_horizon_rows(
    df: pd.DataFrame,
    forward_horizon: int = FWD_HORIZON,
) -> pd.DataFrame:
    """Remove final rows per symbol where forward return cannot be known."""
    data = df.copy()

    data = data.sort_values(["Symbol", "Datetime"]).reset_index(drop=True)
    data["__row_id"] = data.groupby("Symbol").cumcount()
    data["__row_count"] = data.groupby("Symbol")["__row_id"].transform("max") + 1

    data = data[data["__row_id"] < data["__row_count"] - forward_horizon].copy()
    data = data.drop(columns=["__row_id", "__row_count"]).reset_index(drop=True)

    return data


def clean_feature_rows(df: pd.DataFrame) -> pd.DataFrame:
    """Drop rows with missing feature values after labeling."""
    data = df.copy()

    feature_cols = [
        col
        for col in data.columns
        if col not in ["Target", "Return", "Symbol", "Datetime"]
    ]

    data = data.dropna(subset=feature_cols).reset_index(drop=True)

    ordered_last = ["Target", "Return", "Symbol"]
    ordered_cols = [col for col in data.columns if col not in ordered_last] + ordered_last

    return data[ordered_cols]


def summarize_dataset(df: pd.DataFrame) -> None:
    """Print a compact dataset quality summary."""
    print("Combined dataset shape:", df.shape)
    print("Range:", df["Datetime"].min(), "-", df["Datetime"].max())
    print("Per-ticker counts:")
    print(df["Symbol"].value_counts().to_string())

    na_cols = df.columns[df.isna().any()]

    if len(na_cols):
        print("\nColumns with NaNs:")
        print(df[na_cols].isna().sum().sort_values(ascending=False).to_string())
    else:
        print("\nNo NaNs detected.")

    print("\nLabel counts:")
    print(df["Target"].value_counts().sort_index().to_string())

    print("\nLabel ratios (%):")
    print((df["Target"].value_counts(normalize=True) * 100).round(2).to_string())


def split_train_validation(
    df: pd.DataFrame,
    validation_fraction: float = VAL_FRACTION,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Split data by time into train and validation sets."""
    if not 0 < validation_fraction < 1:
        raise ValueError("validation_fraction must be between 0 and 1.")

    data = df.sort_values("Datetime").reset_index(drop=True)

    cutoff_idx = int((1.0 - validation_fraction) * len(data))

    if cutoff_idx <= 0 or cutoff_idx >= len(data):
        raise ValueError("Invalid validation split index. Check dataset size.")

    cutoff_time = data.loc[cutoff_idx, "Datetime"]

    train_df = data[data["Datetime"] < cutoff_time].reset_index(drop=True)
    val_df = data[data["Datetime"] >= cutoff_time].reset_index(drop=True)

    print(f"\nTime split cutoff @ {cutoff_time}")
    print(f"Train: {train_df.shape}, Val: {val_df.shape}")

    return train_df, val_df


def build_model_dataset(feature_frames: list[pd.DataFrame]) -> pd.DataFrame:
    """Combine per-symbol feature frames and prepare final model dataset."""
    if not feature_frames:
        raise ValueError("No feature frames were provided.")

    data = pd.concat(feature_frames, ignore_index=True)

    if "Repaired?" in data.columns:
        data = data.drop(columns=["Repaired?"])

    data = filter_regular_trading_hours(data)
    data = relabel_targets(data)
    data = remove_unusable_forward_horizon_rows(data)
    data = clean_feature_rows(data)

    return data