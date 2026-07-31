from __future__ import annotations

from dataclasses import asdict, replace
from datetime import UTC, date, datetime, timedelta

import pytest

from equity_analysis.tactical.contracts_v22 import (
    Actionability,
    EventEvidenceV22,
    EventRiskLevel,
    EvidenceState,
    SeriesEvidenceV22,
    SetupThesis,
    TacticalBarV22,
    TacticalContextV22,
    TacticalHorizon,
)
from equity_analysis.tactical.signal_v22 import (
    evaluate_tactical_signal_v22,
    serialize_tactical_assessment_v22,
)

SOURCE_HASH = "A" * 64
MAPPING_HASH = "B" * 64


def _bars(
    returns: list[float],
    *,
    weak_final_close: bool = False,
    adjustment_transition: bool = False,
) -> tuple[TacticalBarV22, ...]:
    trading_date = date(2025, 1, 2)
    price = 100.0
    result: list[TacticalBarV22] = [
        TacticalBarV22(
            trading_date=trading_date,
            open_price=99.8,
            high_price=100.5,
            low_price=99.5,
            close_price=price,
            volume=5_000_000,
        )
    ]
    for index, daily_return in enumerate(returns, start=1):
        trading_date += timedelta(days=1)
        open_price = price
        close_price = price * (1.0 + daily_return)
        high_price = max(open_price, close_price) * 1.005
        low_price = min(open_price, close_price) * 0.995
        if weak_final_close and index == len(returns):
            high_price = open_price * 1.005
            low_price = close_price * 0.995
        result.append(
            TacticalBarV22(
                trading_date=trading_date,
                open_price=open_price,
                high_price=high_price,
                low_price=low_price,
                close_price=close_price,
                volume=5_000_000 + index * 1_000,
                adjustment_factor=(
                    0.5 if adjustment_transition and index == len(returns) else 1.0
                ),
            )
        )
        price = close_price
    return tuple(result)


def _series(
    bars: tuple[TacticalBarV22, ...],
    *,
    state: EvidenceState = EvidenceState.VALID,
) -> SeriesEvidenceV22:
    if state != EvidenceState.VALID:
        return SeriesEvidenceV22(
            state=state,
            provider=None,
            source_hash=None,
            available_at=None,
            ingested_at=None,
        )
    observed_at = datetime.combine(
        bars[-1].trading_date,
        datetime.min.time(),
        tzinfo=UTC,
    ) + timedelta(hours=22)
    return SeriesEvidenceV22(
        state=state,
        provider="fixture",
        source_hash=SOURCE_HASH,
        available_at=observed_at,
        ingested_at=observed_at,
        bars=bars,
    )


def _event(
    *,
    state: EvidenceState = EvidenceState.VALID,
    risk_level: EventRiskLevel | None = EventRiskLevel.NONE,
) -> EventEvidenceV22:
    if state != EvidenceState.VALID:
        return EventEvidenceV22(
            state=state,
            risk_level=None,
            source_hash=None,
            available_at=None,
            ingested_at=None,
        )
    return EventEvidenceV22(
        state=state,
        risk_level=risk_level,
        source_hash=SOURCE_HASH,
        available_at=datetime(2025, 1, 1, tzinfo=UTC),
        ingested_at=datetime(2025, 1, 1, tzinfo=UTC),
        event_type="EARNINGS_CALENDAR",
    )


def _context(
    security_returns: list[float],
    *,
    market_returns: list[float] | None = None,
    sector_returns: list[float] | None = None,
    event: EventEvidenceV22 | None = None,
    weak_final_close: bool = False,
    adjustment_transition: bool = False,
) -> TacticalContextV22:
    market_returns = market_returns or [0.0003] * len(security_returns)
    sector_returns = sector_returns or [0.0004] * len(security_returns)
    security = _bars(
        security_returns,
        weak_final_close=weak_final_close,
        adjustment_transition=adjustment_transition,
    )
    market = _bars(market_returns)
    sector = _bars(sector_returns)
    cutoff = datetime.combine(
        security[-1].trading_date + timedelta(days=1),
        datetime.min.time(),
        tzinfo=UTC,
    )
    return TacticalContextV22(
        security_id="SECURITY-1",
        decision_cutoff=cutoff,
        as_of_date=security[-1].trading_date,
        security=_series(security),
        market_benchmark_id="SPY",
        market=_series(market),
        sector_benchmark_id="XLK",
        sector=_series(sector),
        event=event or _event(),
        sector_mapping_version="SECTOR-MAP-v1",
        sector_mapping_hash=MAPPING_HASH,
    )


def _horizon(result, horizon: TacticalHorizon):
    return next(item for item in result.horizons if item.horizon == horizon)


def test_flat_series_does_not_force_a_tactical_thesis() -> None:
    result = evaluate_tactical_signal_v22(_context([0.0] * 149))

    assert all(item.selected_thesis == SetupThesis.NONE for item in result.horizons)
    assert all(item.actionability == Actionability.NO_SETUP for item in result.horizons)


def test_horizons_can_select_different_theses() -> None:
    returns = [0.004] * 129 + [-0.025] * 15 + [0.05] * 5
    result = evaluate_tactical_signal_v22(_context(returns))

    one_week = _horizon(result, TacticalHorizon.ONE_WEEK)
    three_months = _horizon(result, TacticalHorizon.THREE_MONTHS)

    assert one_week.selected_thesis == SetupThesis.NONE
    assert three_months.selected_thesis == SetupThesis.CONTINUATION


def test_falling_knife_gate_blocks_oversold_mean_reversion() -> None:
    returns = [0.0005] * 134 + [-0.045] * 15
    result = evaluate_tactical_signal_v22(
        _context(returns, weak_final_close=True)
    )
    one_week = _horizon(result, TacticalHorizon.ONE_WEEK)

    assert result.mean_reversion_potential.score is not None
    assert result.mean_reversion_potential.score >= 60
    assert result.falling_knife_risk.score is not None
    assert result.falling_knife_risk.score >= 70
    assert not one_week.mean_reversion_eligible
    assert one_week.actionability != Actionability.ENTRY


def test_chase_gate_keeps_continuation_but_requires_pullback() -> None:
    returns = [0.001] * 139 + [0.08] * 10
    result = evaluate_tactical_signal_v22(_context(returns))
    one_week = _horizon(result, TacticalHorizon.ONE_WEEK)

    assert one_week.selected_thesis == SetupThesis.CONTINUATION
    assert result.chase_risk.score is not None
    assert result.chase_risk.score >= 60
    assert one_week.actionability == Actionability.WAIT_FOR_PULLBACK


def test_negative_sector_regime_reduces_continuation_independently() -> None:
    security_returns = [0.0018] * 149
    favorable = evaluate_tactical_signal_v22(
        _context(
            security_returns,
            market_returns=[0.0005] * 149,
            sector_returns=[0.0008] * 149,
        )
    )
    adverse = evaluate_tactical_signal_v22(
        _context(
            security_returns,
            market_returns=[0.0005] * 149,
            sector_returns=[-0.002] * 149,
        )
    )

    assert adverse.sector_regime.score is not None
    assert favorable.sector_regime.score is not None
    assert adverse.sector_regime.score < favorable.sector_regime.score
    assert adverse.sector_relative_strength.score is not None
    assert favorable.sector_relative_strength.score is not None
    assert (
        adverse.sector_relative_strength.score
        > favorable.sector_relative_strength.score
    )
    assert (
        _horizon(adverse, TacticalHorizon.THREE_MONTHS).continuation_score
        != _horizon(favorable, TacticalHorizon.THREE_MONTHS).continuation_score
    )


def test_missing_event_evidence_is_not_neutral_and_caps_actionability() -> None:
    result = evaluate_tactical_signal_v22(
        _context(
            [0.0018] * 149,
            event=_event(state=EvidenceState.MISSING),
        )
    )
    one_week = _horizon(result, TacticalHorizon.ONE_WEEK)

    assert result.event_risk_state == EvidenceState.MISSING
    assert "deterministic_event_risk" in one_week.missing_inputs
    assert one_week.actionability in {
        Actionability.WATCH_ONLY,
        Actionability.NO_SETUP,
    }
    assert one_week.maximum_risk_unit_multiplier == 0.0


def test_assessment_hash_and_serialization_are_deterministic() -> None:
    context = _context([0.001] * 149)

    first = evaluate_tactical_signal_v22(context)
    second = evaluate_tactical_signal_v22(context)

    assert first.input_hash == second.input_hash
    assert serialize_tactical_assessment_v22(first) == (
        serialize_tactical_assessment_v22(second)
    )
    assert first.version == "TACTICAL-SIGNAL-v2.2.0"
    assert first.effective_from == "NEXT_COMPLETED_SESSION_OPEN"
    assert first.signal_ttl_completed_sessions == 1
    assert "ai_overlay" not in asdict(first)
    assert "ai_narrative" not in asdict(first)


def test_future_available_evidence_is_rejected() -> None:
    context = _context([0.001] * 149)
    future_security = replace(
        context.security,
        available_at=context.decision_cutoff + timedelta(seconds=1),
    )

    with pytest.raises(ValueError, match="not available"):
        evaluate_tactical_signal_v22(
            replace(context, security=future_security)
        )


def test_incomplete_session_is_rejected() -> None:
    context = _context([0.001] * 149)
    incomplete = replace(context.security.bars[-1], session_complete=False)
    security = replace(
        context.security,
        bars=(*context.security.bars[:-1], incomplete),
    )

    with pytest.raises(ValueError, match="incomplete"):
        evaluate_tactical_signal_v22(replace(context, security=security))


def test_missing_sector_is_preserved_as_insufficient_data() -> None:
    context = _context([0.001] * 149)
    result = evaluate_tactical_signal_v22(
        replace(
            context,
            sector_benchmark_id=None,
            sector=_series((), state=EvidenceState.MISSING),
        )
    )

    assert result.sector_regime.state == EvidenceState.MISSING
    assert all(
        item.actionability == Actionability.INSUFFICIENT_DATA
        for item in result.horizons
    )
    assert all(item.opportunity_score is None for item in result.horizons)


def test_adjustment_transition_invalidates_liquidity_and_blocks_entry() -> None:
    result = evaluate_tactical_signal_v22(
        _context([0.0018] * 149, adjustment_transition=True)
    )

    assert result.liquidity.state == EvidenceState.INVALID
    assert all(
        item.actionability
        in {
            Actionability.RISK_BLOCKED,
            Actionability.NO_SETUP,
            Actionability.WATCH_ONLY,
        }
        for item in result.horizons
    )
