"""Pure deterministic Quant Trading v1.1 dual-momentum trend strategy."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal, DecimalException, localcontext
from enum import StrEnum
from typing import Any

MODEL_VERSION = "QUANT-TRADING-v1.1.0"
STRATEGY_VERSION = "DUAL-MOMENTUM-TREND-v1.1.0"
FORMULA_VERSION = "DUAL-MOMENTUM-TREND-FORMULAS-v1.1.0"
ENTRY_EXIT_POLICY_VERSION = "DUAL-MOMENTUM-TREND-ENTRY-EXIT-v1.1.0"
ENGINE_VERSION = "QUANT-TRADING-ENGINE-v1.1.0"
CONTRACT_VERSION = "quant-trading-system-v1.1.0"
MODEL_EVIDENCE_LABEL = "NOT_VALIDATED"

REQUIRED_HISTORY = 253
REBALANCE_INTERVAL = 5
MAX_POSITIONS = 10
MAX_HOLDING_SESSIONS = 126
MINIMUM_CROSS_SECTION = 20
ENTRY_PERCENTILE = Decimal("80")
RETENTION_PERCENTILE = Decimal("60")
INITIAL_CASH = Decimal("100000")
RISK_FRACTION = Decimal("0.005")
NOTIONAL_FRACTION = Decimal("0.10")
MAX_ABSOLUTE_DECIMAL = Decimal("1e100")
MAX_VOLUME = 9_223_372_036_854_775_807


class QuantTradingV11Violation(ValueError):
    pass


class SignalState(StrEnum):
    ELIGIBLE = "ELIGIBLE"
    INELIGIBLE = "INELIGIBLE"
    MISSING = "MISSING"
    INVALID = "INVALID"


class RankedState(StrEnum):
    ENTRY_ELIGIBLE = "ENTRY_ELIGIBLE"
    HOLD_ELIGIBLE = "HOLD_ELIGIBLE"
    EXIT_ELIGIBLE = "EXIT_ELIGIBLE"
    NOT_RANKED = "NOT_RANKED"


@dataclass(frozen=True)
class TrendBarV11:
    session_date: date
    open_price: Decimal
    high_price: Decimal
    low_price: Decimal
    close_price: Decimal
    volume: int

    def __post_init__(self) -> None:
        if type(self.session_date) is not date:
            raise QuantTradingV11Violation("session_date must be a date")
        prices = tuple(
            _decimal(value, name)
            for value, name in (
                (self.open_price, "open_price"),
                (self.high_price, "high_price"),
                (self.low_price, "low_price"),
                (self.close_price, "close_price"),
            )
        )
        if min(prices) <= 0:
            raise QuantTradingV11Violation("prices must be positive")
        if self.high_price < max(self.open_price, self.low_price, self.close_price):
            raise QuantTradingV11Violation("high_price is below another price")
        if self.low_price > min(self.open_price, self.high_price, self.close_price):
            raise QuantTradingV11Violation("low_price is above another price")
        if type(self.volume) is not int or not 1 <= self.volume <= MAX_VOLUME:
            raise QuantTradingV11Violation("volume must be a positive signed int64")


@dataclass(frozen=True)
class TrendFeaturesV11:
    atr14: Decimal
    sma100: Decimal
    sma200: Decimal
    market_sma200: Decimal
    momentum252_skip20: Decimal
    momentum126_skip20: Decimal
    market_momentum252_skip20: Decimal
    market_momentum126_skip20: Decimal
    relative252_skip20: Decimal
    relative126_skip20: Decimal
    median_adtv20: Decimal
    atr_percent: Decimal

    def __post_init__(self) -> None:
        for field_name in self.__dataclass_fields__:
            _decimal(getattr(self, field_name), f"features.{field_name}")
        if self.atr14 <= 0 or self.median_adtv20 <= 0 or self.atr_percent <= 0:
            raise QuantTradingV11Violation("positive feature is outside its domain")


@dataclass(frozen=True)
class RawSignalV11:
    security_id: str
    decision_date: date
    state: SignalState
    reasons: tuple[str, ...]
    features: TrendFeaturesV11 | None
    signal_close: Decimal | None
    input_hash: str
    content_hash: str

    def __post_init__(self) -> None:
        _atom(self.security_id, "security_id")
        if type(self.decision_date) is not date:
            raise QuantTradingV11Violation("decision_date must be a date")
        if type(self.state) is not SignalState:
            raise QuantTradingV11Violation("signal state is invalid")
        if type(self.reasons) is not tuple or any(type(item) is not str for item in self.reasons):
            raise QuantTradingV11Violation("signal reasons must be a tuple of strings")
        if self.state is SignalState.ELIGIBLE:
            if (
                self.reasons
                or type(self.features) is not TrendFeaturesV11
                or self.signal_close is None
            ):
                raise QuantTradingV11Violation("eligible signal structure is invalid")
            _positive(self.signal_close, "signal_close")
        elif not self.reasons or self.features is not None or self.signal_close is not None:
            raise QuantTradingV11Violation("noneligible signal structure is invalid")
        _hash(self.input_hash, "input_hash")
        _hash(self.content_hash, "content_hash")
        if self.content_hash != "sha256:" + canonical_hash(_raw_signal_body(self)).lower():
            raise QuantTradingV11Violation("raw signal content hash drift")


@dataclass(frozen=True)
class CrossSectionMemberV11:
    security_id: str
    security: tuple[TrendBarV11, ...]

    def __post_init__(self) -> None:
        _atom(self.security_id, "security_id")
        if type(self.security) is not tuple:
            raise QuantTradingV11Violation("cross-section security history must be a tuple")
        if any(type(item) is not TrendBarV11 for item in self.security):
            raise QuantTradingV11Violation("cross-section history contains an invalid bar")


@dataclass(frozen=True)
class CrossSectionInputV11:
    rebalance_ordinal: int
    expected_security_ids: tuple[str, ...]
    market: tuple[TrendBarV11, ...]
    members: tuple[CrossSectionMemberV11, ...]

    def __post_init__(self) -> None:
        if (
            type(self.rebalance_ordinal) is not int
            or self.rebalance_ordinal < 0
            or self.rebalance_ordinal % REBALANCE_INTERVAL != 0
        ):
            raise QuantTradingV11Violation("rebalance ordinal is outside the five-session schedule")
        if (
            type(self.expected_security_ids) is not tuple
            or len(self.expected_security_ids) < MINIMUM_CROSS_SECTION
            or any(type(item) is not str for item in self.expected_security_ids)
        ):
            raise QuantTradingV11Violation("expected security denominator is invalid")
        if self.expected_security_ids != tuple(sorted(set(self.expected_security_ids))):
            raise QuantTradingV11Violation(
                "expected security denominator must be sorted and unique"
            )
        if type(self.market) is not tuple or any(
            type(item) is not TrendBarV11 for item in self.market
        ):
            raise QuantTradingV11Violation("cross-section market history must be an exact tuple")
        if type(self.members) is not tuple or any(
            type(item) is not CrossSectionMemberV11 for item in self.members
        ):
            raise QuantTradingV11Violation("cross-section members must be an exact tuple")
        observed = tuple(item.security_id for item in self.members)
        if observed != self.expected_security_ids:
            raise QuantTradingV11Violation(
                "cross section must exactly match the canonical expected denominator order"
            )


@dataclass(frozen=True)
class RankedSignalV11:
    security_id: str
    decision_date: date
    raw_input_hash: str
    cross_section_hash: str
    state: RankedState
    rank: int | None
    cross_section_count: int
    momentum252_percentile: Decimal | None
    momentum126_percentile: Decimal | None
    composite_score: Decimal | None
    content_hash: str

    def __post_init__(self) -> None:
        _atom(self.security_id, "security_id")
        _hash(self.raw_input_hash, "raw_input_hash")
        _hash(self.cross_section_hash, "cross_section_hash")
        _hash(self.content_hash, "content_hash")
        if type(self.state) is not RankedState:
            raise QuantTradingV11Violation("ranked state is invalid")
        if type(self.cross_section_count) is not int or self.cross_section_count < 0:
            raise QuantTradingV11Violation("cross_section_count is invalid")
        values = (
            self.momentum252_percentile,
            self.momentum126_percentile,
            self.composite_score,
        )
        if self.state is RankedState.NOT_RANKED:
            if self.rank is not None or any(item is not None for item in values):
                raise QuantTradingV11Violation("not-ranked signal carries rank values")
        else:
            if type(self.rank) is not int or not 1 <= self.rank <= self.cross_section_count:
                raise QuantTradingV11Violation("rank is outside its cross section")
            for value in values:
                numeric = _decimal(value, "rank value")
                if not Decimal("0") <= numeric <= Decimal("100"):
                    raise QuantTradingV11Violation("rank value is outside 0..100")
        expected = "sha256:" + canonical_hash(_ranked_body(self)).lower()
        if self.content_hash != expected:
            raise QuantTradingV11Violation("ranked signal content hash drift")


@dataclass(frozen=True)
class EntryPlanV11:
    signal_close: Decimal
    initial_stop: Decimal
    maximum_entry_price: Decimal
    atr14: Decimal
    maximum_holding_sessions: int = MAX_HOLDING_SESSIONS

    def __post_init__(self) -> None:
        close = _positive(self.signal_close, "signal_close")
        stop = _positive(self.initial_stop, "initial_stop")
        maximum = _positive(self.maximum_entry_price, "maximum_entry_price")
        atr = _positive(self.atr14, "atr14")
        if not stop < close < maximum:
            raise QuantTradingV11Violation("entry plan price geometry is invalid")
        with localcontext() as context:
            context.prec = 50
            context.rounding = ROUND_HALF_EVEN
            fraction = (close - stop) / close
            if not Decimal("0.02") <= fraction <= Decimal("0.10"):
                raise QuantTradingV11Violation(
                    "initial stop must be 2% to 10% below signal close"
                )
            if maximum != close + Decimal("2") * atr:
                raise QuantTradingV11Violation("maximum entry price must equal close plus two ATR")
        if self.maximum_holding_sessions != MAX_HOLDING_SESSIONS:
            raise QuantTradingV11Violation("maximum holding period drift")


def frozen_v11_contract() -> dict[str, Any]:
    body: dict[str, Any] = {
        "contractVersion": CONTRACT_VERSION,
        "modelVersion": MODEL_VERSION,
        "strategyVersion": STRATEGY_VERSION,
        "formulaVersion": FORMULA_VERSION,
        "entryExitPolicyVersion": ENTRY_EXIT_POLICY_VERSION,
        "engineVersion": ENGINE_VERSION,
        "sleeve": "QUANT_TRADING",
        "setup": "DUAL_MOMENTUM_TREND",
        "hypothesis": (
            "Liquid equities with positive medium-term absolute momentum and the "
            "strongest cross-sectional 12-1 and 6-1 momentum, held while broad-market "
            "and security trends remain positive, may improve risk-adjusted participation "
            "by allowing winners to run."
        ),
        "outcomeAwareness": {
            "designedAfterV1OutcomeWasObserved": True,
            "sameHistoryUntouchedHoldoutClaimed": False,
            "sameHistoryMaximumClaim": "DEVELOPMENT_OBSERVED_ONLY",
            "v1ParametersMayBeModifiedInPlace": False,
            "predecessorDispositionHash": (
                "02D8410EC8FF7690C7FE30E4296C06162E708CBF5A0D9F88AEA030737B035F4D"
            ),
            "predecessorValidationProtocolHash": (
                "84B5DEEDF5ABE572C135E3E1CF3D4FF7ED391F93A20A82D4F3B6C1BF48F070BC"
            ),
            "predecessorFullResultHash": (
                "F87E4AF65E9E2AAF73BC6ADA7142FB5C78E21D0E2D8E95771D83963C1533AB8D"
            ),
        },
        "signal": {
            "requiredAlignedSessions": REQUIRED_HISTORY,
            "decisionFrequency": "EVERY_FIFTH_COMPLETED_SPY_SESSION_FROM_FIRST_ELIGIBLE_SESSION",
            "absoluteEligibility": [
                "PRICE_AT_LEAST_5_USD",
                "MEDIAN_ADTV20_AT_LEAST_5000000_USD",
                "SECURITY_CLOSE_ABOVE_SMA200",
                "SPY_CLOSE_ABOVE_SMA200",
                "MOMENTUM_252_SKIP20_POSITIVE",
                "MOMENTUM_126_SKIP20_POSITIVE",
                "ATR_PERCENT_AT_MOST_0.10",
            ],
            "crossSectionMinimum": MINIMUM_CROSS_SECTION,
            "ranking": {
                "momentum252Skip20Weight": "0.60",
                "momentum126Skip20Weight": "0.40",
                "ordinalTieBreak": "SECURITY_ID_ASC",
                "percentileFormula": "100*(COUNT_LOWER+0.5*(COUNT_EQUAL-1))/(N-1)",
                "entryMinimumPercentile": "80",
                "retentionMinimumPercentile": "60",
                "maximumEntryRank": 10,
            },
        },
        "entry": {
            "timing": "NEXT_OBSERVED_SESSION_OPEN_AFTER_REBALANCE_DECISION",
            "skipWhenOpenAtOrBelowInitialStop": True,
            "skipWhenOpenAboveSignalClosePlusAtrMultiple": "2",
            "intradayReclaimEntry": False,
        },
        "exit": {
            "profitTarget": "NONE_ALLOW_WINNERS_TO_RUN",
            "hardStop": (
                "MAX_OF_SIGNAL_CLOSE_MINUS_3_ATR_AND_SIGNAL_CLOSE_MINUS_10_PERCENT_"
                "WITH_MINIMUM_2_PERCENT_DISTANCE"
            ),
            "trailingStop": (
                "MAX_PRIOR_ACTIVE_STOP_AND_HIGHEST_COMPLETED_CLOSE_SINCE_ENTRY_"
                "INCLUSIVE_MINUS_3_TIMES_CURRENT_COMPLETED_SESSION_ATR14"
            ),
            "trailingActivation": (
                "AFTER_ENTRY_SESSION_CLOSE_FOR_NEXT_SESSION; NEVER_LOWER_ACTIVE_STOP"
            ),
            "nextOpenExit": [
                "SPY_CLOSE_NOT_ABOVE_SMA200",
                "SECURITY_CLOSE_NOT_ABOVE_SMA100",
                "REBALANCE_PERCENTILE_BELOW_60_OR_NOT_RANKED",
                "MAXIMUM_126_HELD_SESSIONS",
                "UNEXPLAINED_MISSING_ACTIVE_BAR",
            ],
            "sameBarRule": "STOP_FIRST_AFTER_ENTRY",
            "dailyExitEvaluation": (
                "HARD_OR_TRAILING_STOP_INTRADAY_EVERY_SESSION; MARKET_SMA200_AND_"
                "SECURITY_SMA100_AFTER_EVERY_COMPLETED_CLOSE_FOR_NEXT_OPEN"
            ),
            "rankExitEvaluation": "ONLY_ON_EVERY_FIFTH_SESSION_REBALANCE",
            "holdingCount": (
                "ENTRY_SESSION_IS_HELD_SESSION_1; EXIT_AT_NEXT_OPEN_AFTER_SESSION_126_CLOSE"
            ),
            "sameSecurityReentry": "PROHIBITED_ON_THE_SAME_SESSION_AS_ANY_EXIT",
        },
        "portfolio": {
            "initialCashUsd": "100000",
            "maximumPositions": MAX_POSITIONS,
            "riskFractionPerPosition": "0.005",
            "notionalFractionCapPerPosition": "0.10",
            "wholeSharesOnly": True,
            "selectionPriority": ["COMPOSITE_SCORE_DESC", "SECURITY_ID_ASC"],
            "shareSizing": (
                "DECREMENT_FROM_FLOOR_MIN_OF_NAV_RISK_OVER_FILL_MINUS_STOP_"
                "NAV_NOTIONAL_OVER_FILL_AND_AVAILABLE_CASH_OVER_FILL_UNTIL_"
                "LOSS_TO_STOP_PLUS_ENTRY_COST_PLUS_STOP_EXIT_RESERVE_FITS_RISK_"
                "AND_FILL_NOTIONAL_PLUS_BOTH_COSTS_FIT_CASH"
            ),
            "riskNav": "PRIOR_COMPLETED_CLOSE_PORTFOLIO_NAV",
            "exitReserve": (
                "WORST_CASE_C9_51_BPS_SIDE_COST_AT_INITIAL_STOP_NOTIONAL_USING_"
                "ENTRY_SESSION_PREOPEN_ADTV"
            ),
        },
        "cost": {
            "version": "C9-NONLINEAR-COST-v1.0.0",
            "perSide": (
                "participation=notional/ADTV; impact=min(50bps,25bps*sqrt(participation)); "
                "sideBps=1+impact"
            ),
            "entryAndExitChargedSeparately": True,
        },
        "benchmarks": {
            "primary": "SPY_BUY_AND_HOLD_SAME_CALENDAR_AND_COST_POLICY",
            "cash": "ZERO_RETURN",
            "equalWeight": "NOT_OBSERVED",
            "sector": "NOT_OBSERVED",
        },
        "crossSection": {
            "completeExpectedDenominatorRequired": True,
            "terminalSignalRequiredForEveryExpectedSecurity": True,
            "contentHashBindsOrderedDenominatorAndEveryRawSignal": True,
            "scheduleAnchor": "FIRST_SESSION_AFTER_EXACT_253_SESSION_HISTORY_IS_ORDINAL_ZERO",
        },
        "governance": {
            "initialModelEvidenceLabel": MODEL_EVIDENCE_LABEL,
            "automaticBrokerageExecution": False,
            "llmSignalOrWeightAuthority": False,
            "productionPersistenceBeforeValidation": False,
            "futureReturnsGuaranteed": False,
        },
    }
    body["contentHash"] = canonical_hash(body)
    return body


def validate_v11_contract(value: dict[str, Any]) -> None:
    if value != frozen_v11_contract():
        raise QuantTradingV11Violation("Quant Trading v1.1 contract drift")


def calculate_raw_signal_v11(
    *,
    security_id: str,
    security: tuple[TrendBarV11, ...],
    market: tuple[TrendBarV11, ...],
) -> RawSignalV11:
    _atom(security_id, "security_id")
    if type(security) is not tuple or type(market) is not tuple:
        raise QuantTradingV11Violation("signal histories must be tuples")
    if any(type(item) is not TrendBarV11 for item in (*security, *market)):
        raise QuantTradingV11Violation("signal histories contain invalid bars")
    if len(security) != REQUIRED_HISTORY or len(market) != REQUIRED_HISTORY:
        return _noneligible_signal(
            security_id, security, market, SignalState.MISSING, ("ALIGNED_HISTORY_INCOMPLETE",)
        )
    security_dates = tuple(item.session_date for item in security)
    market_dates = tuple(item.session_date for item in market)
    if (
        security_dates != market_dates
        or security_dates != tuple(sorted(set(security_dates)))
    ):
        return _noneligible_signal(
            security_id, security, market, SignalState.INVALID, ("ALIGNED_HISTORY_INVALID",)
        )
    try:
        features = _features(security, market)
    except (ArithmeticError, DecimalException, QuantTradingV11Violation):
        return _noneligible_signal(
            security_id, security, market, SignalState.INVALID, ("FEATURE_CALCULATION_INVALID",)
        )
    close = security[-1].close_price
    market_close = market[-1].close_price
    checks = (
        (close >= Decimal("5"), "PRICE_BELOW_MINIMUM"),
        (features.median_adtv20 >= Decimal("5000000"), "LIQUIDITY_BELOW_MINIMUM"),
        (close > features.sma200, "SECURITY_TREND_NOT_READY"),
        (market_close > features.market_sma200, "MARKET_REGIME_NOT_READY"),
        (features.momentum252_skip20 > 0, "MOMENTUM_252_NOT_POSITIVE"),
        (features.momentum126_skip20 > 0, "MOMENTUM_126_NOT_POSITIVE"),
        (features.atr_percent <= Decimal("0.10"), "ATR_PERCENT_TOO_HIGH"),
    )
    reasons = tuple(reason for passed, reason in checks if not passed)
    input_hash = _signal_hash(security_id, security, market)
    if reasons:
        return _raw_signal(
            security_id,
            security[-1].session_date,
            SignalState.INELIGIBLE,
            reasons,
            None,
            None,
            input_hash,
        )
    return _raw_signal(
        security_id,
        security[-1].session_date,
        SignalState.ELIGIBLE,
        (),
        features,
        close,
        input_hash,
    )


def rank_cross_section_v11(value: CrossSectionInputV11) -> tuple[RankedSignalV11, ...]:
    if type(value) is not CrossSectionInputV11:
        raise QuantTradingV11Violation("cross section input type is invalid")
    signals = tuple(
        calculate_raw_signal_v11(
            security_id=item.security_id,
            security=item.security,
            market=value.market,
        )
        for item in value.members
    )
    if len({item.decision_date for item in signals}) != 1:
        raise QuantTradingV11Violation("cross section mixes decision dates")
    cross_section_hash = "sha256:" + canonical_hash(
        {
            "modelVersion": MODEL_VERSION,
            "strategyVersion": STRATEGY_VERSION,
            "rebalanceOrdinal": value.rebalance_ordinal,
            "expectedSecurityIds": list(value.expected_security_ids),
            "rawSignals": [[item.security_id, item.content_hash] for item in signals],
        }
    ).lower()
    eligible = tuple(item for item in signals if item.state is SignalState.ELIGIBLE)
    if len(eligible) < MINIMUM_CROSS_SECTION:
        return tuple(_not_ranked(item, len(eligible), cross_section_hash) for item in signals)
    count = len(eligible)
    scored: list[tuple[RawSignalV11, Decimal, Decimal, Decimal]] = []
    with localcontext() as context:
        context.prec = 50
        context.rounding = ROUND_HALF_EVEN
        for item in eligible:
            p252 = _shared_value_percentile(eligible, item, "momentum252_skip20")
            p126 = _shared_value_percentile(eligible, item, "momentum126_skip20")
            score = Decimal("0.60") * p252 + Decimal("0.40") * p126
            scored.append((item, p252, p126, score))
    ordered = sorted(scored, key=lambda row: (-row[3], row[0].security_id))
    overall = {row[0].security_id: index for index, row in enumerate(ordered, 1)}
    by_id = {row[0].security_id: row for row in scored}
    result = []
    for item in signals:
        if item.security_id not in by_id:
            result.append(_not_ranked(item, count, cross_section_hash))
            continue
        _, p252, p126, score = by_id[item.security_id]
        rank = overall[item.security_id]
        if rank <= MAX_POSITIONS and score >= ENTRY_PERCENTILE:
            state = RankedState.ENTRY_ELIGIBLE
        elif score >= RETENTION_PERCENTILE:
            state = RankedState.HOLD_ELIGIBLE
        else:
            state = RankedState.EXIT_ELIGIBLE
        body = _rank_body(
            item, cross_section_hash, state, rank, count, p252, p126, score
        )
        result.append(
            RankedSignalV11(
                item.security_id,
                item.decision_date,
                item.input_hash,
                cross_section_hash,
                state,
                rank,
                count,
                p252,
                p126,
                score,
                "sha256:" + canonical_hash(body).lower(),
            )
        )
    return tuple(result)


def build_entry_plan_v11(signal: RawSignalV11) -> EntryPlanV11:
    if type(signal) is not RawSignalV11 or signal.state is not SignalState.ELIGIBLE:
        raise QuantTradingV11Violation("entry plan requires an eligible raw signal")
    assert signal.features is not None
    assert signal.signal_close is not None
    return entry_plan_from_prices_v11(
        signal_close=signal.signal_close, atr14=signal.features.atr14
    )


def entry_plan_from_prices_v11(*, signal_close: Decimal, atr14: Decimal) -> EntryPlanV11:
    close = _positive(signal_close, "signal_close")
    atr = _positive(atr14, "atr14")
    with localcontext() as context:
        context.prec = 50
        context.rounding = ROUND_HALF_EVEN
        distance = max(Decimal("3") * atr, Decimal("0.02") * close)
        stop = max(close - distance, Decimal("0.90") * close)
        maximum = close + Decimal("2") * atr
    return EntryPlanV11(close, stop, maximum, atr)


def next_trailing_stop_v11(
    *, active_stop: Decimal, highest_close: Decimal, atr14: Decimal
) -> Decimal:
    stop = _positive(active_stop, "active_stop")
    highest = _positive(highest_close, "highest_close")
    atr = _positive(atr14, "atr14")
    with localcontext() as context:
        context.prec = 50
        context.rounding = ROUND_HALF_EVEN
        return max(stop, highest - Decimal("3") * atr)


def _features(
    security: tuple[TrendBarV11, ...], market: tuple[TrendBarV11, ...]
) -> TrendFeaturesV11:
    closes = tuple(item.close_price for item in security)
    market_closes = tuple(item.close_price for item in market)
    t = REQUIRED_HISTORY - 1
    with localcontext() as context:
        context.prec = 50
        context.rounding = ROUND_HALF_EVEN
        ranges = tuple(
            max(
                security[index].high_price - security[index].low_price,
                abs(security[index].high_price - security[index - 1].close_price),
                abs(security[index].low_price - security[index - 1].close_price),
            )
            for index in range(t - 13, t + 1)
        )
        atr = sum(ranges, Decimal("0")) / Decimal("14")
        sma100 = sum(closes[-100:], Decimal("0")) / Decimal("100")
        sma200 = sum(closes[-200:], Decimal("0")) / Decimal("200")
        market_sma200 = sum(market_closes[-200:], Decimal("0")) / Decimal("200")
        m252 = closes[t - 20] / closes[t - 252] - Decimal("1")
        m126 = closes[t - 20] / closes[t - 126] - Decimal("1")
        market252 = market_closes[t - 20] / market_closes[t - 252] - Decimal("1")
        market126 = market_closes[t - 20] / market_closes[t - 126] - Decimal("1")
        adtv = _median(tuple(item.close_price * Decimal(item.volume) for item in security[-20:]))
        atr_percent = atr / closes[-1]
    values = (
        atr,
        sma100,
        sma200,
        market_sma200,
        m252,
        m126,
        market252,
        market126,
        adtv,
        atr_percent,
    )
    if any(not item.is_finite() or abs(item) > MAX_ABSOLUTE_DECIMAL for item in values) or atr <= 0:
        raise QuantTradingV11Violation("calculated feature is outside its domain")
    return TrendFeaturesV11(
        atr,
        sma100,
        sma200,
        market_sma200,
        m252,
        m126,
        market252,
        market126,
        m252 - market252,
        m126 - market126,
        adtv,
        atr_percent,
    )


def _noneligible_signal(
    security_id: str,
    security: tuple[TrendBarV11, ...],
    market: tuple[TrendBarV11, ...],
    state: SignalState,
    reasons: tuple[str, ...],
) -> RawSignalV11:
    decision = (
        security[-1].session_date
        if security
        else (market[-1].session_date if market else date.min)
    )
    return _raw_signal(
        security_id,
        decision,
        state,
        reasons,
        None,
        None,
        _signal_hash(security_id, security, market),
    )


def _raw_signal(
    security_id: str,
    decision_date: date,
    state: SignalState,
    reasons: tuple[str, ...],
    features: TrendFeaturesV11 | None,
    signal_close: Decimal | None,
    input_hash: str,
) -> RawSignalV11:
    draft = {
        "modelVersion": MODEL_VERSION,
        "strategyVersion": STRATEGY_VERSION,
        "securityId": security_id,
        "decisionDate": decision_date.isoformat(),
        "state": state.value,
        "reasons": list(reasons),
        "features": None if features is None else _features_primitive(features),
        "signalClose": None if signal_close is None else _decimal_text(signal_close),
        "inputHash": input_hash,
    }
    return RawSignalV11(
        security_id,
        decision_date,
        state,
        reasons,
        features,
        signal_close,
        input_hash,
        "sha256:" + canonical_hash(draft).lower(),
    )


def _signal_hash(
    security_id: str,
    security: tuple[TrendBarV11, ...],
    market: tuple[TrendBarV11, ...],
) -> str:
    body = {
        "modelVersion": MODEL_VERSION,
        "strategyVersion": STRATEGY_VERSION,
        "formulaVersion": FORMULA_VERSION,
        "securityId": security_id,
        "security": [_bar_primitive(item) for item in security],
        "market": [_bar_primitive(item) for item in market],
    }
    return "sha256:" + canonical_hash(body).lower()


def _bar_primitive(value: TrendBarV11) -> list[object]:
    return [
        value.session_date.isoformat(),
        _decimal_text(value.open_price),
        _decimal_text(value.high_price),
        _decimal_text(value.low_price),
        _decimal_text(value.close_price),
        value.volume,
    ]


def _shared_value_percentile(
    values: tuple[RawSignalV11, ...], current: RawSignalV11, attribute: str
) -> Decimal:
    assert current.features is not None
    current_value = getattr(current.features, attribute)
    observed = tuple(getattr(item.features, attribute) for item in values)
    lower = sum(item < current_value for item in observed)
    equal = sum(item == current_value for item in observed)
    return (
        Decimal("100")
        * (Decimal(lower) + Decimal("0.5") * Decimal(equal - 1))
        / Decimal(len(values) - 1)
    )


def _rank_body(
    item: RawSignalV11,
    cross_section_hash: str,
    state: RankedState,
    rank: int | None,
    count: int,
    p252: Decimal | None,
    p126: Decimal | None,
    score: Decimal | None,
) -> dict[str, object]:
    return {
        "modelVersion": MODEL_VERSION,
        "strategyVersion": STRATEGY_VERSION,
        "securityId": item.security_id,
        "decisionDate": item.decision_date.isoformat(),
        "rawInputHash": item.input_hash,
        "crossSectionHash": cross_section_hash,
        "state": state.value,
        "rank": rank,
        "crossSectionCount": count,
        "momentum252Percentile": None if p252 is None else _decimal_text(p252),
        "momentum126Percentile": None if p126 is None else _decimal_text(p126),
        "compositeScore": None if score is None else _decimal_text(score),
    }


def _not_ranked(
    item: RawSignalV11, count: int, cross_section_hash: str
) -> RankedSignalV11:
    body = _rank_body(
        item, cross_section_hash, RankedState.NOT_RANKED, None, count, None, None, None
    )
    return RankedSignalV11(
        item.security_id,
        item.decision_date,
        item.input_hash,
        cross_section_hash,
        RankedState.NOT_RANKED,
        None,
        count,
        None,
        None,
        None,
        "sha256:" + canonical_hash(body).lower(),
    )


def _ranked_body(value: RankedSignalV11) -> dict[str, object]:
    return {
        "modelVersion": MODEL_VERSION,
        "strategyVersion": STRATEGY_VERSION,
        "securityId": value.security_id,
        "decisionDate": value.decision_date.isoformat(),
        "rawInputHash": value.raw_input_hash,
        "crossSectionHash": value.cross_section_hash,
        "state": value.state.value,
        "rank": value.rank,
        "crossSectionCount": value.cross_section_count,
        "momentum252Percentile": (
            None
            if value.momentum252_percentile is None
            else _decimal_text(value.momentum252_percentile)
        ),
        "momentum126Percentile": (
            None
            if value.momentum126_percentile is None
            else _decimal_text(value.momentum126_percentile)
        ),
        "compositeScore": (
            None if value.composite_score is None else _decimal_text(value.composite_score)
        ),
    }


def _raw_signal_body(value: RawSignalV11) -> dict[str, object]:
    return {
        "modelVersion": MODEL_VERSION,
        "strategyVersion": STRATEGY_VERSION,
        "securityId": value.security_id,
        "decisionDate": value.decision_date.isoformat(),
        "state": value.state.value,
        "reasons": list(value.reasons),
        "features": None if value.features is None else _features_primitive(value.features),
        "signalClose": (
            None if value.signal_close is None else _decimal_text(value.signal_close)
        ),
        "inputHash": value.input_hash,
    }


def _features_primitive(value: TrendFeaturesV11) -> dict[str, str]:
    return {
        field_name: _decimal_text(getattr(value, field_name))
        for field_name in value.__dataclass_fields__
    }


def canonical_hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest().upper()


def _decimal(value: object, name: str) -> Decimal:
    if type(value) is not Decimal or not value.is_finite() or abs(value) > MAX_ABSOLUTE_DECIMAL:
        raise QuantTradingV11Violation(f"{name} must be a finite bounded Decimal")
    return value


def _positive(value: object, name: str) -> Decimal:
    result = _decimal(value, name)
    if result <= 0:
        raise QuantTradingV11Violation(f"{name} must be positive")
    return result


def _decimal_text(value: Decimal) -> str:
    numeric = _decimal(value, "decimal")
    if numeric == 0:
        return "0"
    text = format(numeric, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _median(values: tuple[Decimal, ...]) -> Decimal:
    ordered = sorted(values)
    midpoint = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[midpoint]
    return (ordered[midpoint - 1] + ordered[midpoint]) / Decimal("2")


def _atom(value: object, name: str) -> str:
    if type(value) is not str or not value or value != value.strip() or "|" in value:
        raise QuantTradingV11Violation(f"{name} must be a nonblank canonical atom")
    return value


def _hash(value: object, name: str) -> str:
    if (
        type(value) is not str
        or not value.startswith("sha256:")
        or len(value) != 71
        or any(item not in "0123456789abcdef" for item in value[7:])
    ):
        raise QuantTradingV11Violation(f"{name} must be a lowercase SHA-256 reference")
    return value
