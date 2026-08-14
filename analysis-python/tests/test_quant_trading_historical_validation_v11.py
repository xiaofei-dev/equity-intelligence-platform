from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from equity_analysis.quant_trading.historical_validation_v11 import (
    BATCHES,
    PROTOCOL_STATE,
    PROTOCOL_VERSION,
    V11_FIXED_COST_POLICY_VERSION,
    V11_PRIMARY_COST_POLICY_VERSION,
    V11_SIMULATOR_VERSION,
    QuantHistoricalValidationV11Violation,
    batch_for_ordinal,
    canonical_hash,
    frozen_protocol,
    population_order_key,
    validate_protocol,
)
from equity_analysis.quant_trading.simulator_v11 import (
    COST_POLICY_VERSION,
    FIXED_FIVE_BPS_COST_POLICY_VERSION,
    SIMULATOR_VERSION,
)
from equity_analysis.quant_trading.successor_v11 import frozen_v11_contract

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = (
    ROOT
    / "contracts"
    / "quant-trading-v1"
    / "historical-validation-protocol-v1.1.json"
)
SOURCE = (
    ROOT
    / "analysis-python"
    / "src"
    / "equity_analysis"
    / "quant_trading"
    / "historical_validation_v11.py"
)


def test_canonical_fixture_is_the_exact_frozen_protocol() -> None:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert fixture == frozen_protocol()
    claimed = fixture.pop("contentHash")
    assert claimed == canonical_hash(fixture)
    assert fixture["schemaVersion"] == PROTOCOL_VERSION
    assert fixture["state"] == PROTOCOL_STATE


def test_successor_contract_and_controlled_inputs_are_exactly_bound() -> None:
    protocol = frozen_protocol()
    successor = frozen_v11_contract()
    binding = protocol["controlledBindings"]["successorDecisionContract"]
    assert binding == {
        key: successor[key]
        for key in (
            "contractVersion",
            "modelVersion",
            "strategyVersion",
            "formulaVersion",
            "entryExitPolicyVersion",
            "engineVersion",
            "contentHash",
        )
    }
    assert binding["contentHash"] == (
        "BF9BF8D473CA10C0944E2F900824CE2B64B22C8778684E32AA4E5056CF5BE954"
    )
    simulator = protocol["controlledBindings"]["simulator"]
    assert V11_SIMULATOR_VERSION == SIMULATOR_VERSION
    assert V11_PRIMARY_COST_POLICY_VERSION == COST_POLICY_VERSION
    assert V11_FIXED_COST_POLICY_VERSION == FIXED_FIVE_BPS_COST_POLICY_VERSION
    assert simulator["version"] == SIMULATOR_VERSION
    assert simulator["primaryCostPolicyVersion"] == COST_POLICY_VERSION
    assert simulator["fixedSensitivityCostPolicyVersion"] == (
        FIXED_FIVE_BPS_COST_POLICY_VERSION
    )
    population = protocol["controlledBindings"]["population"]
    assert population["count"] == 191
    assert population["identitySetHash"] == (
        "B29306CE3B1A047C074B68FDA07149FFF72F7B2ECD2BC0D78AAD7B42692656C7"
    )
    assert population["predictorValuesUsed"] is False
    price = protocol["controlledBindings"]["priceEvidence"]
    assert price["receiptHash"] == (
        "B74761883F9395F1334B3F78983DB4237DF0F3F245F449EFFDC73F98FBB738AD"
    )
    assert price["calendarHash"] == (
        "7FE1CA16970AE0346C67120DD4F32BA3BEF039276B9800757D15D3744189AA2C"
    )


def test_post_v1_same_history_claims_are_fail_closed() -> None:
    awareness = frozen_protocol()["outcomeAwareness"]
    assert awareness["v1OutcomeObservedBeforeV11Design"] is True
    assert awareness["v11NumericPricesReadBeforeSeal"] is False
    assert awareness["v11OutcomeMetricsReadBeforeSeal"] is False
    assert awareness["sameControlledHistoryReused"] is True
    assert awareness["sameHistoryUntouchedHoldoutClaimed"] is False
    assert awareness["strictPitClaimed"] is False
    assert awareness["backtestSupportedClaimed"] is False
    assert awareness["forwardSupportedClaimed"] is False
    assert awareness["maximumSameHistoryClaim"] == (
        "DEVELOPMENT_OBSERVED_SAME_HISTORY_POST_V1_OUTCOME"
    )
    assert awareness["failedValidationMayTriggerSameOutcomeRetuning"] is False
    assert awareness["payloadBytesExposeHistoricalBarsAfterIntent"] is True
    assert awareness["prePerformanceSealDoesNotClaimBarsWereUnavailableToProcess"] is True
    assert (
        awareness[
            "returnsPnlRanksAgainstFutureReturnsOrAcceptanceInspectedBeforeInputSeal"
        ]
        is False
    )
    acceptance = frozen_protocol()["acceptance"]
    assert acceptance["modelEvidenceLabelAfterAnyResult"] == "NOT_VALIDATED"
    assert acceptance["claimUpgradeAllowed"] is False
    assert acceptance["productionOrBrokerageAuthorization"] is False


def test_batch_progression_is_nested_and_performance_blind_until_full191() -> None:
    assert tuple(
        (item.code, item.cumulative_count, item.incremental_count, item.performance_gate)
        for item in BATCHES
    ) == (
        ("PILOT25", 25, 25, False),
        ("EXPANSION100", 100, 75, False),
        ("FULL191", 191, 91, True),
    )
    assert batch_for_ordinal(1) == batch_for_ordinal(25) == "PILOT25"
    assert batch_for_ordinal(26) == batch_for_ordinal(100) == "EXPANSION100"
    assert batch_for_ordinal(101) == batch_for_ordinal(191) == "FULL191"
    progression = frozen_protocol()["batchProgression"]
    assert progression["advanceOn"] == (
        "STRUCTURAL_AND_REPLAY_INTEGRITY_ONLY_NEVER_PERFORMANCE"
    )
    assert progression["parameterChangeBetweenBatchesAllowed"] is False
    assert progression["primaryAcceptanceUsesOnly"] == "FULL191"
    assert progression["pilotAndExpansionMayCalculatePerformance"] is False
    assert progression["prefixEqualityRequired"] is True


def test_v111_chronology_repairs_the_draft_without_changing_economics() -> None:
    protocol = frozen_protocol()
    repair = protocol["chronologyRepair"]
    assert repair == {
        "supersedesEngineeringDraftVersion": (
            "QUANT-TRADING-HISTORICAL-VALIDATION-v1.1.0"
        ),
        "supersedesEngineeringDraftHash": (
            "0592A9A24F7975366B0C11DC1F6A991C2330F79671A96320CA30DE182FC438BE"
        ),
        "repairMadeBeforeAnyV11OutcomeAccess": True,
        "economicFormulaCostThresholdOrPopulationChange": False,
        "reason": (
            "ACTUAL_SESSION_SCHEDULE_FORMULA_RANK_AND_TERMINAL_MANIFESTS_DEPEND_"
            "ON_DECODED_SEALED_BARS_AND_CANNOT_BE_TRUTHFULLY_SEALED_PRE_ACCESS"
        ),
    }
    assert protocol["controlledBindings"]["population"]["count"] == 191
    assert protocol["costPolicy"]["version"] == COST_POLICY_VERSION
    assert protocol["acceptance"]["numericGates"] == frozen_protocol()["acceptance"][
        "numericGates"
    ]


def test_journal_chronology_seals_actual_manifests_before_performance() -> None:
    boundary = frozen_protocol()["executionBoundary"]
    assert boundary["journalGrammar"] == [
        "PREPARATION_INTENT",
        "PREPARATION_STRUCTURAL_COMPLETE",
        "OUTCOME_ACCESS_INTENT",
        "OUTCOME_EXECUTION_INTENT",
        "POST_ACCESS_PRE_PERFORMANCE_INPUT_SEAL",
        "EXACTLY_ONE_COMPLETED_FAILED_OR_UNKNOWN_TERMINAL",
    ]
    assert boundary["preAccessFutureValueDerivedManifestHashesForbidden"] is True
    seal = boundary["postAccessPrePerformanceInputSeal"]
    assert seal["derivedInSameCheckedRunAfterPayloadDecode"] is True
    assert seal["mustPrecedeReturnPnlBenchmarkOrAcceptanceAggregation"] is True
    assert seal["performanceEvaluated"] is False
    assert seal["returnPnlBenchmarkOrAcceptanceFieldsAllowed"] is False
    assert boundary["uninterruptedNoninteractiveRunRequired"] is True
    assert boundary["humanOrLlmPauseBetweenDecodeInputSealAndPerformanceAllowed"] is False
    assert boundary["batch25And100Purpose"] == (
        "INTEGRITY_AND_REPLAY_ONLY_NO_PERFORMANCE"
    )
    assert boundary["full191OnlyPerformanceAggregation"] is True
    assert boundary["resultMustBindExecutionIntentAndPostAccessInputSeal"] is True
    assert boundary["uncertainPartialDurableState"] == "UNKNOWN_NO_RETRY"


@pytest.mark.parametrize("value", [0, 192, True, "1", None])
def test_invalid_population_ordinal_fails_closed(value: object) -> None:
    with pytest.raises(QuantHistoricalValidationV11Violation):
        batch_for_ordinal(value)  # type: ignore[arg-type]


def test_population_order_is_deterministic_and_rejects_ambiguous_atoms() -> None:
    identities = ("SEC-C", "SEC-A", "SEC-B")
    first = tuple(sorted(identities, key=population_order_key))
    second = tuple(sorted(reversed(identities), key=population_order_key))
    assert first == second
    with pytest.raises(QuantHistoricalValidationV11Violation):
        population_order_key(" SEC-A")
    with pytest.raises(QuantHistoricalValidationV11Violation):
        population_order_key("SEC|A")


def test_rules_cost_terminal_and_benchmark_semantics_are_exact() -> None:
    protocol = frozen_protocol()
    rules = protocol["strategyRules"]
    assert rules["signal"] == frozen_v11_contract()["signal"]
    assert rules["entry"]["maximumEntryPrice"] == "SIGNAL_CLOSE+2*ATR14"
    assert rules["entry"]["intradayReclaimEntry"] is False
    assert rules["exit"]["profitTarget"] == "NONE_ALLOW_WINNERS_TO_RUN"
    assert rules["exit"]["finalForcedLiquidation"] is False
    assert rules["portfolio"]["initialCashUsd"] == "100000"
    assert rules["portfolio"]["maximumPositions"] == 10
    cost = protocol["costPolicy"]
    assert cost["impactBps"] == "MIN(50,25*SQRT(PARTICIPATION))"
    assert cost["perSideBps"] == "1+IMPACT_BPS"
    assert cost["fixedSensitivity"] == "5_BPS_PER_SIDE_SEPARATE_RESULT"
    assert cost["fixedSensitivityMethod"]["costAddition"] is False
    assert cost["fixedSensitivityMethod"]["ordersAndPositions"].endswith(
        "NEVER_COPIED_FROM_PRIMARY"
    )
    assert cost["currentExecutionBarCloseOrVolumeIncluded"] is False
    assert cost["runnerMustRecomputeAndRejectAdtvMismatch"] is True
    assert cost["executionBarAdtvField"].endswith(
        "STRICTLY_BEFORE_THE_EXECUTION_BAR_SESSION"
    )
    terminal = protocol["terminalPolicy"]
    assert terminal["missingActivePositionBar"] == (
        "PERMANENTLY_MARK_PERFORMANCE_INCOMPLETE_AND_SCHEDULE_NEXT_TRADABLE_OPEN_"
        "DIAGNOSTIC_EXIT"
    )
    assert terminal["separateDividendOrSplitCashFlows"] is False
    benchmarks = protocol["benchmarks"]
    assert benchmarks["primary"]["code"] == "SPY"
    assert benchmarks["equalWeight"]["state"] == "NOT_OBSERVED"
    assert benchmarks["sector"]["state"] == "NOT_OBSERVED"
    assert benchmarks["benchmarkSubstitutionAllowed"] is False


def test_metrics_and_single_terminal_acceptance_are_frozen() -> None:
    protocol = frozen_protocol()
    metrics = protocol["metrics"]
    assert metrics["maxDrawdown"] == "MIN(NAV/RUNNING_PEAK_NAV-1)"
    assert metrics["sharpeRfZero"].endswith("*SQRT(252)")
    assert metrics["subperiods"] == ["2015-2019", "2020-2022", "2023-2026"]
    subperiod = metrics["subperiodMethod"]
    assert subperiod["kind"] == (
        "SLICE_PRIMARY_FULL_RUN_AFTER_CLOSE_NAV_NO_INDEPENDENT_REPLAY"
    )
    assert subperiod["positionsAndCashCarryAcrossBoundaries"] is True
    assert subperiod["boundaryResetOrTrade"] is False
    assert subperiod["boundaryTransactionCost"] == (
        "NONE_BECAUSE_NO_SYNTHETIC_BOUNDARY_TRADE"
    )
    acceptance = protocol["acceptance"]
    assert acceptance["evaluationCount"] == 1
    assert acceptance["allGatesRequired"] is True
    assert acceptance["numericGates"] == {
        "minimumCompletedPortfolioSessions": 2000,
        "minimumClosedTrades": 50,
        "minimumCagrMinusSpy": "0",
        "minimumTotalReturnMinusSpyExclusive": "0",
        "minimumSharpeAdvantageVsSpy": {
            "formula": "STRATEGY_SHARPE_RF_ZERO-SPY_SHARPE_RF_ZERO",
            "minimum": "0.10",
            "notObservedFails": True,
        },
        "maximumDrawdownMagnitudeDeteriorationVsSpy": {
            "formula": "ABS(STRATEGY_MAX_DRAWDOWN)-ABS(SPY_MAX_DRAWDOWN)",
            "maximum": "0.05",
        },
        "minimumPositiveSpyCagrExcessSubperiods": 2,
        "requiredSubperiodCount": 3,
        "maximumSevereLossRate": "0.10",
        "fixedFiveBpsSensitivityMinimumFinalNavExclusive": "100000",
    }
    assert metrics["primaryWindow"]["firstDailySimpleReturn"] == (
        "FIRST_LEDGER_NAV/100000-1"
    )
    assert metrics["closedTradeMethod"]["openTradeAtEndAllowed"] is False
    assert acceptance["failingInterpretation"].endswith("NO_RETUNING_ON_SAME_OUTCOME")
    assert {
        "PRIMARY_STRATEGY_TERMINAL_STATE_COMPLETE_CASH",
        "FIXED_SENSITIVITY_STRATEGY_TERMINAL_STATE_COMPLETE_CASH",
        "SPY_BENCHMARK_EXITED_AT_FINAL_MATURITY_CLOSE_WITH_EXIT_COST",
    }.issubset(set(acceptance["integrityGates"]))


def test_protocol_validation_rejects_any_nested_drift_and_returns_fresh_copies() -> None:
    first = frozen_protocol()
    second = frozen_protocol()
    assert first == second and first is not second
    first["acceptance"]["numericGates"]["minimumClosedTrades"] = 49
    with pytest.raises(QuantHistoricalValidationV11Violation, match="protocol drift"):
        validate_protocol(first)
    validate_protocol(second)


def test_module_has_no_outcome_transport_or_storage_dependency() -> None:
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
    assert imports == {
        "__future__",
        "copy",
        "dataclasses",
        "hashlib",
        "json",
        "typing",
        "equity_analysis.quant_trading.successor_v11",
    }
    called_names = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert called_names.isdisjoint(
        {"open", "run_batch", "simulate_portfolio_v1", "urlopen", "connect"}
    )
    execution = frozen_protocol()["executionBoundary"]
    assert execution["networkAuthorized"] is False
    assert execution["providerRequests"] == 0
    assert execution["databaseWritesAuthorized"] is False
