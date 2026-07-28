from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from equity_analysis.provider_validation.expansion_gate import (
    canonical_hash,
    write_immutable_json,
)

PLAN_SCHEMA_VERSION = "forward-daily-refresh-plan-v1.0.0"
PLAN_POLICY_VERSION = "FORWARD-DAILY-INCREMENTAL-REFRESH-v1.0.0"


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"), parse_float=Decimal)


def _date_part(value: str | None) -> date | None:
    if not value:
        return None
    return date.fromisoformat(value[:10])


def _calendar_due(
    value: str | None,
    *,
    target_date: date,
    maximum_age_days: int,
) -> bool:
    observed = _date_part(value)
    return observed is None or target_date - observed >= timedelta(
        days=maximum_age_days
    )


def _request(
    *,
    endpoint: str,
    symbol: str,
    reason: str,
    target_date: date,
) -> dict[str, str]:
    return {
        "provider": "EODHD",
        "endpoint": endpoint,
        "symbol": symbol,
        "targetDate": target_date.isoformat(),
        "reason": reason,
    }


def build_daily_refresh_plan(
    *,
    repository_root: Path,
    protocol_path: Path,
    target_session_date: date,
    session_completed: bool,
    output_path: Path,
) -> dict[str, Any]:
    protocol = _load(protocol_path)
    if protocol["refreshPolicy"]["version"] != PLAN_POLICY_VERSION:
        raise ValueError("DAILY_REFRESH_POLICY_VERSION_MISMATCH")

    policy = protocol["refreshPolicy"]
    states = {
        item["symbol"]: item for item in protocol["updateStates"]
    }
    benchmarks = tuple(protocol["benchmarkSymbols"])
    preview_symbols = {
        item["symbol"]
        for item in protocol.get("previewSecurities", [])
    }
    if not preview_symbols:
        preview_count = int(protocol["previewSecurityCount"])
        gate = _load(
            repository_root / protocol["sourceAlgorithmGate"]["path"]
        )
        ranked = sorted(
            (
                item
                for item in gate["securities"]
                if item.get("rank") is not None
            ),
            key=lambda item: (item["rank"], item["symbol"]),
        )
        lower_count = preview_count // 2
        upper_count = preview_count - lower_count
        preview_symbols = {
            item["symbol"] for item in ranked[:upper_count]
        } | {
            item["symbol"] for item in ranked[-lower_count:]
        }

    requests: list[dict[str, str]] = []
    for symbol, state in sorted(states.items()):
        if _date_part(state["dailyPriceLastObservationDate"]) != target_session_date:
            requests.append(
                _request(
                    endpoint="eod",
                    symbol=symbol,
                    reason="TARGET_SESSION_PRICE_NOT_OBSERVED",
                    target_date=target_session_date,
                )
            )
        if _date_part(state["marketCapLastObservationDate"]) != target_session_date:
            requests.append(
                _request(
                    endpoint="historical-market-cap",
                    symbol=symbol,
                    reason="TARGET_SESSION_MARKET_CAP_NOT_OBSERVED",
                    target_date=target_session_date,
                )
            )
        if _calendar_due(
            state["fundamentalsLastFetchedAt"],
            target_date=target_session_date,
            maximum_age_days=int(
                policy["fundamentalsMaximumAgeCalendarDays"]
            ),
        ):
            requests.append(
                _request(
                    endpoint="fundamentals",
                    symbol=symbol,
                    reason="FUNDAMENTALS_TTL_DUE",
                    target_date=target_session_date,
                )
            )
        identity_checked = (
            state["identityLastCheckedAt"]
            or state["fundamentalsLastFetchedAt"]
        )
        if _calendar_due(
            identity_checked,
            target_date=target_session_date,
            maximum_age_days=int(policy["identityMaximumAgeCalendarDays"]),
        ) and not any(
            item["symbol"] == symbol
            and item["endpoint"] == "fundamentals"
            for item in requests
        ):
            requests.append(
                _request(
                    endpoint="fundamentals",
                    symbol=symbol,
                    reason="IDENTITY_TTL_DUE",
                    target_date=target_session_date,
                )
            )
        if symbol in preview_symbols and _calendar_due(
            state["corporateActionsLastCheckedAt"],
            target_date=target_session_date,
            maximum_age_days=int(
                policy["universeCorporateActionRefreshCalendarDays"]
            ),
        ):
            for endpoint in ("div", "splits"):
                requests.append(
                    _request(
                        endpoint=endpoint,
                        symbol=symbol,
                        reason="ACTIVE_PREVIEW_ACTIONS_TTL_DUE",
                        target_date=target_session_date,
                    )
                )

    for symbol in benchmarks:
        requests.append(
            _request(
                endpoint="eod",
                symbol=symbol,
                reason="BENCHMARK_TARGET_SESSION_PRICE_REQUIRED",
                target_date=target_session_date,
            )
        )
        for endpoint in ("div", "splits"):
            requests.append(
                _request(
                    endpoint=endpoint,
                    symbol=symbol,
                    reason="BENCHMARK_ACTIONS_REQUIRED",
                    target_date=target_session_date,
                )
            )

    requests.sort(key=lambda item: (item["endpoint"], item["symbol"]))
    counts: dict[str, int] = {}
    for item in requests:
        counts[item["endpoint"]] = counts.get(item["endpoint"], 0) + 1
    planned = len(requests)
    configured_ceiling = int(
        protocol["initialRefreshBudget"]["configuredCeiling"]
    )
    hard_ceiling = int(protocol["initialRefreshBudget"]["hardCeiling"])
    if planned > configured_ceiling or planned > hard_ceiling:
        raise ValueError("DAILY_REFRESH_PLAN_EXCEEDS_APPROVED_CEILING")

    artifact = {
        "artifactType": "FORWARD_DAILY_REFRESH_PLAN",
        "schemaVersion": PLAN_SCHEMA_VERSION,
        "policyVersion": PLAN_POLICY_VERSION,
        "status": (
            "READY_FOR_EXPLICIT_LIVE_EXECUTION"
            if session_completed
            else "WAITING_FOR_COMPLETED_SESSION"
        ),
        "targetSessionDate": target_session_date.isoformat(),
        "sessionCompleted": session_completed,
        "sourceProtocol": {
            "path": protocol_path.relative_to(repository_root).as_posix(),
            "artifactContentHash": protocol["artifactContentHash"],
        },
        "lastUpdatePolicy": {
            "pricesAndMarketCap": "REFRESH_AFTER_EACH_COMPLETED_SESSION",
            "fundamentals": (
                f"REFRESH_WHEN_OLDER_THAN_{policy['fundamentalsMaximumAgeCalendarDays']}"
                "_CALENDAR_DAYS"
            ),
            "identity": (
                f"REFRESH_WHEN_OLDER_THAN_{policy['identityMaximumAgeCalendarDays']}"
                "_CALENDAR_DAYS"
            ),
            "corporateActions": (
                "REFRESH_ACTIVE_PREVIEW_AND_BENCHMARKS; "
                f"UNIVERSE_TTL_{policy['universeCorporateActionRefreshCalendarDays']}"
                "_CALENDAR_DAYS"
            ),
            "missingLastUpdateIsDueImmediately": True,
        },
        "requestCountsByEndpoint": dict(sorted(counts.items())),
        "plannedPhysicalRequests": planned,
        "dailyQuota": 100_000,
        "plannedQuotaPercent": format(
            Decimal(planned) / Decimal(1000), "f"
        ),
        "configuredCeiling": configured_ceiling,
        "hardCeiling": hard_ceiling,
        "retries": 0,
        "requests": requests,
        "networkRequestsExecuted": False,
        "automaticTradingAuthorized": False,
    }
    artifact["artifactContentHash"] = canonical_hash(artifact)
    if output_path.exists():
        if _load(output_path) != artifact:
            raise ValueError("FORWARD_DAILY_REFRESH_PLAN_CONFLICT")
    else:
        write_immutable_json(output_path, artifact)
    return artifact


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build a bounded daily incremental refresh plan."
    )
    parser.add_argument(
        "--protocol",
        type=Path,
        default=Path(
            "docs/generated/forward-daily-incremental-protocol-v1.json"
        ),
    )
    parser.add_argument("--target-session-date", type=date.fromisoformat)
    parser.add_argument("--session-completed", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    root = Path.cwd().resolve()
    target = arguments.target_session_date or datetime.now().date()
    artifact = build_daily_refresh_plan(
        repository_root=root,
        protocol_path=(root / arguments.protocol).resolve(),
        target_session_date=target,
        session_completed=arguments.session_completed,
        output_path=(root / arguments.output).resolve(),
    )
    print(
        json.dumps(
            {
                "status": artifact["status"],
                "targetSessionDate": artifact["targetSessionDate"],
                "plannedPhysicalRequests": artifact[
                    "plannedPhysicalRequests"
                ],
            },
            separators=(",", ":"),
        )
    )


if __name__ == "__main__":
    main()
