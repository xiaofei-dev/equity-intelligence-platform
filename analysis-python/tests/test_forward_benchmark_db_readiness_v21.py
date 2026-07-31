from __future__ import annotations

import hashlib
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid5

import pytest

from equity_analysis.forward_validation.benchmark_construction_v21 import (
    BenchmarkConstructionState,
)
from equity_analysis.forward_validation.benchmark_db_readiness_v21 import (
    BenchmarkDbReadinessError,
    BenchmarkDbReadinessStatus,
    PostgresBenchmarkReadinessAdapterV21,
)
from equity_analysis.historical_validation.protocol_v2 import BenchmarkKind

SNAPSHOT_ID = UUID("11111111-1111-4111-8111-111111111111")
OTHER_SNAPSHOT_ID = UUID("22222222-2222-4222-8222-222222222222")
AS_OF = datetime(2026, 7, 29, 2, 57, 8, tzinfo=UTC)
PARENT_COST_HASH = hashlib.sha256(b"parent-cost-policy").hexdigest()
NAMESPACE = UUID("ec35487c-c4d3-45c0-aeda-254fb65b40fd")


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


class _Result:
    def __init__(self, rows):
        self.rows = rows

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return self.rows


class _Connection:
    def __init__(self, rows):
        self.rows = rows
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    def execute(self, query, params=()):
        self.calls.append((query, params))
        if "benchmark-v21:snapshot" in query:
            return _Result([self.rows["snapshot"]])
        if "benchmark-v21:members" in query:
            return _Result(self.rows["members"])
        if "benchmark-v21:prices" in query:
            return _Result(self.rows["prices"])
        if "benchmark-v21:liquidity" in query:
            return _Result(self.rows["liquidity"])
        if query == "SET TRANSACTION READ ONLY":
            return _Result([])
        raise AssertionError(f"Unexpected SQL: {query}")


def _member_row(
    index: int,
    *,
    status: str,
    reason: str,
    symbol: str,
) -> dict[str, object]:
    public_id = uuid5(NAMESPACE, f"security:{index}")
    profile_id = uuid5(NAMESPACE, f"profile:{index}")
    return {
        "database_security_id": index + 1,
        "public_id": public_id,
        "symbol_at_snapshot": symbol,
        "membership_status": status,
        "membership_reason": reason,
        "normalized_sector_at_snapshot": "VALIDATION",
        "profile_id": profile_id,
        "snapshot_as_of": AS_OF,
        "input_payload_hash": _hash(f"profile:{index}"),
        "objective_rating_status": "INSUFFICIENT_DATA",
        "objective_rating_version": "Objective-Rating-v1",
        "objective_quality_score": None,
        "objective_valuation_score": None,
        "profile_sector_code": None,
        "profile_sector_name": None,
        "classification_effective_at": None,
        "classification_available_at": None,
        "classification_retrieved_at": None,
        "classification_source_hash": None,
        "objective_score_available_at": None,
        "objective_score_ingested_at": None,
        "objective_score_lineage_hash": None,
    }


def _fixture_rows() -> dict[str, object]:
    members: list[dict[str, object]] = []
    for index in range(55):
        members.append(
            _member_row(
                index,
                status="INCLUDED",
                reason="PRIMARY",
                symbol=f"S{index:02d}",
            )
        )
    members.append(
        _member_row(
            55,
            status="REFERENCE_ONLY",
            reason="MARKET_BENCHMARK",
            symbol="SPY",
        )
    )
    members.append(
        _member_row(
            56,
            status="REFERENCE_ONLY",
            reason="SECTOR_BENCHMARK",
            symbol="XLK",
        )
    )
    for index in range(57, 66):
        members.append(
            _member_row(
                index,
                status="EXCLUDED",
                reason="SPECIALIZED_MODEL_REQUIRED",
                symbol=f"X{index:02d}",
            )
        )
    prices = [
        {
            "public_id": row["public_id"],
            "trading_date": AS_OF.date(),
            "open_price": Decimal("100"),
            "close_price": Decimal("101"),
            "adjusted_close": Decimal("101"),
            "adjustment_mode": "TOTAL_RETURN_ADJUSTED",
            "quality_status": "PROVISIONAL",
            "available_at": AS_OF - timedelta(minutes=20),
            "ingested_at": AS_OF - timedelta(minutes=10),
            "normalization_version": "fixture-price-v1",
            "source_hash": _hash(f"price:{row['public_id']}"),
            "session_complete": None,
            "validation_decision_hash": None,
            "promotion_evidence_hash": None,
        }
        for row in members
    ]
    return {
        "snapshot": {
            "id": SNAPSHOT_ID,
            "status": "READY",
            "as_of_time": AS_OF,
            "ingestion_cutoff": AS_OF,
            "manifest_hash": _hash("snapshot-manifest"),
            "security_count": 66,
            "source_count": 1,
            "market_normalization_version": "fixture-price-v1",
            "market_data_provider": "yfinance",
            "market_adjustment_mode": "TOTAL_RETURN_ADJUSTED",
            "universe_version": "closed-test-us-v1",
            "configuration_hash": _hash("universe-configuration"),
        },
        "members": members,
        "prices": prices,
        "liquidity": [],
    }


def _inspect(rows=None, *, snapshot_id=SNAPSHOT_ID):
    fixture = rows or _fixture_rows()
    if rows is None:
        fixture["snapshot"]["id"] = snapshot_id
    connection = _Connection(fixture)
    result = PostgresBenchmarkReadinessAdapterV21().inspect(
        connection,
        data_snapshot_id=snapshot_id,
        parent_liquidity_cost_policy_hash=PARENT_COST_HASH,
    )
    return result, connection


def test_current_v17_shape_is_explicitly_blocked_for_all_six_families() -> None:
    result, connection = _inspect()

    assert result.status == BenchmarkDbReadinessStatus.BLOCKED
    assert result.prospective_enrollment_allowed is False
    assert result.loaded_security_count == 66
    assert tuple(item.kind for item in result.families) == tuple(BenchmarkKind)
    assert all(item.state == BenchmarkConstructionState.MISSING for item in result.families)
    assert "PLACEHOLDER_SECTOR_PRESENT" in result.evidence_blockers
    assert "PROVISIONAL_PRICE_EVIDENCE" in result.evidence_blockers
    assert {
        "COMPLETED_SESSION_EVIDENCE_NOT_PERSISTED_V17",
        "PRICE_VALIDATION_DECISION_HASH_NOT_PERSISTED_V17",
        "PRICE_PROMOTION_EVIDENCE_NOT_PERSISTED_V17",
        "OBJECTIVE_SCORE_LINEAGE_AND_TIMING_NOT_PERSISTED_V17",
    }.issubset(result.schema_blockers)
    assert result.database_writes == 0
    assert result.provider_network_requests == 0
    assert connection.calls[0][0] == "SET TRANSACTION READ ONLY"
    assert all(
        query.lstrip().startswith(("SELECT", "/*", "SET")) for query, _params in connection.calls
    )


def test_adapter_queries_only_the_explicit_snapshot_id() -> None:
    result, connection = _inspect(snapshot_id=OTHER_SNAPSHOT_ID)

    assert result.data_snapshot_id == OTHER_SNAPSHOT_ID
    snapshot_call = next(item for item in connection.calls if "benchmark-v21:snapshot" in item[0])
    member_call = next(item for item in connection.calls if "benchmark-v21:members" in item[0])
    price_call = next(item for item in connection.calls if "benchmark-v21:prices" in item[0])
    assert snapshot_call[1] == (OTHER_SNAPSHOT_ID,)
    assert member_call[1][0] == OTHER_SNAPSHOT_ID
    assert price_call[1][0] == OTHER_SNAPSHOT_ID
    liquidity_call = next(item for item in connection.calls if "benchmark-v21:liquidity" in item[0])
    assert isinstance(liquidity_call[1][0], list)
    assert "MAX(" not in snapshot_call[0].upper()
    assert "ORDER BY" not in snapshot_call[0].upper()


def test_future_rows_are_ignored_and_do_not_change_readiness_hash() -> None:
    rows = _fixture_rows()
    baseline, _connection = _inspect(deepcopy(rows))
    future = deepcopy(rows["prices"][0])
    future["trading_date"] = AS_OF.date() + timedelta(days=1)
    future["available_at"] = AS_OF + timedelta(days=1)
    future["ingested_at"] = AS_OF + timedelta(days=1)
    future["quality_status"] = "VALIDATED"
    future["session_complete"] = True
    future["validation_decision_hash"] = _hash("future-validation")
    rows["prices"].append(future)

    with_future, _connection = _inspect(rows)

    assert with_future.diagnostic_content_hash == baseline.diagnostic_content_hash
    assert with_future.construction_bundle_hash == baseline.construction_bundle_hash


def test_repeated_readiness_is_idempotent() -> None:
    first, _first_connection = _inspect()
    second, _second_connection = _inspect()

    assert first == second
    assert first.diagnostic_content_hash == second.diagnostic_content_hash


def test_missing_spy_uses_non_member_sentinel_and_spy_family_is_missing() -> None:
    rows = _fixture_rows()
    spy_member = next(item for item in rows["members"] if item["symbol_at_snapshot"] == "SPY")
    spy_member["symbol_at_snapshot"] = "NOT-SPY"

    result, _connection = _inspect(rows)

    spy_family = next(item for item in result.families if item.kind == BenchmarkKind.SPY)
    assert spy_family.state == BenchmarkConstructionState.MISSING
    assert "MARKET_BENCHMARK_MUST_BE_SPY" in spy_family.reason_codes
    assert "SPY_REFERENCE_IDENTITY_MISSING_OR_AMBIGUOUS" in result.evidence_blockers


def test_non_ready_or_wrong_population_snapshot_is_rejected() -> None:
    rows = _fixture_rows()
    rows["snapshot"]["status"] = "BUILDING"
    with pytest.raises(BenchmarkDbReadinessError, match="not READY"):
        _inspect(rows)

    rows = _fixture_rows()
    rows["snapshot"]["security_count"] = 65
    with pytest.raises(BenchmarkDbReadinessError, match="66 securities"):
        _inspect(rows)
