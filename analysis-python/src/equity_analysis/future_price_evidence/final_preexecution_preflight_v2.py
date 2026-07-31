from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from equity_analysis.analytics_interface.contracts import canonical_hash
from equity_analysis.daily_refresh.calendar import UnitedStatesMarketCalendar
from equity_analysis.forward_validation.v18_acceptance_v1 import (
    load_and_verify_forward_dqv_v18_acceptance,
)
from equity_analysis.future_price_evidence.contracts_v1 import (
    ACTION_ADJUSTMENT_BINDING_VERSION,
    ADTV_POLICY_VERSION,
    ADTV_WINDOW_SESSIONS,
    FUTURE_PRICE_EVIDENCE_VERSION,
    RAW_HTTP_CAPTURE_VERSION,
    YAHOO_CHART_NORMALIZATION_VERSION,
)
from equity_analysis.future_price_evidence.history_capture_runner_v2 import (
    DEFAULT_LEASE_PATH,
    DEFAULT_STORAGE_ROOT,
    FUTURE_PRICE_HISTORY_CAPTURE_VERSION,
    LIVE_CONFIRMATION,
    load_verified_history_preflight_v2,
)
from equity_analysis.future_price_evidence.history_coverage_v2 import (
    FUTURE_PRICE_HISTORY_COVERAGE_VERSION,
    MOMENTUM_12_1_REQUIRED_SESSIONS,
)
from equity_analysis.future_price_evidence.history_preflight_v2 import (
    DEFAULT_EXTERNAL_REFERENCE_PATH,
    DEFAULT_HISTORY_PREFLIGHT_OUTPUT,
    DEFAULT_V22_SEAL_PATH,
    EXPECTED_PRICE_SYMBOLS,
    EXPECTED_TOTAL_HTTP_ATTEMPTS,
    HISTORY_WINDOW_CALENDAR_DAYS,
)

FINAL_PREEXECUTION_PREFLIGHT_VERSION = (
    "FUTURE-PRICE-HISTORY-FINAL-PREEXECUTION-PREFLIGHT-v2.1.0"
)
FINAL_READINESS_CLOSEOUT_VERSION = (
    "FORWARD-V2.2-FINAL-SUCCESSOR-READINESS-CLOSEOUT-v1.1.0"
)
FINAL_V18_ACCEPTANCE_HASH = (
    "sha256:e5ce27f66981d8341ed0d88f33fc72d380999b3d68360d53ce83f908f51a5f1e"
)
EXPECTED_SUCCESSOR_BLOCKERS = (
    "COMPLETED_SESSION_PRICE_EVIDENCE_MISSING",
    "POST_FREEZE_DECISION_MANIFEST_MISSING",
    "SIX_BENCHMARK_CONSTRUCTION_MISSING",
)
DEFAULT_REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_FINAL_READINESS_PATH = (
    DEFAULT_REPOSITORY_ROOT
    / "docs/generated/forward-v2-2-final-successor-readiness-closeout-v2.json"
)
DEFAULT_V18_ACCEPTANCE_PATH = (
    DEFAULT_REPOSITORY_ROOT
    / "docs/generated/forward-dqv-v18-acceptance-v1.json"
)
DEFAULT_OUTPUT_PATH = (
    DEFAULT_REPOSITORY_ROOT
    / "docs/generated/"
    "future-price-history-final-preexecution-preflight-v2-1.json"
)

_RUNNER_PATH = (
    "analysis-python/src/equity_analysis/future_price_evidence/"
    "history_capture_runner_v2.py"
)
_CLI_PATH = (
    "analysis-python/src/equity_analysis/future_price_evidence/"
    "history_capture_cli_v2.py"
)
_COVERAGE_PATH = (
    "analysis-python/src/equity_analysis/future_price_evidence/"
    "history_coverage_v2.py"
)
_CONTRACTS_PATH = (
    "analysis-python/src/equity_analysis/future_price_evidence/"
    "contracts_v1.py"
)
_UNIVERSE_PATH = (
    "analysis-python/resources/universes/"
    "market-intelligence-closed-test-us-v1.json"
)


class FinalPreexecutionPreflightError(RuntimeError):
    pass


def build_final_preexecution_preflight_v2(
    *,
    repository_root: Path = DEFAULT_REPOSITORY_ROOT,
    as_of: datetime,
    market_calendar: UnitedStatesMarketCalendar | None = None,
) -> dict[str, Any]:
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise FinalPreexecutionPreflightError("AS_OF_MUST_BE_TIMEZONE_AWARE")

    generated_root = repository_root / "docs/generated"
    history_preflight_path = generated_root / DEFAULT_HISTORY_PREFLIGHT_OUTPUT.name
    final_readiness_path = generated_root / DEFAULT_FINAL_READINESS_PATH.name
    v18_acceptance_path = generated_root / DEFAULT_V18_ACCEPTANCE_PATH.name
    seal_path = generated_root / DEFAULT_V22_SEAL_PATH.name
    external_reference_path = generated_root / DEFAULT_EXTERNAL_REFERENCE_PATH.name
    universe_path = repository_root / _UNIVERSE_PATH

    history_preflight, plan = load_verified_history_preflight_v2(
        history_preflight_path
    )
    final_readiness = _verified_artifact(
        final_readiness_path,
        hash_field="artifactContentHash",
    )
    v18_acceptance, v18_hash = load_and_verify_forward_dqv_v18_acceptance(
        v18_acceptance_path,
        repository_root,
    )
    seal = _verified_artifact(seal_path, hash_field="sealContentHash")
    external_reference = _verified_artifact(
        external_reference_path,
        hash_field="artifactContentHash",
    )
    universe = json.loads(universe_path.read_text(encoding="utf-8"))

    _verify_source_contracts(
        history_preflight=history_preflight,
        plan=plan,
        final_readiness=final_readiness,
        v18_acceptance=v18_acceptance,
        v18_hash=v18_hash,
        seal=seal,
        external_reference=external_reference,
        universe=universe,
        universe_path=universe_path,
    )

    calendar = market_calendar or UnitedStatesMarketCalendar()
    latest_completed_session = calendar.latest_completed_session(as_of)
    target_completed = latest_completed_session >= plan.target_session
    storage_audit = _capture_storage_audit(repository_root)
    blocked_reasons = []
    if not target_completed:
        blocked_reasons.append("TARGET_SESSION_NOT_COMPLETED")
    if storage_audit["leaseExists"]:
        blocked_reasons.append("PREEXISTING_CAPTURE_LEASE_REQUIRES_REVIEW")
    if storage_audit["unknownPhysicalRequestCount"]:
        blocked_reasons.append("PHYSICAL_REQUEST_STATE_UNKNOWN")
    status = (
        "READY_FOR_NAMED_DUAL_CALENDAR_REVIEW_AND_SINGLE_EXECUTION"
        if not blocked_reasons
        else "BLOCKED_AWAITING_TARGET_SESSION_COMPLETION"
        if blocked_reasons == ["TARGET_SESSION_NOT_COMPLETED"]
        else "BLOCKED_PREEXECUTION_SAFETY_STATE"
    )

    live_argv = (
        r".\analysis-python\.venv\Scripts\python.exe",
        "-m",
        "equity_analysis.future_price_evidence.history_capture_cli_v2",
        "--execute-live",
        "--confirm-live",
        LIVE_CONFIRMATION,
        "--reviewed-by",
        "<named reviewer>",
        "--confirm-nyse-session",
        "--confirm-nyse-close",
        "--confirm-nasdaq-session",
        "--confirm-nasdaq-close",
    )
    command_body = {
        "workingDirectory": str(repository_root),
        "environment": {"PYTHONPATH": "analysis-python/src"},
        "argv": list(live_argv),
        "databaseFlagPresent": False,
        "resumeFlagPresent": False,
    }
    command_body["commandHash"] = canonical_hash(command_body)

    body: dict[str, Any] = {
        "artifactType": "FUTURE_PRICE_HISTORY_FINAL_PREEXECUTION_PREFLIGHT",
        "schemaVersion": FINAL_PREEXECUTION_PREFLIGHT_VERSION,
        "evaluatedAt": as_of.astimezone(UTC).isoformat(),
        "status": status,
        "blockedReasons": blocked_reasons,
        "targetSession": plan.target_session.isoformat(),
        "latestCompletedSession": latest_completed_session.isoformat(),
        "targetSessionCompleted": target_completed,
        "plan": {
            "version": plan.version,
            "planHash": plan.plan_hash,
            "symbolPlanVersion": plan.symbol_plan_version,
            "symbolPlanHash": plan.symbol_plan_hash,
            "orderedSymbolsHash": plan.ordered_symbols_hash,
            "baseSymbolPlanHash": plan.base_symbol_plan_hash,
            "universeVersion": plan.universe_version,
            "universeFileSha256": plan.universe_file_sha256,
            "preregistrationSealHash": plan.preregistration_seal_hash,
            "externalReferenceUniverseHash": (
                plan.external_reference_universe_hash
            ),
            "externalReferenceRowsHash": plan.external_reference_rows_hash,
            "priceSymbolCount": len(plan.ordered_symbols),
            "yahooChartRequestCount": EXPECTED_PRICE_SYMBOLS,
            "officialCalendarRequestCount": 2,
            "physicalHttpAttemptHardCeiling": EXPECTED_TOTAL_HTTP_ATTEMPTS,
            "configuredWeightHardCeiling": EXPECTED_TOTAL_HTTP_ATTEMPTS,
            "providerRetryLimit": 0,
            "historyWindowCalendarDays": HISTORY_WINDOW_CALENDAR_DAYS,
            "minimumParsedCompletedSessionsPerSymbol": (
                MOMENTUM_12_1_REQUIRED_SESSIONS
            ),
        },
        "evidenceContract": {
            "captureVersion": FUTURE_PRICE_HISTORY_CAPTURE_VERSION,
            "coverageVersion": FUTURE_PRICE_HISTORY_COVERAGE_VERSION,
            "futurePriceEvidenceVersion": FUTURE_PRICE_EVIDENCE_VERSION,
            "rawTransportVersion": RAW_HTTP_CAPTURE_VERSION,
            "rawTransportHashSemantics": "EXACT_HTTP_RESPONSE_BODY_BYTES",
            "normalizationVersion": YAHOO_CHART_NORMALIZATION_VERSION,
            "adjustmentMode": "TOTAL_RETURN_ADJUSTED",
            "actionAdjustmentBindingVersion": (
                ACTION_ADJUSTMENT_BINDING_VERSION
            ),
            "providerRevisionStatus": "AS_OBSERVED_AT_CAPTURE",
            "adtvPolicyVersion": ADTV_POLICY_VERSION,
            "adtvCompletedSessions": ADTV_WINDOW_SESSIONS,
            "rawAndAdjustedBarsRequired": True,
            "corporateActionsRequired": True,
            "actionAdjustmentBindingRequired": True,
            "adtvEvidenceRequired": True,
        },
        "executionSafety": {
            "leaseRequired": True,
            "heartbeatLeasePath": (
                "storage/future-price-history-capture-v2/"
                ".future-price-history-v2.lock"
            ),
            "physicalRequestJournalRequired": True,
            "requestStateSequence": ["INTENT", "COMPLETED_OR_FAILED"],
            "checkpointRequiredForCompletedReplay": True,
            "unknownStatePolicy": "STOP_NO_AUTOMATIC_RETRY",
            "explicitResumeRequired": True,
            "completedReplayPhysicalRequests": 0,
            "providerRetryLimit": 0,
            "databaseWriteDefault": False,
        },
        "currentControlledStateAudit": storage_audit,
        "liveConfirmation": {
            "tokenSha256": _sha256_text(LIVE_CONFIRMATION),
            "namedReviewerRequired": True,
            "nyseScheduledSessionConfirmationRequired": True,
            "nyseCloseConfirmationRequired": True,
            "nasdaqScheduledSessionConfirmationRequired": True,
            "nasdaqCloseConfirmationRequired": True,
            "singleExecutionOnly": True,
        },
        "onlyApprovedPostCloseCommand": command_body,
        "stopConditions": [
            "TARGET_SESSION_NOT_COMPLETED",
            "NYSE_OR_NASDAQ_CALENDAR_REVIEW_NEGATIVE_OR_MISSING",
            "PREEXISTING_OR_CONFLICTING_LEASE",
            "PHYSICAL_REQUEST_STATE_UNKNOWN",
            "CHECKPOINT_OR_JOURNAL_HASH_MISMATCH",
            "V2_2_PREREGISTRATION_OR_UNIVERSE_OR_SOURCE_HASH_CHANGED",
            "REQUEST_COUNT_OR_WEIGHT_ABOVE_69",
            "HTTP_AUTH_LIMIT_TRANSPORT_FORMAT_OR_SEMANTIC_ANOMALY",
            "TARGET_COMPLETED_SESSION_BAR_MISSING",
            "PARSED_COMPLETED_SESSIONS_BELOW_253",
            "ADJUSTED_RAW_ACTION_OR_ADTV_EVIDENCE_MISSING",
            "IMMUTABLE_ARTIFACT_CONFLICT",
        ],
        "sourceBindings": {
            "historyPreflight": _artifact_binding(
                history_preflight_path,
                history_preflight,
                repository_root,
                hash_field="artifactContentHash",
            ),
            "finalSuccessorReadinessCloseoutV2": _artifact_binding(
                final_readiness_path,
                final_readiness,
                repository_root,
                hash_field="artifactContentHash",
            ),
            "v18Acceptance": _artifact_binding(
                v18_acceptance_path,
                v18_acceptance,
                repository_root,
                hash_field="artifactContentHash",
            ),
            "v22PreregistrationSeal": _artifact_binding(
                seal_path,
                seal,
                repository_root,
                hash_field="sealContentHash",
            ),
            "externalReferenceUniverse": _artifact_binding(
                external_reference_path,
                external_reference,
                repository_root,
                hash_field="artifactContentHash",
            ),
            "closedTestUniverse": {
                "path": _UNIVERSE_PATH,
                "fileSha256": _file_sha256(universe_path),
                "contentHash": canonical_hash(universe),
                "universeVersion": universe["universeVersion"],
                "sourceFixtureSha256": universe["sourceFixtureSha256"],
            },
            "runnerSource": _source_binding(repository_root / _RUNNER_PATH),
            "cliSource": _source_binding(repository_root / _CLI_PATH),
            "coverageSource": _source_binding(repository_root / _COVERAGE_PATH),
            "evidenceContractsSource": _source_binding(
                repository_root / _CONTRACTS_PATH
            ),
        },
        "executionBoundary": {
            "networkRequestsExecuted": 0,
            "providerRequestsExecuted": 0,
            "databaseReadsExecuted": 0,
            "databaseWritesExecuted": 0,
            "scoresOrRanksComputed": False,
            "enrollmentExecuted": False,
            "outcomesComputed": False,
            "aiUsedForDeterministicFields": False,
            "automaticTradingAuthorized": False,
            "commitCreated": False,
            "pushExecuted": False,
            "deploymentExecuted": False,
            "rawProviderValuesIncluded": False,
        },
    }
    return {**body, "artifactContentHash": canonical_hash(body)}


def write_immutable_final_preexecution_preflight(
    path: Path,
    artifact: dict[str, Any],
) -> str:
    _verify_canonical_payload(artifact, hash_field="artifactContentHash")
    round_trip = json.loads(
        json.dumps(artifact, sort_keys=True, ensure_ascii=True)
    )
    _verify_canonical_payload(round_trip, hash_field="artifactContentHash")
    encoded = (
        json.dumps(round_trip, indent=2, sort_keys=True, ensure_ascii=True)
        + "\n"
    ).encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != encoded:
            raise FinalPreexecutionPreflightError(
                "IMMUTABLE_FINAL_PREEXECUTION_PREFLIGHT_CONFLICT"
            )
    else:
        with path.open("xb") as handle:
            handle.write(encoded)
    persisted = json.loads(path.read_text(encoding="utf-8"))
    _verify_canonical_payload(persisted, hash_field="artifactContentHash")
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _verify_source_contracts(
    *,
    history_preflight: dict[str, Any],
    plan: Any,
    final_readiness: dict[str, Any],
    v18_acceptance: dict[str, Any],
    v18_hash: str,
    seal: dict[str, Any],
    external_reference: dict[str, Any],
    universe: dict[str, Any],
    universe_path: Path,
) -> None:
    if (
        len(plan.ordered_symbols) != EXPECTED_PRICE_SYMBOLS
        or len(plan.requests) != EXPECTED_TOTAL_HTTP_ATTEMPTS
        or sum(item.configured_weight for item in plan.requests)
        != EXPECTED_TOTAL_HTTP_ATTEMPTS
        or history_preflight.get("endpointCounts")
        != {
            "OFFICIAL_NASDAQ_CALENDAR": 1,
            "OFFICIAL_NYSE_CALENDAR": 1,
            "YAHOO_CHART_JSON": EXPECTED_PRICE_SYMBOLS,
        }
        or history_preflight.get("providerRetryLimit") != 0
        or history_preflight.get("historyWindowCalendarDays")
        != HISTORY_WINDOW_CALENDAR_DAYS
        or history_preflight.get("minimumParsedCompletedSessionsPerSymbol")
        != MOMENTUM_12_1_REQUIRED_SESSIONS
    ):
        raise FinalPreexecutionPreflightError(
            "FROZEN_67_PLUS_2_CAPTURE_PLAN_CHANGED"
        )
    if (
        final_readiness.get("schemaVersion")
        != FINAL_READINESS_CLOSEOUT_VERSION
        or final_readiness.get("status") != "BLOCKED"
        or tuple(final_readiness.get("blockedReasons") or ())
        != EXPECTED_SUCCESSOR_BLOCKERS
        or final_readiness.get("executionBoundary", {}).get(
            "providerNetworkRequests"
        )
        != 0
        or final_readiness.get("executionBoundary", {}).get("databaseWrites")
        != 0
        or final_readiness.get("executionBoundary", {}).get(
            "enrollmentExecuted"
        )
        is not False
    ):
        raise FinalPreexecutionPreflightError(
            "FINAL_SUCCESSOR_READINESS_V2_STATE_CHANGED"
        )
    readiness_v18 = final_readiness.get("sourceBindings", {}).get(
        "v18Acceptance",
        {},
    )
    if (
        v18_hash != FINAL_V18_ACCEPTANCE_HASH
        or v18_acceptance.get("status") != "READY"
        or v18_acceptance.get("enrollmentStatus") != "NOT_EXECUTED"
        or readiness_v18.get("artifactContentHash") != v18_hash
    ):
        raise FinalPreexecutionPreflightError(
            "FINAL_V18_ACCEPTANCE_BINDING_CHANGED"
        )
    universe_sha = _file_sha256(universe_path).removeprefix("sha256:").upper()
    if (
        universe.get("universeVersion") != plan.universe_version
        or universe_sha != plan.universe_file_sha256
        or history_preflight.get("universeFileSha256") != universe_sha
    ):
        raise FinalPreexecutionPreflightError("FROZEN_UNIVERSE_HASH_CHANGED")
    if (
        seal.get("sealContentHash") != plan.preregistration_seal_hash
        or external_reference.get("artifactContentHash")
        != plan.external_reference_universe_hash
        or history_preflight.get("externalReferenceRowsHash")
        != plan.external_reference_rows_hash
    ):
        raise FinalPreexecutionPreflightError(
            "V2_2_SEAL_OR_EXTERNAL_REFERENCE_HASH_CHANGED"
        )


def _capture_storage_audit(repository_root: Path) -> dict[str, Any]:
    storage_root = repository_root / DEFAULT_STORAGE_ROOT.relative_to(
        DEFAULT_REPOSITORY_ROOT
    )
    lease_path = repository_root / DEFAULT_LEASE_PATH.relative_to(
        DEFAULT_REPOSITORY_ROOT
    )
    journals_root = storage_root / "journals"
    unknown_count = 0
    journal_run_count = 0
    if journals_root.is_dir():
        journal_run_count = sum(path.is_dir() for path in journals_root.iterdir())
        for request_directory in journals_root.glob("*/requests/*/*"):
            if not request_directory.is_dir():
                continue
            events = sorted(request_directory.glob("[0-9]*.json"))
            if not events:
                continue
            last = json.loads(events[-1].read_text(encoding="utf-8"))
            if last.get("state") not in {"COMPLETED", "FAILED"}:
                unknown_count += 1
    return {
        "storageRootExists": storage_root.exists(),
        "leaseExists": lease_path.exists(),
        "journalRunCount": journal_run_count,
        "unknownPhysicalRequestCount": unknown_count,
        "checkpointCount": (
            sum(1 for _ in storage_root.glob("runs/*/checkpoint.json"))
            if storage_root.is_dir()
            else 0
        ),
        "auditPerformedWithoutNetworkOrDatabase": True,
    }


def _verified_artifact(path: Path, *, hash_field: str) -> dict[str, Any]:
    artifact = json.loads(path.read_text(encoding="utf-8"))
    _verify_canonical_payload(artifact, hash_field=hash_field)
    return artifact


def _verify_canonical_payload(
    artifact: dict[str, Any],
    *,
    hash_field: str,
) -> None:
    claim = artifact.get(hash_field)
    if not isinstance(claim, str):
        raise FinalPreexecutionPreflightError(
            f"SOURCE_CANONICAL_HASH_MISSING[{hash_field}]"
        )
    body = dict(artifact)
    body.pop(hash_field)
    if canonical_hash(body) != claim:
        raise FinalPreexecutionPreflightError(
            f"SOURCE_CANONICAL_HASH_MISMATCH[{hash_field}]"
        )


def _artifact_binding(
    path: Path,
    artifact: dict[str, Any],
    repository_root: Path,
    *,
    hash_field: str,
) -> dict[str, str]:
    _verify_canonical_payload(artifact, hash_field=hash_field)
    return {
        "path": path.relative_to(repository_root).as_posix(),
        "fileSha256": _file_sha256(path),
        hash_field: str(artifact[hash_field]),
    }


def _source_binding(path: Path) -> dict[str, str]:
    return {
        "path": path.relative_to(DEFAULT_REPOSITORY_ROOT).as_posix(),
        "fileSha256": _file_sha256(path),
    }


def _file_sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _sha256_text(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()
