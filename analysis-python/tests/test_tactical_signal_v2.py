from datetime import date, timedelta

import pytest

from equity_analysis.tactical.signal_v2 import (
    Actionability,
    EntryStage,
    LegacyTacticalState,
    PriorReversalContext,
    SetupType,
    TacticalBar,
    evaluate_tactical_signal,
    serialize_tactical_assessment,
)
from equity_analysis.tactical.walk_forward_v2 import evaluate_walk_forward


def bars(
    daily_returns: list[float],
    *,
    start: float = 100.0,
    volume: int = 2_000_000,
    start_date: date = date(2025, 1, 1),
) -> tuple[TacticalBar, ...]:
    price = start
    result: list[TacticalBar] = []
    for index, daily_return in enumerate(daily_returns):
        prior = price
        price *= 1 + daily_return
        result.append(
            TacticalBar(
                trading_date=start_date + timedelta(days=index),
                open_price=prior,
                high_price=max(prior, price) * 1.005,
                low_price=min(prior, price) * 0.995,
                close_price=price,
                volume=volume,
            )
        )
    return tuple(result)


def replace_last(
    source: tuple[TacticalBar, ...],
    *,
    open_price: float,
    high_price: float,
    low_price: float,
    close_price: float,
    volume: int,
) -> tuple[TacticalBar, ...]:
    prior = source[-1]
    return source[:-1] + (
        TacticalBar(
            trading_date=prior.trading_date,
            open_price=open_price,
            high_price=high_price,
            low_price=low_price,
            close_price=close_price,
            volume=volume,
        ),
    )


def test_strong_trend_remains_confirmed_momentum() -> None:
    security = bars([0.004] * 90)
    benchmark = bars([0.0005] * 90)

    result = evaluate_tactical_signal(security, benchmark)

    assert result.setup_type == SetupType.MOMENTUM
    assert result.entry_stage == EntryStage.CONFIRMED
    assert result.actionability == Actionability.ENTRY
    assert result.decision_domain == "SHORT_TERM_SPECULATION"
    assert result.effective_from == "NEXT_SESSION_OPEN"


def test_gradual_52_week_breakout_is_not_automatically_penalized() -> None:
    security = bars([0.0015] * 260)
    benchmark = bars([0.0004] * 260)

    result = evaluate_tactical_signal(security, benchmark)

    assert security[-1].close_price > max(bar.close_price for bar in security[:-1])
    assert result.setup_type == SetupType.MOMENTUM
    assert result.entry_stage == EntryStage.CONFIRMED
    assert result.momentum_extension_risk_score < 70
    assert result.actionability == Actionability.ENTRY


def test_overextended_breakout_is_confirmed_but_waits_for_pullback() -> None:
    security = bars([0.001] * 255 + [0.04] * 5)
    benchmark = bars([0.0004] * 260)

    result = evaluate_tactical_signal(security, benchmark)

    assert result.setup_type == SetupType.MOMENTUM
    assert result.entry_stage == EntryStage.CONFIRMED
    assert result.horizons[0].outlook == "FAVORABLE"
    assert result.momentum_extension_risk_score >= 70
    assert result.actionability == Actionability.WAIT_FOR_PULLBACK
    assert result.maximum_risk_unit_multiplier == 0.0
    assert result.legacy_state == LegacyTacticalState.WATCH_FOR_CONFIRMATION


def test_healthy_breakout_retains_entry_actionability() -> None:
    security = bars([0.0007] * 250 + [0.004] * 10)
    benchmark = bars([0.0004] * 260)

    result = evaluate_tactical_signal(security, benchmark)

    assert result.setup_type == SetupType.MOMENTUM
    assert result.entry_stage == EntryStage.CONFIRMED
    assert result.momentum_extension_risk_score < 70
    assert result.entry_value_score >= 60
    assert result.actionability == Actionability.ENTRY
    assert result.maximum_risk_unit_multiplier == 1.0


def test_severe_decline_can_raise_bounce_potential_without_authorizing_entry() -> None:
    security = bars([0.002] * 65 + [-0.025] * 25)
    benchmark = bars([0.0002] * 90)

    result = evaluate_tactical_signal(security, benchmark)

    assert result.setup_type == SetupType.MEAN_REVERSION
    assert result.bounce_potential_score > result.entry_timing_score
    assert result.actionability not in {
        Actionability.LIMITED_ENTRY,
        Actionability.ENTRY,
    }
    assert result.falling_knife_risk_score >= 70


def test_bullish_low_rejection_improves_timing_before_ma20_recovery() -> None:
    base = bars([0.001] * 70 + [-0.018] * 9 + [0.0])
    prior_close = base[-2].close_price
    security = replace_last(
        base,
        open_price=prior_close * 0.96,
        high_price=prior_close * 1.015,
        low_price=prior_close * 0.94,
        close_price=prior_close * 1.005,
        volume=5_000_000,
    )
    benchmark = bars([0.0002] * len(security))

    result = evaluate_tactical_signal(security, benchmark)

    assert result.setup_type == SetupType.MEAN_REVERSION
    assert result.bounce_potential_score >= 60
    assert result.reversal_trigger_score >= 50
    assert result.entry_stage in {
        EntryStage.PROBE_ELIGIBLE,
        EntryStage.CONFIRMED,
    }
    assert result.maximum_risk_unit_multiplier in {0.25, 1.0}
    assert result.entry_stage_confidence in {"LOW", "MEDIUM", "HIGH"}
    assert security[-1].close_price < sum(
        bar.close_price for bar in security[-20:]
    ) / 20
    assert result.entry_value_score == result.payoff_asymmetry_score


def test_weak_high_volume_close_does_not_confirm_reversal() -> None:
    base = bars([0.001] * 70 + [-0.018] * 9 + [0.0])
    prior_close = base[-2].close_price
    security = replace_last(
        base,
        open_price=prior_close,
        high_price=prior_close * 1.01,
        low_price=prior_close * 0.90,
        close_price=prior_close * 0.905,
        volume=8_000_000,
    )
    benchmark = bars([0.0002] * len(security))

    result = evaluate_tactical_signal(security, benchmark)

    assert result.reversal_trigger_score < 50
    assert result.actionability not in {
        Actionability.LIMITED_ENTRY,
        Actionability.ENTRY,
    }


def test_zero_volume_pseudo_session_and_unmatched_dates_are_removed() -> None:
    security = list(bars([0.002] * 40))
    benchmark = list(bars([0.001] * 40))
    pseudo = security[20]
    security[20] = TacticalBar(
        trading_date=pseudo.trading_date,
        open_price=pseudo.open_price,
        high_price=pseudo.high_price,
        low_price=pseudo.low_price,
        close_price=pseudo.close_price,
        volume=0,
    )
    benchmark.pop(10)

    result = evaluate_tactical_signal(tuple(security), tuple(benchmark))

    assert result.aligned_session_count == 38


def test_invalidation_requires_prior_reversal_context() -> None:
    security = bars([0.002] * 65 + [-0.01] * 20 + [-0.04])
    benchmark = bars([0.0002] * len(security))
    context = PriorReversalContext(
        entry_stage=EntryStage.PROBE_ELIGIBLE,
        invalidation_level=security[-2].close_price * 0.99,
        established_as_of=security[-2].trading_date,
    )

    result = evaluate_tactical_signal(
        security,
        benchmark,
        prior_reversal_context=context,
    )

    assert result.entry_stage == EntryStage.INVALIDATED
    assert result.actionability == Actionability.RISK_BLOCKED


def test_invalid_ohlc_is_rejected() -> None:
    security = list(bars([0.001] * 40))
    invalid = security[-1]
    security[-1] = TacticalBar(
        trading_date=invalid.trading_date,
        open_price=100,
        high_price=99,
        low_price=98,
        close_price=100,
        volume=1,
    )

    with pytest.raises(ValueError, match="Bar high"):
        evaluate_tactical_signal(tuple(security), bars([0.001] * 40))


def test_recent_listing_has_no_three_month_outlook() -> None:
    result = evaluate_tactical_signal(
        bars([0.003] * 33),
        bars([0.001] * 33),
    )

    assert result.confidence == "LOW"
    assert result.horizons[-1].opportunity_score is None
    assert result.horizons[-1].outlook == "INSUFFICIENT_DATA"


def test_walk_forward_retains_no_edge_claim_and_state_specific_rows() -> None:
    security = bars([0.003] * 180)
    benchmark = bars([0.0005] * 180)

    metrics = evaluate_walk_forward(security, benchmark)

    assert len(metrics) == 12
    assert all(item.statistical_edge_proven == "NOT_ESTABLISHED" for item in metrics)
    assert any(
        item.setup_type == SetupType.MOMENTUM
        and item.entry_stage == EntryStage.CONFIRMED
        and item.episode_count > 0
        for item in metrics
    )


def test_assessment_serialization_is_canonical_and_deterministic() -> None:
    security = bars([0.0007] * 250 + [0.004] * 10)
    benchmark = bars([0.0004] * 260)

    first = evaluate_tactical_signal(security, benchmark)
    second = evaluate_tactical_signal(security, benchmark)
    first_json = serialize_tactical_assessment(first)
    second_json = serialize_tactical_assessment(second)

    assert first_json == second_json
    assert '"version":"TACTICAL-SIGNAL-v2.1.0"' in first_json
    assert '"momentum_extension_risk_score":' in first_json
    assert '"entry_value_score":' in first_json
