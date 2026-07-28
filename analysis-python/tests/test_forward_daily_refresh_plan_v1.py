import json
from datetime import date
from pathlib import Path

from equity_analysis.forward_validation.daily_refresh_plan_v1 import (
    build_daily_refresh_plan,
)
from equity_analysis.provider_validation.expansion_gate import canonical_hash


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_daily_plan_refreshes_market_data_but_respects_fundamentals_ttl(
    tmp_path: Path,
) -> None:
    gate = {
        "securities": [
            {"symbol": "AAA", "rank": 1},
            {"symbol": "BBB", "rank": 2},
        ]
    }
    _write(tmp_path / "gate.json", gate)
    protocol = {
        "refreshPolicy": {
            "version": "FORWARD-DAILY-INCREMENTAL-REFRESH-v1.0.0",
            "fundamentalsMaximumAgeCalendarDays": 7,
            "identityMaximumAgeCalendarDays": 7,
            "universeCorporateActionRefreshCalendarDays": 7,
        },
        "sourceAlgorithmGate": {"path": "gate.json"},
        "updateStates": [
            {
                "symbol": "AAA",
                "dailyPriceLastObservationDate": "2026-07-27",
                "marketCapLastObservationDate": "2026-07-27",
                "fundamentalsLastFetchedAt": "2026-07-27T10:00:00Z",
                "corporateActionsLastCheckedAt": None,
                "identityLastCheckedAt": None,
            },
            {
                "symbol": "BBB",
                "dailyPriceLastObservationDate": "2026-07-28",
                "marketCapLastObservationDate": "2026-07-28",
                "fundamentalsLastFetchedAt": "2026-07-20T10:00:00Z",
                "corporateActionsLastCheckedAt": "2026-07-27T10:00:00Z",
                "identityLastCheckedAt": "2026-07-27T10:00:00Z",
            },
        ],
        "benchmarkSymbols": ["SPY"],
        "previewSecurityCount": 2,
        "initialRefreshBudget": {
            "configuredCeiling": 1000,
            "hardCeiling": 1500,
        },
    }
    protocol["artifactContentHash"] = canonical_hash(protocol)
    _write(tmp_path / "protocol.json", protocol)

    artifact = build_daily_refresh_plan(
        repository_root=tmp_path,
        protocol_path=tmp_path / "protocol.json",
        target_session_date=date(2026, 7, 28),
        session_completed=False,
        output_path=tmp_path / "plan.json",
    )

    assert artifact["status"] == "WAITING_FOR_COMPLETED_SESSION"
    assert artifact["requestCountsByEndpoint"] == {
        "div": 2,
        "eod": 2,
        "fundamentals": 1,
        "historical-market-cap": 1,
        "splits": 2,
    }
    assert artifact["plannedPhysicalRequests"] == 8
    assert artifact["networkRequestsExecuted"] is False


def test_daily_plan_refuses_to_claim_completion_before_session_close(
    tmp_path: Path,
) -> None:
    _write(tmp_path / "gate.json", {"securities": []})
    protocol = {
        "refreshPolicy": {
            "version": "FORWARD-DAILY-INCREMENTAL-REFRESH-v1.0.0",
            "fundamentalsMaximumAgeCalendarDays": 7,
            "identityMaximumAgeCalendarDays": 7,
            "universeCorporateActionRefreshCalendarDays": 7,
        },
        "sourceAlgorithmGate": {"path": "gate.json"},
        "updateStates": [],
        "benchmarkSymbols": [],
        "previewSecurityCount": 0,
        "initialRefreshBudget": {
            "configuredCeiling": 1000,
            "hardCeiling": 1500,
        },
    }
    protocol["artifactContentHash"] = canonical_hash(protocol)
    _write(tmp_path / "protocol.json", protocol)

    artifact = build_daily_refresh_plan(
        repository_root=tmp_path,
        protocol_path=tmp_path / "protocol.json",
        target_session_date=date(2026, 7, 28),
        session_completed=False,
        output_path=tmp_path / "plan.json",
    )

    assert artifact["sessionCompleted"] is False
    assert artifact["status"] == "WAITING_FOR_COMPLETED_SESSION"
