from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from equity_analysis.analytics_interface.contracts import canonical_hash
from equity_analysis.forward_validation.benchmark_construction_v22 import (
    BENCHMARK_PREREGISTRATION_V22_HASH,
    CANDIDATE_CONSTRUCTION_V22_HASH,
    EXTERNAL_REFERENCE_UNIVERSE_V22_HASH,
    INPUT_CAPTURE_V22_HASH,
    INPUT_COVERAGE_V22_HASH,
    PARENT_PREREGISTRATION_HASH,
    PREREGISTRATION_SEAL_V22_HASH,
)

PROSPECTIVE_READINESS_CONTROLLER_V22 = (
    "PROSPECTIVE-READINESS-CONTROLLER-v2.2.0"
)
V18_ACCEPTANCE_VERSION = "FORWARD-DQV-V18-ACCEPTANCE-v1.0.0"
LEGACY_SNAPSHOT_ID = "beaa9952-9852-4088-9dc3-92047824414b"
REQUIRED_BENCHMARK_KINDS = frozenset(
    {
        "SPY",
        "SECTOR",
        "EQUAL_WEIGHT",
        "PURE_MOMENTUM",
        "PURE_VALUE",
        "PURE_QUALITY",
    }
)


def _verified(payload: dict[str, Any]) -> str:
    for field in (
        "artifactContentHash",
        "preregistrationContentHash",
        "sealContentHash",
    ):
        claim = payload.get(field)
        if claim is None:
            continue
        body = {key: value for key, value in payload.items() if key != field}
        if canonical_hash(body) != claim:
            raise ValueError("CANONICAL_HASH_MISMATCH")
        return str(claim)
    raise ValueError("CANONICAL_HASH_MISSING")


def _aware(value: Any) -> datetime:
    parsed = datetime.fromisoformat(str(value))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("TIMESTAMP_NOT_AWARE")
    return parsed


def _check_frozen(
    payload: dict[str, Any],
    expected: str,
    reason: str,
    blockers: set[str],
) -> str | None:
    try:
        observed = _verified(payload)
    except (KeyError, TypeError, ValueError):
        blockers.add(f"{reason}_HASH_INVALID")
        return None
    if observed != expected:
        blockers.add(f"{reason}_FROZEN_HASH_MISMATCH")
        return None
    return observed


def evaluate_successor_readiness_v22(
    *,
    parent_preregistration: dict[str, Any],
    benchmark_preregistration: dict[str, Any],
    preregistration_seal: dict[str, Any],
    external_reference_universe: dict[str, Any],
    input_capture: dict[str, Any],
    input_coverage: dict[str, Any],
    candidate_construction: dict[str, Any],
    future_price_execution: dict[str, Any] | None,
    benchmark_manifest: dict[str, Any] | None,
    post_freeze_decision_manifest: dict[str, Any] | None,
    v18_acceptance: dict[str, Any] | None,
) -> dict[str, Any]:
    """Return a read-only readiness result; never enroll, score, call, or write."""

    blockers: set[str] = set()
    parent_hash = _check_frozen(
        parent_preregistration,
        PARENT_PREREGISTRATION_HASH,
        "PARENT_PREREGISTRATION",
        blockers,
    )
    benchmark_prereg_hash = _check_frozen(
        benchmark_preregistration,
        BENCHMARK_PREREGISTRATION_V22_HASH,
        "BENCHMARK_PREREGISTRATION_V22",
        blockers,
    )
    seal_hash = _check_frozen(
        preregistration_seal,
        PREREGISTRATION_SEAL_V22_HASH,
        "PREREGISTRATION_SEAL_V22",
        blockers,
    )
    external_hash = _check_frozen(
        external_reference_universe,
        EXTERNAL_REFERENCE_UNIVERSE_V22_HASH,
        "EXTERNAL_REFERENCE_UNIVERSE_V22",
        blockers,
    )
    capture_hash = _check_frozen(
        input_capture,
        INPUT_CAPTURE_V22_HASH,
        "INPUT_CAPTURE_V22",
        blockers,
    )
    coverage_hash = _check_frozen(
        input_coverage,
        INPUT_COVERAGE_V22_HASH,
        "INPUT_COVERAGE_V22",
        blockers,
    )
    candidate_hash = _check_frozen(
        candidate_construction,
        CANDIDATE_CONSTRUCTION_V22_HASH,
        "CANDIDATE_CONSTRUCTION_V22",
        blockers,
    )
    if (
        parent_hash
        and benchmark_preregistration.get("parentPreregistrationContentHash")
        != parent_hash
    ):
        blockers.add("PREREGISTRATION_HASH_CHAIN_MISMATCH")
    if (
        benchmark_prereg_hash
        and preregistration_seal.get("benchmarkPreregistration", {}).get(
            "artifactContentHash"
        )
        != benchmark_prereg_hash
    ):
        blockers.add("PREREGISTRATION_HASH_CHAIN_MISMATCH")
    if (
        external_hash
        and preregistration_seal.get("externalReferenceUniverse", {}).get(
            "artifactContentHash"
        )
        != external_hash
    ):
        blockers.add("EXTERNAL_REFERENCE_HASH_CHAIN_MISMATCH")
    if (
        input_capture.get("physicalAttempts") != 55
        or input_capture.get("retryCount") != 0
        or input_capture.get("lockReleased") is not True
    ):
        blockers.add("FUNDAMENTALS_CAPTURE_NOT_TERMINAL")
    if (
        input_coverage.get("captureArtifactContentHash") != capture_hash
        or candidate_construction.get("captureArtifactContentHash") != capture_hash
        or candidate_construction.get("coverageArtifactContentHash") != coverage_hash
    ):
        blockers.add("FUNDAMENTALS_ARTIFACT_HASH_CHAIN_MISMATCH")
    for family in ("pureValue", "pureQuality"):
        coverage = input_coverage.get(family) or {}
        construction = candidate_construction.get(family) or {}
        if (
            coverage.get("coverageGatePassed") is not True
            or int(coverage.get("validCount") or 0) < 44
            or int(construction.get("validCandidateCount") or 0) < 44
            or int(construction.get("selectedCount") or 0)
            != len(construction.get("selected") or [])
        ):
            blockers.add(f"{family.upper()}_44_OF_55_GATE_NOT_MET")

    common_session: str | None = None
    price_execution_hash: str | None = None
    if future_price_execution is None:
        blockers.add("COMPLETED_SESSION_PRICE_EVIDENCE_MISSING")
    else:
        try:
            price_execution_hash = _verified(future_price_execution)
        except (KeyError, TypeError, ValueError):
            blockers.add("COMPLETED_SESSION_PRICE_EVIDENCE_HASH_INVALID")
        common_session = future_price_execution.get("targetSession")
        receipts = future_price_execution.get("symbols") or []
        if (
            future_price_execution.get("artifactType")
            != "FUTURE_COMPLETED_SESSION_PRICE_HISTORY_CAPTURE"
            or future_price_execution.get("schemaVersion")
            != "FUTURE-PRICE-HISTORY-CAPTURE-v2.0.0"
            or future_price_execution.get("status") != "READY"
            or future_price_execution.get("providerRetryLimit") != 0
            or future_price_execution.get("preregistrationSealHash") != seal_hash
            or future_price_execution.get("externalReferenceUniverseHash")
            != external_hash
            or future_price_execution.get("priceSymbolCount") != 67
            or future_price_execution.get("readySymbolCount") != 67
            or len(receipts) != 67
            or len({str(row.get("symbol")) for row in receipts}) != 67
        ):
            blockers.add("COMPLETED_SESSION_PRICE_EVIDENCE_INCOMPLETE")

    benchmark_hash: str | None = None
    observed_kinds: set[str] = set()
    if benchmark_manifest is None:
        blockers.add("SIX_BENCHMARK_CONSTRUCTION_MISSING")
    else:
        try:
            benchmark_hash = _verified(benchmark_manifest)
        except (KeyError, TypeError, ValueError):
            blockers.add("SIX_BENCHMARK_CONSTRUCTION_HASH_INVALID")
        families = benchmark_manifest.get("families") or []
        observed_kinds = {str(item.get("kind")) for item in families}
        available = {
            str(item.get("kind"))
            for item in families
            if item.get("state") == "AVAILABLE"
        }
        if (
            benchmark_manifest.get("schemaVersion")
            != "FORWARD-BENCHMARK-MANIFEST-v2.2.0"
            or benchmark_manifest.get("status") != "READY"
            or benchmark_manifest.get("allSixAvailable") is not True
            or observed_kinds != REQUIRED_BENCHMARK_KINDS
            or available != REQUIRED_BENCHMARK_KINDS
            or benchmark_manifest.get("preregistrationSealHash") != seal_hash
            or benchmark_manifest.get("futurePriceExecutionHash")
            != price_execution_hash
            or benchmark_manifest.get("inputCaptureHash") != capture_hash
            or benchmark_manifest.get("inputCoverageHash") != coverage_hash
            or benchmark_manifest.get("candidateConstructionHash") != candidate_hash
            or (common_session and benchmark_manifest.get("completedSession") != common_session)
        ):
            blockers.add("SIX_BENCHMARK_CONSTRUCTION_INCOMPLETE")

    decision_hash: str | None = None
    if post_freeze_decision_manifest is None:
        blockers.add("POST_FREEZE_DECISION_MANIFEST_MISSING")
    else:
        try:
            decision_hash = _verified(post_freeze_decision_manifest)
            decision_as_of = _aware(post_freeze_decision_manifest.get("decisionAsOf"))
            freeze_boundary = _aware(
                preregistration_seal.get("futureDecisionMustBeStrictlyAfter")
            )
        except (KeyError, TypeError, ValueError):
            blockers.add("POST_FREEZE_DECISION_MANIFEST_HASH_OR_TIME_INVALID")
            decision_as_of = None
            freeze_boundary = None
        rows = post_freeze_decision_manifest.get("decisions") or []
        expected_ids = {
            str(item.get("publicSecurityId"))
            for item in parent_preregistration.get("prospectiveUniverse", {}).get(
                "securities"
            )
            or []
        }
        observed_ids = {
            str(item.get("publicSecurityId") or item.get("securityId"))
            for item in rows
        }
        if post_freeze_decision_manifest.get("dataSnapshotId") == LEGACY_SNAPSHOT_ID:
            blockers.add("LEGACY_PRE_PREREG_DECISION_UPGRADE_FORBIDDEN")
        if decision_as_of is not None and freeze_boundary is not None:
            if decision_as_of <= freeze_boundary:
                blockers.add("DECISION_NOT_STRICTLY_POST_FREEZE")
        if (
            post_freeze_decision_manifest.get("schemaVersion")
            != "FORWARD-DECISION-SNAPSHOT-v2.2.0"
            or post_freeze_decision_manifest.get("prospectiveReady") is not True
            or len(rows) != 66
            or len(observed_ids) != 66
            or observed_ids != expected_ids
            or post_freeze_decision_manifest.get("futurePriceExecutionHash")
            != price_execution_hash
            or post_freeze_decision_manifest.get("benchmarkManifestHash")
            != benchmark_hash
            or (common_session and post_freeze_decision_manifest.get("completedSession")
                != common_session)
            or post_freeze_decision_manifest.get("aiUsedForDeterministicFields")
            is not False
            or post_freeze_decision_manifest.get(
                "aiUsedForDeterministicDecisions"
            )
            is not False
        ):
            blockers.add("POST_FREEZE_DECISION_MANIFEST_INCOMPLETE")

    v18_hash: str | None = None
    if v18_acceptance is None:
        blockers.add("V18_ACCEPTANCE_EVIDENCE_MISSING")
    else:
        try:
            v18_hash = _verified(v18_acceptance)
        except (KeyError, TypeError, ValueError):
            blockers.add("V18_ACCEPTANCE_EVIDENCE_HASH_INVALID")
        if (
            v18_acceptance.get("schemaVersion") != V18_ACCEPTANCE_VERSION
            or v18_acceptance.get("status") != "READY"
            or v18_acceptance.get("migrationVersion") != 18
            or v18_acceptance.get("migrationApplied") is not True
            or v18_acceptance.get("appendOnlyValidated") is not True
            or v18_acceptance.get("fiveHorizonCompletenessValidated") is not True
            or v18_acceptance.get("sixBenchmarkCompletenessValidated") is not True
            or not v18_acceptance.get("migrationFileSha256")
            or not v18_acceptance.get("repositoryContractHash")
        ):
            blockers.add("V18_ACCEPTANCE_EVIDENCE_INCOMPLETE")

    status = "READY" if not blockers else "BLOCKED"
    body = {
        "artifactType": "FORWARD_V2_2_SUCCESSOR_PROSPECTIVE_READINESS",
        "schemaVersion": PROSPECTIVE_READINESS_CONTROLLER_V22,
        "status": status,
        "blockedReasons": sorted(blockers),
        "parentPreregistrationHash": parent_hash,
        "benchmarkPreregistrationHash": benchmark_prereg_hash,
        "preregistrationSealHash": seal_hash,
        "externalReferenceUniverseHash": external_hash,
        "inputCaptureHash": capture_hash,
        "inputCoverageHash": coverage_hash,
        "candidateConstructionHash": candidate_hash,
        "futurePriceExecutionHash": price_execution_hash,
        "benchmarkManifestHash": benchmark_hash,
        "postFreezeDecisionManifestHash": decision_hash,
        "v18AcceptanceHash": v18_hash,
        "commonCompletedSession": common_session,
        "benchmarkKindsObserved": sorted(observed_kinds),
        "providerNetworkRequestsExecuted": 0,
        "databaseReadsExecuted": 0,
        "databaseWritesExecuted": 0,
        "enrollmentExecuted": False,
        "scoresOrRanksComputed": False,
        "outcomesComputed": False,
        "aiUsedForDeterministicFields": False,
        "automaticTradingAuthorized": False,
        "rawProviderValuesIncluded": False,
    }
    return {**body, "artifactContentHash": canonical_hash(body)}


def write_immutable_readiness(path: Path, artifact: dict[str, Any]) -> str:
    encoded = (json.dumps(artifact, indent=2, ensure_ascii=False) + "\n").encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != encoded:
            raise RuntimeError("IMMUTABLE_READINESS_CONFLICT")
    else:
        with path.open("xb") as handle:
            handle.write(encoded)
    return hashlib.sha256(encoded).hexdigest().upper()
