from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from equity_analysis.daily_refresh.evidence_validation_v1 import (
    DailyPriceEvidenceBar,
    DailyPriceSeriesEvidence,
)
from equity_analysis.daily_refresh.price_quality_promotion_v1 import (
    PRICE_QUALITY_PROMOTION_POLICY_HASH,
    PRICE_QUALITY_PROMOTION_POLICY_VERSION,
    CompletedSessionCalendarEvidence,
    PriceQualityPromotionEvidence,
    PromotionCoverageEvidence,
    PromotionReason,
    PromotionScopeMode,
    PromotionState,
    ReconciliationState,
    build_completed_session_calendar_evidence_hash,
    build_population_coverage_hash,
    build_revision_selection_manifest_hash,
    build_source_manifest_hash,
    build_transport_manifest_hash,
    evaluate_price_quality_promotion,
)

CUTOFF = datetime(2026, 7, 29, 2, 57, tzinfo=UTC)
SOURCE_HASH = "sha256:" + "a" * 64
TRANSPORT_CONTENT_HASH = "sha256:" + "b" * 64
POPULATION_HASH = "sha256:" + "d" * 64
ACTION_HASH = "sha256:" + "e" * 64
ADJUSTMENT_HASH = "sha256:" + "f" * 64
CALENDAR_SOURCE_HASH = "sha256:" + "2" * 64


def _bar(
    trading_date: date,
    *,
    source_quality_status: str = "PROVISIONAL",
    session_complete: bool = True,
    selected_revision_is_latest_at_cutoff: bool = True,
) -> DailyPriceEvidenceBar:
    available_at = datetime.combine(
        trading_date,
        datetime.min.time(),
        tzinfo=UTC,
    ) + timedelta(hours=22)
    return DailyPriceEvidenceBar(
        security_id="security-1",
        trading_date=trading_date,
        open_price=Decimal("99"),
        high_price=Decimal("102"),
        low_price=Decimal("98"),
        close_price=Decimal("101"),
        adjusted_close=Decimal("101"),
        volume=1_000_000,
        adjustment_mode="TOTAL_RETURN_ADJUSTED",
        provider="yfinance",
        provider_schema_version="yfinance-chart-v1",
        parser_version="yfinance-parser-v1",
        normalization_version="market-normalization-v1",
        revision_number=1,
        source_revision_status="AS_REPORTED",
        selected_revision_is_latest_at_cutoff=(
            selected_revision_is_latest_at_cutoff
        ),
        source_record_id=f"source-{trading_date.isoformat()}",
        source_content_hash=SOURCE_HASH,
        source_quality_status=source_quality_status,
        available_at=available_at,
        ingested_at=available_at + timedelta(minutes=10),
        session_complete=session_complete,
    )


def _series(
    *,
    source_quality_status: str = "PROVISIONAL",
    session_complete: bool = True,
    selected_revision_is_latest_at_cutoff: bool = True,
) -> DailyPriceSeriesEvidence:
    return DailyPriceSeriesEvidence(
        security_id="security-1",
        expected_provider="yfinance",
        expected_adjustment_mode="TOTAL_RETURN_ADJUSTED",
        expected_completed_session=date(2026, 7, 28),
        bars=(
            _bar(
                date(2026, 7, 27),
                source_quality_status=source_quality_status,
                selected_revision_is_latest_at_cutoff=(
                    selected_revision_is_latest_at_cutoff
                ),
            ),
            _bar(
                date(2026, 7, 28),
                source_quality_status=source_quality_status,
                session_complete=session_complete,
                selected_revision_is_latest_at_cutoff=(
                    selected_revision_is_latest_at_cutoff
                ),
            ),
        ),
    )


def _calendar() -> CompletedSessionCalendarEvidence:
    reviewed_at = CUTOFF - timedelta(minutes=5)
    evidence_hash = build_completed_session_calendar_evidence_hash(
        authority="XNYS_OFFICIAL_TRADING_CALENDAR",
        calendar_version="US-EQUITY-CALENDAR-v1",
        completed_session=date(2026, 7, 28),
        source_content_hash=CALENDAR_SOURCE_HASH,
        reviewed_at=reviewed_at,
    )
    return CompletedSessionCalendarEvidence(
        authority="XNYS_OFFICIAL_TRADING_CALENDAR",
        calendar_version="US-EQUITY-CALENDAR-v1",
        completed_session=date(2026, 7, 28),
        source_content_hash=CALENDAR_SOURCE_HASH,
        reviewed_at=reviewed_at,
        evidence_hash=evidence_hash,
    )


def _coverage(
    *,
    scope_mode: PromotionScopeMode = PromotionScopeMode.PER_SECURITY,
) -> PromotionCoverageEvidence:
    ids = (
        ("security-1",)
        if scope_mode == PromotionScopeMode.PER_SECURITY
        else ("security-1", "security-2")
    )
    population_size = len(ids)
    common_cutoff = (
        None
        if scope_mode == PromotionScopeMode.PER_SECURITY
        else CUTOFF
    )
    coverage_hash = build_population_coverage_hash(
        scope_mode=scope_mode,
        frozen_population_hash=POPULATION_HASH,
        population_size=population_size,
        covered_security_ids=ids,
        common_cutoff=common_cutoff,
    )
    return PromotionCoverageEvidence(
        scope_mode=scope_mode,
        frozen_population_hash=POPULATION_HASH,
        population_size=population_size,
        covered_security_ids=ids,
        common_cutoff=common_cutoff,
        coverage_hash=coverage_hash,
    )


def _evidence(
    *,
    series: DailyPriceSeriesEvidence | None = None,
    coverage: PromotionCoverageEvidence | None = None,
    corporate_action_state: ReconciliationState = ReconciliationState.RECONCILED,
    corporate_action_hash: str | None = ACTION_HASH,
) -> PriceQualityPromotionEvidence:
    selected_series = series or _series()
    transport_content_hashes = (TRANSPORT_CONTENT_HASH,)
    source_content_hashes = (SOURCE_HASH,)
    return PriceQualityPromotionEvidence(
        series=selected_series,
        reviewed_cutoff=CUTOFF,
        reviewer="deterministic-price-quality-controller",
        calendar=_calendar(),
        coverage=coverage or _coverage(),
        transport_manifest_hash=build_transport_manifest_hash(
            security_id=selected_series.security_id,
            reviewed_cutoff=CUTOFF,
            transport_content_hashes=transport_content_hashes,
        ),
        transport_content_hashes=transport_content_hashes,
        source_manifest_hash=build_source_manifest_hash(
            security_id=selected_series.security_id,
            expected_completed_session=(
                selected_series.expected_completed_session
            ),
            source_content_hashes=source_content_hashes,
        ),
        source_content_hashes=source_content_hashes,
        corporate_action_state=corporate_action_state,
        corporate_action_reconciliation_hash=corporate_action_hash,
        adjustment_state=ReconciliationState.RECONCILED,
        adjustment_reconciliation_hash=ADJUSTMENT_HASH,
        revision_selection_manifest_hash=(
            build_revision_selection_manifest_hash(
                series=selected_series,
                reviewed_cutoff=CUTOFF,
            )
        ),
        promotion_policy_version=PRICE_QUALITY_PROMOTION_POLICY_VERSION,
        promotion_policy_hash=PRICE_QUALITY_PROMOTION_POLICY_HASH,
    )


def test_complete_evidence_authorizes_only_a_new_validated_revision() -> None:
    evidence = _evidence()

    first = evaluate_price_quality_promotion(evidence)
    second = evaluate_price_quality_promotion(evidence)

    assert first.state == PromotionState.AUTHORIZED_NEW_REVISION
    assert first.reason_codes == ()
    assert first.structural_validation_passed is True
    assert first.prior_quality_statuses == ("PROVISIONAL",)
    assert first.new_revision_binding is not None
    assert first.new_revision_binding.prior_quality_status == "PROVISIONAL"
    assert first.new_revision_binding.new_quality_status == "VALIDATED"
    assert first.new_revision_binding.minimum_new_revision_number == 2
    assert tuple(
        item.minimum_new_revision_number
        for item in first.new_revision_binding.session_revision_bindings
    ) == (2, 2)
    assert first.new_revision_binding.may_mutate_existing_evidence is False
    assert first.may_mutate_existing_evidence is False
    assert evidence.series.bars[0].source_quality_status == "PROVISIONAL"
    assert first == second
    assert first.promotion_evidence_hash == second.promotion_evidence_hash
    assert first.decision_content_hash == second.decision_content_hash


def test_complete_population_common_cutoff_scope_is_supported() -> None:
    evidence = _evidence(
        coverage=_coverage(
            scope_mode=PromotionScopeMode.COMPLETE_POPULATION_COMMON_CUTOFF
        )
    )

    decision = evaluate_price_quality_promotion(evidence)

    assert decision.state == PromotionState.AUTHORIZED_NEW_REVISION
    assert decision.reason_codes == ()


def test_missing_corporate_action_proof_blocks_promotion() -> None:
    evidence = _evidence(
        corporate_action_state=ReconciliationState.MISSING,
        corporate_action_hash=None,
    )

    decision = evaluate_price_quality_promotion(evidence)

    assert decision.state == PromotionState.BLOCKED
    assert decision.reason_codes == (
        PromotionReason.CORPORATE_ACTION_RECONCILIATION_MISSING,
    )
    assert decision.new_revision_binding is None


def test_unknown_or_not_verified_source_status_is_never_promoted() -> None:
    for source_status in ("UNKNOWN", "NOT_VERIFIED"):
        decision = evaluate_price_quality_promotion(
            _evidence(series=_series(source_quality_status=source_status))
        )

        assert decision.state == PromotionState.BLOCKED
        assert PromotionReason.SOURCE_STATUS_NOT_PROVISIONAL in decision.reason_codes
        assert decision.new_revision_binding is None


def test_non_quality_ohlcv_blocker_cannot_be_bypassed_by_promotion_evidence() -> None:
    evidence = _evidence(series=_series(session_complete=False))

    decision = evaluate_price_quality_promotion(evidence)

    assert decision.state == PromotionState.BLOCKED
    assert PromotionReason.OHLCV_VALIDATION_BLOCKED in decision.reason_codes
    assert decision.structural_validation_passed is False
    assert decision.new_revision_binding is None


def test_unproven_latest_revision_and_policy_mismatch_both_block() -> None:
    evidence = replace(
        _evidence(
            series=_series(selected_revision_is_latest_at_cutoff=False)
        ),
        promotion_policy_hash="sha256:" + "9" * 64,
    )

    decision = evaluate_price_quality_promotion(evidence)

    assert decision.state == PromotionState.BLOCKED
    assert PromotionReason.OHLCV_VALIDATION_BLOCKED in decision.reason_codes
    assert PromotionReason.PROMOTION_POLICY_BINDING_INVALID in decision.reason_codes
    assert PromotionReason.REVISION_SELECTION_PROOF_INVALID in decision.reason_codes
    assert decision.new_revision_binding is None


def test_bad_coverage_hash_and_future_calendar_review_are_explicit_blockers() -> None:
    coverage = replace(
        _coverage(),
        coverage_hash="sha256:" + "8" * 64,
    )
    calendar = _calendar()
    future_calendar = replace(
        calendar,
        reviewed_at=CUTOFF + timedelta(minutes=1),
    )
    evidence = replace(
        _evidence(coverage=coverage),
        calendar=future_calendar,
    )

    decision = evaluate_price_quality_promotion(evidence)

    assert decision.state == PromotionState.BLOCKED
    assert PromotionReason.COMPLETED_SESSION_CALENDAR_INVALID in decision.reason_codes
    assert PromotionReason.POPULATION_COVERAGE_HASH_INVALID in decision.reason_codes
    assert decision.new_revision_binding is None
