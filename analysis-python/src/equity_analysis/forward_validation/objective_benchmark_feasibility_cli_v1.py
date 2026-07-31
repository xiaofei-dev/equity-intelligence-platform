from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import psycopg

from equity_analysis.forward_validation.objective_benchmark_feasibility_v1 import (
    build_objective_benchmark_feasibility_artifact,
    inspect_objective_database,
)
from equity_analysis.provider_validation.execution_safety import (
    repository_root_env_path,
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
    explicit = os.getenv("ANALYTICS_DATABASE_URL") or environment.get(
        "ANALYTICS_DATABASE_URL",
        "",
    )
    if explicit:
        return explicit
    required = (
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
        "POSTGRES_PORT",
        "POSTGRES_DB",
    )
    if any(not environment.get(key) for key in required):
        raise SystemExit(
            "ANALYTICS_DATABASE_URL or local PostgreSQL settings are required"
        )
    return "postgresql://{}:{}@localhost:{}/{}".format(
        environment["POSTGRES_USER"],
        environment["POSTGRES_PASSWORD"],
        environment["POSTGRES_PORT"],
        environment["POSTGRES_DB"],
    )


def _existing_evaluated_at(output_path: Path) -> datetime | None:
    if not output_path.exists():
        return None
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    raw = payload.get("evaluatedAt")
    if not isinstance(raw, str):
        raise ValueError("OBJECTIVE_FEASIBILITY_EXISTING_ARTIFACT_INVALID")
    value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("OBJECTIVE_FEASIBILITY_EXISTING_TIMESTAMP_INVALID")
    return value.astimezone(UTC)


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
    ).encode("utf-8")
    if output_path.exists():
        if output_path.read_bytes() != encoded:
            raise ValueError("OBJECTIVE_FEASIBILITY_IMMUTABLE_ARTIFACT_CONFLICT")
    else:
        with output_path.open("xb") as handle:
            handle.write(encoded)
    return hashlib.sha256(encoded).hexdigest().upper()


def execute_audit(
    *,
    database_url: str,
    data_snapshot_id: UUID,
    repository_root: Path,
    output_path: Path,
    evaluated_at: datetime | None = None,
    connect: Callable[..., Any] = psycopg.connect,
) -> tuple[dict[str, Any], str]:
    resolved_evaluated_at = (
        evaluated_at
        or _existing_evaluated_at(output_path)
        or datetime.now(UTC)
    )
    with connect(database_url) as connection:
        connection.read_only = True
        inventory = inspect_objective_database(
            connection,
            data_snapshot_id=data_snapshot_id,
        )
        connection.rollback()
    artifact = build_objective_benchmark_feasibility_artifact(
        repository_root=repository_root,
        database=inventory,
        evaluated_at=resolved_evaluated_at,
    )
    file_sha256 = write_immutable_artifact(output_path, artifact)
    return artifact, file_sha256


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Generate a read-only Objective benchmark coverage and lineage "
            "feasibility audit for one explicitly selected data snapshot."
        )
    )
    parser.add_argument("--snapshot-id", type=UUID, required=True)
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    artifact, file_sha256 = execute_audit(
        database_url=_database_url(_environment()),
        data_snapshot_id=args.snapshot_id,
        repository_root=args.repository_root.resolve(),
        output_path=args.output,
    )
    print(f"Artifact: {args.output}")
    print(f"File SHA-256: {file_sha256}")
    print(f"Canonical hash: {artifact['artifactContentHash']}")
    print(
        "PURE_QUALITY formal/diagnostic/required: "
        f"{artifact['pureQuality']['formalCandidateCount']}/"
        f"{artifact['pureQuality']['diagnosticPreRegistrationCandidateCount']}/"
        f"{artifact['pureQuality']['minimumRequiredCount']}"
    )
    print(
        "PURE_VALUE formal/diagnostic/required: "
        f"{artifact['pureValue']['formalCandidateCount']}/"
        f"{artifact['pureValue']['diagnosticInputReadyCount']}/"
        f"{artifact['pureValue']['minimumRequiredCount']}"
    )


if __name__ == "__main__":
    main()
