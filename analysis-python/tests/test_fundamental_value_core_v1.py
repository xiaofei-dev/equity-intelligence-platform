from __future__ import annotations

import json
from dataclasses import replace
from decimal import ROUND_DOWN, Decimal, getcontext, setcontext
from pathlib import Path

import pytest

from equity_analysis.fundamental_value.contracts_v1 import (
    Applicability,
    CompanyType,
    DataState,
    ModelEvidenceLabel,
    ValuationMethod,
)
from equity_analysis.fundamental_value.core_v1 import (
    ClaimCeiling,
    CoreViolation,
    FundamentalValueInputsV1,
    MetricEvidence,
    ValuationResult,
    aggregate_valuations,
    canonical_decimal_text,
    evaluate_fundamental_value_v1,
)


def valid(value: str) -> MetricEvidence:
    return MetricEvidence.valid(value)


def inputs() -> FundamentalValueInputsV1:
    fixture = json.loads(
        (
            Path(__file__).parents[2]
            / "contracts"
            / "fundamental-value-v1"
            / "core-assessment.example.json"
        ).read_text(encoding="utf-8")
    )
    values = {name: valid(value) for name, value in fixture["validInputs"].items()}
    return FundamentalValueInputsV1(
        company_type=CompanyType(fixture["companyType"]),
        applicability=Applicability(fixture["applicability"]),
        projection_years=fixture["projectionYears"],
        currency=fixture["currency"],
        **values,
    )


def fixture_payload() -> dict:
    return json.loads(
        (
            Path(__file__).parents[2]
            / "contracts"
            / "fundamental-value-v1"
            / "core-assessment.example.json"
        ).read_text(encoding="utf-8")
    )


def test_complete_assessment_is_deterministic_ordered_and_not_validated() -> None:
    first = evaluate_fundamental_value_v1(inputs())
    second = evaluate_fundamental_value_v1(inputs())
    assert first == second
    assert first.content_hash == second.content_hash
    assert first.content_hash.startswith("sha256:")
    assert first.model_evidence_label == ModelEvidenceLabel.NOT_VALIDATED
    assert first.fair_value.state == DataState.VALID
    assert first.fair_value.low <= first.fair_value.central <= first.fair_value.high
    assert first.margin_of_safety.low <= first.margin_of_safety.central
    assert first.expected_return.low <= first.expected_return.central <= first.expected_return.high
    assert first.deterministic_ranking_authorized is False
    assert first.final_portfolio_weight_authorized is False
    assert first.automatic_brokerage_execution_authorized is False


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (Decimal("1E+2"), "100"),
        (Decimal("1E-7"), "0.0000001"),
        (Decimal("-1E-7"), "-0.0000001"),
        (Decimal("12345678901234567890.12345678901234567890"),
         "12345678901234567890.12345678901234567890"),
        (Decimal("1.2300"), "1.2300"),
        (Decimal("-0"), "0"),
        (Decimal("0.000"), "0"),
    ],
)
def test_canonical_decimal_text_is_ordinary_finite_and_stable(value, expected) -> None:
    assert canonical_decimal_text(value) == expected


@pytest.mark.parametrize("value", [Decimal("NaN"), Decimal("Infinity"), Decimal("-Infinity")])
def test_canonical_decimal_text_rejects_nonfinite_values(value) -> None:
    with pytest.raises(CoreViolation):
        canonical_decimal_text(value)


def test_exponent_and_ordinary_decimal_inputs_share_assessment_hash() -> None:
    exponent = replace(inputs(), reference_price=MetricEvidence.valid(Decimal("1E+2")))
    ordinary = replace(inputs(), reference_price=MetricEvidence.valid(Decimal("100")))
    assert evaluate_fundamental_value_v1(exponent).input_hash == (
        evaluate_fundamental_value_v1(ordinary).input_hash
    )
    assert evaluate_fundamental_value_v1(exponent).content_hash == (
        evaluate_fundamental_value_v1(ordinary).content_hash
    )


def test_evaluation_is_independent_of_mutable_global_decimal_context() -> None:
    baseline = evaluate_fundamental_value_v1(inputs())
    original = getcontext().copy()
    try:
        getcontext().prec = 9
        getcontext().rounding = ROUND_DOWN
        changed_context = evaluate_fundamental_value_v1(inputs())
    finally:
        setcontext(original)
    assert changed_context == baseline
    assert changed_context.content_hash == baseline.content_hash


def test_canonical_core_fixture_matches_known_answers_and_hashes() -> None:
    expected = fixture_payload()["expected"]
    assessment = evaluate_fundamental_value_v1(inputs())
    assert assessment.input_hash == expected["inputHash"]
    assert assessment.content_hash == expected["resultHash"]
    for result in assessment.valuations:
        assert [str(result.low), str(result.central), str(result.high)] == expected["methods"][
            result.method.value
        ]
    assert [
        str(assessment.fair_value.low),
        str(assessment.fair_value.central),
        str(assessment.fair_value.high),
    ] == expected["fairValue"]
    assert [
        str(assessment.expected_return.low),
        str(assessment.expected_return.central),
        str(assessment.expected_return.high),
    ] == expected["expectedReturn"]


def test_quality_is_independent_from_reference_price() -> None:
    low_price = evaluate_fundamental_value_v1(inputs())
    high_price = evaluate_fundamental_value_v1(replace(inputs(), reference_price=valid("200")))
    assert low_price.company_quality == high_price.company_quality
    assert low_price.earnings_and_cash_flow_quality == high_price.earnings_and_cash_flow_quality
    assert low_price.capital_allocation_quality == high_price.capital_allocation_quality
    assert low_price.margin_of_safety != high_price.margin_of_safety
    assert low_price.expected_return != high_price.expected_return


def test_favorable_expected_return_cannot_suppress_downside_risk() -> None:
    base = evaluate_fundamental_value_v1(inputs())
    optimistic = evaluate_fundamental_value_v1(
        replace(inputs(), conservative_growth_rate=valid("0.05"))
    )
    assert optimistic.expected_return.central > base.expected_return.central
    assert optimistic.downside_risk == base.downside_risk


@pytest.mark.parametrize(
    ("field", "state"),
    (
        ("incremental_return_on_invested_capital", DataState.MISSING),
        ("acquisition_discipline", DataState.INVALID),
        ("shareholder_distribution_coverage", DataState.STALE),
    ),
)
def test_capital_allocation_quality_propagates_nonvalid_evidence(
    field: str, state: DataState
) -> None:
    assessment = evaluate_fundamental_value_v1(
        replace(
            inputs(),
            **{field: MetricEvidence(state, reason_code="CAPITAL_ALLOCATION_EVIDENCE_UNUSABLE")},
        )
    )
    assert assessment.capital_allocation_quality.state == state
    assert assessment.capital_allocation_quality.score is None
    assert assessment.risk_cap.ceiling == Decimal("0")


def test_weak_capital_allocation_quality_cannot_improve_risk_cap() -> None:
    strong = evaluate_fundamental_value_v1(
        replace(inputs(), reference_price=valid("50")),
        model_evidence_label=ModelEvidenceLabel.FORWARD_SUPPORTED,
    )
    weak = evaluate_fundamental_value_v1(
        replace(
            inputs(),
            reference_price=valid("50"),
            incremental_return_on_invested_capital=valid("-0.05"),
            acquisition_discipline=valid("0"),
            shareholder_distribution_coverage=valid("0"),
        ),
        model_evidence_label=ModelEvidenceLabel.FORWARD_SUPPORTED,
    )
    assert weak.capital_allocation_quality.score < strong.capital_allocation_quality.score
    assert weak.risk_cap.ceiling <= strong.risk_cap.ceiling
    assert weak.risk_cap.ceiling <= Decimal("0.01")


def test_capital_allocation_evidence_is_versioned_and_hash_bound() -> None:
    baseline = evaluate_fundamental_value_v1(inputs())
    changed = evaluate_fundamental_value_v1(
        replace(inputs(), acquisition_discipline=valid("0.84"))
    )
    assert baseline.formula_version == "fundamental-value-formulas-v1.1.0"
    assert baseline.assumption_policy_version == "fundamental-value-assumptions-v1.1.0"
    assert changed.capital_allocation_quality != baseline.capital_allocation_quality
    assert changed.input_hash != baseline.input_hash
    assert changed.content_hash != baseline.content_hash


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("incremental_return_on_invested_capital", "-1"),
        ("acquisition_discipline", "1.01"),
        ("shareholder_distribution_coverage", "-0.01"),
    ),
)
def test_capital_allocation_economic_domains_fail_closed(field: str, value: str) -> None:
    assessment = evaluate_fundamental_value_v1(replace(inputs(), **{field: valid(value)}))
    assert assessment.capital_allocation_quality.state == DataState.INVALID
    assert assessment.risk_cap.ceiling == Decimal("0")


@pytest.mark.parametrize("growth", ("-1.00", "-1.01"))
def test_explicit_growth_at_or_below_negative_one_invalidates_without_crashing(
    growth: str,
) -> None:
    assessment = evaluate_fundamental_value_v1(
        replace(inputs(), conservative_growth_rate=valid(growth))
    )
    assert assessment.valuations[0].state == DataState.INVALID
    assert assessment.valuations[1].state == DataState.INVALID
    assert assessment.fair_value.state == DataState.INVALID


def test_terminal_growth_below_negative_one_invalidates_without_crashing() -> None:
    assessment = evaluate_fundamental_value_v1(
        replace(inputs(), terminal_growth_rate=valid("-1.10"))
    )
    assert assessment.valuations[0].state == DataState.INVALID
    assert assessment.fair_value.state == DataState.INVALID


def test_extreme_finite_reference_price_invalidates_components_without_crashing() -> None:
    assessment = evaluate_fundamental_value_v1(
        replace(inputs(), reference_price=valid("1e-999999"))
    )
    assert assessment.margin_of_safety.state == DataState.INVALID
    assert assessment.expected_return.state == DataState.INVALID
    assert assessment.risk_cap.ceiling == Decimal("0")


@pytest.mark.parametrize(
    "field",
    ("cash", "debt", "depreciation_and_amortization", "capital_expenditures"),
)
def test_nonnegative_sign_conventions_fail_closed(field: str) -> None:
    assessment = evaluate_fundamental_value_v1(replace(inputs(), **{field: valid("-1")}))
    assert assessment.valuations[0].state == DataState.INVALID
    assert assessment.fair_value.state == DataState.INVALID


def test_owner_earnings_does_not_apply_enterprise_cash_debt_bridge() -> None:
    base = evaluate_fundamental_value_v1(inputs())
    changed_bridge = evaluate_fundamental_value_v1(
        replace(inputs(), cash=valid("300"), debt=valid("150"))
    )
    owner_base = base.valuations[1]
    owner_changed = changed_bridge.valuations[1]
    assert owner_base == owner_changed
    assert base.valuations[2].central != changed_bridge.valuations[2].central
    assert base.valuations[3].central != changed_bridge.valuations[3].central


def test_fcff_bridge_applies_cash_and_debt_exactly_once_per_share() -> None:
    base = evaluate_fundamental_value_v1(inputs()).valuations[0]
    more_cash = evaluate_fundamental_value_v1(replace(inputs(), cash=valid("300"))).valuations[0]
    more_debt = evaluate_fundamental_value_v1(replace(inputs(), debt=valid("200"))).valuations[0]
    assert more_cash.central - base.central == Decimal("10.00")
    assert base.central - more_debt.central == Decimal("10.00")


def test_d_and_a_and_capex_are_counted_once_in_fcff() -> None:
    base = evaluate_fundamental_value_v1(inputs()).valuations[0]
    higher_da = evaluate_fundamental_value_v1(
        replace(inputs(), depreciation_and_amortization=valid("31"))
    ).valuations[0]
    higher_capex = evaluate_fundamental_value_v1(
        replace(inputs(), capital_expenditures=valid("36"))
    ).valuations[0]
    assert higher_da.central > base.central
    assert higher_capex.central < base.central
    assert higher_da.central - base.central == base.central - higher_capex.central


def test_all_three_primary_methods_are_required_but_comparable_is_optional() -> None:
    assessment = evaluate_fundamental_value_v1(
        replace(
            inputs(),
            ebitda=MetricEvidence.missing("COMPARABLE_EBITDA_MISSING"),
        )
    )
    assert assessment.valuations[3].state == DataState.MISSING
    assert assessment.fair_value.state == DataState.VALID

    assessment = evaluate_fundamental_value_v1(
        replace(
            inputs(),
            normalized_free_cash_flow=MetricEvidence.missing("OWNER_EARNINGS_MISSING"),
        )
    )
    assert assessment.valuations[1].state == DataState.MISSING
    assert assessment.fair_value.state == DataState.MISSING
    assert assessment.risk_cap.ceiling == Decimal("0")


def test_comparable_extreme_cannot_control_weighted_conclusion() -> None:
    primary = (
        ValuationResult(
            ValuationMethod.FCFF_DCF,
            DataState.VALID,
            Decimal("80"),
            Decimal("100"),
            Decimal("120"),
            (),
        ),
        ValuationResult(
            ValuationMethod.NORMALIZED_OWNER_EARNINGS,
            DataState.VALID,
            Decimal("90"),
            Decimal("110"),
            Decimal("130"),
            (),
        ),
        ValuationResult(
            ValuationMethod.EARNINGS_POWER,
            DataState.VALID,
            Decimal("70"),
            Decimal("95"),
            Decimal("115"),
            (),
        ),
    )
    normal = aggregate_valuations(
        primary
        + (
            ValuationResult(
                ValuationMethod.COMPARABLE_CROSS_CHECK,
                DataState.VALID,
                Decimal("60"),
                Decimal("105"),
                Decimal("140"),
                (),
            ),
        )
    )
    extreme = aggregate_valuations(
        primary
        + (
            ValuationResult(
                ValuationMethod.COMPARABLE_CROSS_CHECK,
                DataState.VALID,
                Decimal("1"),
                Decimal("10000"),
                Decimal("20000"),
                (),
            ),
        )
    )
    assert extreme.central == normal.central
    assert extreme.low >= Decimal("70")
    assert extreme.high <= Decimal("130")


def test_method_order_does_not_change_weighted_quantiles() -> None:
    assessment = evaluate_fundamental_value_v1(inputs())
    assert aggregate_valuations(assessment.valuations) == aggregate_valuations(
        tuple(reversed(assessment.valuations))
    )


def test_duplicate_method_cardinality_fails_closed() -> None:
    assessment = evaluate_fundamental_value_v1(inputs())
    duplicate_primary = assessment.valuations[:3] + (assessment.valuations[0],)
    assert aggregate_valuations(duplicate_primary).state == DataState.INVALID
    duplicate_comparable = assessment.valuations + (assessment.valuations[3],)
    assert aggregate_valuations(duplicate_comparable).state == DataState.INVALID


def test_result_models_reject_reversed_or_nonvalid_values() -> None:
    with pytest.raises(CoreViolation, match="ordered"):
        ValuationResult(
            ValuationMethod.FCFF_DCF,
            DataState.VALID,
            Decimal("120"),
            Decimal("100"),
            Decimal("130"),
            (),
        )
    with pytest.raises(CoreViolation, match="no values"):
        ValuationResult(
            ValuationMethod.FCFF_DCF,
            DataState.MISSING,
            Decimal("0"),
            None,
            None,
            ("MISSING",),
        )


@pytest.mark.parametrize(
    ("state", "reason"),
    (
        (DataState.INVALID, "INVALID_INPUT"),
        (DataState.STALE, "STALE_INPUT"),
        (DataState.MISSING, "MISSING_INPUT"),
        (DataState.EXCLUDED, "EXCLUDED_INPUT"),
        (DataState.NOT_APPLICABLE, "NOT_APPLICABLE_INPUT"),
    ),
)
def test_nonvalid_values_never_become_zero_or_neutral(state: DataState, reason: str) -> None:
    evidence = MetricEvidence(state=state, reason_code=reason)
    assessment = evaluate_fundamental_value_v1(
        replace(inputs(), return_on_invested_capital=evidence)
    )
    assert assessment.company_quality.state == state
    assert assessment.company_quality.score is None


def test_state_precedence_is_invalid_then_stale_then_missing() -> None:
    assessment = evaluate_fundamental_value_v1(
        replace(
            inputs(),
            return_on_invested_capital=MetricEvidence.missing("MISSING_ROIC"),
            operating_margin=MetricEvidence(DataState.STALE, reason_code="STALE_MARGIN"),
            free_cash_flow_margin=MetricEvidence(DataState.INVALID, reason_code="INVALID_FCF"),
        )
    )
    assert assessment.company_quality.state == DataState.INVALID


def test_missing_advanced_evidence_materiality_is_deterministic() -> None:
    nonmaterial = evaluate_fundamental_value_v1(
        replace(
            inputs(),
            debt_maturity_schedule=MetricEvidence.missing("DEBT_MATURITY_MISSING"),
        ),
        model_evidence_label=ModelEvidenceLabel.FORWARD_SUPPORTED,
    )
    assert nonmaterial.claim_ceiling == ClaimCeiling.LIMITED_MISSING_ADVANCED_EVIDENCE
    assert nonmaterial.risk_cap.ceiling <= Decimal("0.01")

    material_inputs = replace(
        inputs(),
        debt_maturity_schedule=MetricEvidence.missing("DEBT_MATURITY_MISSING"),
        net_debt_to_ebitda=valid("2"),
    )
    material = evaluate_fundamental_value_v1(material_inputs)
    assert material.claim_ceiling == ClaimCeiling.BLOCKED_MATERIAL_REFINANCING_UNCERTAINTY
    assert material.fair_value.state == DataState.EXCLUDED
    assert material.risk_cap.ceiling == Decimal("0")


@pytest.mark.parametrize("state", (DataState.INVALID, DataState.STALE))
def test_invalid_or_stale_debt_maturity_evidence_blocks_positive_debt(
    state: DataState,
) -> None:
    assessment = evaluate_fundamental_value_v1(
        replace(
            inputs(),
            debt_maturity_schedule=MetricEvidence(state, reason_code="DEBT_MATURITY_UNUSABLE"),
        )
    )
    assert assessment.claim_ceiling == ClaimCeiling.BLOCKED_MATERIAL_REFINANCING_UNCERTAINTY
    assert assessment.risk_cap.ceiling == Decimal("0")


def test_zero_debt_missing_maturity_evidence_is_limited_not_material() -> None:
    assessment = evaluate_fundamental_value_v1(
        replace(
            inputs(),
            debt=valid("0"),
            net_debt_to_ebitda=valid("-0.5"),
            debt_maturity_schedule=MetricEvidence.missing("NO_DEBT_SCHEDULE"),
        )
    )
    assert assessment.claim_ceiling == ClaimCeiling.LIMITED_MISSING_ADVANCED_EVIDENCE


def test_missing_distribution_evidence_blocks_expected_return_not_valuation() -> None:
    assessment = evaluate_fundamental_value_v1(
        replace(
            inputs(),
            net_distribution_yield=MetricEvidence.missing("DISTRIBUTION_EVIDENCE_MISSING"),
        )
    )
    assert assessment.fair_value.state == DataState.VALID
    assert assessment.expected_return.state == DataState.MISSING
    assert assessment.expected_return.low is None


@pytest.mark.parametrize("yield_value", ("-0.01", "0.26"))
def test_pathological_distribution_yield_invalidates_expected_return(
    yield_value: str,
) -> None:
    assessment = evaluate_fundamental_value_v1(
        replace(inputs(), net_distribution_yield=valid(yield_value))
    )
    assert assessment.fair_value.state == DataState.VALID
    assert assessment.expected_return.state == DataState.INVALID


def test_missing_cash_flow_quality_forces_zero_cap() -> None:
    assessment = evaluate_fundamental_value_v1(
        replace(
            inputs(),
            cash_flow_to_net_income=MetricEvidence.missing("CASH_CONVERSION_MISSING"),
        ),
        model_evidence_label=ModelEvidenceLabel.FORWARD_SUPPORTED,
    )
    assert assessment.earnings_and_cash_flow_quality.state == DataState.MISSING
    assert assessment.risk_cap.ceiling == Decimal("0")


def test_weaker_valid_cash_flow_quality_cannot_preserve_a_higher_cap() -> None:
    strong = evaluate_fundamental_value_v1(
        replace(inputs(), reference_price=valid("50")),
        model_evidence_label=ModelEvidenceLabel.FORWARD_SUPPORTED,
    )
    weak = evaluate_fundamental_value_v1(
        replace(
            inputs(),
            reference_price=valid("50"),
            cash_flow_to_net_income=valid("0.50"),
        ),
        model_evidence_label=ModelEvidenceLabel.FORWARD_SUPPORTED,
    )
    assert weak.earnings_and_cash_flow_quality.score < strong.earnings_and_cash_flow_quality.score
    assert weak.risk_cap.ceiling < strong.risk_cap.ceiling
    assert weak.risk_cap.ceiling <= Decimal("0.02")


def test_worse_leverage_cannot_improve_resilience_downside_or_cap() -> None:
    good = evaluate_fundamental_value_v1(
        inputs(), model_evidence_label=ModelEvidenceLabel.FORWARD_SUPPORTED
    )
    bad = evaluate_fundamental_value_v1(
        replace(inputs(), net_debt_to_ebitda=valid("4"), interest_coverage=valid("3")),
        model_evidence_label=ModelEvidenceLabel.FORWARD_SUPPORTED,
    )
    assert bad.financial_resilience.score < good.financial_resilience.score
    assert bad.downside_risk.score > good.downside_risk.score
    assert bad.risk_cap.ceiling <= good.risk_cap.ceiling


def test_model_evidence_label_caps_are_conservative_discrete_tiers() -> None:
    expected_maximum = {
        ModelEvidenceLabel.NOT_VALIDATED: Decimal("0.02"),
        ModelEvidenceLabel.DEVELOPMENT_OBSERVED: Decimal("0.02"),
        ModelEvidenceLabel.BACKTEST_SUPPORTED: Decimal("0.03"),
        ModelEvidenceLabel.PIT_SUPPORTED: Decimal("0.03"),
        ModelEvidenceLabel.FORWARD_SUPPORTED: Decimal("0.05"),
    }
    allowed = {Decimal("0"), Decimal("0.01"), Decimal("0.02"), Decimal("0.03"), Decimal("0.05")}
    for label, maximum in expected_maximum.items():
        cap = evaluate_fundamental_value_v1(inputs(), model_evidence_label=label).risk_cap.ceiling
        assert cap in allowed
        assert cap <= maximum


@pytest.mark.parametrize(
    ("company_type", "applicability"),
    (
        (CompanyType.BANK, Applicability.SPECIALIZED_MODEL_REQUIRED),
        (CompanyType.INSURER, Applicability.SPECIALIZED_MODEL_REQUIRED),
        (CompanyType.REIT, Applicability.SPECIALIZED_MODEL_REQUIRED),
        (CompanyType.RESOURCE, Applicability.SPECIALIZED_MODEL_REQUIRED),
        (CompanyType.BIOTECHNOLOGY, Applicability.SPECIALIZED_MODEL_REQUIRED),
        (CompanyType.BENCHMARK, Applicability.NOT_APPLICABLE),
        (CompanyType.INSUFFICIENT_PUBLIC_HISTORY, Applicability.INSUFFICIENT_EVIDENCE),
    ),
)
def test_specialized_and_nonapplicable_types_never_reach_generic_formulas(
    company_type: CompanyType, applicability: Applicability
) -> None:
    with pytest.raises(CoreViolation, match="mature-company"):
        evaluate_fundamental_value_v1(
            replace(inputs(), company_type=company_type, applicability=applicability)
        )


def test_metric_state_contract_rejects_nonfinite_or_nonvalid_values() -> None:
    with pytest.raises(CoreViolation, match="finite"):
        MetricEvidence.valid(Decimal("NaN"))
    with pytest.raises(CoreViolation, match="cannot carry"):
        MetricEvidence(DataState.MISSING, Decimal("0"), "MISSING_WAS_ZERO")
    with pytest.raises(CoreViolation, match="requires a reason"):
        MetricEvidence(DataState.STALE)


def test_method_state_propagates_stale_and_invalid_inputs() -> None:
    stale = evaluate_fundamental_value_v1(
        replace(
            inputs(),
            normalized_free_cash_flow=MetricEvidence(
                DataState.STALE, reason_code="OWNER_EARNINGS_STALE"
            ),
        )
    )
    assert stale.valuations[1].state == DataState.STALE
    assert stale.fair_value.state == DataState.STALE

    invalid = evaluate_fundamental_value_v1(
        replace(
            inputs(),
            normalized_after_tax_operating_earnings=MetricEvidence(
                DataState.INVALID, reason_code="EARNINGS_INVALID"
            ),
        )
    )
    assert invalid.valuations[2].state == DataState.INVALID
    assert invalid.fair_value.state == DataState.INVALID


def test_input_change_changes_canonical_hash_without_nondeterminism() -> None:
    first = evaluate_fundamental_value_v1(inputs())
    changed = evaluate_fundamental_value_v1(replace(inputs(), reference_price=valid("101")))
    assert first.content_hash != changed.content_hash

    below_output_quantum = evaluate_fundamental_value_v1(
        replace(inputs(), ebit=valid("150.000001"))
    )
    assert first.input_hash != below_output_quantum.input_hash
    assert first.content_hash != below_output_quantum.content_hash
