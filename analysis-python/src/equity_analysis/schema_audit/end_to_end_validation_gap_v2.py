from __future__ import annotations

from pathlib import Path
from typing import Any

from equity_analysis.analytics_interface.contracts import canonical_hash
from equity_analysis.forward_validation.prospective_activation_v20 import (
    file_sha256,
    load_canonical_artifact,
)

SCHEMA_VERSION = "END-TO-END-VALIDATION-COMPLETION-GAP-AUDIT-v2.0.0"

_ACTIVATION = Path(
    "docs/generated/forward-dqv-v20-activation-acceptance-v1.json"
)
_ENROLLMENT = Path(
    "docs/generated/prospective-enrollment-adapter-v2-2-v20-preflight-v1.json"
)
_POST_CLOSE = Path(
    "docs/generated/post-close-pipeline-orchestrator-v2-2-preflight-v4.json"
)
_OUTPUT = Path(
    "docs/generated/post-freeze-deterministic-decision-output-v2-2-preflight-v2.json"
)
_LEGACY = Path(
    "docs/generated/end-to-end-validation-completion-gap-audit-v1.json"
)


def build_end_to_end_validation_gap_audit_v2(
    repository_root: Path,
) -> dict[str, Any]:
    artifacts = {
        "v20Activation": _binding(repository_root, _ACTIVATION),
        "prospectiveEnrollment": _binding(repository_root, _ENROLLMENT),
        "postCloseOrchestrator": _binding(repository_root, _POST_CLOSE),
        "deterministicOutput": _binding(repository_root, _OUTPUT),
    }
    legacy = load_canonical_artifact(repository_root / _LEGACY)
    post_close = load_canonical_artifact(repository_root / _POST_CLOSE)
    enrollment = load_canonical_artifact(repository_root / _ENROLLMENT)
    body: dict[str, Any] = {
        "artifactType": "END_TO_END_VALIDATION_COMPLETION_GAP_AUDIT",
        "schemaVersion": SCHEMA_VERSION,
        "effectiveDate": "2026-07-30",
        "overallStatus": "BLOCKED_NOT_VALIDATED",
        "supersedes": {
            "path": _LEGACY.as_posix(),
            "artifactContentHash": legacy["artifactContentHash"],
            "fileSha256": file_sha256(repository_root / _LEGACY),
            "reason": "V20_INFRASTRUCTURE_AND_CURRENT_PREFLIGHT_BINDINGS",
        },
        "authoritativeArtifacts": artifacts,
        "requirements": [
            _requirement(
                "V20_SUCCESSOR_SCHEMA",
                "IMPLEMENTED_OFFLINE",
            ),
            _requirement(
                "CONTROLLED_BENCHMARK_LEDGER_INFRASTRUCTURE",
                "IMPLEMENTED_OFFLINE",
            ),
            _requirement(
                "HUMAN_DECISION_AND_PORTFOLIO_BOUNDARY",
                "IMPLEMENTED_OFFLINE",
            ),
            _requirement(
                "COMPLETED_SESSION_CAPTURE",
                "BLOCKED_BY_TIME",
            ),
            _requirement(
                "REAL_66_MODEL_INPUTS",
                "BLOCKED_BY_EVIDENCE",
            ),
            _requirement(
                "REAL_CONTROLLED_BENCHMARK_LEDGER",
                "NOT_EXECUTED",
            ),
            _requirement(
                "REAL_PROSPECTIVE_ENROLLMENT",
                "NOT_EXECUTED",
            ),
            _requirement(
                "NATURALLY_MATURED_OUTCOMES",
                "NOT_AVAILABLE",
            ),
            _requirement(
                "FINAL_FORWARD_MODEL_VALIDATION",
                "NOT_VALIDATED",
            ),
        ],
        "resolvedStaleBlocker": (
            "CONTROLLED_BENCHMARK_CONSTITUENT_LEDGER_NOT_IMPLEMENTED"
        ),
        "currentPostCloseBlockers": post_close["blockedReasons"],
        "currentEnrollmentBlockers": enrollment["blockedReasons"],
        "modelEvidenceLabelsChanged": False,
        "fixtureMayProveRealExecution": False,
        "executionBoundary": {
            "providerNetworkRequests": 0,
            "databaseReads": 0,
            "businessDatabaseWrites": 0,
            "scoresOrRanksComputed": False,
            "enrollmentExecuted": False,
            "outcomesComputed": False,
            "maturityExecuted": False,
            "commitCreated": False,
            "pushExecuted": False,
            "deploymentExecuted": False,
        },
    }
    return {**body, "artifactContentHash": canonical_hash(body)}


def verify_end_to_end_validation_gap_audit_v2(
    repository_root: Path,
    artifact: dict[str, Any],
) -> str:
    expected = build_end_to_end_validation_gap_audit_v2(repository_root)
    if artifact != expected:
        raise ValueError("END_TO_END_GAP_V2_CURRENT_STATE_MISMATCH")
    return expected["artifactContentHash"]


def _binding(repository_root: Path, relative: Path) -> dict[str, str]:
    artifact = load_canonical_artifact(repository_root / relative)
    return {
        "path": relative.as_posix(),
        "artifactContentHash": artifact["artifactContentHash"],
        "fileSha256": file_sha256(repository_root / relative),
    }


def _requirement(identifier: str, status: str) -> dict[str, str]:
    return {"id": identifier, "status": status}
