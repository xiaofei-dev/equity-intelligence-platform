from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from equity_analysis.analytics_interface.contracts import canonical_hash

PROSPECTIVE_READINESS_CONTROLLER_V1 = "PROSPECTIVE-READINESS-AND-ENROLLMENT-CONTROLLER-v1.0.0"
LEGACY_SNAPSHOT_ID = "beaa9952-9852-4088-9dc3-92047824414b"
REQUIRED_BENCHMARKS = frozenset(
    {
        "SPY",
        "SECTOR",
        "EQUAL_WEIGHT",
        "PURE_MOMENTUM",
        "PURE_VALUE",
        "PURE_QUALITY",
    }
)


class ProspectiveReadinessError(RuntimeError):
    pass


def _verified(payload: dict[str, Any], label: str) -> str:
    for field in (
        "artifactContentHash",
        "manifestContentHash",
        "sealContentHash",
        "preregistrationContentHash",
    ):
        if field in payload:
            claim = payload[field]
            body = {key: value for key, value in payload.items() if key != field}
            if canonical_hash(body) != claim:
                raise ProspectiveReadinessError(f"{label}_CANONICAL_HASH_MISMATCH")
            return str(claim)
    raise ProspectiveReadinessError(f"{label}_CANONICAL_HASH_MISSING")


def _timestamp(payload: dict[str, Any], key: str) -> datetime | None:
    value = payload.get(key)
    if value is None:
        return None
    parsed = datetime.fromisoformat(str(value))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ProspectiveReadinessError(f"{key}_NOT_TIMEZONE_AWARE")
    return parsed


def _families(payload: dict[str, Any]) -> list[dict[str, Any]]:
    values = payload.get("families")
    if values is None:
        values = payload.get("benchmarkFamilies")
    return list(values or [])


def evaluate_prospective_readiness(
    *,
    parent_preregistration: dict[str, Any],
    benchmark_preregistration: dict[str, Any],
    preregistration_seal: dict[str, Any],
    decision_manifest: dict[str, Any] | None,
    future_price_execution: dict[str, Any] | None,
    benchmark_manifest: dict[str, Any] | None,
    benchmark_bundle: dict[str, Any] | None,
    objective_coverage_audit: dict[str, Any] | None,
) -> dict[str, Any]:
    """Evaluate readiness only; this function cannot enroll or mutate evidence."""

    blockers: set[str] = set()
    parent_hash = _verified(parent_preregistration, "PARENT_PREREGISTRATION")
    benchmark_prereg_hash = _verified(
        benchmark_preregistration,
        "BENCHMARK_PREREGISTRATION",
    )
    seal_hash = _verified(preregistration_seal, "PREREGISTRATION_SEAL")
    if (
        benchmark_preregistration.get("parentPreregistrationContentHash") != parent_hash
        or preregistration_seal.get("parentPreregistration", {}).get("artifactContentHash")
        != parent_hash
        or preregistration_seal.get("benchmarkPreregistration", {}).get("artifactContentHash")
        != benchmark_prereg_hash
    ):
        blockers.add("PREREGISTRATION_HASH_CHAIN_MISMATCH")
    cutoff = _timestamp(
        preregistration_seal,
        "futureDecisionMustBeStrictlyAfter",
    )
    if cutoff is None:
        blockers.add("PREREGISTRATION_CUTOFF_MISSING")
    prospective = parent_preregistration.get("prospectiveUniverse", {})
    securities = prospective.get("securities") or []
    roles = [str(item.get("role")) for item in securities]
    stable_ids = [str(item.get("publicSecurityId") or "") for item in securities]
    if (
        len(securities) != 66
        or len(set(stable_ids)) != 66
        or any(not value for value in stable_ids)
    ):
        blockers.add("STABLE_66_IDENTITY_COVERAGE_INCOMPLETE")
    refreshable_count = sum(role != "EXCLUDED" for role in roles)
    if refreshable_count != 57:
        blockers.add("REFRESHABLE_57_COVERAGE_INCOMPLETE")
    reference_symbols = {
        str(item.get("symbol")) for item in securities if item.get("role") == "REFERENCE_ONLY"
    }
    if "SPY" not in reference_symbols:
        blockers.add("SPY_REFERENCE_IDENTITY_MISSING")

    execution_hash = None
    common_session = None
    if future_price_execution is None:
        blockers.update(
            {
                "COMPLETED_SESSION_DUAL_CALENDAR_EVIDENCE_MISSING",
                "RAW_TRANSPORT_BINDING_MISSING",
                "ACTION_ADJUSTMENT_RECONCILIATION_MISSING",
                "PRICE_PROMOTION_DECISIONS_MISSING",
                "DECISION_TIME_ADTV_EVIDENCE_MISSING",
            }
        )
    else:
        execution_hash = _verified(
            future_price_execution,
            "FUTURE_PRICE_EXECUTION",
        )
        artifact_type = str(future_price_execution.get("artifactType") or "")
        if (
            "PREFLIGHT" in artifact_type
            or future_price_execution.get("providerNetworkRequestsExecuted") == 0
        ):
            blockers.add("EXECUTION_EVIDENCE_PREFLIGHT_ONLY")
        if future_price_execution.get("status") != "COMPLETE":
            blockers.add("FUTURE_PRICE_EXECUTION_NOT_COMPLETE")
        common_session = future_price_execution.get("targetSession")
        calendar = future_price_execution.get("completedSessionEvidence") or {}
        if not (
            calendar.get("status") == "READY"
            and calendar.get("nyseBodyHash")
            and calendar.get("nasdaqBodyHash")
            and calendar.get("reviewedBy")
            and calendar.get("evidenceHash")
        ):
            blockers.add("COMPLETED_SESSION_DUAL_CALENDAR_EVIDENCE_MISSING")
        raw = future_price_execution.get("rawTransport") or {}
        if not (
            raw.get("status") == "COMPLETE"
            and raw.get("symbolCount") == 57
            and raw.get("unknownRequestCount") == 0
            and raw.get("hashSemantics") == "EXACT_HTTP_RESPONSE_BODY_BYTES"
            and raw.get("envelopeHashCount") == 57
        ):
            blockers.add("RAW_TRANSPORT_BINDING_INCOMPLETE")
        if int(raw.get("unknownRequestCount") or 0) > 0:
            blockers.add("PHYSICAL_REQUEST_STATE_UNKNOWN")
        actions = future_price_execution.get("actionAdjustment") or {}
        if not (
            actions.get("status") == "RECONCILED"
            and actions.get("reconciledCount") == 57
            and actions.get("commonSession") == common_session
        ):
            blockers.add("ACTION_ADJUSTMENT_RECONCILIATION_INCOMPLETE")
        promotion = future_price_execution.get("pricePromotion") or {}
        stale = set(promotion.get("staleSymbols") or ())
        if "ACN" in stale:
            blockers.add("ACN_PRICE_EVIDENCE_STALE")
        if not (
            promotion.get("status") == "COMPLETE"
            and promotion.get("promotedCount") == 57
            and not stale
            and promotion.get("commonSession") == common_session
        ):
            blockers.add("PRICE_PROMOTION_DECISIONS_INCOMPLETE")
        adtv = future_price_execution.get("adtv") or {}
        if not (
            adtv.get("status") == "COMPLETE"
            and adtv.get("validatedCount") == 57
            and adtv.get("completedSessionCount") == 20
            and adtv.get("commonSession") == common_session
        ):
            blockers.add("DECISION_TIME_ADTV_EVIDENCE_INCOMPLETE")
        if any(
            value is not None and value != common_session
            for value in (
                calendar.get("targetSession"),
                actions.get("commonSession"),
                promotion.get("commonSession"),
                adtv.get("commonSession"),
            )
        ):
            blockers.add("COMMON_COMPLETED_SESSION_MISMATCH")

    decision_hash = None
    if decision_manifest is None:
        blockers.add("READY_IMMUTABLE_DECISION_MANIFEST_MISSING")
    else:
        decision_hash = _verified(decision_manifest, "DECISION_MANIFEST")
        decision_as_of = _timestamp(decision_manifest, "decisionAsOf")
        if decision_manifest.get("dataSnapshotId") == LEGACY_SNAPSHOT_ID:
            blockers.add("LEGACY_PRE_PREREG_DECISION_UPGRADE_FORBIDDEN")
        if cutoff and (decision_as_of is None or decision_as_of <= cutoff):
            blockers.add("DECISION_NOT_STRICTLY_POST_PREREGISTRATION")
        if decision_manifest.get("prospectiveReady") is not True:
            blockers.add("DECISION_MANIFEST_NOT_READY")
        rows = decision_manifest.get("decisions") or []
        public_ids = [
            str(row.get("publicSecurityId") or row.get("securityId") or "") for row in rows
        ]
        if len(rows) != 66 or len(set(public_ids)) != 66 or any(not value for value in public_ids):
            blockers.add("DECISION_STABLE_66_COVERAGE_INCOMPLETE")
        decision_session = decision_manifest.get("completedSession") or (
            decision_manifest.get("decisionSession")
        )
        if common_session and decision_session != common_session:
            blockers.add("COMMON_COMPLETED_SESSION_MISMATCH")
        if decision_manifest.get("aiUsedForDeterministicFields") not in (
            False,
            None,
        ) or decision_manifest.get("aiUsedForDeterministicDecisions") not in (
            False,
            None,
        ):
            blockers.add("AI_AFFECTED_DETERMINISTIC_FIELDS")

    benchmark_manifest_hash = None
    benchmark_bundle_hash = None
    benchmark_families: list[dict[str, Any]] = []
    if benchmark_manifest is None or benchmark_bundle is None:
        blockers.add("SIX_BENCHMARK_V2_1_EVIDENCE_MISSING")
    else:
        benchmark_manifest_hash = _verified(
            benchmark_manifest,
            "BENCHMARK_MANIFEST",
        )
        benchmark_bundle_hash = _verified(
            benchmark_bundle,
            "BENCHMARK_BUNDLE",
        )
        benchmark_families = _families(benchmark_manifest)
        bundle_families = _families(benchmark_bundle)
        kinds = {str(item.get("kind")) for item in benchmark_families}
        available = {
            str(item.get("kind"))
            for item in benchmark_families
            if (item.get("availability") or item.get("state")) == "AVAILABLE"
        }
        if kinds != REQUIRED_BENCHMARKS or available != REQUIRED_BENCHMARKS:
            blockers.add("SIX_BENCHMARK_V2_1_NOT_ALL_AVAILABLE")
        if canonical_hash(benchmark_families) != canonical_hash(bundle_families):
            blockers.add("BENCHMARK_MANIFEST_BUNDLE_MISMATCH")
        if benchmark_manifest.get("controlledBundleHash") not in (
            benchmark_bundle_hash,
            benchmark_bundle.get("bundleContentHash"),
        ):
            blockers.add("BENCHMARK_MANIFEST_BUNDLE_HASH_MISMATCH")
        sector = benchmark_manifest.get("sectorCoverage") or {}
        sector_benchmark_symbols = set(sector.get("benchmarkSymbols") or ())
        if not (
            sector.get("status") == "COMPLETE"
            and int(sector.get("includedSectorCount") or 0) > 1
            and sector.get("mappedSectorCount") == sector.get("includedSectorCount")
            and sector.get("referenceOnlyBenchmarkCount") == sector.get("includedSectorCount")
            and sector_benchmark_symbols
            and sector_benchmark_symbols.issubset(reference_symbols)
            and len(sector_benchmark_symbols) == sector.get("includedSectorCount")
        ):
            blockers.add("SECTOR_BENCHMARK_MAPPING_INCOMPLETE")
        if common_session and benchmark_manifest.get("completedSession") != common_session:
            blockers.add("COMMON_COMPLETED_SESSION_MISMATCH")

    objective_hash = None
    if objective_coverage_audit is None:
        blockers.add("OBJECTIVE_COVERAGE_AUDIT_MISSING")
    else:
        objective_hash = _verified(
            objective_coverage_audit,
            "OBJECTIVE_COVERAGE_AUDIT",
        )
        value = objective_coverage_audit.get("pureValue") or {}
        quality = objective_coverage_audit.get("pureQuality") or {}
        for label, evidence in (("PURE_VALUE", value), ("PURE_QUALITY", quality)):
            if not (
                evidence.get("status") == "ACCEPTED"
                and int(evidence.get("eligibleCount") or 0) >= 20
                and float(evidence.get("coverageRatio") or 0) >= 0.80
                and evidence.get("evidenceHash")
            ):
                blockers.add(f"{label}_OBJECTIVE_COVERAGE_INSUFFICIENT")
        if common_session and objective_coverage_audit.get("completedSession") != common_session:
            blockers.add("COMMON_COMPLETED_SESSION_MISMATCH")

    if preregistration_seal.get("prospectiveUniverseVersion") != prospective.get("universeVersion"):
        blockers.add("UNIVERSE_VERSION_HASH_CHAIN_MISMATCH")
    status = "READY" if not blockers else "BLOCKED"
    body = {
        "artifactType": "PROSPECTIVE_READINESS_AND_ENROLLMENT_CONTROLLER",
        "schemaVersion": PROSPECTIVE_READINESS_CONTROLLER_V1,
        "status": status,
        "blockedReasons": sorted(blockers),
        "parentPreregistrationHash": parent_hash,
        "benchmarkPreregistrationHash": benchmark_prereg_hash,
        "preregistrationSealHash": seal_hash,
        "decisionManifestHash": decision_hash,
        "futurePriceExecutionHash": execution_hash,
        "benchmarkManifestHash": benchmark_manifest_hash,
        "benchmarkBundleHash": benchmark_bundle_hash,
        "objectiveCoverageAuditHash": objective_hash,
        "commonCompletedSession": common_session,
        "stableSecurityCount": len(set(stable_ids)),
        "refreshableSecurityCount": refreshable_count,
        "referenceOnlySymbols": sorted(reference_symbols),
        "benchmarkKindsObserved": sorted({str(item.get("kind")) for item in benchmark_families}),
        "aiUsedForDeterministicFields": False,
        "providerNetworkRequestsExecuted": 0,
        "databaseWritesExecuted": 0,
        "enrollmentExecuted": False,
        "scoresOrRanksComputed": False,
        "automaticTradingAuthorized": False,
        "rawProviderValuesIncluded": False,
    }
    return {**body, "artifactContentHash": canonical_hash(body)}


def load_verified_artifact(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    _verified(payload, path.stem.upper())
    return payload


def file_binding(path: Path) -> dict[str, Any]:
    payload = load_verified_artifact(path)
    return {
        "path": path.as_posix(),
        "fileSha256": hashlib.sha256(path.read_bytes()).hexdigest().upper(),
        "contentHash": next(
            payload[field]
            for field in (
                "artifactContentHash",
                "manifestContentHash",
                "sealContentHash",
                "preregistrationContentHash",
            )
            if field in payload
        ),
    }


def write_immutable_readiness(path: Path, artifact: dict[str, Any]) -> str:
    encoded = (json.dumps(artifact, indent=2, ensure_ascii=False) + "\n").encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != encoded:
            raise ProspectiveReadinessError("IMMUTABLE_READINESS_CONFLICT")
    else:
        with path.open("xb") as handle:
            handle.write(encoded)
    return hashlib.sha256(encoded).hexdigest().upper()
