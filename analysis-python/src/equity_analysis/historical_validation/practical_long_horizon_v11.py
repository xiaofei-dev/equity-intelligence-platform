from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_EVEN, Decimal
from enum import StrEnum
from statistics import median

from equity_analysis.research_rating.long_horizon_v11 import (
    CompanyModelV11,
    LongHorizonV11Assessment,
    LongHorizonV11Inputs,
    MetricEvidence,
    evaluate_long_horizon_v11,
)

PRACTICAL_LONG_HORIZON_VERSION = (
    "LONG-HORIZON-v1.1-PRACTICAL-TIER1-v1.0.0"
)
AVAILABILITY_POLICY_VERSION = (
    "STANDARDIZED-REPORTING-LAG-APPROXIMATION-v1.0.0"
)
EVIDENCE_MODE = "NON_PIT_PROVIDER_REVISION_RISK"
ANNUAL_REPORTING_LAG_DAYS = 90
QUARTERLY_REPORTING_LAG_DAYS = 45
MINIMUM_STABILITY_OBSERVATIONS = 3
MINIMUM_VALUATION_HISTORY_OBSERVATIONS = 12
MAXIMUM_MARKET_CAP_STALENESS_SESSIONS = 5
ROUND_TRIP_COST_BPS = Decimal("4")
_ONE = Decimal("1")
_ZERO = Decimal("0")
_RATE_QUANTUM = Decimal("0.000001")
_SCORE_QUANTUM = Decimal("0.01")


class PracticalTarget(StrEnum):
    BUSINESS_QUALITY = "BUSINESS_QUALITY"
    SECURITY_ATTRACTIVENESS = "SECURITY_ATTRACTIVENESS"
    EXPECTED_RETURN = "EXPECTED_RETURN"
    DOWNSIDE_RISK = "DOWNSIDE_RISK"


@dataclass(frozen=True)
class ProviderRecord:
    field: str
    value: Decimal
    period_end: date
    period_type: str
    available_at: date
    source_hash: str

    def practical_available_on(self) -> date:
        lag = (
            ANNUAL_REPORTING_LAG_DAYS
            if self.period_type == "ANNUAL"
            else QUARTERLY_REPORTING_LAG_DAYS
        )
        return self.period_end + timedelta(days=lag)


@dataclass(frozen=True)
class MarketObservation:
    trading_date: date
    market_capitalization: Decimal
    source_hash: str


@dataclass(frozen=True)
class PriceObservation:
    trading_date: date
    adjusted_close: Decimal


@dataclass(frozen=True)
class PracticalSecurityHistory:
    security_id: str
    symbol: str
    records: tuple[ProviderRecord, ...]
    market_cap_history: tuple[MarketObservation, ...]
    prices: tuple[PriceObservation, ...]


@dataclass(frozen=True)
class PracticalDecision:
    symbol: str
    decision_date: date
    assessment: LongHorizonV11Assessment
    strict_available_record_count: int
    practical_available_record_count: int
    input_source_hashes: tuple[str, ...]
    input_period_ends: tuple[date, ...]
    limitations: tuple[str, ...]

    def target_score(self, target: PracticalTarget) -> Decimal | None:
        if target == PracticalTarget.BUSINESS_QUALITY:
            return self.assessment.business_quality.score
        if target == PracticalTarget.SECURITY_ATTRACTIVENESS:
            return self.assessment.valuation_entry.score
        if target == PracticalTarget.EXPECTED_RETURN:
            return self.assessment.expected_return.base
        if target == PracticalTarget.DOWNSIDE_RISK:
            return self.assessment.downside_risk.score
        raise AssertionError(f"Unsupported target: {target}")


@dataclass(frozen=True)
class RankedOutcome:
    target: PracticalTarget
    symbol: str
    decision_date: date
    horizon_sessions: int
    score: Decimal
    rank: int
    population: int
    entry_date: date
    exit_date: date
    security_net_return: Decimal
    spy_net_return: Decimal
    excess_return: Decimal
    maximum_drawdown: Decimal
    cumulative_path_returns: tuple[Decimal, ...]


@dataclass(frozen=True)
class SliceMetric:
    target: PracticalTarget
    decision_date: date
    horizon_sessions: int
    scored_count: int
    outcome_count: int
    coverage: Decimal
    rank_information_coefficient: Decimal | None
    top_mean_excess_return: Decimal | None
    top_hit_rate: Decimal | None
    top_mean_maximum_drawdown: Decimal | None
    top_minus_bottom_spread: Decimal | None


@dataclass(frozen=True)
class AggregateMetric:
    target: PracticalTarget
    horizon_sessions: int
    slice_count: int
    outcome_count: int
    median_rank_information_coefficient: Decimal | None
    mean_top_excess_return: Decimal | None
    mean_top_hit_rate: Decimal | None
    mean_top_maximum_drawdown: Decimal | None
    mean_top_minus_bottom_spread: Decimal | None
    top_excess_volatility: Decimal | None
    diagnostic_information_ratio: Decimal | None


def _valid(value: Decimal | None) -> MetricEvidence:
    if value is None or not value.is_finite():
        return MetricEvidence.missing()
    return MetricEvidence.valid(value)


def _mean(values: list[Decimal]) -> Decimal:
    return sum(values, _ZERO) / Decimal(len(values))


def _population_std(values: list[Decimal]) -> Decimal:
    if len(values) < 2:
        return _ZERO
    center = _mean(values)
    variance = _mean([(item - center) ** 2 for item in values])
    return variance.sqrt()


def _stability(values: list[Decimal]) -> Decimal | None:
    if len(values) < MINIMUM_STABILITY_OBSERVATIONS:
        return None
    center = abs(_mean(values))
    scale = max(center, Decimal("0.000001"))
    return max(_ZERO, min(_ONE, _ONE - _population_std(values) / scale))


def _records_by_field(
    history: PracticalSecurityHistory,
    decision_date: date,
) -> dict[str, list[ProviderRecord]]:
    grouped: dict[str, list[ProviderRecord]] = {}
    for item in history.records:
        if item.practical_available_on() > decision_date:
            continue
        grouped.setdefault(item.field, []).append(item)
    for values in grouped.values():
        values.sort(key=lambda item: item.period_end)
    return grouped


def _annual_series(
    grouped: dict[str, list[ProviderRecord]],
    field: str,
) -> list[ProviderRecord]:
    return [
        item for item in grouped.get(field, ()) if item.period_type == "ANNUAL"
    ]


def _latest_common_period(
    grouped: dict[str, list[ProviderRecord]],
    fields: tuple[str, ...],
) -> dict[str, ProviderRecord] | None:
    by_field = {
        field: {item.period_end: item for item in _annual_series(grouped, field)}
        for field in fields
    }
    common = set.intersection(
        *(set(values) for values in by_field.values())
    )
    if not common:
        return None
    selected_period = max(common)
    return {field: values[selected_period] for field, values in by_field.items()}


def _market_cap_at(
    history: PracticalSecurityHistory,
    decision_date: date,
) -> MarketObservation | None:
    eligible = [
        item
        for item in history.market_cap_history
        if item.trading_date <= decision_date
    ]
    if not eligible:
        return None
    selected = max(eligible, key=lambda item: item.trading_date)
    completed_sessions = sum(
        selected.trading_date < item.trading_date <= decision_date
        for item in history.prices
    )
    if completed_sessions > MAXIMUM_MARKET_CAP_STALENESS_SESSIONS:
        return None
    return selected


def _historical_fcf_yield_percentile(
    history: PracticalSecurityHistory,
    grouped: dict[str, list[ProviderRecord]],
    decision_date: date,
    current_fcf_yield: Decimal,
) -> tuple[Decimal | None, tuple[str, ...]]:
    ocf = _annual_series(grouped, "operating_cash_flow")
    capex = _annual_series(grouped, "capital_expenditure")
    by_period_ocf = {item.period_end: item for item in ocf}
    by_period_capex = {item.period_end: item for item in capex}
    common = sorted(set(by_period_ocf) & set(by_period_capex))
    month_end_market: dict[tuple[int, int], MarketObservation] = {}
    for market in history.market_cap_history:
        if market.trading_date > decision_date:
            continue
        month = (market.trading_date.year, market.trading_date.month)
        if (
            month not in month_end_market
            or market.trading_date > month_end_market[month].trading_date
        ):
            month_end_market[month] = market
    observations: list[Decimal] = []
    hashes: list[str] = []
    for market in sorted(
        month_end_market.values(),
        key=lambda item: item.trading_date,
    ):
        if market.market_capitalization <= 0:
            continue
        available_periods = [
            period
            for period in common
            if period + timedelta(days=ANNUAL_REPORTING_LAG_DAYS)
            <= market.trading_date
        ]
        if not available_periods:
            continue
        period = max(available_periods)
        fcf = by_period_ocf[period].value - abs(by_period_capex[period].value)
        observations.append(fcf / market.market_capitalization)
        hashes.extend(
            (
                market.source_hash,
                by_period_ocf[period].source_hash,
                by_period_capex[period].source_hash,
            )
        )
    if len(observations) < MINIMUM_VALUATION_HISTORY_OBSERVATIONS:
        return None, tuple(sorted(set(hashes)))
    not_greater = sum(item <= current_fcf_yield for item in observations)
    return (
        Decimal(not_greater) / Decimal(len(observations)),
        tuple(sorted(set(hashes))),
    )


def build_practical_decision(
    history: PracticalSecurityHistory,
    decision_date: date,
) -> PracticalDecision:
    grouped = _records_by_field(history, decision_date)
    source_hashes: set[str] = set()
    strict_available_count = sum(
        item.available_at <= decision_date for item in history.records
    )
    practical_available_count = sum(
        item.practical_available_on() <= decision_date
        for item in history.records
    )

    roic_common = _latest_common_period(
        grouped,
        (
            "operating_income",
            "stockholders_equity",
            "total_debt",
            "cash_and_equivalents",
            "income_tax",
            "pretax_income",
        ),
    )
    roic = None
    if roic_common:
        source_hashes.update(item.source_hash for item in roic_common.values())
        operating_income = roic_common["operating_income"].value
        pretax_income = roic_common["pretax_income"].value
        tax_rate = (
            max(
                _ZERO,
                min(
                    Decimal("0.50"),
                    roic_common["income_tax"].value / pretax_income,
                ),
            )
            if pretax_income > 0
            else None
        )
        invested_capital = (
            roic_common["stockholders_equity"].value
            + roic_common["total_debt"].value
            - roic_common["cash_and_equivalents"].value
        )
        if invested_capital > 0 and tax_rate is not None:
            roic = operating_income * (_ONE - tax_rate) / invested_capital

    margin_common = _latest_common_period(
        grouped,
        ("revenue", "operating_income"),
    )
    operating_margin = None
    if margin_common:
        source_hashes.update(item.source_hash for item in margin_common.values())
        revenue = margin_common["revenue"].value
        if revenue != 0:
            operating_margin = margin_common["operating_income"].value / revenue

    fcf_common = _latest_common_period(
        grouped,
        ("revenue", "operating_cash_flow", "capital_expenditure"),
    )
    fcf_margin = None
    if fcf_common:
        source_hashes.update(item.source_hash for item in fcf_common.values())
        revenue = fcf_common["revenue"].value
        if revenue != 0:
            fcf_margin = (
                fcf_common["operating_cash_flow"].value
                - abs(fcf_common["capital_expenditure"].value)
            ) / revenue

    leverage_common = _latest_common_period(
        grouped,
        ("total_debt", "cash_and_equivalents", "ebitda"),
    )
    net_debt_to_ebitda = None
    if leverage_common:
        source_hashes.update(item.source_hash for item in leverage_common.values())
        if leverage_common["ebitda"].value != 0:
            net_debt_to_ebitda = (
                leverage_common["total_debt"].value
                - leverage_common["cash_and_equivalents"].value
            ) / leverage_common["ebitda"].value

    earnings = [
        item.value for item in _annual_series(grouped, "net_income")
    ][-3:]
    cash_flows = [
        item.value
        for item in _annual_series(grouped, "operating_cash_flow")
    ][-3:]

    market = _market_cap_at(history, decision_date)
    fcf_yield = earnings_yield = ev_to_ebitda = history_percentile = None
    valuation_common = _latest_common_period(
        grouped,
        (
            "operating_cash_flow",
            "capital_expenditure",
            "net_income",
            "total_debt",
            "cash_and_equivalents",
            "ebitda",
        ),
    )
    if valuation_common and market and market.market_capitalization > 0:
        source_hashes.update(item.source_hash for item in valuation_common.values())
        source_hashes.add(market.source_hash)
        fcf = valuation_common["operating_cash_flow"].value - abs(
            valuation_common["capital_expenditure"].value
        )
        fcf_yield = fcf / market.market_capitalization
        earnings_yield = (
            valuation_common["net_income"].value
            / market.market_capitalization
        )
        enterprise_value = (
            market.market_capitalization
            + valuation_common["total_debt"].value
            - valuation_common["cash_and_equivalents"].value
        )
        if valuation_common["ebitda"].value != 0:
            ev_to_ebitda = enterprise_value / valuation_common["ebitda"].value
        history_percentile, history_hashes = _historical_fcf_yield_percentile(
            history,
            grouped,
            decision_date,
            fcf_yield,
        )
        source_hashes.update(history_hashes)

    inputs = LongHorizonV11Inputs(
        symbol=history.symbol,
        company_model=CompanyModelV11.GENERAL,
        return_on_invested_capital=_valid(roic),
        operating_margin=_valid(operating_margin),
        free_cash_flow_margin=_valid(fcf_margin),
        earnings_stability=_valid(_stability(earnings)),
        cash_flow_stability=_valid(_stability(cash_flows)),
        net_debt_to_ebitda=_valid(net_debt_to_ebitda),
        free_cash_flow_yield=_valid(fcf_yield),
        earnings_yield=_valid(earnings_yield),
        enterprise_value_to_ebitda=_valid(ev_to_ebitda),
        own_history_valuation_attractiveness=_valid(history_percentile),
    )
    return PracticalDecision(
        symbol=history.symbol,
        decision_date=decision_date,
        assessment=evaluate_long_horizon_v11(inputs),
        strict_available_record_count=strict_available_count,
        practical_available_record_count=practical_available_count,
        input_source_hashes=tuple(sorted(source_hashes)),
        input_period_ends=tuple(
            sorted(
                {
                    item.period_end
                    for item in history.records
                    if (
                        item.practical_available_on() <= decision_date
                        and item.period_type == "ANNUAL"
                    )
                }
            )
        ),
        limitations=(
            EVIDENCE_MODE,
            "Provider history is the latest downloaded revision, not an as-of archive.",
            "Annual facts use a standardized 90-day reporting-lag approximation.",
            "At least three annual observations are required for Tier-1 stability.",
            "Current-universe retrospective membership creates survivorship bias.",
            "Long Horizon v1.1 formulas and weights are unchanged.",
            "No default aggregate ranking is created.",
        ),
    )


def _net_return(entry: Decimal, exit_value: Decimal) -> Decimal:
    gross = exit_value / entry - _ONE
    cost = ROUND_TRIP_COST_BPS / Decimal("10000")
    return (_ONE + gross) * (_ONE - cost) - _ONE


def _maximum_drawdown(values: list[Decimal]) -> Decimal:
    peak = values[0]
    drawdown = _ZERO
    for value in values:
        peak = max(peak, value)
        drawdown = min(drawdown, value / peak - _ONE)
    return drawdown


def _ranks(values: list[Decimal]) -> list[Decimal]:
    ordered = sorted(enumerate(values), key=lambda item: item[1])
    result = [_ZERO for _ in values]
    index = 0
    while index < len(ordered):
        end = index
        while end + 1 < len(ordered) and ordered[end + 1][1] == ordered[index][1]:
            end += 1
        average_rank = Decimal(index + end + 2) / Decimal("2")
        for position in range(index, end + 1):
            result[ordered[position][0]] = average_rank
        index = end + 1
    return result


def _correlation(left: list[Decimal], right: list[Decimal]) -> Decimal | None:
    if len(left) < 3 or len(left) != len(right):
        return None
    left_mean = _mean(left)
    right_mean = _mean(right)
    numerator = sum(
        (
            (left_item - left_mean) * (right_item - right_mean)
            for left_item, right_item in zip(left, right, strict=True)
        ),
        _ZERO,
    )
    left_sum = sum(((item - left_mean) ** 2 for item in left), _ZERO)
    right_sum = sum(((item - right_mean) ** 2 for item in right), _ZERO)
    if left_sum == 0 or right_sum == 0:
        return None
    return numerator / (left_sum * right_sum).sqrt()


def _spearman(scores: list[Decimal], outcomes: list[Decimal]) -> Decimal | None:
    return _correlation(_ranks(scores), _ranks(outcomes))


def evaluate_slice(
    *,
    decisions: tuple[PracticalDecision, ...],
    histories: dict[str, PracticalSecurityHistory],
    spy_prices: tuple[PriceObservation, ...],
    target: PracticalTarget,
    horizon_sessions: int,
) -> tuple[SliceMetric, tuple[RankedOutcome, ...]]:
    if not decisions:
        raise ValueError("At least one decision is required")
    decision_date = decisions[0].decision_date
    if any(item.decision_date != decision_date for item in decisions):
        raise ValueError("Slice decisions must use one decision date")
    scored = [
        (item, item.target_score(target))
        for item in decisions
        if item.target_score(target) is not None
    ]
    scored.sort(
        key=lambda item: (
            (
                item[1]
                if target == PracticalTarget.DOWNSIDE_RISK
                else -item[1]
            ),
            item[0].symbol,
        )
    )
    spy_by_date = {item.trading_date: item for item in spy_prices}
    spy_dates = sorted(spy_by_date)
    eligible_spy_dates = [item for item in spy_dates if item > decision_date]
    if len(eligible_spy_dates) < horizon_sessions:
        return (
            SliceMetric(
                target=target,
                decision_date=decision_date,
                horizon_sessions=horizon_sessions,
                scored_count=len(scored),
                outcome_count=0,
                coverage=_ZERO,
                rank_information_coefficient=None,
                top_mean_excess_return=None,
                top_hit_rate=None,
                top_mean_maximum_drawdown=None,
                top_minus_bottom_spread=None,
            ),
            (),
        )
    path_dates = eligible_spy_dates[:horizon_sessions]
    entry_date = path_dates[0]
    exit_date = path_dates[-1]
    spy_return = _net_return(
        spy_by_date[entry_date].adjusted_close,
        spy_by_date[exit_date].adjusted_close,
    )
    outcomes: list[RankedOutcome] = []
    for rank, (decision, raw_score) in enumerate(scored, start=1):
        assert raw_score is not None
        prices = {item.trading_date: item for item in histories[decision.symbol].prices}
        if entry_date not in prices or exit_date not in prices:
            continue
        path = [
            prices[item].adjusted_close for item in path_dates if item in prices
        ]
        if len(path) != len(path_dates):
            continue
        security_return = _net_return(
            prices[entry_date].adjusted_close,
            prices[exit_date].adjusted_close,
        )
        entry_value = prices[entry_date].adjusted_close
        cumulative_path = tuple(
            prices[item].adjusted_close / entry_value - _ONE
            for item in path_dates
        )
        outcomes.append(
            RankedOutcome(
                target=target,
                symbol=decision.symbol,
                decision_date=decision_date,
                horizon_sessions=horizon_sessions,
                score=raw_score,
                rank=rank,
                population=len(scored),
                entry_date=entry_date,
                exit_date=exit_date,
                security_net_return=security_return,
                spy_net_return=spy_return,
                excess_return=security_return - spy_return,
                maximum_drawdown=_maximum_drawdown(path),
                cumulative_path_returns=cumulative_path,
            )
        )
    if not outcomes:
        coverage = _ZERO
    else:
        coverage = Decimal(len(outcomes)) / Decimal(max(1, len(scored)))
    top_count = max(1, math.ceil(len(outcomes) * 0.20)) if outcomes else 0
    top = outcomes[:top_count]
    bottom = outcomes[-top_count:] if outcomes else []
    scores = [item.score for item in outcomes]
    desirability_scores = (
        [-item for item in scores]
        if target == PracticalTarget.DOWNSIDE_RISK
        else scores
    )
    excess = [item.excess_return for item in outcomes]
    metric = SliceMetric(
        target=target,
        decision_date=decision_date,
        horizon_sessions=horizon_sessions,
        scored_count=len(scored),
        outcome_count=len(outcomes),
        coverage=coverage,
        rank_information_coefficient=_spearman(desirability_scores, excess),
        top_mean_excess_return=(
            _mean([item.excess_return for item in top]) if top else None
        ),
        top_hit_rate=(
            Decimal(sum(item.excess_return > 0 for item in top))
            / Decimal(len(top))
            if top
            else None
        ),
        top_mean_maximum_drawdown=(
            _mean([item.maximum_drawdown for item in top]) if top else None
        ),
        top_minus_bottom_spread=(
            _mean([item.excess_return for item in top])
            - _mean([item.excess_return for item in bottom])
            if top and bottom
            else None
        ),
    )
    return metric, tuple(outcomes)


def aggregate_metrics(
    metrics: tuple[SliceMetric, ...],
    outcomes: tuple[RankedOutcome, ...],
) -> tuple[AggregateMetric, ...]:
    keys = sorted({(item.target, item.horizon_sessions) for item in metrics})
    aggregates: list[AggregateMetric] = []
    for target, horizon in keys:
        selected = [
            item
            for item in metrics
            if item.target == target and item.horizon_sessions == horizon
        ]
        target_outcomes = [
            item
            for item in outcomes
            if item.target == target and item.horizon_sessions == horizon
        ]
        rank_ics = [
            item.rank_information_coefficient
            for item in selected
            if item.rank_information_coefficient is not None
        ]
        top_excess = [
            item.top_mean_excess_return
            for item in selected
            if item.top_mean_excess_return is not None
        ]
        volatility = _population_std(top_excess) if len(top_excess) >= 2 else None
        mean_top = _mean(top_excess) if top_excess else None
        aggregates.append(
            AggregateMetric(
                target=target,
                horizon_sessions=horizon,
                slice_count=len(selected),
                outcome_count=len(target_outcomes),
                median_rank_information_coefficient=(
                    Decimal(str(median(rank_ics))) if rank_ics else None
                ),
                mean_top_excess_return=mean_top,
                mean_top_hit_rate=_optional_mean(
                    [item.top_hit_rate for item in selected]
                ),
                mean_top_maximum_drawdown=_optional_mean(
                    [item.top_mean_maximum_drawdown for item in selected]
                ),
                mean_top_minus_bottom_spread=_optional_mean(
                    [item.top_minus_bottom_spread for item in selected]
                ),
                top_excess_volatility=volatility,
                diagnostic_information_ratio=(
                    mean_top / volatility
                    if mean_top is not None and volatility not in {None, _ZERO}
                    else None
                ),
            )
        )
    return tuple(aggregates)


def _optional_mean(values: list[Decimal | None]) -> Decimal | None:
    available = [item for item in values if item is not None]
    return _mean(available) if available else None


def format_decimal(value: Decimal | None, *, score: bool = False) -> str | None:
    if value is None:
        return None
    quantum = _SCORE_QUANTUM if score else _RATE_QUANTUM
    return format(value.quantize(quantum, rounding=ROUND_HALF_EVEN), "f")
