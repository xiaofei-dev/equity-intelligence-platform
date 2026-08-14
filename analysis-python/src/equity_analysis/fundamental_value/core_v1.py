from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal, DecimalException, localcontext
from enum import StrEnum

from equity_analysis.fundamental_value.contracts_v1 import (
    AGGREGATION_VERSION,
    ALLOWED_RISK_CAPS,
    MODEL_VERSION,
    RISK_CAP_VERSION,
    STRATEGY_VERSION,
    Applicability,
    CompanyType,
    DataState,
    ModelEvidenceLabel,
    ValuationMethod,
)

SCORE_QUANTUM = Decimal("0.01")
RATE_QUANTUM = Decimal("0.0001")
VALUE_QUANTUM = Decimal("0.01")
METHOD_WEIGHTS = {
    ValuationMethod.FCFF_DCF: Decimal("0.35"),
    ValuationMethod.NORMALIZED_OWNER_EARNINGS: Decimal("0.30"),
    ValuationMethod.EARNINGS_POWER: Decimal("0.25"),
    ValuationMethod.COMPARABLE_CROSS_CHECK: Decimal("0.10"),
}
FORMULA_VERSION = "fundamental-value-formulas-v1.1.0"
ASSUMPTION_POLICY_VERSION = "fundamental-value-assumptions-v1.1.0"
MAXIMUM_DCF_TERMINAL_VALUE_SHARE = Decimal("0.80")
PRIMARY_METHODS = frozenset(
    {
        ValuationMethod.FCFF_DCF,
        ValuationMethod.NORMALIZED_OWNER_EARNINGS,
        ValuationMethod.EARNINGS_POWER,
    }
)


class CoreViolation(ValueError):
    pass


def canonical_decimal_text(value: Decimal) -> str:
    """Return the frozen finite ordinary base-10 Decimal representation."""

    if not isinstance(value, Decimal) or not value.is_finite():
        raise CoreViolation("Canonical Decimal text requires one finite Decimal")
    if value.is_zero():
        return "0"
    return format(value, "f")


class ClaimCeiling(StrEnum):
    FULL_CURRENT_DECISION = "FULL_CURRENT_DECISION"
    LIMITED_MISSING_ADVANCED_EVIDENCE = "LIMITED_MISSING_ADVANCED_EVIDENCE"
    BLOCKED_MATERIAL_REFINANCING_UNCERTAINTY = "BLOCKED_MATERIAL_REFINANCING_UNCERTAINTY"


@dataclass(frozen=True)
class MetricEvidence:
    state: DataState
    value: Decimal | None = None
    reason_code: str | None = None

    def __post_init__(self) -> None:
        if self.state == DataState.VALID:
            if self.value is None or not self.value.is_finite():
                raise CoreViolation("VALID metric evidence requires one finite Decimal value")
            if self.reason_code is not None:
                raise CoreViolation("VALID metric evidence cannot carry a reason code")
        elif self.value is not None or not self.reason_code:
            raise CoreViolation(
                "Non-VALID metric evidence requires a reason and cannot carry a value"
            )

    @classmethod
    def valid(cls, value: Decimal | str) -> MetricEvidence:
        return cls(DataState.VALID, Decimal(value))

    @classmethod
    def missing(cls, reason_code: str) -> MetricEvidence:
        return cls(DataState.MISSING, reason_code=reason_code)


@dataclass(frozen=True)
class FundamentalValueInputsV1:
    company_type: CompanyType
    applicability: Applicability
    reference_price: MetricEvidence
    diluted_shares: MetricEvidence
    cash: MetricEvidence
    debt: MetricEvidence
    ebit: MetricEvidence
    tax_rate: MetricEvidence
    depreciation_and_amortization: MetricEvidence
    capital_expenditures: MetricEvidence
    change_in_working_capital: MetricEvidence
    normalized_free_cash_flow: MetricEvidence
    normalized_after_tax_operating_earnings: MetricEvidence
    ebitda: MetricEvidence
    comparable_ev_to_ebitda: MetricEvidence
    conservative_growth_rate: MetricEvidence
    discount_rate: MetricEvidence
    terminal_growth_rate: MetricEvidence
    net_distribution_yield: MetricEvidence
    return_on_invested_capital: MetricEvidence
    operating_margin: MetricEvidence
    free_cash_flow_margin: MetricEvidence
    earnings_stability: MetricEvidence
    cash_flow_stability: MetricEvidence
    net_debt_to_ebitda: MetricEvidence
    interest_coverage: MetricEvidence
    current_ratio: MetricEvidence
    diluted_share_growth: MetricEvidence
    cash_flow_to_net_income: MetricEvidence
    incremental_return_on_invested_capital: MetricEvidence
    acquisition_discipline: MetricEvidence
    shareholder_distribution_coverage: MetricEvidence
    cyclicality_risk: MetricEvidence
    concentration_risk: MetricEvidence
    event_risk: MetricEvidence
    debt_maturity_schedule: MetricEvidence
    projection_years: int = 5
    currency: str = "USD"

    def __post_init__(self) -> None:
        if self.projection_years < 3 or self.projection_years > 10:
            raise CoreViolation("Projection years must be between three and ten")
        if len(self.currency) != 3 or self.currency.upper() != self.currency:
            raise CoreViolation("Currency must be an uppercase three-letter code")
        if (
            self.debt_maturity_schedule.state == DataState.VALID
            and self.debt_maturity_schedule.value != Decimal("1")
        ):
            raise CoreViolation("Valid debt-maturity coverage uses the exact sentinel value one")


@dataclass(frozen=True)
class DimensionResult:
    state: DataState
    score: Decimal | None
    reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.state == DataState.VALID:
            if self.score is None or not self.score.is_finite() or not 0 <= self.score <= 100:
                raise CoreViolation("VALID dimension requires one finite score from zero to 100")
            if self.reason_codes:
                raise CoreViolation("VALID dimension cannot carry reason codes")
        elif self.score is not None or not self.reason_codes:
            raise CoreViolation("Non-VALID dimension requires reasons and no score")


@dataclass(frozen=True)
class ValuationResult:
    method: ValuationMethod
    state: DataState
    low: Decimal | None
    central: Decimal | None
    high: Decimal | None
    reason_codes: tuple[str, ...]
    terminal_value_share: Decimal | None = None

    def __post_init__(self) -> None:
        values = (self.low, self.central, self.high)
        if self.state == DataState.VALID:
            if any(value is None or not value.is_finite() for value in values):
                raise CoreViolation("VALID valuation requires three finite values")
            assert self.low is not None and self.central is not None and self.high is not None
            if not Decimal("0") < self.low <= self.central <= self.high:
                raise CoreViolation("VALID valuation range must be positive and ordered")
            if self.reason_codes:
                raise CoreViolation("VALID valuation cannot carry reason codes")
        elif any(value is not None for value in values) or not self.reason_codes:
            raise CoreViolation("Non-VALID valuation requires reasons and no values")
        if self.terminal_value_share is not None and (
            self.state != DataState.VALID
            or not self.terminal_value_share.is_finite()
            or not 0 <= self.terminal_value_share <= 1
        ):
            raise CoreViolation("Terminal-value share is invalid")


@dataclass(frozen=True)
class OrderedRange:
    state: DataState
    low: Decimal | None
    central: Decimal | None
    high: Decimal | None
    reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        values = (self.low, self.central, self.high)
        if self.state == DataState.VALID:
            if any(value is None or not value.is_finite() for value in values):
                raise CoreViolation("VALID ordered range requires three finite values")
            assert self.low is not None and self.central is not None and self.high is not None
            if not self.low <= self.central <= self.high:
                raise CoreViolation("VALID ordered range must be ordered")
            if self.reason_codes:
                raise CoreViolation("VALID ordered range cannot carry reason codes")
        elif any(value is not None for value in values) or not self.reason_codes:
            raise CoreViolation("Non-VALID ordered range requires reasons and no values")


@dataclass(frozen=True)
class RiskCapResult:
    ceiling: Decimal
    binding_reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.ceiling not in ALLOWED_RISK_CAPS or not self.binding_reasons:
            raise CoreViolation("Risk cap requires a frozen tier and binding reason")


@dataclass(frozen=True)
class ThesisCondition:
    code: str
    state: DataState
    observed_value: Decimal | None
    threshold: Decimal | None
    satisfied: bool | None
    reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.state == DataState.VALID:
            if (
                self.observed_value is None
                or not self.observed_value.is_finite()
                or self.threshold is None
                or not self.threshold.is_finite()
                or self.satisfied is None
            ):
                raise CoreViolation("VALID thesis condition requires finite values and result")
            if self.reason_codes:
                raise CoreViolation("VALID thesis condition cannot carry reason codes")
        elif self.observed_value is not None or self.satisfied is not None or not self.reason_codes:
            raise CoreViolation(
                "Non-VALID thesis condition requires reasons and no observed result"
            )


@dataclass(frozen=True)
class FundamentalValueAssessmentV1:
    company_type: CompanyType
    applicability: Applicability
    reference_price: MetricEvidence
    currency: str
    projection_years: int
    company_quality: DimensionResult
    financial_resilience: DimensionResult
    earnings_and_cash_flow_quality: DimensionResult
    capital_allocation_quality: DimensionResult
    valuations: tuple[ValuationResult, ...]
    fair_value: OrderedRange
    margin_of_safety: OrderedRange
    expected_return: OrderedRange
    downside_risk: DimensionResult
    claim_ceiling: ClaimCeiling
    thesis_evidence: tuple[ThesisCondition, ...]
    counter_thesis_evidence: tuple[ThesisCondition, ...]
    invalidation_conditions: tuple[ThesisCondition, ...]
    risk_cap: RiskCapResult
    model_evidence_label: ModelEvidenceLabel
    model_version: str
    strategy_version: str
    formula_version: str
    aggregation_version: str
    risk_policy_version: str
    assumption_policy_version: str
    input_hash: str
    content_hash: str
    deterministic_ranking_authorized: bool = False
    final_portfolio_weight_authorized: bool = False
    automatic_brokerage_execution_authorized: bool = False


def evaluate_fundamental_value_v1(
    inputs: FundamentalValueInputsV1,
    *,
    model_evidence_label: ModelEvidenceLabel = ModelEvidenceLabel.NOT_VALIDATED,
) -> FundamentalValueAssessmentV1:
    with localcontext() as context:
        context.prec = 50
        context.rounding = ROUND_HALF_EVEN
        return _evaluate_fundamental_value_v1(inputs, model_evidence_label=model_evidence_label)


def _evaluate_fundamental_value_v1(
    inputs: FundamentalValueInputsV1,
    *,
    model_evidence_label: ModelEvidenceLabel,
) -> FundamentalValueAssessmentV1:
    if (
        inputs.company_type != CompanyType.MATURE_OPERATING_COMPANY
        or inputs.applicability != Applicability.APPLICABLE
    ):
        raise CoreViolation("Generic calculations require mature-company APPLICABLE routing")
    company_quality = _company_quality(inputs)
    financial_resilience = _financial_resilience(inputs)
    cash_flow_quality = _cash_flow_quality(inputs)
    capital_allocation_quality = _capital_allocation_quality(inputs)
    downside_risk = _downside_risk(inputs)
    claim_ceiling = _claim_ceiling(inputs)
    input_hash = _inputs_hash(inputs)

    valuations = (
        _fcff_dcf(inputs, claim_ceiling),
        _owner_earnings(inputs, claim_ceiling),
        _earnings_power(inputs, claim_ceiling),
        _comparable_cross_check(inputs, claim_ceiling),
    )
    fair_value = aggregate_valuations(valuations)
    margin_of_safety = _margin_of_safety(fair_value, inputs.reference_price)
    expected_return = _expected_return(inputs, fair_value)
    thesis, counter_thesis, invalidations = _thesis_conditions(
        inputs, company_quality, financial_resilience, margin_of_safety, downside_risk
    )
    risk_cap = _risk_cap(
        fair_value=fair_value,
        margin_of_safety=margin_of_safety,
        company_quality=company_quality,
        financial_resilience=financial_resilience,
        cash_flow_quality=cash_flow_quality,
        capital_allocation_quality=capital_allocation_quality,
        downside_risk=downside_risk,
        claim_ceiling=claim_ceiling,
        model_evidence_label=model_evidence_label,
    )
    assessment_without_hash = FundamentalValueAssessmentV1(
        company_type=inputs.company_type,
        applicability=inputs.applicability,
        reference_price=inputs.reference_price,
        currency=inputs.currency,
        projection_years=inputs.projection_years,
        company_quality=company_quality,
        financial_resilience=financial_resilience,
        earnings_and_cash_flow_quality=cash_flow_quality,
        capital_allocation_quality=capital_allocation_quality,
        valuations=valuations,
        fair_value=fair_value,
        margin_of_safety=margin_of_safety,
        expected_return=expected_return,
        downside_risk=downside_risk,
        claim_ceiling=claim_ceiling,
        thesis_evidence=thesis,
        counter_thesis_evidence=counter_thesis,
        invalidation_conditions=invalidations,
        risk_cap=risk_cap,
        model_evidence_label=model_evidence_label,
        model_version=MODEL_VERSION,
        strategy_version=STRATEGY_VERSION,
        formula_version=FORMULA_VERSION,
        aggregation_version=AGGREGATION_VERSION,
        risk_policy_version=RISK_CAP_VERSION,
        assumption_policy_version=ASSUMPTION_POLICY_VERSION,
        input_hash=input_hash,
        content_hash="",
    )
    return FundamentalValueAssessmentV1(
        **{
            **assessment_without_hash.__dict__,
            "content_hash": _assessment_hash(assessment_without_hash),
        }
    )


def aggregate_valuations(valuations: tuple[ValuationResult, ...]) -> OrderedRange:
    method_counts = {
        method: sum(item.method == method for item in valuations) for method in ValuationMethod
    }
    if (
        any(method_counts[method] != 1 for method in PRIMARY_METHODS)
        or method_counts[ValuationMethod.COMPARABLE_CROSS_CHECK] > 1
    ):
        return OrderedRange(
            state=DataState.INVALID,
            low=None,
            central=None,
            high=None,
            reason_codes=("VALUATION_METHOD_CARDINALITY_INVALID",),
        )
    if len(valuations) not in (3, 4):
        return OrderedRange(
            state=DataState.INVALID,
            low=None,
            central=None,
            high=None,
            reason_codes=("VALUATION_METHOD_SET_INVALID",),
        )
    valid = tuple(item for item in valuations if item.state == DataState.VALID)
    primary = tuple(item for item in valid if item.method in PRIMARY_METHODS)
    if len(primary) != len(PRIMARY_METHODS):
        primary_states = tuple(item.state for item in valuations if item.method in PRIMARY_METHODS)
        return OrderedRange(
            state=_state_precedence(primary_states),
            low=None,
            central=None,
            high=None,
            reason_codes=("ALL_THREE_PRIMARY_METHODS_REQUIRED",),
        )
    weighted_central = tuple((item.central, METHOD_WEIGHTS[item.method]) for item in valid)
    weighted_low = tuple((item.low, METHOD_WEIGHTS[item.method]) for item in valid)
    weighted_high = tuple((item.high, METHOD_WEIGHTS[item.method]) for item in valid)
    central = _weighted_quantile(weighted_central, Decimal("0.50"))
    low = _weighted_quantile(weighted_low, Decimal("0.25"))
    high = _weighted_quantile(weighted_high, Decimal("0.75"))
    if not low <= central <= high:
        raise CoreViolation("Aggregated fair-value range is not ordered")
    return OrderedRange(DataState.VALID, low, central, high, ())


def _company_quality(inputs: FundamentalValueInputsV1) -> DimensionResult:
    return _dimension(
        (
            (inputs.return_on_invested_capital, Decimal("-0.05"), Decimal("0.25"), False),
            (inputs.operating_margin, Decimal("-0.05"), Decimal("0.30"), False),
            (inputs.free_cash_flow_margin, Decimal("-0.10"), Decimal("0.25"), False),
            (inputs.earnings_stability, Decimal("0"), Decimal("1"), False),
            (inputs.cash_flow_stability, Decimal("0"), Decimal("1"), False),
        )
    )


def _financial_resilience(inputs: FundamentalValueInputsV1) -> DimensionResult:
    return _dimension(
        (
            (inputs.net_debt_to_ebitda, Decimal("-1"), Decimal("5"), True),
            (inputs.interest_coverage, Decimal("0"), Decimal("12"), False),
            (inputs.current_ratio, Decimal("0.5"), Decimal("2"), False),
            (inputs.diluted_share_growth, Decimal("-0.05"), Decimal("0.10"), True),
        )
    )


def _cash_flow_quality(inputs: FundamentalValueInputsV1) -> DimensionResult:
    return _dimension(
        (
            (inputs.cash_flow_to_net_income, Decimal("0.5"), Decimal("1.5"), False),
            (inputs.free_cash_flow_margin, Decimal("-0.10"), Decimal("0.25"), False),
            (inputs.cash_flow_stability, Decimal("0"), Decimal("1"), False),
            (inputs.diluted_share_growth, Decimal("-0.05"), Decimal("0.10"), True),
        )
    )


def _capital_allocation_quality(inputs: FundamentalValueInputsV1) -> DimensionResult:
    """Score price-independent, provider-neutral capital allocation evidence."""
    factors = (
        (
            inputs.incremental_return_on_invested_capital,
            Decimal("-0.05"),
            Decimal("0.20"),
            False,
        ),
        (inputs.acquisition_discipline, Decimal("0"), Decimal("1"), False),
        (inputs.shareholder_distribution_coverage, Decimal("0"), Decimal("1"), False),
    )
    propagated = _dimension(factors)
    if propagated.state != DataState.VALID:
        return propagated
    incremental = inputs.incremental_return_on_invested_capital.value
    acquisition = inputs.acquisition_discipline.value
    distribution = inputs.shareholder_distribution_coverage.value
    assert incremental is not None and acquisition is not None and distribution is not None
    if not Decimal("-1") < incremental <= Decimal("1"):
        return DimensionResult(
            DataState.INVALID, None, ("INCREMENTAL_ROIC_OUTSIDE_VALID_DOMAIN",)
        )
    if not Decimal("0") <= acquisition <= Decimal("1"):
        return DimensionResult(
            DataState.INVALID, None, ("ACQUISITION_DISCIPLINE_OUTSIDE_ZERO_TO_ONE",)
        )
    if not Decimal("0") <= distribution <= Decimal("1"):
        return DimensionResult(
            DataState.INVALID, None, ("DISTRIBUTION_COVERAGE_OUTSIDE_ZERO_TO_ONE",)
        )
    return propagated


def _downside_risk(inputs: FundamentalValueInputsV1) -> DimensionResult:
    resilience = _financial_resilience(inputs)
    risks = (inputs.cyclicality_risk, inputs.concentration_risk, inputs.event_risk)
    if resilience.state != DataState.VALID:
        return DimensionResult(resilience.state, None, resilience.reason_codes)
    invalid = tuple(
        item.reason_code or item.state.value for item in risks if item.state != DataState.VALID
    )
    if invalid:
        return DimensionResult(_derived_state(risks), None, invalid)
    assert resilience.score is not None
    values = [Decimal("100") - resilience.score]
    for item in risks:
        assert item.value is not None
        if item.value < 0 or item.value > 100:
            return DimensionResult(DataState.INVALID, None, ("RISK_SCORE_OUT_OF_RANGE",))
        values.append(item.value)
    return DimensionResult(DataState.VALID, _score(sum(values) / len(values)), ())


def _dimension(
    factors: tuple[tuple[MetricEvidence, Decimal, Decimal, bool], ...],
) -> DimensionResult:
    reasons = tuple(
        item.reason_code or item.state.value
        for item, _, _, _ in factors
        if item.state != DataState.VALID
    )
    if reasons:
        return DimensionResult(
            _derived_state(tuple(item for item, _, _, _ in factors)), None, reasons
        )
    scores: list[Decimal] = []
    for item, low, high, inverse in factors:
        assert item.value is not None
        score = _linear(item.value, low, high)
        scores.append(Decimal("100") - score if inverse else score)
    return DimensionResult(DataState.VALID, _score(sum(scores) / len(scores)), ())


def _fcff_dcf(inputs: FundamentalValueInputsV1, ceiling: ClaimCeiling) -> ValuationResult:
    if ceiling == ClaimCeiling.BLOCKED_MATERIAL_REFINANCING_UNCERTAINTY:
        return _blocked_valuation(ValuationMethod.FCFF_DCF, ceiling.value)
    required = (
        inputs.ebit,
        inputs.tax_rate,
        inputs.depreciation_and_amortization,
        inputs.capital_expenditures,
        inputs.change_in_working_capital,
        inputs.cash,
        inputs.debt,
        inputs.diluted_shares,
        inputs.conservative_growth_rate,
        inputs.discount_rate,
        inputs.terminal_growth_rate,
    )
    values, reasons = _valid_values(required)
    if reasons:
        return _nonvalid_valuation(ValuationMethod.FCFF_DCF, required, reasons)
    (
        ebit,
        tax_rate,
        depreciation,
        capex,
        change_nwc,
        cash,
        debt,
        shares,
        growth,
        discount,
        terminal_growth,
    ) = values
    if not Decimal("0") <= tax_rate <= Decimal("0.60") or shares <= 0:
        return _invalid_valuation(ValuationMethod.FCFF_DCF, "INVALID_TAX_OR_SHARE_INPUT")
    if any(value < 0 for value in (cash, debt, depreciation, capex)):
        return _invalid_valuation(ValuationMethod.FCFF_DCF, "INVALID_NONNEGATIVE_SIGN_INPUT")
    try:
        scenarios = (
            (
                growth - Decimal("0.02"),
                discount + Decimal("0.01"),
                terminal_growth - Decimal("0.005"),
            ),
            (growth, discount, terminal_growth),
            (
                growth + Decimal("0.02"),
                discount - Decimal("0.01"),
                terminal_growth + Decimal("0.005"),
            ),
        )
        _validate_dcf_scenarios(scenarios)
        fcff = ebit * (Decimal("1") - tax_rate) + depreciation - capex - change_nwc
        outputs_with_terminal_share = tuple(
            _dcf_per_share(
                fcff,
                g,
                rate,
                terminal,
                inputs.projection_years,
                cash,
                debt,
                shares,
            )
            for g, rate, terminal in scenarios
        )
    except (CoreViolation, DecimalException, OverflowError) as error:
        return _invalid_valuation(
            ValuationMethod.FCFF_DCF, _domain_failure_reason("FCFF_DCF", error)
        )
    try:
        outputs = tuple(item[0] for item in outputs_with_terminal_share)
        terminal_shares = tuple(item[1] for item in outputs_with_terminal_share)
        if max(terminal_shares) > MAXIMUM_DCF_TERMINAL_VALUE_SHARE:
            return _invalid_valuation(
                ValuationMethod.FCFF_DCF, "DCF_TERMINAL_VALUE_SHARE_EXCEEDS_POLICY"
            )
        return _ordered_valuation(
            ValuationMethod.FCFF_DCF,
            outputs,
            terminal_value_share=_rate(terminal_shares[1]),
        )
    except (CoreViolation, DecimalException, OverflowError) as error:
        return _invalid_valuation(
            ValuationMethod.FCFF_DCF, _domain_failure_reason("FCFF_DCF", error)
        )


def _owner_earnings(inputs: FundamentalValueInputsV1, ceiling: ClaimCeiling) -> ValuationResult:
    if ceiling == ClaimCeiling.BLOCKED_MATERIAL_REFINANCING_UNCERTAINTY:
        return _blocked_valuation(ValuationMethod.NORMALIZED_OWNER_EARNINGS, ceiling.value)
    required = (
        inputs.normalized_free_cash_flow,
        inputs.diluted_shares,
        inputs.conservative_growth_rate,
        inputs.discount_rate,
    )
    values, reasons = _valid_values(required)
    if reasons:
        return _nonvalid_valuation(ValuationMethod.NORMALIZED_OWNER_EARNINGS, required, reasons)
    fcf, shares, growth, discount = values
    try:
        scenarios = (
            (fcf * Decimal("0.90"), growth - Decimal("0.02"), discount + Decimal("0.01")),
            (fcf, growth, discount),
            (fcf * Decimal("1.10"), growth + Decimal("0.02"), discount - Decimal("0.01")),
        )
        outputs: list[Decimal] = []
        for normalized_fcf, scenario_growth, required_return in scenarios:
            if normalized_fcf <= 0 or shares <= 0:
                raise CoreViolation("OWNER_EARNINGS_REQUIRES_POSITIVE_FCF_AND_SHARES")
            if scenario_growth <= Decimal("-1"):
                raise CoreViolation("OWNER_EARNINGS_GROWTH_MUST_EXCEED_NEGATIVE_ONE")
            if required_return <= 0 or required_return <= scenario_growth:
                raise CoreViolation("OWNER_EARNINGS_REQUIRED_RETURN_NOT_ABOVE_GROWTH")
            equity = normalized_fcf * (Decimal("1") + scenario_growth) / (
                required_return - scenario_growth
            )
            outputs.append(equity / shares)
        return _ordered_valuation(ValuationMethod.NORMALIZED_OWNER_EARNINGS, tuple(outputs))
    except (CoreViolation, DecimalException, OverflowError) as error:
        return _invalid_valuation(
            ValuationMethod.NORMALIZED_OWNER_EARNINGS,
            _domain_failure_reason("OWNER_EARNINGS", error),
        )


def _earnings_power(inputs: FundamentalValueInputsV1, ceiling: ClaimCeiling) -> ValuationResult:
    if ceiling == ClaimCeiling.BLOCKED_MATERIAL_REFINANCING_UNCERTAINTY:
        return _blocked_valuation(ValuationMethod.EARNINGS_POWER, ceiling.value)
    required = (
        inputs.normalized_after_tax_operating_earnings,
        inputs.cash,
        inputs.debt,
        inputs.diluted_shares,
        inputs.discount_rate,
    )
    values, reasons = _valid_values(required)
    if reasons:
        return _nonvalid_valuation(ValuationMethod.EARNINGS_POWER, required, reasons)
    earnings, cash, debt, shares, discount = values
    if cash < 0 or debt < 0:
        return _invalid_valuation(ValuationMethod.EARNINGS_POWER, "INVALID_NONNEGATIVE_SIGN_INPUT")
    if earnings <= 0 or shares <= 0:
        return _invalid_valuation(ValuationMethod.EARNINGS_POWER, "INVALID_DISCOUNT_OR_SHARE_INPUT")
    try:
        scenarios = (
            (earnings * Decimal("0.90"), discount + Decimal("0.01")),
            (earnings, discount),
            (earnings * Decimal("1.10"), discount - Decimal("0.01")),
        )
        if any(rate <= 0 for _, rate in scenarios):
            raise CoreViolation("INVALID_DISCOUNT_OR_SHARE_INPUT")
        outputs = tuple(
            (scenario_earnings / rate + cash - debt) / shares
            for scenario_earnings, rate in scenarios
        )
        return _ordered_valuation(ValuationMethod.EARNINGS_POWER, outputs)
    except (CoreViolation, DecimalException, OverflowError) as error:
        return _invalid_valuation(
            ValuationMethod.EARNINGS_POWER, _domain_failure_reason("EARNINGS_POWER", error)
        )


def _comparable_cross_check(
    inputs: FundamentalValueInputsV1, ceiling: ClaimCeiling
) -> ValuationResult:
    if ceiling == ClaimCeiling.BLOCKED_MATERIAL_REFINANCING_UNCERTAINTY:
        return _blocked_valuation(ValuationMethod.COMPARABLE_CROSS_CHECK, ceiling.value)
    required = (
        inputs.ebitda,
        inputs.comparable_ev_to_ebitda,
        inputs.cash,
        inputs.debt,
        inputs.diluted_shares,
    )
    values, reasons = _valid_values(required)
    if reasons:
        return _nonvalid_valuation(ValuationMethod.COMPARABLE_CROSS_CHECK, required, reasons)
    ebitda, multiple, cash, debt, shares = values
    if cash < 0 or debt < 0:
        return _invalid_valuation(
            ValuationMethod.COMPARABLE_CROSS_CHECK, "INVALID_NONNEGATIVE_SIGN_INPUT"
        )
    if ebitda <= 0 or multiple <= 0 or shares <= 0:
        return _invalid_valuation(
            ValuationMethod.COMPARABLE_CROSS_CHECK, "INVALID_COMPARABLE_INPUT"
        )
    try:
        outputs = tuple(
            (ebitda * multiple * factor + cash - debt) / shares
            for factor in (Decimal("0.80"), Decimal("1"), Decimal("1.20"))
        )
        return _ordered_valuation(ValuationMethod.COMPARABLE_CROSS_CHECK, outputs)
    except (CoreViolation, DecimalException, OverflowError) as error:
        return _invalid_valuation(
            ValuationMethod.COMPARABLE_CROSS_CHECK,
            _domain_failure_reason("COMPARABLE", error),
        )


def _validate_dcf_scenarios(
    scenarios: tuple[tuple[Decimal, Decimal, Decimal], ...],
) -> None:
    for growth, discount, terminal_growth in scenarios:
        if growth <= Decimal("-1"):
            raise CoreViolation("DCF_GROWTH_MUST_EXCEED_NEGATIVE_ONE")
        if terminal_growth <= Decimal("-1"):
            raise CoreViolation("DCF_TERMINAL_GROWTH_MUST_EXCEED_NEGATIVE_ONE")
        if discount <= 0 or discount <= terminal_growth:
            raise CoreViolation("DCF_DISCOUNT_RATE_MUST_EXCEED_TERMINAL_GROWTH")


def _domain_failure_reason(method: str, error: BaseException) -> str:
    if isinstance(error, CoreViolation):
        return str(error)
    return f"{method}_DECIMAL_DOMAIN_INVALID"


def _dcf_per_share(
    initial_fcff: Decimal,
    growth: Decimal,
    discount: Decimal,
    terminal_growth: Decimal,
    years: int,
    cash: Decimal,
    debt: Decimal,
    shares: Decimal,
) -> tuple[Decimal, Decimal]:
    if initial_fcff <= 0 or shares <= 0:
        raise CoreViolation("DCF_REQUIRES_POSITIVE_FCFF_AND_SHARES")
    if growth <= Decimal("-1"):
        raise CoreViolation("DCF_GROWTH_MUST_EXCEED_NEGATIVE_ONE")
    if terminal_growth <= Decimal("-1"):
        raise CoreViolation("DCF_TERMINAL_GROWTH_MUST_EXCEED_NEGATIVE_ONE")
    if discount <= terminal_growth or discount <= 0:
        raise CoreViolation("DCF_DISCOUNT_RATE_MUST_EXCEED_TERMINAL_GROWTH")
    present_value = Decimal("0")
    cash_flow = initial_fcff
    for year in range(1, years + 1):
        cash_flow *= Decimal("1") + growth
        present_value += cash_flow / ((Decimal("1") + discount) ** year)
    terminal_value = cash_flow * (Decimal("1") + terminal_growth) / (discount - terminal_growth)
    discounted_terminal = terminal_value / ((Decimal("1") + discount) ** years)
    enterprise_value = present_value + discounted_terminal
    terminal_share = discounted_terminal / enterprise_value
    return (enterprise_value + cash - debt) / shares, terminal_share


def _margin_of_safety(fair_value: OrderedRange, price: MetricEvidence) -> OrderedRange:
    if fair_value.state != DataState.VALID:
        return OrderedRange(fair_value.state, None, None, None, fair_value.reason_codes)
    if price.state != DataState.VALID:
        return OrderedRange(
            price.state, None, None, None, (price.reason_code or price.state.value,)
        )
    assert price.value is not None
    if price.value <= 0:
        return OrderedRange(DataState.INVALID, None, None, None, ("REFERENCE_PRICE_NOT_POSITIVE",))
    assert (
        fair_value.low is not None
        and fair_value.central is not None
        and fair_value.high is not None
    )
    try:
        return OrderedRange(
            DataState.VALID,
            _rate(fair_value.low / price.value - Decimal("1")),
            _rate(fair_value.central / price.value - Decimal("1")),
            _rate(fair_value.high / price.value - Decimal("1")),
            (),
        )
    except (CoreViolation, DecimalException, OverflowError) as error:
        return OrderedRange(
            DataState.INVALID,
            None,
            None,
            None,
            (_domain_failure_reason("MARGIN_OF_SAFETY", error),),
        )


def _expected_return(inputs: FundamentalValueInputsV1, fair_value: OrderedRange) -> OrderedRange:
    required = (
        inputs.reference_price,
        inputs.conservative_growth_rate,
        inputs.net_distribution_yield,
    )
    values, reasons = _valid_values(required)
    if reasons or fair_value.state != DataState.VALID:
        return OrderedRange(
            _state_precedence(tuple(item.state for item in required) + (fair_value.state,)),
            None,
            None,
            None,
            tuple(reasons) + fair_value.reason_codes,
        )
    price, growth, distributions = values
    if price <= 0:
        return OrderedRange(DataState.INVALID, None, None, None, ("REFERENCE_PRICE_NOT_POSITIVE",))
    if not Decimal("-0.20") <= growth <= Decimal("0.20"):
        return OrderedRange(
            DataState.INVALID,
            None,
            None,
            None,
            ("EXPECTED_RETURN_GROWTH_OUT_OF_RANGE",),
        )
    if not Decimal("0") <= distributions <= Decimal("0.25"):
        return OrderedRange(
            DataState.INVALID,
            None,
            None,
            None,
            ("NET_DISTRIBUTION_YIELD_OUT_OF_RANGE",),
        )
    assert (
        fair_value.low is not None
        and fair_value.central is not None
        and fair_value.high is not None
    )
    estimates: list[Decimal] = []
    try:
        scenarios = (
            (fair_value.low, growth - Decimal("0.02")),
            (fair_value.central, growth),
            (fair_value.high, growth + Decimal("0.02")),
        )
        annual_distribution = price * distributions
        for target, scenario_growth in scenarios:
            if target is None or target <= 0 or scenario_growth <= Decimal("-1"):
                raise CoreViolation("EXPECTED_RETURN_SCENARIO_INVALID")
            terminal = target * ((Decimal("1") + scenario_growth) ** inputs.projection_years)
            cash_flows = [-price]
            cash_flows.extend(annual_distribution for _ in range(inputs.projection_years - 1))
            cash_flows.append(annual_distribution + terminal)
            estimates.append(_irr(tuple(cash_flows)))
    except (CoreViolation, DecimalException, OverflowError) as error:
        return OrderedRange(
            DataState.INVALID,
            None,
            None,
            None,
            (_domain_failure_reason("EXPECTED_RETURN", error),),
        )
    try:
        low, central, high = tuple(_rate(value) for value in estimates)
    except (DecimalException, OverflowError) as error:
        return OrderedRange(
            DataState.INVALID,
            None,
            None,
            None,
            (_domain_failure_reason("EXPECTED_RETURN", error),),
        )
    if not low <= central <= high:
        return OrderedRange(
            DataState.INVALID,
            None,
            None,
            None,
            ("EXPECTED_RETURN_RANGE_NOT_ORDERED",),
        )
    return OrderedRange(DataState.VALID, low, central, high, ())


def _claim_ceiling(inputs: FundamentalValueInputsV1) -> ClaimCeiling:
    if inputs.debt_maturity_schedule.state == DataState.VALID:
        return ClaimCeiling.FULL_CURRENT_DECISION
    leverage = inputs.net_debt_to_ebitda
    coverage = inputs.interest_coverage
    debt = inputs.debt
    material = (
        debt.state != DataState.VALID
        or leverage.state != DataState.VALID
        or coverage.state != DataState.VALID
    )
    if not material:
        assert debt.value is not None
        assert leverage.value is not None
        assert coverage.value is not None
        material = debt.value > 0 and (
            leverage.value > Decimal("1") or coverage.value < Decimal("8")
        )
        if debt.value > 0 and inputs.debt_maturity_schedule.state in {
            DataState.INVALID,
            DataState.STALE,
        }:
            material = True
    if material:
        return ClaimCeiling.BLOCKED_MATERIAL_REFINANCING_UNCERTAINTY
    return ClaimCeiling.LIMITED_MISSING_ADVANCED_EVIDENCE


def _thesis_conditions(
    inputs: FundamentalValueInputsV1,
    quality: DimensionResult,
    resilience: DimensionResult,
    margin: OrderedRange,
    downside: DimensionResult,
) -> tuple[tuple[ThesisCondition, ...], tuple[ThesisCondition, ...], tuple[ThesisCondition, ...]]:
    thesis = (
        _condition("QUALITY_AT_LEAST_65", quality, Decimal("65"), greater=True),
        _condition("RESILIENCE_AT_LEAST_60", resilience, Decimal("60"), greater=True),
        _range_condition(
            "CONSERVATIVE_MARGIN_OF_SAFETY_AT_LEAST_15_PERCENT",
            margin,
            Decimal("0.15"),
            greater=True,
        ),
    )
    counter = (
        _condition("DOWNSIDE_RISK_AT_LEAST_60", downside, Decimal("60"), greater=True),
        _metric_condition(
            "NET_DEBT_TO_EBITDA_ABOVE_3", inputs.net_debt_to_ebitda, Decimal("3"), greater=True
        ),
    )
    invalidations = (
        _metric_condition(
            "ROIC_BELOW_8_PERCENT",
            inputs.return_on_invested_capital,
            Decimal("0.08"),
            greater=False,
        ),
        _metric_condition(
            "INTEREST_COVERAGE_BELOW_3", inputs.interest_coverage, Decimal("3"), greater=False
        ),
        _range_condition(
            "CENTRAL_MARGIN_OF_SAFETY_BELOW_ZERO",
            margin,
            Decimal("0"),
            greater=False,
            use_central=True,
        ),
    )
    return thesis, counter, invalidations


def _condition(
    code: str, result: DimensionResult, threshold: Decimal, *, greater: bool
) -> ThesisCondition:
    if result.state != DataState.VALID:
        return ThesisCondition(code, result.state, None, threshold, None, result.reason_codes)
    assert result.score is not None
    satisfied = result.score >= threshold if greater else result.score < threshold
    return ThesisCondition(code, DataState.VALID, result.score, threshold, satisfied, ())


def _range_condition(
    code: str,
    result: OrderedRange,
    threshold: Decimal,
    *,
    greater: bool,
    use_central: bool = False,
) -> ThesisCondition:
    if result.state != DataState.VALID:
        return ThesisCondition(code, result.state, None, threshold, None, result.reason_codes)
    value = result.central if use_central else result.low
    assert value is not None
    satisfied = value >= threshold if greater else value < threshold
    return ThesisCondition(code, DataState.VALID, value, threshold, satisfied, ())


def _metric_condition(
    code: str, evidence: MetricEvidence, threshold: Decimal, *, greater: bool
) -> ThesisCondition:
    if evidence.state != DataState.VALID:
        return ThesisCondition(
            code,
            evidence.state,
            None,
            threshold,
            None,
            (evidence.reason_code or evidence.state.value,),
        )
    assert evidence.value is not None
    satisfied = evidence.value > threshold if greater else evidence.value < threshold
    return ThesisCondition(code, DataState.VALID, evidence.value, threshold, satisfied, ())


def _risk_cap(
    *,
    fair_value: OrderedRange,
    margin_of_safety: OrderedRange,
    company_quality: DimensionResult,
    financial_resilience: DimensionResult,
    cash_flow_quality: DimensionResult,
    capital_allocation_quality: DimensionResult,
    downside_risk: DimensionResult,
    claim_ceiling: ClaimCeiling,
    model_evidence_label: ModelEvidenceLabel,
) -> RiskCapResult:
    if (
        fair_value.state != DataState.VALID
        or claim_ceiling == ClaimCeiling.BLOCKED_MATERIAL_REFINANCING_UNCERTAINTY
    ):
        return RiskCapResult(Decimal("0"), ("VALUATION_NOT_USABLE", claim_ceiling.value))
    results = (
        company_quality,
        financial_resilience,
        cash_flow_quality,
        capital_allocation_quality,
        downside_risk,
    )
    if (
        any(item.state != DataState.VALID for item in results)
        or margin_of_safety.state != DataState.VALID
    ):
        return RiskCapResult(Decimal("0"), ("REQUIRED_RISK_EVIDENCE_NOT_VALID",))
    assert company_quality.score is not None
    assert financial_resilience.score is not None
    assert cash_flow_quality.score is not None
    assert capital_allocation_quality.score is not None
    assert downside_risk.score is not None
    assert margin_of_safety.low is not None
    if downside_risk.score >= 75 or financial_resilience.score < 35:
        base = Decimal("0")
        reasons = ("HIGH_DOWNSIDE_OR_LOW_RESILIENCE",)
    elif downside_risk.score >= 60 or company_quality.score < 50:
        base = Decimal("0.01")
        reasons = ("ELEVATED_RISK_OR_WEAK_QUALITY",)
    elif downside_risk.score >= 45 or margin_of_safety.low < 0:
        base = Decimal("0.02")
        reasons = ("MODERATE_RISK_OR_NEGATIVE_CONSERVATIVE_MARGIN",)
    elif downside_risk.score >= 30 or margin_of_safety.low < Decimal("0.15"):
        base = Decimal("0.03")
        reasons = ("LIMITED_CONSERVATIVE_MARGIN",)
    else:
        base = Decimal("0.05")
        reasons = ("FULL_ECONOMIC_CAP_ELIGIBLE",)
    if cash_flow_quality.score < 40:
        base = min(base, Decimal("0.01"))
        reasons += ("WEAK_EARNINGS_AND_CASH_FLOW_QUALITY",)
    elif cash_flow_quality.score < 55:
        base = min(base, Decimal("0.02"))
        reasons += ("LIMITED_EARNINGS_AND_CASH_FLOW_QUALITY",)
    elif cash_flow_quality.score < 70:
        base = min(base, Decimal("0.03"))
        reasons += ("MODERATE_EARNINGS_AND_CASH_FLOW_QUALITY",)
    if capital_allocation_quality.score < 40:
        base = min(base, Decimal("0.01"))
        reasons += ("WEAK_CAPITAL_ALLOCATION_QUALITY",)
    elif capital_allocation_quality.score < 55:
        base = min(base, Decimal("0.02"))
        reasons += ("LIMITED_CAPITAL_ALLOCATION_QUALITY",)
    elif capital_allocation_quality.score < 70:
        base = min(base, Decimal("0.03"))
        reasons += ("MODERATE_CAPITAL_ALLOCATION_QUALITY",)
    evidence_maximum = {
        ModelEvidenceLabel.NOT_VALIDATED: Decimal("0.02"),
        ModelEvidenceLabel.DEVELOPMENT_OBSERVED: Decimal("0.02"),
        ModelEvidenceLabel.BACKTEST_SUPPORTED: Decimal("0.03"),
        ModelEvidenceLabel.PIT_SUPPORTED: Decimal("0.03"),
        ModelEvidenceLabel.FORWARD_SUPPORTED: Decimal("0.05"),
    }[model_evidence_label]
    if claim_ceiling == ClaimCeiling.LIMITED_MISSING_ADVANCED_EVIDENCE:
        evidence_maximum = min(evidence_maximum, Decimal("0.01"))
        reasons += ("MISSING_ADVANCED_EVIDENCE",)
    ceiling = min(base, evidence_maximum)
    if ceiling < base:
        reasons += ("MODEL_EVIDENCE_CEILING",)
    if ceiling not in ALLOWED_RISK_CAPS:
        raise CoreViolation("Risk cap escaped the frozen discrete tiers")
    return RiskCapResult(ceiling, reasons)


def _weighted_quantile(
    values: tuple[tuple[Decimal | None, Decimal], ...], quantile: Decimal
) -> Decimal:
    usable = sorted((value, weight) for value, weight in values if value is not None)
    if not usable:
        raise CoreViolation("Weighted quantile requires values")
    total = sum((weight for _, weight in usable), Decimal("0"))
    threshold = total * quantile
    cumulative = Decimal("0")
    for value, weight in usable:
        cumulative += weight
        if cumulative >= threshold:
            return _money(value)
    return _money(usable[-1][0])


def _valid_values(
    evidence: tuple[MetricEvidence, ...],
) -> tuple[tuple[Decimal, ...], tuple[str, ...]]:
    reasons = tuple(
        item.reason_code or item.state.value for item in evidence if item.state != DataState.VALID
    )
    if reasons:
        return (), reasons
    values: list[Decimal] = []
    for item in evidence:
        assert item.value is not None
        values.append(item.value)
    return tuple(values), ()


def _ordered_valuation(
    method: ValuationMethod,
    values: tuple[Decimal, ...],
    *,
    terminal_value_share: Decimal | None = None,
) -> ValuationResult:
    ordered = tuple(_money(value) for value in values)
    if len(ordered) != 3 or ordered[0] <= 0:
        return _invalid_valuation(method, "VALUATION_RANGE_NOT_POSITIVE")
    if not ordered[0] <= ordered[1] <= ordered[2]:
        return _invalid_valuation(method, "VALUATION_RANGE_NOT_ORDERED")
    return ValuationResult(
        method,
        DataState.VALID,
        ordered[0],
        ordered[1],
        ordered[2],
        (),
        terminal_value_share,
    )


def _nonvalid_valuation(
    method: ValuationMethod,
    evidence: tuple[MetricEvidence, ...],
    reasons: tuple[str, ...],
) -> ValuationResult:
    return ValuationResult(method, _derived_state(evidence), None, None, None, reasons)


def _invalid_valuation(method: ValuationMethod, reason: str) -> ValuationResult:
    return ValuationResult(method, DataState.INVALID, None, None, None, (reason,))


def _blocked_valuation(method: ValuationMethod, reason: str) -> ValuationResult:
    return ValuationResult(method, DataState.EXCLUDED, None, None, None, (reason,))


def _linear(value: Decimal, low: Decimal, high: Decimal) -> Decimal:
    clipped = min(max(value, low), high)
    return _score((clipped - low) / (high - low) * Decimal("100"))


def _score(value: Decimal) -> Decimal:
    return value.quantize(SCORE_QUANTUM, rounding=ROUND_HALF_EVEN)


def _rate(value: Decimal) -> Decimal:
    return value.quantize(RATE_QUANTUM, rounding=ROUND_HALF_EVEN)


def _money(value: Decimal) -> Decimal:
    return value.quantize(VALUE_QUANTUM, rounding=ROUND_HALF_EVEN)


def _derived_state(evidence: tuple[MetricEvidence, ...]) -> DataState:
    return _state_precedence(tuple(item.state for item in evidence))


def _state_precedence(states: tuple[DataState, ...]) -> DataState:
    precedence = (
        DataState.INVALID,
        DataState.STALE,
        DataState.MISSING,
        DataState.EXCLUDED,
        DataState.NOT_APPLICABLE,
    )
    state_set = set(states)
    return next((state for state in precedence if state in state_set), DataState.VALID)


def _irr(cash_flows: tuple[Decimal, ...]) -> Decimal:
    if not cash_flows or cash_flows[0] >= 0 or cash_flows[-1] <= 0:
        raise CoreViolation("IRR_REQUIRES_INITIAL_OUTFLOW_AND_FINAL_INFLOW")
    with localcontext() as context:
        context.prec = 50
        low = Decimal("-0.99")
        high = Decimal("2")

        def npv(rate: Decimal) -> Decimal:
            return sum(
                (cash_flow / ((Decimal("1") + rate) ** period))
                for period, cash_flow in enumerate(cash_flows)
            )

        if npv(low) < 0 or npv(high) > 0:
            raise CoreViolation("IRR_OUTSIDE_FROZEN_SEARCH_RANGE")
        for _ in range(200):
            midpoint = (low + high) / Decimal("2")
            if npv(midpoint) > 0:
                low = midpoint
            else:
                high = midpoint
        return (low + high) / Decimal("2")


def _assessment_hash(assessment: FundamentalValueAssessmentV1) -> str:
    def canonical(value):
        if isinstance(value, Decimal):
            return canonical_decimal_text(value)
        if isinstance(value, StrEnum):
            return value.value
        if hasattr(value, "__dataclass_fields__"):
            return {
                key: canonical(item)
                for key, item in value.__dict__.items()
                if key != "content_hash"
            }
        if isinstance(value, tuple):
            return [canonical(item) for item in value]
        return value

    payload = canonical(assessment)
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _inputs_hash(inputs: FundamentalValueInputsV1) -> str:
    def canonical(value):
        if isinstance(value, Decimal):
            return canonical_decimal_text(value)
        if isinstance(value, StrEnum):
            return value.value
        if hasattr(value, "__dataclass_fields__"):
            return {key: canonical(item) for key, item in value.__dict__.items()}
        return value

    encoded = json.dumps(
        canonical(inputs), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"
