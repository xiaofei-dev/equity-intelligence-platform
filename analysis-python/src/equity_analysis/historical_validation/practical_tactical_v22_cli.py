from __future__ import annotations

import argparse
from pathlib import Path

from equity_analysis.historical_validation.practical_tactical_v22 import (
    run_practical_tactical_v22_backtest,
)
from equity_analysis.historical_validation.slice_diagnostic_v22 import (
    write_immutable_json,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Evaluate real frozen Tactical v2.2 historical scores with the "
            "Practical Tier-1 benchmark contract."
        )
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(
            "docs/generated/practical-tactical-v2-2-backtest-manifest-v1.json"
        ),
    )
    arguments = parser.parse_args()
    root = Path(__file__).resolve().parents[4]
    _controlled, git_safe, _controlled_path = (
        run_practical_tactical_v22_backtest(
            repository_root=root,
            retrospective_path=root
            / "docs/generated/"
            "tactical-v2-2-tier1-retrospective-manifest-v1.json",
            yahoo_storage_root=root
            / "storage/historical-validation/yahoo-daily-price-cache-v1",
            controlled_output_root=root
            / "storage/historical-validation/practical-tactical-v2-2",
        )
    )
    output = arguments.output
    if not output.is_absolute():
        output = root / output
    write_immutable_json(output, git_safe)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
