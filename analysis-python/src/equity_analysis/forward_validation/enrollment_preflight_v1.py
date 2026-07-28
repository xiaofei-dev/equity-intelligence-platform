from __future__ import annotations

import argparse
import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from equity_analysis.forward_validation.preregistration_v1 import (
    SECTOR_BENCHMARKS,
    bucket_preview,
)
from equity_analysis.provider_validation.expansion_gate import (
    canonical_hash,
    write_immutable_json,
)

PREFLIGHT_VERSION = "forward-enrollment-preflight-v1.0.0"
CALENDAR_VERSION = "XNYS-CALENDAR-v1.0.0"
CALENDAR_SOURCE = "https://www.nyse.com/markets/hours-calendars"
TREASURY_SOURCE = (
    "https://home.treasury.gov/resource-center/data-chart-center/"
    "interest-rates/TextView?type=daily_treasury_yield_curve"
)

NYSE_2026_FULL_HOLIDAYS = frozenset(
    {
        date(2026, 1, 1),
        date(2026, 1, 19),
        date(2026, 2, 16),
        date(2026, 4, 3),
        date(2026, 5, 25),
        date(2026, 6, 19),
        date(2026, 7, 3),
        date(2026, 9, 7),
        date(2026, 11, 26),
        date(2026, 12, 25),
    }
)


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"), parse_float=Decimal)


def is_regular_weekday_session_candidate(value: date) -> bool:
    return value.weekday() < 5 and value not in NYSE_2026_FULL_HOLIDAYS


def build_enrollment_preflight(
    *,
    repository_root: Path,
    preregistration_path: Path,
    algorithm_gate_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    preregistration = _load(preregistration_path)
    gate = _load(algorithm_gate_path)
    if preregistration["status"] != "PREREGISTERED_PENDING_ENROLLMENT_GATES":
        raise ValueError("FORWARD_PREREGISTRATION_NOT_PENDING")
    if (
        preregistration["sourceAlgorithmGate"]["artifactContentHash"]
        != gate["artifactContentHash"]
    ):
        raise ValueError("ALGORITHM_GATE_HASH_MISMATCH")
    candidate_date = date.fromisoformat(
        preregistration["enrollmentRule"]["calendarDayCandidate"]
    )
    top, bottom = bucket_preview(gate["securities"])
    preview = [*top, *bottom]
    sectors = sorted({item["sector"] for item in preview})
    missing_mappings = [
        sector for sector in sectors if sector not in SECTOR_BENCHMARKS
    ]
    benchmark_symbols = sorted(
        {"SPY", *(SECTOR_BENCHMARKS[sector] for sector in sectors)}
    )
    candidate_symbols = sorted({item["symbol"] for item in preview})
    statuses = {
        "calendarDateRule": (
            "PASS"
            if is_regular_weekday_session_candidate(candidate_date)
            and candidate_date.weekday() == 4
            else "BLOCKED"
        ),
        "sectorBenchmarkMapping": "PASS" if not missing_mappings else "BLOCKED",
        "officialPublishedCalendar": "PASS",
        "completedRegularSession": "PENDING_AT_ENROLLMENT",
        "freshWeeklyQcRun": "PENDING_AT_WEEKLY_CLOSE",
        "candidatePriceAndActionRefresh": "PENDING_AT_WEEKLY_CLOSE",
        "benchmarkPriceAndActionRefresh": "PENDING_AT_WEEKLY_CLOSE",
        "threeMonthTreasuryRate": "PENDING_AT_WEEKLY_CLOSE",
        "identityDelistingAndUnresolvedActionReview": "PENDING_AT_WEEKLY_CLOSE",
    }
    ready = all(value == "PASS" for value in statuses.values())
    artifact = {
        "artifactType": "FORWARD_ENROLLMENT_OPERATIONAL_PREFLIGHT",
        "schemaVersion": PREFLIGHT_VERSION,
        "experimentId": preregistration["experimentId"],
        "mode": "DRY_RUN",
        "candidateEnrollmentDate": candidate_date.isoformat(),
        "calendarVersion": CALENDAR_VERSION,
        "calendarSource": CALENDAR_SOURCE,
        "calendarSourceReviewedAt": "2026-07-28",
        "calendarRuleStatus": statuses["calendarDateRule"],
        "officialCalendarConfirmationRequiredAtEnrollment": True,
        "previewSecurityCount": len(candidate_symbols),
        "previewTopCount": len(top),
        "previewBottomCount": len(bottom),
        "previewSymbolsHash": canonical_hash(candidate_symbols),
        "coveredSectors": sectors,
        "sectorBenchmarkMapVersion": preregistration[
            "sectorBenchmarkMapVersion"
        ],
        "benchmarkSymbols": benchmark_symbols,
        "missingSectorMappings": missing_mappings,
        "cashRateContract": {
            "version": preregistration["cashReturnVersion"],
            "source": TREASURY_SOURCE,
            "series": "Daily Treasury Par Yield Curve Rate - 3-Month",
            "availabilityRule": (
                "Use only an observation published and ingested before the "
                "policy decision cutoff; missing remains unavailable."
            ),
        },
        "weeklyCloseExecutionPlan": {
            "step1": (
                "Confirm the candidate date is an actual completed regular "
                "US trading session."
            ),
            "step2": (
                "Refresh and seal the 216-security current QC source universe; "
                "do not reuse the Tuesday rank as a Friday signal."
            ),
            "step3": (
                "Refresh unadjusted closes, splits, dividends, identity and "
                "tradability for the newly selected top/bottom securities."
            ),
            "step4": (
                "Refresh SPY and all required sector ETF prices and actions."
            ),
            "step5": (
                "Store the latest cutoff-safe 3-month Treasury rate or stop "
                "with CASH_RATE_UNAVAILABLE."
            ),
            "step6": (
                "Seal signals, input hashes and all six counterfactual arms; "
                "first fills occur no earlier than the next trading close."
            ),
        },
        "stopConditions": [
            "CALENDAR_SESSION_NOT_CONFIRMED",
            "FRESH_QC_RUN_NOT_SUCCEEDED",
            "BENCHMARK_OR_SECURITY_PRICE_UNAVAILABLE",
            "CORPORATE_ACTION_UNRESOLVED",
            "CASH_RATE_UNAVAILABLE",
            "INPUT_HASH_OR_IDENTITY_CONFLICT",
        ],
        "gateStatuses": statuses,
        "enrollmentReady": ready,
        "signalsEnrolled": 0,
        "networkRequestsExecuted": False,
        "databaseWritesExecuted": False,
        "automaticTradingAuthorized": False,
    }
    artifact["artifactContentHash"] = canonical_hash(artifact)
    if output_path.exists():
        existing = _load(output_path)
        if existing != artifact:
            raise ValueError("FORWARD_ENROLLMENT_PREFLIGHT_CONFLICT")
    else:
        write_immutable_json(output_path, artifact)
    return artifact


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build the offline Forward v1 enrollment preflight."
    )
    parser.add_argument(
        "--preregistration",
        type=Path,
        default=Path(
            "docs/generated/forward-decision-quality-preregistration-v1.json"
        ),
    )
    parser.add_argument(
        "--algorithm-gate",
        type=Path,
        default=Path(
            "docs/generated/objective-rating-v1-current-snapshot-algorithm-gate-v1.json"
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(
            "docs/generated/forward-enrollment-operational-preflight-v1.json"
        ),
    )
    arguments = parser.parse_args()
    root = Path.cwd().resolve()
    artifact = build_enrollment_preflight(
        repository_root=root,
        preregistration_path=(root / arguments.preregistration).resolve(),
        algorithm_gate_path=(root / arguments.algorithm_gate).resolve(),
        output_path=(root / arguments.output).resolve(),
    )
    print(
        json.dumps(
            {
                "candidateDate": artifact["candidateEnrollmentDate"],
                "calendarRule": artifact["calendarRuleStatus"],
                "benchmarks": artifact["benchmarkSymbols"],
                "enrollmentReady": artifact["enrollmentReady"],
            },
            separators=(",", ":"),
        )
    )


if __name__ == "__main__":
    main()
