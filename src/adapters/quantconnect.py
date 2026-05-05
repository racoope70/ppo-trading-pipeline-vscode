"""QuantConnect signal adapter.

This module converts local PPO predictions into a JSON payload that can be
consumed by a QuantConnect/LEAN algorithm.

It does not contain QuantConnect algorithm code. The QuantConnect consumer
algorithm should live separately under quantconnect/ or be pasted directly into
the QuantConnect IDE.

Local usage:
    python -m src.adapters.quantconnect

Optional Gist publishing:
    export GITHUB_TOKEN="..."
    python -m src.adapters.quantconnect --publish-gist
"""

from __future__ import annotations

import argparse
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import requests

from src.config import SYMBOLS, make_results_dir
from src.predict import predict_symbols


DEFAULT_SIGNAL_FILENAME = "live_signals.json"
DEFAULT_GIST_DESCRIPTION = "Live PPO signals for QuantConnect"


def utc_now() -> datetime:
    """Return timezone-aware UTC datetime."""
    return datetime.now(timezone.utc)


def build_quantconnect_payload(
    predictions: list[dict[str, Any]],
    valid_minutes: int = 1440,
    interval: str = "1h",
    producer: str = "ppo_research_pipeline",
) -> dict[str, Any]:
    """Build the JSON structure expected by the QuantConnect consumer.

    Expected shape:
        {
            "generated_utc": "...",
            "valid_until_utc": "...",
            "producer": "...",
            "interval": "1h",
            "models": [...]
        }
    """
    generated = utc_now()
    valid_until = generated + timedelta(minutes=valid_minutes)

    return {
        "generated_utc": generated.isoformat(),
        "valid_until_utc": valid_until.isoformat(),
        "producer": producer,
        "interval": interval,
        "models": predictions,
    }


def save_live_signals(
    payload: dict[str, Any],
    output_dir: Path,
    filename: str = DEFAULT_SIGNAL_FILENAME,
) -> Path:
    """Save QuantConnect-compatible signal JSON locally."""
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / filename

    with output_path.open("w") as file:
        json.dump(payload, file, indent=2, default=str)

    logging.info("Saved QuantConnect signal file: %s", output_path)

    return output_path


def get_gist_headers(token: str) -> dict[str, str]:
    """Return GitHub API headers for Gist publishing."""
    headers = {
        "Accept": "application/vnd.github+json",
    }

    if token:
        headers["Authorization"] = f"token {token}"

    return headers


def publish_json_to_gist(
    payload: dict[str, Any],
    filename: str = DEFAULT_SIGNAL_FILENAME,
    gist_id: str | None = None,
    token: str | None = None,
    description: str = DEFAULT_GIST_DESCRIPTION,
    public: bool = True,
) -> dict[str, str]:
    """Create or update a GitHub Gist containing the signal payload.

    Environment variables:
        GITHUB_TOKEN: required for publishing
        GIST_ID: optional; if provided, updates existing Gist
    """
    token = token or os.getenv("GITHUB_TOKEN", "").strip()
    gist_id = gist_id or os.getenv("GIST_ID", "").strip()

    if not token:
        raise RuntimeError(
            "GITHUB_TOKEN is not set. Add it to your environment or .env file. "
            "Do not commit secrets to GitHub."
        )

    files = {
        filename: {
            "content": json.dumps(payload, indent=2, default=str),
        }
    }

    headers = get_gist_headers(token)

    if gist_id:
        response = requests.patch(
            f"https://api.github.com/gists/{gist_id}",
            headers=headers,
            json={
                "files": files,
                "description": description,
            },
            timeout=30,
        )
    else:
        response = requests.post(
            "https://api.github.com/gists",
            headers=headers,
            json={
                "files": files,
                "description": description,
                "public": public,
            },
            timeout=30,
        )

    if not response.ok:
        raise RuntimeError(
            f"Gist publish failed: {response.status_code} {response.text[:500]}"
        )

    data = response.json()

    published_gist_id = data.get("id", gist_id or "")
    owner = ((data.get("owner") or {}).get("login")) or "anonymous"
    raw_url = ((data.get("files") or {}).get(filename) or {}).get("raw_url", "")

    stable_raw_url = ""
    if published_gist_id and owner:
        stable_raw_url = (
            f"https://gist.githubusercontent.com/"
            f"{owner}/{published_gist_id}/raw/{filename}"
        )

    logging.info("Published Gist: https://gist.github.com/%s/%s", owner, published_gist_id)
    logging.info("Raw URL: %s", stable_raw_url or raw_url)

    return {
        "gist_id": published_gist_id,
        "owner": owner,
        "raw_url": raw_url,
        "stable_raw_url": stable_raw_url,
        "gist_page": f"https://gist.github.com/{owner}/{published_gist_id}",
    }


def export_quantconnect_signals(
    symbols: list[str] | None = None,
    valid_minutes: int = 1440,
    interval: str = "1h",
    publish_gist: bool = False,
    output_dir: Path | None = None,
) -> dict[str, Any]:
    """Run PPO prediction and export a QuantConnect-compatible signal payload."""
    results_dir = output_dir or make_results_dir(prefix="quantconnect_signals")

    predictions = predict_symbols(
        symbols=symbols or SYMBOLS,
        output_dir=results_dir,
        horizon_days=30,
        interval=interval,
    )

    payload = build_quantconnect_payload(
        predictions=predictions,
        valid_minutes=valid_minutes,
        interval=interval,
    )

    signal_path = save_live_signals(
        payload=payload,
        output_dir=results_dir,
        filename=DEFAULT_SIGNAL_FILENAME,
    )

    latest_csv_path = results_dir / "latest_predictions.csv"
    if predictions:
        pd.DataFrame(predictions).to_csv(latest_csv_path, index=False)
        logging.info("Saved prediction table: %s", latest_csv_path)
    else:
        logging.warning("No predictions generated; payload models list is empty.")

    gist_meta = None

    if publish_gist:
        gist_meta = publish_json_to_gist(
            payload=payload,
            filename=DEFAULT_SIGNAL_FILENAME,
        )

        gist_meta_path = results_dir / "gist_metadata.json"
        with gist_meta_path.open("w") as file:
            json.dump(gist_meta, file, indent=2)

        logging.info("Saved Gist metadata: %s", gist_meta_path)

    return {
        "results_dir": str(results_dir),
        "signal_path": str(signal_path),
        "latest_predictions_path": str(latest_csv_path),
        "payload": payload,
        "gist": gist_meta,
    }


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Export PPO predictions as QuantConnect-compatible JSON signals."
    )

    parser.add_argument(
        "--symbols",
        type=str,
        default="",
        help="Optional comma-separated symbols. Defaults to SYMBOLS from src.config.",
    )

    parser.add_argument(
        "--valid-minutes",
        type=int,
        default=1440,
        help="How long the signal JSON should be considered fresh.",
    )

    parser.add_argument(
        "--interval",
        type=str,
        default="1h",
        help="Data interval used for inference.",
    )

    parser.add_argument(
        "--publish-gist",
        action="store_true",
        help="Publish live_signals.json to GitHub Gist using GITHUB_TOKEN.",
    )

    return parser.parse_args()


def main() -> None:
    """Command-line entry point."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        force=True,
    )

    args = parse_args()

    symbols = None
    if args.symbols:
        symbols = [
            symbol.strip().upper()
            for symbol in args.symbols.split(",")
            if symbol.strip()
        ]

    result = export_quantconnect_signals(
        symbols=symbols,
        valid_minutes=args.valid_minutes,
        interval=args.interval,
        publish_gist=args.publish_gist,
    )

    logging.info("QuantConnect signal export complete.")
    logging.info("Output folder: %s", result["results_dir"])
    logging.info("Signal file: %s", result["signal_path"])

    if result["gist"]:
        logging.info("Gist page: %s", result["gist"]["gist_page"])
        logging.info("Stable raw URL: %s", result["gist"]["stable_raw_url"])


if __name__ == "__main__":
    main()