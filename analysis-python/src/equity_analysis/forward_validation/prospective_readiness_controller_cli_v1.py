from __future__ import annotations

import argparse
from pathlib import Path

from equity_analysis.forward_validation.prospective_readiness_controller_v1 import (
    evaluate_prospective_readiness,
    load_verified_artifact,
    write_immutable_readiness,
)

DEFAULT_OUTPUT = Path("docs/generated/prospective-readiness-and-enrollment-controller-v1.json")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Evaluate prospective enrollment readiness offline without enrolling."
    )
    parser.add_argument(
        "--parent-preregistration",
        type=Path,
        default=Path("docs/generated/forward-dqv-preregistration-v2.json"),
    )
    parser.add_argument(
        "--benchmark-preregistration",
        type=Path,
        default=Path("docs/generated/forward-benchmark-preregistration-v2-1.json"),
    )
    parser.add_argument(
        "--seal",
        type=Path,
        default=Path("docs/generated/forward-preregistration-seal-v2-1.json"),
    )
    parser.add_argument(
        "--decision",
        type=Path,
        default=Path("docs/generated/forward-v2-decision-snapshot-20260729T025708Z-beaa9952.json"),
    )
    parser.add_argument(
        "--future-price-execution",
        type=Path,
        default=Path("docs/generated/future-completed-session-price-evidence-preflight-v1.json"),
    )
    parser.add_argument(
        "--benchmark-manifest",
        type=Path,
        default=Path("docs/generated/forward-benchmark-db-readiness-v2-1-beaa9952.json"),
    )
    parser.add_argument("--objective-coverage-audit", type=Path)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    benchmark = load_verified_artifact(args.benchmark_manifest)
    artifact = evaluate_prospective_readiness(
        parent_preregistration=load_verified_artifact(args.parent_preregistration),
        benchmark_preregistration=load_verified_artifact(args.benchmark_preregistration),
        preregistration_seal=load_verified_artifact(args.seal),
        decision_manifest=load_verified_artifact(args.decision),
        future_price_execution=load_verified_artifact(args.future_price_execution),
        benchmark_manifest=benchmark,
        benchmark_bundle=benchmark,
        objective_coverage_audit=(
            load_verified_artifact(args.objective_coverage_audit)
            if args.objective_coverage_audit
            else None
        ),
    )
    file_sha256 = write_immutable_readiness(args.output, artifact)
    print(f"Artifact: {args.output}")
    print(f"File SHA-256: {file_sha256}")
    print(f"Canonical hash: {artifact['artifactContentHash']}")
    print(f"Status: {artifact['status']}")
    print(f"Blocked reasons: {len(artifact['blockedReasons'])}")
    print("Enrollment executed: false")


if __name__ == "__main__":
    main()
