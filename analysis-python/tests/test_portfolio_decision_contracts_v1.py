from decimal import Decimal, getcontext

import pytest

from equity_analysis.portfolio_decision.contracts_v1 import (
    CostPolicyV1,
    PortfolioDecisionContractViolation,
    freeze_decision_policy_v1,
)


def test_frozen_policy_preserves_human_authority_and_sleeve_isolation() -> None:
    policy = freeze_decision_policy_v1(
        CostPolicyV1(Decimal("2"), Decimal("3"), "NOT_ESTIMATED", "NOT_ESTIMATED")
    )

    assert policy["scenarioTypes"] == [
        "HOLD_CURRENT",
        "NEW_MONEY_ONLY",
        "CONSTRAINED_REBALANCE",
        "TARGET_PORTFOLIO",
    ]
    assert policy["authority"] == {
        "candidateForHumanReviewOnly": True,
        "finalWeightAuthority": False,
        "orderAuthority": False,
        "brokerageExecutionAuthority": False,
        "llmSecuritySelectionAuthority": False,
        "llmWeightAuthority": False,
    }
    assert policy["sleeves"]["scoreBlendingAllowed"] is False
    assert policy["evidence"]["notValidatedUpgradeAllowed"] is False
    assert policy["evidence"]["quantV2ResearchAuthorityAllowed"] is False
    assert policy["policyContentHash"].startswith("sha256:")


def test_frozen_policy_is_order_and_decimal_stable() -> None:
    first = freeze_decision_policy_v1(
        CostPolicyV1(Decimal("2.000"), Decimal("3.0"), "AVAILABLE", "AVAILABLE_NOT_APPLIED")
    )
    second = freeze_decision_policy_v1(
        CostPolicyV1(Decimal("2"), Decimal("3"), "AVAILABLE", "AVAILABLE_NOT_APPLIED")
    )
    assert first == second


@pytest.mark.parametrize("value", [Decimal("NaN"), Decimal("Infinity"), Decimal("-0.01")])
def test_cost_policy_rejects_unsafe_values(value: Decimal) -> None:
    with pytest.raises(PortfolioDecisionContractViolation):
        CostPolicyV1(value, Decimal("1"), "NOT_ESTIMATED", "NOT_ESTIMATED")


def test_cost_policy_rejects_numeric_coercion() -> None:
    with pytest.raises(PortfolioDecisionContractViolation):
        CostPolicyV1(2, Decimal("1"), "NOT_ESTIMATED", "NOT_ESTIMATED")  # type: ignore[arg-type]


def test_policy_hash_is_independent_of_ambient_decimal_context() -> None:
    original = getcontext().prec
    try:
        getcontext().prec = 5
        first = freeze_decision_policy_v1(
            CostPolicyV1(
                Decimal("2.0000000000000000000001"),
                Decimal("3.0000000000000000000002"),
                "NOT_ESTIMATED",
                "NOT_ESTIMATED",
            )
        )
        getcontext().prec = 80
        second = freeze_decision_policy_v1(
            CostPolicyV1(
                Decimal("2.0000000000000000000001"),
                Decimal("3.0000000000000000000002"),
                "NOT_ESTIMATED",
                "NOT_ESTIMATED",
            )
        )
        assert first == second
    finally:
        getcontext().prec = original


def test_policy_rejects_decimal_outside_global_magnitude_bound() -> None:
    with pytest.raises(PortfolioDecisionContractViolation):
        CostPolicyV1(
            Decimal("1e101"), Decimal("1"), "NOT_ESTIMATED", "NOT_ESTIMATED"
        )
