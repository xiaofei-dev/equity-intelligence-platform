from __future__ import annotations

import argparse
import json
import os
import re
from collections.abc import Callable
from dataclasses import asdict, dataclass, fields, is_dataclass, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

from equity_analysis.analytics_interface.contracts import canonical_hash
from equity_analysis.forward_validation.contracts_v2 import (
    AuditEventPayload,
    BenchmarkAvailability,
    BenchmarkEvidenceBinding,
    CostPolicyBinding,
    ModelTrack,
    OutcomeDependence,
    PopulationTerminalState,
    ReadyDataSnapshotBinding,
    SecurityDecisionRecord,
    ValidationEvidenceEnvelope,
)
from equity_analysis.forward_validation.decision_snapshot_v2 import (
    DecisionSnapshotBundle,
    build_decision_snapshot,
    build_security_decision,
    build_v16_audit_event_payload,
    load_sealed_model_freeze,
    write_snapshot_bundle,
)
from equity_analysis.market_intelligence.service import MARKET_INTELLIGENCE_VERSION
from equity_analysis.research_rating.long_horizon_v11 import (
    LONG_HORIZON_V11_VERSION,
    CompanyModelV11,
    InputState,
    LongHorizonV11Inputs,
    MetricEvidence,
    evaluate_long_horizon_v11,
)
from equity_analysis.tactical.contracts_v22 import (
    EventEvidenceV22,
    EvidenceState,
    SeriesEvidenceV22,
    TacticalBarV22,
    TacticalContextV22,
)
from equity_analysis.tactical.signal_v22 import evaluate_tactical_signal_v22

DB_DECISION_ASSEMBLER_VERSION = "FORWARD-V2-DB-DECISION-ASSEMBLER-v1.0.0"
LONG_HORIZON_INPUT_VERSION = "LONG-HORIZON-INPUT-v1.1.0"
EXPECTED_CLOSED_POPULATION = 66
DEFAULT_MAX_PRICE_AGE_DAYS = 7
MARKET_BENCHMARK_SYMBOL = "SPY"

_LONG_NON_METRIC_FIELDS = {
    "symbol",
    "company_model",
    "peer_cohort_member_count",
    "peer_cohort_minimum_count",
}
_LONG_METRIC_FIELDS = tuple(
    item.name
    for item in fields(LongHorizonV11Inputs)
    if item.name not in _LONG_NON_METRIC_FIELDS
)


class ForwardV2DbSnapshotError(ValueError):
    code = "FORWARD_V2_DB_SNAPSHOT_INVALID"


class ForwardV2DbConflictError(ValueError):
    code = "FORWARD_V2_DB_IDEMPOTENCY_CONFLICT"


@dataclass(frozen=True)
class SnapshotMemberEvidence:
    database_security_id: int
    public_security_id: UUID
    profile_id: UUID
    symbol: str
    membership_status: str
    membership_reason: str
    company_type: str
    normalized_sector: str | None
    profile_contract_version: str
    profile_input_payload_hash: str


@dataclass(frozen=True)
class ProfileFactEvidence:
    name: str
    metric_version: str
    state: str
    numeric_value: Decimal | None
    reason: str | None
    source_hashes: tuple[str, ...]
    period_start: date | None = None
    period_end: date | None = None
    available_at: datetime | None = None
    ingested_at: datetime | None = None


@dataclass(frozen=True)
class SnapshotDbEvidence:
    data_snapshot: ReadyDataSnapshotBinding
    ingestion_cutoff: datetime
    market_provider: str
    adjustment_mode: str
    members: tuple[SnapshotMemberEvidence, ...]
    profile_facts: dict[UUID, tuple[ProfileFactEvidence, ...]]
    market_benchmark_id: UUID | None
    sector_benchmark_ids: dict[str, UUID]
    member_role_hash: str


@dataclass(frozen=True)
class DbDecisionSnapshotAssembly:
    assembler_version: str
    bundle: DecisionSnapshotBundle
    audit_event: AuditEventPayload
    member_role_hash: str
    membership_counts: dict[str, int]
    provider_network_requests: int = 0
    ai_used_for_deterministic_decisions: bool = False
    database_write_executed: bool = False


@dataclass(frozen=True)
class PersistedAuditEvent:
    audit_event_id: UUID
    event_hash: str
    replayed: bool


@dataclass(frozen=True)
class _SeriesResult:
    evidence: SeriesEvidenceV22
    latest_trading_date: date | None


def _json(value: Any) -> str:
    return json.dumps(
        _canonical_json_value(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )


def _canonical_json_value(value: Any) -> Any:
    """Match the canonical-hash value domain before PostgreSQL JSONB encoding."""
    if is_dataclass(value) and not isinstance(value, type):
        return {
            item.name: _canonical_json_value(getattr(value, item.name))
            for item in fields(value)
        }
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        normalized = value.astimezone(UTC)
        return normalized.isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {
            str(key): _canonical_json_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, tuple | list):
        return [_canonical_json_value(item) for item in value]
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    raise TypeError(f"Unsupported canonical JSON value type: {type(value).__name__}")


def _aware(value: datetime, label: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ForwardV2DbSnapshotError(f"{label} must be timezone-aware")
    return value


def _hash_payload(value: Any) -> str:
    return canonical_hash(value)


def _benchmark_state(state: EvidenceState) -> BenchmarkAvailability:
    return {
        EvidenceState.VALID: BenchmarkAvailability.AVAILABLE,
        EvidenceState.MISSING: BenchmarkAvailability.MISSING,
        EvidenceState.STALE: BenchmarkAvailability.STALE,
        EvidenceState.INVALID: BenchmarkAvailability.INVALID,
        EvidenceState.NOT_APPLICABLE: BenchmarkAvailability.MISSING,
    }[state]


def _company_model(company_type: str) -> CompanyModelV11:
    normalized = company_type.strip().upper().replace("-", "_").replace(" ", "_")
    mappings = {
        "BANK": CompanyModelV11.BANK,
        "BANKING": CompanyModelV11.BANK,
        "INSURANCE": CompanyModelV11.INSURANCE,
        "REIT": CompanyModelV11.REIT,
        "RESOURCE": CompanyModelV11.RESOURCE,
        "RESOURCE_COMPANY": CompanyModelV11.RESOURCE,
        "BIOTECH": CompanyModelV11.BIOTECH,
        "BIOTECHNOLOGY": CompanyModelV11.BIOTECH,
        "RECENT_IPO": CompanyModelV11.RECENT_IPO,
        "IPO": CompanyModelV11.RECENT_IPO,
    }
    return mappings.get(normalized, CompanyModelV11.GENERAL)


def _metric_evidence(
    fact: ProfileFactEvidence | None,
    *,
    cutoff: datetime,
) -> MetricEvidence:
    if fact is None:
        return MetricEvidence.missing()
    if fact.metric_version != LONG_HORIZON_INPUT_VERSION:
        return MetricEvidence.missing()
    if fact.state == InputState.NOT_APPLICABLE.value:
        return MetricEvidence.not_applicable()
    hashes_valid = bool(fact.source_hashes) and all(
        re.fullmatch(r"sha256:[0-9a-f]{64}", value) is not None
        for value in fact.source_hashes
    )
    times_valid = (
        fact.available_at is not None
        and fact.ingested_at is not None
        and fact.available_at.tzinfo is not None
        and fact.ingested_at.tzinfo is not None
        and fact.available_at <= cutoff
        and fact.ingested_at <= cutoff
        and fact.ingested_at >= fact.available_at
    )
    if (
        fact.state == InputState.INVALID.value
        or fact.numeric_value is None
        or not hashes_valid
        or not times_valid
    ):
        return MetricEvidence.invalid()
    if fact.state != InputState.VALID.value:
        return MetricEvidence.missing()
    return MetricEvidence.valid(fact.numeric_value)


def _long_inputs(
    member: SnapshotMemberEvidence,
    facts: tuple[ProfileFactEvidence, ...],
    *,
    cutoff: datetime,
) -> tuple[LongHorizonV11Inputs, str, str]:
    exact = {
        item.name: item
        for item in facts
        if item.name in _LONG_METRIC_FIELDS
        and item.metric_version == LONG_HORIZON_INPUT_VERSION
    }
    metric_inputs = {
        name: _metric_evidence(exact.get(name), cutoff=cutoff)
        for name in _LONG_METRIC_FIELDS
    }
    inputs = LongHorizonV11Inputs(
        symbol=member.symbol,
        company_model=_company_model(member.company_type),
        **metric_inputs,
    )
    input_hash = _hash_payload(
        {
            "assemblerVersion": DB_DECISION_ASSEMBLER_VERSION,
            "modelVersion": LONG_HORIZON_V11_VERSION,
            "profileId": str(member.profile_id),
            "profileInputPayloadHash": member.profile_input_payload_hash,
            "membershipStatus": member.membership_status,
            "membershipReason": member.membership_reason,
            "companyModel": inputs.company_model.value,
            "inputs": asdict(inputs),
        }
    )
    evidence_hash = _hash_payload(
        {
            "profileId": str(member.profile_id),
            "profileInputPayloadHash": member.profile_input_payload_hash,
            "facts": [
                {
                    "name": item.name,
                    "metricVersion": item.metric_version,
                    "state": item.state,
                    "reason": item.reason,
                    "sourceHashes": item.source_hashes,
                    "periodStart": item.period_start,
                    "periodEnd": item.period_end,
                    "availableAt": item.available_at,
                    "ingestedAt": item.ingested_at,
                }
                for item in sorted(facts, key=lambda value: (value.name, value.metric_version))
            ],
        }
    )
    return inputs, input_hash, evidence_hash


def _included_tactical_state(
    assessment,
    required_states: tuple[EvidenceState, ...],
) -> PopulationTerminalState | None:
    if any(item == EvidenceState.INVALID for item in required_states):
        return PopulationTerminalState.INVALID
    if any(item == EvidenceState.STALE for item in required_states):
        return PopulationTerminalState.STALE
    if any(item == EvidenceState.NOT_APPLICABLE for item in required_states):
        return PopulationTerminalState.NOT_APPLICABLE
    if all(item.outlook.value == "INSUFFICIENT_DATA" for item in assessment.horizons):
        return PopulationTerminalState.MISSING
    return None


def _membership_terminal_overrides(
    member: SnapshotMemberEvidence,
) -> tuple[
    PopulationTerminalState | None,
    PopulationTerminalState | None,
    tuple[str, ...],
]:
    if member.membership_status == "REFERENCE_ONLY":
        reason = f"REFERENCE_ONLY:{member.membership_reason}"
        return (
            PopulationTerminalState.NOT_APPLICABLE,
            PopulationTerminalState.NOT_APPLICABLE,
            (reason,),
        )
    if member.membership_status == "EXCLUDED":
        reason = f"EXCLUDED:{member.membership_reason}"
        return (
            PopulationTerminalState.EXCLUDED,
            PopulationTerminalState.EXCLUDED,
            (reason,),
        )
    return None, None, ()


class ForwardV2DbDecisionAssembler:
    """Assemble Forward v2 terminal decisions from one exact READY V17 profile set.

    The class has no provider client. It deliberately ignores V17 horizon scores and
    Objective Rating scores because those records belong to older model contracts.
    """

    def __init__(
        self,
        database_url: str,
        *,
        repository_root: Path,
        connect: Callable[..., Any] = psycopg.connect,
        expected_population: int = EXPECTED_CLOSED_POPULATION,
        max_price_age_days: int = DEFAULT_MAX_PRICE_AGE_DAYS,
    ) -> None:
        if not database_url:
            raise ValueError("Analytics database URL is required")
        if expected_population < 1:
            raise ValueError("Expected population must be positive")
        if max_price_age_days < 0:
            raise ValueError("Price freshness limit cannot be negative")
        self.database_url = database_url
        self.repository_root = repository_root
        self._connect = connect
        self.expected_population = expected_population
        self.max_price_age_days = max_price_age_days

    def latest_ready_closed_snapshot(self) -> tuple[UUID, str]:
        with self._connect(self.database_url, row_factory=dict_row) as connection:
            rows = connection.execute(
                """
                SELECT snapshot.id, member.universe_version, snapshot.as_of_time
                FROM analytics.data_snapshot snapshot
                JOIN analytics.snapshot_universe_member member
                  ON member.snapshot_id = snapshot.id
                JOIN analytics.security_profile_snapshot profile
                  ON profile.data_snapshot_id = snapshot.id
                 AND profile.security_id = member.security_id
                WHERE snapshot.status = 'READY'
                GROUP BY snapshot.id, member.universe_version, snapshot.as_of_time
                HAVING COUNT(DISTINCT member.security_id) = %s
                   AND COUNT(DISTINCT profile.security_id) = %s
                   AND COUNT(profile.id) = %s
                ORDER BY snapshot.as_of_time DESC, snapshot.id, member.universe_version
                LIMIT 1
                """,
                (
                    self.expected_population,
                    self.expected_population,
                    self.expected_population,
                ),
            ).fetchall()
        if not rows:
            raise ForwardV2DbSnapshotError(
                "No READY snapshot has exactly one profile for every closed-universe member"
            )
        return rows[0]["id"], rows[0]["universe_version"]

    def assemble(
        self,
        *,
        data_snapshot_id: UUID,
        universe_version: str,
        idempotency_key: str,
        sealed_at: datetime,
    ) -> DbDecisionSnapshotAssembly:
        sealed_at = _aware(sealed_at, "Decision seal timestamp")
        with self._connect(self.database_url, row_factory=dict_row) as connection:
            evidence = self._load_db_evidence(
                connection,
                data_snapshot_id=data_snapshot_id,
                universe_version=universe_version,
            )
            series = {
                item.public_security_id: self._load_price_series(
                    connection,
                    evidence=evidence,
                    member=item,
                )
                for item in evidence.members
            }
        return self._seal_loaded_evidence(
            evidence=evidence,
            series=series,
            idempotency_key=idempotency_key,
            sealed_at=sealed_at,
        )

    def _seal_loaded_evidence(
        self,
        *,
        evidence: SnapshotDbEvidence,
        series: dict[UUID, _SeriesResult],
        idempotency_key: str,
        sealed_at: datetime,
    ) -> DbDecisionSnapshotAssembly:
        expected_ids = {item.public_security_id for item in evidence.members}
        if set(series) != expected_ids:
            raise ForwardV2DbSnapshotError(
                "Loaded price evidence must cover the exact frozen population"
            )
        market_series = (
            series[evidence.market_benchmark_id]
            if evidence.market_benchmark_id is not None
            else _SeriesResult(
                SeriesEvidenceV22(
                    state=EvidenceState.MISSING,
                    provider=None,
                    source_hash=None,
                    available_at=None,
                    ingested_at=None,
                ),
                None,
            )
        )
        benchmark_evidence = self._benchmark_evidence(evidence, series, market_series)
        decisions = tuple(
            self._build_member_decision(
                evidence=evidence,
                member=member,
                security_series=series[member.public_security_id],
                market_series=market_series,
                sector_series=(
                    series[evidence.sector_benchmark_ids[member.normalized_sector]]
                    if member.normalized_sector in evidence.sector_benchmark_ids
                    else _SeriesResult(
                        SeriesEvidenceV22(
                            state=EvidenceState.MISSING,
                            provider=None,
                            source_hash=None,
                            available_at=None,
                            ingested_at=None,
                        ),
                        None,
                    )
                ),
            )
            for member in evidence.members
        )
        freezes = (
            load_sealed_model_freeze(
                repository_root=self.repository_root,
                artifact_path=(
                    self.repository_root / "docs/generated/tactical-v2-2-model-freeze.json"
                ),
                track=ModelTrack.TACTICAL,
            ),
            load_sealed_model_freeze(
                repository_root=self.repository_root,
                artifact_path=(
                    self.repository_root / "docs/generated/long-horizon-v1-1-model-freeze.json"
                ),
                track=ModelTrack.LONG_HORIZON,
            ),
        )
        bundle = build_decision_snapshot(
            idempotency_key=idempotency_key,
            sealed_at=sealed_at,
            data_snapshot=evidence.data_snapshot,
            model_freezes=freezes,
            benchmark_evidence=benchmark_evidence,
            cost_policy=CostPolicyBinding(
                policy_version="LIQUIDITY-SENSITIVE-COST-v1.0.0",
                contract_hash=freezes[0].cost_model_hash,
            ),
            evidence_envelope=ValidationEvidenceEnvelope(
                outcome_dependence=OutcomeDependence.NON_OVERLAPPING
            ),
            frozen_security_ids=tuple(
                item.public_security_id for item in evidence.members
            ),
            decisions=decisions,
        )
        audit_event = build_v16_audit_event_payload(bundle)
        counts: dict[str, int] = {}
        for member in evidence.members:
            counts[member.membership_status] = counts.get(member.membership_status, 0) + 1
        return DbDecisionSnapshotAssembly(
            assembler_version=DB_DECISION_ASSEMBLER_VERSION,
            bundle=bundle,
            audit_event=audit_event,
            member_role_hash=evidence.member_role_hash,
            membership_counts=counts,
        )

    def _load_db_evidence(
        self,
        connection,
        *,
        data_snapshot_id: UUID,
        universe_version: str,
    ) -> SnapshotDbEvidence:
        snapshot = connection.execute(
            """
            SELECT id, status, as_of_time, ingestion_cutoff, manifest_hash,
                   security_count, source_count, sealed_at,
                   market_normalization_version,
                   fundamental_normalization_version,
                   action_normalization_version,
                   market_data_provider, market_adjustment_mode
            FROM analytics.data_snapshot
            WHERE id = %s
            """,
            (data_snapshot_id,),
        ).fetchone()
        if snapshot is None or snapshot["status"] != "READY":
            raise ForwardV2DbSnapshotError("Data snapshot must exist and be READY")
        if snapshot["security_count"] != self.expected_population:
            raise ForwardV2DbSnapshotError(
                f"READY snapshot must declare exactly {self.expected_population} securities"
            )
        as_of = _aware(snapshot["as_of_time"], "READY snapshot as-of")
        ingestion_cutoff = _aware(snapshot["ingestion_cutoff"], "READY ingestion cutoff")
        if ingestion_cutoff < as_of:
            raise ForwardV2DbSnapshotError("READY ingestion cutoff precedes its as-of")

        universe = connection.execute(
            """
            SELECT version, effective_at, configuration, configuration_hash
            FROM analytics.universe_definition
            WHERE version = %s
            """,
            (universe_version,),
        ).fetchone()
        if universe is None:
            raise ForwardV2DbSnapshotError("Universe definition does not exist")
        member_rows = connection.execute(
            """
            SELECT security.id AS database_security_id, security.public_id,
                   member.symbol_at_snapshot, member.membership_status,
                   member.membership_reason, member.company_type_at_snapshot,
                   member.normalized_sector_at_snapshot,
                   profile.id AS profile_id, profile.snapshot_as_of,
                   profile.contract_version, profile.input_payload_hash
            FROM analytics.snapshot_universe_member member
            JOIN analytics.security security ON security.id = member.security_id
            LEFT JOIN analytics.security_profile_snapshot profile
              ON profile.data_snapshot_id = member.snapshot_id
             AND profile.security_id = member.security_id
            WHERE member.snapshot_id = %s
              AND member.universe_version = %s
            ORDER BY security.public_id, profile.id
            """,
            (data_snapshot_id, universe_version),
        ).fetchall()
        if len(member_rows) != self.expected_population:
            raise ForwardV2DbSnapshotError(
                f"Closed universe must contain exactly {self.expected_population} profile rows"
            )
        if any(item["profile_id"] is None for item in member_rows):
            raise ForwardV2DbSnapshotError("Every universe member requires one V17 profile")
        public_ids = [item["public_id"] for item in member_rows]
        profile_ids = [item["profile_id"] for item in member_rows]
        database_ids = [item["database_security_id"] for item in member_rows]
        if len(set(public_ids)) != len(public_ids):
            raise ForwardV2DbSnapshotError("Closed universe has duplicate public security IDs")
        if len(set(profile_ids)) != len(profile_ids) or len(set(database_ids)) != len(database_ids):
            raise ForwardV2DbSnapshotError(
                "Closed universe must bind exactly one profile to each security"
            )
        if any(item["snapshot_as_of"] != as_of for item in member_rows):
            raise ForwardV2DbSnapshotError(
                "Every V17 profile must use the exact READY snapshot as-of"
            )
        if any(
            item["contract_version"] != MARKET_INTELLIGENCE_VERSION
            for item in member_rows
        ):
            raise ForwardV2DbSnapshotError(
                "Every profile must use the accepted Market Intelligence contract"
            )
        members = tuple(
            SnapshotMemberEvidence(
                database_security_id=item["database_security_id"],
                public_security_id=item["public_id"],
                profile_id=item["profile_id"],
                symbol=item["symbol_at_snapshot"],
                membership_status=item["membership_status"],
                membership_reason=item["membership_reason"],
                company_type=item["company_type_at_snapshot"],
                normalized_sector=item["normalized_sector_at_snapshot"],
                profile_contract_version=item["contract_version"],
                profile_input_payload_hash=item["input_payload_hash"],
            )
            for item in member_rows
        )
        fact_rows = connection.execute(
            """
            SELECT fact.profile_id, fact.fact_name, observation.metric_version,
                   observation.status, observation.numeric_value,
                   COALESCE(observation.reason_detail, observation.reason_code) AS reason,
                   observation.period_start, observation.period_end,
                   observation.available_at AS observation_available_at,
                   observation.ingested_at AS observation_ingested_at,
                   lineage.available_at AS lineage_available_at,
                   lineage.retrieved_at AS lineage_retrieved_at,
                   source.content_hash
            FROM analytics.security_profile_fact fact
            JOIN analytics.metric_observation observation
              ON observation.id = fact.metric_observation_id
            LEFT JOIN analytics.security_profile_fact_lineage lineage
              ON lineage.profile_id = fact.profile_id
             AND lineage.fact_name = fact.fact_name
            LEFT JOIN analytics.source_record source
              ON source.id = lineage.source_record_id
            WHERE fact.profile_id = ANY(%s::uuid[])
            ORDER BY fact.profile_id, fact.fact_name, source.content_hash
            """,
            (profile_ids,),
        ).fetchall()
        facts_by_profile: dict[UUID, dict[tuple[str, str], dict[str, Any]]] = {
            item.profile_id: {} for item in members
        }
        for row in fact_rows:
            key = (row["fact_name"], row["metric_version"])
            aggregate = facts_by_profile[row["profile_id"]].setdefault(
                key,
                {
                    "name": row["fact_name"],
                    "metric_version": row["metric_version"],
                    "state": row["status"],
                    "numeric_value": row["numeric_value"],
                    "reason": row["reason"],
                    "period_start": row["period_start"],
                    "period_end": row["period_end"],
                    "available_times": [row["observation_available_at"]],
                    "ingested_times": [row["observation_ingested_at"]],
                    "source_hashes": [],
                },
            )
            if row["lineage_available_at"] is not None:
                aggregate["available_times"].append(row["lineage_available_at"])
            if row["lineage_retrieved_at"] is not None:
                aggregate["ingested_times"].append(row["lineage_retrieved_at"])
            if row["content_hash"] is not None:
                aggregate["source_hashes"].append(row["content_hash"])
        profile_facts = {
            profile_id: tuple(
                ProfileFactEvidence(
                    name=value["name"],
                    metric_version=value["metric_version"],
                    state=value["state"],
                    numeric_value=value["numeric_value"],
                    reason=value["reason"],
                    source_hashes=tuple(sorted(set(value["source_hashes"]))),
                    period_start=value["period_start"],
                    period_end=value["period_end"],
                    available_at=max(value["available_times"]),
                    ingested_at=max(value["ingested_times"]),
                )
                for value in sorted(items.values(), key=lambda item: item["name"])
            )
            for profile_id, items in facts_by_profile.items()
        }
        sources = connection.execute(
            """
            SELECT batch.id, provider.code, provider.provider_schema_version,
                   batch.request_key, batch.status, batch.parser_version,
                   batch.normalization_version, batch.started_at,
                   batch.completed_at
            FROM analytics.data_snapshot_source snapshot_source
            JOIN analytics.ingestion_batch batch
              ON batch.id = snapshot_source.ingestion_batch_id
            JOIN analytics.data_provider provider ON provider.id = batch.provider_id
            WHERE snapshot_source.snapshot_id = %s
            ORDER BY batch.id
            """,
            (data_snapshot_id,),
        ).fetchall()
        if len(sources) != snapshot["source_count"]:
            raise ForwardV2DbSnapshotError("READY snapshot source count is inconsistent")
        if any(item["status"] != "SUCCEEDED" for item in sources):
            raise ForwardV2DbSnapshotError(
                "READY snapshot contains a non-successful ingestion batch"
            )

        member_payload = [
            {
                "publicSecurityId": str(item.public_security_id),
                "profileId": str(item.profile_id),
                "symbol": item.symbol,
                "membershipStatus": item.membership_status,
                "membershipReason": item.membership_reason,
                "companyType": item.company_type,
                "normalizedSector": item.normalized_sector,
            }
            for item in members
        ]
        member_role_hash = _hash_payload(member_payload)
        universe_hash = _hash_payload(
            {
                "version": universe["version"],
                "effectiveAt": universe["effective_at"],
                "configuration": universe["configuration"],
                "configurationHash": universe["configuration_hash"],
                "members": member_payload,
            }
        )
        source_snapshot_hash = _hash_payload(
            {
                "snapshotId": str(snapshot["id"]),
                "asOf": as_of,
                "ingestionCutoff": ingestion_cutoff,
                "manifestHash": snapshot["manifest_hash"],
                "sealedAt": snapshot["sealed_at"],
                "normalizationVersions": {
                    "market": snapshot["market_normalization_version"],
                    "fundamental": snapshot["fundamental_normalization_version"],
                    "action": snapshot["action_normalization_version"],
                },
                "marketProvider": snapshot["market_data_provider"],
                "adjustmentMode": snapshot["market_adjustment_mode"],
                "sources": [
                    {
                        "batchId": str(item["id"]),
                        "provider": item["code"],
                        "providerSchemaVersion": item["provider_schema_version"],
                        "requestKey": item["request_key"],
                        "status": item["status"],
                        "parserVersion": item["parser_version"],
                        "normalizationVersion": item["normalization_version"],
                        "startedAt": item["started_at"],
                        "completedAt": item["completed_at"],
                    }
                    for item in sources
                ],
            }
        )
        profile_set_hash = _hash_payload(sorted(str(item.profile_id) for item in members))
        market_candidates = [
            item for item in members if item.symbol.upper() == MARKET_BENCHMARK_SYMBOL
        ]
        if len(market_candidates) > 1:
            raise ForwardV2DbSnapshotError("Market benchmark identity is ambiguous")
        sector_benchmarks: dict[str, UUID] = {}
        for item in members:
            reason = item.membership_reason.upper()
            if item.membership_status != "REFERENCE_ONLY" or not reason.startswith(
                "SECTOR_BENCHMARK"
            ):
                continue
            if not item.normalized_sector:
                raise ForwardV2DbSnapshotError("Sector benchmark has no frozen sector")
            if item.normalized_sector in sector_benchmarks:
                raise ForwardV2DbSnapshotError("Sector benchmark identity is ambiguous")
            sector_benchmarks[item.normalized_sector] = item.public_security_id
        return SnapshotDbEvidence(
            data_snapshot=ReadyDataSnapshotBinding(
                data_snapshot_id=data_snapshot_id,
                state="READY",
                as_of=as_of,
                universe_version=universe_version,
                universe_hash=universe_hash,
                profile_set_hash=profile_set_hash,
                source_snapshot_hash=source_snapshot_hash,
            ),
            ingestion_cutoff=ingestion_cutoff,
            market_provider=snapshot["market_data_provider"],
            adjustment_mode=snapshot["market_adjustment_mode"],
            members=members,
            profile_facts=profile_facts,
            market_benchmark_id=(
                market_candidates[0].public_security_id if market_candidates else None
            ),
            sector_benchmark_ids=sector_benchmarks,
            member_role_hash=member_role_hash,
        )

    def _load_price_series(
        self,
        connection,
        *,
        evidence: SnapshotDbEvidence,
        member: SnapshotMemberEvidence,
    ) -> _SeriesResult:
        rows = connection.execute(
            """
            SELECT *
            FROM (
                SELECT DISTINCT ON (observation.trading_date)
                       observation.trading_date, observation.open_price,
                       observation.high_price, observation.low_price,
                       observation.close_price, observation.adjusted_close,
                       observation.volume, observation.revision_number,
                       observation.available_at, observation.ingested_at,
                       observation.quality_status, source.content_hash,
                       provider.code, provider.provider_schema_version,
                       batch.parser_version, observation.normalization_version
                FROM analytics.daily_price_observation observation
                JOIN analytics.data_provider provider
                  ON provider.id = observation.provider_id
                JOIN analytics.source_record source
                  ON source.id = observation.source_record_id
                JOIN analytics.ingestion_batch batch
                  ON batch.id = source.ingestion_batch_id
                JOIN analytics.data_snapshot_source snapshot_source
                  ON snapshot_source.ingestion_batch_id = batch.id
                WHERE snapshot_source.snapshot_id = %s
                  AND observation.security_id = %s
                  AND provider.code = %s
                  AND observation.adjustment_mode = %s
                  AND observation.trading_date <= %s::date
                  AND observation.available_at <= %s
                  AND observation.ingested_at <= %s
                  AND observation.quality_status <> 'REJECTED'
                ORDER BY observation.trading_date,
                         observation.revision_number DESC,
                         observation.available_at DESC,
                         observation.ingested_at DESC
            ) selected
            ORDER BY selected.trading_date
            """,
            (
                evidence.data_snapshot.data_snapshot_id,
                member.database_security_id,
                evidence.market_provider,
                evidence.adjustment_mode,
                evidence.data_snapshot.as_of,
                evidence.data_snapshot.as_of,
                evidence.ingestion_cutoff,
            ),
        ).fetchall()
        if not rows:
            return _SeriesResult(
                SeriesEvidenceV22(
                    state=EvidenceState.MISSING,
                    provider=None,
                    source_hash=None,
                    available_at=None,
                    ingested_at=None,
                ),
                None,
            )
        invalid = any(
            row["open_price"] <= 0
            or row["high_price"] <= 0
            or row["low_price"] <= 0
            or row["close_price"] <= 0
            or row["volume"] <= 0
            or row["quality_status"] != "VALIDATED"
            for row in rows
        )
        latest_date = rows[-1]["trading_date"]
        stale = latest_date < (
            evidence.data_snapshot.as_of.date() - timedelta(days=self.max_price_age_days)
        )
        state = (
            EvidenceState.INVALID
            if invalid
            else EvidenceState.STALE
            if stale
            else EvidenceState.VALID
        )
        bars: list[TacticalBarV22] = []
        for row in rows:
            close = Decimal(row["close_price"])
            adjusted = (
                Decimal(row["adjusted_close"])
                if row["adjusted_close"] is not None
                else close
            )
            factor = adjusted / close if close else Decimal(1)
            bars.append(
                TacticalBarV22(
                    trading_date=row["trading_date"],
                    open_price=float(Decimal(row["open_price"]) * factor),
                    high_price=float(Decimal(row["high_price"]) * factor),
                    low_price=float(Decimal(row["low_price"]) * factor),
                    close_price=float(adjusted),
                    volume=row["volume"],
                    adjustment_factor=float(factor),
                    session_complete=True,
                )
            )
        source_hash = _hash_payload(
            [
                {
                    "tradingDate": row["trading_date"],
                    "revisionNumber": row["revision_number"],
                    "sourceHash": row["content_hash"],
                    "availableAt": row["available_at"],
                    "ingestedAt": row["ingested_at"],
                    "qualityStatus": row["quality_status"],
                    "normalizationVersion": row["normalization_version"],
                    "adjustedOhlcvHash": _hash_payload(asdict(bar)),
                }
                for row, bar in zip(rows, bars, strict=True)
            ]
        )
        return _SeriesResult(
            SeriesEvidenceV22(
                state=state,
                provider=evidence.market_provider,
                source_hash=source_hash,
                available_at=max(item["available_at"] for item in rows),
                ingested_at=max(item["ingested_at"] for item in rows),
                bars=tuple(bars),
            ),
            latest_date,
        )

    def _benchmark_evidence(
        self,
        evidence: SnapshotDbEvidence,
        series: dict[UUID, _SeriesResult],
        market_series: _SeriesResult,
    ) -> tuple[BenchmarkEvidenceBinding, ...]:
        result = [
            BenchmarkEvidenceBinding(
                benchmark_kind="MARKET",
                benchmark_id=MARKET_BENCHMARK_SYMBOL,
                version="SNAPSHOT-BOUND-DAILY-PRICE-v1",
                availability=_benchmark_state(market_series.evidence.state),
                evidence_hash=(
                    market_series.evidence.source_hash
                    if market_series.evidence.state == EvidenceState.VALID
                    else None
                ),
                reason=(
                    None
                    if market_series.evidence.state == EvidenceState.VALID
                    else f"MARKET_BENCHMARK_{market_series.evidence.state.value}"
                ),
            )
        ]
        sector_names = sorted(
            {
                item.normalized_sector
                for item in evidence.members
                if item.normalized_sector is not None
            }
        )
        for sector_name in sector_names:
            benchmark_id = f"SECTOR:{sector_name}"
            public_id = evidence.sector_benchmark_ids.get(sector_name)
            sector = series.get(public_id) if public_id else None
            state = (
                sector.evidence.state
                if sector is not None
                else EvidenceState.MISSING
            )
            result.append(
                BenchmarkEvidenceBinding(
                    benchmark_kind="SECTOR",
                    benchmark_id=benchmark_id,
                    version="FROZEN-SECTOR-BENCHMARK-MAPPING-v1",
                    availability=_benchmark_state(state),
                    evidence_hash=(
                        sector.evidence.source_hash
                        if sector is not None and state == EvidenceState.VALID
                        else None
                    ),
                    reason=(
                        None
                        if state == EvidenceState.VALID
                        else f"SECTOR_BENCHMARK_{state.value}"
                    ),
                )
            )
        return tuple(result)

    def _build_member_decision(
        self,
        *,
        evidence: SnapshotDbEvidence,
        member: SnapshotMemberEvidence,
        security_series: _SeriesResult,
        market_series: _SeriesResult,
        sector_series: _SeriesResult,
    ) -> SecurityDecisionRecord:
        sector_id = (
            f"SECTOR:{member.normalized_sector}"
            if member.normalized_sector is not None
            else None
        )
        required_series = (security_series, market_series, sector_series)
        if all(item.evidence.state == EvidenceState.VALID for item in required_series):
            shared_dates = {
                item.trading_date for item in security_series.evidence.bars
            }.intersection(
                item.trading_date for item in market_series.evidence.bars
            ).intersection(
                item.trading_date for item in sector_series.evidence.bars
            )
            if len(shared_dates) < 21:
                sector_series = _SeriesResult(
                    evidence=replace(
                        sector_series.evidence,
                        state=EvidenceState.MISSING,
                    ),
                    latest_trading_date=sector_series.latest_trading_date,
                )
                as_of_date = evidence.data_snapshot.as_of.date()
            else:
                as_of_date = max(shared_dates)
        else:
            latest_dates = tuple(
                item.latest_trading_date
                for item in required_series
                if item.latest_trading_date is not None
            )
            as_of_date = (
                min(latest_dates)
                if latest_dates
                else evidence.data_snapshot.as_of.date()
            )
        context = TacticalContextV22(
            security_id=str(member.public_security_id),
            decision_cutoff=evidence.data_snapshot.as_of,
            as_of_date=as_of_date,
            security=security_series.evidence,
            market_benchmark_id=MARKET_BENCHMARK_SYMBOL,
            market=market_series.evidence,
            sector_benchmark_id=sector_id,
            sector=sector_series.evidence,
            event=EventEvidenceV22(
                state=EvidenceState.MISSING,
                risk_level=None,
                source_hash=None,
                available_at=None,
                ingested_at=None,
            ),
            sector_mapping_version=evidence.data_snapshot.universe_version,
            sector_mapping_hash=evidence.data_snapshot.universe_hash,
        )
        tactical = evaluate_tactical_signal_v22(context)
        long_inputs, long_input_hash, long_evidence_hash = _long_inputs(
            member,
            evidence.profile_facts[member.profile_id],
            cutoff=evidence.ingestion_cutoff,
        )
        long_assessment = evaluate_long_horizon_v11(long_inputs)
        tactical_override, long_override, exclusions = _membership_terminal_overrides(member)
        if member.membership_status == "INCLUDED" and tactical_override is None:
            tactical_override = _included_tactical_state(
                tactical,
                (
                    security_series.evidence.state,
                    market_series.evidence.state,
                    sector_series.evidence.state,
                ),
            )
        return build_security_decision(
            public_security_id=member.public_security_id,
            profile_id=member.profile_id,
            symbol=member.symbol,
            tactical_assessment=tactical,
            long_horizon_assessment=long_assessment,
            long_horizon_input_hash=long_input_hash,
            long_horizon_evidence_hash=long_evidence_hash,
            tactical_state=tactical_override,
            long_horizon_state=long_override,
            exclusion_reasons=exclusions,
        )


class ForwardV2AuditEventRepository:
    """Persist one immutable V16 audit handoff with exact replay/conflict semantics."""

    def __init__(
        self,
        database_url: str,
        *,
        connect: Callable[..., Any] = psycopg.connect,
    ) -> None:
        if not database_url:
            raise ValueError("Analytics database URL is required")
        self.database_url = database_url
        self._connect = connect

    def persist(self, event: AuditEventPayload) -> PersistedAuditEvent:
        expected_hash = _hash_payload(event.detail)
        if event.event_hash != expected_hash:
            raise ForwardV2DbSnapshotError("V16 audit event hash is invalid")
        with self._connect(self.database_url, row_factory=dict_row) as connection:
            connection.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (event.correlation_id,),
            )
            existing = connection.execute(
                """
                SELECT id, event_hash, detail
                FROM analytics.analytics_audit_event
                WHERE event_type = %s AND correlation_id = %s
                ORDER BY recorded_at, id
                LIMIT 1
                """,
                (event.event_type, event.correlation_id),
            ).fetchone()
            if existing is not None:
                if (
                    existing["event_hash"] != event.event_hash
                    or _hash_payload(existing["detail"]) != expected_hash
                ):
                    raise ForwardV2DbConflictError(
                        "Forward v2 idempotency key is associated with different evidence"
                    )
                return PersistedAuditEvent(
                    audit_event_id=existing["id"],
                    event_hash=existing["event_hash"],
                    replayed=True,
                )
            inserted = connection.execute(
                """
                INSERT INTO analytics.analytics_audit_event (
                    event_type, entity_type, entity_id, actor_service,
                    occurred_at, correlation_id, event_hash, detail
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                ON CONFLICT (event_hash) DO NOTHING
                RETURNING id
                """,
                (
                    event.event_type,
                    event.entity_type,
                    event.entity_id,
                    event.actor_service,
                    event.occurred_at,
                    event.correlation_id,
                    event.event_hash,
                    _json(event.detail),
                ),
            ).fetchone()
            if inserted is not None:
                return PersistedAuditEvent(
                    audit_event_id=inserted["id"],
                    event_hash=event.event_hash,
                    replayed=False,
                )
            duplicate = connection.execute(
                """
                SELECT id, event_type, correlation_id, event_hash, detail
                FROM analytics.analytics_audit_event
                WHERE event_hash = %s
                """,
                (event.event_hash,),
            ).fetchone()
            if (
                duplicate is None
                or duplicate["event_type"] != event.event_type
                or duplicate["correlation_id"] != event.correlation_id
                or _hash_payload(duplicate["detail"]) != expected_hash
            ):
                raise ForwardV2DbConflictError(
                    "Forward v2 audit hash is associated with different evidence"
                )
            return PersistedAuditEvent(
                audit_event_id=duplicate["id"],
                event_hash=duplicate["event_hash"],
                replayed=True,
            )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Seal one database-backed Forward v2 closed-population decision snapshot."
    )
    parser.add_argument("--database-url-env", default="MARKET_INTELLIGENCE_V17_TEST_DATABASE_URL")
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--latest-ready", action="store_true")
    selection.add_argument("--data-snapshot-id", type=UUID)
    parser.add_argument("--universe-version")
    parser.add_argument("--idempotency-key", required=True)
    parser.add_argument("--sealed-at", type=datetime.fromisoformat, required=True)
    parser.add_argument("--manifest-path", type=Path, required=True)
    parser.add_argument("--persist-audit", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    database_url = os.getenv(args.database_url_env)
    if not database_url:
        raise SystemExit(f"{args.database_url_env} is not configured")
    assembler = ForwardV2DbDecisionAssembler(
        database_url,
        repository_root=args.repository_root.resolve(),
    )
    if args.latest_ready:
        snapshot_id, universe_version = assembler.latest_ready_closed_snapshot()
    else:
        if args.universe_version is None:
            raise SystemExit("--universe-version is required with --data-snapshot-id")
        snapshot_id = args.data_snapshot_id
        universe_version = args.universe_version
    assert snapshot_id is not None
    assembly = assembler.assemble(
        data_snapshot_id=snapshot_id,
        universe_version=universe_version,
        idempotency_key=args.idempotency_key,
        sealed_at=args.sealed_at,
    )
    controlled_path, manifest_path = write_snapshot_bundle(
        assembly.bundle,
        repository_root=args.repository_root.resolve(),
        manifest_path=args.manifest_path.resolve(),
    )
    persisted = None
    if args.persist_audit:
        persisted = ForwardV2AuditEventRepository(database_url).persist(assembly.audit_event)
    print(
        json.dumps(
            {
                "assemblerVersion": assembly.assembler_version,
                "dataSnapshotId": str(snapshot_id),
                "universeVersion": universe_version,
                "securityCount": assembly.bundle.manifest.security_count,
                "membershipCounts": assembly.membership_counts,
                "memberRoleHash": assembly.member_role_hash,
                "controlledArtifact": str(controlled_path),
                "controlledArtifactHash": assembly.bundle.controlled_artifact_hash,
                "manifest": str(manifest_path),
                "manifestContentHash": assembly.bundle.manifest.manifest_content_hash,
                "prospectiveReady": assembly.bundle.snapshot.prospective_ready,
                "blockedReasons": assembly.bundle.snapshot.blocked_reasons,
                "auditEventId": str(persisted.audit_event_id) if persisted else None,
                "auditEventHash": persisted.event_hash if persisted else None,
                "auditReplay": persisted.replayed if persisted else None,
                "providerNetworkRequests": 0,
                "aiUsedForDeterministicDecisions": False,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
