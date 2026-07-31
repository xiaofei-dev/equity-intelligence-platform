from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

from equity_analysis.forward_validation.preregistration_seal_v22 import (
    seal_or_verify_preregistrations_v22,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Seal or exactly verify the offline Forward benchmark v2.2 "
            "feasibility correction and data-pending preregistration."
        )
    )
    parser.add_argument("--repository-root", type=Path, required=True)
    args = parser.parse_args()
    repository_root = args.repository_root.resolve()
    bundle = seal_or_verify_preregistrations_v22(
        repository_root=repository_root
    )
    print(f"Rule frozen at: {bundle.benchmark.rule_frozen_at.isoformat()}")
    print(f"Registered at: {bundle.benchmark.registered_at.isoformat()}")
    print(
        "Current VALUE/QUALITY cache readiness: "
        f"{bundle.benchmark.current_cache_value_ready_count}/"
        f"{bundle.benchmark.current_cache_quality_ready_count}/44"
    )
    print(f"Data state: {bundle.benchmark.current_data_state}")
    print(
        "Future decision must be strictly after: "
        f"{bundle.seal.future_decision_must_be_strictly_after.isoformat()}"
    )
    print(f"Seal canonical hash: {bundle.seal.seal_content_hash}")
    for path in (
        "docs/generated/forward-benchmark-v2-2-feasibility.json",
        "docs/generated/forward-benchmark-candidate-policy-v2-2.json",
        "docs/generated/forward-benchmark-external-reference-universe-v2-2.json",
        "docs/generated/forward-benchmark-v2-2-data-preflight.json",
        "docs/generated/forward-benchmark-preregistration-v2-2.json",
        "docs/generated/forward-preregistration-seal-v2-2.json",
    ):
        artifact_path = repository_root / path
        file_hash = hashlib.sha256(artifact_path.read_bytes()).hexdigest().upper()
        print(f"{path}: {file_hash}")


if __name__ == "__main__":
    main()
