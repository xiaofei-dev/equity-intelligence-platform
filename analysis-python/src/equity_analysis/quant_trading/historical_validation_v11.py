"""Outcome-blind preregistration for Quant Trading v1.1.1 historical validation.

This module contains policy only.  It deliberately has no filesystem, provider,
database, price-decoding, simulator, or outcome-result dependency.
"""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from equity_analysis.quant_trading.successor_v11 import frozen_v11_contract

PROTOCOL_VERSION = "QUANT-TRADING-HISTORICAL-VALIDATION-v1.1.1"
PROTOCOL_STATE = "PREREGISTERED_CHRONOLOGY_REPAIR_BEFORE_V11_OUTCOME_ACCESS"
V11_SIMULATOR_VERSION = "QUANT-TRADING-PORTFOLIO-SIMULATOR-v1.1.0"
V11_PRIMARY_COST_POLICY_VERSION = "C9-NONLINEAR-COST-v1.0.0"
V11_FIXED_COST_POLICY_VERSION = "FIXED-5-BPS-PER-SIDE-v1.0.0"

V1_PROTOCOL_HASH = "84B5DEEDF5ABE572C135E3E1CF3D4FF7ED391F93A20A82D4F3B6C1BF48F070BC"
V11_DECISION_CONTRACT_HASH = "BF9BF8D473CA10C0944E2F900824CE2B64B22C8778684E32AA4E5056CF5BE954"
V1_DISPOSITION_HASH = "02D8410EC8FF7690C7FE30E4296C06162E708CBF5A0D9F88AEA030737B035F4D"
V1_FULL_RESULT_HASH = "F87E4AF65E9E2AAF73BC6ADA7142FB5C78E21D0E2D8E95771D83963C1533AB8D"
V11_DRAFT_PROTOCOL_HASH = "0592A9A24F7975366B0C11DC1F6A991C2330F79671A96320CA30DE182FC438BE"
C7_RECEIPT_HASH = "B74761883F9395F1334B3F78983DB4237DF0F3F245F449EFFDC73F98FBB738AD"
C7_RECEIPT_FILE_SHA256 = "CD830491016535733CB9FE5C4BEAEBC6EE6D48F0186B6C82F131BF30FE8168C8"
C7_CALENDAR_HASH = "7FE1CA16970AE0346C67120DD4F32BA3BEF039276B9800757D15D3744189AA2C"
C7_CALENDAR_FILE_SHA256 = "AF107891BB758C021EC012FDAB52AADDD8A07664F41CFCB7A686434A7B477CE8"
C9_IDENTITY_SET_HASH = "B29306CE3B1A047C074B68FDA07149FFF72F7B2ECD2BC0D78AAD7B42692656C7"
C9_PREDICTOR_SEAL_HASH = "E110C20287CB1B9E2260E9DAA33C2F2A8B5CD290F11E20EB733B918F61F595DD"

POPULATION_SIZE = 191


class QuantHistoricalValidationV11Violation(ValueError):
    """Raised when the preregistered protocol or batch boundary drifts."""


@dataclass(frozen=True)
class ValidationBatchV11:
    code: str
    cumulative_count: int
    incremental_count: int
    purpose: str
    performance_gate: bool = False

    def __post_init__(self) -> None:
        if type(self.code) is not str or not self.code:
            raise QuantHistoricalValidationV11Violation("batch code is invalid")
        if type(self.cumulative_count) is not int or self.cumulative_count <= 0:
            raise QuantHistoricalValidationV11Violation("batch cumulative count is invalid")
        if type(self.incremental_count) is not int or self.incremental_count <= 0:
            raise QuantHistoricalValidationV11Violation("batch incremental count is invalid")
        if type(self.purpose) is not str or not self.purpose:
            raise QuantHistoricalValidationV11Violation("batch purpose is invalid")
        if type(self.performance_gate) is not bool:
            raise QuantHistoricalValidationV11Violation("batch performance gate is invalid")


BATCHES = (
    ValidationBatchV11("PILOT25", 25, 25, "ENGINEERING_INTEGRITY_ONLY"),
    ValidationBatchV11("EXPANSION100", 100, 75, "ENGINEERING_INTEGRITY_ONLY"),
    ValidationBatchV11("FULL191", 191, 91, "SOLE_PRIMARY_ACCEPTANCE_POPULATION", True),
)


def canonical_hash(value: object) -> str:
    """Return the frozen uppercase SHA-256 over canonical compact JSON."""

    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest().upper()


def population_order_key(security_id: str) -> tuple[str, str]:
    """Return the outcome-independent population ordering key."""

    if (
        type(security_id) is not str
        or not security_id
        or security_id != security_id.strip()
        or "|" in security_id
    ):
        raise QuantHistoricalValidationV11Violation("security ID is not a canonical atom")
    return hashlib.sha256(security_id.encode("utf-8")).hexdigest().upper(), security_id


def batch_for_ordinal(ordinal: int) -> str:
    """Map a one-based frozen population ordinal to its incremental batch."""

    if type(ordinal) is not int or not 1 <= ordinal <= POPULATION_SIZE:
        raise QuantHistoricalValidationV11Violation("population ordinal is outside 1..191")
    if ordinal <= 25:
        return "PILOT25"
    if ordinal <= 100:
        return "EXPANSION100"
    return "FULL191"


def frozen_protocol() -> dict[str, Any]:
    """Return a fresh copy of the exact pre-outcome v1.1.1 protocol."""

    successor = frozen_v11_contract()
    if successor["contentHash"] != V11_DECISION_CONTRACT_HASH:
        raise QuantHistoricalValidationV11Violation("v1.1 decision contract identity drift")

    body: dict[str, Any] = {
        "schemaVersion": PROTOCOL_VERSION,
        "state": PROTOCOL_STATE,
        "sealedOn": "2026-08-12",
        "outcomeAwareness": {
            "v1OutcomeObservedBeforeV11Design": True,
            "v11NumericPricesReadBeforeSeal": False,
            "v11OutcomeMetricsReadBeforeSeal": False,
            "sameControlledHistoryReused": True,
            "sameHistoryUntouchedHoldoutClaimed": False,
            "strictPitClaimed": False,
            "backtestSupportedClaimed": False,
            "forwardSupportedClaimed": False,
            "maximumSameHistoryClaim": "DEVELOPMENT_OBSERVED_SAME_HISTORY_POST_V1_OUTCOME",
            "parameterOrThresholdChangeAfterV11OutcomeAccessAllowed": False,
            "failedValidationMayTriggerSameOutcomeRetuning": False,
            "requiredSuccessorAfterAnyOutcomeAwareChange": (
                "NEW_VERSION_NEW_PREREGISTRATION_NO_CLAIM_UPGRADE_ON_SAME_HISTORY"
            ),
            "payloadBytesExposeHistoricalBarsAfterIntent": True,
            "prePerformanceSealDoesNotClaimBarsWereUnavailableToProcess": True,
            "returnsPnlRanksAgainstFutureReturnsOrAcceptanceInspectedBeforeInputSeal": False,
        },
        "chronologyRepair": {
            "supersedesEngineeringDraftVersion": (
                "QUANT-TRADING-HISTORICAL-VALIDATION-v1.1.0"
            ),
            "supersedesEngineeringDraftHash": V11_DRAFT_PROTOCOL_HASH,
            "repairMadeBeforeAnyV11OutcomeAccess": True,
            "economicFormulaCostThresholdOrPopulationChange": False,
            "reason": (
                "ACTUAL_SESSION_SCHEDULE_FORMULA_RANK_AND_TERMINAL_MANIFESTS_DEPEND_"
                "ON_DECODED_SEALED_BARS_AND_CANNOT_BE_TRUTHFULLY_SEALED_PRE_ACCESS"
            ),
        },
        "controlledBindings": {
            "predecessorProtocol": {
                "version": "QUANT-TRADING-HISTORICAL-VALIDATION-v1.0.0",
                "contentHash": V1_PROTOCOL_HASH,
                "dispositionHash": V1_DISPOSITION_HASH,
                "fullPopulationResultHash": V1_FULL_RESULT_HASH,
                "resultValuesImported": False,
            },
            "successorDecisionContract": {
                "contractVersion": successor["contractVersion"],
                "modelVersion": successor["modelVersion"],
                "strategyVersion": successor["strategyVersion"],
                "formulaVersion": successor["formulaVersion"],
                "entryExitPolicyVersion": successor["entryExitPolicyVersion"],
                "engineVersion": successor["engineVersion"],
                "contentHash": successor["contentHash"],
            },
            "simulator": {
                "version": V11_SIMULATOR_VERSION,
                "primaryCostPolicyVersion": V11_PRIMARY_COST_POLICY_VERSION,
                "fixedSensitivityCostPolicyVersion": V11_FIXED_COST_POLICY_VERSION,
                "sourceAndRunnerHashes": "BOUND_PRE_ACCESS_BEFORE_ANY_NUMERIC_BYTE_READ",
            },
            "population": {
                "source": "C5_CURRENT_SURVIVOR_CONTROLLED_OVERLAP",
                "count": POPULATION_SIZE,
                "identitySetHash": C9_IDENTITY_SET_HASH,
                "identityProjectionSourceHash": C9_PREDICTOR_SEAL_HASH,
                "predictorValuesUsed": False,
                "historicalMembershipClaimed": False,
                "delistedPopulationClaimed": False,
                "survivorshipBias": True,
            },
            "priceEvidence": {
                "track": "YAHOO_ADJUSTED_OHLCV_CURRENT_SURVIVOR_APPROXIMATION",
                "receiptHash": C7_RECEIPT_HASH,
                "receiptFileSha256": C7_RECEIPT_FILE_SHA256,
                "calendarHash": C7_CALENDAR_HASH,
                "calendarFileSha256": C7_CALENDAR_FILE_SHA256,
                "aliasCount": 203,
                "equityCount": POPULATION_SIZE,
                "primaryBenchmark": "SPY",
                "adjustmentPolicy": "YAHOO-ADJCLOSE-RATIO-OHLC-v1.0.0",
                "separateDividendOrSplitCashFlows": False,
                "currentRevisionOnly": True,
            },
        },
        "batchProgression": {
            "ordering": "SHA256_UTF8_SECURITY_ID_ASC_THEN_SECURITY_ID_ASC",
            "nestedCumulativeSets": True,
            "batches": [
                {
                    "code": item.code,
                    "cumulativeCount": item.cumulative_count,
                    "incrementalCount": item.incremental_count,
                    "purpose": item.purpose,
                    "performanceGate": item.performance_gate,
                }
                for item in BATCHES
            ],
            "advanceOn": "STRUCTURAL_AND_REPLAY_INTEGRITY_ONLY_NEVER_PERFORMANCE",
            "stopOn": [
                "HASH_OR_IDENTITY_DRIFT",
                "FORMULA_OR_RUNNER_PARITY_FAILURE",
                "CALENDAR_OR_ADJUSTMENT_DRIFT",
                "INCOMPLETE_TERMINAL_REGISTRY",
                "NONDETERMINISTIC_REPLAY",
                "UNEXPLAINED_MISSING_ACTIVE_POSITION_BAR",
            ],
            "stoppedBatchMustBePreserved": True,
            "parameterChangeBetweenBatchesAllowed": False,
            "primaryAcceptanceUsesOnly": "FULL191",
            "manifestChronology": (
                "DERIVE_PILOT25_THEN_EXPANSION100_THEN_FULL191_AFTER_PAYLOAD_DECODE_"
                "BEFORE_ANY_PERFORMANCE_AGGREGATION"
            ),
            "pilotAndExpansionMayCalculatePerformance": False,
            "prefixEqualityRequired": True,
        },
        "strategyRules": {
            "arithmetic": {
                "precision": 50,
                "rounding": "ROUND_HALF_EVEN",
                "canonicalDecimal": "FINITE_PLAIN_BASE10_NO_EXPONENT_NO_SIGNED_ZERO",
            },
            "signal": successor["signal"],
            "decisionAnchor": {
                "firstEligibleSession": (
                    "EARLIEST_COMPLETED_SPY_SESSION_WITH_253_ALIGNED_SPY_ROWS_AND_"
                    "AT_LEAST_20_STRUCTURALLY_USABLE_SECURITY_HISTORIES"
                ),
                "frequency": "EVERY_FIFTH_COMPLETED_SPY_SESSION_FROM_FIRST_ELIGIBLE_SESSION",
                "lastEligibleDecision": (
                    "LATEST_ANCHORED_SESSION_WITH_NEXT_ENTRY_SESSION_PLUS_126_COMPLETED_"
                    "HOLDING_SESSIONS_PLUS_ONE_EXIT_SESSION"
                ),
                "rankingPopulation": "ALL_191_TERMINAL_ROWS_EACH_DECISION_DATE",
                "missingRowsRemainExplicit": True,
            },
            "entry": {
                **successor["entry"],
                "initialStop": (
                    "MAX(SIGNAL_CLOSE-MAX(3*ATR14,0.02*SIGNAL_CLOSE),0.90*SIGNAL_CLOSE)"
                ),
                "fill": "NEXT_SESSION_OPEN_ONLY_WHEN_INITIAL_STOP_LT_OPEN_LE_MAXIMUM_ENTRY_PRICE",
                "maximumEntryPrice": "SIGNAL_CLOSE+2*ATR14",
                "entryOrderExpiry": "END_OF_NEXT_OBSERVED_SESSION",
            },
            "exit": {
                **successor["exit"],
                "hardStopGapFill": "SESSION_OPEN_WHEN_OPEN_LE_ACTIVE_STOP",
                "hardStopTouchFill": "ACTIVE_STOP_WHEN_LOW_LE_ACTIVE_STOP",
                "trailingActivation": "CALCULATED_AFTER_COMPLETED_CLOSE_EFFECTIVE_NEXT_SESSION",
                "trailingAtr": "CURRENT_COMPLETED_SESSION_ATR14",
                "highestClose": "INCLUDES_ENTRY_SESSION_COMPLETED_CLOSE",
                "marketAndSecurityTrendEvaluation": "EVERY_COMPLETED_SESSION_CLOSE",
                "rankExitEvaluation": "REBALANCE_SESSIONS_ONLY",
                "holdingCount": (
                    "ENTRY_SESSION_IS_HELD_SESSION_1_EXIT_AT_NEXT_OPEN_AFTER_SESSION_126_CLOSE"
                ),
                "sameSecurityReentry": "PROHIBITED_ON_THE_SAME_SESSION_AS_ANY_EXIT",
                "nextOpenReasonPriority": [
                    "SPY_CLOSE_NOT_ABOVE_SMA200",
                    "SECURITY_CLOSE_NOT_ABOVE_SMA100",
                    "REBALANCE_PERCENTILE_BELOW_60_OR_NOT_RANKED",
                    "MAXIMUM_126_HELD_SESSIONS",
                    "UNEXPLAINED_MISSING_ACTIVE_BAR",
                ],
                "openPhasePriority": [
                    "PENDING_NEXT_OPEN_EXIT",
                    "ACTIVE_STOP_GAP",
                    "NEW_ENTRY",
                ],
                "intradayPriority": ["ACTIVE_STOP", "NO_PROFIT_TARGET"],
                "finalForcedLiquidation": False,
            },
            "portfolio": {
                **successor["portfolio"],
                "navSizingReference": "PRIOR_COMPLETED_CLOSE_NAV",
                "riskIncludes": [
                    "FILL_TO_INITIAL_STOP_LOSS",
                    "ESTIMATED_ENTRY_COST",
                    "WORST_CASE_51_BPS_INITIAL_STOP_NOTIONAL_EXIT_RESERVE",
                ],
                "shareCount": (
                    "FLOOR_MIN_OF_STOP_RISK_NOTIONAL_CAP_AND_AVAILABLE_CASH_THEN_"
                    "DECREMENT_UNTIL_BOTH_RISK_AND_CASH_CONSTRAINTS_PASS"
                ),
                "cashReturn": "0",
                "leverage": False,
                "shorting": False,
            },
        },
        "costPolicy": {
            "version": "C9-NONLINEAR-COST-v1.0.0",
            "entryAndExitChargedSeparately": True,
            "participation": "SIDE_FILL_NOTIONAL/PRIOR_20_COMPLETED_SESSION_MEDIAN_ADTV",
            "impactBps": "MIN(50,25*SQRT(PARTICIPATION))",
            "perSideBps": "1+IMPACT_BPS",
            "sideRate": "PER_SIDE_BPS/10000",
            "sideCostUsd": "SIDE_FILL_NOTIONAL*SIDE_RATE",
            "executionBarAdtvField": (
                "MEDIAN_OF_ADJUSTED_CLOSE_TIMES_VOLUME_FOR_EXACTLY_20_COMPLETED_"
                "SESSIONS_STRICTLY_BEFORE_THE_EXECUTION_BAR_SESSION"
            ),
            "entryLiquidityWindow": (
                "20_COMPLETED_SESSIONS_STRICTLY_BEFORE_ENTRY_SESSION_ENDING_AT_"
                "DECISION_SESSION"
            ),
            "exitLiquidityWindow": "20_COMPLETED_SESSIONS_STRICTLY_BEFORE_EXIT_SESSION",
            "currentExecutionBarCloseOrVolumeIncluded": False,
            "runnerMustRecomputeAndRejectAdtvMismatch": True,
            "missingOrInvalidLiquidity": "NO_FILL_FAIL_CLOSED",
            "fixedSensitivity": "5_BPS_PER_SIDE_SEPARATE_RESULT",
            "fixedSensitivityMethod": {
                "inputAndDecisionStream": "EXACTLY_IDENTICAL_TO_PRIMARY",
                "costReplacement": "REPLACE_C9_SIDE_COST_WITH_EXACT_5_BPS_PER_SIDE",
                "costAddition": False,
                "shareSizingAndCash": (
                    "INDEPENDENT_FULL_PORTFOLIO_REPLAY_FROM_100000_USD_USING_5_BPS_"
                    "ENTRY_COST_AND_5_BPS_STOP_EXIT_RESERVE"
                ),
                "ordersAndPositions": (
                    "RECOMPUTED_DETERMINISTICALLY_UNDER_FIXED_COST_CASH_AND_SIZING_"
                    "NEVER_COPIED_FROM_PRIMARY"
                ),
                "signalsRanksStopsAndExitConditions": "UNCHANGED_FROM_PRIMARY",
                "terminalAndMetricWindow": "IDENTICAL_TO_PRIMARY",
            },
            "monetaryQuantization": "NONE_CANONICAL_DECIMAL",
        },
        "terminalPolicy": {
            "adjustedOhlcv": True,
            "separateDividendOrSplitCashFlows": False,
            "missingCandidateBar": "EXPLICIT_MISSING_NOT_ELIGIBLE_NO_IMPUTATION",
            "missingActivePositionBar": (
                "PERMANENTLY_MARK_PERFORMANCE_INCOMPLETE_AND_SCHEDULE_NEXT_TRADABLE_OPEN_"
                "DIAGNOSTIC_EXIT"
            ),
            "haltOrSuspensionFill": "NO_ASSUMED_FILL",
            "knownAcquisitionDelistingOrBankruptcy": (
                "BLOCKED_NO_V11_TERMINAL_EVENT_INPUT_CONTRACT"
            ),
            "unprovenTerminalEvent": "INVALIDATE_AFFECTED_BATCH_NO_ZERO_OR_CASH_SUBSTITUTION",
            "completeTerminalRowRequired": "EVERY_SECURITY_EVERY_DECISION_AND_PORTFOLIO_SESSION",
            "productionEligibility": False,
        },
        "benchmarks": {
            "primary": {
                "code": "SPY",
                "construction": "BUY_AND_HOLD_WITH_WHOLE_SHARES_AND_RESIDUAL_CASH",
                "window": "FIRST_STRATEGY_ENTRY_SESSION_OPEN_TO_FINAL_MATURITY_SESSION_CLOSE",
                "calendar": "IDENTICAL_TO_STRATEGY",
                "initialCashUsd": "100000",
                "costAndLiquidityPolicy": "IDENTICAL_C9_NONLINEAR_ENTRY_AND_EXIT",
                "terminalPolicy": "IDENTICAL_TO_STRATEGY",
            },
            "cash": {"code": "CASH", "return": "0", "initialCashUsd": "100000"},
            "equalWeight": {
                "state": "NOT_OBSERVED",
                "reason": "V11_DECISION_CONTRACT_DOES_NOT_AUTHORIZE_EQUAL_WEIGHT_RESULT",
            },
            "sector": {
                "state": "NOT_OBSERVED",
                "reason": "NO_DATED_SECTOR_MAPPING_BOUND_TO_V11_POPULATION",
            },
            "benchmarkSubstitutionAllowed": False,
        },
        "metrics": {
            "portfolioSessionConvention": "AFTER_CLOSE_NAV_EACH_COMPLETED_SPY_SESSION",
            "primaryWindow": {
                "start": "FIRST_STRATEGY_ENTRY_SESSION_IMMEDIATELY_BEFORE_OPEN",
                "noStrategyEntry": "INVALID_PRIMARY_RESULT_NO_PERFORMANCE_CLAIM",
                "initialSeedNav": "100000",
                "firstLedgerNav": "AFTER_FIRST_ENTRY_SESSION_COMPLETED_CLOSE",
                "firstDailySimpleReturn": "FIRST_LEDGER_NAV/100000-1",
                "end": "FINAL_MATURITY_SESSION_AFTER_CLOSE_AFTER_ALL_STRATEGY_EXITS",
                "calendarDays": (
                    "FINAL_MATURITY_SESSION_DATE_MINUS_FIRST_STRATEGY_ENTRY_SESSION_DATE"
                ),
                "minimumCalendarDays": 1,
            },
            "totalReturn": "FINAL_AFTER_CLOSE_NAV/100000-1",
            "cagr": "(FINAL_AFTER_CLOSE_NAV/100000)^(365.2425/EXACT_CALENDAR_DAYS)-1",
            "spyExcess": ["TOTAL_RETURN_MINUS_SPY", "CAGR_MINUS_SPY"],
            "maxDrawdown": "MIN(NAV/RUNNING_PEAK_NAV-1)",
            "annualizedVolatility": "SAMPLE_STDDEV_DAILY_SIMPLE_NAV_RETURN*SQRT(252)",
            "sharpeRfZero": "MEAN_DAILY_SIMPLE_NAV_RETURN/SAMPLE_STDDEV*SQRT(252)",
            "zeroVolatilitySharpe": "NOT_OBSERVED",
            "turnover": "SUM_ABSOLUTE_EXECUTED_GROSS_NOTIONAL/MEAN_DAILY_NAV",
            "costs": ["TOTAL_COST_USD", "COST_AS_FRACTION_OF_INITIAL_CASH"],
            "trades": [
                "CLOSED_TRADE_COUNT",
                "WIN_RATE_NET_RETURN_GT_0",
                "LOSS_RATE_NET_RETURN_LT_0",
                "BREAKEVEN_RATE_NET_RETURN_EQ_0",
                "SEVERE_LOSS_RATE_NET_RETURN_LE_MINUS_20_PERCENT",
            ],
            "closedTradeMethod": {
                "pairing": (
                    "ONE_FILLED_BUY_TO_THE_NEXT_FILLED_SELL_FOR_THE_SAME_SECURITY_"
                    "WITH_NO_INTERVENING_FILLED_BUY"
                ),
                "entryCashOutflow": "ENTRY_FILL_PRICE*SHARES+ENTRY_SIDE_COST_USD",
                "exitCashInflow": "EXIT_FILL_PRICE*SHARES-EXIT_SIDE_COST_USD",
                "netPnl": "EXIT_CASH_INFLOW-ENTRY_CASH_OUTFLOW",
                "netReturn": "NET_PNL/ENTRY_CASH_OUTFLOW",
                "openTradeAtEndAllowed": False,
                "closedTradeCount": "EXACT_FILLED_BUY_SELL_PAIR_COUNT",
            },
            "coverage": [
                "TERMINAL_ROW_COUNT",
                "USABLE_SECURITY_RATE_PER_DECISION",
                "RANKED_CROSS_SECTION_COUNT_PER_DECISION",
                "MISSING_REASON_COUNTS",
                "TIME_IN_MARKET",
            ],
            "subperiods": ["2015-2019", "2020-2022", "2023-2026"],
            "subperiodMethod": {
                "kind": "SLICE_PRIMARY_FULL_RUN_AFTER_CLOSE_NAV_NO_INDEPENDENT_REPLAY",
                "start": "FIRST_COMPLETED_SPY_SESSION_ON_OR_AFTER_CALENDAR_START",
                "end": "LAST_COMPLETED_SPY_SESSION_ON_OR_BEFORE_CALENDAR_END",
                "strategyReturn": "END_AFTER_CLOSE_NAV/START_AFTER_CLOSE_NAV-1",
                "spyReturn": "END_AFTER_CLOSE_NAV/START_AFTER_CLOSE_NAV-1",
                "cagr": "(END_NAV/START_NAV)^(365.2425/EXACT_CALENDAR_DAY_DIFFERENCE)-1",
                "minimumCalendarDayDifference": 1,
                "positionsAndCashCarryAcrossBoundaries": True,
                "boundaryResetOrTrade": False,
                "boundaryTransactionCost": "NONE_BECAUSE_NO_SYNTHETIC_BOUNDARY_TRADE",
                "warmupAndDecisionSchedule": "IDENTICAL_UNCHANGED_PRIMARY_FULL_RUN",
            },
            "stressWindows": [
                ["2018-09-20", "2018-12-24"],
                ["2020-02-19", "2020-03-23"],
                ["2022-01-03", "2022-06-16"],
            ],
            "subperiodAndStressStatus": "DIAGNOSTIC_EXCEPT_EXPLICIT_SUBPERIOD_GATE",
        },
        "acceptance": {
            "evaluationCount": 1,
            "primaryBatch": "FULL191",
            "allGatesRequired": True,
            "integrityGates": [
                "EXACT_PROTOCOL_AND_SUCCESSOR_CONTRACT_HASHES",
                "EXACT_191_MEMBER_TERMINAL_DENOMINATOR",
                "DETERMINISTIC_EXACT_REPLAY",
                "NO_UNEXPLAINED_ACTIVE_POSITION_GAP",
                "NO_FORMULA_COST_OR_LEDGER_DRIFT",
                "NO_OUTCOME_AWARE_PARAMETER_CHANGE",
                "PRIMARY_STRATEGY_TERMINAL_STATE_COMPLETE_CASH",
                "FIXED_SENSITIVITY_STRATEGY_TERMINAL_STATE_COMPLETE_CASH",
                "SPY_BENCHMARK_EXITED_AT_FINAL_MATURITY_CLOSE_WITH_EXIT_COST",
            ],
            "numericGates": {
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
            },
            "passingInterpretation": (
                "DIRECTIONALLY_SUPPORTIVE_DEVELOPMENT_OBSERVATION_SAME_HISTORY_ONLY"
            ),
            "failingInterpretation": "NOT_DIRECTIONALLY_SUPPORTIVE_NO_RETUNING_ON_SAME_OUTCOME",
            "invalidInterpretation": "INVALID_OR_INCOMPLETE_NO_PERFORMANCE_CLAIM",
            "modelEvidenceLabelAfterAnyResult": "NOT_VALIDATED",
            "claimUpgradeAllowed": False,
            "productionOrBrokerageAuthorization": False,
        },
        "executionBoundary": {
            "checkedV11RunnerRequiredBeforeOutcomeAccess": True,
            "preAccessSealScope": [
                "EXACT_191_DENOMINATOR_ORDER_IDS_AND_SYMBOLS",
                "EXACT_203_SOURCE_PATH_BYTE_FILE_AND_CANONICAL_CONTENT_HASHES",
                "CALENDAR_AUTHORITY_SOURCE_FILE_HASH_AND_DECLARED_BOUNDS",
                "DECISION_ANCHOR_MATURITY_BATCH_AND_DERIVATION_RULES",
                "SOURCE_CODE_RUNTIME_FORMULA_COST_METRIC_AND_ACCEPTANCE_IDENTITIES",
                "ONE_EVALUATION_RETRY_ZERO_UNKNOWN_NO_RETRY_AND_OUTPUT_PATHS",
            ],
            "preAccessFutureValueDerivedManifestHashesForbidden": True,
            "outcomeAccessIntentRequired": True,
            "outcomeExecutionIntentRequiredBeforeFirstNumericByteRead": True,
            "journalGrammar": [
                "PREPARATION_INTENT",
                "PREPARATION_STRUCTURAL_COMPLETE",
                "OUTCOME_ACCESS_INTENT",
                "OUTCOME_EXECUTION_INTENT",
                "POST_ACCESS_PRE_PERFORMANCE_INPUT_SEAL",
                "EXACTLY_ONE_COMPLETED_FAILED_OR_UNKNOWN_TERMINAL",
            ],
            "postAccessPrePerformanceInputSeal": {
                "derivedInSameCheckedRunAfterPayloadDecode": True,
                "mustPrecedeReturnPnlBenchmarkOrAcceptanceAggregation": True,
                "contents": [
                    "EXACT_VERIFIED_SPY_COMPLETED_SESSION_VECTOR_AND_HASH",
                    "EXACT_FIRST_ELIGIBLE_AND_LAST_MATURE_DECISION_SCHEDULE",
                    "PILOT25_FORMULA_REPLAY_AND_TERMINAL_INPUT_MANIFESTS",
                    "EXPANSION100_FORMULA_REPLAY_AND_TERMINAL_INPUT_MANIFESTS",
                    "FULL191_FORMULA_REPLAY_TERMINAL_INPUT_AND_RANK_MANIFESTS",
                    "EXACT_25_TO_100_TO_191_PREFIX_EQUALITY",
                    "STATE_VOCABULARIES_SOURCE_HASHES_COUNTS_AND_SCHEDULES",
                ],
                "performanceEvaluated": False,
                "returnPnlBenchmarkOrAcceptanceFieldsAllowed": False,
            },
            "numericExposureLimitation": (
                "DECODING_PAYLOAD_BYTES_EXPOSES_BARS_TO_THE_CHECKED_PROCESS_BUT_NO_"
                "RETURN_PNL_BENCHMARK_PERFORMANCE_OR_ACCEPTANCE_VALUE_MAY_BE_"
                "CALCULATED_INSPECTED_OR_EMITTED_BEFORE_THE_INPUT_SEAL"
            ),
            "uninterruptedNoninteractiveRunRequired": True,
            "humanOrLlmPauseBetweenDecodeInputSealAndPerformanceAllowed": False,
            "batch25And100Purpose": "INTEGRITY_AND_REPLAY_ONLY_NO_PERFORMANCE",
            "full191OnlyPerformanceAggregation": True,
            "onePassOnly": True,
            "exactReplayMayVerifyButNotRewrite": True,
            "resultMustBindExecutionIntentAndPostAccessInputSeal": True,
            "deterministicPrewriteFailureState": "FAILED",
            "uncertainPartialDurableState": "UNKNOWN_NO_RETRY",
            "networkAuthorized": False,
            "providerRequests": 0,
            "databaseWritesAuthorized": False,
            "automaticBrokerageExecution": False,
            "llmSignalOrWeightAuthority": False,
        },
    }
    body["contentHash"] = canonical_hash(body)
    return deepcopy(body)


def validate_protocol(value: dict[str, Any]) -> None:
    """Fail closed unless *value* is the exact frozen protocol."""

    if type(value) is not dict or value != frozen_protocol():
        raise QuantHistoricalValidationV11Violation("Quant Trading v1.1.1 protocol drift")


__all__ = [
    "BATCHES",
    "PROTOCOL_STATE",
    "PROTOCOL_VERSION",
    "QuantHistoricalValidationV11Violation",
    "ValidationBatchV11",
    "batch_for_ordinal",
    "canonical_hash",
    "frozen_protocol",
    "population_order_key",
    "validate_protocol",
]
