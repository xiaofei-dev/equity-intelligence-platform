from dataclasses import replace
from decimal import Decimal

from equity_analysis.research_rating.long_horizon_v1 import (
    LONG_HORIZON_VERSION,
)
from equity_analysis.research_rating.long_horizon_v11 import (
    LONG_HORIZON_V11_VERSION,
    AssessmentStatus,
    CompanyModelV11,
    DimensionState,
    InputState,
    LongHorizonV11Inputs,
    MetricEvidence,
    ResearchClassification,
    evaluate_long_horizon_v11,
)


def _valid(value: str) -> MetricEvidence:
    return MetricEvidence.valid(Decimal(value))


def _quality_company(*, expensive: bool = False) -> LongHorizonV11Inputs:
    return LongHorizonV11Inputs(
        symbol="QUALITY",
        company_model=CompanyModelV11.GENERAL,
        return_on_invested_capital=_valid("0.20"),
        operating_margin=_valid("0.25"),
        free_cash_flow_margin=_valid("0.18"),
        earnings_stability=_valid("0.90"),
        cash_flow_stability=_valid("0.90"),
        net_debt_to_ebitda=_valid("0"),
        interest_coverage=_valid("10"),
        current_ratio=_valid("1.80"),
        diluted_share_growth=_valid("-0.02"),
        incremental_return_on_invested_capital=_valid("0.18"),
        reinvestment_efficiency=_valid("0.80"),
        shareholder_yield=_valid("0.06"),
        acquisition_discipline=_valid("80"),
        free_cash_flow_yield=_valid("0.02" if expensive else "0.08"),
        earnings_yield=_valid("0.025" if expensive else "0.07"),
        enterprise_value_to_ebitda=_valid("25" if expensive else "10"),
        own_history_valuation_attractiveness=_valid("0.20" if expensive else "0.75"),
        conservative_fundamental_growth=_valid("0.08"),
        annualized_valuation_normalization=_valid("-0.05" if expensive else "0.01"),
        cyclicality_risk=_valid("20"),
        concentration_risk=_valid("15"),
        event_risk=_valid("10"),
        peer_quality_percentile=_valid("0.85"),
        peer_valuation_attractiveness_percentile=_valid("0.20" if expensive else "0.75"),
        peer_cohort_member_count=30,
        evidence_coverage_ratio=_valid("0.95"),
        point_in_time_verified_ratio=_valid("0.90"),
        revision_lineage_ratio=_valid("0.90"),
        semantic_evidence_ratio=_valid("0.95"),
    )


def _cheap_fragile_company() -> LongHorizonV11Inputs:
    return LongHorizonV11Inputs(
        symbol="FRAGILE",
        company_model=CompanyModelV11.GENERAL,
        return_on_invested_capital=_valid("0.05"),
        operating_margin=_valid("0.08"),
        free_cash_flow_margin=_valid("0.03"),
        earnings_stability=_valid("0.50"),
        cash_flow_stability=_valid("0.45"),
        net_debt_to_ebitda=_valid("2.50"),
        interest_coverage=_valid("5"),
        current_ratio=_valid("1.20"),
        diluted_share_growth=_valid("0.03"),
        incremental_return_on_invested_capital=_valid("0.04"),
        reinvestment_efficiency=_valid("0.40"),
        shareholder_yield=_valid("0.03"),
        acquisition_discipline=_valid("45"),
        free_cash_flow_yield=_valid("0.10"),
        earnings_yield=_valid("0.09"),
        enterprise_value_to_ebitda=_valid("8"),
        own_history_valuation_attractiveness=_valid("0.90"),
        conservative_fundamental_growth=_valid("0.03"),
        annualized_valuation_normalization=_valid("0.04"),
        cyclicality_risk=_valid("60"),
        concentration_risk=_valid("50"),
        event_risk=_valid("40"),
        peer_quality_percentile=_valid("0.25"),
        peer_valuation_attractiveness_percentile=_valid("0.90"),
        peer_cohort_member_count=30,
        evidence_coverage_ratio=_valid("0.90"),
        point_in_time_verified_ratio=_valid("0.85"),
        revision_lineage_ratio=_valid("0.85"),
        semantic_evidence_ratio=_valid("0.90"),
    )


def test_price_sensitive_inputs_change_valuation_not_business_quality() -> None:
    reasonable = evaluate_long_horizon_v11(_quality_company())
    expensive = evaluate_long_horizon_v11(_quality_company(expensive=True))

    assert reasonable.business_quality == expensive.business_quality
    assert reasonable.financial_strength == expensive.financial_strength
    assert reasonable.valuation_entry.score is not None
    assert expensive.valuation_entry.score is not None
    assert expensive.valuation_entry.score < reasonable.valuation_entry.score
    assert expensive.expected_return.base < reasonable.expected_return.base


def test_more_debt_cannot_improve_strength_or_downside_risk() -> None:
    baseline_input = _quality_company()
    leveraged_input = replace(
        baseline_input,
        net_debt_to_ebitda=_valid("4.50"),
    )

    baseline = evaluate_long_horizon_v11(baseline_input)
    leveraged = evaluate_long_horizon_v11(leveraged_input)

    assert leveraged.financial_strength.score < baseline.financial_strength.score
    assert leveraged.downside_risk.score > baseline.downside_risk.score


def test_missing_evidence_cannot_improve_or_inherit_dimension_weight() -> None:
    complete = evaluate_long_horizon_v11(_quality_company())
    missing = evaluate_long_horizon_v11(
        replace(
            _quality_company(),
            free_cash_flow_yield=MetricEvidence.missing(),
        )
    )

    assert complete.valuation_entry.state == DimensionState.VALID
    assert missing.valuation_entry.state == DimensionState.MISSING
    assert missing.valuation_entry.score is None
    assert missing.expected_return.state == DimensionState.MISSING
    assert missing.status == AssessmentStatus.INSUFFICIENT_DATA
    assert any(item.endswith("free_cash_flow_yield") for item in missing.missing_fields)


def test_confidence_cannot_change_economic_scores_or_classification() -> None:
    high = evaluate_long_horizon_v11(_quality_company())
    low = evaluate_long_horizon_v11(
        replace(
            _quality_company(),
            evidence_coverage_ratio=_valid("0.20"),
            point_in_time_verified_ratio=_valid("0.10"),
            revision_lineage_ratio=_valid("0.15"),
            semantic_evidence_ratio=_valid("0.25"),
        )
    )

    assert low.evidence_confidence.score < high.evidence_confidence.score
    assert low.business_quality == high.business_quality
    assert low.financial_strength == high.financial_strength
    assert low.capital_allocation == high.capital_allocation
    assert low.valuation_entry == high.valuation_entry
    assert low.expected_return == high.expected_return
    assert low.downside_risk == high.downside_risk
    assert low.classification == high.classification


def test_high_quality_expensive_and_cheap_fragile_are_distinct() -> None:
    expensive = evaluate_long_horizon_v11(_quality_company(expensive=True))
    fragile = evaluate_long_horizon_v11(_cheap_fragile_company())

    assert expensive.status == AssessmentStatus.ASSESSED
    assert expensive.classification == ResearchClassification.GOOD_COMPANY_EXPENSIVE
    assert fragile.status == AssessmentStatus.ASSESSED
    assert fragile.classification == ResearchClassification.CHEAP_BUT_FRAGILE
    assert expensive.business_quality.score > fragile.business_quality.score
    assert expensive.valuation_entry.score < fragile.valuation_entry.score


def test_expected_return_range_is_ordered_and_not_a_default_rank() -> None:
    result = evaluate_long_horizon_v11(_quality_company())

    assert result.expected_return.state == DimensionState.VALID
    assert result.expected_return.low < result.expected_return.base
    assert result.expected_return.base < result.expected_return.high
    assert result.default_ranking_score is None
    assert result.deterministic_ranking_authorized is False


def test_insufficient_peer_cohort_remains_explicit() -> None:
    result = evaluate_long_horizon_v11(replace(_quality_company(), peer_cohort_member_count=19))

    assert result.sector_relative.state == DimensionState.COHORT_INSUFFICIENT
    assert result.sector_relative.score is None
    assert result.status == AssessmentStatus.COHORT_INSUFFICIENT
    assert result.classification == ResearchClassification.COHORT_INSUFFICIENT


def test_invalid_pre_normalized_input_is_not_clipped_into_validity() -> None:
    result = evaluate_long_horizon_v11(
        replace(_quality_company(), earnings_stability=_valid("1.01"))
    )

    assert result.business_quality.state == DimensionState.INVALID
    assert result.business_quality.score is None
    assert result.status == AssessmentStatus.INVALID_DATA
    assert result.business_quality.factors[3].state == InputState.INVALID


def test_recent_ipo_and_specialized_company_are_not_forced_into_general_model() -> None:
    recent = evaluate_long_horizon_v11(
        LongHorizonV11Inputs(
            symbol="NEW",
            company_model=CompanyModelV11.RECENT_IPO,
        )
    )
    bank = evaluate_long_horizon_v11(
        LongHorizonV11Inputs(
            symbol="BANK",
            company_model=CompanyModelV11.BANK,
        )
    )

    assert recent.status == AssessmentStatus.INSUFFICIENT_PUBLIC_HISTORY
    assert recent.classification == (ResearchClassification.SPECULATIVE_RESEARCH_ONLY)
    assert bank.status == AssessmentStatus.SPECIALIZED_MODEL_REQUIRED
    assert bank.classification == ResearchClassification.SPECIALIZED_MODEL_REQUIRED
    assert bank.business_quality.score is None


def test_not_applicable_general_input_remains_explicit() -> None:
    result = evaluate_long_horizon_v11(
        replace(
            _quality_company(),
            current_ratio=MetricEvidence.not_applicable(),
        )
    )

    assert result.financial_strength.state == DimensionState.NOT_APPLICABLE
    assert result.financial_strength.score is None
    assert result.status == AssessmentStatus.INSUFFICIENT_DATA


def test_v11_is_new_version_and_does_not_reinterpret_v10() -> None:
    result = evaluate_long_horizon_v11(_quality_company())

    assert LONG_HORIZON_VERSION == "LONG-HORIZON-RESEARCH-v1.0.0"
    assert result.version == LONG_HORIZON_V11_VERSION
    assert result.version == "LONG-HORIZON-RESEARCH-v1.1.0"
