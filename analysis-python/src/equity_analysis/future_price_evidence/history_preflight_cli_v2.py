from __future__ import annotations

import argparse
import hashlib
import json
from datetime import date
from pathlib import Path

from equity_analysis.daily_refresh.universe import (
    DEFAULT_UNIVERSE_PATH,
    load_closed_test_universe,
)
from equity_analysis.future_price_evidence.history_preflight_v2 import (
    DEFAULT_HISTORY_PREFLIGHT_OUTPUT,
    build_future_price_history_plan_v2,
    build_future_price_history_preflight_v2,
    write_immutable_future_price_history_preflight_v2,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Write the immutable offline future price history v2 preflight."
    )
    parser.add_argument(
        "--target-session",
        type=date.fromisoformat,
        default=date(2026, 7, 30),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_HISTORY_PREFLIGHT_OUTPUT,
    )
    args = parser.parse_args()

    universe = load_closed_test_universe()
    plan = build_future_price_history_plan_v2(
        base_symbols=universe.refreshable_symbols,
        target_session=args.target_session,
        universe_version=universe.version,
        universe_file_sha256=hashlib.sha256(
            DEFAULT_UNIVERSE_PATH.read_bytes()
        ).hexdigest(),
    )
    artifact = build_future_price_history_preflight_v2(plan)
    file_sha256 = write_immutable_future_price_history_preflight_v2(
        args.output,
        artifact,
    )
    print(
        json.dumps(
            {
                "path": str(args.output),
                "fileSha256": file_sha256,
                "artifactContentHash": artifact["artifactContentHash"],
                "status": artifact["status"],
                "providerNetworkRequests": 0,
                "databaseWrites": 0,
                "scoresOrRanksComputed": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
