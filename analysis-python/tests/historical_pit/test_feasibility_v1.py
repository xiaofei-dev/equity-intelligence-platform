from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid5

import pytest

from equity_analysis.analytics_interface.contracts import canonical_hash
from equity_analysis.historical_pit.feasibility_v1 import (
    DEFAULT_SEED,
    SliceFeasibilityStatus,
    audit_historical_pit_feasibility,
    build_candidate_manifest,
    write_immutable_artifact,
)

SNAPSHOT_ID = UUID("beaa9952-9852-4088-9dc3-92047824414b")
NAMESPACE = UUID("59b74aa6-0f92-46cc-82c7-d8c619040997")
AS_OF = datetime(2026, 7, 29, 2, 57, 8, tzinfo=UTC)


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest().upper()


def _artifact(path: Path, body: dict) -> None:
    payload = {**body, "artifactContentHash": canonical_hash(body)}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _weekdays(start: date, end: date) -> tuple[date, ...]:
    result = []
    current = start
    while current <= end:
        if current.weekday() < 5:
            result.append(current)
        current += timedelta(days=1)
    return tuple(result)


def _price_evidence(root: Path) -> Path:
    sessions = _weekdays(date(2014, 1, 2), date(2026, 7, 28))
    storage = (
        root
        / "storage"
        / "historical-validation"
        / "yahoo-daily-price-cache-v1"
        / "payloads"
        / "SPY"
    )
    payload_body = {
        "schemaVersion": "fixture-price-v1",
        "symbol": "SPY",
        "availableAt": "2026-07-29T22:43:10+00:00",
        "retrievedAt": "2026-07-29T22:43:10+00:00",
        "bars": [{"tradingDate": item.isoformat()} for item in sessions],
    }
    payload = {
        **payload_body,
        "contentHash": canonical_hash(payload_body),
    }
    payload_raw = json.dumps(payload).encode()
    payload_path = storage / "payload.json"
    payload_path.parent.mkdir(parents=True, exist_ok=True)
    payload_path.write_bytes(payload_raw)
    manifest_body = {
        "artifactType": "HISTORICAL_YAHOO_DAILY_PRICE_CACHE_MANIFEST",
        "status": "COMPLETE",
        "universeVersion": "closed-test-us-v1",
        "plannedSecurityCount": 1,
        "completedSecurityCount": 1,
        "failedSecurityCount": 0,
        "unrunSecurityCount": 0,
        "startDate": "2014-01-01",
        "endDate": "2026-07-28",
        "adjustmentPolicyVersion": "TOTAL-RETURN-v1",
        "records": [
            {
                "symbol": "SPY",
                "firstTradingDate": sessions[0].isoformat(),
                "lastTradingDate": sessions[-1].isoformat(),
                "payloadStorageReference": "payloads/SPY/payload.json",
                "payloadContentHash": payload["contentHash"],
                "payloadFileSha256": hashlib.sha256(payload_raw).hexdigest(),
            }
        ],
    }
    path = root / "price-manifest.json"
    _artifact(path, manifest_body)
    return path


class _Result:
    def __init__(self, rows):
        self.rows = rows

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return self.rows


class _Connection:
    def __init__(self):
        self.calls: list[tuple[str, tuple[object, ...]]] = []
        self.members = [
            {
                "security_id": index + 1,
                "public_id": uuid5(NAMESPACE, f"security:{index}"),
                "symbol_at_snapshot": ("SPY" if index == 55 else f"S{index:02d}"),
                "membership_status": (
                    "INCLUDED" if index < 55 else "REFERENCE_ONLY" if index == 55 else "EXCLUDED"
                ),
                "membership_reason": "FIXTURE",
                "company_type_at_snapshot": "FIXTURE",
                "normalized_sector_at_snapshot": "VALIDATION",
            }
            for index in range(66)
        ]

    def execute(self, query, params=()):
        self.calls.append((query, params))
        if query == "SET TRANSACTION READ ONLY":
            return _Result([])
        if "historical-pit:snapshot" in query:
            return _Result(
                [
                    {
                        "id": SNAPSHOT_ID,
                        "status": "READY",
                        "as_of_time": AS_OF,
                        "ingestion_cutoff": AS_OF,
                        "manifest_hash": _hash("snapshot"),
                        "security_count": 66,
                        "universe_version": "closed-test-us-v1",
                        "configuration_hash": _hash("universe"),
                    }
                ]
            )
        if "historical-pit:membership" in query:
            return _Result(
                [
                    {
                        "snapshot_count": 3,
                        "earliest_snapshot_as_of": AS_OF,
                        "latest_snapshot_as_of": AS_OF,
                    }
                ]
            )
        if "historical-pit:members" in query:
            return _Result(self.members)
        if "historical-pit:" in query:
            row = {
                "row_count": 0,
                "security_count": 0,
                "earliest_observation": None,
                "latest_observation": None,
                "earliest_available_at": None,
                "latest_ingested_at": None,
                "maximum_revision": None,
                "validated_count": 0,
                "provisional_count": 0,
                "missing_lineage_count": 0,
                "ticker_change_risk_count": 0,
                "terminal_status_count": 0,
                "distinct_metric_count": 0,
                "revised_count": 0,
                "scored_count": 0,
            }
            return _Result([row])
        raise AssertionError(f"Unexpected query: {query}")


def _audit(tmp_path: Path):
    price_manifest = _price_evidence(tmp_path)
    scoring_preflight = tmp_path / "scoring-v3.json"
    scoring_v4 = tmp_path / "scoring-v4.json"
    long_readiness = tmp_path / "long-readiness.json"
    _artifact(
        scoring_preflight,
        {
            "historicalPitEligibleCount": 0,
            "currentRankingEligibleCount": 0,
        },
    )
    _artifact(
        scoring_v4,
        {
            "historicalPitEligibleCount": 0,
            "currentQcEligibleCount": 0,
        },
    )
    _artifact(
        long_readiness,
        {"summary": {"v11HistoricalDecisionReadyCount": 0}},
    )
    connection = _Connection()
    result = audit_historical_pit_feasibility(
        connection,
        repository_root=tmp_path,
        data_snapshot_id=SNAPSHOT_ID,
        price_manifest_path=price_manifest,
        scoring_preflight_path=scoring_preflight,
        scoring_v4_manifest_path=scoring_v4,
        long_readiness_path=long_readiness,
    )
    return result, connection


def test_closed_pool_has_only_tactical_diagnostics_and_blocked_long(
    tmp_path,
) -> None:
    result, connection = _audit(tmp_path)

    assert result["closedPool"]["securityCount"] == 66
    assert result["closedPool"]["survivorshipBiasPresent"] is True
    assert result["summary"]["formalPitEligibleSliceCount"] == 0
    assert result["summary"]["trackStatusCounts"]["TACTICAL"] == {
        "FORMAL_PIT_ELIGIBLE": 0,
        "DIAGNOSTIC_ONLY": 54,
        "BLOCKED": 0,
    }
    assert result["summary"]["trackStatusCounts"]["LONG"] == {
        "FORMAL_PIT_ELIGIBLE": 0,
        "DIAGNOSTIC_ONLY": 0,
        "BLOCKED": 18,
    }
    assert result["methodologyBoundaries"]["modelExecuted"] is False
    assert result["methodologyBoundaries"]["futureOutcomeValuesReadForSelection"] is False
    assert result["methodologyBoundaries"]["providerNetworkRequests"] == 0
    assert result["methodologyBoundaries"]["databaseWrites"] == 0
    assert connection.calls[0][0] == "SET TRANSACTION READ ONLY"
    assert all(
        query.lstrip().startswith(("SELECT", "WITH", "/*", "SET"))
        for query, _params in connection.calls
    )


def test_fixed_seed_manifest_is_idempotent_and_uses_session_dates_only() -> None:
    sessions = _weekdays(date(2014, 1, 2), date(2026, 7, 28))
    arguments = {
        "spy_sessions": sessions,
        "price_evidence_hash": canonical_hash("price"),
        "seed": DEFAULT_SEED,
        "price_cache_complete": True,
        "historical_price_availability_pit": False,
        "historical_membership_pit": False,
        "historical_classification_pit": False,
        "historical_identity_status_pit": False,
        "historical_actions_pit": False,
        "historical_objective_pit": False,
    }

    first = build_candidate_manifest(**arguments)
    second = build_candidate_manifest(**arguments)

    assert first == second
    assert first["manifestHash"] == second["manifestHash"]
    assert first["candidateCount"] == 72
    assert {item["horizon_label"] for item in first["candidates"]} == {
        "TACTICAL_1W",
        "TACTICAL_1M",
        "TACTICAL_3M",
        "LONG_12M_PLUS",
    }


def test_artifact_hash_and_immutable_writer(tmp_path) -> None:
    artifact, _connection = _audit(tmp_path)
    unhashed = dict(artifact)
    claim = unhashed.pop("artifactContentHash")

    assert claim == canonical_hash(unhashed)
    output = tmp_path / "audit.json"
    first = write_immutable_artifact(output, artifact)
    second = write_immutable_artifact(output, artifact)
    assert first == second
    assert first == hashlib.sha256(output.read_bytes()).hexdigest().upper()

    changed = {**artifact, "auditMode": "CHANGED"}
    with pytest.raises(ValueError, match="IMMUTABLE_ARTIFACT_CONFLICT"):
        write_immutable_artifact(output, changed)


def test_long_slices_never_become_formal_without_objective_pit() -> None:
    sessions = _weekdays(date(2014, 1, 2), date(2026, 7, 28))
    manifest = build_candidate_manifest(
        spy_sessions=sessions,
        price_evidence_hash=canonical_hash("price"),
        seed=DEFAULT_SEED,
        price_cache_complete=True,
        historical_price_availability_pit=True,
        historical_membership_pit=True,
        historical_classification_pit=True,
        historical_identity_status_pit=True,
        historical_actions_pit=True,
        historical_objective_pit=False,
    )

    long_rows = [item for item in manifest["candidates"] if item["track"] == "LONG"]
    assert all(item["status"] == SliceFeasibilityStatus.BLOCKED.value for item in long_rows)
    assert all(
        "OBJECTIVE_AND_FUNDAMENTAL_INPUTS_NOT_PIT_READY" in item["reason_codes"]
        for item in long_rows
    )
