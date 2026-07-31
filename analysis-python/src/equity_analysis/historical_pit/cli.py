from __future__ import annotations

import argparse
import os
from pathlib import Path
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

from equity_analysis.historical_pit.feasibility_v1 import (
    DEFAULT_SEED,
    audit_historical_pit_feasibility,
    write_immutable_artifact,
)
from equity_analysis.provider_validation.execution_safety import (
    repository_root_env_path,
)

DEFAULT_SNAPSHOT_ID = UUID("beaa9952-9852-4088-9dc3-92047824414b")


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


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Run the strictly offline, read-only Historical PIT Slice Feasibility Audit v1."
        )
    )
    parser.add_argument(
        "--snapshot-id",
        type=UUID,
        default=DEFAULT_SNAPSHOT_ID,
    )
    parser.add_argument(
        "--price-manifest",
        type=Path,
        default=Path(
            "docs/generated/historical-yahoo-price-cache-20260729T-HISTORICAL-V1-R2-manifest.json"
        ),
    )
    parser.add_argument(
        "--scoring-preflight",
        type=Path,
        default=Path("docs/generated/scoring-input-v3-coverage-preflight-v1.json"),
    )
    parser.add_argument(
        "--scoring-v4-manifest",
        type=Path,
        default=Path("docs/generated/scoring-input-v4-sec-offline-manifest-v2.json"),
    )
    parser.add_argument(
        "--long-readiness",
        type=Path,
        default=Path("docs/generated/long-horizon-v1-1-historical-readiness-2026-07-29.json"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("docs/generated/historical-pit-slice-feasibility-audit-v1.json"),
    )
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    args = parser.parse_args()
    repository_root = Path.cwd()
    with psycopg.connect(
        _database_url(_environment()),
        row_factory=dict_row,
    ) as connection:
        artifact = audit_historical_pit_feasibility(
            connection,
            repository_root=repository_root,
            data_snapshot_id=args.snapshot_id,
            price_manifest_path=args.price_manifest,
            scoring_preflight_path=args.scoring_preflight,
            scoring_v4_manifest_path=args.scoring_v4_manifest,
            long_readiness_path=args.long_readiness,
            seed=args.seed,
        )
    file_sha256 = write_immutable_artifact(args.output, artifact)
    print(f"Artifact: {args.output}")
    print(f"File SHA-256: {file_sha256}")
    print(f"Canonical hash: {artifact['artifactContentHash']}")
    print(f"Formal PIT eligible slices: {artifact['summary']['formalPitEligibleSliceCount']}")


if __name__ == "__main__":
    main()
