"""Training utilities for the PPO walk-forward pipeline.

This module contains reusable helper functions used by training and
evaluation scripts. It intentionally excludes environment definitions,
model artifact saving, live prediction, and broker execution logic.
"""

from __future__ import annotations

import csv
import logging
from pathlib import Path
from threading import Lock

import pandas as pd
import torch

from src.config import SKIP_AGG_PATH


_SKIP_LOCK = Lock()


def get_mu_sigma(model, obs) -> tuple[float, float]:
    """Return Gaussian policy mean and standard deviation for continuous actions.

    This is useful for diagnostics when using Stable-Baselines3 PPO with a
    continuous action space. The values approximate the model's action
    distribution before deterministic action selection.

    Parameters
    ----------
    model:
        A trained Stable-Baselines3 PPO model.

    obs:
        Observation returned by the vectorized environment.

    Returns
    -------
    tuple[float, float]
        The policy mean and standard deviation.
    """
    with torch.no_grad():
        obs_tensor, _ = model.policy.obs_to_tensor(obs)
        features = model.policy.extract_features(obs_tensor)
        latent_pi, _ = model.policy.mlp_extractor(features)
        mean_actions = model.policy.action_net(latent_pi)
        log_std = model.policy.log_std

        mu = float(mean_actions.detach().cpu().numpy().squeeze())
        sigma = float(log_std.exp().detach().cpu().numpy().squeeze())

    return mu, sigma


def get_walk_forward_windows(
    df: pd.DataFrame,
    window_size: int,
    step_size: int,
    min_len: int = 1200,
) -> list[tuple[int, int]]:
    """Create rolling walk-forward windows.

    Parameters
    ----------
    df:
        Ticker-specific dataframe sorted by time.

    window_size:
        Number of rows in each training/evaluation window.

    step_size:
        Number of rows to move forward between windows.

    min_len:
        Minimum trailing length required to consider a window.

    Returns
    -------
    list[tuple[int, int]]
        List of `(start, end)` row-index windows.
    """
    if window_size <= 0:
        raise ValueError("window_size must be positive.")

    if step_size <= 0:
        raise ValueError("step_size must be positive.")

    if min_len <= 0:
        raise ValueError("min_len must be positive.")

    if df.empty:
        return []

    windows = [
        (start, start + window_size)
        for start in range(0, len(df) - min_len, step_size)
        if start + window_size < len(df)
    ]

    return windows


def record_skips_global(
    ticker: str,
    skipped_windows: list[str],
    total_windows: int | None = None,
    fully_skipped: bool = False,
    output_path: Path = SKIP_AGG_PATH,
) -> None:
    """Append skipped walk-forward windows to the global skip log.

    This helps resume interrupted training runs without losing visibility
    into which ticker/window combinations were skipped because artifacts
    already existed.

    Parameters
    ----------
    ticker:
        Stock symbol being processed.

    skipped_windows:
        Window names such as ``AAPL_window3``.

    total_windows:
        Total number of available windows for the ticker.

    fully_skipped:
        Whether every window for the ticker was skipped.

    output_path:
        CSV path for the skip log.
    """
    if not skipped_windows and not fully_skipped:
        return

    output_path.parent.mkdir(parents=True, exist_ok=True)

    with _SKIP_LOCK:
        new_file = not output_path.exists()

        with output_path.open("a", newline="") as file:
            writer = csv.writer(file)

            if new_file:
                writer.writerow(["Ticker", "Window", "FullySkipped", "TotalWindows"])

            if fully_skipped:
                writer.writerow(
                    [
                        ticker,
                        "ALL",
                        True,
                        total_windows if total_windows is not None else "",
                    ]
                )
                return

            for window_name in skipped_windows:
                window_number = _parse_window_number(window_name)
                writer.writerow(
                    [
                        ticker,
                        window_number,
                        False,
                        total_windows if total_windows is not None else "",
                    ]
                )


def _parse_window_number(window_name: str) -> int | str:
    """Extract window number from names like AAPL_window3."""
    try:
        _, window_str = window_name.split("_window")
        return int(window_str)
    except Exception:
        logging.debug("Could not parse window number from %s", window_name)
        return ""


def summarize_skip_log(path: Path = SKIP_AGG_PATH) -> None:
    """Log a compact summary of skipped walk-forward windows."""
    if not path.exists():
        logging.info("No skip log found at %s", path)
        return

    try:
        recap = pd.read_csv(path)

        fully_skipped_mask = recap["FullySkipped"].astype(str).str.lower().isin(
            ["true", "1", "yes"]
        )

        recap["FullySkipped"] = fully_skipped_mask

        fully_skipped_tickers = (
            recap.loc[recap["FullySkipped"], "Ticker"]
            .dropna()
            .unique()
            .tolist()
        )

        if fully_skipped_tickers:
            logging.info(
                "Fully skipped tickers: %s",
                ", ".join(fully_skipped_tickers),
            )

        partially_skipped = recap[~recap["FullySkipped"]]

        if not partially_skipped.empty:
            counts = (
                partially_skipped.groupby("Ticker")["Window"]
                .count()
                .sort_values(ascending=False)
            )

            logging.info("Partially skipped window counts per ticker:")

            for ticker, count in counts.items():
                logging.info("  - %s: %s window(s) already complete", ticker, count)

        logging.info("Global skip log: %s", path)

    except Exception as exc:
        logging.warning("Could not summarize skip log: %s", exc)