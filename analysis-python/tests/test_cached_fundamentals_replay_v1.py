from __future__ import annotations

import json
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

import pytest

from equity_analysis.daily_refresh.cached_fundamentals_replay_v1 import (
    JOURNAL_RELATIVE_ROOT,
    discover_cached_fundamentals,
    load_cached_fundamentals_payload,
)
from equity_analysis.provider_validation.expansion_gate import canonical_hash


def _write_event(path: Path, event: dict) -> None:
    event["eventHash"] = canonical_hash(event)
    path.write_text(
        json.dumps(event, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )


def _cached_response(repository_root: Path) -> tuple[Path, Path]:
    request_dir = (
        repository_root
        / JOURNAL_RELATIVE_ROOT
        / "fixture-run"
        / "requests"
        / "AAPL"
        / "request-id"
    )
    response_dir = request_dir / "responses"
    response_dir.mkdir(parents=True)
    raw = json.dumps(
        {
            "General": {
                "Name": "Apple Inc.",
                "Sector": "Technology",
                "Industry": "Consumer Electronics",
                "CurrencyCode": "USD",
            },
            "Highlights": {"MarketCapitalization": "100"},
            "Financials": {},
        },
        separators=(",", ":"),
    ).encode()
    response_hash = sha256(raw).hexdigest().upper()
    response_path = response_dir / f"{response_hash}.bin"
    response_path.write_bytes(raw)
    relative_response = response_path.relative_to(repository_root).as_posix()
    intent_path = request_dir / "000001-INTENT.json"
    completed_path = request_dir / "000002-COMPLETED.json"
    _write_event(
        intent_path,
        {
            "schemaVersion": "physical-request-journal-v1.0.0",
            "eventType": "PHYSICAL_REQUEST",
            "runId": "fixture-run",
            "symbol": "AAPL",
            "requestIdentity": "request-id",
            "sequence": 1,
            "state": "INTENT",
            "detail": {
                "endpointCategory": "fundamentals",
                "startedAt": "2026-07-27T12:00:00Z",
            },
        },
    )
    _write_event(
        completed_path,
        {
            "schemaVersion": "physical-request-journal-v1.0.0",
            "eventType": "PHYSICAL_REQUEST",
            "runId": "fixture-run",
            "symbol": "AAPL",
            "requestIdentity": "request-id",
            "sequence": 2,
            "state": "COMPLETED",
            "detail": {
                "endpointCategory": "fundamentals",
                "durationMs": 249,
                "status": 200,
                "responseCheckpointPath": relative_response,
                "responseContentHash": response_hash,
            },
        },
    )
    return completed_path, response_path


def test_discovers_one_hash_verified_response_with_conservative_completion_time(
    tmp_path: Path,
) -> None:
    _cached_response(tmp_path)

    selected = discover_cached_fundamentals(
        repository_root=tmp_path,
        symbols={"AAPL", "MSFT"},
    )

    assert set(selected) == {"AAPL"}
    assert selected["AAPL"].retrieved_at == datetime(
        2026, 7, 27, 12, 0, 0, 250000, tzinfo=UTC
    )
    payload = load_cached_fundamentals_payload(
        repository_root=tmp_path,
        evidence=selected["AAPL"],
    )
    assert payload["General"]["Name"] == "Apple Inc."


def test_rejects_tampered_cached_response(tmp_path: Path) -> None:
    _completed, response = _cached_response(tmp_path)
    response.write_bytes(b"tampered")

    with pytest.raises(ValueError, match="CACHE_RESPONSE_HASH_MISMATCH"):
        discover_cached_fundamentals(
            repository_root=tmp_path,
            symbols={"AAPL"},
        )
