from __future__ import annotations

import argparse
from pathlib import Path

from equity_analysis.historical_validation.diagnostic_closeout_v1 import (
    CloseoutPaths,
    build_historical_diagnostic_closeout,
    write_immutable_closeout,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Close historical evidence as diagnostic-only without running "
            "models, reading a database, or making provider requests."
        )
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(
            "docs/generated/historical-diagnostic-evidence-closeout-v1.json"
        ),
    )
    args = parser.parse_args()
    repository_root = Path.cwd()
    artifact = build_historical_diagnostic_closeout(
        repository_root,
        paths=CloseoutPaths(),
    )
    file_sha256 = write_immutable_closeout(args.output, artifact)
    print(f"Artifact: {args.output}")
    print(f"File SHA-256: {file_sha256}")
    print(f"Canonical hash: {artifact['artifactContentHash']}")
    print(f"Terminal status: {artifact['terminalStatus']}")


if __name__ == "__main__":
    main()
