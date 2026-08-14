from dataclasses import replace
from decimal import Decimal, getcontext

import pytest

from equity_analysis.portfolio_decision import (
    DECISION_CONTRACT_VERSION,
    CostPolicyV1,
    EvidenceState,
    PortfolioScenarioInputV1,
    PortfolioScenarioViolation,
    RebalancePermission,
    ScenarioConstraintsV1,
    ScenarioPositionV1,
    ScenarioType,
    SleeveBudgetV1,
    SleeveType,
    TaxEstimateState,
    calculate_portfolio_scenario_v1,
    freeze_decision_policy_v1,
)

HASH = "sha256:" + "1" * 64


def position(
    ordinal: int,
    *,
    sleeve: SleeveType = SleeveType.LONG_TERM_CORE,
    sector: str = "45",
    current: str | None = "10000",
    state: EvidenceState = EvidenceState.VALID,
    permission: RebalancePermission = RebalancePermission.BUY_AND_SELL,
    approved: bool = True,
    allowed: bool = True,
    target: str | None = None,
    classification: str = "VALUATION_OPPORTUNITY",
    cap: str | None = "0.4",
    model: str = "FUNDAMENTAL-VALUE-v1.0.0",
) -> ScenarioPositionV1:
    if sleeve is SleeveType.QUANT_TRADING:
        cap = None
        if model == "FUNDAMENTAL-VALUE-v1.0.0":
            model = "QUANT-TRADING-v1.1.0"
        if classification == "VALUATION_OPPORTUNITY":
            classification = "ENTRY_CANDIDATE"
    return ScenarioPositionV1(
        f"00000000-0000-4000-8000-{ordinal:012d}",
        f"S{ordinal}",
        sleeve,
        sector,
        None if current is None else Decimal(current),
        state,
        permission,
        approved,
        allowed,
        model,
        "NOT_VALIDATED",
        classification,
        None if cap is None else Decimal(cap),
        None if target is None else Decimal(target),
    )


def scenario(
    scenario_type: ScenarioType,
    positions: tuple[ScenarioPositionV1, ...],
    *,
    cash: str = "20000",
    new_money: str = "0",
    long_budget: str = "0.8",
    tax_state: TaxEstimateState = TaxEstimateState.NOT_ESTIMATED,
    tax_amount: str | None = None,
    tax_lot_evidence_hash: str | None = None,
) -> PortfolioScenarioInputV1:
    cost_policy = CostPolicyV1(
        Decimal("2"), Decimal("3"), "NOT_ESTIMATED", tax_state.value
    )
    return PortfolioScenarioInputV1(
        DECISION_CONTRACT_VERSION,
        scenario_type,
        HASH,
        HASH,
        freeze_decision_policy_v1(cost_policy)["policyContentHash"],
        Decimal(cash),
        Decimal("0"),
        Decimal(new_money),
        positions,
        (
            SleeveBudgetV1(SleeveType.LONG_TERM_CORE, Decimal(long_budget)),
            SleeveBudgetV1(SleeveType.QUANT_TRADING, Decimal("0.2")),
        ),
        ScenarioConstraintsV1(
            20,
            Decimal("0.5"),
            Decimal("0.8"),
            Decimal("0.1"),
            Decimal("0"),
            Decimal("0.2"),
        ),
        cost_policy,
        tax_state,
        None if tax_amount is None else Decimal(tax_amount),
        tax_lot_evidence_hash,
    )


def test_hold_current_has_exact_zero_trade_cost_and_authority() -> None:
    result = calculate_portfolio_scenario_v1(
        scenario(ScenarioType.HOLD_CURRENT, (position(1), position(2)))
    ).payload
    assert result["status"] == "CANDIDATE_FOR_HUMAN_REVIEW"
    assert result["economics"]["grossTradedNotional"] == "0"
    assert result["economics"]["estimatedTransactionAndSlippageCost"] == "0"
    assert result["economics"]["oneWayWeightTurnover"] == "0"
    assert all(item["deltaNotional"] == "0" for item in result["positions"])
    assert result["authority"] == {
        "candidateForHumanReviewOnly": True,
        "finalWeightAuthority": False,
        "orderAuthority": False,
        "automaticBrokerageExecution": False,
        "llmDecisionAuthority": False,
        "humanDecisionRequired": True,
    }


def test_hold_current_reports_existing_constraint_violations_without_trading() -> None:
    concentrated = position(1, current="90000", cap="1")
    result = calculate_portfolio_scenario_v1(
        scenario(ScenarioType.HOLD_CURRENT, (concentrated,), cash="10000")
    ).payload
    assert result["status"] == "CANDIDATE_FOR_HUMAN_REVIEW"
    assert result["constraintStatus"] == "VIOLATED"
    assert "MAXIMUM_POSITION_WEIGHT_EXCEEDED" in result["reasonCodes"]
    assert result["economics"]["grossTradedNotional"] == "0"


def test_hold_current_preserves_nonvalid_position_as_explicit_partial_value() -> None:
    missing = position(2, current=None, state=EvidenceState.MISSING)
    result = calculate_portfolio_scenario_v1(
        scenario(ScenarioType.HOLD_CURRENT, (position(1), missing))
    ).payload
    assert result["status"] == "CANDIDATE_FOR_HUMAN_REVIEW"
    assert result["positions"][1]["currentMarketValue"] is None
    assert result["positions"][1]["targetMarketValue"] is None
    assert result["constraintStatus"] == "PARTIAL_NOT_EVALUATED"


def test_new_money_never_sells_and_equal_water_fills_approved_candidates() -> None:
    first = position(1, current="10000", cap="0.5")
    second = position(2, sector="20", current="10000", cap="0.5")
    result = calculate_portfolio_scenario_v1(
        scenario(
            ScenarioType.NEW_MONEY_ONLY,
            (first, second),
            cash="20000",
            new_money="10000",
            long_budget="1",
        )
    ).payload
    assert result["status"] == "CANDIDATE_FOR_HUMAN_REVIEW"
    deltas = [Decimal(item["deltaNotional"]) for item in result["positions"]]
    assert deltas[0] == deltas[1]
    assert all(delta >= 0 for delta in deltas)
    assert result["economics"]["grossSellNotional"] == "0"
    assert Decimal(result["economics"]["finalCash"]) > 0


def test_new_money_shared_sector_capacity_is_not_double_counted() -> None:
    first = position(1, current="10000", cap="1")
    second = position(2, current="10000", cap="1")
    result = calculate_portfolio_scenario_v1(
        scenario(
            ScenarioType.NEW_MONEY_ONLY,
            (first, second),
            cash="80000",
            new_money="10000",
            long_budget="1",
        )
    ).payload
    assert result["status"] == "CANDIDATE_FOR_HUMAN_REVIEW"
    assert result["constraintStatus"] == "PASSED"
    assert Decimal(result["economics"]["finalCash"]) >= 0


def test_new_money_uses_only_human_approved_research_eligible_candidates() -> None:
    unapproved = position(1, approved=False)
    quant_exit = position(
        2,
        sleeve=SleeveType.QUANT_TRADING,
        classification="EXIT_REVIEW",
    )
    result = calculate_portfolio_scenario_v1(
        scenario(
            ScenarioType.NEW_MONEY_ONLY,
            (unapproved, quant_exit),
            new_money="5000",
        )
    ).payload
    assert result["status"] == "NO_FEASIBLE_CANDIDATE"
    assert result["reasonCodes"] == ["NO_HUMAN_APPROVED_ELIGIBLE_CANDIDATE"]


def test_nonhold_fails_closed_for_stale_price() -> None:
    stale = position(1, current=None, state=EvidenceState.STALE)
    result = calculate_portfolio_scenario_v1(
        scenario(ScenarioType.NEW_MONEY_ONLY, (stale,), new_money="1000")
    ).payload
    assert result["status"] == "NO_FEASIBLE_CANDIDATE"
    assert result["reasonCodes"] == ["INCOMPLETE_PRICE_EVIDENCE"]


@pytest.mark.parametrize(
    "permission,current,target,reason",
    [
        (RebalancePermission.LOCKED, "10000", "9000", "LOCKED_POSITION_CHANGE_FORBIDDEN"),
        (RebalancePermission.BUY_ONLY, "10000", "9000", "BUY_ONLY_POSITION_SALE_FORBIDDEN"),
        (RebalancePermission.SELL_ONLY, "10000", "11000", "SELL_ONLY_POSITION_INCREASE_FORBIDDEN"),
    ],
)
def test_constrained_rebalance_enforces_permissions(
    permission: RebalancePermission, current: str, target: str, reason: str
) -> None:
    item = position(1, current=current, target=target, permission=permission)
    result = calculate_portfolio_scenario_v1(
        scenario(ScenarioType.CONSTRAINED_REBALANCE, (item,))
    ).payload
    assert result["status"] == "NO_FEASIBLE_CANDIDATE"
    assert reason in result["reasonCodes"]


def test_constrained_rebalance_applies_cost_and_optional_tax_before_constraints() -> None:
    first = position(1, current="10000", target="15000")
    second = position(2, current="10000", target="5000")
    result = calculate_portfolio_scenario_v1(
        scenario(
            ScenarioType.CONSTRAINED_REBALANCE,
            (first, second),
            cash="20000",
            tax_state=TaxEstimateState.AVAILABLE_APPLIED,
            tax_amount="100",
            tax_lot_evidence_hash=HASH,
        )
    ).payload
    assert result["status"] == "CANDIDATE_FOR_HUMAN_REVIEW"
    assert result["economics"]["grossBuyNotional"] == "5000"
    assert result["economics"]["grossSellNotional"] == "5000"
    assert result["economics"]["estimatedTransactionAndSlippageCost"] == "5"
    assert result["economics"]["appliedTaxAmount"] == "100"
    assert result["economics"]["finalCash"] == "19895"


def test_target_portfolio_evaluates_exact_authorized_human_target() -> None:
    target = position(
        1,
        current="10000",
        target="12000",
        permission=RebalancePermission.BUY_AND_SELL,
        cap="0.5",
    )
    result = calculate_portfolio_scenario_v1(
        scenario(ScenarioType.TARGET_PORTFOLIO, (target,), cash="20000")
    ).payload
    assert result["status"] == "CANDIDATE_FOR_HUMAN_REVIEW"
    assert result["positions"][0]["targetMarketValue"] == "12000"
    assert result["positions"][0]["deltaNotional"] == "2000"


def test_target_weight_and_turnover_use_scale20_half_even_ratio_policy() -> None:
    target = position(1, current="1000", target="2000", cap="0.5")
    result = calculate_portfolio_scenario_v1(
        scenario(
            ScenarioType.TARGET_PORTFOLIO,
            (target,),
            cash="91001.5",
        )
    ).payload

    assert result["status"] == "CANDIDATE_FOR_HUMAN_REVIEW"
    assert result["economics"]["finalAssetValue"] == "92001"
    assert result["positions"][0]["finalAssetWeight"] == "0.02173889414245497332"
    assert result["economics"]["oneWayWeightTurnover"] == "0.01086950614334626314"


def test_target_portfolio_rejects_locked_or_unauthorized_increase() -> None:
    locked = position(1, target="11000", permission=RebalancePermission.LOCKED)
    result = calculate_portfolio_scenario_v1(
        scenario(ScenarioType.TARGET_PORTFOLIO, (locked,))
    ).payload
    assert result["status"] == "NO_FEASIBLE_CANDIDATE"
    assert "LOCKED_POSITION_CHANGE_FORBIDDEN" in result["reasonCodes"]
    excluded = position(1, target="11000", allowed=False)
    result = calculate_portfolio_scenario_v1(
        scenario(ScenarioType.TARGET_PORTFOLIO, (excluded,))
    ).payload
    assert "POSITION_INCREASE_NOT_EVIDENCE_AUTHORIZED" in result["reasonCodes"]


def test_target_portfolio_does_not_clamp_constraint_violation() -> None:
    target = position(1, current="10000", target="29000", cap="0.4")
    result = calculate_portfolio_scenario_v1(
        scenario(ScenarioType.TARGET_PORTFOLIO, (target,), cash="20000")
    ).payload
    assert result["status"] == "NO_FEASIBLE_CANDIDATE"
    assert "FUNDAMENTAL_VALUE_RISK_CAP_EXCEEDED" in result["reasonCodes"]
    assert result["positions"] == []


def test_tax_unavailable_is_null_not_zero() -> None:
    result = calculate_portfolio_scenario_v1(
        scenario(ScenarioType.HOLD_CURRENT, (position(1),))
    ).payload
    assert result["economics"]["taxEstimateState"] == "NOT_ESTIMATED"
    assert result["economics"]["taxEstimateAmount"] is None
    assert result["economics"]["impactState"] == "NOT_ESTIMATED"


def test_tax_policy_state_must_match_and_impact_is_not_silently_ignored() -> None:
    base = scenario(ScenarioType.HOLD_CURRENT, (position(1),))
    with pytest.raises(PortfolioScenarioViolation, match="TAX_POLICY_STATE_MISMATCH"):
        replace(
            base,
            tax_estimate_state=TaxEstimateState.AVAILABLE_NOT_APPLIED,
            tax_estimate_amount=Decimal("10"),
        )
    with pytest.raises(
        PortfolioScenarioViolation, match="IMPACT_EVIDENCE_CONTRACT_NOT_IMPLEMENTED"
    ):
        impact = CostPolicyV1(
            Decimal("2"), Decimal("3"), "AVAILABLE", "NOT_ESTIMATED"
        )
        replace(
            base,
            cost_policy=impact,
            decision_policy_hash=freeze_decision_policy_v1(impact)[
                "policyContentHash"
            ],
        )


def test_applied_tax_requires_lot_evidence_and_a_modeled_sale() -> None:
    with pytest.raises(PortfolioScenarioViolation, match="LOT_EVIDENCE"):
        scenario(
            ScenarioType.CONSTRAINED_REBALANCE,
            (position(1, target="9000"),),
            tax_state=TaxEstimateState.AVAILABLE_APPLIED,
            tax_amount="10",
        )
    no_sale = scenario(
        ScenarioType.TARGET_PORTFOLIO,
        (position(1, target="11000"),),
        tax_state=TaxEstimateState.AVAILABLE_APPLIED,
        tax_amount="10",
        tax_lot_evidence_hash=HASH,
    )
    result = calculate_portfolio_scenario_v1(no_sale).payload
    assert result["status"] == "NO_FEASIBLE_CANDIDATE"
    assert result["reasonCodes"] == ["APPLIED_TAX_REQUIRES_MODELED_SALE"]


def test_exact_sleeve_budgets_are_required_and_unassigned_never_increases() -> None:
    base = scenario(ScenarioType.HOLD_CURRENT, (position(1),))
    with pytest.raises(PortfolioScenarioViolation, match="BUDGET_SET_INCOMPLETE"):
        replace(base, sleeve_budgets=(base.sleeve_budgets[0],))
    unassigned = ScenarioPositionV1(
        "00000000-0000-4000-8000-000000000001",
        "CASHLIKE",
        SleeveType.UNASSIGNED,
        "UNASSIGNED",
        Decimal("100"),
        EvidenceState.VALID,
        RebalancePermission.BUY_AND_SELL,
        True,
        False,
        "NO_MODEL",
        "NOT_VALIDATED",
        "NOT_APPLICABLE",
        None,
        Decimal("200"),
    )
    result = calculate_portfolio_scenario_v1(
        scenario(ScenarioType.TARGET_PORTFOLIO, (unassigned,))
    ).payload
    assert "POSITION_INCREASE_NOT_EVIDENCE_AUTHORIZED" in result["reasonCodes"]


def test_quant_v2_cannot_receive_research_authority() -> None:
    with pytest.raises(PortfolioScenarioViolation, match="QUANT_V2"):
        position(
            1,
            sleeve=SleeveType.QUANT_TRADING,
            model="QUANT-TRADING-v2.0.0",
            allowed=True,
        )


def test_model_evidence_label_is_preserved_without_upgrade_or_downgrade() -> None:
    supported = replace(position(1), model_evidence_label="BACKTEST_SUPPORTED")
    result = calculate_portfolio_scenario_v1(
        scenario(ScenarioType.HOLD_CURRENT, (supported,))
    ).payload
    assert result["positions"][0]["modelEvidenceLabel"] == "BACKTEST_SUPPORTED"
    with pytest.raises(PortfolioScenarioViolation, match="LABEL_INVALID"):
        replace(position(1), model_evidence_label="GUARANTEED")


def test_new_money_does_not_invest_preexisting_cash() -> None:
    result = calculate_portfolio_scenario_v1(
        scenario(
            ScenarioType.NEW_MONEY_ONLY,
            (position(1, current="10000", cap="1"),),
            cash="80000",
            new_money="1000",
            long_budget="1",
        )
    ).payload
    assert result["status"] == "CANDIDATE_FOR_HUMAN_REVIEW"
    traded = Decimal(result["economics"]["grossBuyNotional"])
    cost = Decimal(
        result["economics"]["estimatedTransactionAndSlippageCost"]
    )
    assert traded + cost <= Decimal("1000")
    assert Decimal(result["economics"]["finalCash"]) >= Decimal("80000")


def test_exact_replay_is_hash_stable_and_does_not_mutate_decimal_context() -> None:
    value = scenario(ScenarioType.HOLD_CURRENT, (position(1), position(2)))
    original_precision = getcontext().prec
    getcontext().prec = 17
    try:
        first = calculate_portfolio_scenario_v1(value).payload
        second = calculate_portfolio_scenario_v1(value).payload
        assert first == second
        assert first["contentHash"] == second["contentHash"]
        assert getcontext().prec == 17
    finally:
        getcontext().prec = original_precision


def test_noncanonical_order_is_rejected_instead_of_silently_sorted() -> None:
    with pytest.raises(PortfolioScenarioViolation, match="NOT_CANONICALLY_ORDERED"):
        scenario(ScenarioType.HOLD_CURRENT, (position(2), position(1)))


@pytest.mark.parametrize("value", [Decimal("NaN"), Decimal("Infinity"), 1])
def test_adversarial_decimal_types_fail_closed(value: object) -> None:
    with pytest.raises(PortfolioScenarioViolation):
        replace(position(1), current_market_value=value)  # type: ignore[arg-type]


def test_tuple_boundary_rejects_mutable_position_collection() -> None:
    valid = scenario(ScenarioType.HOLD_CURRENT, (position(1),))
    with pytest.raises(PortfolioScenarioViolation, match="COLLECTION_MUST_BE_TUPLE"):
        replace(valid, positions=[position(1)])  # type: ignore[arg-type]
