from __future__ import annotations

import argparse
from pathlib import Path

from equity_analysis.historical_validation.provider_backtest_coverage_v1 import (
    build_provider_backtest_coverage,
    write_coverage,
)
from equity_analysis.historical_validation.provider_backtest_preflight_v1 import (
    REPOSITORY_ROOT,
)

DEFAULT_OUTPUT = Path(
    "docs/generated/practical-long-horizon-provider-backtest-coverage-v1-3.json"
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Verify the practical Long Horizon controlled data canary and full scope."
        )
    )
    parser.add_argument(
        "--repository-root",
        type=Path,
        default=REPOSITORY_ROOT,
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    repository_root = args.repository_root.resolve()
    output = args.output
    if not output.is_absolute():
        output = repository_root / output
    artifact = build_provider_backtest_coverage(
        repository_root=repository_root
    )
    write_coverage(output, artifact)
    print(output)
    print(artifact["artifactContentHash"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
