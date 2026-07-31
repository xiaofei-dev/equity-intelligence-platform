from __future__ import annotations

import json
from pathlib import Path

import pytest

from equity_analysis.forward_validation.prospective_activation_v20 import (
    ProspectiveActivationV20Error,
    build_deterministic_output_preflight_v20,
    build_post_close_preflight_v20,
    build_prospective_enrollment_preflight_v20,
    build_v20_activation_acceptance,
    verify_v20_activation_acceptance,
    write_immutable_artifact,
)
from equity_analysis.schema_audit.end_to_end_validation_gap_v2 import (
    build_end_to_end_validation_gap_audit_v2,
    verify_end_to_end_validation_gap_audit_v2,
)

ROOT = Path(__file__).resolve().parents[2]


def _checked_in(relative: str) -> dict:
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def _activation() -> dict:
    return _checked_in(
        "docs/generated/forward-dqv-v20-activation-acceptance-v1.json"
    )


def test_v20_activation_binds_current_sources_and_no_real_execution() -> None:
    artifact = _activation()
    assert verify_v20_activation_acceptance(ROOT, artifact) == (
        artifact["artifactContentHash"]
    )
    assert artifact == build_v20_activation_acceptance(
        ROOT,
        focused_python_tests_passed=67,
        postgresql17_acceptance_passed=3,
    )
    assert set(artifact["infrastructure"].values()) == {"READY"}
    assert set(artifact["realExecutionState"].values()) == {
        "NOT_EXECUTED",
        "NOT_AVAILABLE",
    }
    assert artifact["humanAndPortfolioGovernance"][
        "portfolioSuitabilityState"
    ] == "NOT_ASSESSED_BY_MODEL"
    assert artifact["humanAndPortfolioGovernance"][
        "automaticTradingAuthorized"
    ] is False


def test_v20_enrollment_preflight_supersedes_v19_without_enrolling() -> None:
    expected = build_prospective_enrollment_preflight_v20(
        ROOT,
        activation=_activation(),
    )
    actual = _checked_in(
        "docs/generated/"
        "prospective-enrollment-adapter-v2-2-v20-preflight-v1.json"
    )
    assert actual == expected
    assert actual["infrastructureState"] == "READY"
    assert actual["realEnrollmentState"] == "NOT_EXECUTED"
    assert "REAL_CONTROLLED_BENCHMARK_LEDGER_MISSING" in (
        actual["blockedReasons"]
    )
    assert actual["executionBoundary"]["enrollmentExecuted"] is False


def test_post_close_v4_resolves_only_stale_implementation_blocker() -> None:
    expected = build_post_close_preflight_v20(
        ROOT,
        activation=_activation(),
    )
    actual = _checked_in(
        "docs/generated/post-close-pipeline-orchestrator-v2-2-preflight-v4.json"
    )
    assert actual == expected
    assert (
        "CONTROLLED_BENCHMARK_CONSTITUENT_LEDGER_NOT_IMPLEMENTED"
        not in actual["blockedReasons"]
    )
    assert "REAL_CONTROLLED_BENCHMARK_LEDGER_MISSING" in (
        actual["blockedReasons"]
    )
    assert actual["supersededImplementationBlocker"][
        "mayProveRealLedgerExists"
    ] is False
    assert "TARGET_SESSION_NOT_COMPLETED" in actual["blockedReasons"]


def test_deterministic_output_preflight_keeps_real_evidence_missing() -> None:
    expected = build_deterministic_output_preflight_v20(
        ROOT,
        activation=_activation(),
    )
    actual = _checked_in(
        "docs/generated/"
        "post-freeze-deterministic-decision-output-v2-2-preflight-v2.json"
    )
    assert actual == expected
    assert actual["controlledLedgerInfrastructureState"] == "READY"
    assert "REAL_CONTROLLED_BENCHMARK_LEDGER_MISSING" in actual["blockers"]
    assert actual["realScoresComputed"] is False


def test_gap_v2_is_current_and_model_labels_remain_unvalidated() -> None:
    actual = _checked_in(
        "docs/generated/end-to-end-validation-completion-gap-audit-v2.json"
    )
    assert build_end_to_end_validation_gap_audit_v2(ROOT) == actual
    assert verify_end_to_end_validation_gap_audit_v2(ROOT, actual) == (
        actual["artifactContentHash"]
    )
    states = {item["id"]: item["status"] for item in actual["requirements"]}
    assert states["V20_SUCCESSOR_SCHEMA"] == "IMPLEMENTED_OFFLINE"
    assert states["REAL_PROSPECTIVE_ENROLLMENT"] == "NOT_EXECUTED"
    assert states["NATURALLY_MATURED_OUTCOMES"] == "NOT_AVAILABLE"
    assert states["FINAL_FORWARD_MODEL_VALIDATION"] == "NOT_VALIDATED"
    assert actual["modelEvidenceLabelsChanged"] is False


def test_source_hash_drift_is_rejected() -> None:
    artifact = _activation()
    artifact["sourceFiles"]["v20Migration"]["fileSha256"] = (
        "sha256:" + "f" * 64
    )
    with pytest.raises(
        ProspectiveActivationV20Error,
        match="V20_ACTIVATION_HASH_MISMATCH",
    ):
        verify_v20_activation_acceptance(ROOT, artifact)


def test_immutable_writer_replays_and_rejects_conflict(
    tmp_path: Path,
) -> None:
    artifact = _activation()
    path = tmp_path / "artifact.json"
    assert write_immutable_artifact(path, artifact) == (
        write_immutable_artifact(path, artifact)
    )
    path.write_text("{}\n", encoding="utf-8")
    with pytest.raises(
        ProspectiveActivationV20Error,
        match="IMMUTABLE_ARTIFACT_CONFLICT",
    ):
        write_immutable_artifact(path, artifact)
