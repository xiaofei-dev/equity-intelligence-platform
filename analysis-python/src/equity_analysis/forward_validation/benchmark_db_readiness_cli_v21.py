from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

from equity_analysis.analytics_interface.contracts import canonical_hash
from equity_analysis.forward_validation.benchmark_db_readiness_v21 import (
    BenchmarkDbReadinessV21,
    PostgresBenchmarkReadinessAdapterV21,
)
from equity_analysis.provider_validation.execution_safety import (
    repository_root_env_path,
)

BENCHMARK_DB_READINESS_ARTIFACT_V21 = "FORWARD-BENCHMARK-DB-READINESS-ARTIFACT-v2.1.0"
FROZEN_PARENT_LIQUIDITY_COST_POLICY_VERSION = "LIQUIDITY-SENSITIVE-COST-v1.0.0"
FROZEN_PARENT_LIQUIDITY_COST_POLICY_HASH = (
    "sha256:b07f5c5ad4b2f13d0c81a48b2eab4e722da9b0e43143e013bedcc155faba96bb"
)


def _environment() -> dict[str, str]:
    path = repository_root_env_path()
    if not path.exists():
        return {}
    result: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            result[key.strip()] = value.strip()
    return result


def _database_url(environment: dict[str, str]) -> str:
    explicit = os.getenv("ANALYTICS_DATABASE_URL") or environment.get("ANALYTICS_DATABASE_URL", "")
    if explicit:
        return explicit
    required = (
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
        "POSTGRES_PORT",
        "POSTGRES_DB",
    )
    if any(not environment.get(key) for key in required):
        raise SystemExit("ANALYTICS_DATABASE_URL or local PostgreSQL settings are required")
    return "postgresql://{}:{}@localhost:{}/{}".format(
        environment["POSTGRES_USER"],
        environment["POSTGRES_PASSWORD"],
        environment["POSTGRES_PORT"],
        environment["POSTGRES_DB"],
    )


def build_git_safe_artifact(
    result: BenchmarkDbReadinessV21,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "artifactType": "FORWARD_BENCHMARK_DB_READINESS",
        "schemaVersion": BENCHMARK_DB_READINESS_ARTIFACT_V21,
        "readinessVersion": result.version,
        "dataSnapshotId": str(result.data_snapshot_id),
        "snapshotAsOf": result.snapshot_as_of.isoformat(),
        "ingestionCutoff": result.ingestion_cutoff.isoformat(),
        "universeVersion": result.universe_version,
        "universeHash": result.universe_hash,
        "declaredSecurityCount": result.declared_security_count,
        "loadedSecurityCount": result.loaded_security_count,
        "status": result.status.value,
        "schemaBlockers": list(result.schema_blockers),
        "evidenceBlockers": list(result.evidence_blockers),
        "benchmarkFamilies": [
            {
                "kind": family.kind.value,
                "state": family.state.value,
                "reasonCodes": list(family.reason_codes),
                "evidenceHash": family.evidence_hash,
                "sourceEvidenceHash": family.source_evidence_hash,
                "constituentSetHash": family.constituent_set_hash,
                "weightHash": family.weight_hash,
                "selectionHash": family.selection_hash,
                "costEvidenceHash": family.cost_evidence_hash,
                "sectorAssignmentHash": family.sector_assignment_hash,
                "terminalHash": family.terminal_hash,
            }
            for family in result.families
        ],
        "constructionContractHash": result.construction_contract_hash,
        "constructionBundleHash": result.construction_bundle_hash,
        "parentLiquidityCostPolicyVersion": (FROZEN_PARENT_LIQUIDITY_COST_POLICY_VERSION),
        "parentLiquidityCostPolicyHash": (result.parent_liquidity_cost_policy_hash),
        "diagnosticContentHash": result.diagnostic_content_hash,
        "prospectiveEnrollmentAllowed": (result.prospective_enrollment_allowed),
        "databaseWrites": result.database_writes,
        "providerNetworkRequests": result.provider_network_requests,
        "latestSnapshotSelectionUsed": False,
        "rawProviderValuesIncluded": False,
        "automaticTradingAuthorized": False,
    }
    return {**body, "artifactContentHash": canonical_hash(body)}


def write_immutable_artifact(
    output_path: Path,
    artifact: dict[str, Any],
) -> str:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (
        json.dumps(
            artifact,
            indent=2,
            sort_keys=False,
            ensure_ascii=False,
        )
        + "\n"
    ).encode()
    if output_path.exists():
        if output_path.read_bytes() != encoded:
            raise ValueError("BENCHMARK_DB_READINESS_IMMUTABLE_ARTIFACT_CONFLICT")
    else:
        with output_path.open("xb") as handle:
            handle.write(encoded)
    return hashlib.sha256(encoded).hexdigest().upper()


def execute_readiness(
    *,
    database_url: str,
    data_snapshot_id: UUID,
    output_path: Path,
    parent_liquidity_cost_policy_hash: str = (FROZEN_PARENT_LIQUIDITY_COST_POLICY_HASH),
    connect: Callable[..., Any] = psycopg.connect,
) -> tuple[dict[str, Any], str]:
    with connect(database_url, row_factory=dict_row) as connection:
        result = PostgresBenchmarkReadinessAdapterV21().inspect(
            connection,
            data_snapshot_id=data_snapshot_id,
            parent_liquidity_cost_policy_hash=(parent_liquidity_cost_policy_hash),
        )
    artifact = build_git_safe_artifact(result)
    file_sha256 = write_immutable_artifact(output_path, artifact)
    return artifact, file_sha256


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Generate a read-only PostgreSQL benchmark readiness diagnostic "
            "for one explicitly identified READY snapshot."
        )
    )
    parser.add_argument("--snapshot-id", type=UUID, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--parent-liquidity-cost-policy-hash",
        default=FROZEN_PARENT_LIQUIDITY_COST_POLICY_HASH,
    )
    args = parser.parse_args()
    artifact, file_sha256 = execute_readiness(
        database_url=_database_url(_environment()),
        data_snapshot_id=args.snapshot_id,
        output_path=args.output,
        parent_liquidity_cost_policy_hash=(args.parent_liquidity_cost_policy_hash),
    )
    print(f"Artifact: {args.output}")
    print(f"File SHA-256: {file_sha256}")
    print(f"Canonical hash: {artifact['artifactContentHash']}")
    print(f"Prospective enrollment allowed: {artifact['prospectiveEnrollmentAllowed']}")


if __name__ == "__main__":
    main()
