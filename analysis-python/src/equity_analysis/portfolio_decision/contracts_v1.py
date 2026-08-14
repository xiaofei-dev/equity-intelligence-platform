"""Frozen Task 5 decision-support authority and economic-policy boundary."""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal, localcontext
from enum import Enum
from hashlib import sha256

DECISION_CONTRACT_VERSION = "portfolio-decision-scenario-v1.0.0"
COST_POLICY_VERSION = "portfolio-decision-cost-policy-v1.0.0"
EVALUATION_POLICY_VERSION = "portfolio-decision-evaluation-policy-v1.0.0"
DECIMAL_MAGNITUDE_LIMIT = Decimal("1e100")


class PortfolioDecisionContractViolation(ValueError):
    """Raised when a decision policy would cross the human-control boundary."""


class ScenarioType(str, Enum):
    HOLD_CURRENT = "HOLD_CURRENT"
    NEW_MONEY_ONLY = "NEW_MONEY_ONLY"
    CONSTRAINED_REBALANCE = "CONSTRAINED_REBALANCE"
    TARGET_PORTFOLIO = "TARGET_PORTFOLIO"


@dataclass(frozen=True, slots=True)
class CostPolicyV1:
    transaction_cost_bps: Decimal
    slippage_bps: Decimal
    impact_state: str
    tax_estimate_state: str

    def __post_init__(self) -> None:
        for field_name, value in (
            ("transaction_cost_bps", self.transaction_cost_bps),
            ("slippage_bps", self.slippage_bps),
        ):
            if (
                type(value) is not Decimal
                or not value.is_finite()
                or value < 0
                or abs(value) > DECIMAL_MAGNITUDE_LIMIT
            ):
                raise PortfolioDecisionContractViolation(
                    f"{field_name} must be a finite nonnegative Decimal"
                )
        if self.impact_state not in {"NOT_ESTIMATED", "AVAILABLE"}:
            raise PortfolioDecisionContractViolation("unsupported impact state")
        if self.tax_estimate_state not in {
            "NOT_ESTIMATED",
            "AVAILABLE_NOT_APPLIED",
            "AVAILABLE_APPLIED",
        }:
            raise PortfolioDecisionContractViolation("unsupported tax estimate state")


def freeze_decision_policy_v1(cost_policy: CostPolicyV1) -> dict[str, object]:
    """Return the canonical policy that must be sealed before scenario results."""

    value: dict[str, object] = {
        "contractVersion": DECISION_CONTRACT_VERSION,
        "scenarioTypes": [item.value for item in ScenarioType],
        "authority": {
            "candidateForHumanReviewOnly": True,
            "finalWeightAuthority": False,
            "orderAuthority": False,
            "brokerageExecutionAuthority": False,
            "llmSecuritySelectionAuthority": False,
            "llmWeightAuthority": False,
        },
        "sleeves": {
            "values": ["LONG_TERM_CORE", "QUANT_TRADING"],
            "scoreBlendingAllowed": False,
            "scoreInferredCashTransferAllowed": False,
            "explicitHumanBudgetRequired": True,
        },
        "objectiveHierarchy": [
            "INTEGRITY_CHRONOLOGY_OWNERSHIP",
            "HARD_CONTROLS_AND_LOCKED_POSITIONS",
            "SCENARIO_SEMANTICS",
            "MINIMIZE_GROSS_TRADED_NOTIONAL",
            "MINIMIZE_ESTIMATED_COST",
            "MINIMIZE_HUMAN_TARGET_DEVIATION",
            "SECURITY_ID_ASC_TIE_BREAK",
        ],
        "evidence": {
            "acceptedPriceRequiredForNonzeroTrade": True,
            "missingValueSubstitutionAllowed": False,
            "notValidatedUpgradeAllowed": False,
            "quantV2ResearchAuthorityAllowed": False,
            "fundamentalValueRiskCapIsCeilingOnly": True,
        },
        "costPolicy": {
            "version": COST_POLICY_VERSION,
            "transactionCostBps": _decimal_text(cost_policy.transaction_cost_bps),
            "slippageBps": _decimal_text(cost_policy.slippage_bps),
            "impactState": cost_policy.impact_state,
            "taxEstimateState": cost_policy.tax_estimate_state,
            "missingImpactOrTaxSubstitutedWithZero": False,
        },
        "turnover": {
            "oneWayDefinition": (
                "0.5*(sum(abs(securityWeightDelta))+abs(cashWeightDelta))"
            ),
            "grossTradedNotionalRateReportedSeparately": True,
        },
        "evaluation": {
            "version": EVALUATION_POLICY_VERSION,
            "entry": "FIRST_ELIGIBLE_COMPLETED_SESSION_AFTER_HUMAN_DECISION",
            "maturities": [20, 60, 252, 504, 756],
            "comparators": ["HOLD_CURRENT", "SPY_TOTAL_RETURN"],
            "cashReturn": "0",
            "missingPathForwardFillAllowed": False,
            "modelEvidenceUpgradeAllowed": False,
        },
    }
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return {**value, "policyContentHash": f"sha256:{sha256(canonical.encode()).hexdigest()}"}


def _decimal_text(value: Decimal) -> str:
    if (
        type(value) is not Decimal
        or not value.is_finite()
        or abs(value) > DECIMAL_MAGNITUDE_LIMIT
    ):
        raise PortfolioDecisionContractViolation("decimal is outside the sealed domain")
    if value == 0:
        return "0"
    with localcontext() as context:
        context.prec = 50
        context.rounding = ROUND_HALF_EVEN
        text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text
