from __future__ import annotations

import argparse
import json
from pathlib import Path

from equity_analysis.schema_audit.end_to_end_validation_gap_v1 import (
    build_end_to_end_validation_gap_audit,
    verify_end_to_end_validation_gap_audit,
    write_or_verify_gap_audit,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_OUTPUT = (
    REPOSITORY_ROOT / "docs/generated/end-to-end-validation-completion-gap-audit-v1.json"
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=("Build the strict offline end-to-end validation completion gap audit.")
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)

    artifact = build_end_to_end_validation_gap_audit(REPOSITORY_ROOT)
    verify_end_to_end_validation_gap_audit(REPOSITORY_ROOT, artifact)
    file_hash = write_or_verify_gap_audit(args.output, artifact)
    print(
        json.dumps(
            {
                "path": str(args.output),
                "fileSha256": file_hash,
                "artifactContentHash": artifact["artifactContentHash"],
                "overallStatus": artifact["overallStatus"],
                "providerNetworkRequests": 0,
                "databaseWrites": 0,
                "scoresOrRanksComputed": False,
                "enrollmentExecuted": False,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
