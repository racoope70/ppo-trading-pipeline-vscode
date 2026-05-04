"""Market data download utilities.

This module downloads OHLCV data from yfinance and normalizes the output
schema for downstream feature engineering. It contains no Google Colab,
Google Drive, notebook, training, or model-saving logic.
"""

from __future__ import annotations

import logging
import re
import time
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

from src.config import INTERVAL, PERIOD_DAYS, SYMBOLS
from src.paths import RAW_DATA_DIR


REQUIRED_OHLCV_COLUMNS = {"Open", "High", "Low", "Close", "Volume"}


def force_datetime_column(df: pd.DataFrame) -> pd.DataFrame:
    """Ensure a clean, sorted, tz-naive Datetime column exists."""
    data = df.copy()

    if isinstance(data.index, pd.DatetimeIndex):
        try:
            if data.index.tz is not None:
                data.index = data.index.tz_convert(None)
        except Exception:
            try:
                data.index = data.index.tz_localize(None)
            except Exception:
                pass

        data.index.name = "Datetime"
        data = data.reset_index()
    else:
        data = data.reset_index()
        first_col = data.columns[0]

        if np.issubdtype(data[first_col].dtype, np.datetime64):
            data = data.rename(columns={first_col: "Datetime"})
        elif "Date" in data.columns:
            data["Datetime"] = pd.to_datetime(data["Date"], errors="coerce")
        elif "Datetime" not in data.columns:
            data["Datetime"] = pd.to_datetime(data[first_col], errors="coerce")

    if "Datetime" not in data.columns:
        raise KeyError("Failed to construct Datetime column from yfinance output.")

    data["Datetime"] = pd.to_datetime(data["Datetime"], errors="coerce")
    data = data.dropna(subset=["Datetime"])
    data = data.drop_duplicates(subset=["Datetime"])
    data = data.sort_values("Datetime").reset_index(drop=True)

    return data


def normalize_ohlcv(df: pd.DataFrame, ticker: str) -> pd.DataFrame:
    """Normalize yfinance OHLCV columns to a stable schema."""
    data = df.copy()

    if isinstance(data.columns, pd.MultiIndex):
        flattened_cols = []
        for col in data.columns:
            parts = [str(part) for part in col if part is not None and str(part) != ""]
            flattened_cols.append(" ".join(parts))
        data.columns = flattened_cols

    data.columns = [re.sub(r"\s+", " ", str(col)).strip() for col in data.columns]

    ticker_pattern = ticker.upper().replace("-", "[- ]?")
    rename_candidates = {}

    for col in data.columns:
        col_upper = col.upper()
        cleaned = re.sub(rf"^(?:{ticker_pattern})[\s/_-]+", "", col_upper)
        cleaned = re.sub(rf"[\s/_-]+(?:{ticker_pattern})$", "", cleaned)
        cleaned = cleaned.title()
        rename_candidates[col] = cleaned

    if any(rename_candidates[col] != col for col in data.columns):
        data = data.rename(columns=rename_candidates)

    case_insensitive_cols = {col.lower(): col for col in data.columns}

    desired_columns = {
        "Open": ["open"],
        "High": ["high"],
        "Low": ["low"],
        "Close": ["close", "close*", "last"],
        "Adj Close": ["adj close", "adj_close", "adjclose", "adjusted close"],
        "Volume": ["volume", "vol"],
    }

    rename_map = {}

    for desired, aliases in desired_columns.items():
        if desired.lower() in case_insensitive_cols:
            rename_map[case_insensitive_cols[desired.lower()]] = desired
            continue

        for alias in aliases:
            if alias in case_insensitive_cols:
                rename_map[case_insensitive_cols[alias]] = desired
                break

    if rename_map:
        data = data.rename(columns=rename_map)

    return data


def validate_ohlcv_schema(df: pd.DataFrame, ticker: str) -> pd.DataFrame:
    """Validate required OHLCV columns and synthesize Adj Close if missing."""
    missing = REQUIRED_OHLCV_COLUMNS - set(df.columns)

    if missing:
        logging.debug("[%s] Columns received: %s", ticker, list(df.columns))
        raise ValueError(f"{ticker}: missing OHLCV columns after normalization: {missing}")

    data = df.copy()

    if "Adj Close" not in data.columns:
        data["Adj Close"] = data["Close"]

    return data


def postprocess_download(df: pd.DataFrame, ticker: str) -> pd.DataFrame:
    """Normalize, validate, and annotate a downloaded yfinance dataframe."""
    data = normalize_ohlcv(df, ticker)
    data = force_datetime_column(data)
    data = validate_ohlcv_schema(data, ticker)
    data["Symbol"] = ticker

    return data


def download_stock_data(
    ticker: str,
    interval: str = INTERVAL,
    period_days: int = PERIOD_DAYS,
    max_retries: int = 5,
    sleep_base: int = 3,
) -> pd.DataFrame | None:
    """Download one ticker from yfinance with a history() fallback."""
    period_str = f"{int(period_days)}d"

    for attempt in range(1, max_retries + 1):
        try:
            logging.info(
                "[%s] Attempt %s: yf.download(period=%s, interval=%s)",
                ticker,
                attempt,
                period_str,
                interval,
            )

            data = yf.download(
                tickers=ticker,
                period=period_str,
                interval=interval,
                progress=False,
                auto_adjust=False,
                group_by="column",
                threads=False,
                prepost=False,
                repair=True,
            )

            if data is None or data.empty:
                raise ValueError("Empty data from yf.download().")

            data = postprocess_download(data, ticker)

            logging.info(
                "[%s] Downloaded %s rows from %s to %s",
                ticker,
                len(data),
                data["Datetime"].min(),
                data["Datetime"].max(),
            )

            return data

        except Exception as download_error:
            logging.warning(
                "[%s] yf.download failed: %s | trying history() fallback",
                ticker,
                download_error,
            )

            try:
                history = yf.Ticker(ticker).history(
                    period=period_str,
                    interval=interval,
                    auto_adjust=False,
                    actions=False,
                )

                if history is None or history.empty:
                    raise ValueError("Empty data from history().")

                data = postprocess_download(history, ticker)

                logging.info(
                    "[%s] Fallback downloaded %s rows from %s to %s",
                    ticker,
                    len(data),
                    data["Datetime"].min(),
                    data["Datetime"].max(),
                )

                return data

            except Exception as history_error:
                wait_seconds = sleep_base * attempt
                logging.warning(
                    "[%s] history() failed: %s | retrying in %s seconds",
                    ticker,
                    history_error,
                    wait_seconds,
                )
                time.sleep(wait_seconds)

    logging.error("[%s] Failed to download after %s attempts.", ticker, max_retries)
    return None


def save_raw_symbol_data(
    df: pd.DataFrame,
    ticker: str,
    output_dir: Path = RAW_DATA_DIR,
) -> Path:
    """Save one ticker's raw normalized OHLCV data to CSV."""
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{ticker}_raw_ohlcv.csv"
    df.to_csv(output_path, index=False)
    return output_path


def download_symbols(
    symbols: list[str] | None = None,
    interval: str = INTERVAL,
    period_days: int = PERIOD_DAYS,
    save_raw: bool = True,
) -> dict[str, pd.DataFrame]:
    """Download multiple tickers and return a dictionary of dataframes."""
    symbols = symbols or SYMBOLS
    downloaded: dict[str, pd.DataFrame] = {}

    for idx, ticker in enumerate(symbols, start=1):
        logging.info("[%s/%s] Downloading %s", idx, len(symbols), ticker)

        data = download_stock_data(
            ticker=ticker,
            interval=interval,
            period_days=period_days,
        )

        if data is None or data.empty:
            logging.warning("[%s] No usable data returned.", ticker)
            continue

        downloaded[ticker] = data

        if save_raw:
            output_path = save_raw_symbol_data(data, ticker)
            logging.info("[%s] Saved raw data to %s", ticker, output_path)

        time.sleep(0.5)

    return downloaded


def main() -> None:
    """Command-line entry point for downloading raw market data."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        force=True,
    )

    logging.info("yfinance version: %s", getattr(yf, "__version__", "unknown"))
    logging.info("pandas version: %s", pd.__version__)

    downloaded = download_symbols()
    logging.info("Downloaded %s/%s symbols.", len(downloaded), len(SYMBOLS))


if __name__ == "__main__":
    main()