import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from equity_analysis.provider_validation.combined_backfill_cli import (
    classify_symbols,
)
from equity_analysis.provider_validation.controlled_evidence import (
    build_controlled_evidence,
    build_frozen_slices,
    build_symbol_evidence,
)
from equity_analysis.provider_validation.expansion_gate import (
    FORMULA_INPUT_FIELDS,
    canonical_hash,
)


def _raw_record(
    field: str,
    *,
    provider: str,
    dataset: str = "FINANCIAL",
    period_end: date,
    ingested_at: datetime,
) -> dict:
    raw = {
        "symbol": "TEST",
        "providerSymbol": "TEST.US",
        "dataset": dataset,
        "normalizedField": field,
        "value": "1",
        "unit": "USD",
        "currency": "USD",
        "periodType": "QUARTERLY" if dataset == "FINANCIAL" else "DAILY",
        "fiscalPeriodEnd": period_end.isoformat(),
        "effectiveAt": datetime.combine(period_end, datetime.min.time(), UTC).isoformat(),
        "availableAt": datetime.combine(period_end, datetime.min.time(), UTC).isoformat(),
        "ingestedAt": ingested_at.isoformat(),
        "sourceReference": f"{provider}:controlled",
        "providerCode": provider,
        "providerSchemaVersion": "schema-v1",
        "parserVersion": "parser-v1",
        "normalizationVersion": "provider-neutral-scoring-input-v2.0.0",
        "sourceContentHash": "A" * 64,
        "accessionNumber": "0000000000-00-000001" if dataset == "FINANCIAL" else None,
    }
    raw["contentHash"] = canonical_hash(raw)
    return raw


def _complete_payload(ingested_at: datetime) -> dict:
    records = []
    base = date(2024, 12, 31)
    for field in sorted(FORMULA_INPUT_FIELDS - {"market_capitalization"}):
        provider = (
            "sec_edgar"
            if field in {"diluted_weighted_average_shares", "interest_expense"}
            else "eodhd"
        )
        for offset in range(8):
            records.append(
                _raw_record(
                    field,
                    provider=provider,
                    period_end=base - timedelta(days=91 * offset),
                    ingested_at=ingested_at,
                )
            )
    for field in ("open", "high", "low", "close", "adjusted_close", "volume"):
        records.append(
            _raw_record(
                field,
                provider="eodhd",
                dataset="DAILY_PRICE",
                period_end=base,
                ingested_at=ingested_at,
            )
        )
    for offset in range(12):
        records.append(
            _raw_record(
                "market_capitalization",
                provider="eodhd",
                dataset="HISTORICAL_MARKET_CAP",
                period_end=base - timedelta(days=30 * offset),
                ingested_at=ingested_at,
            )
        )
    return {
        "inputContractVersion": "provider-neutral-scoring-input-v2.0.0",
        "symbol": "TEST",
        "records": records,
    }


def _write_hashed_payload(directory: Path, payload: dict) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{canonical_hash(payload)}.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_builder_rejects_filename_content_hash_corruption(tmp_path) -> None:
    directory = tmp_path / "TEST"
    path = _write_hashed_payload(
        directory,
        _complete_payload(datetime(2026, 7, 27, tzinfo=UTC)),
    )
    path.write_text('{"symbol":"TEST","records":[]}', encoding="utf-8")
    with pytest.raises(ValueError, match="CONTROLLED_PAYLOAD_HASH_MISMATCH"):
        build_symbol_evidence("TEST", directory)


def test_builder_deterministically_selects_latest_valid_payload(tmp_path) -> None:
    directory = tmp_path / "TEST"
    older = _write_hashed_payload(
        directory,
        _complete_payload(datetime(2026, 7, 26, tzinfo=UTC)),
    )
    newer = _write_hashed_payload(
        directory,
        _complete_payload(datetime(2026, 7, 27, tzinfo=UTC)),
    )
    evidence = build_symbol_evidence("TEST", directory)
    assert evidence["v2PayloadPath"] == newer.as_posix()
    assert evidence["v2ContentHash"] == newer.stem
    assert evidence["candidatePayloadCount"] == 2
    assert evidence["formulaCoverageComplete"] is True
    assert evidence["eodhdCoverageComplete"] is True
    assert evidence["secSupplementCoverageComplete"] is True
    assert older != newer


def test_incomplete_evidence_only_requests_missing_endpoint_group() -> None:
    common = {
        "v2StorageExists": True,
        "v2ContentHash": "A" * 64,
        "formulaCoverageComplete": False,
    }
    classifications = classify_symbols(
        ("SEC_ONLY", "EODHD_ONLY"),
        {
            "SEC_ONLY": {
                **common,
                "eodhdCoverageComplete": True,
                "secSupplementCoverageComplete": False,
            },
            "EODHD_ONLY": {
                **common,
                "eodhdCoverageComplete": False,
                "secSupplementCoverageComplete": True,
            },
        },
    )
    assert classifications[0]["actions"] == ("NEEDS_SEC",)
    assert classifications[1]["actions"] == ("NEEDS_EODHD",)


def test_missing_storage_and_frozen_slices_are_deterministic(tmp_path) -> None:
    evidence = build_controlled_evidence(["A", "B"], tmp_path)
    assert evidence["records"]["A"]["v2StorageExists"] is False
    manifest_payload = {
        "slices": [
            {"sliceId": "slice-1", "sequence": 1, "symbols": ["A", "B"]},
        ],
    }
    manifest = {
        **manifest_payload,
        "artifactContentHash": canonical_hash(manifest_payload),
    }
    first = build_frozen_slices(manifest)
    assert first == build_frozen_slices(manifest)
    payload = {key: value for key, value in first[0].items() if key != "contentHash"}
    assert first[0]["contentHash"] == canonical_hash(payload)
    with pytest.raises(ValueError, match="REMAINING_MANIFEST_HASH_MISMATCH"):
        build_frozen_slices({**manifest, "artifactContentHash": "B" * 64})
