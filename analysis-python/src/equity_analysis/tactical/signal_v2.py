from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from datetime import date
from enum import StrEnum
from statistics import fmean, pstdev

TACTICAL_SIGNAL_VERSION = "TACTICAL-SIGNAL-v2.1.0"


class SetupType(StrEnum):
    MOMENTUM = "MOMENTUM"
    MEAN_REVERSION = "MEAN_REVERSION"


class EntryStage(StrEnum):
    NONE = "NONE"
    EARLY_REVERSAL_CANDIDATE = "EARLY_REVERSAL_CANDIDATE"
    PROBE_ELIGIBLE = "PROBE_ELIGIBLE"
    CONFIRMED = "CONFIRMED"
    INVALIDATED = "INVALIDATED"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class Actionability(StrEnum):
    WATCH_ONLY = "WATCH_ONLY"
    WAIT_FOR_PULLBACK = "WAIT_FOR_PULLBACK"
    LIMITED_ENTRY = "LIMITED_ENTRY"
    ENTRY = "ENTRY"
    RISK_BLOCKED = "RISK_BLOCKED"
    NO_SETUP = "NO_SETUP"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class HorizonOutlook(StrEnum):
    FAVORABLE = "FAVORABLE"
    NEUTRAL = "NEUTRAL"
    UNFAVORABLE = "UNFAVORABLE"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class LegacyTacticalState(StrEnum):
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
    adjustment_factor: float = 1.0
    session_complete: bool = True


@dataclass(frozen=True)
class PriorReversalContext:
    entry_stage: EntryStage
    invalidation_level: float
    established_as_of: date


@dataclass(frozen=True)
class HorizonSignal:
    trading_days: int
    horizon_label: str
    opportunity_score: float | None
    outlook: HorizonOutlook


@dataclass(frozen=True)
class TacticalAssessment:
    version: str
    decision_domain: str
    data_cadence: str
    effective_from: str
    signal_ttl_completed_sessions: int
    as_of_date: date
    setup_type: SetupType
    entry_stage: EntryStage
    entry_stage_confidence: str
    actionability: Actionability
    maximum_risk_unit_multiplier: float
    legacy_state: LegacyTacticalState
    confidence: str
    momentum_score: float
    momentum_extension_risk_score: float
    bounce_potential_score: float
    reversal_trigger_score: float
    reversal_structure_present: bool
    trend_confirmation_score: float
    entry_timing_score: float
    entry_value_score: float
    payoff_asymmetry_score: float
    market_regime_score: float
    event_drift_score: float
    liquidity_score: float
    risk_penalty: float
    falling_knife_risk_score: float
    invalidation_level: float | None
    invalidation_distance_percent: float | None
    returns: dict[int, float]
    relative_returns: dict[int, float]
    horizons: tuple[HorizonSignal, ...]
    aligned_session_count: int
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


def _max_drawdown(closes: list[float], lookback: int) -> float:
    peak = closes[-lookback]
    worst = 0.0
    for close in closes[-lookback:]:
        peak = max(peak, close)
        worst = min(worst, close / peak - 1.0)
    return abs(worst)


def _projected_trend_extension_atr(
    closes: list[float],
    atr_percent: float,
) -> float:
    """Return positive latest-close extension above a prior 20-session log trend."""

    prior = closes[-21:-1]
    log_prices = [math.log(value) for value in prior]
    mean_x = (len(log_prices) - 1) / 2.0
    mean_y = fmean(log_prices)
    denominator = sum((index - mean_x) ** 2 for index in range(len(log_prices)))
    slope = (
        sum(
            (index - mean_x) * (value - mean_y)
            for index, value in enumerate(log_prices)
        )
        / denominator
    )
    intercept = mean_y - slope * mean_x
    projected_log_price = intercept + slope * len(log_prices)
    positive_residual = max(math.log(closes[-1]) - projected_log_price, 0.0)
    return positive_residual / max(atr_percent, 1e-9)


def _momentum_extension_risk(
    *,
    closes: list[float],
    daily_returns: list[float],
    latest_open: float,
    prior_close: float,
    latest: float,
    ma5: float,
    ma20: float,
    atr_percent: float,
) -> float:
    """Measure chase risk without penalizing a breakout merely for making a high."""

    ma20_extension_atr = max(latest / ma20 - 1.0, 0.0) / max(atr_percent, 1e-9)
    ma5_extension_atr = max(latest / ma5 - 1.0, 0.0) / max(atr_percent, 1e-9)
    projected_extension_atr = _projected_trend_extension_atr(closes, atr_percent)

    recent_five = daily_returns[-5:]
    prior_returns = daily_returns[-20:-5]
    prior_average = fmean(prior_returns)
    prior_volatility = max(pstdev(prior_returns), 0.002)
    burst_z = (fmean(recent_five) - prior_average) / prior_volatility
    positive_gap_atr = max(latest_open / prior_close - 1.0, 0.0) / max(
        atr_percent,
        1e-9,
    )

    ma20_risk = _clip((ma20_extension_atr - 3.0) / 3.0 * 100.0)
    ma5_risk = _clip((ma5_extension_atr - 1.5) / 2.0 * 100.0)
    projected_risk = _clip((projected_extension_atr - 0.5) / 2.0 * 100.0)
    burst_risk = _clip((burst_z - 1.5) / 3.0 * 100.0)
    gap_risk = _clip((positive_gap_atr - 0.5) / 1.5 * 100.0)
    return _clip(
        0.25 * ma20_risk
        + 0.20 * ma5_risk
        + 0.30 * projected_risk
        + 0.20 * burst_risk
        + 0.05 * gap_risk
    )


def _validate_bar(bar: TacticalBar) -> None:
    if (
        bar.open_price <= 0
        or bar.high_price <= 0
        or bar.low_price <= 0
        or bar.close_price <= 0
        or bar.volume < 0
        or bar.adjustment_factor <= 0
    ):
        raise ValueError(
            "Bars require positive adjusted OHLC prices and adjustment factors, "
            "with non-negative volume"
        )
    if bar.high_price < max(bar.open_price, bar.close_price, bar.low_price):
        raise ValueError("Bar high must not be below open, close, or low")
    if bar.low_price > min(bar.open_price, bar.close_price, bar.high_price):
        raise ValueError("Bar low must not be above open, close, or high")


def _validate_series(bars: tuple[TacticalBar, ...]) -> None:
    dates = tuple(bar.trading_date for bar in bars)
    if tuple(sorted(dates)) != dates:
        raise ValueError("Bars must be chronological")
    if len(set(dates)) != len(dates):
        raise ValueError("Bars must have unique trading dates")
    for bar in bars:
        _validate_bar(bar)


def _align_completed_sessions(
    bars: tuple[TacticalBar, ...],
    benchmark_bars: tuple[TacticalBar, ...],
) -> tuple[tuple[TacticalBar, ...], tuple[TacticalBar, ...]]:
    _validate_series(bars)
    _validate_series(benchmark_bars)
    security_by_date = {
        bar.trading_date: bar
        for bar in bars
        if bar.session_complete and bar.volume > 0
    }
    benchmark_by_date = {
        bar.trading_date: bar
        for bar in benchmark_bars
        if bar.session_complete and bar.volume > 0
    }
    shared_dates = tuple(sorted(security_by_date.keys() & benchmark_by_date.keys()))
    if len(shared_dates) < 21:
        raise ValueError(
            "Tactical Signal v2 requires at least 21 shared completed sessions "
            "with positive volume"
        )
    return (
        tuple(security_by_date[trading_date] for trading_date in shared_dates),
        tuple(benchmark_by_date[trading_date] for trading_date in shared_dates),
    )


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


def _volume_ratio(bars: tuple[TacticalBar, ...]) -> tuple[float, bool]:
    selected = bars[-21:]
    factors = [bar.adjustment_factor for bar in selected]
    adjustment_stable = max(factors) / min(factors) <= 1.05
    prior_volumes = [bar.volume for bar in selected[:-1]]
    if not prior_volumes:
        return 1.0, adjustment_stable
    return selected[-1].volume / fmean(prior_volumes), adjustment_stable


def _horizon_outlook(score: float) -> HorizonOutlook:
    if score >= 60:
        return HorizonOutlook.FAVORABLE
    if score >= 40:
        return HorizonOutlook.NEUTRAL
    return HorizonOutlook.UNFAVORABLE


def _legacy_state(
    setup_type: SetupType,
    entry_stage: EntryStage,
    actionability: Actionability,
) -> LegacyTacticalState:
    if entry_stage == EntryStage.INSUFFICIENT_DATA:
        return LegacyTacticalState.INSUFFICIENT_DATA
    if actionability == Actionability.WAIT_FOR_PULLBACK:
        return LegacyTacticalState.WATCH_FOR_CONFIRMATION
    if entry_stage == EntryStage.CONFIRMED:
        return (
            LegacyTacticalState.MOMENTUM_ENTRY
            if setup_type == SetupType.MOMENTUM
            else LegacyTacticalState.MEAN_REVERSION_ENTRY
        )
    if actionability in {Actionability.RISK_BLOCKED, Actionability.NO_SETUP}:
        return LegacyTacticalState.AVOID
    return LegacyTacticalState.WATCH_FOR_CONFIRMATION


def _entry_stage_confidence(
    *,
    setup_type: SetupType,
    entry_stage: EntryStage,
    one_week_opportunity: float,
    momentum: float,
    bounce_potential: float,
    reversal_trigger: float,
    trend_confirmation: float,
    payoff_asymmetry: float,
    entry_value: float,
    momentum_extension_risk: float,
    risk_penalty: float,
    falling_knife_risk: float,
) -> str:
    if entry_stage == EntryStage.PROBE_ELIGIBLE:
        margin = min(
            bounce_potential - 68,
            reversal_trigger - 50,
            payoff_asymmetry - 55,
            one_week_opportunity - 40,
            88 - risk_penalty,
            85 - falling_knife_risk,
        )
    elif entry_stage == EntryStage.CONFIRMED and setup_type == SetupType.MOMENTUM:
        margin = min(
            momentum - 65,
            trend_confirmation - 60,
            one_week_opportunity - 55,
            72 - risk_penalty,
        )
        if momentum_extension_risk < 70 and entry_value >= 60:
            margin = min(
                margin,
                70 - momentum_extension_risk,
                entry_value - 60,
            )
    elif entry_stage == EntryStage.CONFIRMED:
        margin = min(
            bounce_potential - 60,
            reversal_trigger - 65,
            trend_confirmation - 50,
            one_week_opportunity - 50,
            82 - risk_penalty,
        )
    elif entry_stage == EntryStage.EARLY_REVERSAL_CANDIDATE:
        margin = min(bounce_potential - 60, payoff_asymmetry - 45)
    else:
        return "NOT_APPLICABLE"
    if margin < 5:
        return "LOW"
    if margin < 12:
        return "MEDIUM"
    return "HIGH"


def _entry_decision(
    *,
    setup_type: SetupType,
    one_week_opportunity: float,
    momentum: float,
    bounce_potential: float,
    reversal_trigger: float,
    trend_confirmation: float,
    payoff_asymmetry: float,
    entry_value: float,
    momentum_extension_risk: float,
    risk_penalty: float,
    falling_knife_risk: float,
    reversal_structure_present: bool,
    aligned_session_count: int,
    prior_context: PriorReversalContext | None,
    latest_low: float,
) -> tuple[EntryStage, Actionability]:
    if (
        prior_context is not None
        and prior_context.entry_stage
        in {EntryStage.PROBE_ELIGIBLE, EntryStage.CONFIRMED}
        and latest_low <= prior_context.invalidation_level
    ):
        return EntryStage.INVALIDATED, Actionability.RISK_BLOCKED

    if aligned_session_count < 60:
        if (
            setup_type == SetupType.MEAN_REVERSION
            and bounce_potential >= 60
            and payoff_asymmetry >= 45
        ):
            return EntryStage.EARLY_REVERSAL_CANDIDATE, Actionability.WATCH_ONLY
        return EntryStage.NONE, Actionability.WATCH_ONLY

    if setup_type == SetupType.MOMENTUM:
        if risk_penalty >= 85 or one_week_opportunity < 30:
            return EntryStage.NONE, Actionability.RISK_BLOCKED
        if (
            momentum >= 65
            and trend_confirmation >= 60
            and one_week_opportunity >= 55
            and risk_penalty < 72
        ):
            if momentum_extension_risk >= 70 or entry_value < 60:
                return EntryStage.CONFIRMED, Actionability.WAIT_FOR_PULLBACK
            return EntryStage.CONFIRMED, Actionability.ENTRY
        return EntryStage.NONE, Actionability.WATCH_ONLY

    if risk_penalty >= 92 or falling_knife_risk >= 94:
        return EntryStage.NONE, Actionability.RISK_BLOCKED
    if (
        bounce_potential >= 60
        and reversal_trigger >= 65
        and trend_confirmation >= 50
        and one_week_opportunity >= 50
        and risk_penalty < 82
    ):
        return EntryStage.CONFIRMED, Actionability.ENTRY
    if (
        bounce_potential >= 68
        and reversal_trigger >= 50
        and payoff_asymmetry >= 55
        and one_week_opportunity >= 40
        and risk_penalty < 88
        and falling_knife_risk < 85
        and reversal_structure_present
    ):
        return EntryStage.PROBE_ELIGIBLE, Actionability.LIMITED_ENTRY
    if bounce_potential >= 60 and payoff_asymmetry >= 45:
        return EntryStage.EARLY_REVERSAL_CANDIDATE, Actionability.WATCH_ONLY
    if bounce_potential < 35 and one_week_opportunity < 30:
        return EntryStage.NONE, Actionability.NO_SETUP
    return EntryStage.NONE, Actionability.WATCH_ONLY


def evaluate_tactical_signal(
    bars: tuple[TacticalBar, ...],
    benchmark_bars: tuple[TacticalBar, ...],
    *,
    event_drift_score: float = 50.0,
    prior_reversal_context: PriorReversalContext | None = None,
) -> TacticalAssessment:
    """Evaluate a completed-daily-session tactical setup.

    The model separates rebound potential, entry timing, and risk. A severe
    decline may raise rebound potential without authorizing an entry. The
    caller must supply corporate-action-adjusted OHLC prices and must not
    include an incomplete current session.
    """

    aligned, aligned_benchmark = _align_completed_sessions(bars, benchmark_bars)
    closes = [bar.close_price for bar in aligned]
    benchmark_closes = [bar.close_price for bar in aligned_benchmark]
    available_lookbacks = tuple(
        lookback for lookback in (1, 3, 5, 10, 20, 60) if len(closes) > lookback
    )
    returns = {lookback: _return(closes, lookback) for lookback in available_lookbacks}
    relative = {
        lookback: returns[lookback] - _return(benchmark_closes, lookback)
        for lookback in available_lookbacks
    }

    if 60 in returns:
        momentum = (
            0.15 * _score_signed(returns[5], 0.04)
            + 0.20 * _score_signed(returns[10], 0.06)
            + 0.25 * _score_signed(returns[20], 0.10)
            + 0.15 * _score_signed(returns[60], 0.18)
            + 0.15 * _score_signed(relative[20], 0.08)
            + 0.10 * _score_signed(relative[60], 0.14)
        )
    else:
        momentum = (
            0.20 * _score_signed(returns[5], 0.04)
            + 0.25 * _score_signed(returns[10], 0.06)
            + 0.35 * _score_signed(returns[20], 0.10)
            + 0.20 * _score_signed(relative[20], 0.08)
        )

    latest_bar = aligned[-1]
    latest = latest_bar.close_price
    ma5 = _sma(closes, 5)
    ma10 = _sma(closes, 10)
    ma20 = _sma(closes, 20)
    ma60 = _sma(closes, 60) if len(closes) >= 60 else ma20
    daily_returns = [
        closes[index] / closes[index - 1] - 1.0 for index in range(1, len(closes))
    ]
    vol20 = max(pstdev(daily_returns[-20:]), 0.002)
    distance20 = latest / ma20 - 1.0
    stretch_score = _score_signed(-distance20, max(0.06, 2.0 * vol20))
    selloff_score = (
        0.45 * _score_signed(-returns[5], 0.08)
        + 0.35 * _score_signed(-returns[10], 0.12)
        + 0.20 * _score_signed(-returns[20], 0.18)
    )
    drawdown60 = _max_drawdown(closes, min(60, len(closes)))
    drawdown_score = _score_signed(drawdown60 - 0.10, 0.10)
    atr_percent = _atr_percent(aligned)
    momentum_extension_risk = _momentum_extension_risk(
        closes=closes,
        daily_returns=daily_returns,
        latest_open=latest_bar.open_price,
        prior_close=aligned[-2].close_price,
        latest=latest,
        ma5=ma5,
        ma20=ma20,
        atr_percent=atr_percent,
    )
    low20 = min(bar.low_price for bar in aligned[-20:])
    low_distance_atr = max(latest - low20, 0.0) / max(latest * atr_percent, 1e-9)
    support_proximity = 100.0 * math.exp(-low_distance_atr / 1.25)
    relative_exhaustion = _score_signed(-relative[5], 0.08)
    bounce_potential = _clip(
        0.30 * stretch_score
        + 0.25 * selloff_score
        + 0.15 * drawdown_score
        + 0.15 * support_proximity
        + 0.15 * relative_exhaustion
    )

    intraday_range = max(latest_bar.high_price - latest_bar.low_price, 1e-9)
    close_location = 100.0 * (
        latest_bar.close_price - latest_bar.low_price
    ) / intraday_range
    body_score = _score_signed(
        latest_bar.close_price / latest_bar.open_price - 1.0,
        0.025,
    )
    one_day_score = _score_signed(returns[1], 0.03)
    relative_one_day_score = _score_signed(relative[1], 0.03)
    prior_three_average = fmean(daily_returns[-5:-2])
    recent_two_average = fmean(daily_returns[-2:])
    downside_deceleration = _score_signed(
        recent_two_average - prior_three_average,
        0.02,
    )
    prior_five_low = min(bar.low_price for bar in aligned[-6:-1])
    made_lower_low = latest_bar.low_price < prior_five_low
    reclaimed_prior_low = made_lower_low and latest_bar.close_price > prior_five_low
    bullish_low_rejection = (
        close_location >= 60
        and latest_bar.close_price >= latest_bar.open_price
    )
    higher_close_and_low = (
        latest_bar.close_price > aligned[-2].close_price
        and latest_bar.low_price >= aligned[-2].low_price
    )
    reversal_structure_present = (
        reclaimed_prior_low or bullish_low_rejection or higher_close_and_low
    )
    low_reclaim_score = (
        90.0
        if reclaimed_prior_low
        else _score_signed(latest / prior_five_low - 1.0, 0.03)
    )
    volume_ratio, volume_context_reliable = _volume_ratio(aligned)
    if not volume_context_reliable:
        direction_aware_volume = 50.0
    elif close_location >= 60 and latest_bar.close_price >= latest_bar.open_price:
        direction_aware_volume = _clip(50.0 + 30.0 * (volume_ratio - 1.0))
    elif close_location <= 40:
        direction_aware_volume = _clip(50.0 - 30.0 * (volume_ratio - 1.0))
    else:
        direction_aware_volume = 50.0
    reversal_trigger = _clip(
        0.20 * close_location
        + 0.15 * body_score
        + 0.15 * one_day_score
        + 0.10 * relative_one_day_score
        + 0.15 * downside_deceleration
        + 0.15 * low_reclaim_score
        + 0.10 * direction_aware_volume
    )

    trend_confirmation = 0.0
    trend_confirmation += 20.0 if latest > ma5 else 0.0
    trend_confirmation += 15.0 if latest > ma10 else 0.0
    trend_confirmation += 15.0 if returns[3] > 0 else 0.0
    trend_confirmation += 15.0 if returns[5] > 0 else 0.0
    trend_confirmation += 15.0 if relative[5] > 0 else 0.0
    trend_confirmation += 10.0 if latest_bar.low_price > aligned[-2].low_price else 0.0
    trend_confirmation += 10.0 if latest > aligned[-2].close_price else 0.0

    gaps = [
        abs(current.open_price / prior.close_price - 1.0)
        for prior, current in zip(aligned[-21:-1], aligned[-20:], strict=True)
    ]
    average_gap = fmean(gaps)
    trend_damage = (
        (0.5 if latest < ma20 else 0.0)
        + (0.5 if latest < ma60 else 0.0)
    )
    prior_ten_low = min(bar.low_price for bar in aligned[-11:-1])
    weak_fresh_low = latest_bar.low_price <= prior_ten_low and close_location < 45
    risk_penalty = _clip(
        100.0
        * (
            0.35 * min(atr_percent / 0.06, 1.0)
            + 0.25 * min(drawdown60 / 0.35, 1.0)
            + 0.15 * min(average_gap / 0.04, 1.0)
            + 0.15 * trend_damage
            + 0.10 * (1.0 if weak_fresh_low else 0.0)
        )
    )
    negative_acceleration = _score_signed(
        -(recent_two_average - prior_three_average),
        0.02,
    )
    repeated_closing_lows = sum(
        current.close_price < prior.close_price
        for prior, current in zip(aligned[-6:-1], aligned[-5:], strict=True)
    )
    falling_knife_risk = _clip(
        0.30 * negative_acceleration
        + 0.25 * _score_signed(-returns[5], 0.08)
        + 0.20 * (100.0 - close_location)
        + 0.15 * (20.0 * repeated_closing_lows)
        + 0.10 * (100.0 if weak_fresh_low else 0.0)
    )

    invalidation_level = max(low20 - 0.50 * atr_percent * latest, 0.01)
    invalidation_distance = max(
        (latest - low20) / latest + 0.50 * atr_percent,
        0.50 * atr_percent,
    )
    recovery_distance = max(ma20 / latest - 1.0, 0.0) + 0.25 * max(
        ma60 / latest - 1.0,
        0.0,
    )
    payoff_asymmetry = _clip(
        100.0 * (recovery_distance / max(invalidation_distance, 1e-9)) / 2.5
    )

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
        weight
        for lookback, weight, _ in regime_components
        if lookback in benchmark_returns
    )
    regime = sum(
        weight * _score_signed(benchmark_returns[lookback], scale)
        for lookback, weight, scale in regime_components
        if lookback in benchmark_returns
    ) / regime_weight
    dollar_volume = fmean(
        bar.close_price * bar.volume for bar in aligned[-20:]
    )
    liquidity = _clip(20.0 * math.log10(max(dollar_volume, 1.0)) - 80.0)
    event = _clip(event_drift_score)
    setup_type = (
        SetupType.MOMENTUM
        if momentum >= bounce_potential
        else SetupType.MEAN_REVERSION
    )
    entry_value = (
        _clip(
            0.30 * trend_confirmation
            + 0.25 * momentum
            + 0.15 * regime
            + 0.10 * liquidity
            + 0.20 * (100.0 - momentum_extension_risk)
            - 0.25 * risk_penalty
        )
        if setup_type == SetupType.MOMENTUM
        else payoff_asymmetry
    )

    horizon_specs = {
        5: ("ONE_WEEK",),
        20: ("ONE_MONTH",),
        60: ("THREE_MONTHS",),
    }
    horizons: list[HorizonSignal] = []
    for horizon, (label,) in horizon_specs.items():
        if len(aligned) <= horizon:
            horizons.append(
                HorizonSignal(
                    trading_days=horizon,
                    horizon_label=label,
                    opportunity_score=None,
                    outlook=HorizonOutlook.INSUFFICIENT_DATA,
                )
            )
            continue
        if setup_type == SetupType.MOMENTUM:
            weights = {
                5: (0.35, 0.30, 0.10, 0.10, 0.15, 0.25),
                20: (0.45, 0.20, 0.15, 0.10, 0.10, 0.22),
                60: (0.50, 0.10, 0.20, 0.10, 0.10, 0.18),
            }[horizon]
            opportunity = _clip(
                weights[0] * momentum
                + weights[1] * trend_confirmation
                + weights[2] * regime
                + weights[3] * event
                + weights[4] * liquidity
                - weights[5] * risk_penalty
            )
        else:
            weights = {
                5: (0.30, 0.30, 0.15, 0.05, 0.10, 0.10, 0.25),
                20: (0.35, 0.20, 0.20, 0.10, 0.05, 0.10, 0.22),
                60: (0.30, 0.10, 0.20, 0.15, 0.15, 0.10, 0.18),
            }[horizon]
            opportunity = _clip(
                weights[0] * bounce_potential
                + weights[1] * reversal_trigger
                + weights[2] * payoff_asymmetry
                + weights[3] * momentum
                + weights[4] * regime
                + weights[5] * liquidity
                - weights[6] * risk_penalty
            )
        rounded = round(opportunity, 2)
        horizons.append(
            HorizonSignal(
                trading_days=horizon,
                horizon_label=label,
                opportunity_score=rounded,
                outlook=_horizon_outlook(opportunity),
            )
        )

    one_week_opportunity = horizons[0].opportunity_score
    if one_week_opportunity is None:
        entry_stage = EntryStage.INSUFFICIENT_DATA
        actionability = Actionability.INSUFFICIENT_DATA
    else:
        entry_stage, actionability = _entry_decision(
            setup_type=setup_type,
            one_week_opportunity=one_week_opportunity,
            momentum=momentum,
            bounce_potential=bounce_potential,
            reversal_trigger=reversal_trigger,
            trend_confirmation=trend_confirmation,
            payoff_asymmetry=payoff_asymmetry,
            entry_value=entry_value,
            momentum_extension_risk=momentum_extension_risk,
            risk_penalty=risk_penalty,
            falling_knife_risk=falling_knife_risk,
            reversal_structure_present=reversal_structure_present,
            aligned_session_count=len(aligned),
            prior_context=prior_reversal_context,
            latest_low=latest_bar.low_price,
        )

    reasons: list[str] = []
    warnings: list[str] = []
    if setup_type == SetupType.MOMENTUM:
        reasons.append("Momentum continuation is the stronger current tactical thesis.")
    else:
        reasons.append("Mean reversion is the stronger current tactical thesis.")
    if entry_stage == EntryStage.EARLY_REVERSAL_CANDIDATE:
        reasons.append(
            "Rebound potential is present, but completed-session evidence does not "
            "authorize an entry."
        )
    elif entry_stage == EntryStage.PROBE_ELIGIBLE:
        reasons.append(
            "Early stabilization evidence permits only a limited, separately "
            "risk-controlled probe."
        )
    elif entry_stage == EntryStage.CONFIRMED:
        if actionability == Actionability.WAIT_FOR_PULLBACK:
            reasons.append(
                "The momentum thesis is confirmed, but current entry value does "
                "not justify chasing the extension."
            )
        else:
            reasons.append("Completed-session price evidence confirms the selected setup.")
    elif entry_stage == EntryStage.INVALIDATED:
        warnings.append("The prior reversal thesis crossed its deterministic invalidation.")
    if actionability == Actionability.RISK_BLOCKED:
        warnings.append("Risk controls currently block a tactical entry.")
    if actionability == Actionability.WAIT_FOR_PULLBACK:
        warnings.append(
            "Momentum extension or setup-specific entry value requires a pullback "
            "before entry."
        )
    if risk_penalty >= 60:
        warnings.append("Recent volatility, drawdown, gap, or trend damage is elevated.")
    if falling_knife_risk >= 70:
        warnings.append("Downside acceleration or weak closing behavior remains elevated.")
    if not volume_context_reliable:
        warnings.append(
            "A recent corporate-action adjustment suppresses volume confirmation."
        )
    if liquidity < 50:
        warnings.append("Liquidity is below the model's preferred range.")
    if len(aligned) < 126:
        warnings.append("Limited shared trading history reduces confidence.")
    if aligned[-1].trading_date != bars[-1].trading_date:
        warnings.append(
            "Security data was aligned to the last shared completed benchmark session."
        )
    confidence = (
        "LOW"
        if len(aligned) < 90 or liquidity < 35
        else "MEDIUM"
        if len(aligned) < 126 or risk_penalty >= 60
        else "HIGH"
    )
    entry_timing = (
        trend_confirmation
        if setup_type == SetupType.MOMENTUM
        else reversal_trigger
    )
    entry_stage_confidence = _entry_stage_confidence(
        setup_type=setup_type,
        entry_stage=entry_stage,
        one_week_opportunity=one_week_opportunity or 0.0,
        momentum=momentum,
        bounce_potential=bounce_potential,
        reversal_trigger=reversal_trigger,
        trend_confirmation=trend_confirmation,
        payoff_asymmetry=payoff_asymmetry,
        entry_value=entry_value,
        momentum_extension_risk=momentum_extension_risk,
        risk_penalty=risk_penalty,
        falling_knife_risk=falling_knife_risk,
    )
    maximum_risk_unit_multiplier = (
        0.25
        if actionability == Actionability.LIMITED_ENTRY
        else 1.0
        if actionability == Actionability.ENTRY
        else 0.0
    )
    return TacticalAssessment(
        version=TACTICAL_SIGNAL_VERSION,
        decision_domain="SHORT_TERM_SPECULATION",
        data_cadence="COMPLETED_DAILY_SESSION",
        effective_from="NEXT_SESSION_OPEN",
        signal_ttl_completed_sessions=1,
        as_of_date=aligned[-1].trading_date,
        setup_type=setup_type,
        entry_stage=entry_stage,
        entry_stage_confidence=entry_stage_confidence,
        actionability=actionability,
        maximum_risk_unit_multiplier=maximum_risk_unit_multiplier,
        legacy_state=_legacy_state(setup_type, entry_stage, actionability),
        confidence=confidence,
        momentum_score=round(momentum, 2),
        momentum_extension_risk_score=round(momentum_extension_risk, 2),
        bounce_potential_score=round(bounce_potential, 2),
        reversal_trigger_score=round(reversal_trigger, 2),
        reversal_structure_present=reversal_structure_present,
        trend_confirmation_score=round(trend_confirmation, 2),
        entry_timing_score=round(entry_timing, 2),
        entry_value_score=round(entry_value, 2),
        payoff_asymmetry_score=round(payoff_asymmetry, 2),
        market_regime_score=round(regime, 2),
        event_drift_score=round(event, 2),
        liquidity_score=round(liquidity, 2),
        risk_penalty=round(risk_penalty, 2),
        falling_knife_risk_score=round(falling_knife_risk, 2),
        invalidation_level=(
            round(invalidation_level, 6)
            if entry_stage
            in {EntryStage.PROBE_ELIGIBLE, EntryStage.CONFIRMED}
            else None
        ),
        invalidation_distance_percent=(
            round((latest - invalidation_level) / latest * 100.0, 2)
            if entry_stage
            in {EntryStage.PROBE_ELIGIBLE, EntryStage.CONFIRMED}
            else None
        ),
        returns={key: round(value * 100.0, 2) for key, value in returns.items()},
        relative_returns={
            key: round(value * 100.0, 2) for key, value in relative.items()
        },
        horizons=tuple(horizons),
        aligned_session_count=len(aligned),
        reasons=tuple(reasons),
        warnings=tuple(warnings),
    )


def serialize_tactical_assessment(assessment: TacticalAssessment) -> str:
    """Serialize an assessment canonically for hashing, replay, and audit."""

    return json.dumps(
        asdict(assessment),
        default=lambda value: value.isoformat() if isinstance(value, date) else str(value),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
