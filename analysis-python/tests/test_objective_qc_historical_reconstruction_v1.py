from __future__ import annotations

from datetime import date, timedelta

from equity_analysis.historical_validation.objective_qc_reconstruction_v1 import (
    HistoricalQcEvidenceInventory,
    ReconstructionBlocker,
    ReconstructionConfig,
    assess_reconstruction_capacity,
    plan_stratified_decision_dates,
)
from equity_analysis.historical_validation.sampling_v1 import HistoricalAgeBand


def _weekday_sessions(start: date, end: date) -> tuple[date, ...]:
    current = start
    sessions = []
    while current <= end:
        if current.weekday() < 5:
            sessions.append(current)
        current += timedelta(days=1)
    return tuple(sessions)


def test_stratified_plan_is_order_independent_and_seeded() -> None:
    sessions = _weekday_sessions(date(2015, 1, 1), date(2026, 7, 29))
    config = ReconstructionConfig(
        anchor_date=date(2026, 7, 29),
        dates_per_stratum=4,
    )

    first = plan_stratified_decision_dates(sessions, config)
    second = plan_stratified_decision_dates(tuple(reversed(sessions)), config)

    assert first == second
    assert [item.stratum for item in first] == [
        HistoricalAgeBand.RECENT,
        HistoricalAgeBand.MEDIUM,
        HistoricalAgeBand.OLDER,
    ]
    assert [len(item.decisions) for item in first] == [4, 4, 4]
    assert all(
        decision.decision_date.weekday() < 5
        for plan in first
        for decision in plan.decisions
    )


def test_plan_reports_horizon_support_without_using_outcome_values() -> None:
    sessions = _weekday_sessions(date(2025, 7, 1), date(2026, 7, 29))
    config = ReconstructionConfig(
        anchor_date=date(2026, 7, 29),
        dates_per_stratum=8,
    )

    plans = plan_stratified_decision_dates(sessions, config)
    recent = plans[0]

    assert recent.available_month_count == 7
    assert recent.decisions == ()
    assert plans[1].available_month_count == 1
    assert plans[1].decisions == ()
    assert plans[2].decisions == ()


def test_capacity_fails_closed_for_current_local_evidence_shape() -> None:
    inventory = HistoricalQcEvidenceInventory(
        benchmark_session_dates=_weekday_sessions(
            date(2025, 7, 16),
            date(2026, 7, 28),
        ),
        priced_security_count=61,
        fundamental_security_count=56,
        fundamental_fact_count=157_641,
        facts_with_period_start_count=0,
        proven_discrete_quarter_fact_count=0,
        historical_market_value_security_count=0,
    )
    config = ReconstructionConfig(anchor_date=date(2026, 7, 28))

    result = assess_reconstruction_capacity(inventory, config)

    assert result.score_reconstruction_authorized is False
    assert result.pit_verified_claimed is False
    assert result.historical_membership_claimed is False
    assert ReconstructionBlocker.FROZEN_QC_COHORT_TOO_SMALL in result.blockers
    assert (
        ReconstructionBlocker.FUNDAMENTAL_PERIOD_START_UNAVAILABLE
        in result.blockers
    )
    assert (
        ReconstructionBlocker.DISCRETE_QUARTER_SEMANTICS_UNAVAILABLE
        in result.blockers
    )
    assert (
        ReconstructionBlocker.HISTORICAL_MARKET_VALUE_UNAVAILABLE
        in result.blockers
    )
    assert ReconstructionBlocker.OLDER_DECISION_DATES_UNAVAILABLE in result.blockers
    assert result.network_requests_executed is False


def test_capacity_does_not_authorize_without_membership_evidence() -> None:
    sessions = _weekday_sessions(date(2015, 1, 1), date(2026, 7, 29))
    inventory = HistoricalQcEvidenceInventory(
        benchmark_session_dates=sessions,
        priced_security_count=120,
        fundamental_security_count=120,
        fundamental_fact_count=100_000,
        facts_with_period_start_count=80_000,
        proven_discrete_quarter_fact_count=70_000,
        historical_market_value_security_count=120,
        historical_membership_proven=False,
    )
    result = assess_reconstruction_capacity(
        inventory,
        ReconstructionConfig(anchor_date=date(2026, 7, 29)),
    )

    assert result.blockers == (
        ReconstructionBlocker.HISTORICAL_MEMBERSHIP_UNPROVEN,
    )
    assert result.score_reconstruction_authorized is False


def test_frozen_general_cohort_minimum_cannot_be_relaxed() -> None:
    try:
        ReconstructionConfig(
            anchor_date=date(2026, 7, 29),
            minimum_qc_cohort=55,
        )
    except ValueError as error:
        assert str(error) == "Frozen QC general-company minimum cannot change"
    else:
        raise AssertionError("Expected the frozen QC cohort guard to reject 55")
