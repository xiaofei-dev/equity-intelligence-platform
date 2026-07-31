from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from equity_analysis.daily_refresh.evidence_validation_v1 import (
    ClassificationSourceEvidence,
    DailyPriceEvidenceBar,
    DailyPriceSeriesEvidence,
    EvidencePersistenceScope,
    EvidenceReason,
    EvidenceValidationState,
    validate_classification_evidence,
    validate_daily_price_series,
)

CUTOFF = datetime(2026, 7, 29, 2, 57, tzinfo=UTC)
SOURCE_HASH = "sha256:" + "a" * 64


def _classification(**changes) -> ClassificationSourceEvidence:
    value = ClassificationSourceEvidence(
        security_id="security-1",
        classification_version="GICS-PROVIDER-NORMALIZATION-v1.0.0",
        normalized_sector="Information Technology",
        normalized_industry="Systems Software",
        company_type="MATURE_OPERATING_COMPANY",
        effective_from=date(2026, 1, 1),
        effective_to=None,
        source_record_id="classification-source-1",
        source_provider="documented-provider",
        source_schema_version="provider-classification-v1",
        normalization_version="classification-normalization-v1",
        source_content_hash=SOURCE_HASH,
        source_quality_status="VALIDATED",
        available_at=CUTOFF - timedelta(days=1),
        ingested_at=CUTOFF - timedelta(hours=12),
    )
    return replace(value, **changes)


def _bar(
    trading_date: date,
    *,
    quality_status: str = "VALIDATED",
    session_complete: bool = True,
    revision_number: int = 1,
    adjustment_mode: str = "TOTAL_RETURN_ADJUSTED",
    provider: str = "yfinance",
) -> DailyPriceEvidenceBar:
    return DailyPriceEvidenceBar(
        security_id="security-1",
        trading_date=trading_date,
        open_price=Decimal("99"),
        high_price=Decimal("102"),
        low_price=Decimal("98"),
        close_price=Decimal("101"),
        adjusted_close=Decimal("101"),
        volume=1_000_000,
        adjustment_mode=adjustment_mode,
        provider=provider,
        provider_schema_version="yfinance-chart-v1",
        parser_version="yfinance-parser-v1",
        normalization_version="market-normalization-v1",
        revision_number=revision_number,
        source_revision_status="AS_REPORTED",
        selected_revision_is_latest_at_cutoff=True,
        source_record_id=f"price-source-{trading_date.isoformat()}",
        source_content_hash=SOURCE_HASH,
        source_quality_status=quality_status,
        available_at=datetime.combine(
            trading_date,
            datetime.min.time(),
            tzinfo=UTC,
        )
        + timedelta(hours=22),
        ingested_at=datetime.combine(
            trading_date,
            datetime.min.time(),
            tzinfo=UTC,
        )
        + timedelta(hours=23),
        session_complete=session_complete,
    )


def _series(*bars: DailyPriceEvidenceBar) -> DailyPriceSeriesEvidence:
    return DailyPriceSeriesEvidence(
        security_id="security-1",
        expected_provider="yfinance",
        expected_adjustment_mode="TOTAL_RETURN_ADJUSTED",
        expected_completed_session=date(2026, 7, 28),
        bars=bars,
    )


def test_validation_placeholder_never_becomes_authoritative_classification() -> None:
    evidence = _classification(
        normalized_sector="VALIDATION",
        normalized_industry="VALIDATION",
    )

    decision = validate_classification_evidence(evidence, as_of=CUTOFF)

    assert decision.state == EvidenceValidationState.INVALID
    assert decision.reason_codes == (
        EvidenceReason.CLASSIFICATION_PLACEHOLDER_REJECTED,
    )
    assert evidence.normalized_sector == "VALIDATION"


def test_classification_requires_validated_hash_bound_source_lineage() -> None:
    evidence = _classification(
        source_record_id="",
        source_content_hash="a" * 64,
        source_quality_status="PROVISIONAL",
    )

    decision = validate_classification_evidence(evidence, as_of=CUTOFF)

    assert decision.state == EvidenceValidationState.INVALID
    assert decision.reason_codes == (
        EvidenceReason.CLASSIFICATION_REQUIRED_FIELD_MISSING,
        EvidenceReason.CLASSIFICATION_SOURCE_HASH_INVALID,
        EvidenceReason.CLASSIFICATION_SOURCE_LINEAGE_MISSING,
        EvidenceReason.CLASSIFICATION_SOURCE_QUALITY_NOT_VALIDATED,
    )


def test_valid_classification_decision_is_content_addressed_and_repeatable() -> None:
    evidence = _classification()

    first = validate_classification_evidence(evidence, as_of=CUTOFF)
    second = validate_classification_evidence(evidence, as_of=CUTOFF)

    assert first.state == EvidenceValidationState.VALIDATED
    assert first.reason_codes == ()
    assert first == second
    assert first.evidence_content_hash == second.evidence_content_hash
    assert first.decision_content_hash == second.decision_content_hash
    assert first.evidence_content_hash != first.decision_content_hash
    assert (
        first.persistence_scope
        == EvidencePersistenceScope.NEW_REVISION_OR_SNAPSHOT_ONLY
    )
    assert first.may_mutate_existing_evidence is False
    assert first.binding_authorized is True
    assert first.promotion_authorized is False


def test_provisional_price_rows_are_rejected_without_relabeling() -> None:
    provisional = _bar(date(2026, 7, 28), quality_status="PROVISIONAL")
    evidence = _series(provisional)

    decision = validate_daily_price_series(evidence, cutoff=CUTOFF)

    assert decision.state == EvidenceValidationState.INVALID
    assert decision.reason_codes == (
        EvidenceReason.PRICE_QUALITY_STATUS_NOT_VALIDATED,
    )
    assert evidence.bars[0].source_quality_status == "PROVISIONAL"
    assert decision.source_quality_statuses == ("PROVISIONAL",)
    assert decision.binding_authorized is False
    assert decision.promotion_authorized is False


def test_valid_completed_price_series_has_stable_evidence_and_decision_hashes() -> None:
    evidence = _series(
        _bar(date(2026, 7, 27)),
        _bar(date(2026, 7, 28)),
    )

    first = validate_daily_price_series(evidence, cutoff=CUTOFF)
    second = validate_daily_price_series(evidence, cutoff=CUTOFF)

    assert first.state == EvidenceValidationState.VALIDATED
    assert first.reason_codes == ()
    assert first.session_count == 2
    assert first.first_session == date(2026, 7, 27)
    assert first.last_session == date(2026, 7, 28)
    assert first == second
    assert first.evidence_content_hash == second.evidence_content_hash
    assert first.decision_content_hash == second.decision_content_hash
    assert (
        first.persistence_scope
        == EvidencePersistenceScope.NEW_REVISION_OR_SNAPSHOT_ONLY
    )
    assert first.may_mutate_existing_evidence is False
    assert first.binding_authorized is True
    assert first.promotion_authorized is False


def test_incomplete_or_future_price_session_cannot_pass_cutoff() -> None:
    future_incomplete = _bar(
        date(2026, 7, 30),
        session_complete=False,
    )
    evidence = replace(
        _series(future_incomplete),
        expected_completed_session=date(2026, 7, 30),
    )

    decision = validate_daily_price_series(evidence, cutoff=CUTOFF)

    assert decision.state == EvidenceValidationState.INVALID
    assert decision.reason_codes == (
        EvidenceReason.PRICE_SESSION_AFTER_CUTOFF,
        EvidenceReason.PRICE_SESSION_NOT_COMPLETE,
        EvidenceReason.PRICE_TIME_INVALID,
    )


def test_duplicate_revision_and_mixed_contract_evidence_are_explicitly_invalid() -> None:
    first = _bar(date(2026, 7, 28))
    conflicting = replace(
        first,
        adjustment_mode="UNADJUSTED",
        provider="other-provider",
        revision_number=0,
        selected_revision_is_latest_at_cutoff=False,
    )
    evidence = _series(first, conflicting)

    decision = validate_daily_price_series(evidence, cutoff=CUTOFF)

    assert decision.state == EvidenceValidationState.INVALID
    assert decision.reason_codes == (
        EvidenceReason.PRICE_ADJUSTMENT_MODE_MISMATCH,
        EvidenceReason.PRICE_DATES_NOT_STRICTLY_ORDERED,
        EvidenceReason.PRICE_DUPLICATE_SESSION_DATE,
        EvidenceReason.PRICE_PROVIDER_MISMATCH,
        EvidenceReason.PRICE_REVISION_INVALID,
        EvidenceReason.PRICE_REVISION_SELECTION_UNPROVEN,
    )
