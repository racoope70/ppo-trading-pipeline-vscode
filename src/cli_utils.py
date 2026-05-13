"""Shared CLI helpers for PPO research scripts."""

from __future__ import annotations


def parse_ticker_args(raw_tickers: list[str] | None) -> list[str] | None:
    """Parse ticker CLI inputs into a clean uppercase ticker list.

    Supports both formats:
        --tickers AAPL PFE UNH
        --tickers AAPL,PFE,UNH

    Returns:
        None if no tickers were provided.
    """
    if not raw_tickers:
        return None

    parsed: list[str] = []

    for item in raw_tickers:
        if item is None:
            continue

        for token in str(item).split(","):
            ticker = token.strip().upper()

            if ticker:
                parsed.append(ticker)

    # Preserve order while removing duplicates.
    output: list[str] = []
    seen: set[str] = set()

    for ticker in parsed:
        if ticker not in seen:
            output.append(ticker)
            seen.add(ticker)

    return output or None