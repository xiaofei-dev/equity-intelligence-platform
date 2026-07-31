from __future__ import annotations

import json
from pathlib import Path

from equity_analysis.analytics_interface.contracts import canonical_hash

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
ARTIFACT_PATH = (
    REPOSITORY_ROOT / "docs/generated/end-to-end-validation-completion-gap-audit-v1.json"
)


def _artifact() -> dict:
    return json.loads(ARTIFACT_PATH.read_text(encoding="utf-8"))


def _requirements(artifact: dict) -> dict[str, dict]:
    return {item["id"]: item for item in artifact["requirements"]}


def test_checked_in_gap_audit_v1_remains_canonical_legacy_evidence() -> None:
    artifact = _artifact()
    body = dict(artifact)
    claim = body.pop("artifactContentHash")
    assert canonical_hash(body) == claim


def test_fixture_never_proves_real_execution() -> None:
    artifact = _artifact()
    assert artifact["fixtureMayProveRealExecution"] is False
    requirements = _requirements(artifact)
    for item_id in (
        "POST_CLOSE_COMPLETED_SESSION_CAPTURE",
        "SIX_BENCHMARK_CONSTRUCTION",
        "REAL_POST_FREEZE_MODEL_EXECUTION",
        "REAL_66_PROSPECTIVE_DECISION_SNAPSHOT",
        "REAL_V2_2_PROSPECTIVE_ENROLLMENT",
        "REAL_NATURALLY_MATURED_OUTCOMES",
        "REAL_DQV_STATISTICS_EXECUTION",
        "FINAL_PROSPECTIVE_MODEL_VALIDATION",
    ):
        assert requirements[item_id]["status"] != "IMPLEMENTED_OFFLINE"


def test_every_requirement_uses_the_authoritative_state_taxonomy() -> None:
    allowed = {
        "IMPLEMENTED_OFFLINE",
        "BLOCKED_BY_TIME",
        "BLOCKED_BY_EVIDENCE",
        "NOT_EXECUTED",
        "NOT_VALIDATED",
    }
    assert {item["status"] for item in _artifact()["requirements"]}.issubset(allowed)


def test_chronology_is_accepted_but_output_payload_remains_critical() -> None:
    artifact = _artifact()
    requirements = _requirements(artifact)
    assert artifact["overallStatus"] == "CRITICAL_BLOCKED_NOT_VALIDATED"
    v19_accepted = bool(
        artifact["authoritativeArtifacts"]["v19ChronologyAcceptance"].get("artifactContentHash")
    )
    assert requirements["ENROLLMENT_CHRONOLOGY_LEAKAGE_GUARD"]["status"] == (
        "IMPLEMENTED_OFFLINE" if v19_accepted else "BLOCKED_BY_EVIDENCE"
    )
    assert requirements["V19_V2_1_1_PRODUCTION_REACHABILITY"]["status"] == (
        "IMPLEMENTED_OFFLINE" if v19_accepted else "BLOCKED_BY_EVIDENCE"
    )
    assert requirements["POST_V19_DEPENDENT_ARTIFACT_REGENERATION"]["status"] == (
        "IMPLEMENTED_OFFLINE"
    )
    assert requirements["IMMUTABLE_DECISION_OUTPUT_PAYLOAD"]["status"] == ("BLOCKED_BY_EVIDENCE")
    critical = {
        item["requirementId"]
        for item in artifact["criticalFindings"]
        if item["severity"] == "CRITICAL"
    }
    assert {
        "IMMUTABLE_DECISION_OUTPUT_PAYLOAD",
        "FINAL_PROSPECTIVE_MODEL_VALIDATION",
    }.issubset(critical)


def test_goal_specific_evaluation_gaps_remain_explicit() -> None:
    requirements = _requirements(_artifact())
    assert requirements["TACTICAL_ENTRY_TIMING_VALIDATION"]["status"] == ("IMPLEMENTED_OFFLINE")
    assert requirements["LONG_EXPECTED_RETURN_CALIBRATION"]["status"] == ("IMPLEMENTED_OFFLINE")
    assert (
        requirements["MISSING_AI_HUMAN_AND_EVIDENCE_ROLE_SEPARATION"]["status"]
        == "IMPLEMENTED_OFFLINE"
    )
    assert requirements["REPEATED_PROSPECTIVE_COHORT_ACCUMULATION"]["status"] == ("NOT_EXECUTED")
    assert requirements["POST_FREEZE_66_MODEL_INPUT_ADAPTER"]["status"] == ("BLOCKED_BY_EVIDENCE")
    assert requirements["MATURED_OUTCOME_AND_PATH_METRIC_EVALUATOR"]["status"] == (
        "IMPLEMENTED_OFFLINE"
    )
    assert requirements["DQV_STATISTICS_AND_FINAL_QUALITY_REPORT"]["status"] == (
        "IMPLEMENTED_OFFLINE"
    )
    assert requirements["MATURITY_TO_STATISTICS_ADAPTER"]["status"] == ("IMPLEMENTED_OFFLINE")
    assert requirements["FINAL_PROSPECTIVE_MODEL_VALIDATION"]["status"] == ("NOT_VALIDATED")


def test_audit_itself_is_strictly_offline_and_non_mutating() -> None:
    execution = _artifact()["executionBoundary"]
    assert execution == {
        "providerNetworkRequests": 0,
        "databaseReads": 0,
        "databaseWrites": 0,
        "scoresOrRanksComputed": False,
        "enrollmentExecuted": False,
        "outcomesComputed": False,
        "commitCreated": False,
        "pushExecuted": False,
        "deploymentExecuted": False,
    }
