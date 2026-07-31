from __future__ import annotations

import argparse
import json
from pathlib import Path

from equity_analysis.historical_validation.slice_diagnostic_v22 import (
    build_sealed_slice_plan,
    run_sealed_historical_diagnostic,
    write_immutable_json,
)


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[4]


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Seal and run the strictly offline historical DQV v2.2 diagnostic"
        )
    )
    parser.add_argument("--repository-root", type=Path)
    arguments = parser.parse_args()
    root = (arguments.repository_root or _repository_root()).resolve()
    manifest_path = (
        root
        / "docs/generated/"
        "historical-yahoo-price-cache-20260729T-HISTORICAL-V1-R2-manifest.json"
    )
    storage_root = (
        root / "storage/historical-validation/yahoo-daily-price-cache-v1"
    )
    plan_path = (
        root / "docs/generated/historical-dqv-v2-2-slice-plan.json"
    )
    closeout_path = (
        root
        / "docs/generated/"
        "historical-dqv-v2-2-slice-diagnostic-closeout.json"
    )
    plan = build_sealed_slice_plan(
        manifest_path=manifest_path,
        storage_root=storage_root,
    )
    plan_file_hash = write_immutable_json(plan_path, plan)
    _controlled, closeout, controlled_path = (
        run_sealed_historical_diagnostic(
            plan_path=plan_path,
            manifest_path=manifest_path,
            storage_root=storage_root,
            universe_path=(
                root
                / "analysis-python/resources/universes/"
                "market-intelligence-closed-test-us-v1.json"
            ),
            tactical_freeze_path=(
                root / "docs/generated/tactical-v2-2-model-freeze.json"
            ),
            long_horizon_freeze_path=(
                root / "docs/generated/long-horizon-v1-1-model-freeze.json"
            ),
            protocol_fixture_path=(
                root
                / "docs/generated/"
                "forward-decision-quality-validation-v2-2-protocol-fixture.json"
            ),
            controlled_output_root=(
                root / "storage/historical-validation/dqv-v2-2"
            ),
        )
    )
    closeout_file_hash = write_immutable_json(closeout_path, closeout)
    print(
        json.dumps(
            {
                "status": closeout["terminalStatus"],
                "planPath": plan_path.as_posix(),
                "planFileSha256": plan_file_hash,
                "planArtifactContentHash": plan["artifactContentHash"],
                "controlledPath": controlled_path.as_posix(),
                "controlledFileSha256": closeout["controlledResult"][
                    "fileSha256"
                ],
                "closeoutPath": closeout_path.as_posix(),
                "closeoutFileSha256": closeout_file_hash,
                "closeoutArtifactContentHash": closeout[
                    "artifactContentHash"
                ],
                "summary": closeout["sliceSummary"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
