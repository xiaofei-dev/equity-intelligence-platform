from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from equity_analysis.fundamental_value.historical_company_quality_approximation_v1 import (
    ApproximationError,
    ApproximationState,
    CurrentRevisionEvidenceEnvelopeV1,
    build_approximation_producer_registry,
    canonical_hash,
    replay_approximation_coverage,
    seal_evidence_envelope,
)
from equity_analysis.fundamental_value.historical_company_quality_pilot_v1 import (
    load_session_calendar_dates_only,
)

REPOSITORY = Path(__file__).resolve().parents[2]


def _valid_envelope() -> tuple[CurrentRevisionEvidenceEnvelopeV1, object]:
    contract = build_approximation_producer_registry(REPOSITORY)["operating_margin"]
    body = {
        "availability_stratum": "CURRENT_REVISION_APPROXIMATION",
        "producer_version": contract.producer_version,
        "producer_content_hash": contract.content_hash,
        "operand_code": contract.operand_code,
        "security_id": "SEC:1:AAA",
        "issuer_id": "1",
        "listing_id": "US_LISTING:AAA",
        "decision_cutoff": datetime(2020, 5, 20, tzinfo=UTC),
        "period_start": date(2020, 1, 1),
        "period_end": date(2020, 3, 31),
        "filing_date_proxy": datetime(2020, 5, 1, tzinfo=UTC),
        "effective_at": datetime(2020, 3, 31, tzinfo=UTC),
        "available_at": datetime(2020, 5, 1, tzinfo=UTC),
        "ingested_at": datetime(2026, 7, 1, tzinfo=UTC),
        "provider": "EODHD",
        "provider_schema_version": "schema-v1",
        "adapter_version": "adapter-v1",
        "revision_id": "CURRENT_SNAPSHOT_NO_FIELD_REVISION_ID",
        "source_hashes": ("A" * 64,),
        "parent_hashes": ("B" * 64,),
        "unit": "RATIO",
        "currency": "USD",
        "state": ApproximationState.VALID,
        "reason": "VALID_CURRENT_REVISION_APPROXIMATION",
        "value": Decimal("0.25"),
        "current_revision_limitation": "Revised history; not strict PIT.",
    }
    body["output_hash"] = canonical_hash(body)
    return CurrentRevisionEvidenceEnvelopeV1(**body), contract


def _reseal(value: CurrentRevisionEvidenceEnvelopeV1, **changes: object):
    changed = replace(value, **changes, output_hash="")
    body = changed.__dict__.copy()
    body.pop("output_hash")
    return replace(changed, output_hash=canonical_hash(body))


def test_registry_is_separate_current_revision_lineage() -> None:
    registry = build_approximation_producer_registry(REPOSITORY)
    assert set(registry) == {
        "return_on_invested_capital", "operating_margin",
        "free_cash_flow_margin", "earnings_stability", "cash_flow_stability",
    }
    assert all(item.availability_stratum == "CURRENT_REVISION_APPROXIMATION"
               for item in registry.values())
    assert all("APPROXIMATION" in item.producer_version
               for item in registry.values())


def test_revised_history_label_and_valid_state_is_semantically_blocked() -> None:
    envelope, contract = _valid_envelope()
    with pytest.raises(ApproximationError, match="VALID_BLOCKED_QUARTERLY"):
        seal_evidence_envelope(envelope, contract)
    contaminated = _reseal(envelope, availability_stratum="STRICT_PIT")
    with pytest.raises(ApproximationError, match="CROSS_CONTAMINATION"):
        seal_evidence_envelope(contaminated, contract)


def test_filing_date_after_cutoff_is_rejected() -> None:
    envelope, contract = _valid_envelope()
    changed = _reseal(
        envelope,
        filing_date_proxy=datetime(2020, 6, 1, tzinfo=UTC),
    )
    with pytest.raises(ApproximationError, match="FILING_DATE_AFTER"):
        seal_evidence_envelope(changed, contract)


@pytest.mark.parametrize(("changes", "reason"), [
    ({"period_end": date(2020, 5, 21)}, "PERIOD_END_AFTER_DECISION"),
    ({"period_end": date(2020, 5, 2)}, "PERIOD_END_AFTER_FILING"),
    ({"effective_at": datetime(2020, 3, 30, tzinfo=UTC)},
     "EFFECTIVE_BEFORE_PERIOD_END"),
    ({"effective_at": datetime(2020, 5, 2, tzinfo=UTC)},
     "EFFECTIVE_AFTER_FILING"),
])
def test_future_period_and_effective_chronology_fail(
    changes: dict[str, object], reason: str,
) -> None:
    envelope, contract = _valid_envelope()
    with pytest.raises(ApproximationError, match=reason):
        seal_evidence_envelope(_reseal(envelope, **changes), contract)


@pytest.mark.parametrize("changes", [
    {"period_start": None},
    {"period_start": date(2020, 3, 31), "period_end": date(2020, 3, 31)},
    {"unit": "USD"},
    {"currency": "EUR"},
])
def test_period_unit_currency_and_missing_start_semantics_fail(
    changes: dict[str, object],
) -> None:
    envelope, contract = _valid_envelope()
    with pytest.raises(ApproximationError):
        seal_evidence_envelope(_reseal(envelope, **changes), contract)


def test_revision_contract_and_output_hash_drift_fail() -> None:
    envelope, contract = _valid_envelope()
    with pytest.raises(ApproximationError, match="NONBLANK"):
        seal_evidence_envelope(_reseal(envelope, revision_id="  "), contract)
    with pytest.raises(ApproximationError, match="OUTPUT_HASH_DRIFT"):
        seal_evidence_envelope(replace(envelope, value=Decimal("0.30")), contract)
    with pytest.raises(ApproximationError, match="PRODUCER_BINDING"):
        seal_evidence_envelope(
            _reseal(envelope, producer_content_hash="F" * 64), contract)


def test_non_valid_evidence_cannot_carry_value() -> None:
    envelope, contract = _valid_envelope()
    missing = _reseal(envelope, state=ApproximationState.MISSING)
    with pytest.raises(ApproximationError, match="MUST_NOT_HAVE_VALUE"):
        seal_evidence_envelope(missing, contract)


def test_valid_with_empty_or_opaque_parent_set_is_never_admitted() -> None:
    envelope, contract = _valid_envelope()
    for parents in ((), ("C" * 64,)):
        with pytest.raises(ApproximationError, match="VALID_BLOCKED_QUARTERLY"):
            seal_evidence_envelope(
                _reseal(envelope, parent_hashes=parents), contract)


def test_semantic_support_hash_drift_fails(tmp_path: Path) -> None:
    target = tmp_path / "docs/generated"
    target.mkdir(parents=True)
    source = REPOSITORY / "docs/generated/eodhd-fundamentals-documentation-semantic-audit-v2.json"
    (target / source.name).write_text(source.read_text() + " ", encoding="utf-8")
    with pytest.raises(ApproximationError, match="HASH_DRIFT"):
        build_approximation_producer_registry(tmp_path)


def test_actual_25_100_216_replay_is_value_free_and_bound() -> None:
    controlled = Path("C:/Projects/equity-intelligence-platform")
    spy = next(controlled.glob(
        "storage/historical-validation/yahoo-daily-price-cache-v1/payloads/SPY/*.json"))
    result = replay_approximation_coverage(
        REPOSITORY, controlled, load_session_calendar_dates_only(spy))
    assert [item["securityCount"] for item in result["phases"]] == [25, 100, 216]
    assert result["availabilityStratum"] == "CURRENT_REVISION_APPROXIMATION"
    assert result["claimCeiling"] == (
        "DEVELOPMENT_OBSERVED_CURRENT_REVISION_APPROXIMATION")
    assert result["outcomesRead"] is False
    assert result["networkRequests"] == result["databaseRequests"] == 0
    assert all(
        row["companyQualityTargetCounts"] == {"MISSING": phase["securityCount"]}
        for phase in result["phases"] for row in phase["matrix"]
    )
    artifact = json.loads((REPOSITORY
        / "contracts/fundamental-value-historical-validation-v1"
        / "stage7c3-company-quality-approximation-summary.json").read_text())
    claimed = artifact.pop("summaryContentHash")
    assert claimed == canonical_hash(artifact)
    assert artifact["fullInMemoryResultHash"] == result["contentHash"]
    assert artifact["phaseMatrixHashes"] == {
        item["phase"]: item["contentHash"] for item in result["phases"]
    }
