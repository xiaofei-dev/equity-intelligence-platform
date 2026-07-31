from __future__ import annotations

import argparse
from datetime import UTC, datetime
from pathlib import Path

from equity_analysis.historical_validation.long_horizon_tier2_pit_reconstruction import (
    build_long_horizon_tier2_pit_reconstruction,
    write_long_horizon_tier2_artifacts,
)

DEFAULT_OUTPUT = Path(
    "docs/generated/"
    "long-horizon-v1-1-tier2-pit-reconstruction-2026-07-30.json"
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Build the offline Long Horizon v1.1 Tier-2 PIT "
            "input-reconstruction evidence."
        )
    )
    parser.add_argument(
        "--repository-root",
        type=Path,
        default=Path.cwd(),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
    )
    parser.add_argument(
        "--generated-at",
        default="2026-07-30T16:00:00Z",
    )
    args = parser.parse_args()
    generated_at = datetime.fromisoformat(
        str(args.generated_at).replace("Z", "+00:00")
    ).astimezone(UTC)
    root = args.repository_root.resolve()
    controlled, git_artifact = (
        build_long_horizon_tier2_pit_reconstruction(
            root,
            generated_at=generated_at,
        )
    )
    controlled_sha, artifact_sha = write_long_horizon_tier2_artifacts(
        repository_root=root,
        controlled=controlled,
        git_artifact=git_artifact,
        git_path=args.output,
    )
    print(f"controlled={controlled_sha}")
    print(f"artifact={artifact_sha}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
