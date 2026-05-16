"""Validate a dynamic signal payload against its reproducibility manifest.

Purpose:
    - Read a payload sidecar manifest.
    - Confirm the referenced payload exists.
    - Recompute the payload SHA256 hash.
    - Confirm the saved manifest hash matches the current payload content.
    - Confirm key metadata still agrees with the payload contents.

Example:
    python -m src.validate_payload_manifest \
      --manifest quantconnect/test_payloads/selected_dynamic_signals_6ticker_quality_250marketbars.manifest.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def sha256_file(path: Path) -> str:
    """Return SHA256 hash for a file."""
    digest = hashlib.sha256()

    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)

    return digest.hexdigest()


def load_json(path: Path) -> dict:
    """Load a JSON file as a dictionary."""
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    with path.open() as file:
        return json.load(file)


def resolve_payload_path(manifest_path: Path, manifest: dict) -> Path:
    """Resolve payload path from the manifest.

    The manifest stores a repository-relative payload path. If that path does
    not exist from the current working directory, fall back to resolving it
    relative to the manifest's parent directory.
    """
    raw_path = manifest.get("payload_path")

    if not raw_path:
        raise ValueError("Manifest is missing required field: payload_path")

    payload_path = Path(raw_path)

    if payload_path.exists():
        return payload_path

    fallback_path = manifest_path.parent / payload_path.name

    if fallback_path.exists():
        return fallback_path

    raise FileNotFoundError(
        "Payload file not found. Checked:\n"
        f"  {payload_path}\n"
        f"  {fallback_path}"
    )


def validate_manifest(manifest_path: Path) -> dict:
    """Validate payload manifest and return validation results."""
    manifest = load_json(manifest_path)
    payload_path = resolve_payload_path(manifest_path, manifest)
    payload = load_json(payload_path)

    expected_sha = manifest.get("payload_sha256")
    actual_sha = sha256_file(payload_path)

    if not expected_sha:
        raise ValueError("Manifest is missing required field: payload_sha256")

    payload_signals = payload.get("signals", [])

    actual_symbols = payload.get("symbols", [])
    actual_selected_models = payload.get("selected_models", {})
    actual_rows_per_symbol = payload.get("rows_per_symbol")
    actual_signal_rows = len(payload_signals)
    actual_first_timestamp = payload_signals[0]["timestamp"] if payload_signals else None
    actual_last_timestamp = payload_signals[-1]["timestamp"] if payload_signals else None

    checks = {
        "payload_exists": payload_path.exists(),
        "sha256_match": actual_sha == expected_sha,
        "symbols_match": actual_symbols == manifest.get("symbols"),
        "selected_models_match": actual_selected_models == manifest.get("selected_models"),
        "rows_per_symbol_match": actual_rows_per_symbol == manifest.get("rows_per_symbol"),
        "signal_rows_match": actual_signal_rows == manifest.get("signal_rows"),
        "first_timestamp_match": actual_first_timestamp == manifest.get("first_timestamp"),
        "last_timestamp_match": actual_last_timestamp == manifest.get("last_timestamp"),
    }

    all_passed = all(checks.values())

    return {
        "all_passed": all_passed,
        "manifest_path": str(manifest_path),
        "payload_path": str(payload_path),
        "expected_sha256": expected_sha,
        "actual_sha256": actual_sha,
        "checks": checks,
        "payload_summary": {
            "symbols": actual_symbols,
            "selected_models": actual_selected_models,
            "rows_per_symbol": actual_rows_per_symbol,
            "signal_rows": actual_signal_rows,
            "first_timestamp": actual_first_timestamp,
            "last_timestamp": actual_last_timestamp,
        },
    }


def print_results(results: dict) -> None:
    """Print validation results."""
    print("=" * 80)
    print("PAYLOAD MANIFEST VALIDATION")
    print("=" * 80)
    print("Manifest:", results["manifest_path"])
    print("Payload:", results["payload_path"])
    print("Expected SHA256:", results["expected_sha256"])
    print("Actual SHA256:  ", results["actual_sha256"])

    print("\nChecks:")
    for name, passed in results["checks"].items():
        status = "PASS" if passed else "FAIL"
        print(f"  {name}: {status}")

    print("\nPayload summary:")
    summary = results["payload_summary"]
    print("  symbols:", summary["symbols"])
    print("  selected_models:", summary["selected_models"])
    print("  rows_per_symbol:", summary["rows_per_symbol"])
    print("  signal_rows:", summary["signal_rows"])
    print("  first_timestamp:", summary["first_timestamp"])
    print("  last_timestamp:", summary["last_timestamp"])

    print("\nResult:", "PASS" if results["all_passed"] else "FAIL")


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Validate a dynamic signal payload against its manifest."
    )

    parser.add_argument(
        "--manifest",
        type=Path,
        required=True,
        help="Path to payload sidecar manifest JSON.",
    )

    return parser.parse_args()


def main() -> None:
    """Run payload manifest validation."""
    args = parse_args()

    results = validate_manifest(args.manifest)
    print_results(results)

    if not results["all_passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()