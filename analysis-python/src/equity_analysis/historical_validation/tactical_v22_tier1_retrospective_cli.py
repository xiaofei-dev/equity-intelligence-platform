from __future__ import annotations

import argparse
from pathlib import Path

from equity_analysis.historical_validation.slice_diagnostic_v22 import (
    write_immutable_json,
)
from equity_analysis.historical_validation.tactical_v22_tier1_retrospective import (
    run_tactical_v22_tier1_retrospective,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the offline Tactical v2.2 Tier-1 retrospective."
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(
            "docs/generated/"
            "tactical-v2-2-tier1-retrospective-manifest-v1.json"
        ),
    )
    arguments = parser.parse_args()
    root = Path(__file__).resolve().parents[4]
    _controlled, git_safe, _controlled_path = (
        run_tactical_v22_tier1_retrospective(
            repository_root=root,
            plan_path=root
            / "docs/generated/historical-dqv-v2-2-slice-plan.json",
            manifest_path=root
            / (
                "docs/generated/historical-yahoo-price-cache-"
                "20260729T-HISTORICAL-V1-R2-manifest.json"
            ),
            storage_root=root
            / "storage/historical-validation/yahoo-daily-price-cache-v1",
            universe_path=root
            / (
                "analysis-python/resources/universes/"
                "market-intelligence-closed-test-us-v1.json"
            ),
            classification_path=root
            / "analysis-python/tests/fixtures/provider_acceptance_universe_v3.json",
            freeze_path=root
            / "docs/generated/tactical-v2-2-model-freeze.json",
            controlled_output_root=root
            / "storage/historical-validation/tactical-v2-2-tier1",
        )
    )
    write_immutable_json(root / arguments.output, git_safe)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
