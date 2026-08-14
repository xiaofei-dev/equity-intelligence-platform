"""Deterministic Quant Trading v2 regime-filtered mean-reversion strategy."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal, DecimalException, localcontext
from enum import StrEnum
from typing import Any

MODEL_VERSION = "QUANT-TRADING-v2.0.0"
STRATEGY_VERSION = "REGIME-FILTERED-MEAN-REVERSION-v2.0.0"
FORMULA_VERSION = "REGIME-FILTERED-MEAN-REVERSION-FORMULAS-v2.0.0"
ENTRY_EXIT_POLICY_VERSION = "REGIME-FILTERED-MEAN-REVERSION-ENTRY-EXIT-v2.0.0"
ENGINE_VERSION = "QUANT-TRADING-ENGINE-v2.0.0"
CONTRACT_VERSION = "quant-trading-system-v2.0.0"
MODEL_EVIDENCE_LABEL = "NOT_VALIDATED"

REQUIRED_HISTORY = 253
MINIMUM_CROSS_SECTION = 20
MINIMUM_ELIGIBLE_SET = 3
MAX_POSITIONS = 5
MAX_HOLDING_SESSIONS = 10
INITIAL_CASH = Decimal("100000")
RISK_FRACTION = Decimal("0.005")
NOTIONAL_FRACTION = Decimal("0.20")
MAX_ABSOLUTE_DECIMAL = Decimal("1e100")
MAX_VOLUME = 9_223_372_036_854_775_807


class QuantTradingV2Violation(ValueError):
    """Raised when the frozen v2 contract or deterministic input is invalid."""


class SignalStateV2(StrEnum):
    ELIGIBLE = "ELIGIBLE"
    INELIGIBLE = "INELIGIBLE"
    MISSING = "MISSING"
    INVALID = "INVALID"


class RankedStateV2(StrEnum):
    ENTRY_ELIGIBLE = "ENTRY_ELIGIBLE"
    NOT_SELECTED = "NOT_SELECTED"
    NOT_RANKED = "NOT_RANKED"


@dataclass(frozen=True)
class MeanReversionBarV2:
    session_date: date
    open_price: Decimal
    high_price: Decimal
    low_price: Decimal
    close_price: Decimal
    volume: int

    def __post_init__(self) -> None:
        if type(self.session_date) is not date:
            raise QuantTradingV2Violation("session_date must be a date")
        prices = tuple(
            _positive(value, name)
            for value, name in (
                (self.open_price, "open_price"),
                (self.high_price, "high_price"),
                (self.low_price, "low_price"),
                (self.close_price, "close_price"),
            )
        )
        if self.high_price < max(prices) or self.low_price > min(prices):
            raise QuantTradingV2Violation("OHLC geometry is invalid")
        if type(self.volume) is not int or not 1 <= self.volume <= MAX_VOLUME:
            raise QuantTradingV2Violation("volume must be a positive signed int64")


@dataclass(frozen=True)
class MeanReversionFeaturesV2:
    atr14: Decimal
    sma20: Decimal
    sma50: Decimal
    sma200: Decimal
    market_sma200: Decimal
    rsi2: Decimal
    zscore20: Decimal
    pullback_from_sma20: Decimal
    median_adtv20: Decimal
    atr_percent: Decimal

    def __post_init__(self) -> None:
        for field_name in self.__dataclass_fields__:
            _decimal(getattr(self, field_name), f"features.{field_name}")
        if self.atr14 <= 0 or self.median_adtv20 <= 0 or self.atr_percent <= 0:
            raise QuantTradingV2Violation("positive feature is outside its domain")
        if not Decimal("0") <= self.rsi2 <= Decimal("100"):
            raise QuantTradingV2Violation("RSI2 is outside 0..100")


@dataclass(frozen=True)
class EntryPlanV2:
    signal_close: Decimal
    maximum_entry_price: Decimal
    initial_stop: Decimal
    profit_target: Decimal
    atr14: Decimal
    reward_risk_at_maximum_entry: Decimal
    maximum_holding_sessions: int = MAX_HOLDING_SESSIONS

    def __post_init__(self) -> None:
        close = _positive(self.signal_close, "signal_close")
        maximum = _positive(self.maximum_entry_price, "maximum_entry_price")
        stop = _positive(self.initial_stop, "initial_stop")
        target = _positive(self.profit_target, "profit_target")
        atr = _positive(self.atr14, "atr14")
        ratio = _positive(
            self.reward_risk_at_maximum_entry,
            "reward_risk_at_maximum_entry",
        )
        if not stop < close <= maximum < target:
            raise QuantTradingV2Violation("entry plan price geometry is invalid")
        with localcontext() as context:
            context.prec = 50
            context.rounding = ROUND_HALF_EVEN
            expected = (target - maximum) / (maximum - stop)
            distance = (close - stop) / close
            if ratio != expected or ratio < Decimal("1.25"):
                raise QuantTradingV2Violation("entry plan reward-risk is invalid")
            if not Decimal("0.03") <= distance <= Decimal("0.08"):
                raise QuantTradingV2Violation("initial stop distance is outside 3%..8%")
            if maximum != close + Decimal("0.25") * atr:
                raise QuantTradingV2Violation("maximum entry must equal close plus 0.25 ATR")
        if self.maximum_holding_sessions != MAX_HOLDING_SESSIONS:
            raise QuantTradingV2Violation("maximum holding period drift")


@dataclass(frozen=True)
class RawSignalV2:
    security_id: str
    decision_date: date
    state: SignalStateV2
    reasons: tuple[str, ...]
    features: MeanReversionFeaturesV2 | None
    signal_close: Decimal | None
    entry_plan: EntryPlanV2 | None
    input_hash: str
    content_hash: str

    def __post_init__(self) -> None:
        _atom(self.security_id, "security_id")
        if type(self.decision_date) is not date:
            raise QuantTradingV2Violation("decision_date must be a date")
        if type(self.state) is not SignalStateV2:
            raise QuantTradingV2Violation("signal state is invalid")
        if type(self.reasons) is not tuple or any(
            type(item) is not str or not item for item in self.reasons
        ):
            raise QuantTradingV2Violation("signal reasons must be a tuple of strings")
        if self.state is SignalStateV2.ELIGIBLE:
            if (
                self.reasons
                or type(self.features) is not MeanReversionFeaturesV2
                or self.signal_close is None
                or type(self.entry_plan) is not EntryPlanV2
            ):
                raise QuantTradingV2Violation("eligible signal structure is invalid")
            _positive(self.signal_close, "signal_close")
            if self.entry_plan.signal_close != self.signal_close:
                raise QuantTradingV2Violation("entry plan does not bind signal close")
        elif (
            not self.reasons
            or self.features is not None
            or self.signal_close is not None
            or self.entry_plan is not None
        ):
            raise QuantTradingV2Violation("noneligible signal structure is invalid")
        _hash(self.input_hash, "input_hash")
        _hash(self.content_hash, "content_hash")
        if self.content_hash != _content_hash(_raw_body(self)):
            raise QuantTradingV2Violation("raw signal content hash drift")


@dataclass(frozen=True)
class CrossSectionMemberV2:
    security_id: str
    security: tuple[MeanReversionBarV2, ...]

    def __post_init__(self) -> None:
        _atom(self.security_id, "security_id")
        if type(self.security) is not tuple or any(
            type(item) is not MeanReversionBarV2 for item in self.security
        ):
            raise QuantTradingV2Violation("member history must be an exact bar tuple")


@dataclass(frozen=True)
class CrossSectionInputV2:
    decision_ordinal: int
    expected_security_ids: tuple[str, ...]
    market: tuple[MeanReversionBarV2, ...]
    members: tuple[CrossSectionMemberV2, ...]

    def __post_init__(self) -> None:
        if type(self.decision_ordinal) is not int or self.decision_ordinal < 0:
            raise QuantTradingV2Violation("decision ordinal is invalid")
        if (
            type(self.expected_security_ids) is not tuple
            or len(self.expected_security_ids) < MINIMUM_CROSS_SECTION
            or any(type(item) is not str for item in self.expected_security_ids)
            or self.expected_security_ids
            != tuple(sorted(set(self.expected_security_ids)))
        ):
            raise QuantTradingV2Violation("expected denominator is invalid")
        if type(self.market) is not tuple or any(
            type(item) is not MeanReversionBarV2 for item in self.market
        ):
            raise QuantTradingV2Violation("market history must be an exact bar tuple")
        if type(self.members) is not tuple or any(
            type(item) is not CrossSectionMemberV2 for item in self.members
        ):
            raise QuantTradingV2Violation("members must be an exact tuple")
        if tuple(item.security_id for item in self.members) != self.expected_security_ids:
            raise QuantTradingV2Violation("members do not match the canonical denominator")


@dataclass(frozen=True)
class RankedSignalV2:
    security_id: str
    decision_date: date
    raw_input_hash: str
    cross_section_hash: str
    state: RankedStateV2
    rank: int | None
    eligible_count: int
    depth_percentile: Decimal | None
    oversold_percentile: Decimal | None
    composite_score: Decimal | None
    content_hash: str

    def __post_init__(self) -> None:
        _atom(self.security_id, "security_id")
        _hash(self.raw_input_hash, "raw_input_hash")
        _hash(self.cross_section_hash, "cross_section_hash")
        _hash(self.content_hash, "content_hash")
        if type(self.state) is not RankedStateV2:
            raise QuantTradingV2Violation("ranked state is invalid")
        if type(self.eligible_count) is not int or self.eligible_count < 0:
            raise QuantTradingV2Violation("eligible_count is invalid")
        values = (
            self.depth_percentile,
            self.oversold_percentile,
            self.composite_score,
        )
        if self.state is RankedStateV2.NOT_RANKED:
            if self.rank is not None or any(value is not None for value in values):
                raise QuantTradingV2Violation("not-ranked signal carries rank values")
        else:
            if type(self.rank) is not int or not 1 <= self.rank <= self.eligible_count:
                raise QuantTradingV2Violation("rank is outside the eligible set")
            for value in values:
                numeric = _decimal(value, "rank value")
                if not Decimal("0") <= numeric <= Decimal("100"):
                    raise QuantTradingV2Violation("rank value is outside 0..100")
            if (self.state is RankedStateV2.ENTRY_ELIGIBLE) != (
                self.rank <= MAX_POSITIONS
            ):
                raise QuantTradingV2Violation("ranked state does not match position limit")
        if self.content_hash != _content_hash(_ranked_body(self)):
            raise QuantTradingV2Violation("ranked signal content hash drift")


def frozen_v2_contract() -> dict[str, Any]:
    body: dict[str, Any] = {
        "contractVersion": CONTRACT_VERSION,
        "modelVersion": MODEL_VERSION,
        "strategyVersion": STRATEGY_VERSION,
        "formulaVersion": FORMULA_VERSION,
        "entryExitPolicyVersion": ENTRY_EXIT_POLICY_VERSION,
        "engineVersion": ENGINE_VERSION,
        "sleeve": "QUANT_TRADING",
        "setup": "REGIME_FILTERED_MEAN_REVERSION",
        "hypothesis": (
            "Liquid common stocks in established security and broad-market uptrends "
            "may exhibit short-lived mean reversion after an objectively extreme "
            "two-session RSI and twenty-session z-score pullback."
        ),
        "independence": {
            "modifiesV1OrV11InPlace": False,
            "combinesMomentumAndMeanReversionScores": False,
            "sameHistoricalCacheUntouchedHoldoutClaimed": False,
            "sameHistoricalCacheMaximumClaim": "DEVELOPMENT_OBSERVED_ONLY",
            "oneRetrospectiveExecutionOnly": True,
            "sameOutcomeRetuningAllowed": False,
            "unsupportiveResultIsAcceptable": True,
        },
        "signal": {
            "requiredAlignedSessions": REQUIRED_HISTORY,
            "decisionFrequency": "EVERY_COMPLETED_SPY_SESSION",
            "rsi2Formula": (
                "SIMPLE_TWO_CHANGE_RSI; AVERAGE_LAST_TWO_POSITIVE_CHANGES_AND_"
                "AVERAGE_LAST_TWO_ABSOLUTE_NEGATIVE_CHANGES; 100-100/(1+GAIN/LOSS); "
                "BOTH_ZERO=50; LOSS_ZERO=100; GAIN_ZERO=0"
            ),
            "absoluteEligibility": [
                "PRICE_AT_LEAST_5_USD",
                "MEDIAN_ADTV20_AT_LEAST_5000000_USD",
                "SPY_CLOSE_ABOVE_SMA200",
                "SECURITY_CLOSE_ABOVE_SMA200",
                "SECURITY_SMA50_ABOVE_SMA200",
                "SECURITY_CLOSE_BELOW_SMA20",
                "RSI2_AT_MOST_10",
                "ZSCORE20_AT_MOST_MINUS_1.25",
                "ATR_PERCENT_AT_MOST_0.10",
                "MAXIMUM_ENTRY_REWARD_RISK_AT_LEAST_1.25",
            ],
            "crossSectionDenominatorMinimum": MINIMUM_CROSS_SECTION,
            "eligibleSetMinimum": MINIMUM_ELIGIBLE_SET,
            "ranking": {
                "pullbackDepthPercentileWeight": "0.60",
                "rsiOversoldPercentileWeight": "0.40",
                "ordinalTieBreak": "SECURITY_ID_ASC",
                "percentileFormula": "100*(COUNT_LOWER+0.5*(COUNT_EQUAL-1))/(N-1)",
                "maximumEntryRank": MAX_POSITIONS,
            },
        },
        "entry": {
            "timing": "NEXT_OBSERVED_SESSION_OPEN_AFTER_DECISION",
            "maximumEntryPrice": "SIGNAL_CLOSE_PLUS_0.25_ATR14",
            "skipWhenOpenAtOrBelowInitialStop": True,
            "skipWhenOpenAboveMaximumEntryPrice": True,
            "skipWhenOpenAtOrAboveProfitTarget": True,
            "sameSessionReentry": "PROHIBITED",
        },
        "exit": {
            "initialStop": (
                "SIGNAL_CLOSE_MINUS_MIN(MAX(2.5_ATR14,3_PERCENT_SIGNAL_CLOSE),"
                "8_PERCENT_SIGNAL_CLOSE)"
            ),
            "profitTarget": "FROZEN_SIGNAL_SESSION_SMA20",
            "sameBarRule": "STOP_FIRST_THEN_TARGET",
            "maximumHoldingSessions": MAX_HOLDING_SESSIONS,
            "timeExit": "SESSION_10_COMPLETED_CLOSE",
            "nextOpenExit": [
                "SPY_CLOSE_NOT_ABOVE_SMA200",
                "SECURITY_CLOSE_NOT_ABOVE_SMA200",
                "UNEXPLAINED_MISSING_ACTIVE_BAR",
            ],
            "trailingStop": "NONE",
        },
        "portfolio": {
            "initialCashUsd": "100000",
            "maximumPositions": MAX_POSITIONS,
            "riskFractionPerPosition": "0.005",
            "notionalFractionCapPerPosition": "0.20",
            "wholeSharesOnly": True,
            "selectionPriority": ["COMPOSITE_SCORE_DESC", "SECURITY_ID_ASC"],
        },
        "cost": {
            "version": "C9-NONLINEAR-COST-v1.0.0",
            "perSide": (
                "participation=notional/ADTV; impact=min(50bps,25bps*sqrt(participation)); "
                "sideBps=1+impact"
            ),
            "entryAndExitChargedSeparately": True,
            "fixedFiveBpsSensitivityRequired": True,
        },
        "validation": {
            "executionCount": 1,
            "primaryBenchmark": "SPY_BUY_AND_HOLD_SAME_CALENDAR_AND_COST_POLICY",
            "minimumCompletedTrades": 100,
            "gates": {
                "positiveNetCagr": "GREATER_THAN_0",
                "positiveNetExpectancy": "GREATER_THAN_0",
                "sharpeVsSpy": "GREATER_THAN_SPY",
                "calmarVsSpy": "GREATER_THAN_SPY",
                "maximumDrawdownVsSpy": "NO_WORSE_THAN_SPY",
                "cagrVsSpy": "NO_LESS_THAN_SPY_MINUS_0.02",
                "positiveCalendarYears": "AT_LEAST_6_OF_9_MATURE_YEARS",
                "fixedCostSensitivityCagr": "GREATER_THAN_0",
            },
            "directionallySupportiveRule": "AT_LEAST_6_OF_8_GATES_AND_NO_NEGATIVE_EXPECTANCY",
            "productionValidationClaimAllowed": False,
            "failureAction": "RETAIN_NOT_VALIDATED_AND_STOP_WITHOUT_SAME_OUTCOME_RETUNING",
        },
        "governance": {
            "initialModelEvidenceLabel": MODEL_EVIDENCE_LABEL,
            "automaticBrokerageExecution": False,
            "llmSignalOrWeightAuthority": False,
            "finalPortfolioWeightAuthority": False,
            "futureReturnsGuaranteed": False,
        },
    }
    body["contentHash"] = canonical_hash(body)
    return body


def validate_v2_contract(value: dict[str, Any]) -> None:
    if value != frozen_v2_contract():
        raise QuantTradingV2Violation("Quant Trading v2 contract drift")


def calculate_raw_signal_v2(
    *,
    security_id: str,
    security: tuple[MeanReversionBarV2, ...],
    market: tuple[MeanReversionBarV2, ...],
) -> RawSignalV2:
    _atom(security_id, "security_id")
    if type(security) is not tuple or type(market) is not tuple:
        raise QuantTradingV2Violation("signal histories must be tuples")
    if any(type(item) is not MeanReversionBarV2 for item in (*security, *market)):
        raise QuantTradingV2Violation("signal histories contain invalid bars")
    input_hash = _signal_hash(security_id, security, market)
    if len(security) != REQUIRED_HISTORY or len(market) != REQUIRED_HISTORY:
        return _noneligible(
            security_id,
            security,
            market,
            SignalStateV2.MISSING,
            ("ALIGNED_HISTORY_INCOMPLETE",),
            input_hash,
        )
    dates = tuple(item.session_date for item in security)
    if dates != tuple(item.session_date for item in market) or dates != tuple(
        sorted(set(dates))
    ):
        return _noneligible(
            security_id,
            security,
            market,
            SignalStateV2.INVALID,
            ("ALIGNED_HISTORY_INVALID",),
            input_hash,
        )
    try:
        features = _features(security, market)
        plan = entry_plan_from_features_v2(security[-1].close_price, features)
    except (ArithmeticError, DecimalException, QuantTradingV2Violation):
        return _noneligible(
            security_id,
            security,
            market,
            SignalStateV2.INVALID,
            ("FEATURE_OR_PLAN_CALCULATION_INVALID",),
            input_hash,
        )
    close = security[-1].close_price
    checks = (
        (close >= Decimal("5"), "PRICE_BELOW_MINIMUM"),
        (features.median_adtv20 >= Decimal("5000000"), "LIQUIDITY_BELOW_MINIMUM"),
        (market[-1].close_price > features.market_sma200, "MARKET_REGIME_NOT_READY"),
        (close > features.sma200, "SECURITY_LONG_TREND_NOT_READY"),
        (features.sma50 > features.sma200, "SECURITY_TREND_SLOPE_NOT_READY"),
        (close < features.sma20, "PULLBACK_NOT_BELOW_MEAN"),
        (features.rsi2 <= Decimal("10"), "RSI2_NOT_OVERSOLD"),
        (features.zscore20 <= Decimal("-1.25"), "ZSCORE20_NOT_EXTREME"),
        (features.atr_percent <= Decimal("0.10"), "ATR_PERCENT_TOO_HIGH"),
        (plan is not None, "ENTRY_REWARD_RISK_INSUFFICIENT"),
    )
    reasons = tuple(reason for passed, reason in checks if not passed)
    if reasons:
        return _raw_signal(
            security_id,
            security[-1].session_date,
            SignalStateV2.INELIGIBLE,
            reasons,
            None,
            None,
            None,
            input_hash,
        )
    assert plan is not None
    return _raw_signal(
        security_id,
        security[-1].session_date,
        SignalStateV2.ELIGIBLE,
        (),
        features,
        close,
        plan,
        input_hash,
    )


def rank_cross_section_v2(value: CrossSectionInputV2) -> tuple[RankedSignalV2, ...]:
    if type(value) is not CrossSectionInputV2:
        raise QuantTradingV2Violation("cross-section input type is invalid")
    signals = tuple(
        calculate_raw_signal_v2(
            security_id=member.security_id,
            security=member.security,
            market=value.market,
        )
        for member in value.members
    )
    if len({item.decision_date for item in signals}) != 1:
        raise QuantTradingV2Violation("cross section mixes decision dates")
    cross_hash = _content_hash(
        {
            "modelVersion": MODEL_VERSION,
            "strategyVersion": STRATEGY_VERSION,
            "decisionOrdinal": value.decision_ordinal,
            "expectedSecurityIds": list(value.expected_security_ids),
            "rawSignals": [[item.security_id, item.content_hash] for item in signals],
        }
    )
    eligible = tuple(item for item in signals if item.state is SignalStateV2.ELIGIBLE)
    if len(eligible) < MINIMUM_ELIGIBLE_SET:
        return tuple(_not_ranked(item, len(eligible), cross_hash) for item in signals)
    scored: list[tuple[RawSignalV2, Decimal, Decimal, Decimal]] = []
    with localcontext() as context:
        context.prec = 50
        context.rounding = ROUND_HALF_EVEN
        for item in eligible:
            assert item.features is not None
            depth = _percentile(
                eligible,
                item,
                lambda signal: -_required_features(signal).zscore20,
            )
            oversold = _percentile(
                eligible,
                item,
                lambda signal: Decimal("100") - _required_features(signal).rsi2,
            )
            score = Decimal("0.60") * depth + Decimal("0.40") * oversold
            scored.append((item, depth, oversold, score))
    ordered = sorted(scored, key=lambda row: (-row[3], row[0].security_id))
    ranks = {row[0].security_id: index for index, row in enumerate(ordered, 1)}
    by_id = {row[0].security_id: row for row in scored}
    result: list[RankedSignalV2] = []
    for item in signals:
        row = by_id.get(item.security_id)
        if row is None:
            result.append(_not_ranked(item, len(eligible), cross_hash))
            continue
        _, depth, oversold, score = row
        rank = ranks[item.security_id]
        state = (
            RankedStateV2.ENTRY_ELIGIBLE
            if rank <= MAX_POSITIONS
            else RankedStateV2.NOT_SELECTED
        )
        body = {
            "securityId": item.security_id,
            "decisionDate": item.decision_date.isoformat(),
            "rawInputHash": item.input_hash,
            "crossSectionHash": cross_hash,
            "state": state.value,
            "rank": rank,
            "eligibleCount": len(eligible),
            "depthPercentile": _decimal_text(depth),
            "oversoldPercentile": _decimal_text(oversold),
            "compositeScore": _decimal_text(score),
        }
        result.append(
            RankedSignalV2(
                item.security_id,
                item.decision_date,
                item.input_hash,
                cross_hash,
                state,
                rank,
                len(eligible),
                depth,
                oversold,
                score,
                _content_hash(body),
            )
        )
    return tuple(result)


def _features(
    security: tuple[MeanReversionBarV2, ...],
    market: tuple[MeanReversionBarV2, ...],
) -> MeanReversionFeaturesV2:
    closes = tuple(item.close_price for item in security)
    market_closes = tuple(item.close_price for item in market)
    t = REQUIRED_HISTORY - 1
    with localcontext() as context:
        context.prec = 50
        context.rounding = ROUND_HALF_EVEN
        true_ranges = tuple(
            max(
                security[index].high_price - security[index].low_price,
                abs(security[index].high_price - security[index - 1].close_price),
                abs(security[index].low_price - security[index - 1].close_price),
            )
            for index in range(t - 13, t + 1)
        )
        atr = sum(true_ranges, Decimal("0")) / Decimal("14")
        sma20 = sum(closes[-20:], Decimal("0")) / Decimal("20")
        sma50 = sum(closes[-50:], Decimal("0")) / Decimal("50")
        sma200 = sum(closes[-200:], Decimal("0")) / Decimal("200")
        market_sma200 = sum(market_closes[-200:], Decimal("0")) / Decimal("200")
        variance = sum(
            ((item - sma20) * (item - sma20) for item in closes[-20:]),
            Decimal("0"),
        ) / Decimal("20")
        if variance <= 0:
            raise QuantTradingV2Violation("twenty-session variance must be positive")
        standard_deviation = variance.sqrt()
        zscore = (closes[-1] - sma20) / standard_deviation
        rsi = _rsi2(closes)
        adtv = _median(
            tuple(item.close_price * Decimal(item.volume) for item in security[-20:])
        )
        atr_percent = atr / closes[-1]
        pullback = closes[-1] / sma20 - Decimal("1")
    values = (
        atr,
        sma20,
        sma50,
        sma200,
        market_sma200,
        rsi,
        zscore,
        pullback,
        adtv,
        atr_percent,
    )
    if any(not item.is_finite() or abs(item) > MAX_ABSOLUTE_DECIMAL for item in values):
        raise QuantTradingV2Violation("calculated feature is outside its domain")
    return MeanReversionFeaturesV2(*values)


def _rsi2(closes: tuple[Decimal, ...]) -> Decimal:
    if len(closes) < 3:
        raise QuantTradingV2Violation("RSI2 history is incomplete")
    with localcontext() as context:
        context.prec = 50
        context.rounding = ROUND_HALF_EVEN
        changes = (closes[-2] - closes[-3], closes[-1] - closes[-2])
        gains = tuple(max(change, Decimal("0")) for change in changes)
        losses = tuple(max(-change, Decimal("0")) for change in changes)
        average_gain = (gains[0] + gains[1]) / Decimal("2")
        average_loss = (losses[0] + losses[1]) / Decimal("2")
        if average_gain == 0 and average_loss == 0:
            return Decimal("50")
        if average_loss == 0:
            return Decimal("100")
        if average_gain == 0:
            return Decimal("0")
        relative_strength = average_gain / average_loss
        return Decimal("100") - Decimal("100") / (Decimal("1") + relative_strength)


def entry_plan_from_features_v2(
    signal_close: Decimal,
    features: MeanReversionFeaturesV2,
) -> EntryPlanV2 | None:
    if type(features) is not MeanReversionFeaturesV2:
        raise QuantTradingV2Violation("entry-plan features type is invalid")
    close = _positive(signal_close, "signal_close")
    with localcontext() as context:
        context.prec = 50
        context.rounding = ROUND_HALF_EVEN
        distance = min(
            max(Decimal("2.5") * features.atr14, Decimal("0.03") * close),
            Decimal("0.08") * close,
        )
        stop = close - distance
        maximum = close + Decimal("0.25") * features.atr14
        target = features.sma20
        if stop <= 0 or not close <= maximum < target:
            return None
        ratio = (target - maximum) / (maximum - stop)
        if ratio < Decimal("1.25"):
            return None
    return EntryPlanV2(close, maximum, stop, target, features.atr14, ratio)


def _raw_signal(
    security_id: str,
    decision_date: date,
    state: SignalStateV2,
    reasons: tuple[str, ...],
    features: MeanReversionFeaturesV2 | None,
    signal_close: Decimal | None,
    entry_plan: EntryPlanV2 | None,
    input_hash: str,
) -> RawSignalV2:
    body = {
        "securityId": security_id,
        "decisionDate": decision_date.isoformat(),
        "state": state.value,
        "reasons": list(reasons),
        "features": _features_primitive(features) if features is not None else None,
        "signalClose": _decimal_text(signal_close) if signal_close is not None else None,
        "entryPlan": _entry_plan_primitive(entry_plan) if entry_plan is not None else None,
        "inputHash": input_hash,
    }
    return RawSignalV2(
        security_id,
        decision_date,
        state,
        reasons,
        features,
        signal_close,
        entry_plan,
        input_hash,
        _content_hash(body),
    )


def _noneligible(
    security_id: str,
    security: tuple[MeanReversionBarV2, ...],
    market: tuple[MeanReversionBarV2, ...],
    state: SignalStateV2,
    reasons: tuple[str, ...],
    input_hash: str,
) -> RawSignalV2:
    decision_date = (
        security[-1].session_date
        if security
        else (market[-1].session_date if market else date.min)
    )
    return _raw_signal(
        security_id,
        decision_date,
        state,
        reasons,
        None,
        None,
        None,
        input_hash,
    )


def _not_ranked(
    signal: RawSignalV2,
    eligible_count: int,
    cross_hash: str,
) -> RankedSignalV2:
    body = {
        "securityId": signal.security_id,
        "decisionDate": signal.decision_date.isoformat(),
        "rawInputHash": signal.input_hash,
        "crossSectionHash": cross_hash,
        "state": RankedStateV2.NOT_RANKED.value,
        "rank": None,
        "eligibleCount": eligible_count,
        "depthPercentile": None,
        "oversoldPercentile": None,
        "compositeScore": None,
    }
    return RankedSignalV2(
        signal.security_id,
        signal.decision_date,
        signal.input_hash,
        cross_hash,
        RankedStateV2.NOT_RANKED,
        None,
        eligible_count,
        None,
        None,
        None,
        _content_hash(body),
    )


def _percentile(
    signals: tuple[RawSignalV2, ...],
    current: RawSignalV2,
    value: Any,
) -> Decimal:
    values = tuple(value(signal) for signal in signals)
    current_value = value(current)
    if len(values) == 1:
        return Decimal("50")
    lower = sum(item < current_value for item in values)
    equal_others = sum(item == current_value for item in values) - 1
    return (
        Decimal("100")
        * (Decimal(lower) + Decimal("0.5") * Decimal(equal_others))
        / Decimal(len(values) - 1)
    )


def _required_features(signal: RawSignalV2) -> MeanReversionFeaturesV2:
    if signal.features is None:
        raise QuantTradingV2Violation("eligible signal has no features")
    return signal.features


def _signal_hash(
    security_id: str,
    security: tuple[MeanReversionBarV2, ...],
    market: tuple[MeanReversionBarV2, ...],
) -> str:
    return _content_hash(
        {
            "modelVersion": MODEL_VERSION,
            "strategyVersion": STRATEGY_VERSION,
            "securityId": security_id,
            "security": [_bar_primitive(item) for item in security],
            "market": [_bar_primitive(item) for item in market],
        }
    )


def _bar_primitive(value: MeanReversionBarV2) -> list[Any]:
    return [
        value.session_date.isoformat(),
        _decimal_text(value.open_price),
        _decimal_text(value.high_price),
        _decimal_text(value.low_price),
        _decimal_text(value.close_price),
        value.volume,
    ]


def _features_primitive(value: MeanReversionFeaturesV2) -> dict[str, str]:
    return {name: _decimal_text(getattr(value, name)) for name in value.__dataclass_fields__}


def _entry_plan_primitive(value: EntryPlanV2) -> dict[str, Any]:
    return {
        "signalClose": _decimal_text(value.signal_close),
        "maximumEntryPrice": _decimal_text(value.maximum_entry_price),
        "initialStop": _decimal_text(value.initial_stop),
        "profitTarget": _decimal_text(value.profit_target),
        "atr14": _decimal_text(value.atr14),
        "rewardRiskAtMaximumEntry": _decimal_text(value.reward_risk_at_maximum_entry),
        "maximumHoldingSessions": value.maximum_holding_sessions,
    }


def _raw_body(value: RawSignalV2) -> dict[str, Any]:
    return {
        "securityId": value.security_id,
        "decisionDate": value.decision_date.isoformat(),
        "state": value.state.value,
        "reasons": list(value.reasons),
        "features": _features_primitive(value.features) if value.features else None,
        "signalClose": _decimal_text(value.signal_close) if value.signal_close else None,
        "entryPlan": _entry_plan_primitive(value.entry_plan) if value.entry_plan else None,
        "inputHash": value.input_hash,
    }


def _ranked_body(value: RankedSignalV2) -> dict[str, Any]:
    return {
        "securityId": value.security_id,
        "decisionDate": value.decision_date.isoformat(),
        "rawInputHash": value.raw_input_hash,
        "crossSectionHash": value.cross_section_hash,
        "state": value.state.value,
        "rank": value.rank,
        "eligibleCount": value.eligible_count,
        "depthPercentile": (
            _decimal_text(value.depth_percentile)
            if value.depth_percentile is not None
            else None
        ),
        "oversoldPercentile": (
            _decimal_text(value.oversold_percentile)
            if value.oversold_percentile is not None
            else None
        ),
        "compositeScore": (
            _decimal_text(value.composite_score)
            if value.composite_score is not None
            else None
        ),
    }


def canonical_hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode(
            "utf-8"
        )
    ).hexdigest().upper()


def _content_hash(value: object) -> str:
    return "sha256:" + canonical_hash(value).lower()


def _decimal(value: object, name: str) -> Decimal:
    if type(value) is not Decimal or not value.is_finite() or abs(value) > MAX_ABSOLUTE_DECIMAL:
        raise QuantTradingV2Violation(f"{name} must be a finite bounded Decimal")
    return value


def _positive(value: object, name: str) -> Decimal:
    numeric = _decimal(value, name)
    if numeric <= 0:
        raise QuantTradingV2Violation(f"{name} must be positive")
    return numeric


def _decimal_text(value: Decimal) -> str:
    numeric = _decimal(value, "decimal")
    if numeric == 0:
        return "0"
    text = format(numeric, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def _median(values: tuple[Decimal, ...]) -> Decimal:
    if not values:
        raise QuantTradingV2Violation("median requires observations")
    ordered = tuple(sorted(values))
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / Decimal("2")


def _atom(value: object, name: str) -> str:
    if type(value) is not str or not value or value != value.strip() or "|" in value:
        raise QuantTradingV2Violation(f"{name} is invalid")
    return value


def _hash(value: object, name: str) -> str:
    if (
        type(value) is not str
        or not value.startswith("sha256:")
        or len(value) != 71
        or any(character not in "0123456789abcdef" for character in value[7:])
    ):
        raise QuantTradingV2Violation(f"{name} is invalid")
    return value
