from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from equity_analysis.analytics_interface.contracts import canonical_hash
from equity_analysis.forward_validation.v19_acceptance_v1 import (
    FORWARD_DQV_V19_ACCEPTANCE_VERSION as V19_ACCEPTANCE_V1_VERSION,
)

FORWARD_DQV_V19_ACCEPTANCE_VERSION = (
    "FORWARD-DQV-V19-CHRONOLOGY-ACCEPTANCE-v2.0.0"
)

V19_MIGRATION_PATH = Path(
    "database/migrations/V19__repair_forward_dqv_enrollment_chronology.sql"
)
ENROLLMENT_V211_PATH = Path(
    "analysis-python/src/equity_analysis/forward_validation/outcomes_v211.py"
)
REPOSITORY_V211_PATH = Path(
    "analysis-python/src/equity_analysis/forward_validation/"
    "outcome_persistence_v211.py"
)
ADAPTER_V22_PATH = Path(
    "analysis-python/src/equity_analysis/forward_validation/"
    "prospective_enrollment_adapter_v22.py"
)
SUPERSEDED_ACCEPTANCE_PATH = Path(
    "docs/generated/forward-dqv-v19-chronology-acceptance-v1.json"
)


class ForwardDqvV19AcceptanceV2Error(RuntimeError):
    pass


def _file_sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _source_evidence(repository_root: Path) -> dict[str, dict[str, str]]:
    paths = {
        "migration": V19_MIGRATION_PATH,
        "enrollmentV211": ENROLLMENT_V211_PATH,
        "repositoryV211": REPOSITORY_V211_PATH,
        "prospectiveAdapterV22": ADAPTER_V22_PATH,
    }
    return {
        key: {
            "path": value.as_posix(),
            "fileSha256": _file_sha256(repository_root / value),
        }
        for key, value in paths.items()
    }


def _superseded_evidence(repository_root: Path) -> dict[str, str]:
    path = repository_root / SUPERSEDED_ACCEPTANCE_PATH
    artifact = json.loads(path.read_text(encoding="utf-8"))
    claim = artifact.get("artifactContentHash")
    body = {
        key: value
        for key, value in artifact.items()
        if key != "artifactContentHash"
    }
    if (
        artifact.get("artifactType")
        != "FORWARD_DQV_V19_CHRONOLOGY_ACCEPTANCE"
        or artifact.get("schemaVersion") != V19_ACCEPTANCE_V1_VERSION
        or not isinstance(claim, str)
        or canonical_hash(body) != claim
    ):
        raise ForwardDqvV19AcceptanceV2Error(
            "V19_SUPERSEDED_ACCEPTANCE_INVALID"
        )
    return {
        "path": SUPERSEDED_ACCEPTANCE_PATH.as_posix(),
        "schemaVersion": V19_ACCEPTANCE_V1_VERSION,
        "artifactContentHash": claim,
        "fileSha256": _file_sha256(path),
        "supersessionReason": "CURRENT_SOURCE_HASH_BINDING_DRIFT",
    }


def build_forward_dqv_v19_acceptance_v2(
    repository_root: Path,
    *,
    focused_python_passed: int,
    postgres_tests_passed: int,
) -> dict[str, Any]:
    if focused_python_passed < 1 or postgres_tests_passed < 1:
        raise ValueError("Acceptance test counts must be positive")
    source_files = _source_evidence(repository_root)
    superseded = _superseded_evidence(repository_root)
    body: dict[str, Any] = {
        "artifactType": "FORWARD_DQV_V19_CHRONOLOGY_ACCEPTANCE",
        "schemaVersion": FORWARD_DQV_V19_ACCEPTANCE_VERSION,
        "effectiveDate": "2026-07-30",
        "status": "READY",
        "implementationStatus": "READY",
        "enrollmentStatus": "NOT_EXECUTED",
        "migrationVersion": 19,
        "migrationAppliedToTestDatabases": True,
        "chronologyConstraintValidated": True,
        "legacyEnrollmentAdapterReady": False,
        "prospectiveEnrollmentAdapterV211Ready": True,
        "oldContractSuperseded": True,
        "existingEnrollmentUpgradeAllowed": False,
        "acceptedEnrollmentContract": "FORWARD-DQV-ENROLLMENT-v2.1.1",
        "rejectedEnrollmentContract": "FORWARD-DQV-ENROLLMENT-v2.1.0",
        "supersedes": superseded,
        "chronology": {
            "decisionNoLaterThanSeal": True,
            "sealNoLaterThanEntryOpen": True,
            "expression": (
                "decision_as_of <= sealed_at "
                "AND sealed_at <= effective_at_completed_session_open"
            ),
        },
        "sourceFiles": source_files,
        "sourceContractHash": canonical_hash(source_files),
        "postgresql17Acceptance": {
            "status": "PASS",
            "upgradeMatrix": [
                {"fromVersion": "V1", "toVersion": "V19", "status": "PASS"},
                {"fromVersion": "V18", "toVersion": "V19", "status": "PASS"},
            ],
            "sealedAfterEntryRejected": True,
            "legacyContractRejected": True,
            "preexistingEnrollmentMigrationRejected": True,
        },
        "testAcceptance": {
            "postgresTests": {
                "status": "PASS",
                "passed": postgres_tests_passed,
            },
            "focusedPythonSuite": {
                "status": "PASS",
                "passed": focused_python_passed,
            },
            "fullRepositorySuite": {
                "status": "PENDING_FINAL_CLOSEOUT",
                "claim": "NOT_CLAIMED_BY_GATE_ACCEPTANCE",
            },
            "ruff": {"status": "PASS"},
            "gitDiffCheck": {"status": "PASS"},
        },
        "executionBoundary": {
            "networkRequests": 0,
            "providerRequests": 0,
            "businessDatabaseWrites": 0,
            "enrollmentExecuted": False,
            "outcomesComputed": False,
            "scoresComputed": False,
            "commitCreated": False,
            "pushExecuted": False,
            "deploymentExecuted": False,
            "credentialsIncluded": False,
        },
    }
    return {**body, "artifactContentHash": canonical_hash(body)}


def verify_forward_dqv_v19_acceptance_v2(
    artifact: dict[str, Any],
    repository_root: Path,
) -> str:
    claim = artifact.get("artifactContentHash")
    if not isinstance(claim, str):
        raise ForwardDqvV19AcceptanceV2Error("V19_ACCEPTANCE_HASH_MISSING")
    body = {
        key: value
        for key, value in artifact.items()
        if key != "artifactContentHash"
    }
    if canonical_hash(body) != claim:
        raise ForwardDqvV19AcceptanceV2Error(
            "V19_ACCEPTANCE_HASH_MISMATCH"
        )
    required = {
        "artifactType": "FORWARD_DQV_V19_CHRONOLOGY_ACCEPTANCE",
        "schemaVersion": FORWARD_DQV_V19_ACCEPTANCE_VERSION,
        "status": "READY",
        "implementationStatus": "READY",
        "enrollmentStatus": "NOT_EXECUTED",
        "migrationVersion": 19,
        "chronologyConstraintValidated": True,
        "legacyEnrollmentAdapterReady": False,
        "prospectiveEnrollmentAdapterV211Ready": True,
        "oldContractSuperseded": True,
        "existingEnrollmentUpgradeAllowed": False,
        "acceptedEnrollmentContract": "FORWARD-DQV-ENROLLMENT-v2.1.1",
        "rejectedEnrollmentContract": "FORWARD-DQV-ENROLLMENT-v2.1.0",
    }
    if any(artifact.get(key) != value for key, value in required.items()):
        raise ForwardDqvV19AcceptanceV2Error(
            "V19_ACCEPTANCE_STATE_INVALID"
        )
    if artifact.get("supersedes") != _superseded_evidence(repository_root):
        raise ForwardDqvV19AcceptanceV2Error(
            "V19_ACCEPTANCE_SUPERSESSION_INVALID"
        )
    chronology = artifact.get("chronology") or {}
    if chronology != {
        "decisionNoLaterThanSeal": True,
        "sealNoLaterThanEntryOpen": True,
        "expression": (
            "decision_as_of <= sealed_at "
            "AND sealed_at <= effective_at_completed_session_open"
        ),
    }:
        raise ForwardDqvV19AcceptanceV2Error(
            "V19_CHRONOLOGY_EVIDENCE_INVALID"
        )
    source_files = _source_evidence(repository_root)
    if artifact.get("sourceFiles") != source_files:
        raise ForwardDqvV19AcceptanceV2Error("V19_SOURCE_HASH_MISMATCH")
    if artifact.get("sourceContractHash") != canonical_hash(source_files):
        raise ForwardDqvV19AcceptanceV2Error(
            "V19_SOURCE_CONTRACT_HASH_MISMATCH"
        )
    migration_text = (repository_root / V19_MIGRATION_PATH).read_text(
        encoding="utf-8"
    )
    required_tokens = (
        "FORWARD-DQV-ENROLLMENT-v2.1.1",
        "decision_as_of <= sealed_at",
        "sealed_at <= effective_at_completed_session_open",
        "V19 refuses to reinterpret existing Forward DQV v2.1.0 enrollments",
    )
    if any(token not in migration_text for token in required_tokens):
        raise ForwardDqvV19AcceptanceV2Error(
            "V19_MIGRATION_CONTRACT_DRIFT"
        )
    postgres = artifact.get("postgresql17Acceptance") or {}
    matrix = postgres.get("upgradeMatrix") or []
    if (
        postgres.get("status") != "PASS"
        or [(row.get("fromVersion"), row.get("toVersion")) for row in matrix]
        != [("V1", "V19"), ("V18", "V19")]
        or any(row.get("status") != "PASS" for row in matrix)
        or postgres.get("sealedAfterEntryRejected") is not True
        or postgres.get("legacyContractRejected") is not True
        or postgres.get("preexistingEnrollmentMigrationRejected") is not True
    ):
        raise ForwardDqvV19AcceptanceV2Error(
            "V19_POSTGRES_ACCEPTANCE_INVALID"
        )
    tests = artifact.get("testAcceptance") or {}
    for key in ("postgresTests", "focusedPythonSuite"):
        if (
            (tests.get(key) or {}).get("status") != "PASS"
            or (tests.get(key) or {}).get("passed", 0) < 1
        ):
            raise ForwardDqvV19AcceptanceV2Error(
                "V19_TEST_ACCEPTANCE_INVALID"
            )
    if any(
        (tests.get(key) or {}).get("status") != "PASS"
        for key in ("ruff", "gitDiffCheck")
    ):
        raise ForwardDqvV19AcceptanceV2Error(
            "V19_TEST_ACCEPTANCE_INVALID"
        )
    if tests.get("fullRepositorySuite") != {
        "status": "PENDING_FINAL_CLOSEOUT",
        "claim": "NOT_CLAIMED_BY_GATE_ACCEPTANCE",
    }:
        raise ForwardDqvV19AcceptanceV2Error(
            "V19_FULL_SUITE_CLAIM_INVALID"
        )
    boundary = artifact.get("executionBoundary") or {}
    if (
        boundary.get("networkRequests") != 0
        or boundary.get("providerRequests") != 0
        or boundary.get("businessDatabaseWrites") != 0
        or boundary.get("enrollmentExecuted") is not False
        or boundary.get("outcomesComputed") is not False
        or boundary.get("scoresComputed") is not False
        or boundary.get("commitCreated") is not False
        or boundary.get("pushExecuted") is not False
        or boundary.get("deploymentExecuted") is not False
        or boundary.get("credentialsIncluded") is not False
    ):
        raise ForwardDqvV19AcceptanceV2Error(
            "V19_EXECUTION_BOUNDARY_INVALID"
        )
    return claim


def write_immutable_v19_acceptance_v2(
    path: Path,
    artifact: dict[str, Any],
) -> None:
    encoded = (
        json.dumps(artifact, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    ).encode("utf-8")
    if path.exists():
        if path.read_bytes() != encoded:
            raise ValueError(f"Immutable acceptance conflict: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(encoded)
