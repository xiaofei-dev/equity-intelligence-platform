from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from equity_analysis.analytics_interface.contracts import canonical_hash

FORWARD_DQV_EVALUATION_PROTOCOL_V22 = "FORWARD-DQV-EVALUATION-PROTOCOL-v2.2.0"
FORWARD_DQV_PROTOCOL_FIXTURE_V22 = "FORWARD-DQV-EVALUATION-PROTOCOL-FIXTURE-v2.2.0"
REQUIRED_BENCHMARKS = (
    "SPY",
    "SECTOR",
    "EQUAL_WEIGHT",
    "PURE_MOMENTUM",
    "PURE_VALUE",
    "PURE_QUALITY",
)
FORMAL_HORIZONS = (5, 20, 60, 252)
ALL_HORIZONS = (5, 20, 60, 126, 252)
HISTORICAL_RANDOM_SEED = 20260729


class DqvEvaluationProtocolV22Error(ValueError):
    pass


def _file_sha256(path: Path) -> str:
    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise DqvEvaluationProtocolV22Error(f"Protocol dependency must be a JSON object: {path}")
    return payload


def _verified_binding(
    repository_root: Path,
    *,
    relative_path: str,
    content_hash_field: str,
) -> dict[str, str]:
    path = repository_root / relative_path
    payload = _read_json(path)
    recorded_hash = payload.get(content_hash_field)
    if not isinstance(recorded_hash, str):
        raise DqvEvaluationProtocolV22Error(
            f"Protocol dependency has no {content_hash_field}: {relative_path}"
        )
    body = {key: value for key, value in payload.items() if key != content_hash_field}
    computed_hash = canonical_hash(body).removeprefix("sha256:").lower()
    normalized_recorded_hash = recorded_hash.removeprefix("sha256:").lower()
    if computed_hash != normalized_recorded_hash:
        raise DqvEvaluationProtocolV22Error(
            f"Protocol dependency canonical hash is invalid: {relative_path}"
        )
    return {
        "path": relative_path,
        "schemaVersion": str(payload.get("schemaVersion")),
        "artifactContentHash": recorded_hash,
        "fileSha256": _file_sha256(path),
    }


def _horizon_contract() -> list[dict[str, Any]]:
    rows = []
    for sessions in ALL_HORIZONS:
        long_horizon = sessions in {126, 252}
        formal = sessions in FORMAL_HORIZONS
        rows.append(
            {
                "completedSessions": sessions,
                "modelTrack": "LONG_HORIZON" if long_horizon else "TACTICAL",
                "evaluationRole": (
                    "LONG_HORIZON_INTERIM_DIAGNOSTIC"
                    if sessions == 126
                    else "LONG_HORIZON_FORMAL"
                    if sessions == 252
                    else "TACTICAL_FORMAL"
                ),
                "formalGateEligible": formal,
                "minimumEligibleSecurityDecisions": 100,
                "minimumCoverageRatio": "0.80",
                "minimumDistinctDecisionDates": 2,
                "minimumMaturedCalendarSpanSessions": sessions * 2,
                "minimumBootstrapBlockSessions": sessions,
                "purgeSessions": sessions,
                "embargoSessions": sessions,
                "outcomeDependence": "PURGED_BLOCK",
                "resampling": "BLOCK_BOOTSTRAP",
                "naturalMaturityRequired": True,
            }
        )
    return rows


def _historical_diagnostic_contract() -> dict[str, Any]:
    return {
        "evaluationRole": "DEVELOPMENT_OBSERVED",
        "formalGateEligible": False,
        "claimCeiling": "DIAGNOSTIC_ONLY",
        "untouchedHoldout": False,
        "outcomesWereObservableBeforeThisProtocol": True,
        "selectionMustBeSealedBeforeReplay": True,
        "selectionAfterOutcomesExistDoesNotCreateAHoldout": True,
        "randomSelection": {
            "method": "STRATIFIED_RANDOM_COMPLETED_SESSIONS",
            "seed": HISTORICAL_RANDOM_SEED,
            "samplesPerBand": 6,
            "minimumSessionSpacing": 15,
            "bands": [
                {
                    "name": "RECENT_3_TO_9_MONTHS",
                    "minimumMonthsBeforeFreeze": 3,
                    "maximumMonthsBeforeFreeze": 9,
                },
                {
                    "name": "PRIOR_1_TO_3_YEARS",
                    "minimumMonthsBeforeFreeze": 12,
                    "maximumMonthsBeforeFreeze": 36,
                },
                {
                    "name": "OLDER_4_TO_10_YEARS",
                    "minimumMonthsBeforeFreeze": 48,
                    "maximumMonthsBeforeFreeze": 120,
                },
            ],
        },
        "calendarAnchors": {
            "method": "LAST_COMPLETED_SESSION_ON_OR_BEFORE_OFFSET",
            "monthOffsetsBeforeFreeze": [3, 6, 9, 12, 18, 24, 48, 72, 120],
            "missingAnchorPolicy": "EXPLICIT_MISSING",
        },
        "horizonsCompletedSessions": list(ALL_HORIZONS),
        "outcomeAvailabilityPolicy": ("EVALUATE_ONLY_HORIZONS_MATURED_WITHIN_THE_FROZEN_HISTORY"),
        "leakageControls": {
            "decisionInputs": ("AVAILABLE_AND_INGESTED_NO_LATER_THAN_DECISION_CUTOFF"),
            "membership": (
                "HISTORICAL_MEMBERSHIP_REQUIRED_FOR_PIT_CLAIM;"
                "CURRENT_UNIVERSE_RETROSPECTIVE_IS_DIAGNOSTIC_ONLY"
            ),
            "delistedSecurities": "RETAIN_WITH_EXPLICIT_TERMINAL_STATE",
            "classification": "DATED_SECTOR_AND_SIZE_BINDING_REQUIRED",
            "revisions": (
                "DECISION_TIME_REVISION_REQUIRED;CURRENT_RESTATEMENT_CANNOT_BE_BACKDATED"
            ),
            "corporateActions": (
                "DECISION_FEATURES_USE_ONLY_ACTIONS_KNOWN_AT_CUTOFF;"
                "OUTCOME_ADJUSTMENT_EVIDENCE_IS_RECORDED_SEPARATELY"
            ),
            "outcomes": (
                "LOADED_ONLY_AFTER_SLICE_PLAN_HASH_IS_SEALED;"
                "PRIOR_HUMAN_OBSERVATION_REMAINS_DISCLOSED"
            ),
            "parameterChangesAfterReplay": "NEW_MODEL_AND_PROTOCOL_VERSION_REQUIRED",
        },
    }


def _metric_contract() -> dict[str, Any]:
    return {
        "returnAccounting": {
            "entry": "NEXT_COMPLETED_SESSION_OPEN",
            "exit": "PREREGISTERED_HORIZON_COMPLETED_SESSION_CLOSE",
            "requiredRepresentations": ["GROSS", "COST", "NET"],
            "benchmarkComparisonUses": "NET_RETURN",
            "liquiditySensitiveCostRequired": True,
        },
        "requiredMetrics": [
            "RANK_INFORMATION_COEFFICIENT",
            "TOP_MINUS_BOTTOM_NET_RETURN",
            "TOP_MINUS_EACH_BENCHMARK_NET_RETURN",
            "MAXIMUM_ADVERSE_EXCURSION",
            "MAXIMUM_FAVORABLE_EXCURSION",
            "MAXIMUM_DRAWDOWN",
            "DOWNSIDE_CAPTURE",
            "TURNOVER",
            "LIQUIDITY_PARTICIPATION_RATE",
            "COVERAGE",
            "ASSESSED_COUNT",
            "MISSING_COUNT",
            "STALE_COUNT",
            "INVALID_COUNT",
            "NOT_APPLICABLE_COUNT",
            "SPECIALIZED_MODEL_REQUIRED_COUNT",
            "EXCLUDED_COUNT",
            "ABSTENTION_COUNT",
        ],
        "benchmarks": list(REQUIRED_BENCHMARKS),
        "longHorizonTargetsRemainSeparate": [
            "BUSINESS_QUALITY",
            "SECURITY_ATTRACTIVENESS",
            "DOWNSIDE_RISK",
        ],
        "defaultLongHorizonAggregateRankAuthorized": False,
        "aiMayAffectDeterministicFields": False,
    }


def _statistical_contract() -> dict[str, Any]:
    return {
        "confidenceLevel": "0.90",
        "familyWiseAlpha": "0.10",
        "multipleComparisonMethod": "HOLM_BONFERRONI",
        "bootstrapMethod": "DETERMINISTIC_CIRCULAR_BLOCK_BOOTSTRAP",
        "bootstrapIterations": 10_000,
        "bootstrapSeed": HISTORICAL_RANDOM_SEED,
        "ordinaryIidBootstrapAllowed": False,
        "confirmatoryFamilies": [
            {
                "name": "TACTICAL_5_SESSION",
                "tests": [
                    "DISCRIMINATION",
                    "ACTIONABILITY_PARTICIPATION_MINUS_ABSTENTION",
                    *[f"NET_EXCESS_{benchmark}" for benchmark in REQUIRED_BENCHMARKS],
                ],
            },
            {
                "name": "TACTICAL_20_SESSION",
                "tests": [
                    "DISCRIMINATION",
                    "ACTIONABILITY_PARTICIPATION_MINUS_ABSTENTION",
                    *[f"NET_EXCESS_{benchmark}" for benchmark in REQUIRED_BENCHMARKS],
                ],
            },
            {
                "name": "TACTICAL_60_SESSION",
                "tests": [
                    "DISCRIMINATION",
                    "ACTIONABILITY_PARTICIPATION_MINUS_ABSTENTION",
                    *[f"NET_EXCESS_{benchmark}" for benchmark in REQUIRED_BENCHMARKS],
                ],
            },
            {
                "name": "LONG_252_BUSINESS_QUALITY",
                "tests": ["FUTURE_FUNDAMENTAL_DISCRIMINATION"],
            },
            {
                "name": "LONG_252_SECURITY_ATTRACTIVENESS",
                "tests": [
                    "DISCRIMINATION",
                    *[f"NET_EXCESS_{benchmark}" for benchmark in REQUIRED_BENCHMARKS],
                ],
            },
            {
                "name": "LONG_252_DOWNSIDE_RISK",
                "tests": [
                    "MAXIMUM_DRAWDOWN_NONINFERIORITY",
                    "DOWNSIDE_CAPTURE_NOT_ABOVE_ONE",
                ],
            },
        ],
        "positiveClaimRule": (
            "EVERY_CONFIRMATORY_TEST_IN_THE_RELEVANT_FAMILY_MUST_PASS_ITS_HOLM_ADJUSTED_BOUND"
        ),
        "tacticalActionabilityPairing": {
            "groupingFrozenBeforeOutcome": True,
            "participationCategories": ["ENTRY", "LIMITED_ENTRY"],
            "comparison": "PAIRED_WITHIN_DECISION_DATE_NET_RETURN_SPREAD",
            "minimumPairedDecisionDates": 2,
            "minimumObservationsPerGroup": 20,
            "singleGroupDatePolicy": "REPORT_NOT_COMPARABLE_AND_EXCLUDE_FROM_THIS_TEST",
            "outcomeDrivenRegroupingAuthorized": False,
            "exactMarketBottomPredictionClaimed": False,
        },
    }


def _stratification_contract() -> dict[str, Any]:
    return {
        "dimensions": ["SECTOR", "MARKET_CAP_SIZE_BAND"],
        "sectorSourceMustBeDated": True,
        "sizeBands": ["MEGA", "LARGE", "MID", "SMALL", "MISSING"],
        "minimumEligibleDecisionsForInferentialStratum": 20,
        "minimumDistinctDecisionDatesForInferentialStratum": 2,
        "allStrataReportedEvenWhenUnderpowered": True,
        "underpoweredStratumStatus": "INSUFFICIENT_EVIDENCE",
        "consistencyGuardrail": (
            "AN_ADEQUATELY_POWERED_PREDECLARED_STRATUM_WITH_A_"
            "HOLM_ADJUSTED_ADVERSE_UPPER_BOUND_CAPS_THE_TRACK_AT_MIXED"
        ),
        "missingClassificationPolicy": "EXPLICIT_MISSING_NOT_IMPUTED",
    }


def _terminal_rules() -> dict[str, Any]:
    return {
        "BLOCKED_BY_DATA": [
            "HASH_OR_VERSION_MISMATCH",
            "INCOMPLETE_FROZEN_POPULATION",
            "REQUIRED_BENCHMARK_UNAVAILABLE",
            "LOOK_AHEAD_OR_REVISION_LEAKAGE",
            "OUTCOME_NOT_NATURALLY_MATURED",
            "ORDINARY_IID_BOOTSTRAP_PROPOSED",
        ],
        "INSUFFICIENT_EVIDENCE": [
            "ELIGIBLE_SECURITY_DECISIONS_BELOW_100",
            "COVERAGE_BELOW_0_80",
            "DISTINCT_DECISION_DATES_BELOW_2",
            "MATURED_CALENDAR_SPAN_BELOW_TWO_HORIZONS",
            "REQUIRED_INTERVAL_OR_PATH_METRIC_MISSING",
        ],
        "NOT_VALIDATED": [
            "ANY_REQUIRED_HOLM_ADJUSTED_POSITIVE_LOWER_BOUND_NOT_ABOVE_ZERO",
            "MAXIMUM_DRAWDOWN_WORSE_THAN_FROZEN_BENCHMARK",
            "DOWNSIDE_CAPTURE_ABOVE_ONE",
        ],
        "MIXED": [
            "LONG_HORIZON_TARGETS_DISAGREE",
            "ADEQUATELY_POWERED_PREDECLARED_STRATUM_IS_MATERIALLY_ADVERSE",
        ],
        "VALIDATED": [
            "ONLY_FORMAL_PROSPECTIVE_HORIZON",
            "ALL_RELEVANT_CONFIRMATORY_FAMILIES_PASS",
            "ALL_RISK_AND_EVIDENCE_GUARDRAILS_PASS",
        ],
        "DIAGNOSTIC_ONLY": [
            "EVERY_HISTORICAL_SLICE",
            "126_SESSION_LONG_HORIZON_INTERIM",
        ],
        "thresholdOptimizationAfterObservedOutcomeAllowed": False,
        "favorableConclusionRequired": False,
    }


def build_protocol_fixture(repository_root: Path) -> dict[str, Any]:
    bindings = {
        "tacticalFreeze": _verified_binding(
            repository_root,
            relative_path="docs/generated/tactical-v2-2-model-freeze.json",
            content_hash_field="artifactContentHash",
        ),
        "longHorizonFreeze": _verified_binding(
            repository_root,
            relative_path="docs/generated/long-horizon-v1-1-model-freeze.json",
            content_hash_field="artifactContentHash",
        ),
        "forwardPreregistrationV2": _verified_binding(
            repository_root,
            relative_path="docs/generated/forward-dqv-preregistration-v2.json",
            content_hash_field="preregistrationContentHash",
        ),
        "benchmarkPreregistrationV22": _verified_binding(
            repository_root,
            relative_path="docs/generated/forward-benchmark-preregistration-v2-2.json",
            content_hash_field="preregistrationContentHash",
        ),
        "outcomeLedgerV18Acceptance": _verified_binding(
            repository_root,
            relative_path="docs/generated/forward-dqv-v18-acceptance-v1.json",
            content_hash_field="artifactContentHash",
        ),
    }
    body = {
        "artifactType": "FORWARD_DQV_EVALUATION_PROTOCOL_FIXTURE",
        "schemaVersion": FORWARD_DQV_PROTOCOL_FIXTURE_V22,
        "protocolVersion": FORWARD_DQV_EVALUATION_PROTOCOL_V22,
        "status": "BLOCKED_AWAITING_PROSPECTIVE_DATA",
        "purpose": "CONTRACT_FIXTURE",
        "bindings": bindings,
        "historicalDiagnostics": _historical_diagnostic_contract(),
        "prospectiveHorizons": _horizon_contract(),
        "metrics": _metric_contract(),
        "statistics": _statistical_contract(),
        "stratification": _stratification_contract(),
        "terminalRules": _terminal_rules(),
        "currentBlockers": [
            "PROSPECTIVE_ENROLLMENT_NOT_EXECUTED",
            "NATURALLY_MATURED_OUTCOMES_NOT_AVAILABLE",
        ],
        "executionBoundary": {
            "historicalScoringExecuted": False,
            "prospectiveEnrollmentExecuted": False,
            "outcomeObservationExecuted": False,
            "providerNetworkRequests": 0,
            "databaseWrites": 0,
            "commitCreated": False,
            "pushExecuted": False,
            "deploymentExecuted": False,
            "automaticTradingAuthorized": False,
            "rawProviderValuesIncluded": False,
        },
    }
    return {**body, "artifactContentHash": canonical_hash(body)}


def verify_protocol_fixture(
    payload: dict[str, Any],
    *,
    repository_root: Path,
) -> None:
    expected = build_protocol_fixture(repository_root)
    if payload != expected:
        raise DqvEvaluationProtocolV22Error(
            "Forward DQV v2.2 protocol fixture differs from the frozen contract"
        )
    if payload["status"] != "BLOCKED_AWAITING_PROSPECTIVE_DATA":
        raise DqvEvaluationProtocolV22Error(
            "Protocol fixture cannot claim readiness before prospective data"
        )
    horizons = payload["prospectiveHorizons"]
    if tuple(item["completedSessions"] for item in horizons) != ALL_HORIZONS:
        raise DqvEvaluationProtocolV22Error("Five-horizon contract is incomplete")
    formal = tuple(item["completedSessions"] for item in horizons if item["formalGateEligible"])
    if formal != FORMAL_HORIZONS:
        raise DqvEvaluationProtocolV22Error("Formal-horizon roles are incorrect")
    if tuple(payload["metrics"]["benchmarks"]) != REQUIRED_BENCHMARKS:
        raise DqvEvaluationProtocolV22Error("Six-benchmark contract is incomplete")


def write_or_verify_protocol_fixture(
    repository_root: Path,
    *,
    output_path: Path,
) -> Path:
    payload = build_protocol_fixture(repository_root)
    encoded = (json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n").encode(
        "utf-8"
    )
    if output_path.exists():
        if output_path.read_bytes() != encoded:
            raise DqvEvaluationProtocolV22Error(
                f"Immutable protocol fixture conflict: {output_path}"
            )
        return output_path
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(encoded)
    return output_path
