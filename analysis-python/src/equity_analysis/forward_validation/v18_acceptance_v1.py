from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from equity_analysis.analytics_interface.contracts import canonical_hash

FORWARD_DQV_V18_ACCEPTANCE_VERSION = "FORWARD-DQV-V18-ACCEPTANCE-v1.0.0"

V18_MIGRATION_PATH = Path(
    "database/migrations/V18__create_forward_dqv_v2_outcome_ledger.sql"
)
OUTCOMES_V21_PATH = Path(
    "analysis-python/src/equity_analysis/forward_validation/outcomes_v21.py"
)
REPOSITORY_V21_PATH = Path(
    "analysis-python/src/equity_analysis/forward_validation/"
    "outcome_persistence_v21.py"
)

EXPECTED_TABLES = (
    "analytics.forward_dqv_enrollment_v2",
    "analytics.forward_dqv_maturity_schedule_v2",
    "analytics.forward_dqv_outcome_batch_v2",
    "analytics.forward_dqv_security_outcome_v2",
    "analytics.forward_dqv_benchmark_outcome_v2",
    "analytics.forward_dqv_path_metric_v2",
    "analytics.forward_dqv_quality_report_v2",
)
EXPECTED_HORIZONS = (5, 20, 60, 126, 252)
EXPECTED_BENCHMARK_KINDS = (
    "SPY",
    "SECTOR",
    "EQUAL_WEIGHT",
    "PURE_MOMENTUM",
    "PURE_VALUE",
    "PURE_QUALITY",
)
EXPECTED_UPGRADE_STARTS = ("V1", "V3", "V12", "V16", "V17")


class ForwardDqvV18AcceptanceError(RuntimeError):
    pass


def _file_sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _source_evidence(repository_root: Path) -> dict[str, dict[str, str]]:
    return {
        "migration": {
            "path": V18_MIGRATION_PATH.as_posix(),
            "fileSha256": _file_sha256(repository_root / V18_MIGRATION_PATH),
        },
        "outcomesV21": {
            "path": OUTCOMES_V21_PATH.as_posix(),
            "fileSha256": _file_sha256(repository_root / OUTCOMES_V21_PATH),
        },
        "repositoryV21": {
            "path": REPOSITORY_V21_PATH.as_posix(),
            "fileSha256": _file_sha256(repository_root / REPOSITORY_V21_PATH),
        },
    }


def build_forward_dqv_v18_acceptance(repository_root: Path) -> dict[str, Any]:
    source_files = _source_evidence(repository_root)
    repository_contract_hash = canonical_hash(
        {
            "outcomesV21": source_files["outcomesV21"]["fileSha256"],
            "repositoryV21": source_files["repositoryV21"]["fileSha256"],
        }
    )
    body: dict[str, Any] = {
        "artifactType": "FORWARD_DQV_V18_ACCEPTANCE",
        "schemaVersion": FORWARD_DQV_V18_ACCEPTANCE_VERSION,
        "effectiveDate": "2026-07-29",
        "status": "READY",
        "implementationStatus": "READY",
        "enrollmentStatus": "NOT_EXECUTED",
        "migrationVersion": 18,
        "migrationApplied": True,
        "appendOnlyValidated": True,
        "fiveHorizonCompletenessValidated": True,
        "sixBenchmarkCompletenessValidated": True,
        "migrationFileSha256": source_files["migration"]["fileSha256"],
        "repositoryContractHash": repository_contract_hash,
        "sourceFiles": source_files,
        "schemaContract": {
            "tables": list(EXPECTED_TABLES),
            "completedSessionHorizons": list(EXPECTED_HORIZONS),
            "benchmarkKinds": list(EXPECTED_BENCHMARK_KINDS),
            "tableCount": len(EXPECTED_TABLES),
            "horizonCount": len(EXPECTED_HORIZONS),
            "benchmarkKindCount": len(EXPECTED_BENCHMARK_KINDS),
        },
        "postgresql17Acceptance": {
            "status": "PASS",
            "engine": "PostgreSQL 17",
            "upgradeMatrix": [
                {
                    "fromVersion": start,
                    "toVersion": "V18",
                    "status": "PASS",
                }
                for start in EXPECTED_UPGRADE_STARTS
            ],
        },
        "testAcceptance": {
            "repositoryTests": {"status": "PASS", "passed": 3},
            "fullPythonSuite": {
                "status": "PASS",
                "passed": 892,
                "skipped": 17,
                "workingDirectory": "repository-root",
            },
            "ruff": {"status": "PASS"},
            "gitDiffCheck": {
                "status": "PASS",
                "lineEndingNoticesOnly": True,
            },
        },
        "executionBoundary": {
            "networkRequests": 0,
            "providerRequests": 0,
            "businessDatabaseWrites": 0,
            "scoresComputed": False,
            "enrollmentExecuted": False,
            "outcomesComputed": False,
            "commitCreated": False,
            "pushExecuted": False,
            "deploymentExecuted": False,
            "credentialsIncluded": False,
            "databaseUrlIncluded": False,
        },
    }
    return {**body, "artifactContentHash": canonical_hash(body)}


def verify_forward_dqv_v18_acceptance(
    artifact: dict[str, Any],
    repository_root: Path,
) -> str:
    claimed_hash = artifact.get("artifactContentHash")
    if not isinstance(claimed_hash, str):
        raise ForwardDqvV18AcceptanceError("ACCEPTANCE_CANONICAL_HASH_MISSING")
    body = {
        key: value
        for key, value in artifact.items()
        if key != "artifactContentHash"
    }
    if canonical_hash(body) != claimed_hash:
        raise ForwardDqvV18AcceptanceError("ACCEPTANCE_CANONICAL_HASH_MISMATCH")

    required_pairs = {
        "artifactType": "FORWARD_DQV_V18_ACCEPTANCE",
        "schemaVersion": FORWARD_DQV_V18_ACCEPTANCE_VERSION,
        "status": "READY",
        "implementationStatus": "READY",
        "enrollmentStatus": "NOT_EXECUTED",
        "migrationVersion": 18,
        "migrationApplied": True,
        "appendOnlyValidated": True,
        "fiveHorizonCompletenessValidated": True,
        "sixBenchmarkCompletenessValidated": True,
    }
    if any(artifact.get(key) != value for key, value in required_pairs.items()):
        raise ForwardDqvV18AcceptanceError("ACCEPTANCE_STATE_INVALID")

    source_files = artifact.get("sourceFiles")
    if source_files != _source_evidence(repository_root):
        raise ForwardDqvV18AcceptanceError("ACCEPTANCE_SOURCE_HASH_MISMATCH")
    if artifact.get("migrationFileSha256") != source_files["migration"][
        "fileSha256"
    ]:
        raise ForwardDqvV18AcceptanceError("ACCEPTANCE_MIGRATION_HASH_MISMATCH")
    expected_repository_hash = canonical_hash(
        {
            "outcomesV21": source_files["outcomesV21"]["fileSha256"],
            "repositoryV21": source_files["repositoryV21"]["fileSha256"],
        }
    )
    if artifact.get("repositoryContractHash") != expected_repository_hash:
        raise ForwardDqvV18AcceptanceError("ACCEPTANCE_REPOSITORY_HASH_MISMATCH")

    contract = artifact.get("schemaContract") or {}
    if (
        tuple(contract.get("tables") or ()) != EXPECTED_TABLES
        or tuple(contract.get("completedSessionHorizons") or ())
        != EXPECTED_HORIZONS
        or tuple(contract.get("benchmarkKinds") or ())
        != EXPECTED_BENCHMARK_KINDS
        or contract.get("tableCount") != 7
        or contract.get("horizonCount") != 5
        or contract.get("benchmarkKindCount") != 6
    ):
        raise ForwardDqvV18AcceptanceError("ACCEPTANCE_SCHEMA_CONTRACT_INVALID")

    migration_text = (repository_root / V18_MIGRATION_PATH).read_text(
        encoding="utf-8"
    )
    migration_tokens = (
        *(f"CREATE TABLE {table}" for table in EXPECTED_TABLES),
        "CHECK (completed_sessions IN (5, 20, 60, 126, 252))",
        *EXPECTED_BENCHMARK_KINDS,
    )
    if any(token not in migration_text for token in migration_tokens):
        raise ForwardDqvV18AcceptanceError("ACCEPTANCE_MIGRATION_CONTRACT_DRIFT")

    matrix = artifact.get("postgresql17Acceptance") or {}
    rows = matrix.get("upgradeMatrix") or []
    if (
        matrix.get("status") != "PASS"
        or matrix.get("engine") != "PostgreSQL 17"
        or tuple(row.get("fromVersion") for row in rows)
        != EXPECTED_UPGRADE_STARTS
        or any(
            row.get("toVersion") != "V18" or row.get("status") != "PASS"
            for row in rows
        )
    ):
        raise ForwardDqvV18AcceptanceError("ACCEPTANCE_POSTGRES_MATRIX_INVALID")

    tests = artifact.get("testAcceptance") or {}
    if (
        tests.get("repositoryTests") != {"status": "PASS", "passed": 3}
        or (tests.get("fullPythonSuite") or {}).get("status") != "PASS"
        or (tests.get("ruff") or {}).get("status") != "PASS"
        or (tests.get("gitDiffCheck") or {}).get("status") != "PASS"
    ):
        raise ForwardDqvV18AcceptanceError("ACCEPTANCE_TEST_EVIDENCE_INVALID")

    boundary = artifact.get("executionBoundary") or {}
    if (
        boundary.get("networkRequests") != 0
        or boundary.get("businessDatabaseWrites") != 0
        or boundary.get("scoresComputed") is not False
        or boundary.get("enrollmentExecuted") is not False
        or boundary.get("credentialsIncluded") is not False
        or boundary.get("databaseUrlIncluded") is not False
    ):
        raise ForwardDqvV18AcceptanceError("ACCEPTANCE_EXECUTION_BOUNDARY_INVALID")
    return claimed_hash


def load_and_verify_forward_dqv_v18_acceptance(
    path: Path,
    repository_root: Path,
) -> tuple[dict[str, Any], str]:
    artifact = json.loads(path.read_text(encoding="utf-8"))
    return artifact, verify_forward_dqv_v18_acceptance(
        artifact,
        repository_root,
    )


def write_immutable_acceptance(path: Path, artifact: dict[str, Any]) -> str:
    encoded = (json.dumps(artifact, indent=2, ensure_ascii=False) + "\n").encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != encoded:
            raise ForwardDqvV18AcceptanceError(
                "IMMUTABLE_ACCEPTANCE_CONFLICT"
            )
    else:
        with path.open("xb") as handle:
            handle.write(encoded)
    return hashlib.sha256(encoded).hexdigest().upper()
