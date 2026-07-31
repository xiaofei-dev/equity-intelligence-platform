from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from equity_analysis.historical_validation.long_horizon_tier1_retrospective import (
    build_long_horizon_tier1_retrospective,
    write_long_horizon_tier1_artifacts,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_OUTPUT = Path(
    "docs/generated/"
    "long-horizon-v1-1-tier1-retrospective-2026-07-30.json"
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Build the offline Long Horizon v1.1 Tier-1 price-outcome "
            "retrospective without executing the model."
        )
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
    )
    args = parser.parse_args(argv)
    controlled, artifact = build_long_horizon_tier1_retrospective(
        REPOSITORY_ROOT,
        generated_at=datetime(2026, 7, 30, 9, 30, tzinfo=UTC),
    )
    controlled_file_hash, artifact_file_hash = (
        write_long_horizon_tier1_artifacts(
            repository_root=REPOSITORY_ROOT,
            controlled=controlled,
            git_artifact=artifact,
            git_path=args.output,
        )
    )
    checked_in = json.loads(
        (REPOSITORY_ROOT / args.output).read_text(encoding="utf-8")
    )
    print(
        json.dumps(
            {
                "path": args.output.as_posix(),
                "fileSha256": artifact_file_hash,
                "artifactContentHash": checked_in["artifactContentHash"],
                "controlledFileSha256": controlled_file_hash,
                "controlledPayloadContentHash": checked_in[
                    "controlledPayloadContentHash"
                ],
                "status": checked_in["status"],
                "candidateCount": checked_in["candidateCount"],
                "modelDecisionCount": checked_in["modelDecisionCount"],
                "providerNetworkRequests": 0,
                "validatedClaimAllowed": False,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
