from __future__ import annotations

import argparse
from pathlib import Path

from equity_analysis.historical_validation.slice_diagnostic_v22 import (
    write_immutable_json,
)
from equity_analysis.historical_validation.tactical_v22_tier1_statistical_closeout import (
    build_tactical_v22_tier1_statistical_closeout,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Build the offline Tactical v2.2 Tier-1 statistical closeout."
        )
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(
            "docs/generated/"
            "tactical-v2-2-tier1-statistical-closeout-2026-07-30.json"
        ),
    )
    arguments = parser.parse_args()
    root = Path(__file__).resolve().parents[4]
    artifact = build_tactical_v22_tier1_statistical_closeout(
        repository_root=root,
        git_safe_path=root
        / (
            "docs/generated/"
            "tactical-v2-2-tier1-retrospective-manifest-v1.json"
        ),
        controlled_path=root
        / (
            "storage/historical-validation/tactical-v2-2-tier1/"
            "f8bd49c75ea236a3b7857d4f850a2c17599e8def62de4c506eee7e028b00f287"
            ".json"
        ),
    )
    write_immutable_json(root / arguments.output, artifact)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
