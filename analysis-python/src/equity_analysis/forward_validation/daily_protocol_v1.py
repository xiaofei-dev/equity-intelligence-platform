from __future__ import annotations

import argparse
import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from equity_analysis.forward_validation.preregistration_v1 import (
    SECTOR_BENCHMARKS,
    bucket_preview,
)
from equity_analysis.provider_validation.eodhd_interest_semantics_audit import (
    _fundamentals_events,
)
from equity_analysis.provider_validation.expansion_gate import (
    canonical_hash,
    write_immutable_json,
)

DAILY_PROTOCOL_VERSION = "FORWARD-VALIDATION-v1.1.0"
DAILY_REFRESH_POLICY_VERSION = "FORWARD-DAILY-INCREMENTAL-REFRESH-v1.0.0"
DAILY_ENROLLMENT_POLICY_VERSION = "DAILY-AFTER-CLOSE-ENROLLMENT-v1.0.0"
DAILY_PRICE_MAX_AGE_SESSIONS = 0
MARKET_CAP_MAX_AGE_SESSIONS = 0
FUNDAMENTALS_MAX_AGE_CALENDAR_DAYS = 7
IDENTITY_MAX_AGE_CALENDAR_DAYS = 7
ACTION_UNIVERSE_REFRESH_CALENDAR_DAYS = 7
MAX_PLANNED_EODHD_REQUESTS = 1000
HARD_EODHD_REQUEST_CEILING = 1500


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"), parse_float=Decimal)


def _latest_dataset_date(payload: dict[str, Any], dataset: str) -> str | None:
    candidates = [
        str(record["fiscalPeriodEnd"])
        for record in payload.get("records", [])
        if record.get("dataset") == dataset and record.get("fiscalPeriodEnd")
    ]
    return max(candidates) if candidates else None


def _run_timestamp(run_id: str) -> str:
    parsed = datetime.strptime(run_id.split("-", 1)[0], "%Y%m%dT%H%M%SZ")
    return parsed.isoformat() + "Z"


def build_daily_protocol(
    *,
    repository_root: Path,
    weekly_preregistration_path: Path,
    algorithm_gate_path: Path,
    aggregate_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    weekly = _load(weekly_preregistration_path)
    gate = _load(algorithm_gate_path)
    aggregate = _load(aggregate_path)
    if (
        weekly["sourceAlgorithmGate"]["artifactContentHash"]
        != gate["artifactContentHash"]
    ):
        raise ValueError("ALGORITHM_GATE_HASH_MISMATCH")
    formula_ready = {
        item["symbol"]: item
        for item in aggregate["securities"]
        if item["status"] == "FORMULA_READY"
    }
    fundamentals = _fundamentals_events(repository_root)
    update_states: list[dict[str, Any]] = []
    for symbol, item in sorted(formula_ready.items()):
        storage_reference = item.get("storageReference")
        payload_path = (
            repository_root / storage_reference
            if storage_reference
            else repository_root
            / "storage/provider-validation/scoring-inputs-v2"
            / symbol
            / f"{item['contentHash']}.json"
        )
        payload = _load(payload_path)
        if canonical_hash(payload) != item["contentHash"]:
            raise ValueError(f"FORMULA_READY_PAYLOAD_HASH_MISMATCH[{symbol}]")
        event = fundamentals.get(symbol)
        update_states.append(
            {
                "symbol": symbol,
                "dailyPriceLastObservationDate": _latest_dataset_date(
                    payload, "DAILY_PRICE"
                ),
                "marketCapLastObservationDate": _latest_dataset_date(
                    payload, "HISTORICAL_MARKET_CAP"
                ),
                "fundamentalsLastFetchedAt": (
                    _run_timestamp(event["runId"]) if event else None
                ),
                "fundamentalsResponseHash": (
                    event["detail"]["responseContentHash"] if event else None
                ),
                "corporateActionsLastCheckedAt": None,
                "identityLastCheckedAt": None,
            }
        )
    top, bottom = bucket_preview(gate["securities"])
    preview = [*top, *bottom]
    preview_symbols = sorted({item["symbol"] for item in preview})
    sectors = sorted({item["sector"] for item in preview})
    benchmark_symbols = sorted(
        {"SPY", *(SECTOR_BENCHMARKS[sector] for sector in sectors)}
    )
    price_requests = len(update_states) + len(benchmark_symbols)
    market_cap_requests = len(update_states)
    action_requests = 2 * (len(preview_symbols) + len(benchmark_symbols))
    planned_requests = price_requests + market_cap_requests + action_requests
    if planned_requests > MAX_PLANNED_EODHD_REQUESTS:
        raise ValueError("DAILY_REFRESH_PLAN_EXCEEDS_CONFIGURED_CEILING")
    artifact = {
        "artifactType": "FORWARD_DAILY_INCREMENTAL_PROTOCOL",
        "schemaVersion": "forward-daily-incremental-protocol-v1.0.0",
        "experimentVersion": DAILY_PROTOCOL_VERSION,
        "status": "PENDING_FIRST_COMPLETED_SESSION",
        "supersedes": {
            "path": weekly_preregistration_path.relative_to(
                repository_root
            ).as_posix(),
            "artifactContentHash": weekly["artifactContentHash"],
            "reason": "User approved daily rather than weekly enrollment.",
        },
        "sourceAlgorithmGate": {
            "path": algorithm_gate_path.relative_to(repository_root).as_posix(),
            "artifactContentHash": gate["artifactContentHash"],
            "asOfTime": gate["asOfTime"],
        },
        "enrollmentPolicy": {
            "version": DAILY_ENROLLMENT_POLICY_VERSION,
            "frequency": "EACH_COMPLETED_REGULAR_US_TRADING_SESSION",
            "timing": "After close and after complete EOD data are verified.",
            "topFraction": "0.20",
            "bottomFraction": "0.20",
            "boundaryTiesRetained": True,
            "activeEpisodeReentryProhibited": True,
            "sameSecuritySameStrategyBucketReentryCooldownTradingDays": 60,
            "dailySignalsAreCorrelatedCohorts": True,
            "primaryEvaluationRule": (
                "Retain daily cohorts, but calculate inference using unique "
                "first-entry episodes and report overlap explicitly."
            ),
        },
        "refreshPolicy": {
            "version": DAILY_REFRESH_POLICY_VERSION,
            "dailyPriceMaximumAgeCompletedSessions": DAILY_PRICE_MAX_AGE_SESSIONS,
            "marketCapMaximumAgeCompletedSessions": MARKET_CAP_MAX_AGE_SESSIONS,
            "fundamentalsMaximumAgeCalendarDays": (
                FUNDAMENTALS_MAX_AGE_CALENDAR_DAYS
            ),
            "identityMaximumAgeCalendarDays": IDENTITY_MAX_AGE_CALENDAR_DAYS,
            "universeCorporateActionRefreshCalendarDays": (
                ACTION_UNIVERSE_REFRESH_CALENDAR_DAYS
            ),
            "priorityRefreshTriggers": [
                "MISSING_DATA",
                "PROVIDER_UPDATED_DATE_CHANGED",
                "EXPECTED_OR_REPORTED_FILING",
                "ACTIVE_SIGNAL",
                "TOP_OR_BOTTOM_BUCKET_PREVIEW",
                "IDENTITY_OR_CORPORATE_ACTION_WARNING",
            ],
            "missingLastUpdateIsDueImmediately": True,
            "noDefaultForStaleOrMissingData": True,
        },
        "firstDailySessionCandidate": "2026-07-28",
        "firstDailySessionStatus": "PREMARKET_NOT_COMPLETED",
        "sourceSecurityCount": len(update_states),
        "previewSecurityCount": len(preview_symbols),
        "benchmarkSymbols": benchmark_symbols,
        "initialRefreshBudget": {
            "dailyPriceRequests": price_requests,
            "historicalMarketCapRequests": market_cap_requests,
            "previewAndBenchmarkDividendSplitRequests": action_requests,
            "fundamentalsRequests": 0,
            "plannedEodhdPhysicalRequests": planned_requests,
            "configuredCeiling": MAX_PLANNED_EODHD_REQUESTS,
            "hardCeiling": HARD_EODHD_REQUEST_CEILING,
            "dailyPlanQuotaPercentAt100k": format(
                Decimal(planned_requests) / Decimal(1000), "f"
            ),
            "retries": 0,
        },
        "updateStates": update_states,
        "signalsEnrolled": 0,
        "networkRequestsExecuted": False,
        "databaseWritesExecuted": False,
        "automaticTradingAuthorized": False,
        "formalHistoricalPitClaim": False,
    }
    artifact["artifactContentHash"] = canonical_hash(artifact)
    if output_path.exists():
        existing = _load(output_path)
        if existing != artifact:
            raise ValueError("FORWARD_DAILY_PROTOCOL_CONFLICT")
    else:
        write_immutable_json(output_path, artifact)
    return artifact


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build the versioned daily Forward validation protocol."
    )
    parser.add_argument(
        "--weekly-preregistration",
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
        "--aggregate",
        type=Path,
        default=Path("docs/generated/formula-ready-243-final-aggregate-v1.json"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(
            "docs/generated/forward-daily-incremental-protocol-v1.json"
        ),
    )
    arguments = parser.parse_args()
    root = Path.cwd().resolve()
    artifact = build_daily_protocol(
        repository_root=root,
        weekly_preregistration_path=(
            root / arguments.weekly_preregistration
        ).resolve(),
        algorithm_gate_path=(root / arguments.algorithm_gate).resolve(),
        aggregate_path=(root / arguments.aggregate).resolve(),
        output_path=(root / arguments.output).resolve(),
    )
    print(
        json.dumps(
            {
                "experimentVersion": artifact["experimentVersion"],
                "status": artifact["status"],
                "plannedRequests": artifact["initialRefreshBudget"][
                    "plannedEodhdPhysicalRequests"
                ],
            },
            separators=(",", ":"),
        )
    )


if __name__ == "__main__":
    main()
