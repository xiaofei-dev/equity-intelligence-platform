from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from enum import StrEnum

from equity_analysis.research_rating.long_horizon_v1 import (
    CompanyModel,
    LongHorizonAssessment,
    LongHorizonInputs,
    evaluate_long_horizon,
)

LONG_HORIZON_REPLAY_VERSION = "LONG-HORIZON-HISTORICAL-REPLAY-v1.0.0"
CONSERVATIVE_LAG_POLICY_VERSION = "ANNUAL-CURRENT-REVISION-LAG-v1.0.0"
DEFAULT_ANNUAL_AVAILABILITY_LAG_DAYS = 150
DEFAULT_EVIDENCE_CONFIDENCE = 0.75
OUTCOME_HORIZONS = (126, 252)
_HASH_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")


class AnnualMetric(StrEnum):
    REVENUE = "revenue"
    OPERATING_INCOME = "operating_income"
    NET_INCOME = "net_income"
    TOTAL_EQUITY = "total_equity"
    TOTAL_DEBT = "total_debt"
    DILUTED_EPS = "diluted_eps"
    ENTERPRISE_VALUE = "enterprise_value"
    EBITDA = "ebitda"
    SHARES_OUTSTANDING = "shares_outstanding"
    CASH_AND_EQUIVALENTS = "cash_and_equivalents"


class ReplayClaimBoundary(StrEnum):
    CURRENT_REVISION_RETROSPECTIVE_CONSERVATIVE_LAG = (
        "CURRENT_REVISION_RETROSPECTIVE/CONSERVATIVE_LAG"
    )


class ExcludedFactReason(StrEnum):
    FACT_PERIOD_AFTER_DECISION = "FACT_PERIOD_AFTER_DECISION"
    FACT_NOT_AVAILABLE_BY_CONSERVATIVE_LAG = (
        "FACT_NOT_AVAILABLE_BY_CONSERVATIVE_LAG"
    )


class OutcomeStatus(StrEnum):
    MATURED = "MATURED"
    NOT_MATURED = "NOT_MATURED"


@dataclass(frozen=True)
class AnnualFactRecord:
    metric: AnnualMetric
    value: Decimal
    period_end: date
    current_revision_evidence_hash: str

    def __post_init__(self) -> None:
        if not self.value.is_finite():
            raise ValueError("Annual fact values must be finite")
        _require_hash(
            self.current_revision_evidence_hash,
            "Annual fact current-revision evidence hash",
        )


@dataclass(frozen=True)
class AdjustedPriceObservation:
    trading_date: date
    adjusted_close: Decimal
    evidence_hash: str

    def __post_init__(self) -> None:
        if not self.adjusted_close.is_finite() or self.adjusted_close <= 0:
            raise ValueError("Adjusted close must be finite and positive")
        _require_hash(self.evidence_hash, "Adjusted price evidence hash")


@dataclass(frozen=True)
class SelectedAnnualFact:
    metric: AnnualMetric
    period_end: date
    conservative_available_date: date
    current_revision_evidence_hash: str


@dataclass(frozen=True)
class ExcludedAnnualFact:
    metric: AnnualMetric
    period_end: date
    conservative_available_date: date
    current_revision_evidence_hash: str
    reason: ExcludedFactReason


@dataclass(frozen=True)
class HistoricalOutcomeAttachment:
    horizon_trading_days: int
    status: OutcomeStatus
    entry_date: date
    exit_date: date | None
    adjusted_total_return: Decimal | None
    exit_price_evidence_hash: str | None


@dataclass(frozen=True)
class LongHorizonReplayResult:
    version: str
    security_id: str
    symbol: str
    decision_date: date
    claim_boundary: ReplayClaimBoundary
    availability_policy_version: str
    annual_availability_lag_days: int
    inputs: LongHorizonInputs
    assessment: LongHorizonAssessment
    selected_facts: tuple[SelectedAnnualFact, ...]
    excluded_facts: tuple[ExcludedAnnualFact, ...]
    outcomes: tuple[HistoricalOutcomeAttachment, ...]

    @property
    def score(self) -> float | None:
        return self.assessment.score

    @property
    def status(self) -> str:
        return self.assessment.status


def replay_long_horizon_decision(
    *,
    security_id: str,
    symbol: str,
    company_model: CompanyModel,
    decision_date: date,
    decision_adjusted_price: Decimal,
    decision_price_evidence_hash: str,
    annual_facts: tuple[AnnualFactRecord, ...],
    future_adjusted_prices: tuple[AdjustedPriceObservation, ...] = (),
    decision_valuation_price: Decimal | None = None,
    annual_availability_lag_days: int = DEFAULT_ANNUAL_AVAILABILITY_LAG_DAYS,
    evidence_confidence: float = DEFAULT_EVIDENCE_CONFIDENCE,
) -> LongHorizonReplayResult:
    """Approximately replay the frozen long-horizon model without PIT claims.

    Annual facts are current-revision records. The conservative lag determines
    which records may enter the decision-time input. Future prices are attached
    only after the frozen evaluator has run and can never affect its inputs.
    """
    if not security_id.strip() or not symbol.strip():
        raise ValueError("Security ID and symbol are required")
    if (
        not decision_adjusted_price.is_finite()
        or decision_adjusted_price <= 0
    ):
        raise ValueError("Decision adjusted price must be finite and positive")
    _require_hash(decision_price_evidence_hash, "Decision price evidence hash")
    valuation_price = decision_valuation_price or decision_adjusted_price
    if not valuation_price.is_finite() or valuation_price <= 0:
        raise ValueError("Decision valuation price must be finite and positive")
    if annual_availability_lag_days < 0:
        raise ValueError("Annual availability lag cannot be negative")
    if not 0 <= evidence_confidence <= 1:
        raise ValueError("Evidence confidence must be between zero and one")
    _validate_unique_facts(annual_facts)
    future_prices = _validate_future_prices(
        future_adjusted_prices,
        decision_date=decision_date,
    )

    eligible, selected, excluded = _select_facts(
        annual_facts,
        decision_date=decision_date,
        lag_days=annual_availability_lag_days,
    )
    inputs = _build_inputs(
        symbol=symbol,
        company_model=company_model,
        decision_adjusted_price=valuation_price,
        eligible=eligible,
        evidence_confidence=evidence_confidence,
    )
    assessment = evaluate_long_horizon(inputs)
    outcomes = _attach_outcomes(
        decision_date=decision_date,
        decision_adjusted_price=decision_adjusted_price,
        future_prices=future_prices,
    )
    return LongHorizonReplayResult(
        version=LONG_HORIZON_REPLAY_VERSION,
        security_id=security_id,
        symbol=symbol,
        decision_date=decision_date,
        claim_boundary=(
            ReplayClaimBoundary.CURRENT_REVISION_RETROSPECTIVE_CONSERVATIVE_LAG
        ),
        availability_policy_version=CONSERVATIVE_LAG_POLICY_VERSION,
        annual_availability_lag_days=annual_availability_lag_days,
        inputs=inputs,
        assessment=assessment,
        selected_facts=selected,
        excluded_facts=excluded,
        outcomes=outcomes,
    )


def _require_hash(value: str, name: str) -> None:
    if not _HASH_PATTERN.fullmatch(value):
        raise ValueError(f"{name} must be a canonical sha256 value")


def _validate_unique_facts(facts: tuple[AnnualFactRecord, ...]) -> None:
    identities = tuple((item.metric, item.period_end) for item in facts)
    if len(identities) != len(set(identities)):
        raise ValueError(
            "Annual facts must contain one current revision per metric and period"
        )


def _validate_future_prices(
    prices: tuple[AdjustedPriceObservation, ...],
    *,
    decision_date: date,
) -> tuple[AdjustedPriceObservation, ...]:
    dates = tuple(item.trading_date for item in prices)
    if len(dates) != len(set(dates)):
        raise ValueError("Future adjusted price dates must be unique")
    if tuple(sorted(dates)) != dates:
        raise ValueError("Future adjusted prices must be ordered")
    if any(item <= decision_date for item in dates):
        raise ValueError(
            "Outcome observations must be strictly after the decision date"
        )
    return prices


def _select_facts(
    facts: tuple[AnnualFactRecord, ...],
    *,
    decision_date: date,
    lag_days: int,
) -> tuple[
    dict[AnnualMetric, tuple[AnnualFactRecord, ...]],
    tuple[SelectedAnnualFact, ...],
    tuple[ExcludedAnnualFact, ...],
]:
    eligible: dict[AnnualMetric, list[AnnualFactRecord]] = {}
    selected: list[SelectedAnnualFact] = []
    excluded: list[ExcludedAnnualFact] = []
    for fact in sorted(facts, key=lambda item: (item.metric.value, item.period_end)):
        available_date = fact.period_end + timedelta(days=lag_days)
        reason = (
            ExcludedFactReason.FACT_PERIOD_AFTER_DECISION
            if fact.period_end > decision_date
            else ExcludedFactReason.FACT_NOT_AVAILABLE_BY_CONSERVATIVE_LAG
            if available_date > decision_date
            else None
        )
        if reason is not None:
            excluded.append(
                ExcludedAnnualFact(
                    metric=fact.metric,
                    period_end=fact.period_end,
                    conservative_available_date=available_date,
                    current_revision_evidence_hash=(
                        fact.current_revision_evidence_hash
                    ),
                    reason=reason,
                )
            )
            continue
        eligible.setdefault(fact.metric, []).append(fact)
        selected.append(
            SelectedAnnualFact(
                metric=fact.metric,
                period_end=fact.period_end,
                conservative_available_date=available_date,
                current_revision_evidence_hash=(
                    fact.current_revision_evidence_hash
                ),
            )
        )
    return (
        {
            metric: tuple(sorted(records, key=lambda item: item.period_end))
            for metric, records in eligible.items()
        },
        tuple(selected),
        tuple(excluded),
    )


def _build_inputs(
    *,
    symbol: str,
    company_model: CompanyModel,
    decision_adjusted_price: Decimal,
    eligible: dict[AnnualMetric, tuple[AnnualFactRecord, ...]],
    evidence_confidence: float,
) -> LongHorizonInputs:
    operating_margin = _same_period_ratio(
        eligible,
        AnnualMetric.OPERATING_INCOME,
        AnnualMetric.REVENUE,
    )
    net_margin = _same_period_ratio(
        eligible,
        AnnualMetric.NET_INCOME,
        AnnualMetric.REVENUE,
    )
    return_on_equity = _same_period_ratio(
        eligible,
        AnnualMetric.NET_INCOME,
        AnnualMetric.TOTAL_EQUITY,
        require_positive_denominator=True,
    )
    revenue_growth = _year_over_year(eligible.get(AnnualMetric.REVENUE, ()))
    earnings_growth = _year_over_year(
        eligible.get(AnnualMetric.NET_INCOME, ())
    )
    debt_to_equity = _same_period_ratio(
        eligible,
        AnnualMetric.TOTAL_DEBT,
        AnnualMetric.TOTAL_EQUITY,
        require_positive_denominator=True,
    )
    diluted_eps = _latest(eligible.get(AnnualMetric.DILUTED_EPS, ()))
    market_cap_and_income = _decision_market_cap_and_income(
        eligible,
        decision_adjusted_price=decision_adjusted_price,
    )
    price_earnings = (
        decision_adjusted_price / diluted_eps.value
        if diluted_eps is not None and diluted_eps.value > 0
        else market_cap_and_income[0] / market_cap_and_income[1]
        if market_cap_and_income is not None
        and market_cap_and_income[1] > 0
        else None
    )
    enterprise_value_ebitda = _enterprise_value_ebitda(
        eligible,
        decision_adjusted_price=decision_adjusted_price,
    )
    peg = (
        price_earnings / (earnings_growth * Decimal("100"))
        if price_earnings is not None
        and earnings_growth is not None
        and earnings_growth > 0
        else None
    )
    return LongHorizonInputs(
        symbol=symbol,
        company_model=company_model,
        price_earnings=_as_float(price_earnings),
        enterprise_value_ebitda=_as_float(enterprise_value_ebitda),
        peg=_as_float(peg),
        operating_margin=_as_float(operating_margin),
        net_margin=_as_float(net_margin),
        return_on_equity=_as_float(return_on_equity),
        revenue_growth_yoy=_as_float(revenue_growth),
        earnings_growth_yoy=_as_float(earnings_growth),
        current_ratio=None,
        debt_to_equity=_as_float(debt_to_equity),
        evidence_confidence=evidence_confidence,
    )


def _latest(
    records: tuple[AnnualFactRecord, ...],
) -> AnnualFactRecord | None:
    return records[-1] if records else None


def _decision_market_cap_and_income(
    eligible: dict[AnnualMetric, tuple[AnnualFactRecord, ...]],
    *,
    decision_adjusted_price: Decimal,
) -> tuple[Decimal, Decimal] | None:
    shares = {
        item.period_end: item
        for item in eligible.get(AnnualMetric.SHARES_OUTSTANDING, ())
    }
    income = {
        item.period_end: item
        for item in eligible.get(AnnualMetric.NET_INCOME, ())
    }
    common_periods = sorted(shares.keys() & income.keys())
    if not common_periods:
        return None
    period_end = common_periods[-1]
    if shares[period_end].value <= 0:
        return None
    return (
        decision_adjusted_price * shares[period_end].value,
        income[period_end].value,
    )


def _enterprise_value_ebitda(
    eligible: dict[AnnualMetric, tuple[AnnualFactRecord, ...]],
    *,
    decision_adjusted_price: Decimal,
) -> Decimal | None:
    direct = _same_period_ratio(
        eligible,
        AnnualMetric.ENTERPRISE_VALUE,
        AnnualMetric.EBITDA,
        require_positive_numerator=True,
        require_positive_denominator=True,
    )
    if direct is not None:
        return direct
    by_metric = {
        metric: {
            item.period_end: item
            for item in eligible.get(metric, ())
        }
        for metric in (
            AnnualMetric.SHARES_OUTSTANDING,
            AnnualMetric.TOTAL_DEBT,
            AnnualMetric.CASH_AND_EQUIVALENTS,
            AnnualMetric.EBITDA,
        )
    }
    common_periods = sorted(
        set.intersection(
            *(set(rows) for rows in by_metric.values()),
        )
    )
    if not common_periods:
        return None
    period_end = common_periods[-1]
    shares = by_metric[AnnualMetric.SHARES_OUTSTANDING][period_end].value
    ebitda = by_metric[AnnualMetric.EBITDA][period_end].value
    if shares <= 0 or ebitda <= 0:
        return None
    enterprise_value = (
        decision_adjusted_price * shares
        + by_metric[AnnualMetric.TOTAL_DEBT][period_end].value
        - by_metric[AnnualMetric.CASH_AND_EQUIVALENTS][period_end].value
    )
    return enterprise_value / ebitda if enterprise_value > 0 else None


def _same_period_ratio(
    eligible: dict[AnnualMetric, tuple[AnnualFactRecord, ...]],
    numerator_metric: AnnualMetric,
    denominator_metric: AnnualMetric,
    *,
    require_positive_numerator: bool = False,
    require_positive_denominator: bool = False,
) -> Decimal | None:
    numerators = {
        item.period_end: item for item in eligible.get(numerator_metric, ())
    }
    denominators = {
        item.period_end: item for item in eligible.get(denominator_metric, ())
    }
    common_periods = sorted(numerators.keys() & denominators.keys())
    if not common_periods:
        return None
    period_end = common_periods[-1]
    numerator = numerators[period_end].value
    denominator = denominators[period_end].value
    if denominator == 0:
        return None
    if require_positive_numerator and numerator <= 0:
        return None
    if require_positive_denominator and denominator <= 0:
        return None
    return numerator / denominator


def _year_over_year(
    records: tuple[AnnualFactRecord, ...],
) -> Decimal | None:
    if len(records) < 2:
        return None
    previous, current = records[-2:]
    elapsed_days = (current.period_end - previous.period_end).days
    if not 300 <= elapsed_days <= 430 or previous.value == 0:
        return None
    return current.value / previous.value - Decimal(1)


def _as_float(value: Decimal | None) -> float | None:
    return float(value) if value is not None else None


def _attach_outcomes(
    *,
    decision_date: date,
    decision_adjusted_price: Decimal,
    future_prices: tuple[AdjustedPriceObservation, ...],
) -> tuple[HistoricalOutcomeAttachment, ...]:
    results = []
    for horizon in OUTCOME_HORIZONS:
        if len(future_prices) < horizon:
            results.append(
                HistoricalOutcomeAttachment(
                    horizon_trading_days=horizon,
                    status=OutcomeStatus.NOT_MATURED,
                    entry_date=decision_date,
                    exit_date=None,
                    adjusted_total_return=None,
                    exit_price_evidence_hash=None,
                )
            )
            continue
        terminal = future_prices[horizon - 1]
        results.append(
            HistoricalOutcomeAttachment(
                horizon_trading_days=horizon,
                status=OutcomeStatus.MATURED,
                entry_date=decision_date,
                exit_date=terminal.trading_date,
                adjusted_total_return=(
                    terminal.adjusted_close / decision_adjusted_price
                    - Decimal(1)
                ),
                exit_price_evidence_hash=terminal.evidence_hash,
            )
        )
    return tuple(results)
