import json
from pathlib import Path

import pytest

from src.validate_payload_manifest import sha256_file, validate_manifest


def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2))


def test_validate_manifest_passes_for_matching_payload(tmp_path):
    payload_path = tmp_path / "payload.json"
    manifest_path = tmp_path / "payload.manifest.json"

    payload = {
        "symbols": ["AAPL", "XOM"],
        "selected_models": {
            "AAPL": "ppo_AAPL_window1",
            "XOM": "ppo_XOM_window2",
        },
        "rows_per_symbol": 2,
        "signals": [
            {"timestamp": "2026-02-10T10:00:00+00:00", "symbol": "AAPL"},
            {"timestamp": "2026-02-10T11:00:00+00:00", "symbol": "XOM"},
        ],
    }

    write_json(payload_path, payload)

    manifest = {
        "payload_path": str(payload_path),
        "payload_sha256": sha256_file(payload_path),
        "symbols": ["AAPL", "XOM"],
        "selected_models": {
            "AAPL": "ppo_AAPL_window1",
            "XOM": "ppo_XOM_window2",
        },
        "rows_per_symbol": 2,
        "signal_rows": 2,
        "first_timestamp": "2026-02-10T10:00:00+00:00",
        "last_timestamp": "2026-02-10T11:00:00+00:00",
    }

    write_json(manifest_path, manifest)

    results = validate_manifest(manifest_path)

    assert results["all_passed"] is True
    assert all(results["checks"].values())


def test_validate_manifest_fails_for_changed_payload_hash(tmp_path):
    payload_path = tmp_path / "payload.json"
    manifest_path = tmp_path / "payload.manifest.json"

    payload = {
        "symbols": ["AAPL"],
        "selected_models": {"AAPL": "ppo_AAPL_window1"},
        "rows_per_symbol": 1,
        "signals": [
            {"timestamp": "2026-02-10T10:00:00+00:00", "symbol": "AAPL"},
        ],
    }

    write_json(payload_path, payload)

    manifest = {
        "payload_path": str(payload_path),
        "payload_sha256": sha256_file(payload_path),
        "symbols": ["AAPL"],
        "selected_models": {"AAPL": "ppo_AAPL_window1"},
        "rows_per_symbol": 1,
        "signal_rows": 1,
        "first_timestamp": "2026-02-10T10:00:00+00:00",
        "last_timestamp": "2026-02-10T10:00:00+00:00",
    }

    write_json(manifest_path, manifest)

    payload["symbols"] = ["AAPL", "XOM"]
    write_json(payload_path, payload)

    results = validate_manifest(manifest_path)

    assert results["all_passed"] is False
    assert results["checks"]["sha256_match"] is False
    assert results["checks"]["symbols_match"] is False


def test_validate_manifest_requires_payload_hash(tmp_path):
    payload_path = tmp_path / "payload.json"
    manifest_path = tmp_path / "payload.manifest.json"

    payload = {
        "symbols": [],
        "selected_models": {},
        "rows_per_symbol": 0,
        "signals": [],
    }

    write_json(payload_path, payload)

    manifest = {
        "payload_path": str(payload_path),
        "symbols": [],
        "selected_models": {},
        "rows_per_symbol": 0,
        "signal_rows": 0,
        "first_timestamp": None,
        "last_timestamp": None,
    }

    write_json(manifest_path, manifest)

    with pytest.raises(ValueError, match="payload_sha256"):
        validate_manifest(manifest_path)