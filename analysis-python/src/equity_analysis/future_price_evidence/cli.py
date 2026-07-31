from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

from equity_analysis.future_price_evidence.preflight_v1 import (
    DEFAULT_OUTPUT,
    DEFAULT_PREREGISTRATION_SEAL,
    build_future_price_evidence_plan,
    build_future_price_evidence_preflight,
    write_immutable_preflight,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Build the offline-only Future Completed-Session Price Evidence v1 "
            "preflight. This command has no live execution option."
        )
    )
    parser.add_argument(
        "--preregistration-seal",
        type=Path,
        default=DEFAULT_PREREGISTRATION_SEAL,
    )
    parser.add_argument("--target-session", type=date.fromisoformat)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    plan = build_future_price_evidence_plan(
        preregistration_seal_path=args.preregistration_seal,
        target_session=args.target_session,
    )
    artifact = build_future_price_evidence_preflight(plan)
    file_sha256 = write_immutable_preflight(args.output, artifact)
    print(f"Artifact: {args.output}")
    print(f"File SHA-256: {file_sha256}")
    print(f"Canonical hash: {artifact['artifactContentHash']}")
    print("Network requests executed: 0")


if __name__ == "__main__":
    main()
