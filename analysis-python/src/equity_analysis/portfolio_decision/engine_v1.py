"""Pure deterministic Portfolio Decision Scenario v1 calculation engine."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal, localcontext
from enum import StrEnum
from hashlib import sha256
from typing import Any
from uuid import UUID

from .contracts_v1 import (
    COST_POLICY_VERSION,
    DECIMAL_MAGNITUDE_LIMIT,
    DECISION_CONTRACT_VERSION,
    CostPolicyV1,
    ScenarioType,
    freeze_decision_policy_v1,
)

ENGINE_VERSION = "PORTFOLIO-DECISION-SCENARIO-ENGINE-v1.0.0"
RESULT_VERSION = "portfolio-decision-scenario-result-v1.0.0"
HASH_PATTERN = re.compile(r"sha256:[0-9a-f]{64}")
DECIMAL_ZERO = Decimal("0")
DECIMAL_ONE = Decimal("1")
RATIO_QUANTUM = Decimal("0.00000000000000000001")
RATIO_POLICY_VERSION = "PORTFOLIO-DECISION-RATIO-SCALE20-HALF-EVEN-v1.0.0"
MODEL_EVIDENCE_LABELS = {
    "NOT_VALIDATED",
    "DEVELOPMENT_OBSERVED",
    "BACKTEST_SUPPORTED",
    "PIT_SUPPORTED",
    "FORWARD_SUPPORTED",
}


class PortfolioScenarioViolation(ValueError):
    """Raised when scenario inputs cross the frozen deterministic boundary."""


class SleeveType(StrEnum):
    LONG_TERM_CORE = "LONG_TERM_CORE"
    QUANT_TRADING = "QUANT_TRADING"
    UNASSIGNED = "UNASSIGNED"


class EvidenceState(StrEnum):
    VALID = "VALID"
    MISSING = "MISSING"
    STALE = "STALE"
    INVALID = "INVALID"


class RebalancePermission(StrEnum):
    LOCKED = "LOCKED"
    BUY_ONLY = "BUY_ONLY"
    SELL_ONLY = "SELL_ONLY"
    BUY_AND_SELL = "BUY_AND_SELL"


class TaxEstimateState(StrEnum):
    NOT_ESTIMATED = "NOT_ESTIMATED"
    AVAILABLE_NOT_APPLIED = "AVAILABLE_NOT_APPLIED"
    AVAILABLE_APPLIED = "AVAILABLE_APPLIED"


@dataclass(frozen=True, slots=True)
class ScenarioConstraintsV1:
    maximum_position_count: int
    maximum_position_weight: Decimal
    maximum_sector_weight: Decimal
    minimum_cash_weight: Decimal
    maximum_leverage_ratio: Decimal
    maximum_speculative_weight: Decimal

    def __post_init__(self) -> None:
        if type(self.maximum_position_count) is not int or self.maximum_position_count <= 0:
            raise PortfolioScenarioViolation("MAXIMUM_POSITION_COUNT_INVALID")
        for value in (
            self.maximum_position_weight,
            self.maximum_sector_weight,
            self.minimum_cash_weight,
            self.maximum_speculative_weight,
        ):
            _bounded_decimal(value, DECIMAL_ZERO, DECIMAL_ONE, "WEIGHT_CONSTRAINT_INVALID")
        _bounded_decimal(
            self.maximum_leverage_ratio,
            DECIMAL_ZERO,
            None,
            "LEVERAGE_CONSTRAINT_INVALID",
        )


@dataclass(frozen=True, slots=True)
class SleeveBudgetV1:
    sleeve: SleeveType
    maximum_weight: Decimal

    def __post_init__(self) -> None:
        if self.sleeve not in (SleeveType.LONG_TERM_CORE, SleeveType.QUANT_TRADING):
            raise PortfolioScenarioViolation("SLEEVE_BUDGET_TYPE_INVALID")
        _bounded_decimal(
            self.maximum_weight, DECIMAL_ZERO, DECIMAL_ONE, "SLEEVE_BUDGET_INVALID"
        )


@dataclass(frozen=True, slots=True)
class ScenarioPositionV1:
    security_id: str
    ticker: str
    sleeve: SleeveType
    sector_code: str
    current_market_value: Decimal | None
    price_state: EvidenceState
    permission: RebalancePermission
    human_approved_candidate: bool
    research_use_allowed: bool
    model_version: str
    model_evidence_label: str
    research_classification: str
    fundamental_value_risk_cap: Decimal | None = None
    target_market_value: Decimal | None = None

    def __post_init__(self) -> None:
        _uuid(self.security_id, "SECURITY_ID_INVALID")
        _atom(self.ticker, "TICKER_INVALID")
        _atom(self.sector_code, "SECTOR_CODE_INVALID")
        _atom(self.model_version, "MODEL_VERSION_INVALID")
        _atom(self.research_classification, "RESEARCH_CLASSIFICATION_INVALID")
        if type(self.sleeve) is not SleeveType or type(self.price_state) is not EvidenceState:
            raise PortfolioScenarioViolation("POSITION_ENUM_INVALID")
        if type(self.permission) is not RebalancePermission:
            raise PortfolioScenarioViolation("PERMISSION_INVALID")
        if type(self.human_approved_candidate) is not bool or type(
            self.research_use_allowed
        ) is not bool:
            raise PortfolioScenarioViolation("POSITION_BOOLEAN_INVALID")
        if self.model_evidence_label not in MODEL_EVIDENCE_LABELS:
            raise PortfolioScenarioViolation("MODEL_EVIDENCE_LABEL_INVALID")
        if self.price_state is EvidenceState.VALID:
            _bounded_decimal(
                self.current_market_value,
                DECIMAL_ZERO,
                None,
                "CURRENT_MARKET_VALUE_INVALID",
            )
        elif self.current_market_value is not None:
            raise PortfolioScenarioViolation("NONVALID_PRICE_VALUE_MUST_BE_NULL")
        if self.fundamental_value_risk_cap is not None:
            _bounded_decimal(
                self.fundamental_value_risk_cap,
                DECIMAL_ZERO,
                DECIMAL_ONE,
                "FUNDAMENTAL_VALUE_RISK_CAP_INVALID",
            )
            if self.sleeve is not SleeveType.LONG_TERM_CORE:
                raise PortfolioScenarioViolation("RISK_CAP_SLEEVE_INVALID")
        if self.target_market_value is not None:
            _bounded_decimal(
                self.target_market_value,
                DECIMAL_ZERO,
                None,
                "TARGET_MARKET_VALUE_INVALID",
            )
        if self.model_version == "QUANT-TRADING-v2.0.0" and self.research_use_allowed:
            raise PortfolioScenarioViolation("QUANT_V2_RESEARCH_AUTHORITY_FORBIDDEN")
        if self.sleeve is SleeveType.LONG_TERM_CORE:
            if self.model_version != "FUNDAMENTAL-VALUE-v1.0.0":
                raise PortfolioScenarioViolation("FUNDAMENTAL_MODEL_BINDING_INVALID")
        elif self.sleeve is SleeveType.QUANT_TRADING:
            if self.model_version not in {
                "QUANT-TRADING-v1.1.0",
                "QUANT-TRADING-v2.0.0",
            } or self.research_classification not in {
                "ENTRY_CANDIDATE",
                "HOLD_REVIEW",
                "EXIT_REVIEW",
                "NO_SIGNAL",
                "NOT_APPLICABLE",
                "INSUFFICIENT_EVIDENCE",
            }:
                raise PortfolioScenarioViolation("QUANT_MODEL_BINDING_INVALID")
        elif (
            self.model_version != "NO_MODEL"
            or self.research_classification != "NOT_APPLICABLE"
            or self.research_use_allowed
            or self.fundamental_value_risk_cap is not None
        ):
            raise PortfolioScenarioViolation("UNASSIGNED_MODEL_BINDING_INVALID")


@dataclass(frozen=True, slots=True)
class PortfolioScenarioInputV1:
    contract_version: str
    scenario_type: ScenarioType
    portfolio_context_hash: str
    constraint_policy_hash: str
    decision_policy_hash: str
    current_cash: Decimal
    liability_value: Decimal
    new_money_amount: Decimal
    positions: tuple[ScenarioPositionV1, ...]
    sleeve_budgets: tuple[SleeveBudgetV1, ...]
    constraints: ScenarioConstraintsV1
    cost_policy: CostPolicyV1
    tax_estimate_state: TaxEstimateState
    tax_estimate_amount: Decimal | None
    tax_lot_evidence_hash: str | None

    def __post_init__(self) -> None:
        if self.contract_version != DECISION_CONTRACT_VERSION:
            raise PortfolioScenarioViolation("SCENARIO_CONTRACT_VERSION_UNSUPPORTED")
        if type(self.scenario_type) is not ScenarioType:
            raise PortfolioScenarioViolation("SCENARIO_TYPE_INVALID")
        for value in (
            self.portfolio_context_hash,
            self.constraint_policy_hash,
        ):
            if type(value) is not str or HASH_PATTERN.fullmatch(value) is None:
                raise PortfolioScenarioViolation("SCENARIO_HASH_INVALID")
        if self.decision_policy_hash != freeze_decision_policy_v1(self.cost_policy)[
            "policyContentHash"
        ]:
            raise PortfolioScenarioViolation("DECISION_POLICY_HASH_MISMATCH")
        _bounded_decimal(self.current_cash, DECIMAL_ZERO, None, "CURRENT_CASH_INVALID")
        _bounded_decimal(self.liability_value, DECIMAL_ZERO, None, "LIABILITY_INVALID")
        _bounded_decimal(
            self.new_money_amount, DECIMAL_ZERO, None, "NEW_MONEY_AMOUNT_INVALID"
        )
        if type(self.positions) is not tuple or type(self.sleeve_budgets) is not tuple:
            raise PortfolioScenarioViolation("SCENARIO_COLLECTION_MUST_BE_TUPLE")
        security_ids = tuple(item.security_id for item in self.positions)
        if security_ids != tuple(sorted(security_ids)):
            raise PortfolioScenarioViolation("POSITIONS_NOT_CANONICALLY_ORDERED")
        if len(security_ids) != len(set(security_ids)):
            raise PortfolioScenarioViolation("DUPLICATE_SCENARIO_SECURITY")
        sleeves = tuple(item.sleeve for item in self.sleeve_budgets)
        if sleeves != (SleeveType.LONG_TERM_CORE, SleeveType.QUANT_TRADING):
            raise PortfolioScenarioViolation("SLEEVE_BUDGET_SET_INCOMPLETE")
        if type(self.tax_estimate_state) is not TaxEstimateState:
            raise PortfolioScenarioViolation("TAX_ESTIMATE_STATE_INVALID")
        if self.tax_estimate_state is TaxEstimateState.NOT_ESTIMATED:
            if self.tax_estimate_amount is not None:
                raise PortfolioScenarioViolation("UNAVAILABLE_TAX_AMOUNT_MUST_BE_NULL")
        else:
            _bounded_decimal(
                self.tax_estimate_amount,
                DECIMAL_ZERO,
                None,
                "TAX_ESTIMATE_AMOUNT_INVALID",
            )
        if self.tax_lot_evidence_hash is not None and (
            type(self.tax_lot_evidence_hash) is not str
            or HASH_PATTERN.fullmatch(self.tax_lot_evidence_hash) is None
        ):
            raise PortfolioScenarioViolation("TAX_LOT_EVIDENCE_HASH_INVALID")
        if self.tax_estimate_state is TaxEstimateState.AVAILABLE_APPLIED:
            if self.tax_lot_evidence_hash is None:
                raise PortfolioScenarioViolation("APPLIED_TAX_REQUIRES_LOT_EVIDENCE")
        elif self.tax_lot_evidence_hash is not None:
            raise PortfolioScenarioViolation("UNAPPLIED_TAX_LOT_EVIDENCE_FORBIDDEN")
        if self.cost_policy.tax_estimate_state != self.tax_estimate_state.value:
            raise PortfolioScenarioViolation("TAX_POLICY_STATE_MISMATCH")
        if self.cost_policy.impact_state != "NOT_ESTIMATED":
            raise PortfolioScenarioViolation("IMPACT_EVIDENCE_CONTRACT_NOT_IMPLEMENTED")
        if self.scenario_type is ScenarioType.HOLD_CURRENT and self.new_money_amount != 0:
            raise PortfolioScenarioViolation("HOLD_CURRENT_NEW_MONEY_FORBIDDEN")
        if (
            self.scenario_type is ScenarioType.HOLD_CURRENT
            and self.tax_estimate_state is TaxEstimateState.AVAILABLE_APPLIED
        ):
            raise PortfolioScenarioViolation("HOLD_CURRENT_APPLIED_TAX_FORBIDDEN")
        requires_targets = self.scenario_type in {
            ScenarioType.CONSTRAINED_REBALANCE,
            ScenarioType.TARGET_PORTFOLIO,
        }
        if requires_targets and any(item.target_market_value is None for item in self.positions):
            raise PortfolioScenarioViolation("EXACT_TARGET_SET_REQUIRED")
        if not requires_targets and any(
            item.target_market_value is not None for item in self.positions
        ):
            raise PortfolioScenarioViolation("TARGETS_NOT_ALLOWED_FOR_SCENARIO")


@dataclass(frozen=True, slots=True)
class PortfolioScenarioResultV1:
    payload: dict[str, Any]


def calculate_portfolio_scenario_v1(
    value: PortfolioScenarioInputV1,
) -> PortfolioScenarioResultV1:
    """Calculate one deterministic, non-authoritative scenario candidate."""

    if type(value) is not PortfolioScenarioInputV1:
        raise PortfolioScenarioViolation("SCENARIO_INPUT_TYPE_INVALID")
    with localcontext() as context:
        context.prec = 50
        context.rounding = ROUND_HALF_EVEN
        input_hash = _content_hash(_input_body(value))
        if value.scenario_type is ScenarioType.HOLD_CURRENT:
            if any(item.price_state is not EvidenceState.VALID for item in value.positions):
                return _partial_hold(value, input_hash)
            targets = {
                item.security_id: item.current_market_value for item in value.positions
            }
            reasons: list[str] = []
        elif any(item.price_state is not EvidenceState.VALID for item in value.positions):
            return _infeasible(value, input_hash, ["INCOMPLETE_PRICE_EVIDENCE"])
        elif value.scenario_type is ScenarioType.NEW_MONEY_ONLY:
            targets, reasons = _new_money_targets(value)
        else:
            targets = {
                item.security_id: item.target_market_value for item in value.positions
            }
            reasons = _target_semantic_reasons(value, targets)
        if reasons:
            return _infeasible(value, input_hash, reasons)
        assert all(target is not None for target in targets.values())
        complete_targets = {key: target for key, target in targets.items() if target is not None}
        return _evaluate_candidate(value, input_hash, complete_targets)


def _new_money_targets(
    value: PortfolioScenarioInputV1,
) -> tuple[dict[str, Decimal | None], list[str]]:
    targets = {item.security_id: item.current_market_value for item in value.positions}
    if value.new_money_amount == 0:
        return targets, []
    candidates = tuple(item for item in value.positions if _increase_eligible(item))
    if not candidates:
        return targets, ["NO_HUMAN_APPROVED_ELIGIBLE_CANDIDATE"]
    current_invested = sum(
        (item.current_market_value or DECIMAL_ZERO for item in value.positions), DECIMAL_ZERO
    )
    pre_cost_assets = value.current_cash + value.new_money_amount + current_invested
    rate = _cost_rate(value.cost_policy)
    contribution_capacity = value.new_money_amount / (DECIMAL_ONE + rate)
    cash_floor_capacity = max(
        DECIMAL_ZERO,
        (
            value.current_cash
            + value.new_money_amount
            - value.constraints.minimum_cash_weight * pre_cost_assets
        )
        / (
            DECIMAL_ONE
            + rate
            - value.constraints.minimum_cash_weight * rate
        ),
    )
    deployable = min(contribution_capacity, cash_floor_capacity)
    minimum_assets = pre_cost_assets - deployable * rate
    headrooms: dict[str, Decimal] = {}
    sector_current: dict[str, Decimal] = {}
    sleeve_current: dict[SleeveType, Decimal] = {}
    for item in value.positions:
        current = item.current_market_value or DECIMAL_ZERO
        sector_current[item.sector_code] = sector_current.get(item.sector_code, 0) + current
        sleeve_current[item.sleeve] = sleeve_current.get(item.sleeve, 0) + current
    budget_map = {item.sleeve: item.maximum_weight for item in value.sleeve_budgets}
    current_position_count = sum(
        1 for item in value.positions if (item.current_market_value or DECIMAL_ZERO) > 0
    )
    remaining_slots = max(
        0, value.constraints.maximum_position_count - current_position_count
    )
    zero_value_ids = tuple(
        item.security_id
        for item in candidates
        if (item.current_market_value or DECIMAL_ZERO) == 0
    )
    admitted_zero_ids = set(zero_value_ids[:remaining_slots])
    candidates = tuple(
        item
        for item in candidates
        if (item.current_market_value or DECIMAL_ZERO) > 0
        or item.security_id in admitted_zero_ids
    )
    if not candidates:
        return targets, ["MAXIMUM_POSITION_COUNT_PREVENTS_NEW_CANDIDATE"]
    for item in candidates:
        current = item.current_market_value or DECIMAL_ZERO
        headroom_caps = [
            value.constraints.maximum_position_weight * minimum_assets - current
        ]
        if item.fundamental_value_risk_cap is not None:
            headroom_caps.append(
                item.fundamental_value_risk_cap * minimum_assets - current
            )
        headrooms[item.security_id] = max(DECIMAL_ZERO, min(headroom_caps))
    sector_capacities = {
        sector: max(
            DECIMAL_ZERO,
            value.constraints.maximum_sector_weight * minimum_assets - current,
        )
        for sector, current in sector_current.items()
    }
    sleeve_capacities = {
        sleeve: max(
            DECIMAL_ZERO,
            min(
                budget_map.get(sleeve, DECIMAL_ONE),
                (
                    value.constraints.maximum_speculative_weight
                    if sleeve is SleeveType.QUANT_TRADING
                    else DECIMAL_ONE
                ),
            )
            * minimum_assets
            - current,
        )
        for sleeve, current in sleeve_current.items()
    }
    allocations = _equal_water_fill(
        deployable,
        candidates,
        headrooms,
        sector_capacities,
        sleeve_capacities,
    )
    for item in candidates:
        targets[item.security_id] = (item.current_market_value or DECIMAL_ZERO) + allocations[
            item.security_id
        ]
    return targets, []


def _equal_water_fill(
    amount: Decimal,
    candidates: tuple[ScenarioPositionV1, ...],
    headrooms: dict[str, Decimal],
    sector_capacities: dict[str, Decimal],
    sleeve_capacities: dict[SleeveType, Decimal],
) -> dict[str, Decimal]:
    allocations = {item.security_id: DECIMAL_ZERO for item in candidates}
    active = [item.security_id for item in candidates if headrooms[item.security_id] > 0]
    remaining = amount
    while active and remaining > 0:
        by_id = {item.security_id: item for item in candidates}
        sector_counts = {
            sector: sum(1 for item_id in active if by_id[item_id].sector_code == sector)
            for sector in sector_capacities
        }
        sleeve_counts = {
            sleeve: sum(1 for item_id in active if by_id[item_id].sleeve is sleeve)
            for sleeve in sleeve_capacities
        }
        step_caps = [remaining / Decimal(len(active))]
        step_caps.extend(headrooms[item_id] - allocations[item_id] for item_id in active)
        step_caps.extend(
            capacity / Decimal(sector_counts[sector])
            for sector, capacity in sector_capacities.items()
            if sector_counts[sector] > 0
        )
        step_caps.extend(
            capacity / Decimal(sleeve_counts[sleeve])
            for sleeve, capacity in sleeve_capacities.items()
            if sleeve_counts[sleeve] > 0
        )
        step = max(DECIMAL_ZERO, min(step_caps))
        if step == 0:
            break
        for item_id in active:
            item = by_id[item_id]
            allocations[item_id] += step
            sector_capacities[item.sector_code] -= step
            sleeve_capacities[item.sleeve] -= step
        remaining -= step * Decimal(len(active))
        active = [
            item_id
            for item_id in active
            if headrooms[item_id] > allocations[item_id]
            and sector_capacities[by_id[item_id].sector_code] > 0
            and sleeve_capacities[by_id[item_id].sleeve] > 0
        ]
    return allocations


def _increase_eligible(item: ScenarioPositionV1) -> bool:
    if (
        item.price_state is not EvidenceState.VALID
        or not item.human_approved_candidate
        or not item.research_use_allowed
        or item.permission not in {
            RebalancePermission.BUY_ONLY,
            RebalancePermission.BUY_AND_SELL,
        }
    ):
        return False
    if item.sleeve is SleeveType.LONG_TERM_CORE:
        return (
            item.model_version == "FUNDAMENTAL-VALUE-v1.0.0"
            and item.fundamental_value_risk_cap is not None
        )
    if item.sleeve is SleeveType.QUANT_TRADING:
        return (
            item.model_version != "QUANT-TRADING-v2.0.0"
            and item.research_classification == "ENTRY_CANDIDATE"
        )
    return False


def _target_semantic_reasons(
    value: PortfolioScenarioInputV1,
    targets: dict[str, Decimal | None],
) -> list[str]:
    reasons: set[str] = set()
    for item in value.positions:
        current = item.current_market_value
        target = targets[item.security_id]
        assert current is not None and target is not None
        delta = target - current
        permission_blocks_change = False
        if value.scenario_type in {
            ScenarioType.CONSTRAINED_REBALANCE,
            ScenarioType.TARGET_PORTFOLIO,
        }:
            if item.permission is RebalancePermission.LOCKED and delta != 0:
                reasons.add("LOCKED_POSITION_CHANGE_FORBIDDEN")
                permission_blocks_change = True
            if item.permission is RebalancePermission.BUY_ONLY and delta < 0:
                reasons.add("BUY_ONLY_POSITION_SALE_FORBIDDEN")
                permission_blocks_change = True
            if item.permission is RebalancePermission.SELL_ONLY and delta > 0:
                reasons.add("SELL_ONLY_POSITION_INCREASE_FORBIDDEN")
                permission_blocks_change = True
        if delta > 0 and not permission_blocks_change and not _increase_eligible(item):
            reasons.add("POSITION_INCREASE_NOT_EVIDENCE_AUTHORIZED")
    return sorted(reasons)


def _evaluate_candidate(
    value: PortfolioScenarioInputV1,
    input_hash: str,
    targets: dict[str, Decimal],
) -> PortfolioScenarioResultV1:
    current = {
        item.security_id: item.current_market_value or DECIMAL_ZERO for item in value.positions
    }
    buys = sum((max(DECIMAL_ZERO, targets[key] - current[key]) for key in targets), 0)
    sells = sum((max(DECIMAL_ZERO, current[key] - targets[key]) for key in targets), 0)
    if value.tax_estimate_state is TaxEstimateState.AVAILABLE_APPLIED and sells == 0:
        return _infeasible(
            value, input_hash, ["APPLIED_TAX_REQUIRES_MODELED_SALE"]
        )
    traded = buys + sells
    estimated_cost = traded * _cost_rate(value.cost_policy)
    applied_tax = (
        value.tax_estimate_amount or DECIMAL_ZERO
        if value.tax_estimate_state is TaxEstimateState.AVAILABLE_APPLIED
        else DECIMAL_ZERO
    )
    final_cash = (
        value.current_cash
        + value.new_money_amount
        + sells
        - buys
        - estimated_cost
        - applied_tax
    )
    final_assets = final_cash + sum(targets.values(), DECIMAL_ZERO)
    reasons = _constraint_reasons(value, targets, final_cash, final_assets)
    if reasons and value.scenario_type is not ScenarioType.HOLD_CURRENT:
        return _infeasible(value, input_hash, reasons)
    pre_cost_assets = (
        value.current_cash
        + value.new_money_amount
        + sum(current.values(), DECIMAL_ZERO)
    )
    if pre_cost_assets <= 0 or final_assets <= 0:
        return _infeasible(value, input_hash, ["PORTFOLIO_ASSET_VALUE_NOT_POSITIVE"])
    current_cash_weight = _ratio(value.current_cash + value.new_money_amount, pre_cost_assets)
    final_cash_weight = _ratio(final_cash, final_assets)
    one_way_turnover = _ratio(
        sum(
            (
                abs(
                    _ratio(targets[key], final_assets)
                    - _ratio(current[key], pre_cost_assets)
                )
                for key in targets
            ),
            DECIMAL_ZERO,
        )
        + abs(final_cash_weight - current_cash_weight),
        Decimal("2"),
    )
    rows = [
        {
            "securityId": item.security_id,
            "ticker": item.ticker,
            "sleeve": item.sleeve.value,
            "sectorCode": item.sector_code,
            "modelEvidenceLabel": item.model_evidence_label,
            "currentMarketValue": _text(item.current_market_value),
            "targetMarketValue": _text(targets[item.security_id]),
            "deltaNotional": _text(targets[item.security_id] - current[item.security_id]),
            "finalAssetWeight": _text(_ratio(targets[item.security_id], final_assets)),
        }
        for item in value.positions
    ]
    body: dict[str, Any] = {
        "resultVersion": RESULT_VERSION,
        "engineVersion": ENGINE_VERSION,
        "contractVersion": DECISION_CONTRACT_VERSION,
        "scenarioType": value.scenario_type.value,
        "inputContentHash": input_hash,
        "status": "CANDIDATE_FOR_HUMAN_REVIEW",
        "reasonCodes": reasons,
        "positions": rows,
        "economics": {
            "grossBuyNotional": _text(buys),
            "grossSellNotional": _text(sells),
            "grossTradedNotional": _text(traded),
            "estimatedTransactionAndSlippageCost": _text(estimated_cost),
            "impactState": value.cost_policy.impact_state,
            "taxEstimateState": value.tax_estimate_state.value,
            "taxEstimateAmount": _text(value.tax_estimate_amount),
            "appliedTaxAmount": _text(applied_tax),
            "oneWayWeightTurnover": _text(one_way_turnover),
            "grossTradedNotionalRate": _text(traded / pre_cost_assets),
            "finalCash": _text(final_cash),
            "finalAssetValue": _text(final_assets),
        },
        "constraintStatus": "VIOLATED" if reasons else "PASSED",
        "authority": _authority(),
    }
    body["contentHash"] = _content_hash(body)
    return PortfolioScenarioResultV1(body)


def _constraint_reasons(
    value: PortfolioScenarioInputV1,
    targets: dict[str, Decimal],
    final_cash: Decimal,
    final_assets: Decimal,
) -> list[str]:
    if final_cash < 0 or final_assets <= 0 or final_assets <= value.liability_value:
        return ["FINAL_CASH_OR_NET_ASSET_VALUE_INVALID"]
    reasons: set[str] = set()
    positive = tuple(amount for amount in targets.values() if amount > 0)
    if len(positive) > value.constraints.maximum_position_count:
        reasons.add("MAXIMUM_POSITION_COUNT_EXCEEDED")
    for amount in positive:
        if amount / final_assets > value.constraints.maximum_position_weight:
            reasons.add("MAXIMUM_POSITION_WEIGHT_EXCEEDED")
    sectors: dict[str, Decimal] = {}
    sleeves: dict[SleeveType, Decimal] = {}
    for item in value.positions:
        amount = targets[item.security_id]
        sectors[item.sector_code] = sectors.get(item.sector_code, 0) + amount
        sleeves[item.sleeve] = sleeves.get(item.sleeve, 0) + amount
        if (
            item.sleeve is SleeveType.LONG_TERM_CORE
            and item.fundamental_value_risk_cap is not None
            and amount > (item.fundamental_value_risk_cap * final_assets)
        ):
            reasons.add("FUNDAMENTAL_VALUE_RISK_CAP_EXCEEDED")
    if any(
        amount / final_assets > value.constraints.maximum_sector_weight
        for amount in sectors.values()
    ):
        reasons.add("MAXIMUM_SECTOR_WEIGHT_EXCEEDED")
    if final_cash / final_assets < value.constraints.minimum_cash_weight:
        reasons.add("MINIMUM_CASH_WEIGHT_VIOLATED")
    net_value = final_assets - value.liability_value
    if value.liability_value / net_value > value.constraints.maximum_leverage_ratio:
        reasons.add("MAXIMUM_LEVERAGE_RATIO_EXCEEDED")
    quant_weight = sleeves.get(SleeveType.QUANT_TRADING, DECIMAL_ZERO) / final_assets
    if quant_weight > value.constraints.maximum_speculative_weight:
        reasons.add("MAXIMUM_SPECULATIVE_WEIGHT_EXCEEDED")
    for budget in value.sleeve_budgets:
        if sleeves.get(budget.sleeve, DECIMAL_ZERO) / final_assets > budget.maximum_weight:
            reasons.add(f"{budget.sleeve.value}_BUDGET_EXCEEDED")
    return sorted(reasons)


def _infeasible(
    value: PortfolioScenarioInputV1,
    input_hash: str,
    reasons: list[str],
) -> PortfolioScenarioResultV1:
    body: dict[str, Any] = {
        "resultVersion": RESULT_VERSION,
        "engineVersion": ENGINE_VERSION,
        "contractVersion": DECISION_CONTRACT_VERSION,
        "scenarioType": value.scenario_type.value,
        "inputContentHash": input_hash,
        "status": "NO_FEASIBLE_CANDIDATE",
        "reasonCodes": sorted(set(reasons)),
        "positions": [],
        "economics": None,
        "constraintStatus": "NOT_EVALUATED",
        "authority": _authority(),
    }
    body["contentHash"] = _content_hash(body)
    return PortfolioScenarioResultV1(body)


def _partial_hold(
    value: PortfolioScenarioInputV1, input_hash: str
) -> PortfolioScenarioResultV1:
    rows = [
        {
            "securityId": item.security_id,
            "ticker": item.ticker,
            "sleeve": item.sleeve.value,
            "sectorCode": item.sector_code,
            "modelEvidenceLabel": item.model_evidence_label,
            "priceState": item.price_state.value,
            "currentMarketValue": _text(item.current_market_value),
            "targetMarketValue": _text(item.current_market_value),
            "deltaNotional": "0" if item.current_market_value is not None else None,
            "finalAssetWeight": None,
        }
        for item in value.positions
    ]
    body: dict[str, Any] = {
        "resultVersion": RESULT_VERSION,
        "engineVersion": ENGINE_VERSION,
        "contractVersion": DECISION_CONTRACT_VERSION,
        "scenarioType": value.scenario_type.value,
        "inputContentHash": input_hash,
        "status": "CANDIDATE_FOR_HUMAN_REVIEW",
        "reasonCodes": ["HOLD_CURRENT_PARTIAL_PRICE_EVIDENCE"],
        "positions": rows,
        "economics": {
            "grossBuyNotional": "0",
            "grossSellNotional": "0",
            "grossTradedNotional": "0",
            "estimatedTransactionAndSlippageCost": "0",
            "impactState": value.cost_policy.impact_state,
            "taxEstimateState": value.tax_estimate_state.value,
            "taxEstimateAmount": _text(value.tax_estimate_amount),
            "appliedTaxAmount": "0",
            "oneWayWeightTurnover": "0",
            "grossTradedNotionalRate": "0",
            "finalCash": _text(value.current_cash),
            "finalAssetValue": None,
        },
        "constraintStatus": "PARTIAL_NOT_EVALUATED",
        "authority": _authority(),
    }
    body["contentHash"] = _content_hash(body)
    return PortfolioScenarioResultV1(body)


def _authority() -> dict[str, bool]:
    return {
        "candidateForHumanReviewOnly": True,
        "finalWeightAuthority": False,
        "orderAuthority": False,
        "automaticBrokerageExecution": False,
        "llmDecisionAuthority": False,
        "humanDecisionRequired": True,
    }


def _input_body(value: PortfolioScenarioInputV1) -> dict[str, Any]:
    return {
        "contractVersion": value.contract_version,
        "scenarioType": value.scenario_type.value,
        "portfolioContextHash": value.portfolio_context_hash,
        "constraintPolicyHash": value.constraint_policy_hash,
        "decisionPolicyHash": value.decision_policy_hash,
        "currentCash": _text(value.current_cash),
        "liabilityValue": _text(value.liability_value),
        "newMoneyAmount": _text(value.new_money_amount),
        "positions": [
            {
                "securityId": item.security_id,
                "ticker": item.ticker,
                "sleeve": item.sleeve.value,
                "sectorCode": item.sector_code,
                "currentMarketValue": _text(item.current_market_value),
                "priceState": item.price_state.value,
                "permission": item.permission.value,
                "humanApprovedCandidate": item.human_approved_candidate,
                "researchUseAllowed": item.research_use_allowed,
                "modelVersion": item.model_version,
                "modelEvidenceLabel": item.model_evidence_label,
                "researchClassification": item.research_classification,
                "fundamentalValueRiskCap": _text(item.fundamental_value_risk_cap),
                "targetMarketValue": _text(item.target_market_value),
            }
            for item in value.positions
        ],
        "sleeveBudgets": [
            {"sleeve": item.sleeve.value, "maximumWeight": _text(item.maximum_weight)}
            for item in value.sleeve_budgets
        ],
        "constraints": {
            "maximumPositionCount": value.constraints.maximum_position_count,
            "maximumPositionWeight": _text(value.constraints.maximum_position_weight),
            "maximumSectorWeight": _text(value.constraints.maximum_sector_weight),
            "minimumCashWeight": _text(value.constraints.minimum_cash_weight),
            "maximumLeverageRatio": _text(value.constraints.maximum_leverage_ratio),
            "maximumSpeculativeWeight": _text(
                value.constraints.maximum_speculative_weight
            ),
        },
        "costPolicy": {
            "version": COST_POLICY_VERSION,
            "transactionCostBps": _text(value.cost_policy.transaction_cost_bps),
            "slippageBps": _text(value.cost_policy.slippage_bps),
            "impactState": value.cost_policy.impact_state,
            "taxEstimateState": value.cost_policy.tax_estimate_state,
        },
        "taxEstimateState": value.tax_estimate_state.value,
        "taxEstimateAmount": _text(value.tax_estimate_amount),
        "taxLotEvidenceHash": value.tax_lot_evidence_hash,
    }


def _cost_rate(value: CostPolicyV1) -> Decimal:
    return (value.transaction_cost_bps + value.slippage_bps) / Decimal("10000")


def _ratio(numerator: Decimal, denominator: Decimal) -> Decimal:
    """Apply the frozen cross-language scale-20 half-even ratio policy."""

    if denominator == 0:
        raise PortfolioScenarioViolation("RATIO_DENOMINATOR_ZERO")
    with localcontext() as context:
        context.prec = 250
        context.rounding = ROUND_HALF_EVEN
        return (numerator / denominator).quantize(
            RATIO_QUANTUM,
            rounding=ROUND_HALF_EVEN,
        )


def _content_hash(value: dict[str, Any]) -> str:
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return f"sha256:{sha256(canonical.encode()).hexdigest()}"


def _text(value: Decimal | None) -> str | None:
    if value is None:
        return None
    _bounded_decimal(value, None, None, "DECIMAL_SERIALIZATION_INVALID")
    if value == 0:
        return "0"
    with localcontext() as context:
        context.prec = 50
        context.rounding = ROUND_HALF_EVEN
        text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _bounded_decimal(
    value: Decimal | None,
    minimum: Decimal | None,
    maximum: Decimal | None,
    reason: str,
) -> Decimal:
    if (
        type(value) is not Decimal
        or not value.is_finite()
        or abs(value) > DECIMAL_MAGNITUDE_LIMIT
    ):
        raise PortfolioScenarioViolation(reason)
    if minimum is not None and value < minimum:
        raise PortfolioScenarioViolation(reason)
    if maximum is not None and value > maximum:
        raise PortfolioScenarioViolation(reason)
    return value


def _uuid(value: str, reason: str) -> None:
    if type(value) is not str:
        raise PortfolioScenarioViolation(reason)
    try:
        parsed = UUID(value)
    except (ValueError, AttributeError) as exc:
        raise PortfolioScenarioViolation(reason) from exc
    if str(parsed) != value:
        raise PortfolioScenarioViolation(reason)


def _atom(value: str, reason: str) -> None:
    if type(value) is not str or value.strip(" \t\n\r\f\v") == "" or "|" in value:
        raise PortfolioScenarioViolation(reason)
