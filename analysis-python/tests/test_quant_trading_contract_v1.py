from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from equity_analysis.quant_trading import (
    QuantTradingContractViolation,
    QuantTradingDecisionContractV1,
)

FIXTURE = Path(__file__).parents[2] / "contracts/quant-trading-v1/decision-contract.example.json"


def payload() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def reseal(candidate: dict) -> dict:
    material = {key: value for key, value in candidate.items() if key != "contractContentHash"}
    canonical = json.dumps(
        material, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()
    candidate["contractContentHash"] = f"sha256:{hashlib.sha256(canonical).hexdigest()}"
    return candidate


def test_canonical_contract_is_accepted() -> None:
    contract = QuantTradingDecisionContractV1.parse(payload())
    assert contract.payload["setup"] == "MOMENTUM_CONTINUATION"
    assert contract.payload["validationGovernance"]["initialModelEvidenceLabel"] == "NOT_VALIDATED"


def test_parsed_contract_is_deeply_immutable_and_detached() -> None:
    candidate = payload()
    contract = QuantTradingDecisionContractV1.parse(candidate)
    candidate["setup"] = "MUTATED"
    assert contract.payload["setup"] == "MOMENTUM_CONTINUATION"
    with pytest.raises(TypeError):
        contract.payload["setup"] = "MUTATED"
    assert isinstance(contract.payload["diagnosticHorizons"], tuple)


@pytest.mark.parametrize(
    ("path", "value"),
    (
        (("setup",), "MEAN_REVERSION"),
        (("legacyBoundary", "meanReversionIncluded"), True),
        (("legacyBoundary", "reuseLegacyV21PortfolioTables"), True),
        (("legacyBoundary", "tacticalV22Immutable"), False),
        (("legacyBoundary", "fundamentalValueInputAllowed"), True),
        (("signalTiming", "signalAfterCompletedClose"), False),
        (("signalTiming", "entrySession"), "NEXT_COMPLETED_SESSION_ONLY"),
        (("signalTiming", "entryValidityScheduledSessions"), 1.0),
        (("tradePlan", "maximumHoldingSessions"), 61),
        (("tradePlan", "maximumHoldingSessions"), 60.0),
        (("tradePlan", "entryFillPolicy", "openAboveRangeHigh"), "FILL_AT_OPEN"),
        (("tradePlan", "tradePlanFeasibility", "targets"), "ALLOW_DUPLICATES"),
        (("tradePlan", "tradePlanFeasibility", "invalidPlanEffect"), "CLAMP"),
        (
            ("tradePlan", "entryFillPolicy", "limitTouchCondition"),
            "SESSION_LOW_AT_OR_BELOW_ENTRY_RANGE_LOW",
        ),
        (("tradePlan", "exitExecutionPolicy", "sameBarStopAndTarget"), "TARGET_FIRST"),
        (("tradePlan", "exitExecutionPolicy", "trailingStopEffective"), "SAME_SESSION"),
        (("tradePlan", "exitExecutionPolicy", "targetDisposition"), "PARTIAL_EXIT"),
        (("tradePlan", "positionSizing", "shareRounding"), "FRACTIONAL"),
        (("tradePlan", "positionSizing", "estimatedEntryAndExitCostsReserved"), False),
        (("tradePlan", "candidateSelection", "slotReleasedOnlyAfterExitFill"), False),
        (
            (
                "tradePlan",
                "marketDataAndLifecyclePolicy",
                "separateDividendOrSplitCashFlowApplied",
            ),
            True,
        ),
        (("tradePlan", "marketDataAndLifecyclePolicy", "haltOrSuspensionFillAssumed"), True),
        (("tradePlan", "marketDataAndLifecyclePolicy", "missingTerminalEvidenceEffect"), "ZERO"),
        (("portfolioSimulation", "maximumConcurrentPositions"), 11),
        (("portfolioSimulation", "maximumConcurrentPositions"), 10.0),
        (("portfolioSimulation", "leverageAllowed"), True),
        (("automationBoundary", "executesTrades"), True),
        (("validationGovernance", "diagnosticHorizonsMayValidateModel"), True),
        (("validationGovernance", "perfectPredictionRequired"), True),
    ),
)
def test_frozen_boundaries_fail_closed(path: tuple[str, ...], value: object) -> None:
    candidate = payload()
    target = candidate
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(QuantTradingContractViolation):
        QuantTradingDecisionContractV1.parse(reseal(candidate))


@pytest.mark.parametrize("value", ["0.006", "0.01", 0.005, True, "NaN", "1e-3"])
def test_position_risk_is_exact_strict_decimal(value: object) -> None:
    candidate = payload()
    candidate["tradePlan"]["positionSizing"]["navRiskPerPosition"] = value
    with pytest.raises(QuantTradingContractViolation):
        QuantTradingDecisionContractV1.parse(reseal(candidate))


def test_cost_formula_and_sensitivity_are_frozen() -> None:
    candidate = payload()
    candidate["costPolicy"]["primary"]["impactBps"] = "min(50,20*sqrt(participation))"
    with pytest.raises(QuantTradingContractViolation, match="cost formula"):
        QuantTradingDecisionContractV1.parse(reseal(candidate))
    candidate = payload()
    candidate["costPolicy"]["sensitivity"]["perSideBps"] = "4"
    with pytest.raises(QuantTradingContractViolation, match="5 bps"):
        QuantTradingDecisionContractV1.parse(reseal(candidate))


@pytest.mark.parametrize(
    ("section", "field", "value"),
    (
        ("exitExecutionPolicy", "ordinaryStopTouchFill", "SESSION_CLOSE"),
        (
            "exitExecutionPolicy",
            "reclaimLimitEntryDayExitEvaluation",
            {"sameBarPriority": "TARGET_FIRST"},
        ),
        ("exitExecutionPolicy", "openPhasePriority", ["GAP_THROUGH_STOP"]),
        ("positionSizing", "costSolver", "ROUND_TO_NEAREST_SHARE"),
        ("positionSizing", "decimalContext", "AMBIENT_CONTEXT"),
        ("positionSizing", "estimatedExitLiquidity", "EXIT_DATE_ADTV"),
        ("positionSizing", "riskBudgetIncludesEntryAndEstimatedExitCosts", False),
    ),
)
def test_execution_phase_and_sizing_solver_are_exact(
    section: str, field: str, value: object
) -> None:
    candidate = payload()
    candidate["tradePlan"][section][field] = value
    with pytest.raises(QuantTradingContractViolation):
        QuantTradingDecisionContractV1.parse(reseal(candidate))


def test_v22_identity_and_event_evidence_are_required() -> None:
    candidate = payload()
    candidate["evidenceBoundary"]["requiredIdentifiers"].remove("listingId")
    with pytest.raises(QuantTradingContractViolation, match="identity"):
        QuantTradingDecisionContractV1.parse(reseal(candidate))
    for field in (
        "completedSessionRequired",
        "selectorIdsRequired",
        "corporateActionEvidenceRequired",
    ):
        candidate = payload()
        candidate["evidenceBoundary"][field] = False
        with pytest.raises(QuantTradingContractViolation):
            QuantTradingDecisionContractV1.parse(reseal(candidate))


def test_benchmarks_and_diagnostic_horizons_are_exact() -> None:
    candidate = payload()
    candidate["benchmarkPolicy"]["sector"] = "PRIMARY"
    with pytest.raises(QuantTradingContractViolation, match="Benchmark"):
        QuantTradingDecisionContractV1.parse(reseal(candidate))
    candidate = payload()
    candidate["diagnosticHorizons"] = [20, 60]
    with pytest.raises(QuantTradingContractViolation, match="Diagnostic horizons"):
        QuantTradingDecisionContractV1.parse(reseal(candidate))
    candidate = payload()
    candidate["diagnosticHorizons"] = [5.0, 20, 60]
    with pytest.raises(QuantTradingContractViolation, match="Diagnostic horizons"):
        QuantTradingDecisionContractV1.parse(reseal(candidate))


def test_exact_version_and_evidence_contracts_are_frozen() -> None:
    candidate = payload()
    candidate["evidenceBoundary"]["contractVersion"] = "future-evidence"
    with pytest.raises(QuantTradingContractViolation):
        QuantTradingDecisionContractV1.parse(reseal(candidate))
    candidate = payload()
    candidate["versionSet"]["calendarVersion"] = "future-calendar"
    with pytest.raises(QuantTradingContractViolation, match="Version set"):
        QuantTradingDecisionContractV1.parse(reseal(candidate))


@pytest.mark.parametrize(
    ("section", "field", "value"),
    (
        ("benchmarkPolicy", "cashAnnualRate", "0.04"),
        ("benchmarkPolicy", "equalWeightRebalance", "MONTHLY"),
        ("costPolicy.primary", "perSideBps", "2+impactBps"),
        ("costPolicy.primary", "totalCostRate", "2*entryCostRate"),
        ("costPolicy.primary", "sideRate", "perSideBps/100"),
        ("costPolicy.primary", "sideCostUsd", "orderNotional+sideRate"),
        ("costPolicy.primary", "totalCostUsd", "entrySideCostUsd"),
        ("costPolicy.primary", "sideSpecificInputsRequired", False),
        ("costPolicy.primary", "decimalContext", "AMBIENT_CONTEXT"),
        ("costPolicy.primary", "estimatedExitCostLiquidity", "FUTURE_EXIT_ADTV"),
        ("costPolicy.primary", "monetaryQuantization", "ROUND_TO_CENTS"),
        ("costPolicy.primary", "averageDailyDollarVolume", "CURRENT_SESSION"),
        ("costPolicy.primary", "missingLiquidityEffect", "ZERO"),
    ),
)
def test_benchmark_and_execution_cost_parity_is_frozen(
    section: str, field: str, value: object
) -> None:
    candidate = payload()
    target = candidate
    for key in section.split("."):
        target = target[key]
    target[field] = value
    with pytest.raises(QuantTradingContractViolation):
        QuantTradingDecisionContractV1.parse(reseal(candidate))


def test_unknown_fields_and_hash_drift_fail_closed() -> None:
    candidate = payload()
    candidate["automaticBuy"] = True
    with pytest.raises(QuantTradingContractViolation, match="keys"):
        QuantTradingDecisionContractV1.parse(reseal(candidate))
    candidate = copy.deepcopy(payload())
    candidate["modelVersion"] = "changed-without-resealing"
    with pytest.raises(QuantTradingContractViolation):
        QuantTradingDecisionContractV1.parse(candidate)
