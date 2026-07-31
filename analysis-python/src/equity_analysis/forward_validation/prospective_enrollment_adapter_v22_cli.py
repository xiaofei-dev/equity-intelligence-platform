from __future__ import annotations

import argparse
import json
from pathlib import Path

from equity_analysis.forward_validation.prospective_activation_v20 import (
    V20_ACCEPTANCE_PATH,
    build_prospective_enrollment_preflight_v20,
    load_canonical_artifact,
    write_immutable_artifact,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_OUTPUT = (
    REPOSITORY_ROOT
    / "docs/generated/prospective-enrollment-adapter-v2-2-v20-preflight-v1.json"
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Build the repository-current prospective enrollment v2.2 "
            "preflight without database access."
        )
    )
    parser.add_argument(
        "--write-blocked-preflight",
        action="store_true",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    if not args.write_blocked_preflight:
        parser.error("--write-blocked-preflight is required")

    activation = load_canonical_artifact(
        REPOSITORY_ROOT / V20_ACCEPTANCE_PATH
    )
    artifact = build_prospective_enrollment_preflight_v20(
        REPOSITORY_ROOT,
        activation=activation,
    )
    if artifact["status"] != "BLOCKED_BY_TIME_OR_EVIDENCE":
        raise RuntimeError(
            "Repository-current preflight unexpectedly became enrollment-ready"
        )
    file_hash = write_immutable_artifact(
        args.output,
        artifact,
    )
    print(
        json.dumps(
            {
                "path": str(args.output),
                "fileSha256": file_hash,
                "artifactContentHash": artifact["artifactContentHash"],
                "status": artifact["status"],
                "blockedReasons": artifact["blockedReasons"],
                "databaseWritesExecuted": 0,
                "providerNetworkRequestsExecuted": 0,
                "enrollmentExecuted": False,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
