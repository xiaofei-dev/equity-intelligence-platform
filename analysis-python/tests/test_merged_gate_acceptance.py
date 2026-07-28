import json
from datetime import UTC, datetime
from hashlib import sha256

import pytest

from equity_analysis.provider_validation.merged_acceptance import (
    _load_verified,
    merge_live_results,
)


def _result(symbol: str, status: str) -> dict:
    return {
        "symbol": symbol,
        "sector": "Industrials",
        "candidateRole": "PRIMARY",
        "status": status,
        "reasonCodes": [] if status == "PASS" else ["MISSING_PITAVAILABILITY"],
    }


def _base(count: int, status: str = "PASS") -> dict:
    return {
        "reportVersion": "mature-company-data-gate-v1.0.0",
        "runId": "base-run",
        "results": [_result(f"S{index:03d}", status) for index in range(count)],
    }


def _metadata(run_id: str) -> dict:
    return {
        "evidenceType": "LIVE_IMMUTABLE_REPORT",
        "runId": run_id,
        "reportSha256": "a" * 64,
    }


def test_latest_hash_verified_live_result_overrides_old_symbol_once() -> None:
    base = _base(100)
    base["results"][0] = _result("S000", "PARTIAL")
    override = {
        "runId": "focused-run",
        "results": [_result("S000", "PASS")],
    }

    merged = merge_live_results(
        base,
        ((_metadata("focused-run"), override),),
        target_pass_count=100,
        base_metadata=_metadata("base-run"),
    )

    assert merged["uniquePassCount"] == 100
    assert merged["aggregateGateStatus"] == "PASS"
    record = next(item for item in merged["ledger"] if item["symbol"] == "S000")
    assert record["sourceRunId"] == "focused-run"
    assert record["status"] == "PASS"


def test_duplicate_symbol_is_rejected() -> None:
    base = _base(100)
    base["results"].append(_result("S000", "PASS"))

    with pytest.raises(ValueError, match="duplicate"):
        merge_live_results(
            base,
            (),
            target_pass_count=100,
            base_metadata=_metadata("base-run"),
        )


def test_less_than_one_hundred_unique_live_passes_fails() -> None:
    merged = merge_live_results(
        _base(99),
        (),
        target_pass_count=100,
        base_metadata=_metadata("base-run"),
    )

    assert merged["uniquePassCount"] == 99
    assert merged["aggregateGateStatus"] == "FAIL"
    assert merged["passShortfall"] == 1


def test_exactly_one_hundred_unique_live_passes_passes() -> None:
    merged = merge_live_results(
        _base(100),
        (),
        target_pass_count=100,
        base_metadata=_metadata("base-run"),
    )

    assert merged["uniquePassCount"] == 100
    assert merged["aggregateGateStatus"] == "PASS"
    assert len({item["symbol"] for item in merged["passRecords"]}) == 100


def test_missing_or_hash_mismatched_source_is_rejected(tmp_path) -> None:
    missing = tmp_path / "missing.json"
    with pytest.raises(ValueError, match="missing"):
        _load_verified(str(missing), "a" * 64)

    source = tmp_path / "source.json"
    source.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="hash mismatch"):
        _load_verified(str(source), "a" * 64)


def test_offline_evidence_cannot_be_injected_as_live_override() -> None:
    base = _base(100)
    offline = {
        "runId": "offline-derived",
        "results": [_result("S000", "PASS")],
    }
    metadata = _metadata("offline-derived")
    metadata["evidenceType"] = "OFFLINE_DERIVED"

    with pytest.raises(ValueError, match="live"):
        merge_live_results(
            base,
            ((metadata, offline),),
            target_pass_count=100,
            base_metadata=_metadata("base-run"),
        )


def test_fixture_hash_helper_uses_exact_file_bytes(tmp_path) -> None:
    source = tmp_path / "source.json"
    source.write_text(
        json.dumps(
            {"generatedAt": datetime(2026, 7, 27, tzinfo=UTC).isoformat()}
        ),
        encoding="utf-8",
    )
    expected = sha256(source.read_bytes()).hexdigest().upper()

    assert _load_verified(str(source), expected)["generatedAt"]
