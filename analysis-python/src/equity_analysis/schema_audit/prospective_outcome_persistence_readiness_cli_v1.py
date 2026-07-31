from __future__ import annotations

import argparse
from pathlib import Path

from equity_analysis.schema_audit.prospective_outcome_persistence_readiness_v1 import (
    build_prospective_outcome_persistence_readiness_audit,
    write_immutable_audit,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Audit Forward DQV v2 PostgreSQL persistence readiness without "
            "network or database access."
        )
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(
            "docs/generated/"
            "prospective-outcome-persistence-readiness-audit-v1.json"
        ),
    )
    args = parser.parse_args()
    artifact = build_prospective_outcome_persistence_readiness_audit(
        Path.cwd()
    )
    file_hash = write_immutable_audit(args.output, artifact)
    print(f"Artifact: {args.output}")
    print(f"File SHA-256: {file_hash}")
    print(f"Canonical hash: {artifact['artifactContentHash']}")
    print(f"Status: {artifact['status']}")


if __name__ == "__main__":
    main()
