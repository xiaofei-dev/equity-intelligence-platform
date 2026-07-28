from datetime import date, timedelta

import pytest

from equity_analysis.tactical.signal_v1 import (
    TacticalBar,
    TacticalState,
    evaluate_tactical_signal,
)
from equity_analysis.tactical.walk_forward_v1 import evaluate_walk_forward


def bars(
    daily_returns: list[float],
    *,
    start: float = 100.0,
    volume: int = 2_000_000,
) -> tuple[TacticalBar, ...]:
    price = start
    result: list[TacticalBar] = []
    start_date = date(2025, 1, 1)
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


def test_strong_confirmed_trend_is_momentum_entry() -> None:
    security = bars([0.004] * 90)
    benchmark = bars([0.0005] * 90)

    result = evaluate_tactical_signal(security, benchmark)

    assert result.preferred_setup == "MOMENTUM"
    assert result.state == TacticalState.MOMENTUM_ENTRY
    assert result.momentum_score > result.mean_reversion_score
    assert result.entry_confirmation_score >= 60


def test_falling_knife_is_not_promoted_as_mean_reversion_entry() -> None:
    security = bars([0.002] * 65 + [-0.025] * 25)
    benchmark = bars([0.0002] * 90)

    result = evaluate_tactical_signal(security, benchmark)

    assert result.state == TacticalState.AVOID
    assert result.risk_penalty > 60
    assert result.entry_confirmation_score < 60


def test_event_score_is_bounded() -> None:
    security = bars([0.001] * 90)
    benchmark = bars([0.001] * 90)

    result = evaluate_tactical_signal(security, benchmark, event_drift_score=150)

    assert result.event_drift_score == 100


def test_requires_sixty_one_daily_bars() -> None:
    with pytest.raises(ValueError, match="at least 21"):
        evaluate_tactical_signal(bars([0.001] * 20), bars([0.001] * 90))


def test_recent_ipo_gets_low_confidence_provisional_signal() -> None:
    security = bars([0.005] * 33)
    benchmark = bars([0.001] * 33)

    result = evaluate_tactical_signal(security, benchmark)

    assert result.confidence == "LOW"
    assert "Limited trading history reduces confidence." in result.warnings
    assert 60 not in result.returns
    assert result.horizons[-1].horizon_label == "THREE_MONTHS"
    assert result.horizons[-1].state == TacticalState.INSUFFICIENT_DATA
    assert result.horizons[-1].opportunity_score is None


def test_walk_forward_never_claims_statistical_edge() -> None:
    security = bars([0.003] * 160)
    benchmark = bars([0.0005] * 160)

    metrics = evaluate_walk_forward(security, benchmark)

    assert all(item.statistical_edge_proven == "NOT_ESTABLISHED" for item in metrics)
    assert all(item.episode_count > 0 for item in metrics)
    assert tuple(item.horizon_trading_days for item in metrics) == (5, 20, 60)
