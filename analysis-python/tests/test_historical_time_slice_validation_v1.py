from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from equity_analysis.historical_validation import (
    BenchmarkKind,
    EvidenceMode,
    HistoricalConclusion,
    HistoricalOutcome,
    HistoricalSignal,
    HistoricalTimeSlice,
    HistoricalValidationProtocol,
    TimePartition,
    UniverseMode,
    evaluate_time_slices,
)

DECISION = datetime(2020, 1, 31, 21, tzinfo=UTC)


def _signal(
    index: int,
    *,
    decision: datetime,
    evidence_mode: EvidenceMode = EvidenceMode.PIT_VERIFIED,
    positive_relation: bool = True,
) -> HistoricalSignal:
    score = Decimal(index * 4)
    direction = Decimal(index if positive_relation else 26 - index)
    security_return = direction / Decimal("100")
    return HistoricalSignal(
        security_id=f"security-{index:02d}",
        symbol=f"S{index:02d}",
        score=score,
        latest_input_available_at=decision - timedelta(days=1),
        membership_available_at=decision - timedelta(days=30),
        evidence_mode=evidence_mode,
        outcomes=(
            HistoricalOutcome(
                horizon_trading_days=20,
                entry_time=decision + timedelta(days=1),
                exit_time=decision + timedelta(days=29),
                security_return=security_return,
                market_benchmark_return=Decimal("0.01"),
                sector_benchmark_return=Decimal("0.015"),
            ),
            HistoricalOutcome(
                horizon_trading_days=252,
                entry_time=decision + timedelta(days=1),
                exit_time=decision + timedelta(days=365),
                security_return=security_return + Decimal("0.10"),
                market_benchmark_return=Decimal("0.05"),
                sector_benchmark_return=Decimal("0.06"),
            ),
        ),
    )


def _slice(
    index: int,
    *,
    evidence_mode: EvidenceMode = EvidenceMode.PIT_VERIFIED,
    universe_mode: UniverseMode = UniverseMode.HISTORICAL_MEMBERSHIP,
    positive_relation: bool = True,
) -> HistoricalTimeSlice:
    decision = DECISION + timedelta(days=index * 400)
    return HistoricalTimeSlice(
        slice_id=f"slice-{index}",
        decision_time=decision,
        partition=TimePartition.HOLDOUT,
        strategy_version="QC-v1.0.0",
        data_snapshot_hash=f"sha256:{index:064d}",
        universe_version="test-universe-v1",
        universe_mode=universe_mode,
        availability_policy_version="ACTUAL-FILING-AVAILABLE-v1",
        eligible_universe_count=25,
        signals=tuple(
            _signal(
                security_index,
                decision=decision,
                evidence_mode=evidence_mode,
                positive_relation=positive_relation,
            )
            for security_index in range(1, 26)
        ),
    )


def _protocol(*, minimum_holdout_slices: int = 4) -> HistoricalValidationProtocol:
    return HistoricalValidationProtocol(
        strategy_version="QC-v1.0.0",
        horizons_trading_days=(20, 252),
        primary_horizon_trading_days=252,
        benchmark_kind=BenchmarkKind.MARKET,
        minimum_holdout_slices=minimum_holdout_slices,
        minimum_securities_per_slice=20,
        bootstrap_iterations=200,
    )


def test_rejects_input_that_was_not_available_at_decision_time() -> None:
    item = _slice(0)
    first = item.signals[0]
    leaked = first.__class__(
        **{
            **first.__dict__,
            "latest_input_available_at": item.decision_time + timedelta(seconds=1),
        }
    )
    broken = item.__class__(**{**item.__dict__, "signals": (leaked, *item.signals[1:])})

    with pytest.raises(ValueError, match="LOOK_AHEAD_INPUT"):
        evaluate_time_slices((broken,), _protocol(minimum_holdout_slices=1))


def test_strict_historical_slices_can_reach_robust_signal_conclusion() -> None:
    report = evaluate_time_slices(
        tuple(_slice(index) for index in range(4)),
        _protocol(),
    )

    assert report.conclusion == HistoricalConclusion.ROBUST_HISTORICAL_SIGNAL
    assert report.calculation_validated is True
    assert report.statistical_edge_proven == "NOT_ESTABLISHED"
    primary = next(
        item
        for item in report.aggregate_metrics
        if item.partition == TimePartition.HOLDOUT
        and item.horizon_trading_days == 252
    )
    assert primary.eligible_slice_count == 4
    assert primary.median_rank_information_coefficient == Decimal("1.00000000")
    assert primary.spread_bootstrap_lower_90 is not None
    assert primary.spread_bootstrap_lower_90 > 0


def test_approximate_current_universe_is_capped_at_directionally_positive() -> None:
    report = evaluate_time_slices(
        tuple(
            _slice(
                index,
                evidence_mode=EvidenceMode.CONSERVATIVE_LAG,
                universe_mode=UniverseMode.CURRENT_UNIVERSE_RETROSPECTIVE,
            )
            for index in range(4)
        ),
        _protocol(),
    )

    assert report.conclusion == HistoricalConclusion.DIRECTIONALLY_POSITIVE
    assert report.evidence_modes == (EvidenceMode.CONSERVATIVE_LAG,)
    assert report.universe_modes == (UniverseMode.CURRENT_UNIVERSE_RETROSPECTIVE,)


def test_negative_rank_relation_is_unfavorable() -> None:
    report = evaluate_time_slices(
        tuple(_slice(index, positive_relation=False) for index in range(4)),
        _protocol(),
    )

    assert report.conclusion == HistoricalConclusion.UNFAVORABLE


def test_reports_top_bucket_drawdown_protection_separately_from_return() -> None:
    item = _slice(0)
    signals = tuple(
        signal.__class__(
            **{
                **signal.__dict__,
                "outcomes": tuple(
                    outcome.__class__(
                        **{
                            **outcome.__dict__,
                            "maximum_drawdown": -(
                                Decimal("0.30")
                                - signal.score / Decimal("500")
                            ),
                        }
                    )
                    for outcome in signal.outcomes
                ),
            }
        )
        for signal in item.signals
    )
    adjusted = item.__class__(**{**item.__dict__, "signals": signals})

    report = evaluate_time_slices(
        (adjusted,),
        _protocol(minimum_holdout_slices=1),
    )

    primary = next(
        result
        for result in report.aggregate_metrics
        if result.partition == TimePartition.HOLDOUT
        and result.horizon_trading_days == 252
    )
    assert primary.mean_top_maximum_drawdown is not None
    assert primary.mean_bottom_maximum_drawdown is not None
    assert primary.mean_top_minus_bottom_drawdown_protection is not None
    assert primary.mean_top_minus_bottom_drawdown_protection > 0


def test_small_holdout_remains_insufficient_sample() -> None:
    report = evaluate_time_slices((_slice(0),), _protocol())

    assert report.conclusion == HistoricalConclusion.INSUFFICIENT_SAMPLE


def test_sector_benchmark_requires_sector_outcome() -> None:
    item = _slice(0)
    first = item.signals[0]
    first_outcomes = tuple(
        outcome.__class__(
            **{
                **outcome.__dict__,
                "sector_benchmark_return": None,
            }
        )
        for outcome in first.outcomes
    )
    missing_sector = first.__class__(
        **{**first.__dict__, "outcomes": first_outcomes}
    )
    adjusted = item.__class__(
        **{**item.__dict__, "signals": (missing_sector, *item.signals[1:])}
    )
    protocol = _protocol(minimum_holdout_slices=1).__class__(
        **{
            **_protocol(minimum_holdout_slices=1).__dict__,
            "benchmark_kind": BenchmarkKind.SECTOR,
        }
    )

    report = evaluate_time_slices((adjusted,), protocol)

    primary = next(
        result
        for result in report.aggregate_metrics
        if result.partition == TimePartition.HOLDOUT
        and result.horizon_trading_days == 252
    )
    assert primary.eligible_slice_count == 1
    assert primary.total_usable_signals == 24


def test_does_not_mix_availability_policies_in_one_report() -> None:
    first = _slice(0)
    second = _slice(1).__class__(
        **{
            **_slice(1).__dict__,
            "availability_policy_version": "QUARTER-90-ANNUAL-150-v1",
        }
    )

    with pytest.raises(ValueError, match="exactly one availability policy"):
        evaluate_time_slices(
            (first, second),
            _protocol(minimum_holdout_slices=1),
        )
