from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from statistics import fmean, pstdev

TACTICAL_SIGNAL_VERSION = "TACTICAL-SIGNAL-v1.1.0"


class TacticalState(StrEnum):
    MOMENTUM_ENTRY = "MOMENTUM_ENTRY"
    MEAN_REVERSION_ENTRY = "MEAN_REVERSION_ENTRY"
    WATCH_FOR_CONFIRMATION = "WATCH_FOR_CONFIRMATION"
    AVOID = "AVOID"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


@dataclass(frozen=True)
class TacticalBar:
    trading_date: date
    open_price: float
    high_price: float
    low_price: float
    close_price: float
    volume: int


@dataclass(frozen=True)
class HorizonSignal:
    trading_days: int
    horizon_label: str
    opportunity_score: float | None
    state: TacticalState


@dataclass(frozen=True)
class TacticalAssessment:
    version: str
    as_of_date: date
    state: TacticalState
    preferred_setup: str
    confidence: str
    momentum_score: float
    mean_reversion_score: float
    entry_confirmation_score: float
    market_regime_score: float
    event_drift_score: float
    liquidity_score: float
    risk_penalty: float
    returns: dict[int, float]
    relative_returns: dict[int, float]
    horizons: tuple[HorizonSignal, ...]
    reasons: tuple[str, ...]
    warnings: tuple[str, ...]


def _clip(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return min(high, max(low, value))


def _score_signed(value: float, scale: float) -> float:
    return _clip(50.0 + 50.0 * math.tanh(value / scale))


def _return(closes: list[float], lookback: int) -> float:
    return closes[-1] / closes[-(lookback + 1)] - 1.0


def _sma(values: list[float], lookback: int) -> float:
    return fmean(values[-lookback:])


def _atr_percent(bars: tuple[TacticalBar, ...], lookback: int = 14) -> float:
    selected = bars[-(lookback + 1) :]
    true_ranges: list[float] = []
    for prior, current in zip(selected[:-1], selected[1:], strict=True):
        true_ranges.append(
            max(
                current.high_price - current.low_price,
                abs(current.high_price - prior.close_price),
                abs(current.low_price - prior.close_price),
            )
        )
    return fmean(true_ranges) / selected[-1].close_price


def _max_drawdown(closes: list[float], lookback: int) -> float:
    peak = closes[-lookback]
    worst = 0.0
    for close in closes[-lookback:]:
        peak = max(peak, close)
        worst = min(worst, close / peak - 1.0)
    return abs(worst)


def _validate_bars(bars: tuple[TacticalBar, ...]) -> None:
    if len(bars) < 21:
        raise ValueError("Tactical Signal v1 requires at least 21 daily bars")
    if tuple(sorted(bar.trading_date for bar in bars)) != tuple(
        bar.trading_date for bar in bars
    ):
        raise ValueError("Bars must be chronological")
    if len({bar.trading_date for bar in bars}) != len(bars):
        raise ValueError("Bars must have unique trading dates")
    if any(
        bar.open_price <= 0
        or bar.high_price <= 0
        or bar.low_price <= 0
        or bar.close_price <= 0
        or bar.volume < 0
        for bar in bars
    ):
        raise ValueError("Bars require positive OHLC prices and non-negative volume")


def _horizon_state(
    opportunity: float,
    preferred_setup: str,
    confirmation: float,
    risk_penalty: float,
) -> TacticalState:
    if risk_penalty >= 72 or opportunity < 35:
        return TacticalState.AVOID
    if opportunity >= 65 and confirmation >= 58:
        return (
            TacticalState.MOMENTUM_ENTRY
            if preferred_setup == "MOMENTUM"
            else TacticalState.MEAN_REVERSION_ENTRY
        )
    return TacticalState.WATCH_FOR_CONFIRMATION


def evaluate_tactical_signal(
    bars: tuple[TacticalBar, ...],
    benchmark_bars: tuple[TacticalBar, ...],
    *,
    event_drift_score: float = 50.0,
) -> TacticalAssessment:
    """Evaluate a daily-data 1-4 week setup without blending opposing strategies.

    The model uses only information present in the supplied bars. The caller is
    responsible for ensuring that the final bar was available by the evaluation
    cutoff.
    """

    _validate_bars(bars)
    _validate_bars(benchmark_bars)
    if bars[-1].trading_date != benchmark_bars[-1].trading_date:
        raise ValueError("Security and benchmark must share the same as-of date")

    closes = [bar.close_price for bar in bars]
    benchmark_closes = [bar.close_price for bar in benchmark_bars]
    available_lookbacks = (5, 10, 20, 60) if len(closes) >= 61 else (5, 10, 20)
    returns = {lookback: _return(closes, lookback) for lookback in available_lookbacks}
    relative = {
        lookback: returns[lookback] - _return(benchmark_closes, lookback)
        for lookback in available_lookbacks
    }
    if 60 in returns:
        momentum_score = (
            0.15 * _score_signed(returns[5], 0.04)
            + 0.20 * _score_signed(returns[10], 0.06)
            + 0.25 * _score_signed(returns[20], 0.10)
            + 0.15 * _score_signed(returns[60], 0.18)
            + 0.15 * _score_signed(relative[20], 0.08)
            + 0.10 * _score_signed(relative[60], 0.14)
        )
    else:
        momentum_score = (
            0.20 * _score_signed(returns[5], 0.04)
            + 0.25 * _score_signed(returns[10], 0.06)
            + 0.35 * _score_signed(returns[20], 0.10)
            + 0.20 * _score_signed(relative[20], 0.08)
        )

    ma5 = _sma(closes, 5)
    ma20 = _sma(closes, 20)
    ma60 = _sma(closes, 60) if len(closes) >= 60 else ma20
    latest = closes[-1]
    daily_returns = [
        closes[index] / closes[index - 1] - 1.0 for index in range(1, len(closes))
    ]
    vol20 = max(pstdev(daily_returns[-20:]), 0.002)
    distance20_z = (latest / ma20 - 1.0) / vol20
    oversold_score = _clip(50.0 - 15.0 * distance20_z)
    trend_floor = _clip(50.0 + 50.0 * math.tanh((latest / ma60 - 1.0) / 0.08))
    falling_knife_penalty = (
        30.0
        if returns[5] < -0.08 and latest < ma20 < ma60
        else 15.0
        if returns[5] < -0.05 and latest < ma20
        else 0.0
    )
    mean_reversion_score = _clip(
        0.65 * oversold_score + 0.35 * trend_floor - falling_knife_penalty
    )

    recent_volumes = [bar.volume for bar in bars[-21:-1] if bar.volume > 0]
    volume_ratio = (
        bars[-1].volume / fmean(recent_volumes)
        if recent_volumes and bars[-1].volume > 0
        else 1.0
    )
    confirmation = 20.0
    confirmation += 20.0 if latest > ma5 else 0.0
    confirmation += 20.0 if latest > ma20 else 0.0
    confirmation += 15.0 if returns[5] > 0 else 0.0
    confirmation += 15.0 if relative[5] > 0 else 0.0
    confirmation += _clip((volume_ratio - 0.75) * 20.0, 0.0, 10.0)

    benchmark_returns = {
        lookback: _return(benchmark_closes, lookback)
        for lookback in (5, 20, 60)
        if len(benchmark_closes) > lookback
    }
    regime_components = (
        (5, 0.25, 0.035),
        (20, 0.45, 0.08),
        (60, 0.30, 0.14),
    )
    regime_weight = sum(
        weight for lookback, weight, _ in regime_components if lookback in benchmark_returns
    )
    regime = sum(
        weight * _score_signed(benchmark_returns[lookback], scale)
        for lookback, weight, scale in regime_components
        if lookback in benchmark_returns
    ) / regime_weight

    dollar_volume = fmean(
        bar.close_price * bar.volume for bar in bars[-20:] if bar.volume > 0
    )
    liquidity = _clip(20.0 * math.log10(max(dollar_volume, 1.0)) - 80.0)
    atr_pct = _atr_percent(bars)
    drawdown60 = _max_drawdown(closes, min(60, len(closes)))
    gaps = [
        abs(current.open_price / prior.close_price - 1.0)
        for prior, current in zip(bars[-21:-1], bars[-20:], strict=True)
    ]
    avg_gap = fmean(gaps)
    risk_penalty = _clip(
        100.0
        * (
            0.45 * min(atr_pct / 0.06, 1.0)
            + 0.35 * min(drawdown60 / 0.35, 1.0)
            + 0.20 * min(avg_gap / 0.04, 1.0)
        )
    )

    preferred = "MOMENTUM" if momentum_score >= mean_reversion_score else "MEAN_REVERSION"
    setup_score = max(momentum_score, mean_reversion_score)
    event = _clip(event_drift_score)
    horizon_weights = {
        5: ("ONE_WEEK", 0.30, 0.25, 0.20, 0.10, 0.15),
        20: ("ONE_MONTH", 0.45, 0.15, 0.15, 0.10, 0.15),
        60: ("THREE_MONTHS", 0.55, 0.10, 0.15, 0.10, 0.10),
    }
    horizons: list[HorizonSignal] = []
    for horizon, (label, *weights) in horizon_weights.items():
        if len(bars) <= horizon:
            horizons.append(
                HorizonSignal(
                    trading_days=horizon,
                    horizon_label=label,
                    opportunity_score=None,
                    state=TacticalState.INSUFFICIENT_DATA,
                )
            )
            continue
        opportunity = _clip(
            weights[0] * setup_score
            + weights[1] * confirmation
            + weights[2] * regime
            + weights[3] * event
            + weights[4] * liquidity
            - 0.30 * risk_penalty
        )
        horizons.append(
            HorizonSignal(
                trading_days=horizon,
                horizon_label=label,
                opportunity_score=round(opportunity, 2),
                state=_horizon_state(
                    opportunity,
                    preferred,
                    confirmation,
                    risk_penalty,
                ),
            )
        )
    primary = horizons[1]

    reasons: list[str] = []
    warnings: list[str] = []
    if preferred == "MOMENTUM":
        reasons.append("Momentum is stronger than the mean-reversion setup.")
    else:
        reasons.append("Mean reversion is stronger than trend continuation.")
    if confirmation >= 60:
        reasons.append("Daily-price entry confirmation is present.")
    else:
        warnings.append("Entry confirmation is incomplete.")
    if risk_penalty >= 60:
        warnings.append("Recent volatility, drawdown, or gap risk is elevated.")
    if liquidity < 50:
        warnings.append("Liquidity is below the model's preferred range.")
    if len(bars) < 126:
        warnings.append("Limited trading history reduces confidence.")
    confidence = (
        "LOW"
        if len(bars) < 90 or liquidity < 35
        else "MEDIUM"
        if len(bars) < 126 or risk_penalty >= 60
        else "HIGH"
    )
    return TacticalAssessment(
        version=TACTICAL_SIGNAL_VERSION,
        as_of_date=bars[-1].trading_date,
        state=primary.state,
        preferred_setup=preferred,
        confidence=confidence,
        momentum_score=round(momentum_score, 2),
        mean_reversion_score=round(mean_reversion_score, 2),
        entry_confirmation_score=round(confirmation, 2),
        market_regime_score=round(regime, 2),
        event_drift_score=round(event, 2),
        liquidity_score=round(liquidity, 2),
        risk_penalty=round(risk_penalty, 2),
        returns={key: round(value * 100.0, 2) for key, value in returns.items()},
        relative_returns={key: round(value * 100.0, 2) for key, value in relative.items()},
        horizons=tuple(horizons),
        reasons=tuple(reasons),
        warnings=tuple(warnings),
    )
