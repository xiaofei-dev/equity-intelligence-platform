from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

from equity_analysis.analytics_interface.contracts import canonical_hash
from equity_analysis.forward_validation.prospective_readiness_controller_v1 import (
    evaluate_prospective_readiness,
)

ROOT = Path(__file__).resolve().parents[2]


def _load(path: str) -> dict:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def _rehash(payload: dict, field: str) -> dict:
    value = deepcopy(payload)
    value.pop(field, None)
    value[field] = canonical_hash(value)
    return value


def _inputs() -> dict:
    benchmark = _load("docs/generated/forward-benchmark-db-readiness-v2-1-beaa9952.json")
    return {
        "parent_preregistration": _load("docs/generated/forward-dqv-preregistration-v2.json"),
        "benchmark_preregistration": _load(
            "docs/generated/forward-benchmark-preregistration-v2-1.json"
        ),
        "preregistration_seal": _load("docs/generated/forward-preregistration-seal-v2-1.json"),
        "decision_manifest": _load(
            "docs/generated/forward-v2-decision-snapshot-20260729T025708Z-beaa9952.json"
        ),
        "future_price_execution": _load(
            "docs/generated/future-completed-session-price-evidence-preflight-v1.json"
        ),
        "benchmark_manifest": benchmark,
        "benchmark_bundle": benchmark,
        "objective_coverage_audit": None,
    }


def _execution(*, unknown: int = 0, stale=(), action_session="2026-07-30") -> dict:
    body = {
        "artifactType": "FUTURE_COMPLETED_SESSION_PRICE_EVIDENCE_EXECUTION",
        "status": "COMPLETE",
        "targetSession": "2026-07-30",
        "providerNetworkRequestsExecuted": 59,
        "completedSessionEvidence": {
            "status": "READY",
            "targetSession": "2026-07-30",
            "nyseBodyHash": "sha256:" + "1" * 64,
            "nasdaqBodyHash": "sha256:" + "2" * 64,
            "reviewedBy": "reviewer",
            "evidenceHash": "sha256:" + "3" * 64,
        },
        "rawTransport": {
            "status": "COMPLETE",
            "symbolCount": 57,
            "unknownRequestCount": unknown,
            "hashSemantics": "EXACT_HTTP_RESPONSE_BODY_BYTES",
            "envelopeHashCount": 57,
        },
        "actionAdjustment": {
            "status": "RECONCILED",
            "reconciledCount": 57,
            "commonSession": action_session,
        },
        "pricePromotion": {
            "status": "COMPLETE",
            "promotedCount": 57,
            "staleSymbols": list(stale),
            "commonSession": "2026-07-30",
        },
        "adtv": {
            "status": "COMPLETE",
            "validatedCount": 57,
            "completedSessionCount": 20,
            "commonSession": "2026-07-30",
        },
    }
    return {**body, "artifactContentHash": canonical_hash(body)}


def _objective(count: int = 20, ratio: float = 0.80) -> dict:
    body = {
        "artifactType": "OBJECTIVE_COVERAGE_AUDIT",
        "completedSession": "2026-07-30",
        "pureValue": {
            "status": "ACCEPTED",
            "eligibleCount": count,
            "coverageRatio": ratio,
            "evidenceHash": "sha256:" + "4" * 64,
        },
        "pureQuality": {
            "status": "ACCEPTED",
            "eligibleCount": count,
            "coverageRatio": ratio,
            "evidenceHash": "sha256:" + "5" * 64,
        },
    }
    return {**body, "artifactContentHash": canonical_hash(body)}


def test_current_repository_state_is_deterministically_blocked() -> None:
    result = evaluate_prospective_readiness(**_inputs())

    assert result["status"] == "BLOCKED"
    assert "LEGACY_PRE_PREREG_DECISION_UPGRADE_FORBIDDEN" in result["blockedReasons"]
    assert "EXECUTION_EVIDENCE_PREFLIGHT_ONLY" in result["blockedReasons"]
    assert "SIX_BENCHMARK_V2_1_NOT_ALL_AVAILABLE" in result["blockedReasons"]
    assert "SECTOR_BENCHMARK_MAPPING_INCOMPLETE" in result["blockedReasons"]
    assert "OBJECTIVE_COVERAGE_AUDIT_MISSING" in result["blockedReasons"]
    assert result["enrollmentExecuted"] is False
    assert result["providerNetworkRequestsExecuted"] == 0
    assert result["databaseWritesExecuted"] == 0
    assert result["artifactContentHash"] == canonical_hash(
        {key: value for key, value in result.items() if key != "artifactContentHash"}
    )


def test_preflight_can_never_substitute_for_execution_evidence() -> None:
    inputs = _inputs()
    result = evaluate_prospective_readiness(**inputs)

    assert "EXECUTION_EVIDENCE_PREFLIGHT_ONLY" in result["blockedReasons"]
    assert "FUTURE_PRICE_EXECUTION_NOT_COMPLETE" in result["blockedReasons"]
    assert "RAW_TRANSPORT_BINDING_INCOMPLETE" in result["blockedReasons"]


def test_unknown_stale_acn_and_common_session_mismatch_are_independent() -> None:
    inputs = _inputs()
    inputs["future_price_execution"] = _execution(
        unknown=1,
        stale=("ACN",),
        action_session="2026-07-29",
    )
    result = evaluate_prospective_readiness(**inputs)

    assert "PHYSICAL_REQUEST_STATE_UNKNOWN" in result["blockedReasons"]
    assert "ACN_PRICE_EVIDENCE_STALE" in result["blockedReasons"]
    assert "COMMON_COMPLETED_SESSION_MISMATCH" in result["blockedReasons"]


def test_partial_benchmark_set_and_sector_mapping_are_rejected() -> None:
    inputs = _inputs()
    benchmark = deepcopy(inputs["benchmark_manifest"])
    benchmark["benchmarkFamilies"][0]["state"] = "AVAILABLE"
    benchmark = _rehash(benchmark, "artifactContentHash")
    inputs["benchmark_manifest"] = benchmark
    inputs["benchmark_bundle"] = benchmark
    result = evaluate_prospective_readiness(**inputs)

    assert "SIX_BENCHMARK_V2_1_NOT_ALL_AVAILABLE" in result["blockedReasons"]
    assert "SECTOR_BENCHMARK_MAPPING_INCOMPLETE" in result["blockedReasons"]


def test_objective_audit_interface_uses_thresholds_without_optimistic_defaults() -> None:
    inputs = _inputs()
    inputs["objective_coverage_audit"] = _objective(count=19, ratio=0.79)
    blocked = evaluate_prospective_readiness(**inputs)

    assert "PURE_VALUE_OBJECTIVE_COVERAGE_INSUFFICIENT" in blocked["blockedReasons"]
    assert "PURE_QUALITY_OBJECTIVE_COVERAGE_INSUFFICIENT" in blocked["blockedReasons"]

    inputs["objective_coverage_audit"] = _objective()
    accepted = evaluate_prospective_readiness(**inputs)
    assert "PURE_VALUE_OBJECTIVE_COVERAGE_INSUFFICIENT" not in accepted["blockedReasons"]
    assert "PURE_QUALITY_OBJECTIVE_COVERAGE_INSUFFICIENT" not in accepted["blockedReasons"]
