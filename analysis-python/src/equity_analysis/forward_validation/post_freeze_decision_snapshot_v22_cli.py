from __future__ import annotations

import argparse
import json
from pathlib import Path

from equity_analysis.forward_validation.post_freeze_decision_snapshot_v22 import (
    build_git_safe_post_freeze_manifest_v22,
    build_post_freeze_contract_fixture_v22,
    write_immutable_git_safe_post_freeze_manifest_v22,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_FIXTURE_PATH = (
    REPOSITORY_ROOT
    / "docs/generated/"
    "post-freeze-decision-snapshot-v2-2-contract-fixture-v2.json"
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build the offline post-freeze decision snapshot v2.2 fixture."
    )
    parser.add_argument(
        "--write-contract-fixture",
        action="store_true",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_FIXTURE_PATH)
    args = parser.parse_args(argv)
    if not args.write_contract_fixture:
        parser.error("--write-contract-fixture is required")
    snapshot = build_post_freeze_contract_fixture_v22(
        repository_root=REPOSITORY_ROOT
    )
    manifest = build_git_safe_post_freeze_manifest_v22(snapshot)
    file_hash = write_immutable_git_safe_post_freeze_manifest_v22(
        args.output,
        manifest,
    )
    print(
        json.dumps(
            {
                "path": str(args.output),
                "fileSha256": file_hash,
                "artifactContentHash": manifest["artifactContentHash"],
                "securityCount": manifest["populationCount"],
                "providerNetworkRequests": 0,
                "databaseWrites": 0,
                "scoresOrRanksComputed": False,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
