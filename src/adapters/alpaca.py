"""Alpaca adapter utilities.

This module contains stable Alpaca API helpers used by future paper/live
trading scripts. It intentionally does not contain the full paper-trading
live loop yet because that logic is still being tuned.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd
from dotenv import load_dotenv

from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest, StockLatestTradeRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderSide, QueryOrderStatus, TimeInForce
from alpaca.trading.requests import GetOrdersRequest, MarketOrderRequest


def load_environment(env_path: str | Path = ".env") -> None:
    """Load local environment variables from .env if available."""
    path = Path(env_path)

    if path.exists():
        load_dotenv(path, override=True)
    else:
        load_dotenv(override=True)


def resolve_alpaca_credentials() -> tuple[str, str, str]:
    """Resolve Alpaca credentials from environment variables."""
    api_key = (
        os.getenv("ALPACA_API_KEY")
        or os.getenv("ALPACA_API_KEY_ID")
        or os.getenv("APCA_API_KEY_ID")
        or ""
    ).strip()

    api_secret = (
        os.getenv("ALPACA_SECRET_KEY")
        or os.getenv("ALPACA_API_SECRET_KEY")
        or os.getenv("APCA_API_SECRET_KEY")
        or ""
    ).strip()

    base_url = (
        os.getenv("APCA_API_BASE_URL")
        or "https://paper-api.alpaca.markets"
    ).strip()

    if not api_key or not api_secret:
        raise RuntimeError(
            "Missing Alpaca credentials. Expected one of: "
            "ALPACA_API_KEY / ALPACA_SECRET_KEY, "
            "ALPACA_API_KEY_ID / ALPACA_API_SECRET_KEY, or "
            "APCA_API_KEY_ID / APCA_API_SECRET_KEY."
        )

    return api_key, api_secret, base_url


def create_alpaca_clients(
    env_path: str | Path = ".env",
    require_paper: bool = True,
) -> tuple[TradingClient, StockHistoricalDataClient]:
    """Create Alpaca trading and historical data clients."""
    load_environment(env_path)

    api_key, api_secret, base_url = resolve_alpaca_credentials()

    if require_paper and "paper-api" not in base_url.lower():
        raise RuntimeError(
            f"Refusing to initialize non-paper Alpaca endpoint: {base_url}"
        )

    trading_client = TradingClient(
        api_key,
        api_secret,
        paper=True,
        url_override=base_url,
    )

    data_client = StockHistoricalDataClient(api_key, api_secret)

    return trading_client, data_client


def get_account_snapshot(trading_client: TradingClient) -> dict[str, Any]:
    """Return a compact Alpaca account snapshot."""
    account = trading_client.get_account()

    return {
        "status": str(getattr(account, "status", "")),
        "equity": float(getattr(account, "equity", 0.0)),
        "cash": float(getattr(account, "cash", 0.0)),
        "buying_power": float(getattr(account, "buying_power", 0.0)),
        "trading_blocked": bool(getattr(account, "trading_blocked", False)),
        "shorting_enabled": bool(getattr(account, "shorting_enabled", False)),
    }


def assert_account_ready(trading_client: TradingClient) -> None:
    """Raise if the Alpaca account is not ready for paper trading."""
    snapshot = get_account_snapshot(trading_client)

    if snapshot["trading_blocked"]:
        raise RuntimeError(f"Trading is blocked. Account snapshot: {snapshot}")

    logging.info(
        "Alpaca account ready | status=%s | equity=%.2f | cash=%.2f | shorting=%s",
        snapshot["status"],
        snapshot["equity"],
        snapshot["cash"],
        snapshot["shorting_enabled"],
    )


def normalize_timeframe(value: str) -> TimeFrame:
    """Convert common string intervals into Alpaca TimeFrame objects."""
    key = str(value).strip().lower().replace(" ", "")

    if key in {"1h", "1hr", "60min", "1hour"}:
        return TimeFrame.Hour

    if key in {"1d", "1day", "day"}:
        return TimeFrame.Day

    if key in {"15m", "15min"}:
        return TimeFrame(15, "Min")

    if key in {"5m", "5min"}:
        return TimeFrame(5, "Min")

    raise ValueError(f"Unsupported Alpaca timeframe: {value}")


def get_latest_price(
    trading_client: TradingClient,
    data_client: StockHistoricalDataClient,
    symbol: str,
) -> float:
    """Return the latest trade price, falling back to position price if needed."""
    symbol = symbol.upper()

    try:
        request = StockLatestTradeRequest(symbol_or_symbols=symbol)
        response = data_client.get_stock_latest_trade(request)
        trade = response.get(symbol)

        if trade is not None:
            return float(trade.price)

    except Exception as error:
        logging.warning("[%s] latest trade lookup failed: %s", symbol, error)

    try:
        position = trading_client.get_open_position(symbol)
        return float(getattr(position, "current_price", None) or getattr(position, "avg_entry_price"))
    except Exception:
        return float("nan")


def get_recent_bars(
    data_client: StockHistoricalDataClient,
    symbol: str,
    limit: int = 200,
    timeframe: str | TimeFrame = "1h",
    feed: str | None = None,
) -> pd.DataFrame:
    """Fetch recent OHLCV bars from Alpaca."""
    symbol = symbol.upper()
    tf = normalize_timeframe(timeframe) if isinstance(timeframe, str) else timeframe
    feed = feed or os.getenv("BARS_FEED", "").strip() or None

    request = StockBarsRequest(
        symbol_or_symbols=symbol,
        timeframe=tf,
        limit=int(limit),
        feed=feed,
    )

    response = data_client.get_stock_bars(request)

    if not hasattr(response, "df"):
        return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])

    df = response.df.copy()

    if df.empty:
        return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])

    if isinstance(df.index, pd.MultiIndex):
        try:
            df = df.xs(symbol, level=0)
        except Exception:
            df = df.reset_index(level=0, drop=True)

    df.index = pd.to_datetime(df.index, utc=True, errors="coerce")

    df = df.rename(
        columns={
            "open": "Open",
            "high": "High",
            "low": "Low",
            "close": "Close",
            "volume": "Volume",
        }
    )

    columns = [col for col in ["Open", "High", "Low", "Close", "Volume"] if col in df.columns]

    return df[columns].sort_index().dropna(how="all")


def get_open_position_qty(trading_client: TradingClient, symbol: str) -> float:
    """Return current open position quantity, or zero if flat."""
    try:
        position = trading_client.get_open_position(symbol.upper())
        return float(getattr(position, "qty", 0.0) or 0.0)
    except Exception:
        return 0.0


def get_positions_snapshot(trading_client: TradingClient) -> pd.DataFrame:
    """Return all open Alpaca positions as a dataframe."""
    try:
        positions = trading_client.get_all_positions()
    except Exception:
        positions = []

    rows = []

    for position in positions or []:
        rows.append(
            {
                "symbol": str(getattr(position, "symbol", "")).upper(),
                "qty": float(getattr(position, "qty", 0.0) or 0.0),
                "market_value": float(getattr(position, "market_value", 0.0) or 0.0),
                "avg_entry_price": float(getattr(position, "avg_entry_price", 0.0) or 0.0),
                "current_price": float(getattr(position, "current_price", 0.0) or 0.0),
                "unrealized_plpc": float(getattr(position, "unrealized_plpc", 0.0) or 0.0),
            }
        )

    return pd.DataFrame(rows)


def list_open_orders(
    trading_client: TradingClient,
    symbols: list[str] | None = None,
):
    """List open Alpaca orders, optionally filtered by symbols."""
    symbol_filter = [symbol.upper() for symbol in symbols] if symbols else None

    request = GetOrdersRequest(
        status=QueryOrderStatus.OPEN,
        symbols=symbol_filter,
    )

    try:
        return trading_client.get_orders(filter=request) or []
    except Exception:
        return []


def cancel_open_orders(
    trading_client: TradingClient,
    symbols: list[str] | None = None,
) -> int:
    """Cancel open Alpaca orders. Returns number of cancel attempts."""
    orders = list_open_orders(trading_client, symbols=symbols)
    cancelled = 0

    for order in orders:
        order_id = getattr(order, "id", None)
        symbol = str(getattr(order, "symbol", "")).upper()

        if not order_id:
            continue

        try:
            trading_client.cancel_order_by_id(order_id)
            cancelled += 1
            logging.info("[%s] canceled open order id=%s", symbol, order_id)
        except Exception as error:
            logging.warning("[%s] cancel failed for order id=%s: %s", symbol, order_id, error)

    return cancelled


def submit_market_order(
    trading_client: TradingClient,
    symbol: str,
    side: str,
    qty: float,
    time_in_force: TimeInForce = TimeInForce.DAY,
    dry_run: bool = False,
):
    """Submit a market order, or log the action in dry-run mode."""
    symbol = symbol.upper()
    side_key = side.strip().lower()

    if side_key == "buy":
        order_side = OrderSide.BUY
    elif side_key == "sell":
        order_side = OrderSide.SELL
    else:
        raise ValueError(f"Unsupported order side: {side}")

    qty = float(qty)

    if qty <= 0:
        raise ValueError(f"Order quantity must be positive. Got {qty}")

    if dry_run:
        logging.info("[DRY_RUN] would submit %s %s qty=%s", side_key, symbol, qty)
        return None

    request = MarketOrderRequest(
        symbol=symbol,
        side=order_side,
        qty=qty,
        time_in_force=time_in_force,
    )

    order = trading_client.submit_order(request)

    logging.info(
        "[%s] submitted %s market order qty=%s id=%s",
        symbol,
        side_key,
        qty,
        getattr(order, "id", ""),
    )

    return order


def flatten_symbol(
    trading_client: TradingClient,
    symbol: str,
    dry_run: bool = False,
):
    """Close an existing position using a market order."""
    symbol = symbol.upper()
    qty = get_open_position_qty(trading_client, symbol)

    if abs(qty) <= 1e-9:
        logging.info("[%s] already flat.", symbol)
        return None

    side = "sell" if qty > 0 else "buy"

    return submit_market_order(
        trading_client=trading_client,
        symbol=symbol,
        side=side,
        qty=abs(qty),
        dry_run=dry_run,
    )


def smoke_test_connection() -> None:
    """Small local connection test for Alpaca paper account."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        force=True,
    )

    trading_client, data_client = create_alpaca_clients(require_paper=True)
    assert_account_ready(trading_client)

    positions = get_positions_snapshot(trading_client)
    print("Positions:")
    print(positions if not positions.empty else "(no open positions)")

    symbol = os.getenv("ALPACA_SMOKE_SYMBOL", "AAPL").upper()
    price = get_latest_price(trading_client, data_client, symbol)
    print(f"Latest {symbol} price: {price}")


if __name__ == "__main__":
    smoke_test_connection()