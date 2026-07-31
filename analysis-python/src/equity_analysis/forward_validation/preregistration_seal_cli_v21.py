from __future__ import annotations

import argparse
import json
from pathlib import Path

from equity_analysis.forward_validation.preregistration_seal_v21 import (
    BENCHMARK_ARTIFACT_RELATIVE_PATH,
    PARENT_ARTIFACT_RELATIVE_PATH,
    SEAL_ARTIFACT_RELATIVE_PATH,
    seal_or_verify_preregistrations,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Seal or exactly verify the offline Forward DQV v2 and benchmark "
            "v2.1 preregistrations."
        )
    )
    parser.add_argument(
        "--repository-root",
        type=Path,
        default=Path(__file__).resolve().parents[4],
    )
    return parser


def main() -> int:
    args = _parser().parse_args()
    repository_root = args.repository_root.resolve()
    bundle = seal_or_verify_preregistrations(repository_root=repository_root)
    print(
        json.dumps(
            {
                "status": "SEALED_AND_VERIFIED",
                "parentArtifact": PARENT_ARTIFACT_RELATIVE_PATH.as_posix(),
                "parentRegisteredAt": bundle.parent.registered_at.isoformat(),
                "parentContentHash": (
                    bundle.parent.preregistration_content_hash
                ),
                "benchmarkArtifact": (
                    BENCHMARK_ARTIFACT_RELATIVE_PATH.as_posix()
                ),
                "benchmarkRegisteredAt": (
                    bundle.benchmark.registered_at.isoformat()
                ),
                "benchmarkContentHash": (
                    bundle.benchmark.preregistration_content_hash
                ),
                "sealArtifact": SEAL_ARTIFACT_RELATIVE_PATH.as_posix(),
                "sealContentHash": bundle.seal.seal_content_hash,
                "legacyDecisionEligible": False,
                "providerNetworkRequests": 0,
                "databaseWriteExecuted": False,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
