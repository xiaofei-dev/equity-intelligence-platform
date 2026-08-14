from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from types import MappingProxyType
from typing import Any

CONTRACT_VERSION = "quant-trading-system-v1.0.0"
MODEL_VERSION = "QUANT-TRADING-v1.0.0"
STRATEGY_VERSION = "MOMENTUM-CONTINUATION-v1.0.0"
COST_POLICY_VERSION = "C9-NONLINEAR-COST-v1.0.0"
VERSION_SET = {
    "evidenceContractVersion": "unified-market-data-evidence-foundation-v1.0.0",
    "calendarVersion": "US-EQUITIES-XNYS-XNAS-DAILY-v1.0.0",
    "signalFormulaVersion": "MOMENTUM-CONTINUATION-FORMULAS-v1.0.0",
    "entryExitPolicyVersion": "MOMENTUM-CONTINUATION-ENTRY-EXIT-v1.0.0",
    "riskPolicyVersion": "QUANT-TRADING-RISK-v1.0.0",
    "benchmarkPolicyVersion": "QUANT-TRADING-BENCHMARKS-v1.0.0",
    "costPolicyVersion": COST_POLICY_VERSION,
    "validationGovernanceVersion": "QUANT-TRADING-VALIDATION-v1.0.0",
}

_DECIMAL = re.compile(r"-?(?:0|[1-9]\d*)(?:\.\d+)?\Z")
_HASH = re.compile(r"sha256:[0-9a-f]{64}\Z")
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\Z")


class QuantTradingContractViolation(ValueError):
    pass


@dataclass(frozen=True)
class QuantTradingDecisionContractV1:
    payload: Any

    @classmethod
    def parse(cls, payload: dict[str, Any]) -> QuantTradingDecisionContractV1:
        if not isinstance(payload, dict):
            raise QuantTradingContractViolation("Contract payload must be an object")
        _exact_keys(
            payload,
            {
                "contractVersion",
                "modelVersion",
                "strategyVersion",
                "market",
                "cadence",
                "sleeve",
                "direction",
                "setup",
                "legacyBoundary",
                "evidenceBoundary",
                "signalTiming",
                "tradePlan",
                "portfolioSimulation",
                "benchmarkPolicy",
                "costPolicy",
                "diagnosticHorizons",
                "validationGovernance",
                "automationBoundary",
                "versionSet",
                "contractContentHash",
            },
            "contract",
        )
        _equals(payload, "contractVersion", CONTRACT_VERSION)
        _equals(payload, "modelVersion", MODEL_VERSION)
        _equals(payload, "strategyVersion", STRATEGY_VERSION)
        _equals(payload, "market", "US_LISTED_EQUITIES")
        _equals(payload, "cadence", "DAILY_COMPLETED_SESSION")
        _equals(payload, "sleeve", "QUANT_TRADING")
        _equals(payload, "direction", "LONG_ONLY")
        _equals(payload, "setup", "MOMENTUM_CONTINUATION")
        _validate_legacy(_object(payload, "legacyBoundary"))
        _validate_evidence(_object(payload, "evidenceBoundary"))
        _validate_timing(_object(payload, "signalTiming"))
        _validate_trade_plan(_object(payload, "tradePlan"))
        _validate_portfolio(_object(payload, "portfolioSimulation"))
        _validate_benchmarks(_object(payload, "benchmarkPolicy"))
        _validate_cost(_object(payload, "costPolicy"))
        horizons = _list(payload, "diagnosticHorizons")
        if any(type(horizon) is not int for horizon in horizons) or horizons != [5, 20, 60]:
            raise QuantTradingContractViolation("Diagnostic horizons must be exactly 5, 20, and 60")
        _validate_governance(_object(payload, "validationGovernance"))
        _validate_automation(_object(payload, "automationBoundary"))
        _validate_versions(_object(payload, "versionSet"))
        declared = _hash(payload, "contractContentHash")
        canonical = json.dumps(
            {key: value for key, value in payload.items() if key != "contractContentHash"},
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        expected = f"sha256:{hashlib.sha256(canonical).hexdigest()}"
        if declared != expected:
            raise QuantTradingContractViolation("Contract content hash is invalid")
        return cls(payload=_freeze(json.loads(json.dumps(payload))))


def _validate_legacy(value: dict[str, Any]) -> None:
    expected = {
        "tacticalV22Immutable": True,
        "legacyOneWeekOneMonthThreeMonthDisplayOnly": True,
        "reuseLegacyV21PortfolioTables": False,
        "meanReversionIncluded": False,
        "futureMeanReversionRequiresSuccessorStrategy": True,
        "fundamentalValueInputAllowed": False,
        "crossEngineScoreBlendingAllowed": False,
    }
    if value != expected:
        raise QuantTradingContractViolation("Legacy and cross-engine boundaries are invalid")


def _validate_evidence(value: dict[str, Any]) -> None:
    expected_keys = {
        "contractVersion",
        "requiredIdentifiers",
        "completedSessionRequired",
        "selectorIdsRequired",
        "corporateActionEvidenceRequired",
        "missingEventEvidenceEffect",
        "providerNativeFieldsAllowed",
        "strictDecimalAndFiniteValues",
        "utcWholeSecondTimestamps",
    }
    _exact_keys(value, expected_keys, "evidenceBoundary")
    _equals(value, "contractVersion", VERSION_SET["evidenceContractVersion"])
    if _list(value, "requiredIdentifiers") != [
        "securityId",
        "companyId",
        "instrumentId",
        "shareClassId",
        "listingId",
        "tickerAssignmentId",
    ]:
        raise QuantTradingContractViolation("Durable V22 identity tuple is incomplete")
    _all_exact_booleans(
        value,
        {
            "completedSessionRequired": True,
            "selectorIdsRequired": True,
            "corporateActionEvidenceRequired": True,
            "providerNativeFieldsAllowed": False,
            "strictDecimalAndFiniteValues": True,
            "utcWholeSecondTimestamps": True,
        },
    )
    _equals(value, "missingEventEvidenceEffect", "INELIGIBLE_FAIL_CLOSED")


def _validate_timing(value: dict[str, Any]) -> None:
    expected = {
        "signalAfterCompletedClose": True,
        "entrySession": "NEXT_ELIGIBLE_SCHEDULED_SESSION_OPEN",
        "replayRequiresEntrySessionSubsequentlySealedCompleted": True,
        "entryValidityScheduledSessions": 1,
        "sameSessionEntryAllowed": False,
        "futureOrIncompleteSessionAllowed": False,
    }
    if type(value.get("entryValidityScheduledSessions")) is not int or value != expected:
        raise QuantTradingContractViolation("Signal and entry timing are invalid")


def _validate_trade_plan(value: dict[str, Any]) -> None:
    _exact_keys(
        value,
        {
            "entryRangeRequired",
            "entryFillPolicy",
            "initialStopRequired",
            "targetsRequired",
            "trailingStopRequired",
            "invalidationRequired",
            "tradePlanFeasibility",
            "maximumHoldingSessions",
            "exitExecutionPolicy",
            "positionSizing",
            "candidateSelection",
            "cashRequiredWhenNoEligibleSetup",
            "marketDataAndLifecyclePolicy",
        },
        "tradePlan",
    )
    _all_exact_booleans(
        value,
        {
            "entryRangeRequired": True,
            "initialStopRequired": True,
            "targetsRequired": True,
            "trailingStopRequired": True,
            "invalidationRequired": True,
            "cashRequiredWhenNoEligibleSetup": True,
        },
    )
    entry_fill = _object(value, "entryFillPolicy")
    if entry_fill != {
        "openInsideRange": "FILL_AT_OPEN",
        "openAboveRangeHigh": "SKIP_AND_REMAIN_CASH",
        "openBelowInitialStop": "SKIP_AND_REMAIN_CASH",
        "openBelowRangeLowButAboveStop": "LIMIT_TOUCH_REQUIRED",
        "limitTouchCondition": "SESSION_HIGH_AT_OR_ABOVE_ENTRY_RANGE_LOW",
        "limitTouchFill": "ENTRY_RANGE_LOW",
        "noTouch": "SKIP_AND_REMAIN_CASH",
        "rangeBoundsInclusive": True,
    }:
        raise QuantTradingContractViolation("Entry fill policy is invalid")
    if _object(value, "tradePlanFeasibility") != {
        "entryRange": "entryRangeLow<=entryRangeHigh",
        "priceGeometry": ("FOR_EVERY_ENTRY_FILL:0<initialStop<fill<=entryRangeHigh<firstTarget"),
        "targets": "NONEMPTY_STRICTLY_ASCENDING",
        "activeLongTrailingStop": (
            "MONOTONIC_NONDECREASING_AND_STRICTLY_BELOW_CURRENT_EXECUTABLE_"
            "REFERENCE_BEFORE_NEXT_SESSION"
        ),
        "invalidPlanEffect": "INELIGIBLE_FAIL_CLOSED",
    }:
        raise QuantTradingContractViolation("Price geometry policy is invalid")
    if (
        type(value.get("maximumHoldingSessions")) is not int
        or value.get("maximumHoldingSessions") != 60
    ):
        raise QuantTradingContractViolation("Maximum holding period must be 60 sessions")
    if _object(value, "exitExecutionPolicy") != {
        "gapThroughStopFill": "SESSION_OPEN",
        "gapThroughTargetFill": "SESSION_OPEN",
        "ordinaryStopTouchFill": "ACTIVE_STOP_PRICE",
        "ordinaryTargetTouchFill": "FIRST_TARGET_PRICE",
        "sameBarStopAndTarget": "STOP_FIRST",
        "openPhasePriority": [
            "PENDING_INVALIDATION",
            "GAP_THROUGH_STOP",
            "GAP_THROUGH_TARGET",
        ],
        "intradayPhasePriority": ["STOP", "TARGET"],
        "closePhasePriority": [
            "TIME_STOP_ON_60TH_SESSION",
            "CALCULATE_TRAILING_STOP",
            "EVALUATE_INVALIDATION",
        ],
        "targetDisposition": "FULL_EXIT_AT_FIRST_TARGET",
        "openInsideRangeEntryDayExitEvaluation": "INTRADAY_STOP_FIRST_THEN_TARGET",
        "reclaimLimitEntryDayExitEvaluation": {
            "entryCondition": "SESSION_HIGH_AT_OR_ABOVE_ENTRY_RANGE_LOW",
            "stopCondition": "SESSION_LOW_AT_OR_BELOW_INITIAL_STOP",
            "stopFill": "INITIAL_STOP_PRICE",
            "targetCondition": "SESSION_HIGH_AT_OR_ABOVE_FIRST_TARGET",
            "targetFill": "FIRST_TARGET_PRICE",
            "sameBarPriority": "STOP_FIRST",
            "otherwise": "HOLD_TO_NEXT_ELIGIBLE_SESSION",
        },
        "trailingStopCalculation": "AFTER_COMPLETED_CLOSE",
        "trailingStopEffective": "NEXT_ELIGIBLE_SCHEDULED_SESSION",
        "invalidationEvaluation": "AFTER_COMPLETED_CLOSE",
        "invalidationFill": "NEXT_ELIGIBLE_SCHEDULED_SESSION_OPEN",
        "timeStopFill": "CLOSE_OF_60TH_COMPLETED_HOLDING_SESSION",
    }:
        raise QuantTradingContractViolation("Exit execution policy is invalid")
    sizing = _object(value, "positionSizing")
    _exact_keys(
        sizing,
        {
            "method",
            "navObservation",
            "navRiskPerPosition",
            "notionalCap",
            "shareRounding",
            "estimatedEntryAndExitCostsReserved",
            "shareLimitOrder",
            "riskBudgetIncludesEntryAndEstimatedExitCosts",
            "initialShareCandidate",
            "estimatedExitNotional",
            "estimatedExitLiquidity",
            "costSolver",
            "riskInequality",
            "cashInequality",
            "decimalRounding",
            "decimalContext",
            "minimumOfAllShareLimitsWins",
        },
        "positionSizing",
    )
    _equals(sizing, "method", "STOP_DISTANCE_RISK_SIZING")
    _equals(sizing, "navObservation", "PRIOR_COMPLETED_SESSION_CLOSE")
    if _decimal(sizing, "navRiskPerPosition") != Decimal("0.005"):
        raise QuantTradingContractViolation("Position NAV risk must be 0.5 percent")
    if _decimal(sizing, "notionalCap") != Decimal("0.10"):
        raise QuantTradingContractViolation("Position notional cap must be 10 percent")
    _equals(sizing, "shareRounding", "FLOOR_TO_WHOLE_SHARES")
    if sizing.get("estimatedEntryAndExitCostsReserved") is not True:
        raise QuantTradingContractViolation("Entry and exit costs must be reserved")
    if _list(sizing, "shareLimitOrder") != [
        "STOP_RISK",
        "NOTIONAL_CAP",
        "AVAILABLE_CASH_AFTER_COST_RESERVE",
    ]:
        raise QuantTradingContractViolation("All sizing limits are required")
    sizing_rules = {
        "riskBudgetIncludesEntryAndEstimatedExitCosts": True,
        "initialShareCandidate": (
            "floor(min(nav*0.005/(entryPrice-initialStop),nav*0.10/entryPrice,"
            "availableCash/entryPrice))"
        ),
        "estimatedExitNotional": "initialStop*wholeShares",
        "estimatedExitLiquidity": "SAME_ENTRY_DECISION_PRIOR_20_SESSION_ADTV",
        "costSolver": "DECREMENT_ONE_SHARE_UNTIL_RISK_AND_CASH_INEQUALITIES_PASS",
        "riskInequality": (
            "shares*(entryPrice-initialStop)+entryCost+estimatedExitCost<=nav*0.005"
        ),
        "cashInequality": ("shares*entryPrice+entryCost+estimatedExitCost<=availableCash"),
        "decimalRounding": "ROUND_HALF_EVEN_FOR_RATES_FLOOR_ONLY_FOR_SHARES",
        "decimalContext": "PRECISION_50_ROUND_HALF_EVEN_LOCAL_CONTEXT",
    }
    for field, expected in sizing_rules.items():
        if sizing.get(field) != expected:
            raise QuantTradingContractViolation(f"{field} sizing rule is invalid")
    if sizing.get("minimumOfAllShareLimitsWins") is not True:
        raise QuantTradingContractViolation("The lower sizing bound must win")
    if _object(value, "candidateSelection") != {
        "priority": ["MOMENTUM_SCORE_DESC", "SECURITY_ID_ASC"],
        "maximumNewPositionsLimitedByOpenSlots": True,
        "slotReleasedOnlyAfterExitFill": True,
        "rejectedOrUnfilledCapitalRemainsCash": True,
    }:
        raise QuantTradingContractViolation("Candidate selection is invalid")
    if _object(value, "marketDataAndLifecyclePolicy") != {
        "priceMode": "SPLIT_AND_DIVIDEND_ADJUSTED_OHLCV",
        "separateDividendOrSplitCashFlowApplied": False,
        "tickerAndListingChangesFollowDurableIdentity": True,
        "haltOrSuspensionFillAssumed": False,
        "missingHaltOrSuspensionEvidenceEffect": "INVALID",
        "acquisitionTreatment": ("LAST_TRADABLE_SESSION_OR_EXPLICIT_CASH_OR_STOCK_CONSIDERATION"),
        "delistingTreatment": "EXPLICIT_TERMINAL_CASH_VALUE_REQUIRED",
        "bankruptcyTreatment": "EXPLICIT_TERMINAL_CASH_VALUE_REQUIRED",
        "missingTerminalEvidenceEffect": "INVALID",
    }:
        raise QuantTradingContractViolation("Market-data and lifecycle policy is invalid")


def _validate_portfolio(value: dict[str, Any]) -> None:
    _exact_keys(
        value,
        {
            "initialCashUsd",
            "maximumConcurrentPositions",
            "leverageAllowed",
            "shortingAllowed",
            "optionsAllowed",
            "automaticBrokerageExecutionAllowed",
        },
        "portfolioSimulation",
    )
    if _decimal(value, "initialCashUsd") != Decimal("100000"):
        raise QuantTradingContractViolation("Simulation capital must be USD 100,000")
    maximum_positions = value.get("maximumConcurrentPositions")
    if type(maximum_positions) is not int or maximum_positions != 10:
        raise QuantTradingContractViolation("Maximum concurrent positions must be 10")
    _all_exact_booleans(
        value,
        {
            "leverageAllowed": False,
            "shortingAllowed": False,
            "optionsAllowed": False,
            "automaticBrokerageExecutionAllowed": False,
        },
    )


def _validate_benchmarks(value: dict[str, Any]) -> None:
    if value != {
        "primary": "SPY",
        "supplemental": ["CASH", "EQUAL_WEIGHT"],
        "sector": "DIAGNOSTIC_UNTIL_DATED_MAPPING",
        "cashAnnualRate": "0",
        "calendar": "SAME_COMPLETED_SESSION_CALENDAR_AS_STRATEGY",
        "spyConstruction": ("BUY_AND_HOLD_ADJUSTED_OHLCV_WITH_IDENTICAL_COST_AND_TERMINAL_RULES"),
        "equalWeightConstruction": "ELIGIBLE_POPULATION_EQUAL_WEIGHT",
        "equalWeightRebalance": "EACH_SIGNAL_DECISION_DATE",
        "equalWeightCosts": "IDENTICAL_COST_AND_LIQUIDITY_POLICY",
        "terminalTreatment": "IDENTICAL_TO_STRATEGY",
    }:
        raise QuantTradingContractViolation("Benchmark policy is invalid")


def _validate_cost(value: dict[str, Any]) -> None:
    _exact_keys(value, {"version", "primary", "sensitivity"}, "costPolicy")
    _equals(value, "version", COST_POLICY_VERSION)
    primary = _object(value, "primary")
    if primary != {
        "participation": "orderNotional/averageDailyDollarVolume",
        "impactBps": "min(50,25*sqrt(participation))",
        "perSideBps": "1+impactBps",
        "sideRate": "perSideBps/10000",
        "sideCostUsd": "orderNotional*sideRate",
        "totalCostUsd": "entrySideCostUsd+exitSideCostUsd",
        "totalCostRate": "entryCostRate+exitCostRate",
        "netReturn": "grossReturn-entryCostRate-exitCostRate",
        "entryOrderNotional": "ENTRY_FILL_PRICE*WHOLE_SHARES",
        "exitOrderNotional": "EXIT_FILL_PRICE*WHOLE_SHARES",
        "averageDailyDollarVolume": ("PRIOR_20_COMPLETED_SESSIONS_MEDIAN_DOLLAR_VOLUME"),
        "estimatedExitCostLiquidity": (
            "ENTRY_DECISION_PRIOR_20_COMPLETED_SESSIONS_MEDIAN_DOLLAR_VOLUME"
        ),
        "actualExitCostLiquidity": ("PRIOR_20_COMPLETED_SESSIONS_BEFORE_EXIT_MEDIAN_DOLLAR_VOLUME"),
        "decimalContext": "PRECISION_50_ROUND_HALF_EVEN_LOCAL_CONTEXT",
        "monetaryQuantization": "NONE_CANONICAL_DECIMAL",
        "sideSpecificInputsRequired": True,
        "missingLiquidityEffect": "INELIGIBLE",
    }:
        raise QuantTradingContractViolation("Primary nonlinear cost formula is invalid")
    sensitivity = _object(value, "sensitivity")
    if _decimal(sensitivity, "perSideBps") != Decimal("5"):
        raise QuantTradingContractViolation("Cost sensitivity must be 5 bps per side")


def _validate_governance(value: dict[str, Any]) -> None:
    expected = {
        "initialModelEvidenceLabel": "NOT_VALIDATED",
        "historicalEvidenceLabel": "DEVELOPMENT_OBSERVED_CURRENT_REVISION_CURRENT_SURVIVOR",
        "diagnosticHorizonsMayValidateModel": False,
        "historicalResultsGuaranteeFutureReturns": False,
        "observedOutcomesMayChangeFrozenMethodology": False,
        "perfectPredictionRequired": False,
    }
    if value != expected:
        raise QuantTradingContractViolation("Validation governance is invalid")


def _validate_automation(value: dict[str, Any]) -> None:
    expected = {
        "createsBrokerageOrders": False,
        "executesTrades": False,
        "setsFinalPortfolioWeights": False,
        "llmMayAffectSignalsOrTrades": False,
        "humanDecisionRequired": True,
    }
    if value != expected:
        raise QuantTradingContractViolation("Automation boundary is invalid")


def _validate_versions(value: dict[str, Any]) -> None:
    _exact_keys(
        value,
        {
            "evidenceContractVersion",
            "calendarVersion",
            "signalFormulaVersion",
            "entryExitPolicyVersion",
            "riskPolicyVersion",
            "benchmarkPolicyVersion",
            "costPolicyVersion",
            "validationGovernanceVersion",
        },
        "versionSet",
    )
    if value != VERSION_SET:
        raise QuantTradingContractViolation("Version set is invalid")


def _freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


def _exact_keys(value: dict[str, Any], expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise QuantTradingContractViolation(f"{label} keys are invalid")


def _object(value: dict[str, Any], key: str) -> dict[str, Any]:
    item = value.get(key)
    if not isinstance(item, dict):
        raise QuantTradingContractViolation(f"{key} must be an object")
    return item


def _list(value: dict[str, Any], key: str) -> list[Any]:
    item = value.get(key)
    if not isinstance(item, list):
        raise QuantTradingContractViolation(f"{key} must be a list")
    return item


def _string(value: dict[str, Any], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item.strip():
        raise QuantTradingContractViolation(f"{key} must be a nonblank string")
    return item


def _equals(value: dict[str, Any], key: str, expected: str) -> None:
    if _string(value, key) != expected:
        raise QuantTradingContractViolation(f"{key} is invalid")


def _decimal(value: dict[str, Any], key: str) -> Decimal:
    item = value.get(key)
    if not isinstance(item, str) or _DECIMAL.fullmatch(item) is None:
        raise QuantTradingContractViolation(f"{key} must be an ordinary decimal string")
    try:
        parsed = Decimal(item)
    except InvalidOperation as error:
        raise QuantTradingContractViolation(f"{key} must be finite") from error
    if not parsed.is_finite():
        raise QuantTradingContractViolation(f"{key} must be finite")
    return parsed


def _hash(value: dict[str, Any], key: str) -> str:
    item = _string(value, key)
    if _HASH.fullmatch(item) is None:
        raise QuantTradingContractViolation(f"{key} must be a canonical SHA-256 reference")
    return item


def _all_exact_booleans(value: dict[str, Any], expected: dict[str, bool]) -> None:
    for key, required in expected.items():
        if value.get(key) is not required:
            raise QuantTradingContractViolation(f"{key} must be {required}")
