from __future__ import annotations

import math
from dataclasses import dataclass
from statistics import fmean, pstdev

from equity_analysis.tactical.contracts_v22 import (
    ComponentScoreV22,
    EvidenceState,
    TacticalBarV22,
    TacticalHorizon,
)


@dataclass(frozen=True)
class TacticalFeatureSetV22:
    continuation_by_horizon: dict[TacticalHorizon, float]
    mean_reversion_by_horizon: dict[TacticalHorizon, float]
    market_relative_by_horizon: dict[TacticalHorizon, float]
    sector_relative_by_horizon: dict[TacticalHorizon, float]
    mean_reversion_potential: ComponentScoreV22
    rebound_readiness: ComponentScoreV22
    falling_knife_risk: ComponentScoreV22
    chase_risk: ComponentScoreV22
    volatility_risk: ComponentScoreV22
    liquidity: ComponentScoreV22
    market_regime: ComponentScoreV22
    sector_regime: ComponentScoreV22
    continuation_entry_value: float
    mean_reversion_entry_value: float
    reversal_structure_present: bool


def clip(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return min(high, max(low, value))


def score_signed(value: float, scale: float) -> float:
    return clip(50.0 + 50.0 * math.tanh(value / scale))


def _return(closes: list[float], lookback: int) -> float:
    return closes[-1] / closes[-(lookback + 1)] - 1.0


def _sma(values: list[float], lookback: int) -> float:
    return fmean(values[-lookback:])


def _maximum_drawdown(closes: list[float], lookback: int) -> float:
    selected = closes[-lookback:]
    peak = selected[0]
    worst = 0.0
    for close in selected:
        peak = max(peak, close)
        worst = min(worst, close / peak - 1.0)
    return abs(worst)


def _atr_percent(bars: tuple[TacticalBarV22, ...], lookback: int = 14) -> float:
    selected = bars[-(lookback + 1) :]
    true_ranges = [
        max(
            current.high_price - current.low_price,
            abs(current.high_price - prior.close_price),
            abs(current.low_price - prior.close_price),
        )
        for prior, current in zip(selected[:-1], selected[1:], strict=True)
    ]
    return max(fmean(true_ranges) / selected[-1].close_price, 0.001)


def _regime_score(closes: list[float]) -> float:
    components: list[tuple[float, float]] = []
    for lookback, scale, weight in (
        (5, 0.035, 0.20),
        (20, 0.08, 0.35),
        (60, 0.14, 0.30),
        (120, 0.22, 0.15),
    ):
        if len(closes) > lookback:
            components.append((score_signed(_return(closes, lookback), scale), weight))
    if not components:
        return 50.0
    weighted = sum(value * weight for value, weight in components)
    return weighted / sum(weight for _, weight in components)


def _horizon_lookbacks(horizon: TacticalHorizon) -> tuple[tuple[int, float, float], ...]:
    return {
        TacticalHorizon.ONE_WEEK: (
            (5, 0.04, 0.55),
            (20, 0.10, 0.45),
        ),
        TacticalHorizon.ONE_MONTH: (
            (20, 0.10, 0.55),
            (60, 0.18, 0.45),
        ),
        TacticalHorizon.THREE_MONTHS: (
            (60, 0.18, 0.60),
            (120, 0.28, 0.40),
        ),
    }[horizon]


def _trend_score(closes: list[float], horizon: TacticalHorizon) -> float | None:
    available = [
        (score_signed(_return(closes, lookback), scale), weight)
        for lookback, scale, weight in _horizon_lookbacks(horizon)
        if len(closes) > lookback
    ]
    if len(available) != len(_horizon_lookbacks(horizon)):
        return None
    return sum(value * weight for value, weight in available)


def _relative_score(
    security_closes: list[float],
    benchmark_closes: list[float],
    horizon: TacticalHorizon,
) -> float | None:
    available = [
        (
            score_signed(
                _return(security_closes, lookback)
                - _return(benchmark_closes, lookback),
                scale,
            ),
            weight,
        )
        for lookback, scale, weight in _horizon_lookbacks(horizon)
        if len(security_closes) > lookback and len(benchmark_closes) > lookback
    ]
    if len(available) != len(_horizon_lookbacks(horizon)):
        return None
    return sum(value * weight for value, weight in available)


def _component(score: float, reason: str) -> ComponentScoreV22:
    return ComponentScoreV22(
        state=EvidenceState.VALID,
        score=round(clip(score), 2),
        reasons=(reason,),
    )


def extract_features_v22(
    security: tuple[TacticalBarV22, ...],
    market: tuple[TacticalBarV22, ...],
    sector: tuple[TacticalBarV22, ...],
) -> TacticalFeatureSetV22:
    closes = [item.close_price for item in security]
    market_closes = [item.close_price for item in market]
    sector_closes = [item.close_price for item in sector]
    latest = security[-1]
    daily_returns = [
        closes[index] / closes[index - 1] - 1.0 for index in range(1, len(closes))
    ]
    atr_percent = _atr_percent(security)
    ma5 = _sma(closes, 5)
    ma20 = _sma(closes, 20)
    ma60 = _sma(closes, 60) if len(closes) >= 60 else ma20

    distance20 = latest.close_price / ma20 - 1.0
    stretch = score_signed(-distance20, max(0.06, 2.0 * pstdev(daily_returns[-20:])))
    selloff = (
        0.50 * score_signed(-_return(closes, 5), 0.08)
        + 0.30 * score_signed(-_return(closes, 10), 0.12)
        + 0.20 * score_signed(-_return(closes, 20), 0.18)
    )
    drawdown = _maximum_drawdown(closes, min(60, len(closes)))
    drawdown_score = score_signed(drawdown - 0.10, 0.10)
    low20 = min(item.low_price for item in security[-20:])
    distance_from_low_atr = max(latest.close_price - low20, 0.0) / max(
        latest.close_price * atr_percent,
        1e-9,
    )
    support_proximity = 100.0 * math.exp(-distance_from_low_atr / 1.25)
    market_relative_five = _return(closes, 5) - _return(market_closes, 5)
    sector_relative_five = _return(closes, 5) - _return(sector_closes, 5)
    relative_exhaustion = (
        0.50 * score_signed(-market_relative_five, 0.08)
        + 0.50 * score_signed(-sector_relative_five, 0.08)
    )
    mean_reversion_potential_value = clip(
        0.28 * stretch
        + 0.24 * selloff
        + 0.14 * drawdown_score
        + 0.14 * support_proximity
        + 0.20 * relative_exhaustion
    )

    intraday_range = max(latest.high_price - latest.low_price, 1e-9)
    close_location = 100.0 * (latest.close_price - latest.low_price) / intraday_range
    body_score = score_signed(latest.close_price / latest.open_price - 1.0, 0.025)
    one_day = score_signed(_return(closes, 1), 0.03)
    one_day_relative = (
        0.50
        * score_signed(
            _return(closes, 1) - _return(market_closes, 1),
            0.03,
        )
        + 0.50
        * score_signed(
            _return(closes, 1) - _return(sector_closes, 1),
            0.03,
        )
    )
    prior_three_average = fmean(daily_returns[-5:-2])
    recent_two_average = fmean(daily_returns[-2:])
    deceleration = score_signed(recent_two_average - prior_three_average, 0.02)
    prior_five_low = min(item.low_price for item in security[-6:-1])
    made_lower_low = latest.low_price < prior_five_low
    reclaimed_prior_low = made_lower_low and latest.close_price > prior_five_low
    bullish_low_rejection = (
        close_location >= 60 and latest.close_price >= latest.open_price
    )
    higher_close_and_low = (
        latest.close_price > security[-2].close_price
        and latest.low_price >= security[-2].low_price
    )
    reversal_structure = (
        reclaimed_prior_low or bullish_low_rejection or higher_close_and_low
    )
    reclaim_score = (
        90.0
        if reclaimed_prior_low
        else score_signed(latest.close_price / prior_five_low - 1.0, 0.03)
    )
    adjustment_factors = [item.adjustment_factor for item in security[-21:]]
    adjustment_stable = max(adjustment_factors) / min(adjustment_factors) <= 1.05
    prior_volumes = [item.volume for item in security[-21:-1]]
    volume_ratio = latest.volume / max(fmean(prior_volumes), 1.0)
    if not adjustment_stable:
        direction_aware_volume = 50.0
    elif close_location >= 60 and latest.close_price >= latest.open_price:
        direction_aware_volume = clip(50.0 + 30.0 * (volume_ratio - 1.0))
    elif close_location <= 40:
        direction_aware_volume = clip(50.0 - 30.0 * (volume_ratio - 1.0))
    else:
        direction_aware_volume = 50.0
    rebound_readiness_value = clip(
        0.18 * close_location
        + 0.14 * body_score
        + 0.14 * one_day
        + 0.12 * one_day_relative
        + 0.16 * deceleration
        + 0.16 * reclaim_score
        + 0.10 * direction_aware_volume
    )

    negative_acceleration = score_signed(
        -(recent_two_average - prior_three_average),
        0.02,
    )
    repeated_lower_closes = sum(
        current.close_price < prior.close_price
        for prior, current in zip(security[-6:-1], security[-5:], strict=True)
    )
    prior_ten_low = min(item.low_price for item in security[-11:-1])
    weak_fresh_low = latest.low_price <= prior_ten_low and close_location < 45
    falling_knife_value = clip(
        0.28 * negative_acceleration
        + 0.24 * score_signed(-_return(closes, 5), 0.08)
        + 0.18 * (100.0 - close_location)
        + 0.18 * (20.0 * repeated_lower_closes)
        + 0.12 * (100.0 if weak_fresh_low else 0.0)
    )

    positive_ma20_extension = max(latest.close_price / ma20 - 1.0, 0.0)
    positive_ma5_extension = max(latest.close_price / ma5 - 1.0, 0.0)
    recent_five = daily_returns[-5:]
    prior_fifteen = daily_returns[-20:-5]
    burst_z = (
        fmean(recent_five) - fmean(prior_fifteen)
    ) / max(pstdev(prior_fifteen), 0.002)
    positive_gap_atr = max(
        latest.open_price / security[-2].close_price - 1.0,
        0.0,
    ) / atr_percent
    chase_value = clip(
        0.35 * clip((positive_ma20_extension / atr_percent - 2.5) / 3.0 * 100.0)
        + 0.25 * clip((positive_ma5_extension / atr_percent - 1.25) / 2.0 * 100.0)
        + 0.30 * clip((burst_z - 1.25) / 3.0 * 100.0)
        + 0.10 * clip((positive_gap_atr - 0.5) / 1.5 * 100.0)
    )

    gaps = [
        abs(current.open_price / prior.close_price - 1.0)
        for prior, current in zip(security[-21:-1], security[-20:], strict=True)
    ]
    trend_damage = (
        (0.5 if latest.close_price < ma20 else 0.0)
        + (0.5 if latest.close_price < ma60 else 0.0)
    )
    volatility_value = clip(
        100.0
        * (
            0.40 * min(atr_percent / 0.06, 1.0)
            + 0.25 * min(drawdown / 0.35, 1.0)
            + 0.15 * min(fmean(gaps) / 0.04, 1.0)
            + 0.20 * trend_damage
        )
    )

    if adjustment_stable:
        average_dollar_volume = fmean(
            item.close_price * item.volume for item in security[-20:]
        )
        liquidity_score = clip(
            20.0 * math.log10(max(average_dollar_volume, 1.0)) - 80.0
        )
        liquidity = _component(
            liquidity_score,
            "Twenty-session adjusted-dollar-volume capacity is available.",
        )
    else:
        liquidity_score = 0.0
        liquidity = ComponentScoreV22(
            state=EvidenceState.INVALID,
            score=None,
            reasons=(
                "A recent adjustment-factor transition prevents comparable "
                "price-volume capacity.",
            ),
        )

    market_regime_value = _regime_score(market_closes)
    sector_regime_value = _regime_score(sector_closes)
    market_relative: dict[TacticalHorizon, float] = {}
    sector_relative: dict[TacticalHorizon, float] = {}
    continuation: dict[TacticalHorizon, float] = {}
    mean_reversion: dict[TacticalHorizon, float] = {}
    for horizon in TacticalHorizon:
        security_trend = _trend_score(closes, horizon)
        market_relative_score = _relative_score(closes, market_closes, horizon)
        sector_relative_score = _relative_score(closes, sector_closes, horizon)
        if (
            security_trend is None
            or market_relative_score is None
            or sector_relative_score is None
        ):
            continue
        market_relative[horizon] = market_relative_score
        sector_relative[horizon] = sector_relative_score
        regime_weight = {
            TacticalHorizon.ONE_WEEK: 0.10,
            TacticalHorizon.ONE_MONTH: 0.15,
            TacticalHorizon.THREE_MONTHS: 0.22,
        }[horizon]
        continuation[horizon] = clip(
            (0.50 - regime_weight) * security_trend
            + 0.25 * market_relative_score
            + 0.25 * sector_relative_score
            + regime_weight / 2.0 * market_regime_value
            + regime_weight / 2.0 * sector_regime_value
        )
        readiness_weight = {
            TacticalHorizon.ONE_WEEK: 0.40,
            TacticalHorizon.ONE_MONTH: 0.28,
            TacticalHorizon.THREE_MONTHS: 0.15,
        }[horizon]
        potential_weight = {
            TacticalHorizon.ONE_WEEK: 0.45,
            TacticalHorizon.ONE_MONTH: 0.42,
            TacticalHorizon.THREE_MONTHS: 0.30,
        }[horizon]
        residual_weight = 1.0 - readiness_weight - potential_weight
        mean_reversion[horizon] = clip(
            potential_weight * mean_reversion_potential_value
            + readiness_weight * rebound_readiness_value
            + residual_weight
            * (
                0.40 * security_trend
                + 0.20 * market_relative_score
                + 0.20 * sector_relative_score
                + 0.10 * market_regime_value
                + 0.10 * sector_regime_value
            )
        )

    invalidation_distance = max(
        (latest.close_price - low20) / latest.close_price
        + 0.50 * atr_percent,
        0.50 * atr_percent,
    )
    recovery_distance = max(ma20 / latest.close_price - 1.0, 0.0) + 0.25 * max(
        ma60 / latest.close_price - 1.0,
        0.0,
    )
    mean_reversion_entry_value = clip(
        100.0 * (recovery_distance / max(invalidation_distance, 1e-9)) / 2.5
    )
    continuation_entry_value = clip(
        0.30 * fmean(continuation.values())
        + 0.20 * market_regime_value
        + 0.20 * sector_regime_value
        + 0.15 * liquidity_score
        + 0.15 * (100.0 - chase_value)
        - 0.20 * volatility_value
    )

    return TacticalFeatureSetV22(
        continuation_by_horizon=continuation,
        mean_reversion_by_horizon=mean_reversion,
        market_relative_by_horizon=market_relative,
        sector_relative_by_horizon=sector_relative,
        mean_reversion_potential=_component(
            mean_reversion_potential_value,
            "Stretch, selloff, drawdown, support, and relative exhaustion "
            "are separate from timing.",
        ),
        rebound_readiness=_component(
            rebound_readiness_value,
            "Completed-session reversal structure and direction-aware participation are measured.",
        ),
        falling_knife_risk=_component(
            falling_knife_value,
            "Downside acceleration, lower closes, weak location, and fresh lows are measured.",
        ),
        chase_risk=_component(
            chase_value,
            "ATR-normalized extension, burst acceleration, and positive gaps are measured.",
        ),
        volatility_risk=_component(
            volatility_value,
            "ATR, drawdown, gaps, and trend damage are measured without changing thesis scores.",
        ),
        liquidity=liquidity,
        market_regime=_component(
            market_regime_value,
            "Market trend is measured from the versioned market benchmark.",
        ),
        sector_regime=_component(
            sector_regime_value,
            "Sector trend is measured independently from the market benchmark.",
        ),
        continuation_entry_value=continuation_entry_value,
        mean_reversion_entry_value=mean_reversion_entry_value,
        reversal_structure_present=reversal_structure,
    )
