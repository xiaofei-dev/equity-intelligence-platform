from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_HALF_EVEN, Decimal
from hashlib import sha256
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

import psycopg

from equity_analysis.market_intelligence.objective_gate_replay_v1 import (
    REPLAY_VERSION,
    ObjectiveGateReplayPlan,
    build_objective_gate_replay_plan,
)
from equity_analysis.provider_validation.expansion_gate import canonical_hash
from equity_analysis.screening.config import QC_VERSION, QC_WEIGHTS
from equity_analysis.screening.current_snapshot_algorithm_gate_v1 import (
    QC_RAW_FACTORS,
    VALUATION_INPUTS,
    valuation_guardrail_score,
)
from equity_analysis.screening.models import (
    CompanyType,
    FactorInput,
    FactorStatus,
    SecurityObservation,
    SizeCohort,
)
from equity_analysis.screening.normalization import normalize_observations

CONTROLLED_PROVIDER = "objective_current_gate"
CONTROLLED_PROVIDER_SCHEMA = "objective-current-gate-v1"
FACTOR_VERSION = "v1.0.0"
SCORE_QUANTUM = Decimal("0.0001")
SUPPLEMENTAL_SOURCE_MARKER = "cached-profile-replay-v1"
SUPPLEMENTAL_CLASSIFICATION_VERSION = "provider-current-replay-v1.0.0"


@dataclass(frozen=True)
class ObjectiveGateReplayReceipt:
    snapshot_id: UUID
    snapshot_key: str
    screening_run_id: UUID
    objective_scored_count: int
    insufficient_data_count: int
    non_applicable_count: int
    source_record_count: int
    gate_content_hash: str
    supplemental_batch_count: int = 0
    supplemental_source_count: int = 0
    supplemental_aggregate_hash: str | None = None
    effective_as_of_time: datetime | None = None
    effective_ingestion_cutoff: datetime | None = None
    network_requests_executed: bool = False
    full_market_intelligence_eligibility_claimed: bool = False


@dataclass(frozen=True)
class SupplementalReplaySource:
    batch_id: UUID
    source_record_id: UUID
    security_id: int
    security_public_id: UUID
    symbol: str
    normalized_sector: str
    content_hash: str
    storage_reference: str
    available_at: datetime
    ingested_at: datetime


@dataclass(frozen=True)
class SupplementalReplayEvidence:
    batch_ids: tuple[UUID, ...]
    sources: tuple[SupplementalReplaySource, ...]
    aggregate_hash: str
    maximum_available_at: datetime
    maximum_ingested_at: datetime

    @property
    def sectors_by_security_id(self) -> dict[int, str]:
        return {
            source.security_id: source.normalized_sector
            for source in self.sources
        }

    @property
    def source_ids_by_symbol(self) -> dict[str, UUID]:
        return {
            source.symbol: source.source_record_id
            for source in self.sources
        }


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"), parse_float=Decimal)


def _q(value: Decimal) -> Decimal:
    return value.quantize(SCORE_QUANTUM, rounding=ROUND_HALF_EVEN)


def _sha(value: Any) -> str:
    return "sha256:" + canonical_hash(value).lower()


def _deterministic_uuid(kind: str, *parts: str) -> UUID:
    return uuid5(NAMESPACE_URL, ":".join((kind, *parts)))


def _normalized_inputs(
    *,
    repository_root: Path,
    manifest: dict[str, Any],
    gate: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    configured_weights = {
        name: Decimal(str(value)) for name, value in gate.get("weights", {}).items()
    }
    if configured_weights != QC_WEIGHTS:
        raise ValueError("OBJECTIVE_GATE_WEIGHT_MISMATCH")
    manifest_by_symbol = {
        item["symbol"]: item for item in manifest["securities"]
    }
    observations: list[SecurityObservation] = []
    as_of = datetime.fromisoformat(str(gate["asOfTime"]).replace("Z", "+00:00"))
    for gate_item in gate["securities"]:
        symbol = gate_item["symbol"]
        source = manifest_by_symbol[symbol]
        payload = _load(repository_root / source["storageReference"])
        raw = payload["qcRawFactors"]
        factor_names = (*QC_RAW_FACTORS, *VALUATION_INPUTS)
        observations.append(
            SecurityObservation(
                security_id=f"US:{symbol}",
                symbol=symbol,
                as_of_time=as_of,
                sector=gate_item["sector"],
                size_cohort=SizeCohort(gate_item["sizeCohort"]),
                company_type=CompanyType.MATURE_OPERATING_COMPANY,
                factors=tuple(
                    FactorInput(
                        name=name,
                        value=Decimal(str(raw[name])),
                        status=FactorStatus.VALID,
                    )
                    for name in factor_names
                ),
            )
        )
    normalized = normalize_observations(observations)
    result: dict[str, dict[str, Any]] = {}
    ranked_scores: list[tuple[Decimal, str]] = []
    for gate_item in gate["securities"]:
        symbol = gate_item["symbol"]
        by_name = {
            factor.name: factor for factor in normalized[f"US:{symbol}"]
        }
        contributions: dict[str, Decimal] = {}
        for name in QC_RAW_FACTORS:
            gate_factor = gate_item["factorScores"][name]
            expected = Decimal(str(gate_factor["normalizedScore"]))
            factor = by_name[name]
            if (
                factor.normalized_score != expected
                or factor.cohort_level != gate_factor["cohortLevel"]
                or factor.cohort_size != gate_factor["cohortSize"]
            ):
                raise ValueError(f"OBJECTIVE_GATE_RECOMPUTE_MISMATCH[{symbol}:{name}]")
            contribution = _q(factor.normalized_score * QC_WEIGHTS[name])
            if contribution != Decimal(str(gate_factor["contribution"])):
                raise ValueError(
                    f"OBJECTIVE_GATE_CONTRIBUTION_MISMATCH[{symbol}:{name}]"
                )
            contributions[name] = contribution
        valuation_gate = gate_item["factorScores"]["valuation_guardrail"]
        for name, percentile_name in (
            ("earnings_yield", "earningsYieldPercentile"),
            ("fcf_yield", "fcfYieldPercentile"),
        ):
            factor = by_name[name]
            if factor.normalized_score != Decimal(
                str(valuation_gate[percentile_name])
            ):
                raise ValueError(
                    f"OBJECTIVE_GATE_RECOMPUTE_MISMATCH[{symbol}:{name}]"
                )
        valuation = valuation_guardrail_score(
            by_name["earnings_yield"].normalized_score,
            by_name["fcf_yield"].normalized_score,
        )
        if valuation != Decimal(str(valuation_gate["normalizedScore"])):
            raise ValueError(
                f"OBJECTIVE_GATE_RECOMPUTE_MISMATCH[{symbol}:valuation_guardrail]"
            )
        valuation_contribution = _q(
            valuation * QC_WEIGHTS["valuation_guardrail"]
        )
        if valuation_contribution != Decimal(str(valuation_gate["contribution"])):
            raise ValueError(
                f"OBJECTIVE_GATE_CONTRIBUTION_MISMATCH[{symbol}:valuation_guardrail]"
            )
        contributions["valuation_guardrail"] = valuation_contribution
        score = _q(sum(contributions.values(), Decimal(0)))
        if score != Decimal(str(gate_item["score"])):
            raise ValueError(f"OBJECTIVE_GATE_SCORE_MISMATCH[{symbol}]")
        ranked_scores.append((score, symbol))
        result[symbol] = {
            "factors": by_name,
            "valuation_guardrail": valuation,
            "contributions": contributions,
            "score": score,
        }
    expected_order = [
        symbol
        for _, symbol in sorted(
            ranked_scores,
            key=lambda item: (-item[0], item[1]),
        )
    ]
    actual_order = [
        item["symbol"]
        for item in sorted(gate["securities"], key=lambda item: item["rank"])
    ]
    if actual_order != expected_order:
        raise ValueError("OBJECTIVE_GATE_RANK_ORDER_MISMATCH")
    gate_by_symbol = {item["symbol"]: item for item in gate["securities"]}
    for expected_rank, symbol in enumerate(expected_order, start=1):
        gate_item = gate_by_symbol[symbol]
        if gate_item["rank"] != expected_rank:
            raise ValueError(f"OBJECTIVE_GATE_RANK_MISMATCH[{symbol}]")
        result[symbol]["rank"] = expected_rank
    return result


class ObjectiveGateReplayPostgresWriter:
    """Append an accepted current-only Objective gate to a cloned V17 snapshot.

    The writer never mutates the source snapshot and never performs network I/O.
    It persists Objective QC availability separately from the broader Market
    Intelligence eligibility state.
    """

    def __init__(self, database_url: str, repository_root: Path) -> None:
        if not database_url:
            raise ValueError("Analytics database URL is required")
        self.database_url = database_url
        self.repository_root = repository_root.resolve()

    def replay(
        self,
        *,
        source_snapshot_id: UUID,
        universe_version: str,
        input_manifest_path: Path,
        algorithm_gate_path: Path,
        closed_pool_audit_path: Path,
        supplemental_ingestion_batch_ids: tuple[UUID, ...] = (),
    ) -> ObjectiveGateReplayReceipt:
        plan = build_objective_gate_replay_plan(
            repository_root=self.repository_root,
            input_manifest_path=input_manifest_path,
            algorithm_gate_path=algorithm_gate_path,
            closed_pool_audit_path=closed_pool_audit_path,
        )
        if str(source_snapshot_id) != plan.source_snapshot_id:
            raise ValueError("Source snapshot ID does not match the sealed replay plan")
        if universe_version != plan.universe_version:
            raise ValueError("Universe version does not match the sealed replay plan")
        manifest = _load(input_manifest_path)
        gate = _load(algorithm_gate_path)
        normalized = _normalized_inputs(
            repository_root=self.repository_root,
            manifest=manifest,
            gate=gate,
        )
        gate_by_symbol = {item["symbol"]: item for item in gate["securities"]}
        manifest_by_symbol = {
            item["symbol"]: item for item in manifest["securities"]
        }
        with psycopg.connect(self.database_url) as connection:
            lock_identity = canonical_hash(
                {
                    "kind": "objective-current-replay",
                    "sourceSnapshotId": str(source_snapshot_id),
                    "universeVersion": universe_version,
                    "gateHash": plan.gate_content_hash,
                }
            )
            connection.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (lock_identity,),
            )
            source_snapshot = connection.execute(
                """
                SELECT snapshot_key, status, as_of_time, ingestion_cutoff,
                       market_normalization_version,
                       fundamental_normalization_version,
                       action_normalization_version,
                       market_data_provider, market_adjustment_mode
                FROM analytics.data_snapshot
                WHERE id = %s
                """,
                (source_snapshot_id,),
            ).fetchone()
            if source_snapshot is None or source_snapshot[1] != "READY":
                raise ValueError("Source snapshot must exist and be READY")
            gate_as_of = datetime.fromisoformat(
                plan.as_of_time.replace("Z", "+00:00")
            )
            if gate_as_of > source_snapshot[2] or gate_as_of > source_snapshot[3]:
                raise ValueError("Objective gate is later than the source snapshot cutoff")
            members = connection.execute(
                """
                SELECT member.security_id, security.public_id,
                       member.membership_status, member.membership_reason,
                       member.symbol_at_snapshot, member.company_type_at_snapshot,
                       member.normalized_sector_at_snapshot
                FROM analytics.snapshot_universe_member member
                JOIN analytics.security security ON security.id = member.security_id
                WHERE member.snapshot_id = %s AND member.universe_version = %s
                ORDER BY member.symbol_at_snapshot
                """,
                (source_snapshot_id, universe_version),
            ).fetchall()
            if len(members) != plan.source_profile_count:
                raise ValueError("Source snapshot universe does not match the replay plan")
            if {row[4] for row in members} != {
                item.symbol for item in plan.securities
            }:
                raise ValueError("Source snapshot symbols do not match the replay plan")
            planned_by_symbol = {item.symbol: item for item in plan.securities}
            for row in members:
                planned = planned_by_symbol[row[4]]
                if (
                    str(row[1]) != planned.security_id
                    or row[2] != planned.membership_status
                    or row[5] != planned.company_type
                ):
                    raise ValueError(
                        f"Source snapshot identity does not match the replay plan [{row[4]}]"
                    )

            supplemental = self._validate_supplemental_batches(
                connection,
                supplemental_ingestion_batch_ids=(
                    supplemental_ingestion_batch_ids
                ),
                allowed_members={
                    UUID(str(row[1])): (int(row[0]), str(row[4]))
                    for row in members
                },
            )
            effective_as_of = source_snapshot[2]
            effective_cutoff = source_snapshot[3]
            if supplemental is not None:
                effective_as_of = max(
                    effective_as_of,
                    supplemental.maximum_available_at,
                )
                effective_cutoff = max(
                    effective_cutoff,
                    supplemental.maximum_ingested_at,
                    effective_as_of,
                )
            provider_id = self._controlled_provider(connection)
            batch_id = self._controlled_batch(
                connection,
                provider_id=provider_id,
                plan=plan,
                completed_at=effective_cutoff,
            )
            source_records = self._controlled_sources(
                connection,
                provider_id=provider_id,
                batch_id=batch_id,
                plan=plan,
                manifest_by_symbol=manifest_by_symbol,
                gate_symbols=tuple(sorted(gate_by_symbol)),
                input_manifest_path=input_manifest_path,
                algorithm_gate_path=algorithm_gate_path,
                available_at=gate_as_of,
                ingested_at=effective_cutoff,
            )
            snapshot_id, snapshot_key = self._clone_snapshot(
                connection,
                source_snapshot_id=source_snapshot_id,
                source_snapshot=source_snapshot,
                universe_version=universe_version,
                batch_id=batch_id,
                plan=plan,
                supplemental=supplemental,
                effective_as_of=effective_as_of,
                effective_cutoff=effective_cutoff,
            )
            run_id = self._persist_screening_run(
                connection,
                snapshot_id=snapshot_id,
                universe_version=universe_version,
                plan=plan,
                gate=gate,
                gate_by_symbol=gate_by_symbol,
                normalized=normalized,
                source_records=source_records,
                supplemental=supplemental,
            )
        return ObjectiveGateReplayReceipt(
            snapshot_id=snapshot_id,
            snapshot_key=snapshot_key,
            screening_run_id=run_id,
            objective_scored_count=plan.objective_scored_count,
            insufficient_data_count=plan.insufficient_data_count,
            non_applicable_count=plan.non_applicable_count,
            source_record_count=len(source_records),
            gate_content_hash=plan.gate_content_hash,
            supplemental_batch_count=(
                0 if supplemental is None else len(supplemental.batch_ids)
            ),
            supplemental_source_count=(
                0 if supplemental is None else len(supplemental.sources)
            ),
            supplemental_aggregate_hash=(
                None if supplemental is None else supplemental.aggregate_hash
            ),
            effective_as_of_time=effective_as_of,
            effective_ingestion_cutoff=effective_cutoff,
        )

    def _validate_supplemental_batches(
        self,
        connection,
        *,
        supplemental_ingestion_batch_ids: tuple[UUID, ...],
        allowed_members: dict[UUID, tuple[int, str]],
    ) -> SupplementalReplayEvidence | None:
        if not supplemental_ingestion_batch_ids:
            return None
        batch_ids = tuple(
            sorted(set(supplemental_ingestion_batch_ids), key=str)
        )
        if len(batch_ids) != len(supplemental_ingestion_batch_ids):
            raise ValueError("SUPPLEMENTAL_BATCH_IDS_DUPLICATE")
        sources: list[SupplementalReplaySource] = []
        seen_security_ids: set[int] = set()
        for batch_id in batch_ids:
            rows = connection.execute(
                """
                SELECT provider.code, batch.status, source.id,
                       source.source_reference, source.available_at,
                       source.ingested_at, source.content_hash,
                       source.storage_reference
                FROM analytics.ingestion_batch batch
                JOIN analytics.data_provider provider
                  ON provider.id = batch.provider_id
                JOIN analytics.source_record source
                  ON source.ingestion_batch_id = batch.id
                WHERE batch.id = %s
                ORDER BY source.id
                """,
                (batch_id,),
            ).fetchall()
            if not rows:
                raise ValueError(
                    f"SUPPLEMENTAL_BATCH_NOT_FOUND_OR_EMPTY[{batch_id}]"
                )
            for row in rows:
                (
                    provider_code,
                    batch_status,
                    source_id,
                    source_reference,
                    available_at,
                    ingested_at,
                    content_hash,
                    storage_reference,
                ) = row
                if provider_code != "eodhd":
                    raise ValueError(
                        f"SUPPLEMENTAL_PROVIDER_NOT_EODHD[{batch_id}]"
                    )
                if batch_status != "SUCCEEDED":
                    raise ValueError(
                        f"SUPPLEMENTAL_BATCH_NOT_SUCCEEDED[{batch_id}]"
                    )
                if (
                    not isinstance(source_reference, str)
                    or SUPPLEMENTAL_SOURCE_MARKER not in source_reference
                ):
                    raise ValueError(
                        f"SUPPLEMENTAL_SOURCE_REFERENCE_NOT_APPROVED[{source_id}]"
                    )
                if not isinstance(storage_reference, str) or not storage_reference:
                    raise ValueError(
                        f"SUPPLEMENTAL_STORAGE_REFERENCE_MISSING[{source_id}]"
                    )
                storage_path = (
                    self.repository_root / storage_reference
                ).resolve()
                try:
                    storage_path.relative_to(self.repository_root)
                except ValueError as error:
                    raise ValueError(
                        f"SUPPLEMENTAL_STORAGE_OUTSIDE_REPOSITORY[{source_id}]"
                    ) from error
                if not storage_path.is_file():
                    raise ValueError(
                        f"SUPPLEMENTAL_STORAGE_MISSING[{source_id}]"
                    )
                expected_hash = str(content_hash).removeprefix("sha256:").upper()
                actual_hash = sha256(storage_path.read_bytes()).hexdigest().upper()
                if actual_hash != expected_hash:
                    raise ValueError(
                        f"SUPPLEMENTAL_STORAGE_HASH_MISMATCH[{source_id}]"
                    )
                profile_rows = connection.execute(
                    """
                    SELECT DISTINCT profile.security_id, security.public_id,
                                    security.symbol
                    FROM analytics.company_profile_observation profile
                    JOIN analytics.security security
                      ON security.id = profile.security_id
                    WHERE profile.source_record_id = %s
                    """,
                    (source_id,),
                ).fetchall()
                if len(profile_rows) != 1:
                    raise ValueError(
                        f"SUPPLEMENTAL_COMPANY_PROFILE_MISSING_OR_AMBIGUOUS[{source_id}]"
                    )
                security_id = int(profile_rows[0][0])
                public_id = UUID(str(profile_rows[0][1]))
                symbol = str(profile_rows[0][2])
                expected_member = allowed_members.get(public_id)
                if expected_member != (security_id, symbol):
                    raise ValueError(
                        f"SUPPLEMENTAL_SECURITY_NOT_IN_PARENT_SNAPSHOT[{source_id}]"
                    )
                if security_id in seen_security_ids:
                    raise ValueError(
                        f"SUPPLEMENTAL_SECURITY_DUPLICATE[{symbol}]"
                    )
                market_cap_count = connection.execute(
                    """
                    SELECT COUNT(*)
                    FROM analytics.market_value_observation
                    WHERE source_record_id = %s
                      AND security_id = %s
                      AND metric_code = 'MARKET_CAP'
                    """,
                    (source_id, security_id),
                ).fetchone()[0]
                if market_cap_count < 1:
                    raise ValueError(
                        f"SUPPLEMENTAL_MARKET_CAP_MISSING[{symbol}]"
                    )
                classifications = connection.execute(
                    """
                    SELECT normalized_sector, source_record_id
                    FROM analytics.security_classification
                    WHERE security_id = %s
                      AND classification_version = %s
                      AND source_record_id = %s
                    ORDER BY effective_from DESC, id DESC
                    """,
                    (
                        security_id,
                        SUPPLEMENTAL_CLASSIFICATION_VERSION,
                        source_id,
                    ),
                ).fetchall()
                if (
                    len(classifications) != 1
                    or not isinstance(classifications[0][0], str)
                    or not classifications[0][0].strip()
                ):
                    raise ValueError(
                        f"SUPPLEMENTAL_CLASSIFICATION_MISSING_OR_AMBIGUOUS[{symbol}]"
                    )
                audit_rows = connection.execute(
                    """
                    SELECT entity_id, detail
                    FROM analytics.analytics_audit_event
                    WHERE event_type = 'PROVIDER_CACHE_REPLAY'
                      AND detail ->> 'sourceRecordId' = %s
                    ORDER BY occurred_at, id
                    """,
                    (str(source_id),),
                ).fetchall()
                if len(audit_rows) != 1:
                    raise ValueError(
                        f"SUPPLEMENTAL_AUDIT_MISSING_OR_AMBIGUOUS[{source_id}]"
                    )
                audit_entity_id, detail = audit_rows[0]
                if (
                    str(audit_entity_id) != str(public_id)
                    or detail.get("schemaVersion")
                    != "provider-cache-replay-v1.0.0"
                    or detail.get("sourceRecordId") != str(source_id)
                    or str(detail.get("sourceContentHash", "")).upper()
                    != str(content_hash).upper()
                    or detail.get("storageReference") != storage_reference
                    or detail.get("networkRequestsExecuted") is not False
                    or detail.get("physicalRequests") != 0
                ):
                    raise ValueError(
                        f"SUPPLEMENTAL_AUDIT_CONTRACT_MISMATCH[{source_id}]"
                    )
                seen_security_ids.add(security_id)
                sources.append(
                    SupplementalReplaySource(
                        batch_id=batch_id,
                        source_record_id=source_id,
                        security_id=security_id,
                        security_public_id=public_id,
                        symbol=symbol,
                        normalized_sector=classifications[0][0],
                        content_hash=str(content_hash),
                        storage_reference=storage_reference,
                        available_at=available_at,
                        ingested_at=ingested_at,
                    )
                )
        sources.sort(key=lambda source: (source.symbol, str(source.source_record_id)))
        aggregate_hash = canonical_hash(
            {
                "schemaVersion": "objective-replay-supplement-v1.0.0",
                "sourceMarker": SUPPLEMENTAL_SOURCE_MARKER,
                "classificationVersion": SUPPLEMENTAL_CLASSIFICATION_VERSION,
                "batchIds": [str(batch_id) for batch_id in batch_ids],
                "sources": [
                    {
                        "batchId": str(source.batch_id),
                        "sourceRecordId": str(source.source_record_id),
                        "securityPublicId": str(source.security_public_id),
                        "symbol": source.symbol,
                        "normalizedSector": source.normalized_sector,
                        "contentHash": source.content_hash,
                        "storageReference": source.storage_reference,
                        "availableAt": source.available_at.isoformat(),
                        "ingestedAt": source.ingested_at.isoformat(),
                    }
                    for source in sources
                ],
            }
        )
        return SupplementalReplayEvidence(
            batch_ids=batch_ids,
            sources=tuple(sources),
            aggregate_hash=aggregate_hash,
            maximum_available_at=max(source.available_at for source in sources),
            maximum_ingested_at=max(source.ingested_at for source in sources),
        )

    @staticmethod
    def _controlled_provider(connection) -> int:
        connection.execute(
            """
            INSERT INTO analytics.data_provider (
                code, name, provider_schema_version
            ) VALUES (%s, %s, %s)
            ON CONFLICT (code) DO NOTHING
            """,
            (
                CONTROLLED_PROVIDER,
                "Controlled Objective Current Gate Evidence",
                CONTROLLED_PROVIDER_SCHEMA,
            ),
        )
        row = connection.execute(
            """
            SELECT id, provider_schema_version
            FROM analytics.data_provider WHERE code = %s
            """,
            (CONTROLLED_PROVIDER,),
        ).fetchone()
        if row is None or row[1] != CONTROLLED_PROVIDER_SCHEMA:
            raise ValueError("Controlled Objective provider registry conflict")
        return row[0]

    @staticmethod
    def _controlled_batch(
        connection,
        *,
        provider_id: int,
        plan: ObjectiveGateReplayPlan,
        completed_at: datetime,
    ) -> UUID:
        request_key = (
            f"objective-current-gate:{REPLAY_VERSION}:{plan.gate_content_hash}"
        )
        batch_id = _deterministic_uuid(
            "objective-current-batch",
            REPLAY_VERSION,
            plan.gate_content_hash,
        )
        connection.execute(
            """
            INSERT INTO analytics.ingestion_batch (
                id, provider_id, request_key, status, parser_version,
                normalization_version, started_at, completed_at
            ) VALUES (%s, %s, %s, 'SUCCEEDED', %s, %s, %s, %s)
            ON CONFLICT (provider_id, request_key) DO NOTHING
            """,
            (
                batch_id,
                provider_id,
                request_key,
                REPLAY_VERSION,
                plan.strategy_version,
                completed_at,
                completed_at,
            ),
        )
        row = connection.execute(
            """
            SELECT id, status, parser_version, normalization_version
            FROM analytics.ingestion_batch
            WHERE provider_id = %s AND request_key = %s
            """,
            (provider_id, request_key),
        ).fetchone()
        if row is None or tuple(row[1:]) != (
            "SUCCEEDED",
            REPLAY_VERSION,
            plan.strategy_version,
        ):
            raise ValueError("Controlled Objective ingestion batch conflict")
        return row[0]

    @staticmethod
    def _controlled_sources(
        connection,
        *,
        provider_id: int,
        batch_id: UUID,
        plan: ObjectiveGateReplayPlan,
        manifest_by_symbol: dict[str, dict[str, Any]],
        gate_symbols: tuple[str, ...],
        input_manifest_path: Path,
        algorithm_gate_path: Path,
        available_at: datetime,
        ingested_at: datetime,
    ) -> dict[str, UUID]:
        result: dict[str, UUID] = {}
        for symbol in gate_symbols:
            item = manifest_by_symbol[symbol]
            content_hash = str(item["payloadContentHash"]).removeprefix(
                "sha256:"
            ).upper()
            source_reference = (
                f"controlled-objective-current:{symbol}:"
                f"{content_hash}"
            )
            source_id = _deterministic_uuid(
                "objective-current-source", symbol, content_hash
            )
            connection.execute(
                """
                INSERT INTO analytics.source_record (
                    id, ingestion_batch_id, provider_id, provider_record_id,
                    source_reference, original_at, available_at, ingested_at,
                    schema_version, revision_status, quality_status,
                    content_hash, storage_reference
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    'AS_REPORTED', 'VALIDATED', %s, %s
                )
                ON CONFLICT (provider_id, source_reference, content_hash)
                DO NOTHING
                """,
                (
                    source_id,
                    batch_id,
                    provider_id,
                    symbol,
                    source_reference,
                    available_at,
                    available_at,
                    ingested_at,
                    CONTROLLED_PROVIDER_SCHEMA,
                    content_hash,
                    item["storageReference"],
                ),
            )
            row = connection.execute(
                """
                SELECT id, ingestion_batch_id, storage_reference
                FROM analytics.source_record
                WHERE provider_id = %s AND source_reference = %s
                  AND content_hash = %s
                """,
                (provider_id, source_reference, content_hash),
            ).fetchone()
            if row is None or row[1] != batch_id or row[2] != item["storageReference"]:
                raise ValueError(
                    f"Controlled Objective source record conflict [{symbol}]"
                )
            result[symbol] = row[0]
        for role, path, content_hash in (
            (
                "manifest",
                input_manifest_path,
                plan.manifest_content_hash,
            ),
            (
                "gate",
                algorithm_gate_path,
                plan.gate_content_hash,
            ),
        ):
            try:
                storage_reference = str(
                    path.resolve().relative_to(Path.cwd().resolve())
                ).replace("\\", "/")
            except ValueError:
                storage_reference = str(path.resolve())
            source_reference = f"controlled-objective-artifact:{role}:{content_hash}"
            source_id = _deterministic_uuid(
                "objective-current-artifact", role, content_hash
            )
            connection.execute(
                """
                INSERT INTO analytics.source_record (
                    id, ingestion_batch_id, provider_id, provider_record_id,
                    source_reference, original_at, available_at, ingested_at,
                    schema_version, revision_status, quality_status,
                    content_hash, storage_reference
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    'AS_REPORTED', 'VALIDATED', %s, %s
                )
                ON CONFLICT (provider_id, source_reference, content_hash)
                DO NOTHING
                """,
                (
                    source_id,
                    batch_id,
                    provider_id,
                    role,
                    source_reference,
                    available_at,
                    available_at,
                    ingested_at,
                    CONTROLLED_PROVIDER_SCHEMA,
                    content_hash,
                    storage_reference,
                ),
            )
            row = connection.execute(
                """
                SELECT id, ingestion_batch_id, storage_reference
                FROM analytics.source_record
                WHERE provider_id = %s AND source_reference = %s
                  AND content_hash = %s
                """,
                (provider_id, source_reference, content_hash),
            ).fetchone()
            if (
                row is None
                or row[1] != batch_id
                or row[2] != storage_reference
            ):
                raise ValueError(
                    f"Controlled Objective artifact source conflict [{role}]"
                )
            result[f"__{role}__"] = row[0]
        return result

    @staticmethod
    def _clone_snapshot(
        connection,
        *,
        source_snapshot_id: UUID,
        source_snapshot,
        universe_version: str,
        batch_id: UUID,
        plan: ObjectiveGateReplayPlan,
        supplemental: SupplementalReplayEvidence | None,
        effective_as_of: datetime,
        effective_cutoff: datetime,
    ) -> tuple[UUID, str]:
        supplemental_identity = (
            "none" if supplemental is None else supplemental.aggregate_hash
        )
        snapshot_key = (
            f"{source_snapshot[0]}:objective-current-v1-1:"
            f"{plan.gate_content_hash[:12].lower()}:"
            f"{canonical_hash(universe_version)[:12].lower()}:"
            f"{supplemental_identity[:12].lower()}"
        )
        snapshot_id = _deterministic_uuid(
            "objective-current-snapshot",
            REPLAY_VERSION,
            str(source_snapshot_id),
            universe_version,
            plan.gate_content_hash,
            supplemental_identity,
            effective_as_of.isoformat(),
            effective_cutoff.isoformat(),
        )
        manifest_hash = _sha(
            {
                "replayVersion": REPLAY_VERSION,
                "sourceSnapshotId": str(source_snapshot_id),
                "universeVersion": universe_version,
                "objectiveManifestHash": plan.manifest_content_hash,
                "objectiveGateHash": plan.gate_content_hash,
                "scope": plan.scope,
                "supplementalAggregateHash": (
                    None
                    if supplemental is None
                    else supplemental.aggregate_hash
                ),
                "supplementalBatchIds": (
                    []
                    if supplemental is None
                    else [str(item) for item in supplemental.batch_ids]
                ),
                "effectiveAsOfTime": effective_as_of.isoformat(),
                "effectiveIngestionCutoff": effective_cutoff.isoformat(),
            }
        )
        parent_batch_ids = {
            row[0]
            for row in connection.execute(
                """
                SELECT ingestion_batch_id
                FROM analytics.data_snapshot_source
                WHERE snapshot_id = %s
                """,
                (source_snapshot_id,),
            ).fetchall()
        }
        expected_batch_ids = parent_batch_ids | {batch_id}
        if supplemental is not None:
            expected_batch_ids.update(supplemental.batch_ids)
        existing = connection.execute(
            """
            SELECT id, status, manifest_hash FROM analytics.data_snapshot
            WHERE snapshot_key = %s
            """,
            (snapshot_key,),
        ).fetchone()
        if existing is not None:
            if (
                existing[0] != snapshot_id
                or existing[1] != "READY"
                or existing[2] != manifest_hash
            ):
                raise ValueError("Objective replay snapshot conflict")
            actual_batch_ids = {
                row[0]
                for row in connection.execute(
                    """
                    SELECT ingestion_batch_id
                    FROM analytics.data_snapshot_source
                    WHERE snapshot_id = %s
                    """,
                    (snapshot_id,),
                ).fetchall()
            }
            member_count = connection.execute(
                """
                SELECT COUNT(*)
                FROM analytics.snapshot_universe_member
                WHERE snapshot_id = %s AND universe_version = %s
                """,
                (snapshot_id, universe_version),
            ).fetchone()[0]
            if (
                actual_batch_ids != expected_batch_ids
                or member_count != plan.source_profile_count
            ):
                raise ValueError("Objective replay snapshot lineage conflict")
            return existing[0], snapshot_key
        connection.execute(
            """
            INSERT INTO analytics.data_snapshot (
                id, snapshot_key, status, as_of_time, ingestion_cutoff,
                market_normalization_version,
                fundamental_normalization_version,
                action_normalization_version, manifest_hash,
                market_data_provider, market_adjustment_mode
            ) VALUES (
                %s, %s, 'BUILDING', %s, %s, %s, %s, %s, %s, %s, %s
            )
            """,
            (
                snapshot_id,
                snapshot_key,
                effective_as_of,
                effective_cutoff,
                source_snapshot[4],
                source_snapshot[5],
                source_snapshot[6],
                manifest_hash,
                source_snapshot[7],
                source_snapshot[8],
            ),
        )
        connection.execute(
            """
            INSERT INTO analytics.data_snapshot_source (
                snapshot_id, ingestion_batch_id
            )
            SELECT %s, ingestion_batch_id
            FROM analytics.data_snapshot_source WHERE snapshot_id = %s
            """,
            (snapshot_id, source_snapshot_id),
        )
        connection.execute(
            """
            INSERT INTO analytics.data_snapshot_source (
                snapshot_id, ingestion_batch_id
            ) VALUES (%s, %s)
            ON CONFLICT DO NOTHING
            """,
            (snapshot_id, batch_id),
        )
        if supplemental is not None:
            for supplemental_batch_id in supplemental.batch_ids:
                connection.execute(
                    """
                    INSERT INTO analytics.data_snapshot_source (
                        snapshot_id, ingestion_batch_id
                    ) VALUES (%s, %s)
                    ON CONFLICT DO NOTHING
                    """,
                    (snapshot_id, supplemental_batch_id),
                )
        connection.execute(
            """
            INSERT INTO analytics.snapshot_universe_member (
                snapshot_id, universe_version, security_id,
                membership_status, membership_reason, symbol_at_snapshot,
                company_type_at_snapshot, normalized_sector_at_snapshot
            )
            SELECT %s, universe_version, security_id, membership_status,
                   membership_reason, symbol_at_snapshot,
                   company_type_at_snapshot, normalized_sector_at_snapshot
            FROM analytics.snapshot_universe_member
            WHERE snapshot_id = %s AND universe_version = %s
            """,
            (snapshot_id, source_snapshot_id, universe_version),
        )
        if supplemental is not None:
            for security_id, normalized_sector in (
                supplemental.sectors_by_security_id.items()
            ):
                updated = connection.execute(
                    """
                    UPDATE analytics.snapshot_universe_member
                    SET normalized_sector_at_snapshot = %s
                    WHERE snapshot_id = %s
                      AND universe_version = %s
                      AND security_id = %s
                    """,
                    (
                        normalized_sector,
                        snapshot_id,
                        universe_version,
                        security_id,
                    ),
                ).rowcount
                if updated != 1:
                    raise ValueError(
                        "SUPPLEMENTAL_CLASSIFICATION_MEMBER_NOT_FOUND"
                    )
        counts = connection.execute(
            """
            SELECT
              (SELECT COUNT(*) FROM analytics.data_snapshot_source
               WHERE snapshot_id = %s),
              (SELECT COUNT(*) FROM analytics.snapshot_universe_member
               WHERE snapshot_id = %s AND universe_version = %s)
            """,
            (snapshot_id, snapshot_id, universe_version),
        ).fetchone()
        connection.execute(
            """
            UPDATE analytics.data_snapshot
            SET status = 'READY', source_count = %s, security_count = %s,
                sealed_at = %s
            WHERE id = %s AND status = 'BUILDING'
            """,
            (counts[0], counts[1], effective_cutoff, snapshot_id),
        )
        return snapshot_id, snapshot_key

    @staticmethod
    def _persist_screening_run(
        connection,
        *,
        snapshot_id: UUID,
        universe_version: str,
        plan: ObjectiveGateReplayPlan,
        gate: dict[str, Any],
        gate_by_symbol: dict[str, dict[str, Any]],
        normalized: dict[str, dict[str, Any]],
        source_records: dict[str, UUID],
        supplemental: SupplementalReplayEvidence | None,
    ) -> UUID:
        supplemental_identity = (
            "none" if supplemental is None else supplemental.aggregate_hash
        )
        run_id = _deterministic_uuid(
            "objective-current-run",
            REPLAY_VERSION,
            str(snapshot_id),
            universe_version,
            plan.gate_content_hash,
            supplemental_identity,
        )
        request_hash = _sha(
            {
                "replayVersion": REPLAY_VERSION,
                "snapshotId": str(snapshot_id),
                "universeVersion": universe_version,
                "strategyVersion": plan.strategy_version,
                "scope": plan.scope,
                "manifestHash": plan.manifest_content_hash,
                "gateHash": plan.gate_content_hash,
                "supplementalAggregateHash": (
                    None
                    if supplemental is None
                    else supplemental.aggregate_hash
                ),
                "supplementalBatchIds": (
                    []
                    if supplemental is None
                    else [str(item) for item in supplemental.batch_ids]
                ),
            }
        )
        existing = connection.execute(
            """
            SELECT status, canonical_request_hash, snapshot_id,
                   universe_version, result_hash
            FROM analytics.screening_run WHERE id = %s
            """,
            (run_id,),
        ).fetchone()
        if existing is not None:
            if tuple(existing) != (
                "SUCCEEDED",
                request_hash,
                snapshot_id,
                universe_version,
                f"sha256:{plan.gate_content_hash.lower()}",
            ):
                raise ValueError("Objective replay screening run conflict")
            return run_id
        now = datetime.now(UTC)
        connection.execute(
            """
            INSERT INTO analytics.screening_run (
                id, run_key, idempotency_key, canonical_request_hash,
                status, as_of_time, snapshot_id, universe_version,
                include_near_term_market_condition, submitted_at, started_at
            ) SELECT %s, %s, %s, %s, 'RUNNING', as_of_time, id, %s,
                     FALSE, %s, %s
              FROM analytics.data_snapshot WHERE id = %s AND status = 'READY'
            """,
            (
                run_id,
                f"objective-current-replay:{run_id}",
                f"objective-current-replay:{snapshot_id}:{plan.gate_content_hash}",
                request_hash,
                universe_version,
                now,
                now,
                snapshot_id,
            ),
        )
        connection.execute(
            """
            INSERT INTO analytics.screening_run_strategy (
                run_id, strategy_version
            ) VALUES (%s, %s)
            """,
            (run_id, plan.strategy_version),
        )
        db_members = {
            row[1]: row
            for row in connection.execute(
                """
                SELECT security.id, member.symbol_at_snapshot,
                       member.company_type_at_snapshot, member.membership_status,
                       (
                            SELECT value.numeric_value
                            FROM analytics.market_value_observation value
                            WHERE value.security_id = security.id
                              AND value.metric_code = 'MARKET_CAP'
                              AND value.observation_date <= (
                                  SELECT snapshot.as_of_time::date
                                  FROM analytics.data_snapshot snapshot
                                  WHERE snapshot.id = %s
                              )
                              AND value.available_at <= (
                                  SELECT snapshot.ingestion_cutoff
                                  FROM analytics.data_snapshot snapshot
                                  WHERE snapshot.id = %s
                              )
                              AND value.ingested_at <= (
                                  SELECT snapshot.ingestion_cutoff
                                  FROM analytics.data_snapshot snapshot
                                  WHERE snapshot.id = %s
                              )
                              AND EXISTS (
                                  SELECT 1
                                  FROM analytics.source_record source
                                  JOIN analytics.data_snapshot_source snapshot_source
                                    ON snapshot_source.ingestion_batch_id =
                                       source.ingestion_batch_id
                                  WHERE source.id = value.source_record_id
                                    AND snapshot_source.snapshot_id = %s
                              )
                            ORDER BY value.observation_date DESC,
                                     value.revision_number DESC
                            LIMIT 1
                       )
                FROM analytics.snapshot_universe_member member
                JOIN analytics.security security ON security.id = member.security_id
                WHERE member.snapshot_id = %s AND member.universe_version = %s
                """,
                (
                    snapshot_id,
                    snapshot_id,
                    snapshot_id,
                    snapshot_id,
                    snapshot_id,
                    universe_version,
                ),
            ).fetchall()
        }
        plan_by_symbol = {item.symbol: item for item in plan.securities}
        for symbol, row in db_members.items():
            planned = plan_by_symbol[symbol]
            if planned.objective_state == "NOT_APPLICABLE":
                # The Objective run is limited to INCLUDED securities. Reference
                # and excluded members remain in the cloned 66-security snapshot,
                # where the Market Intelligence assembler preserves their
                # membership reason and emits NOT_APPLICABLE views. V8 requires a
                # numeric size cohort for every coverage row, so inserting these
                # members here would either invent a cohort or require an
                # unnecessary schema migration.
                continue
            gate_item = gate_by_symbol.get(symbol)
            if planned.objective_state == "OBJECTIVE_QC_SCORED":
                coverage = "QUANT_ELIGIBLE"
                contributions = normalized[symbol]["contributions"]
                quality = _q(
                    sum(
                        contributions[name]
                        for name in QC_RAW_FACTORS
                    )
                    / Decimal("0.95")
                )
                valuation = normalized[symbol]["valuation_guardrail"]
                error = None
                size = gate_item["sizeCohort"]
            elif planned.objective_state == "INSUFFICIENT_DATA":
                coverage = "INSUFFICIENT_DATA"
                quality = None
                valuation = None
                error = "CURRENT_QC_INPUT_NOT_READY"
                if row[4] is None:
                    raise ValueError(
                        f"MISSING_MARKET_CAP_FOR_COHORT[{symbol}]"
                    )
                size = _size_cohort(Decimal(row[4]))
            connection.execute(
                """
                INSERT INTO analytics.coverage_result (
                    run_id, security_id, coverage_state, company_type,
                    size_cohort, quality_score, valuation_score, error_code
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    run_id,
                    row[0],
                    coverage,
                    row[2],
                    size,
                    quality,
                    valuation,
                    error,
                ),
            )
            if error is not None:
                connection.execute(
                    """
                    INSERT INTO analytics.coverage_reason (
                        run_id, security_id, reason_type, reason_code,
                        detail, display_order
                    ) VALUES (%s, %s, %s, %s, %s, 0)
                    """,
                    (
                        run_id,
                        row[0],
                        (
                            "MISSING_DATA"
                            if coverage == "INSUFFICIENT_DATA"
                            else "EXCLUSION"
                        ),
                        error,
                        "Current-only Objective replay preserves explicit non-scoring state.",
                    ),
                )
                continue
            source_id = source_records[symbol]
            factor_results = normalized[symbol]["factors"]
            for factor_name in (*QC_RAW_FACTORS, *VALUATION_INPUTS):
                factor = factor_results[factor_name]
                factor_id = connection.execute(
                    """
                    INSERT INTO analytics.factor_result (
                        run_id, security_id, factor_code, factor_version,
                        status, raw_value, winsorized_value, normalized_score,
                        cohort_level, cohort_size
                    ) VALUES (
                        %s, %s, %s, %s, 'VALID', %s, %s, %s, %s, %s
                    ) RETURNING id
                    """,
                    (
                        run_id,
                        row[0],
                        factor_name,
                        FACTOR_VERSION,
                        factor.raw_value,
                        factor.winsorized_value,
                        factor.normalized_score,
                        factor.cohort_level,
                        factor.cohort_size,
                    ),
                ).fetchone()[0]
                connection.execute(
                    """
                    INSERT INTO analytics.factor_result_lineage (
                        factor_result_id, source_record_id, lineage_role
                    ) VALUES (%s, %s, %s)
                    """,
                    (factor_id, source_id, "CONTROLLED_CURRENT_INPUT"),
                )
                for source_key, lineage_role in (
                    ("__manifest__", "NORMALIZATION_COHORT_MANIFEST"),
                    ("__gate__", "ACCEPTED_OBJECTIVE_GATE"),
                ):
                    connection.execute(
                        """
                        INSERT INTO analytics.factor_result_lineage (
                            factor_result_id, source_record_id, lineage_role
                        ) VALUES (%s, %s, %s)
                        """,
                        (factor_id, source_records[source_key], lineage_role),
                    )
                supplemental_source_id = (
                    None
                    if supplemental is None
                    else supplemental.source_ids_by_symbol.get(symbol)
                )
                if supplemental_source_id is not None:
                    connection.execute(
                        """
                        INSERT INTO analytics.factor_result_lineage (
                            factor_result_id, source_record_id, lineage_role
                        ) VALUES (%s, %s, %s)
                        """,
                        (
                            factor_id,
                            supplemental_source_id,
                            "SUPPLEMENTAL_CURRENT_PROFILE",
                        ),
                    )
            valuation_score = normalized[symbol]["valuation_guardrail"]
            valuation_factor_id = connection.execute(
                """
                INSERT INTO analytics.factor_result (
                    run_id, security_id, factor_code, factor_version,
                    status, raw_value, winsorized_value, normalized_score,
                    cohort_level, cohort_size
                ) VALUES (
                    %s, %s, 'valuation_guardrail', %s, 'VALID',
                    %s, %s, %s, 'GENERAL_COMPANY', 136
                ) RETURNING id
                """,
                (
                    run_id,
                    row[0],
                    FACTOR_VERSION,
                    valuation_score,
                    valuation_score,
                    valuation_score,
                ),
            ).fetchone()[0]
            connection.execute(
                """
                INSERT INTO analytics.factor_result_lineage (
                    factor_result_id, source_record_id, lineage_role
                ) VALUES (%s, %s, %s)
                """,
                (
                    valuation_factor_id,
                    source_id,
                    "DERIVED_CURRENT_VALUATION_GUARDRAIL",
                ),
            )
            for source_key, lineage_role in (
                ("__manifest__", "NORMALIZATION_COHORT_MANIFEST"),
                ("__gate__", "ACCEPTED_OBJECTIVE_GATE"),
            ):
                connection.execute(
                    """
                    INSERT INTO analytics.factor_result_lineage (
                        factor_result_id, source_record_id, lineage_role
                    ) VALUES (%s, %s, %s)
                    """,
                    (
                        valuation_factor_id,
                        source_records[source_key],
                        lineage_role,
                    ),
                )
            supplemental_source_id = (
                None
                if supplemental is None
                else supplemental.source_ids_by_symbol.get(symbol)
            )
            if supplemental_source_id is not None:
                connection.execute(
                    """
                    INSERT INTO analytics.factor_result_lineage (
                        factor_result_id, source_record_id, lineage_role
                    ) VALUES (%s, %s, %s)
                    """,
                    (
                        valuation_factor_id,
                        supplemental_source_id,
                        "SUPPLEMENTAL_CURRENT_PROFILE",
                    ),
                )
            rating_id = connection.execute(
                """
                INSERT INTO analytics.strategy_rating (
                    run_id, security_id, strategy_version, status, score, rank
                ) VALUES (%s, %s, %s, 'SCORED', %s, %s)
                RETURNING id
                """,
                (
                    run_id,
                    row[0],
                    QC_VERSION,
                    normalized[symbol]["score"],
                    normalized[symbol]["rank"],
                ),
            ).fetchone()[0]
            for factor_name, weight in QC_WEIGHTS.items():
                factor_score = (
                    normalized[symbol]["valuation_guardrail"]
                    if factor_name == "valuation_guardrail"
                    else factor_results[factor_name].normalized_score
                )
                connection.execute(
                    """
                    INSERT INTO analytics.factor_contribution (
                        strategy_rating_id, factor_code, normalized_score,
                        weight, contribution
                    ) VALUES (%s, %s, %s, %s, %s)
                    """,
                    (
                        rating_id,
                        factor_name,
                        factor_score,
                        weight,
                        normalized[symbol]["contributions"][factor_name],
                    ),
                )
            connection.execute(
                """
                INSERT INTO analytics.horizon_assessment (
                    run_id, security_id, horizon, status, score, label
                ) VALUES (
                    %s, %s, 'LONG_TERM', 'SCORED', %s,
                    'CURRENT_DECISION_ONLY'
                )
                """,
                (run_id, row[0], normalized[symbol]["score"]),
            )
        connection.execute(
            """
            UPDATE analytics.screening_run
            SET status = 'SUCCEEDED', completed_at = %s, result_hash = %s
            WHERE id = %s AND status = 'RUNNING'
            """,
            (now, f"sha256:{plan.gate_content_hash.lower()}", run_id),
        )
        return run_id


def _size_cohort(market_cap: Decimal) -> str:
    if market_cap >= Decimal("200000000000"):
        return "MEGA"
    if market_cap >= Decimal("10000000000"):
        return "LARGE"
    if market_cap >= Decimal("2000000000"):
        return "MID"
    return "SMALL"
