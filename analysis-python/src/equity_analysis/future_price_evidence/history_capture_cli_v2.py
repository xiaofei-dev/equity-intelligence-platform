from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from equity_analysis.future_price_evidence.history_capture_runner_v2 import (
    DATABASE_CONFIRMATION,
    LIVE_CONFIRMATION,
    CalendarReviewConfirmation,
    FuturePriceHistoryCaptureRunnerV2,
    build_ready_for_execution_status,
)
from equity_analysis.future_price_evidence.history_preflight_v2 import (
    DEFAULT_HISTORY_PREFLIGHT_OUTPUT,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Inspect or execute the bounded Future Completed-Session Price "
            "History Capture v2 plan."
        )
    )
    parser.add_argument(
        "--preflight",
        type=Path,
        default=DEFAULT_HISTORY_PREFLIGHT_OUTPUT,
    )
    parser.add_argument("--execute-live", action="store_true")
    parser.add_argument("--confirm-live")
    parser.add_argument("--reviewed-by")
    parser.add_argument("--confirm-nyse-session", action="store_true")
    parser.add_argument("--confirm-nyse-close", action="store_true")
    parser.add_argument("--confirm-nasdaq-session", action="store_true")
    parser.add_argument("--confirm-nasdaq-close", action="store_true")
    parser.add_argument("--run-id")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument(
        "--write-database",
        action="store_true",
        help=(
            "Reserved for an embedded caller that supplies the versioned "
            "persistence gateway; the standalone CLI refuses this flag."
        ),
    )
    parser.add_argument("--confirm-database")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.execute_live:
        status = build_ready_for_execution_status(
            preflight_path=args.preflight,
            as_of=datetime.now(UTC),
        )
        print(json.dumps(status, indent=2, sort_keys=True))
        return 0
    if args.write_database:
        if args.confirm_database != DATABASE_CONFIRMATION:
            raise SystemExit("Database write confirmation is invalid.")
        raise SystemExit(
            "Standalone live capture never writes PostgreSQL. Use an embedded "
            "operations entry point with AdapterPersistenceGateway."
        )
    if args.confirm_live != LIVE_CONFIRMATION:
        raise SystemExit("Live confirmation is invalid.")
    if not args.reviewed_by:
        raise SystemExit("A named official-calendar reviewer is required.")
    review = CalendarReviewConfirmation(
        reviewed_by=args.reviewed_by,
        nyse_confirms_scheduled_session=args.confirm_nyse_session,
        nyse_confirms_close=args.confirm_nyse_close,
        nasdaq_confirms_scheduled_session=args.confirm_nasdaq_session,
        nasdaq_confirms_close=args.confirm_nasdaq_close,
    )
    result = FuturePriceHistoryCaptureRunnerV2(
        preflight_path=args.preflight,
    ).execute(
        review=review,
        network_enabled=True,
        live_confirmation=args.confirm_live,
        run_id=args.run_id,
        resume=args.resume,
    )
    print(
        json.dumps(
            {
                "runId": result.run_id,
                "state": result.state,
                "targetSession": result.target_session.isoformat(),
                "symbolCount": result.symbol_count,
                "readySymbolCount": result.ready_symbol_count,
                "physicalAttempts": result.physical_attempts,
                "configuredWeight": result.configured_weight,
                "reportPath": str(result.report_path),
                "reportSha256": result.report_sha256,
                "reportContentHash": result.report_content_hash,
                "controlledManifestPath": str(result.controlled_manifest_path),
                "controlledManifestSha256": result.controlled_manifest_sha256,
                "controlledManifestContentHash": (
                    result.controlled_manifest_content_hash
                ),
                "databaseReceiptCount": result.database_receipt_count,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
