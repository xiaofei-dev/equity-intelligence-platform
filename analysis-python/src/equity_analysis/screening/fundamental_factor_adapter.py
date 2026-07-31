from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from equity_analysis.screening.config import QC_WEIGHTS, UQ_WEIGHTS
from equity_analysis.screening.factors import (
    InvalidFactorInput,
    cash_conversion,
    compound_annual_growth_rate,
    earnings_yield,
    enterprise_value,
    fcf_yield,
    free_cash_flow,
    free_cash_flow_margin,
    interest_coverage,
    invested_capital,
    margin_quality,
    margin_stability,
    net_debt_to_ebitda,
    return_on_invested_capital,
)
from equity_analysis.screening.models import DataLineage, FactorInput, FactorStatus

CURRENT_WINDOW_MAX_AGE_DAYS = 150
DISCRETE_QUARTER_MIN_DAYS = 60
DISCRETE_QUARTER_MAX_DAYS = 120
ANNUAL_MIN_DAYS = 300
ANNUAL_MAX_DAYS = 400
THREE_YEAR_MIN_DAYS = 1000
THREE_YEAR_MAX_DAYS = 1200

FUNDAMENTAL_FACTOR_CODES = tuple(
    sorted(set(QC_WEIGHTS) | set(UQ_WEIGHTS))
)
INSTANT_METRICS = frozenset(
    {
        "cash_and_equivalents",
        "enterprise_value",
        "minority_interest",
        "shares_outstanding",
        "stockholders_equity",
        "total_debt",
    }
)


@dataclass(frozen=True)
class PersistedFundamentalFact:
    metric_code: str
    value: Decimal
    unit: str
    currency: str | None
    period_start: date | None
    period_end: date
    fiscal_period: str
    form_type: str
    filed_at: datetime
    available_at: datetime
    ingested_at: datetime
    mapping_version: str
    normalization_version: str
    revision_status: str
    quality_status: str
    provider: str
    source_reference: str
    content_hash: str

    @property
    def lineage(self) -> DataLineage:
        return DataLineage(
            provider=self.provider,
            source_reference=self.source_reference,
            period_end=self.period_end,
            filed_at=self.filed_at,
            available_at=self.available_at,
            ingested_at=self.ingested_at,
            currency=self.currency,
            unit=self.unit,
            revision_status=self.revision_status,
            quality_status=self.quality_status,
            content_hash=self.content_hash,
        )


@dataclass(frozen=True)
class PersistedMarketValue:
    value: Decimal
    unit: str
    currency: str | None
    observation_date: date
    available_at: datetime
    ingested_at: datetime
    revision_status: str
    quality_status: str
    provider: str
    source_reference: str
    content_hash: str

    @property
    def lineage(self) -> DataLineage:
        return DataLineage(
            provider=self.provider,
            source_reference=self.source_reference,
            period_end=self.observation_date,
            available_at=self.available_at,
            ingested_at=self.ingested_at,
            currency=self.currency,
            unit=self.unit,
            revision_status=self.revision_status,
            quality_status=self.quality_status,
            content_hash=self.content_hash,
        )


@dataclass(frozen=True)
class FundamentalOperandDiagnostic:
    factor_code: str
    operand_code: str
    status: FactorStatus
    reason_code: str | None


FACTOR_OPERAND_REQUIREMENTS: dict[str, tuple[str, ...]] = {
    "roic": (
        "TTM:operating_income",
        "TTM:income_tax",
        "TTM:pretax_income",
        "INSTANT:stockholders_equity",
        "INSTANT:total_debt",
        "INSTANT:cash_and_equivalents",
        "PRIOR_1Y_INSTANT:stockholders_equity",
        "PRIOR_1Y_INSTANT:total_debt",
        "PRIOR_1Y_INSTANT:cash_and_equivalents",
    ),
    "fcf_margin": (
        "TTM:operating_cash_flow",
        "TTM:capital_expenditure",
        "TTM:revenue",
    ),
    "cash_conversion": (
        "TTM:operating_cash_flow",
        "TTM:capital_expenditure",
        "TTM:net_income",
    ),
    "margin_quality": (
        "TTM:gross_profit",
        "TTM:operating_income",
        "TTM:revenue",
        "PRIOR_3Y_TTM:gross_profit",
        "PRIOR_3Y_TTM:operating_income",
        "PRIOR_3Y_TTM:revenue",
    ),
    "stability": ("EIGHT_QUARTER_ALIGNED_MARGIN_HISTORY",),
    "eps_growth": (
        "TTM:net_income",
        "TTM:diluted_weighted_average_shares",
        "PRIOR_3Y_TTM:net_income",
        "PRIOR_3Y_TTM:diluted_weighted_average_shares",
    ),
    "fcf_per_share_growth": (
        "TTM:operating_cash_flow",
        "TTM:capital_expenditure",
        "TTM:diluted_weighted_average_shares",
        "PRIOR_3Y_TTM:operating_cash_flow",
        "PRIOR_3Y_TTM:capital_expenditure",
        "PRIOR_3Y_TTM:diluted_weighted_average_shares",
    ),
    "net_debt_to_ebitda": (
        "INSTANT:total_debt",
        "INSTANT:cash_and_equivalents",
        "TTM:ebitda",
    ),
    "interest_coverage": (
        "TTM:operating_income",
        "TTM:interest_expense",
    ),
    "dilution": (
        "TTM:diluted_weighted_average_shares",
        "PRIOR_3Y_TTM:diluted_weighted_average_shares",
    ),
    "valuation_guardrail": ("VALUATION_COHORT_PERCENTILES",),
    "earnings_yield": (
        "TTM:operating_income",
        "CURRENT_ENTERPRISE_VALUE",
    ),
    "fcf_yield": (
        "TTM:operating_cash_flow",
        "TTM:capital_expenditure",
        "CURRENT_MARKET_CAP",
    ),
    "historical_fcf_yield_percentile": (
        "HISTORICAL_PIT_FCF_YIELD_SERIES",
    ),
    "operating_margin": (
        "TTM:operating_income",
        "TTM:revenue",
    ),
}


@dataclass(frozen=True)
class _Operand:
    status: FactorStatus
    value: Decimal | None = None
    reason: str | None = None
    lineage: tuple[DataLineage, ...] = ()


@dataclass(frozen=True)
class _Window:
    facts: tuple[PersistedFundamentalFact, ...]
    value: Decimal

    @property
    def end(self) -> date:
        return self.facts[-1].period_end

    @property
    def lineage(self) -> tuple[DataLineage, ...]:
        return _lineage(self.facts)


def assemble_fundamental_factor_inputs(
    facts: tuple[PersistedFundamentalFact, ...],
    *,
    market_value: PersistedMarketValue | None,
    as_of: datetime,
    ingestion_cutoff: datetime,
) -> dict[str, FactorInput]:
    """Build frozen Objective Rating inputs from proven persisted facts only."""
    if (
        as_of.tzinfo is None
        or as_of.utcoffset() is None
        or ingestion_cutoff.tzinfo is None
        or ingestion_cutoff.utcoffset() is None
    ):
        raise ValueError("Objective factor assembly boundaries must include timezones")
    eligible = tuple(
        fact
        for fact in facts
        if fact.available_at <= as_of and fact.ingested_at <= ingestion_cutoff
    )
    by_metric = {
        metric: tuple(fact for fact in eligible if fact.metric_code == metric)
        for metric in {fact.metric_code for fact in eligible}
    }

    ttm: dict[str, _Operand] = {}
    windows: dict[str, tuple[_Window, ...]] = {}
    for metric in (
        "capital_expenditure",
        "diluted_weighted_average_shares",
        "ebitda",
        "gross_profit",
        "income_tax",
        "interest_expense",
        "net_income",
        "operating_cash_flow",
        "operating_income",
        "pretax_income",
        "revenue",
    ):
        ttm[metric], windows[metric] = _ttm(
            by_metric.get(metric, ()),
            as_of=as_of,
            weighted_average=metric == "diluted_weighted_average_shares",
        )

    prior_ttm = {
        metric: _prior_three_year(windows[metric])
        for metric in (
            "capital_expenditure",
            "diluted_weighted_average_shares",
            "gross_profit",
            "net_income",
            "operating_cash_flow",
            "operating_income",
            "revenue",
        )
    }
    instant = {
        metric: _instant(by_metric.get(metric, ()))
        for metric in INSTANT_METRICS
    }
    current_reference = max(
        (
            item.period_end
            for operand in ttm.values()
            if operand.status == FactorStatus.VALID
            for item in operand.lineage
            if item.period_end is not None
        ),
        default=as_of.date(),
    )
    prior_instant = {
        metric: _instant(
            by_metric.get(metric, ()),
            before_or_on=current_reference,
            target_age_days=365,
        )
        for metric in ("cash_and_equivalents", "stockholders_equity", "total_debt")
    }

    current_invested = _calculate(
        "current_invested_capital",
        (
            instant["stockholders_equity"],
            instant["total_debt"],
            instant["cash_and_equivalents"],
        ),
        lambda equity, debt, cash: invested_capital(equity, debt, cash),
    )
    prior_invested = _calculate(
        "prior_invested_capital",
        (
            prior_instant["stockholders_equity"],
            prior_instant["total_debt"],
            prior_instant["cash_and_equivalents"],
        ),
        lambda equity, debt, cash: invested_capital(equity, debt, cash),
    )
    current_fcf = _calculate(
        "fcf_ttm",
        (ttm["operating_cash_flow"], ttm["capital_expenditure"]),
        free_cash_flow,
    )
    prior_fcf = _calculate(
        "prior_fcf_ttm",
        (prior_ttm["operating_cash_flow"], prior_ttm["capital_expenditure"]),
        free_cash_flow,
    )
    current_gross_margin = _ratio(
        "gross_margin_ttm", ttm["gross_profit"], ttm["revenue"]
    )
    current_operating_margin = _ratio(
        "operating_margin_ttm", ttm["operating_income"], ttm["revenue"]
    )
    prior_gross_margin = _ratio(
        "prior_gross_margin_ttm",
        prior_ttm["gross_profit"],
        prior_ttm["revenue"],
    )
    prior_operating_margin = _ratio(
        "prior_operating_margin_ttm",
        prior_ttm["operating_income"],
        prior_ttm["revenue"],
    )
    current_eps = _ratio(
        "diluted_eps_current",
        ttm["net_income"],
        ttm["diluted_weighted_average_shares"],
    )
    prior_eps = _ratio(
        "diluted_eps_prior",
        prior_ttm["net_income"],
        prior_ttm["diluted_weighted_average_shares"],
    )
    current_fcf_per_share = _ratio(
        "fcf_per_share_current",
        current_fcf,
        ttm["diluted_weighted_average_shares"],
    )
    prior_fcf_per_share = _ratio(
        "fcf_per_share_prior",
        prior_fcf,
        prior_ttm["diluted_weighted_average_shares"],
    )
    market_cap = _market_cap_operand(
        market_value,
        as_of=as_of,
        ingestion_cutoff=ingestion_cutoff,
    )
    enterprise = instant["enterprise_value"]
    if enterprise.status != FactorStatus.VALID:
        enterprise = _calculate(
            "enterprise_value",
            (
                market_cap,
                instant["total_debt"],
                instant["cash_and_equivalents"],
                instant["minority_interest"],
            ),
            enterprise_value,
        )

    operating_margins, fcf_margins, stability_lineage = _aligned_margin_history(
        windows
    )
    factors = {
        "roic": _factor(
            "roic",
            (
                ttm["operating_income"],
                ttm["income_tax"],
                ttm["pretax_income"],
                current_invested,
                prior_invested,
            ),
            return_on_invested_capital,
        ),
        "fcf_margin": _factor(
            "fcf_margin",
            (
                ttm["operating_cash_flow"],
                ttm["capital_expenditure"],
                ttm["revenue"],
            ),
            free_cash_flow_margin,
        ),
        "cash_conversion": _factor(
            "cash_conversion",
            (
                ttm["operating_cash_flow"],
                ttm["capital_expenditure"],
                ttm["net_income"],
            ),
            cash_conversion,
        ),
        "margin_quality": _factor(
            "margin_quality",
            (
                current_gross_margin,
                current_operating_margin,
                prior_gross_margin,
                prior_operating_margin,
            ),
            lambda gross, operating, prior_gross, prior_operating: margin_quality(
                gross,
                operating,
                prior_gross,
                prior_operating,
            ),
        ),
        "stability": _series_factor(
            "stability",
            operating_margins,
            fcf_margins,
            stability_lineage,
        ),
        "eps_growth": _factor(
            "eps_growth",
            (current_eps, prior_eps),
            lambda current, prior: compound_annual_growth_rate(current, prior, 3),
        ),
        "fcf_per_share_growth": _factor(
            "fcf_per_share_growth",
            (current_fcf_per_share, prior_fcf_per_share),
            lambda current, prior: compound_annual_growth_rate(current, prior, 3),
        ),
        "net_debt_to_ebitda": _factor(
            "net_debt_to_ebitda",
            (
                instant["total_debt"],
                instant["cash_and_equivalents"],
                ttm["ebitda"],
            ),
            lambda debt, cash, ebitda_value: net_debt_to_ebitda(
                debt - cash, ebitda_value
            ),
        ),
        "interest_coverage": _factor(
            "interest_coverage",
            (ttm["operating_income"], ttm["interest_expense"]),
            interest_coverage,
        ),
        "dilution": _factor(
            "dilution",
            (
                ttm["diluted_weighted_average_shares"],
                prior_ttm["diluted_weighted_average_shares"],
            ),
            lambda current, prior: compound_annual_growth_rate(current, prior, 3),
        ),
        "valuation_guardrail": _missing(
            "valuation_guardrail",
            "VALUATION_GUARDRAIL_REQUIRES_COHORT_PERCENTILES",
        ),
        "earnings_yield": _factor(
            "earnings_yield",
            (ttm["operating_income"], enterprise),
            earnings_yield,
        ),
        "fcf_yield": _factor(
            "fcf_yield",
            (current_fcf, market_cap),
            fcf_yield,
        ),
        "historical_fcf_yield_percentile": _missing(
            "historical_fcf_yield_percentile",
            "HISTORICAL_PIT_FCF_YIELD_SERIES_NOT_PERSISTED",
        ),
        "operating_margin": _from_operand(
            "operating_margin", current_operating_margin
        ),
    }
    return {
        name: factors.get(name, _missing(name, "FACTOR_INPUT_NOT_ASSEMBLED"))
        for name in FUNDAMENTAL_FACTOR_CODES
    }


def diagnose_fundamental_operand_evidence(
    facts: tuple[PersistedFundamentalFact, ...],
    *,
    market_value: PersistedMarketValue | None,
    as_of: datetime,
    ingestion_cutoff: datetime,
) -> tuple[FundamentalOperandDiagnostic, ...]:
    """Describe frozen-v1 operand readiness without exposing provider values."""
    eligible = tuple(
        fact
        for fact in facts
        if fact.available_at <= as_of and fact.ingested_at <= ingestion_cutoff
    )
    by_metric = {
        metric: tuple(fact for fact in eligible if fact.metric_code == metric)
        for metric in {fact.metric_code for fact in eligible}
    }
    operand_states: dict[str, _Operand] = {}
    windows: dict[str, tuple[_Window, ...]] = {}
    duration_metrics = {
        operand.split(":", maxsplit=1)[1]
        for operands in FACTOR_OPERAND_REQUIREMENTS.values()
        for operand in operands
        if operand.startswith(("TTM:", "PRIOR_3Y_TTM:"))
    }
    for metric in sorted(duration_metrics):
        current, metric_windows = _ttm(
            by_metric.get(metric, ()),
            as_of=as_of,
            weighted_average=metric == "diluted_weighted_average_shares",
        )
        operand_states[f"TTM:{metric}"] = current
        operand_states[f"PRIOR_3Y_TTM:{metric}"] = _prior_three_year(
            metric_windows
        )
        windows[metric] = metric_windows

    current_reference = max(
        (
            item.period_end
            for operand in operand_states.values()
            if operand.status == FactorStatus.VALID
            for item in operand.lineage
            if item.period_end is not None
        ),
        default=as_of.date(),
    )
    instant_metrics = {
        operand.split(":", maxsplit=1)[1]
        for operands in FACTOR_OPERAND_REQUIREMENTS.values()
        for operand in operands
        if operand.startswith(("INSTANT:", "PRIOR_1Y_INSTANT:"))
    }
    for metric in sorted(instant_metrics):
        operand_states[f"INSTANT:{metric}"] = _instant(
            by_metric.get(metric, ())
        )
        operand_states[f"PRIOR_1Y_INSTANT:{metric}"] = _instant(
            by_metric.get(metric, ()),
            before_or_on=current_reference,
            target_age_days=365,
        )

    market_cap = _market_cap_operand(
        market_value,
        as_of=as_of,
        ingestion_cutoff=ingestion_cutoff,
    )
    operand_states["CURRENT_MARKET_CAP"] = market_cap
    enterprise = operand_states.get(
        "INSTANT:enterprise_value",
        _missing_operand("INSTANT_FACT_NOT_AVAILABLE"),
    )
    if enterprise.status != FactorStatus.VALID:
        enterprise = _calculate(
            "enterprise_value",
            (
                market_cap,
                operand_states.get(
                    "INSTANT:total_debt",
                    _missing_operand("INSTANT_FACT_NOT_AVAILABLE"),
                ),
                operand_states.get(
                    "INSTANT:cash_and_equivalents",
                    _missing_operand("INSTANT_FACT_NOT_AVAILABLE"),
                ),
                operand_states.get(
                    "INSTANT:minority_interest",
                    _missing_operand("INSTANT_FACT_NOT_AVAILABLE"),
                ),
            ),
            enterprise_value,
        )
    operand_states["CURRENT_ENTERPRISE_VALUE"] = enterprise

    operating_margins, fcf_margins, _ = _aligned_margin_history(
        {
            metric: windows.get(metric, ())
            for metric in (
                "operating_income",
                "revenue",
                "operating_cash_flow",
                "capital_expenditure",
            )
        }
    )
    operand_states["EIGHT_QUARTER_ALIGNED_MARGIN_HISTORY"] = (
        _Operand(status=FactorStatus.VALID)
        if len(operating_margins) == 8 and len(fcf_margins) == 8
        else _missing_operand("EIGHT_ALIGNED_DISCRETE_QUARTERS_NOT_AVAILABLE")
    )
    operand_states["VALUATION_COHORT_PERCENTILES"] = _missing_operand(
        "VALUATION_GUARDRAIL_REQUIRES_COHORT_PERCENTILES"
    )
    operand_states["HISTORICAL_PIT_FCF_YIELD_SERIES"] = _missing_operand(
        "HISTORICAL_PIT_FCF_YIELD_SERIES_NOT_PERSISTED"
    )

    diagnostics = []
    for factor_code in sorted(FACTOR_OPERAND_REQUIREMENTS):
        for operand_code in FACTOR_OPERAND_REQUIREMENTS[factor_code]:
            operand = operand_states.get(
                operand_code,
                _missing_operand("OPERAND_EVIDENCE_NOT_ASSEMBLED"),
            )
            diagnostics.append(
                FundamentalOperandDiagnostic(
                    factor_code=factor_code,
                    operand_code=operand_code,
                    status=operand.status,
                    reason_code=operand.reason,
                )
            )
    return tuple(diagnostics)


def _ttm(
    facts: tuple[PersistedFundamentalFact, ...],
    *,
    as_of: datetime,
    weighted_average: bool,
) -> tuple[_Operand, tuple[_Window, ...]]:
    valid = tuple(fact for fact in facts if fact.quality_status == "VALIDATED")
    direct = [
        fact
        for fact in valid
        if fact.fiscal_period == "TTM"
        and fact.period_start is not None
        and ANNUAL_MIN_DAYS
        <= (fact.period_end - fact.period_start).days + 1
        <= ANNUAL_MAX_DAYS
    ]
    if direct:
        selected = max(
            direct,
            key=lambda fact: (fact.period_end, fact.available_at, fact.ingested_at),
        )
        if (as_of.date() - selected.period_end).days > CURRENT_WINDOW_MAX_AGE_DAYS:
            return _missing_operand("LATEST_TTM_WINDOW_IS_STALE"), ()
        return (
            _Operand(
                status=FactorStatus.VALID,
                value=selected.value,
                lineage=(selected.lineage,),
            ),
            (),
        )
    discrete = _latest_discrete_facts(valid)
    windows = _consecutive_windows(discrete, weighted_average=weighted_average)
    if not windows:
        reason = (
            "PERIOD_SEMANTICS_UNPROVEN"
            if facts
            else "FUNDAMENTAL_FACT_NOT_PERSISTED"
        )
        if facts and any(fact.quality_status == "REJECTED" for fact in facts):
            return _invalid_operand("SOURCE_FACT_REJECTED"), ()
        return _missing_operand(reason), ()
    current = windows[-1]
    if (as_of.date() - current.end).days > CURRENT_WINDOW_MAX_AGE_DAYS:
        return _missing_operand("LATEST_DISCRETE_TTM_WINDOW_IS_STALE"), windows
    return (
        _Operand(
            status=FactorStatus.VALID,
            value=current.value,
            lineage=current.lineage,
        ),
        windows,
    )


def _latest_discrete_facts(
    facts: tuple[PersistedFundamentalFact, ...],
) -> tuple[PersistedFundamentalFact, ...]:
    selected: dict[tuple[date, date], PersistedFundamentalFact] = {}
    for fact in facts:
        if (
            fact.period_start is None
            or fact.fiscal_period == "Q_UNPROVEN"
            or not fact.fiscal_period.startswith("Q")
        ):
            continue
        duration = (fact.period_end - fact.period_start).days + 1
        if not DISCRETE_QUARTER_MIN_DAYS <= duration <= DISCRETE_QUARTER_MAX_DAYS:
            continue
        key = (fact.period_start, fact.period_end)
        previous = selected.get(key)
        if previous is None or (
            fact.available_at,
            fact.ingested_at,
            fact.source_reference,
        ) > (
            previous.available_at,
            previous.ingested_at,
            previous.source_reference,
        ):
            selected[key] = fact
    return tuple(sorted(selected.values(), key=lambda fact: fact.period_end))


def _consecutive_windows(
    facts: tuple[PersistedFundamentalFact, ...],
    *,
    weighted_average: bool,
) -> tuple[_Window, ...]:
    result = []
    for index in range(len(facts) - 3):
        selected = facts[index : index + 4]
        if len({(fact.unit, fact.currency) for fact in selected}) != 1:
            continue
        if any(
            not (
                -1 <= (current.period_start - previous.period_end).days <= 10
                and 70 <= (current.period_end - previous.period_end).days <= 120
            )
            for previous, current in zip(selected, selected[1:], strict=False)
        ):
            continue
        if weighted_average:
            days = tuple(
                (fact.period_end - fact.period_start).days + 1
                for fact in selected
                if fact.period_start is not None
            )
            value = sum(
                (fact.value * day_count for fact, day_count in zip(selected, days, strict=True)),
                Decimal(0),
            ) / Decimal(sum(days))
        else:
            value = sum((fact.value for fact in selected), Decimal(0))
        result.append(_Window(facts=selected, value=value))
    return tuple(result)


def _prior_three_year(windows: tuple[_Window, ...]) -> _Operand:
    if not windows:
        return _missing_operand("CURRENT_TTM_WINDOW_NOT_AVAILABLE")
    current = windows[-1]
    candidates = [
        window
        for window in windows
        if THREE_YEAR_MIN_DAYS
        <= (current.end - window.end).days
        <= THREE_YEAR_MAX_DAYS
    ]
    if not candidates:
        return _missing_operand("THREE_YEAR_PRIOR_TTM_WINDOW_NOT_AVAILABLE")
    selected = candidates[-1]
    return _Operand(
        status=FactorStatus.VALID,
        value=selected.value,
        lineage=selected.lineage,
    )


def _instant(
    facts: tuple[PersistedFundamentalFact, ...],
    *,
    before_or_on: date | None = None,
    target_age_days: int | None = None,
) -> _Operand:
    valid = [
        fact
        for fact in facts
        if fact.quality_status == "VALIDATED"
        and fact.period_start is None
        and (before_or_on is None or fact.period_end <= before_or_on)
    ]
    if target_age_days is not None and before_or_on is not None:
        valid = [
            fact
            for fact in valid
            if target_age_days - 65
            <= (before_or_on - fact.period_end).days
            <= target_age_days + 65
        ]
    if not valid:
        if facts and any(fact.quality_status == "REJECTED" for fact in facts):
            return _invalid_operand("SOURCE_FACT_REJECTED")
        return _missing_operand(
            "PRIOR_INSTANT_FACT_NOT_AVAILABLE"
            if target_age_days is not None
            else "INSTANT_FACT_NOT_AVAILABLE"
        )
    selected = max(
        valid,
        key=lambda fact: (fact.period_end, fact.available_at, fact.ingested_at),
    )
    return _Operand(
        status=FactorStatus.VALID,
        value=selected.value,
        lineage=(selected.lineage,),
    )


def _market_cap_operand(
    market_value: PersistedMarketValue | None,
    *,
    as_of: datetime,
    ingestion_cutoff: datetime,
) -> _Operand:
    if market_value is None:
        return _missing_operand("PIT_MARKET_CAP_NOT_AVAILABLE")
    if (
        market_value.available_at > as_of
        or market_value.ingested_at > ingestion_cutoff
        or market_value.quality_status not in {"VALIDATED", "PROVISIONAL"}
    ):
        return _invalid_operand("PIT_MARKET_CAP_LINEAGE_INVALID")
    if market_value.value <= 0:
        return _invalid_operand("PIT_MARKET_CAP_NONPOSITIVE")
    return _Operand(
        status=FactorStatus.VALID,
        value=market_value.value,
        lineage=(market_value.lineage,),
    )


def _calculate(
    name: str,
    operands: tuple[_Operand, ...],
    calculation: Callable[..., Decimal],
) -> _Operand:
    invalid = [operand for operand in operands if operand.status == FactorStatus.INVALID]
    if invalid:
        return _invalid_operand(
            f"{name.upper()}_INPUT_INVALID",
            _operand_lineage(operands),
        )
    missing = [
        operand
        for operand in operands
        if operand.status != FactorStatus.VALID or operand.value is None
    ]
    if missing:
        return _missing_operand(
            f"{name.upper()}_INPUT_MISSING",
            _operand_lineage(operands),
        )
    try:
        value = calculation(
            *(operand.value for operand in operands if operand.value is not None)
        )
    except (InvalidFactorInput, ArithmeticError) as error:
        return _invalid_operand(str(error), _operand_lineage(operands))
    return _Operand(
        status=FactorStatus.VALID,
        value=value,
        lineage=_operand_lineage(operands),
    )


def _ratio(name: str, numerator: _Operand, denominator: _Operand) -> _Operand:
    return _calculate(
        name,
        (numerator, denominator),
        lambda left, right: _positive_ratio(left, right, name),
    )


def _positive_ratio(left: Decimal, right: Decimal, name: str) -> Decimal:
    if right <= 0:
        raise InvalidFactorInput(f"{name} requires a positive denominator")
    return left / right


def _factor(
    name: str,
    operands: tuple[_Operand, ...],
    calculation: Callable[..., Decimal],
) -> FactorInput:
    return _from_operand(name, _calculate(name, operands, calculation))


def _from_operand(name: str, operand: _Operand) -> FactorInput:
    return FactorInput(
        name=name,
        value=operand.value,
        status=operand.status,
        reason=operand.reason,
        lineage=operand.lineage,
    )


def _series_factor(
    name: str,
    operating_margins: tuple[Decimal, ...],
    fcf_margins: tuple[Decimal, ...],
    lineage: tuple[DataLineage, ...],
) -> FactorInput:
    if len(operating_margins) < 8 or len(fcf_margins) < 8:
        return _missing(name, "EIGHT_ALIGNED_DISCRETE_QUARTERS_NOT_AVAILABLE")
    try:
        value = margin_stability(operating_margins, fcf_margins)
    except (InvalidFactorInput, ArithmeticError) as error:
        return FactorInput(
            name=name,
            value=None,
            status=FactorStatus.INVALID,
            reason=str(error),
            lineage=lineage,
        )
    return FactorInput(
        name=name,
        value=value,
        status=FactorStatus.VALID,
        lineage=lineage,
    )


def _aligned_margin_history(
    windows: dict[str, tuple[_Window, ...]],
) -> tuple[tuple[Decimal, ...], tuple[Decimal, ...], tuple[DataLineage, ...]]:
    by_metric: dict[str, dict[date, PersistedFundamentalFact]] = {}
    for metric in (
        "operating_income",
        "revenue",
        "operating_cash_flow",
        "capital_expenditure",
    ):
        facts = {
            fact.period_end: fact
            for window in windows[metric]
            for fact in window.facts
        }
        by_metric[metric] = facts
    common = sorted(set.intersection(*(set(items) for items in by_metric.values())))
    selected = common[-8:]
    if len(selected) != 8:
        return (), (), ()
    all_facts = tuple(
        by_metric[metric][period_end]
        for period_end in selected
        for metric in (
            "operating_income",
            "revenue",
            "operating_cash_flow",
            "capital_expenditure",
        )
    )
    if len({(fact.unit, fact.currency) for fact in all_facts}) != 1:
        return (), (), _lineage(all_facts)
    operating_margins = tuple(
        by_metric["operating_income"][period_end].value
        / by_metric["revenue"][period_end].value
        for period_end in selected
        if by_metric["revenue"][period_end].value > 0
    )
    fcf_margins = tuple(
        (
            by_metric["operating_cash_flow"][period_end].value
            - abs(by_metric["capital_expenditure"][period_end].value)
        )
        / by_metric["revenue"][period_end].value
        for period_end in selected
        if by_metric["revenue"][period_end].value > 0
    )
    return operating_margins, fcf_margins, _lineage(all_facts)


def _operand_lineage(operands: tuple[_Operand, ...]) -> tuple[DataLineage, ...]:
    unique = {
        (item.provider, item.source_reference, item.content_hash): item
        for operand in operands
        for item in operand.lineage
    }
    return tuple(unique[key] for key in sorted(unique))


def _lineage(
    facts: tuple[PersistedFundamentalFact, ...],
) -> tuple[DataLineage, ...]:
    unique = {
        (fact.provider, fact.source_reference, fact.content_hash): fact.lineage
        for fact in facts
    }
    return tuple(unique[key] for key in sorted(unique))


def _missing(name: str, reason: str) -> FactorInput:
    return FactorInput(
        name=name,
        value=None,
        status=FactorStatus.MISSING,
        reason=reason,
    )


def _missing_operand(
    reason: str,
    lineage: tuple[DataLineage, ...] = (),
) -> _Operand:
    return _Operand(
        status=FactorStatus.MISSING,
        reason=reason,
        lineage=lineage,
    )


def _invalid_operand(
    reason: str,
    lineage: tuple[DataLineage, ...] = (),
) -> _Operand:
    return _Operand(
        status=FactorStatus.INVALID,
        reason=reason,
        lineage=lineage,
    )
