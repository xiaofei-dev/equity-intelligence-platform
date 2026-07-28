from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from equity_analysis.provider_validation.current_factor_windows_v1 import (
    FACTOR_INPUT_SNAPSHOT_VERSION,
    _derive_arithmetic,
    _earnings_yield_source_status,
    _factor_status,
    _status,
    _ttm_status,
    consecutive_quarter_windows,
)
from equity_analysis.provider_validation.expansion_gate import (
    canonical_hash,
    write_immutable_json,
)

CUTOFF = datetime(2026, 7, 27, 23, 59, 59, tzinfo=UTC)


def _quarter(
    start: date,
    end: date,
    *,
    value: str = "10",
    unit: str = "USD",
    currency: str | None = "USD",
    duration_class: str = "DISCRETE_QUARTER",
    available_at: str = "2026-05-01T12:00:00Z",
    suffix: str = "a",
) -> dict[str, object]:
    record = {
        "observationType": "DURATION",
        "normalizedOperand": "revenue",
        "periodStart": start.isoformat(),
        "periodEnd": end.isoformat(),
        "durationClass": duration_class,
        "availableAt": available_at,
        "mappingPriority": 1,
        "accession": f"0000000000-26-00000{suffix}",
        "observationId": f"sec-fact:{suffix}",
        "contentHash": canonical_hash([start.isoformat(), end.isoformat(), suffix]),
        "sourceContentHash": "A" * 64,
        "value": value,
        "unit": unit,
        "currency": currency,
    }
    return record


def _regular_quarters(count: int = 8) -> list[dict[str, object]]:
    starts = [
        date(2024, 1, 1),
        date(2024, 4, 1),
        date(2024, 7, 1),
        date(2024, 10, 1),
        date(2025, 1, 1),
        date(2025, 4, 1),
        date(2025, 7, 1),
        date(2025, 10, 1),
    ]
    ends = [
        date(2024, 3, 31),
        date(2024, 6, 30),
        date(2024, 9, 30),
        date(2024, 12, 31),
        date(2025, 3, 31),
        date(2025, 6, 30),
        date(2025, 9, 30),
        date(2025, 12, 31),
    ]
    return [
        _quarter(start, end, suffix=str(index))
        for index, (start, end) in enumerate(zip(starts, ends, strict=True))
    ][:count]


def test_consecutive_quarter_windows_accepts_eight_aligned_discrete_periods() -> None:
    windows = consecutive_quarter_windows(
        _regular_quarters(),
        count=8,
        cutoff=CUTOFF,
    )

    assert len(windows) == 1
    assert [row["periodEnd"] for row in windows[0]][-1] == "2025-12-31"


def test_consecutive_quarter_windows_rejects_gap_and_ytd() -> None:
    records = _regular_quarters(4)
    records[1]["periodStart"] = "2024-05-01"
    assert consecutive_quarter_windows(records, count=4, cutoff=CUTOFF) == []

    records = _regular_quarters(4)
    records[2]["durationClass"] = "YTD"
    assert consecutive_quarter_windows(records, count=4, cutoff=CUTOFF) == []


def test_consecutive_quarter_windows_rejects_mixed_unit_currency_and_future() -> None:
    records = _regular_quarters(4)
    records[3]["currency"] = "EUR"
    assert consecutive_quarter_windows(records, count=4, cutoff=CUTOFF) == []

    records = _regular_quarters(4)
    records[3]["availableAt"] = "2026-07-28T00:00:00Z"
    assert consecutive_quarter_windows(records, count=4, cutoff=CUTOFF) == []


def test_consecutive_quarter_windows_accepts_53_week_fiscal_year() -> None:
    records = [
        _quarter(date(2024, 2, 4), date(2024, 5, 4), suffix="1"),
        _quarter(date(2024, 5, 5), date(2024, 8, 3), suffix="2"),
        _quarter(date(2024, 8, 4), date(2024, 11, 2), suffix="3"),
        _quarter(date(2024, 11, 3), date(2025, 2, 8), suffix="4"),
    ]

    assert len(consecutive_quarter_windows(records, count=4, cutoff=CUTOFF)) == 1


def test_ttm_weighted_shares_uses_duration_days_instead_of_sum() -> None:
    records = [
        _quarter(
            date(2025, 2, 2),
            date(2025, 5, 3),
            value="100",
            unit="SHARES",
            currency=None,
            suffix="s1",
        ),
        _quarter(
            date(2025, 5, 4),
            date(2025, 8, 2),
            value="200",
            unit="SHARES",
            currency=None,
            suffix="s2",
        ),
        _quarter(
            date(2025, 8, 3),
            date(2025, 11, 1),
            value="300",
            unit="SHARES",
            currency=None,
            suffix="s3",
        ),
        _quarter(
            date(2025, 11, 2),
            date(2026, 2, 7),
            value="400",
            unit="SHARES",
            currency=None,
            suffix="s4",
        ),
    ]
    status, _ = _ttm_status(
        records,
        cutoff=datetime(2026, 6, 1, tzinfo=UTC),
        weighted_average=True,
    )
    day_counts = [
        (
            date.fromisoformat(record["periodEnd"])
            - date.fromisoformat(record["periodStart"])
        ).days
        + 1
        for record in records
    ]
    expected = sum(
        Decimal(str((index + 1) * 100)) * days
        for index, days in enumerate(day_counts)
    ) / Decimal(sum(day_counts))

    assert status["status"] == "VALID"
    assert Decimal(status["value"]) == expected
    assert Decimal(status["value"]) != Decimal("1000")
    assert status["derivationLineage"]["operation"] == (
        "DAY_WEIGHTED_AVERAGE_FOUR_DISCRETE_QUARTERS"
    )


def test_latest_revision_is_deterministic_and_cutoff_safe() -> None:
    records = _regular_quarters(4)
    revised = dict(records[-1])
    revised.update(
        {
            "value": "11",
            "availableAt": "2026-06-01T12:00:00Z",
            "accession": "0000000000-26-999999",
            "observationId": "sec-fact:revision",
            "contentHash": "B" * 64,
        }
    )
    future = dict(revised)
    future.update(
        {
            "value": "12",
            "availableAt": "2026-07-28T00:00:00Z",
            "observationId": "sec-fact:future",
        }
    )

    window = consecutive_quarter_windows(
        [*records, revised, future],
        count=4,
        cutoff=CUTOFF,
    )[-1]

    assert window[-1]["value"] == "11"
    assert window[-1]["observationId"] == "sec-fact:revision"


def test_missing_is_not_coerced_to_zero_or_neutral() -> None:
    missing = _status("MISSING", "OPERAND_ABSENT")

    assert "value" not in missing
    factor = _factor_status(("required_operand",), {"required_operand": missing})
    assert factor == {
        "status": "MISSING",
        "reasonCode": "MISSING_REQUIRED_OPERANDS",
        "requiredOperands": ["required_operand"],
        "blockingOperands": ["required_operand"],
    }


def test_arithmetic_rejects_cross_currency_inputs() -> None:
    usd = _status("VALID", "OK", value=Decimal("10"), unit="USD", currency="USD")
    eur = _status("VALID", "OK", value=Decimal("5"), unit="EUR", currency="EUR")

    result = _derive_arithmetic(
        [usd, eur],
        operation="ADD",
        reason="MISSING",
    )

    assert result["status"] == "INVALID"
    assert result["reasonCode"] == "OPERAND_UNIT_OR_CURRENCY_MISMATCH"
    assert "value" not in result


def test_direct_enterprise_value_makes_minority_component_not_required() -> None:
    operands = {
        "ebit_ttm": _status(
            "VALID",
            "OK",
            value=Decimal("100"),
            unit="USD",
            currency="USD",
        ),
        "enterprise_value": _status(
            "VALID",
            "OK",
            value=Decimal("1000"),
            unit="USD",
            currency="USD",
        ),
        "pit_market_cap": _status("MISSING", "NOT_USED"),
        "instant_total_debt": _status("MISSING", "NOT_USED"),
        "instant_cash": _status("MISSING", "NOT_USED"),
        "instant_minority_interest": _status(
            "NOT_APPLICABLE",
            "DIRECT_PROVIDER_ENTERPRISE_VALUE_MATCHES_FROZEN_FORMULA",
        ),
    }

    result = _earnings_yield_source_status(operands)

    assert result["status"] == "VALID"
    assert result["requiredOperands"] == ["ebit_ttm", "enterprise_value"]
    assert result["sourceRoute"] == "DIRECT_PROVIDER_ENTERPRISE_VALUE"


def test_content_addressed_snapshot_is_immutable(tmp_path: Path) -> None:
    payload = {
        "schemaVersion": FACTOR_INPUT_SNAPSHOT_VERSION,
        "symbol": "TEST",
        "value": "123.45",
    }
    content_hash = canonical_hash(payload)
    path = tmp_path / "TEST" / f"{content_hash}.json"
    write_immutable_json(path, payload)

    assert json.loads(path.read_text(encoding="utf-8")) == payload
    with pytest.raises(FileExistsError):
        write_immutable_json(path, payload)


def test_content_hash_and_resume_identity_are_deterministic() -> None:
    payload = {
        "schemaVersion": FACTOR_INPUT_SNAPSHOT_VERSION,
        "symbol": "TEST",
        "cutoff": CUTOFF.isoformat(),
        "periods": [
            (date(2025, 1, 1) + timedelta(days=index * 90)).isoformat()
            for index in range(4)
        ],
    }

    assert canonical_hash(payload) == canonical_hash(json.loads(json.dumps(payload)))


def test_generated_manifest_is_value_free_and_tracks_all_frozen_candidates() -> None:
    repository_root = Path(__file__).resolve().parents[2]
    path = (
        repository_root
        / "docs/generated/objective-rating-v1-current-factor-input-manifest-v1-4.json"
    )
    manifest = json.loads(path.read_text(encoding="utf-8"))

    assert manifest["sourceContractCandidateCount"] == 55
    assert len({item["symbol"] for item in manifest["securities"]}) == 55
    assert manifest["licensedValuesIncluded"] is False
    assert manifest["scoresOrRanksIncluded"] is False
    assert manifest["networkRequestsExecuted"] is False
    assert manifest["currentQcInputReadyCount"] == 0
    assert manifest["currentUqInputReadyCount"] == 0
    assert manifest["derivationCounts"] == {
        "SEC-FY-MINUS-9M-v1.0.0": 9018,
        "SEC-YTD-DIFFERENCE-v1.0.0": 18267,
    }
    assert manifest["factorStatusCounts"]["qcFactors:stability"] == {
        "MISSING": 12,
        "VALID": 43,
    }
    assert "instant_minority_interest" not in manifest["blockingOperandCounts"]
    assert '"value":' not in path.read_text(encoding="utf-8")
    assert canonical_hash(
        {
            key: value
            for key, value in manifest.items()
            if key != "artifactContentHash"
        }
    ) == manifest["artifactContentHash"]
