from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_HALF_EVEN, Decimal
from enum import StrEnum

LONG_HORIZON_V11_VERSION = "LONG-HORIZON-RESEARCH-v1.1.0"

_SCORE_QUANTUM = Decimal("0.01")
_RATE_QUANTUM = Decimal("0.0001")
_ZERO = Decimal("0")
_ONE = Decimal("1")
_HUNDRED = Decimal("100")


class CompanyModelV11(StrEnum):
    GENERAL = "GENERAL"
    BANK = "BANK"
    INSURANCE = "INSURANCE"
    REIT = "REIT"
    RESOURCE = "RESOURCE"
    BIOTECH = "BIOTECH"
    RECENT_IPO = "RECENT_IPO"


class InputState(StrEnum):
    VALID = "VALID"
    MISSING = "MISSING"
    INVALID = "INVALID"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class DimensionState(StrEnum):
    VALID = "VALID"
    MISSING = "MISSING"
    INVALID = "INVALID"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    COHORT_INSUFFICIENT = "COHORT_INSUFFICIENT"
    SPECIALIZED_MODEL_REQUIRED = "SPECIALIZED_MODEL_REQUIRED"


class AssessmentStatus(StrEnum):
    ASSESSED = "ASSESSED"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    INVALID_DATA = "INVALID_DATA"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    COHORT_INSUFFICIENT = "COHORT_INSUFFICIENT"
    SPECIALIZED_MODEL_REQUIRED = "SPECIALIZED_MODEL_REQUIRED"
    INSUFFICIENT_PUBLIC_HISTORY = "INSUFFICIENT_PUBLIC_HISTORY"


class ResearchClassification(StrEnum):
    QUALITY_AT_REASONABLE_PRICE = "QUALITY_AT_REASONABLE_PRICE"
    GOOD_COMPANY_EXPENSIVE = "GOOD_COMPANY_EXPENSIVE"
    CHEAP_BUT_FRAGILE = "CHEAP_BUT_FRAGILE"
    ATTRACTIVE_FOR_FURTHER_RESEARCH = "ATTRACTIVE_FOR_FURTHER_RESEARCH"
    SELECTIVE_RESEARCH = "SELECTIVE_RESEARCH"
    HIGH_PERMANENT_LOSS_RISK = "HIGH_PERMANENT_LOSS_RISK"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    COHORT_INSUFFICIENT = "COHORT_INSUFFICIENT"
    SPECIALIZED_MODEL_REQUIRED = "SPECIALIZED_MODEL_REQUIRED"
    SPECULATIVE_RESEARCH_ONLY = "SPECULATIVE_RESEARCH_ONLY"


@dataclass(frozen=True)
class MetricEvidence:
    state: InputState
    value: Decimal | None = None

    def __post_init__(self) -> None:
        if self.state == InputState.VALID:
            if self.value is None or not self.value.is_finite():
                raise ValueError("VALID metric evidence requires a finite value")
        elif self.value is not None:
            raise ValueError("Non-VALID metric evidence cannot carry a value")

    @classmethod
    def valid(cls, value: Decimal | str) -> MetricEvidence:
        return cls(state=InputState.VALID, value=Decimal(value))

    @classmethod
    def missing(cls) -> MetricEvidence:
        return cls(state=InputState.MISSING)

    @classmethod
    def invalid(cls) -> MetricEvidence:
        return cls(state=InputState.INVALID)

    @classmethod
    def not_applicable(cls) -> MetricEvidence:
        return cls(state=InputState.NOT_APPLICABLE)


def _missing_metric() -> MetricEvidence:
    return MetricEvidence.missing()


@dataclass(frozen=True)
class LongHorizonV11Inputs:
    symbol: str
    company_model: CompanyModelV11

    # Business quality.
    return_on_invested_capital: MetricEvidence = field(default_factory=_missing_metric)
    operating_margin: MetricEvidence = field(default_factory=_missing_metric)
    free_cash_flow_margin: MetricEvidence = field(default_factory=_missing_metric)
    earnings_stability: MetricEvidence = field(default_factory=_missing_metric)
    cash_flow_stability: MetricEvidence = field(default_factory=_missing_metric)

    # Financial strength.
    net_debt_to_ebitda: MetricEvidence = field(default_factory=_missing_metric)
    interest_coverage: MetricEvidence = field(default_factory=_missing_metric)
    current_ratio: MetricEvidence = field(default_factory=_missing_metric)
    diluted_share_growth: MetricEvidence = field(default_factory=_missing_metric)

    # Capital allocation.
    incremental_return_on_invested_capital: MetricEvidence = field(default_factory=_missing_metric)
    reinvestment_efficiency: MetricEvidence = field(default_factory=_missing_metric)
    shareholder_yield: MetricEvidence = field(default_factory=_missing_metric)
    acquisition_discipline: MetricEvidence = field(default_factory=_missing_metric)

    # Valuation and expected-return components.
    free_cash_flow_yield: MetricEvidence = field(default_factory=_missing_metric)
    earnings_yield: MetricEvidence = field(default_factory=_missing_metric)
    enterprise_value_to_ebitda: MetricEvidence = field(default_factory=_missing_metric)
    own_history_valuation_attractiveness: MetricEvidence = field(default_factory=_missing_metric)
    conservative_fundamental_growth: MetricEvidence = field(default_factory=_missing_metric)
    annualized_valuation_normalization: MetricEvidence = field(default_factory=_missing_metric)

    # Permanent-loss and downside-risk context. Scores use 0 = low, 100 = high.
    cyclicality_risk: MetricEvidence = field(default_factory=_missing_metric)
    concentration_risk: MetricEvidence = field(default_factory=_missing_metric)
    event_risk: MetricEvidence = field(default_factory=_missing_metric)

    # Sector-relative evidence. Percentiles use 0 = weak, 1 = strong/attractive.
    peer_quality_percentile: MetricEvidence = field(default_factory=_missing_metric)
    peer_valuation_attractiveness_percentile: MetricEvidence = field(
        default_factory=_missing_metric
    )
    peer_cohort_member_count: int | None = None
    peer_cohort_minimum_count: int = 20

    # Epistemic confidence remains separate from all economic scores.
    evidence_coverage_ratio: MetricEvidence = field(default_factory=_missing_metric)
    point_in_time_verified_ratio: MetricEvidence = field(default_factory=_missing_metric)
    revision_lineage_ratio: MetricEvidence = field(default_factory=_missing_metric)
    semantic_evidence_ratio: MetricEvidence = field(default_factory=_missing_metric)

    def __post_init__(self) -> None:
        if not self.symbol.strip():
            raise ValueError("Symbol is required")
        if self.peer_cohort_member_count is not None:
            if self.peer_cohort_member_count < 0:
                raise ValueError("Peer cohort member count cannot be negative")
        if self.peer_cohort_minimum_count < 1:
            raise ValueError("Peer cohort minimum count must be positive")


@dataclass(frozen=True)
class FactorScore:
    name: str
    state: InputState
    normalized_score: Decimal | None


@dataclass(frozen=True)
class DimensionAssessment:
    code: str
    state: DimensionState
    score: Decimal | None
    factors: tuple[FactorScore, ...]
    missing_fields: tuple[str, ...] = ()
    invalid_fields: tuple[str, ...] = ()
    not_applicable_fields: tuple[str, ...] = ()


@dataclass(frozen=True)
class ExpectedReturnRange:
    state: DimensionState
    low: Decimal | None
    base: Decimal | None
    high: Decimal | None
    component_names: tuple[str, ...]
    missing_fields: tuple[str, ...] = ()
    invalid_fields: tuple[str, ...] = ()


@dataclass(frozen=True)
class SectorRelativeAssessment:
    state: DimensionState
    score: Decimal | None
    quality_percentile_score: Decimal | None
    valuation_attractiveness_percentile_score: Decimal | None
    cohort_member_count: int | None
    cohort_minimum_count: int
    missing_fields: tuple[str, ...] = ()
    invalid_fields: tuple[str, ...] = ()


@dataclass(frozen=True)
class EvidenceConfidenceAssessment:
    state: DimensionState
    score: Decimal | None
    components: tuple[FactorScore, ...]
    missing_fields: tuple[str, ...] = ()
    invalid_fields: tuple[str, ...] = ()


@dataclass(frozen=True)
class LongHorizonV11Assessment:
    version: str
    status: AssessmentStatus
    classification: ResearchClassification
    business_quality: DimensionAssessment
    financial_strength: DimensionAssessment
    capital_allocation: DimensionAssessment
    valuation_entry: DimensionAssessment
    expected_return: ExpectedReturnRange
    downside_risk: DimensionAssessment
    sector_relative: SectorRelativeAssessment
    evidence_confidence: EvidenceConfidenceAssessment
    default_ranking_score: None
    deterministic_ranking_authorized: bool
    missing_fields: tuple[str, ...]
    invalid_fields: tuple[str, ...]
    limitations: tuple[str, ...]


@dataclass(frozen=True)
class _FactorDefinition:
    name: str
    evidence: MetricEvidence
    low: Decimal
    high: Decimal
    inverse: bool = False
    bounded_ratio: bool = False
    bounded_score: bool = False


def _clip(value: Decimal, low: Decimal, high: Decimal) -> Decimal:
    return min(high, max(low, value))


def _score_quantize(value: Decimal) -> Decimal:
    return value.quantize(_SCORE_QUANTUM, rounding=ROUND_HALF_EVEN)


def _rate_quantize(value: Decimal) -> Decimal:
    return value.quantize(_RATE_QUANTUM, rounding=ROUND_HALF_EVEN)


def _linear(value: Decimal, low: Decimal, high: Decimal) -> Decimal:
    if high <= low:
        raise ValueError("Scoring range must be increasing")
    score = _HUNDRED * (value - low) / (high - low)
    return _score_quantize(_clip(score, _ZERO, _HUNDRED))


def _factor_score(item: _FactorDefinition) -> FactorScore:
    evidence = item.evidence
    if evidence.state != InputState.VALID:
        return FactorScore(item.name, evidence.state, None)
    assert evidence.value is not None
    if item.bounded_ratio and not _ZERO <= evidence.value <= _ONE:
        return FactorScore(item.name, InputState.INVALID, None)
    if item.bounded_score and not _ZERO <= evidence.value <= _HUNDRED:
        return FactorScore(item.name, InputState.INVALID, None)
    score = (
        _score_quantize(evidence.value)
        if item.bounded_score
        else _linear(evidence.value, item.low, item.high)
    )
    if item.inverse:
        score = _score_quantize(_HUNDRED - score)
    return FactorScore(item.name, InputState.VALID, score)


def _dimension(
    code: str,
    definitions: tuple[_FactorDefinition, ...],
    *,
    higher_is_better: bool = True,
) -> DimensionAssessment:
    factors = tuple(_factor_score(item) for item in definitions)
    missing = tuple(item.name for item in factors if item.state == InputState.MISSING)
    invalid = tuple(item.name for item in factors if item.state == InputState.INVALID)
    not_applicable = tuple(item.name for item in factors if item.state == InputState.NOT_APPLICABLE)
    if invalid:
        state = DimensionState.INVALID
    elif missing:
        state = DimensionState.MISSING
    elif not_applicable:
        state = DimensionState.NOT_APPLICABLE
    else:
        state = DimensionState.VALID
    score = None
    if state == DimensionState.VALID:
        normalized = tuple(
            item.normalized_score for item in factors if item.normalized_score is not None
        )
        score = _score_quantize(sum(normalized, _ZERO) / Decimal(len(normalized)))
        if not higher_is_better:
            # Risk dimensions are intentionally reported as 0 = low, 100 = high.
            score = _score_quantize(_HUNDRED - score)
    return DimensionAssessment(
        code=code,
        state=state,
        score=score,
        factors=factors,
        missing_fields=missing,
        invalid_fields=invalid,
        not_applicable_fields=not_applicable,
    )


def _business_quality(inputs: LongHorizonV11Inputs) -> DimensionAssessment:
    return _dimension(
        "BUSINESS_QUALITY",
        (
            _FactorDefinition(
                "return_on_invested_capital",
                inputs.return_on_invested_capital,
                Decimal("-0.05"),
                Decimal("0.25"),
            ),
            _FactorDefinition(
                "operating_margin",
                inputs.operating_margin,
                Decimal("-0.05"),
                Decimal("0.30"),
            ),
            _FactorDefinition(
                "free_cash_flow_margin",
                inputs.free_cash_flow_margin,
                Decimal("-0.10"),
                Decimal("0.25"),
            ),
            _FactorDefinition(
                "earnings_stability",
                inputs.earnings_stability,
                _ZERO,
                _ONE,
                bounded_ratio=True,
            ),
            _FactorDefinition(
                "cash_flow_stability",
                inputs.cash_flow_stability,
                _ZERO,
                _ONE,
                bounded_ratio=True,
            ),
        ),
    )


def _financial_strength(inputs: LongHorizonV11Inputs) -> DimensionAssessment:
    return _dimension(
        "FINANCIAL_STRENGTH",
        (
            _FactorDefinition(
                "net_debt_to_ebitda",
                inputs.net_debt_to_ebitda,
                Decimal("-1"),
                Decimal("5"),
                inverse=True,
            ),
            _FactorDefinition(
                "interest_coverage",
                inputs.interest_coverage,
                _ZERO,
                Decimal("12"),
            ),
            _FactorDefinition(
                "current_ratio",
                inputs.current_ratio,
                Decimal("0.50"),
                Decimal("2"),
            ),
            _FactorDefinition(
                "diluted_share_growth",
                inputs.diluted_share_growth,
                Decimal("-0.05"),
                Decimal("0.10"),
                inverse=True,
            ),
        ),
    )


def _capital_allocation(inputs: LongHorizonV11Inputs) -> DimensionAssessment:
    return _dimension(
        "CAPITAL_ALLOCATION",
        (
            _FactorDefinition(
                "incremental_return_on_invested_capital",
                inputs.incremental_return_on_invested_capital,
                Decimal("-0.05"),
                Decimal("0.25"),
            ),
            _FactorDefinition(
                "reinvestment_efficiency",
                inputs.reinvestment_efficiency,
                _ZERO,
                _ONE,
                bounded_ratio=True,
            ),
            _FactorDefinition(
                "shareholder_yield",
                inputs.shareholder_yield,
                Decimal("-0.10"),
                Decimal("0.10"),
            ),
            _FactorDefinition(
                "acquisition_discipline",
                inputs.acquisition_discipline,
                _ZERO,
                _HUNDRED,
                bounded_score=True,
            ),
        ),
    )


def _valuation_entry(inputs: LongHorizonV11Inputs) -> DimensionAssessment:
    return _dimension(
        "VALUATION_ENTRY",
        (
            _FactorDefinition(
                "free_cash_flow_yield",
                inputs.free_cash_flow_yield,
                _ZERO,
                Decimal("0.12"),
            ),
            _FactorDefinition(
                "earnings_yield",
                inputs.earnings_yield,
                _ZERO,
                Decimal("0.12"),
            ),
            _FactorDefinition(
                "enterprise_value_to_ebitda",
                inputs.enterprise_value_to_ebitda,
                Decimal("5"),
                Decimal("30"),
                inverse=True,
            ),
            _FactorDefinition(
                "own_history_valuation_attractiveness",
                inputs.own_history_valuation_attractiveness,
                _ZERO,
                _ONE,
                bounded_ratio=True,
            ),
        ),
    )


def _downside_risk(inputs: LongHorizonV11Inputs) -> DimensionAssessment:
    return _dimension(
        "PERMANENT_LOSS_AND_DOWNSIDE_RISK",
        (
            _FactorDefinition(
                "net_debt_to_ebitda",
                inputs.net_debt_to_ebitda,
                Decimal("-1"),
                Decimal("5"),
                inverse=True,
            ),
            _FactorDefinition(
                "interest_coverage",
                inputs.interest_coverage,
                _ZERO,
                Decimal("12"),
            ),
            _FactorDefinition(
                "earnings_stability",
                inputs.earnings_stability,
                _ZERO,
                _ONE,
                bounded_ratio=True,
            ),
            _FactorDefinition(
                "cash_flow_stability",
                inputs.cash_flow_stability,
                _ZERO,
                _ONE,
                bounded_ratio=True,
            ),
            _FactorDefinition(
                "diluted_share_growth",
                inputs.diluted_share_growth,
                Decimal("-0.05"),
                Decimal("0.10"),
                inverse=True,
            ),
            _FactorDefinition(
                "cyclicality_risk",
                inputs.cyclicality_risk,
                _ZERO,
                _HUNDRED,
                inverse=True,
                bounded_score=True,
            ),
            _FactorDefinition(
                "concentration_risk",
                inputs.concentration_risk,
                _ZERO,
                _HUNDRED,
                inverse=True,
                bounded_score=True,
            ),
            _FactorDefinition(
                "event_risk",
                inputs.event_risk,
                _ZERO,
                _HUNDRED,
                inverse=True,
                bounded_score=True,
            ),
        ),
        higher_is_better=False,
    )


def _sector_relative(
    inputs: LongHorizonV11Inputs,
) -> SectorRelativeAssessment:
    definitions = (
        _FactorDefinition(
            "peer_quality_percentile",
            inputs.peer_quality_percentile,
            _ZERO,
            _ONE,
            bounded_ratio=True,
        ),
        _FactorDefinition(
            "peer_valuation_attractiveness_percentile",
            inputs.peer_valuation_attractiveness_percentile,
            _ZERO,
            _ONE,
            bounded_ratio=True,
        ),
    )
    factors = tuple(_factor_score(item) for item in definitions)
    missing = tuple(item.name for item in factors if item.state == InputState.MISSING)
    invalid = tuple(item.name for item in factors if item.state == InputState.INVALID)
    if inputs.peer_cohort_member_count is None:
        missing = (*missing, "peer_cohort_member_count")
    if invalid:
        state = DimensionState.INVALID
    elif missing:
        state = DimensionState.MISSING
    elif inputs.peer_cohort_member_count < inputs.peer_cohort_minimum_count:
        state = DimensionState.COHORT_INSUFFICIENT
    elif any(item.state == InputState.NOT_APPLICABLE for item in factors):
        state = DimensionState.NOT_APPLICABLE
    else:
        state = DimensionState.VALID
    quality = factors[0].normalized_score
    valuation = factors[1].normalized_score
    score = (
        _score_quantize((quality + valuation) / Decimal("2"))
        if state == DimensionState.VALID and quality is not None and valuation is not None
        else None
    )
    return SectorRelativeAssessment(
        state=state,
        score=score,
        quality_percentile_score=quality,
        valuation_attractiveness_percentile_score=valuation,
        cohort_member_count=inputs.peer_cohort_member_count,
        cohort_minimum_count=inputs.peer_cohort_minimum_count,
        missing_fields=missing,
        invalid_fields=invalid,
    )


def _evidence_confidence(
    inputs: LongHorizonV11Inputs,
) -> EvidenceConfidenceAssessment:
    definitions = (
        _FactorDefinition(
            "evidence_coverage_ratio",
            inputs.evidence_coverage_ratio,
            _ZERO,
            _ONE,
            bounded_ratio=True,
        ),
        _FactorDefinition(
            "point_in_time_verified_ratio",
            inputs.point_in_time_verified_ratio,
            _ZERO,
            _ONE,
            bounded_ratio=True,
        ),
        _FactorDefinition(
            "revision_lineage_ratio",
            inputs.revision_lineage_ratio,
            _ZERO,
            _ONE,
            bounded_ratio=True,
        ),
        _FactorDefinition(
            "semantic_evidence_ratio",
            inputs.semantic_evidence_ratio,
            _ZERO,
            _ONE,
            bounded_ratio=True,
        ),
    )
    dimension = _dimension("EVIDENCE_CONFIDENCE", definitions)
    return EvidenceConfidenceAssessment(
        state=dimension.state,
        score=dimension.score,
        components=dimension.factors,
        missing_fields=dimension.missing_fields,
        invalid_fields=dimension.invalid_fields,
    )


def _expected_return(
    inputs: LongHorizonV11Inputs,
    *,
    quality: DimensionAssessment,
    downside_risk: DimensionAssessment,
) -> ExpectedReturnRange:
    component_names = (
        "free_cash_flow_yield",
        "earnings_yield",
        "conservative_fundamental_growth",
        "shareholder_yield",
        "annualized_valuation_normalization",
    )
    evidence_by_name = {
        "free_cash_flow_yield": inputs.free_cash_flow_yield,
        "earnings_yield": inputs.earnings_yield,
        "conservative_fundamental_growth": (inputs.conservative_fundamental_growth),
        "shareholder_yield": inputs.shareholder_yield,
        "annualized_valuation_normalization": (inputs.annualized_valuation_normalization),
    }
    missing = tuple(
        name for name, evidence in evidence_by_name.items() if evidence.state == InputState.MISSING
    )
    invalid = tuple(
        name for name, evidence in evidence_by_name.items() if evidence.state == InputState.INVALID
    )
    not_applicable = tuple(
        name
        for name, evidence in evidence_by_name.items()
        if evidence.state == InputState.NOT_APPLICABLE
    )
    if quality.state == DimensionState.INVALID:
        invalid = (*invalid, "business_quality")
    elif quality.state != DimensionState.VALID:
        missing = (*missing, "business_quality")
    if downside_risk.state == DimensionState.INVALID:
        invalid = (*invalid, "downside_risk")
    elif downside_risk.state != DimensionState.VALID:
        missing = (*missing, "downside_risk")
    if invalid:
        state = DimensionState.INVALID
    elif missing:
        state = DimensionState.MISSING
    elif not_applicable:
        state = DimensionState.NOT_APPLICABLE
    else:
        state = DimensionState.VALID
    if state != DimensionState.VALID:
        return ExpectedReturnRange(
            state=state,
            low=None,
            base=None,
            high=None,
            component_names=component_names,
            missing_fields=missing,
            invalid_fields=invalid,
        )
    values = {name: evidence.value for name, evidence in evidence_by_name.items()}
    assert all(value is not None for value in values.values())
    assert quality.score is not None and downside_risk.score is not None
    income_yield = (values["free_cash_flow_yield"] + values["earnings_yield"]) / Decimal("2")
    growth = _clip(
        values["conservative_fundamental_growth"],
        Decimal("-0.10"),
        Decimal("0.20"),
    )
    shareholder_yield = _clip(
        values["shareholder_yield"],
        Decimal("-0.10"),
        Decimal("0.15"),
    )
    valuation_normalization = _clip(
        values["annualized_valuation_normalization"],
        Decimal("-0.15"),
        Decimal("0.15"),
    )
    base = _clip(
        income_yield + growth + shareholder_yield + valuation_normalization,
        Decimal("-0.50"),
        Decimal("0.50"),
    )
    downside_buffer = Decimal("0.03") + downside_risk.score / _HUNDRED * Decimal("0.12")
    upside_buffer = Decimal("0.03") + quality.score / _HUNDRED * Decimal("0.07")
    return ExpectedReturnRange(
        state=DimensionState.VALID,
        low=_rate_quantize(max(Decimal("-1"), base - downside_buffer)),
        base=_rate_quantize(base),
        high=_rate_quantize(min(_ONE, base + upside_buffer)),
        component_names=component_names,
    )


def _classification(
    *,
    quality: DimensionAssessment,
    strength: DimensionAssessment,
    capital_allocation: DimensionAssessment,
    valuation: DimensionAssessment,
    expected_return: ExpectedReturnRange,
    downside_risk: DimensionAssessment,
    sector_relative: SectorRelativeAssessment,
) -> tuple[AssessmentStatus, ResearchClassification]:
    economic_dimensions = (
        quality,
        strength,
        capital_allocation,
        valuation,
        downside_risk,
    )
    if any(item.state == DimensionState.INVALID for item in economic_dimensions):
        return AssessmentStatus.INVALID_DATA, ResearchClassification.INSUFFICIENT_DATA
    if expected_return.state == DimensionState.INVALID:
        return AssessmentStatus.INVALID_DATA, ResearchClassification.INSUFFICIENT_DATA
    if sector_relative.state == DimensionState.INVALID:
        return AssessmentStatus.INVALID_DATA, ResearchClassification.INSUFFICIENT_DATA
    if (
        any(
            item.state in {DimensionState.MISSING, DimensionState.NOT_APPLICABLE}
            for item in economic_dimensions
        )
        or expected_return.state != DimensionState.VALID
    ):
        return (
            AssessmentStatus.INSUFFICIENT_DATA,
            ResearchClassification.INSUFFICIENT_DATA,
        )
    if sector_relative.state == DimensionState.COHORT_INSUFFICIENT:
        return (
            AssessmentStatus.COHORT_INSUFFICIENT,
            ResearchClassification.COHORT_INSUFFICIENT,
        )
    if sector_relative.state != DimensionState.VALID:
        return (
            AssessmentStatus.INSUFFICIENT_DATA,
            ResearchClassification.INSUFFICIENT_DATA,
        )
    assert quality.score is not None
    assert strength.score is not None
    assert capital_allocation.score is not None
    assert valuation.score is not None
    assert downside_risk.score is not None
    assert expected_return.base is not None
    if strength.score < Decimal("40") or downside_risk.score >= Decimal("70"):
        classification = ResearchClassification.HIGH_PERMANENT_LOSS_RISK
    elif valuation.score >= Decimal("70") and (
        quality.score < Decimal("45")
        or strength.score < Decimal("45")
        or downside_risk.score > Decimal("65")
    ):
        classification = ResearchClassification.CHEAP_BUT_FRAGILE
    elif quality.score >= Decimal("70") and valuation.score < Decimal("45"):
        classification = ResearchClassification.GOOD_COMPANY_EXPENSIVE
    elif (
        quality.score >= Decimal("70")
        and strength.score >= Decimal("60")
        and capital_allocation.score >= Decimal("55")
        and valuation.score >= Decimal("55")
        and downside_risk.score <= Decimal("50")
    ):
        classification = ResearchClassification.QUALITY_AT_REASONABLE_PRICE
    elif (
        quality.score >= Decimal("55")
        and strength.score >= Decimal("55")
        and capital_allocation.score >= Decimal("45")
        and valuation.score >= Decimal("55")
        and expected_return.base >= Decimal("0.10")
        and downside_risk.score <= Decimal("60")
    ):
        classification = ResearchClassification.ATTRACTIVE_FOR_FURTHER_RESEARCH
    else:
        classification = ResearchClassification.SELECTIVE_RESEARCH
    return AssessmentStatus.ASSESSED, classification


def _special_dimension(state: DimensionState, code: str) -> DimensionAssessment:
    return DimensionAssessment(code=code, state=state, score=None, factors=())


def _specialized_result(
    inputs: LongHorizonV11Inputs,
) -> LongHorizonV11Assessment | None:
    specialized = {
        CompanyModelV11.BANK,
        CompanyModelV11.INSURANCE,
        CompanyModelV11.REIT,
        CompanyModelV11.RESOURCE,
        CompanyModelV11.BIOTECH,
    }
    if inputs.company_model == CompanyModelV11.RECENT_IPO:
        state = DimensionState.NOT_APPLICABLE
        status = AssessmentStatus.INSUFFICIENT_PUBLIC_HISTORY
        classification = ResearchClassification.SPECULATIVE_RESEARCH_ONLY
        limitation = (
            "A recent IPO lacks enough public-cycle evidence for this 12-month-plus model.",
        )
    elif inputs.company_model in specialized:
        state = DimensionState.SPECIALIZED_MODEL_REQUIRED
        status = AssessmentStatus.SPECIALIZED_MODEL_REQUIRED
        classification = ResearchClassification.SPECIALIZED_MODEL_REQUIRED
        limitation = (
            f"{inputs.company_model.value} requires a specialized model; "
            "general-company factors are not coerced into a score.",
        )
    else:
        return None
    return LongHorizonV11Assessment(
        version=LONG_HORIZON_V11_VERSION,
        status=status,
        classification=classification,
        business_quality=_special_dimension(state, "BUSINESS_QUALITY"),
        financial_strength=_special_dimension(state, "FINANCIAL_STRENGTH"),
        capital_allocation=_special_dimension(state, "CAPITAL_ALLOCATION"),
        valuation_entry=_special_dimension(state, "VALUATION_ENTRY"),
        expected_return=ExpectedReturnRange(
            state=state,
            low=None,
            base=None,
            high=None,
            component_names=(),
        ),
        downside_risk=_special_dimension(
            state,
            "PERMANENT_LOSS_AND_DOWNSIDE_RISK",
        ),
        sector_relative=SectorRelativeAssessment(
            state=state,
            score=None,
            quality_percentile_score=None,
            valuation_attractiveness_percentile_score=None,
            cohort_member_count=inputs.peer_cohort_member_count,
            cohort_minimum_count=inputs.peer_cohort_minimum_count,
        ),
        evidence_confidence=EvidenceConfidenceAssessment(
            state=state,
            score=None,
            components=(),
        ),
        default_ranking_score=None,
        deterministic_ranking_authorized=False,
        missing_fields=(),
        invalid_fields=(),
        limitations=limitation,
    )


def _collect_fields(
    *dimensions: DimensionAssessment,
    expected_return: ExpectedReturnRange,
    sector_relative: SectorRelativeAssessment,
    confidence: EvidenceConfidenceAssessment,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    missing = [
        f"{dimension.code}.{name}" for dimension in dimensions for name in dimension.missing_fields
    ]
    invalid = [
        f"{dimension.code}.{name}" for dimension in dimensions for name in dimension.invalid_fields
    ]
    missing.extend(f"EXPECTED_RETURN.{name}" for name in expected_return.missing_fields)
    invalid.extend(f"EXPECTED_RETURN.{name}" for name in expected_return.invalid_fields)
    missing.extend(f"SECTOR_RELATIVE.{name}" for name in sector_relative.missing_fields)
    invalid.extend(f"SECTOR_RELATIVE.{name}" for name in sector_relative.invalid_fields)
    missing.extend(f"EVIDENCE_CONFIDENCE.{name}" for name in confidence.missing_fields)
    invalid.extend(f"EVIDENCE_CONFIDENCE.{name}" for name in confidence.invalid_fields)
    return tuple(dict.fromkeys(missing)), tuple(dict.fromkeys(invalid))


def evaluate_long_horizon_v11(
    inputs: LongHorizonV11Inputs,
) -> LongHorizonV11Assessment:
    special = _specialized_result(inputs)
    if special is not None:
        return special

    quality = _business_quality(inputs)
    strength = _financial_strength(inputs)
    capital_allocation = _capital_allocation(inputs)
    valuation = _valuation_entry(inputs)
    downside_risk = _downside_risk(inputs)
    sector_relative = _sector_relative(inputs)
    confidence = _evidence_confidence(inputs)
    expected_return = _expected_return(
        inputs,
        quality=quality,
        downside_risk=downside_risk,
    )
    status, classification = _classification(
        quality=quality,
        strength=strength,
        capital_allocation=capital_allocation,
        valuation=valuation,
        expected_return=expected_return,
        downside_risk=downside_risk,
        sector_relative=sector_relative,
    )
    missing, invalid = _collect_fields(
        quality,
        strength,
        capital_allocation,
        valuation,
        downside_risk,
        expected_return=expected_return,
        sector_relative=sector_relative,
        confidence=confidence,
    )
    return LongHorizonV11Assessment(
        version=LONG_HORIZON_V11_VERSION,
        status=status,
        classification=classification,
        business_quality=quality,
        financial_strength=strength,
        capital_allocation=capital_allocation,
        valuation_entry=valuation,
        expected_return=expected_return,
        downside_risk=downside_risk,
        sector_relative=sector_relative,
        evidence_confidence=confidence,
        default_ranking_score=None,
        deterministic_ranking_authorized=False,
        missing_fields=missing,
        invalid_fields=invalid,
        limitations=(
            "The model separates company quality from security attractiveness.",
            "Expected-return ranges are deterministic research estimates, not promises.",
            "Evidence confidence does not alter any economic dimension.",
            "No default cross-sectional ranking is authorized by this assessment.",
            "Objective Rating v1 remains an independent model.",
            "AI narrative cannot alter deterministic fields.",
        ),
    )
