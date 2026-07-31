from __future__ import annotations

import argparse
from pathlib import Path

from equity_analysis.historical_validation.provider_backtest_preflight_v1 import (
    REPOSITORY_ROOT,
    build_provider_backtest_preflight,
    write_preflight,
)

DEFAULT_OUTPUT = Path(
    "docs/generated/practical-long-horizon-provider-backtest-preflight-v1.json"
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Build the no-network practical Long Horizon backtest provider preflight."
        )
    )
    parser.add_argument(
        "--repository-root",
        type=Path,
        default=REPOSITORY_ROOT,
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
    )
    args = parser.parse_args()
    repository_root = args.repository_root.resolve()
    output = args.output
    if not output.is_absolute():
        output = repository_root / output
    payload = build_provider_backtest_preflight(
        repository_root=repository_root
    )
    write_preflight(output, payload)
    print(output)
    print(payload["artifactContentHash"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
