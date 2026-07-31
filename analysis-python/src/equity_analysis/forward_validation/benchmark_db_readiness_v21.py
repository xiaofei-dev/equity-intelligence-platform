from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any
from uuid import UUID

from equity_analysis.analytics_interface.contracts import canonical_hash
from equity_analysis.forward_validation.benchmark_construction_v21 import (
    BENCHMARK_CONSTRUCTION_V21,
    BenchmarkConstructionRequestV21,
    BenchmarkConstructionState,
    BenchmarkEvidenceBundleV21,
    BenchmarkLiquidityEvidence,
    BenchmarkPriceBar,
    BenchmarkUniverseSecurity,
    ObjectiveScoreEvidence,
    SectorBenchmarkAssignment,
    UniverseRole,
    build_benchmark_evidence_bundle_v21,
)
from equity_analysis.historical_validation.protocol_v2 import BenchmarkKind

BENCHMARK_DB_READINESS_V21 = "FORWARD-BENCHMARK-DB-READINESS-v2.1.0"
EXPECTED_CLOSED_POPULATION = 66
MISSING_MARKET_REFERENCE_PREFIX = "urn:benchmark-v21:missing-market-reference:"


class BenchmarkDbReadinessStatus(StrEnum):
    READY = "READY"
    BLOCKED = "BLOCKED"


class BenchmarkDbReadinessError(ValueError):
    pass


@dataclass(frozen=True)
class BenchmarkFamilyReadinessV21:
    kind: BenchmarkKind
    state: BenchmarkConstructionState
    reason_codes: tuple[str, ...]
    evidence_hash: str | None
    source_evidence_hash: str | None
    constituent_set_hash: str | None
    weight_hash: str | None
    selection_hash: str | None
    cost_evidence_hash: str | None
    sector_assignment_hash: str | None
    terminal_hash: str


@dataclass(frozen=True)
class BenchmarkDbReadinessV21:
    version: str
    status: BenchmarkDbReadinessStatus
    data_snapshot_id: UUID
    snapshot_as_of: datetime
    ingestion_cutoff: datetime
    universe_version: str
    universe_hash: str
    declared_security_count: int
    loaded_security_count: int
    schema_blockers: tuple[str, ...]
    evidence_blockers: tuple[str, ...]
    families: tuple[BenchmarkFamilyReadinessV21, ...]
    construction_contract_hash: str
    construction_bundle_hash: str
    parent_liquidity_cost_policy_hash: str
    prospective_enrollment_allowed: bool
    database_writes: int
    provider_network_requests: int
    diagnostic_content_hash: str


def _aware(value: datetime, label: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise BenchmarkDbReadinessError(f"{label} must be timezone-aware")
    return value


def _role(value: str) -> UniverseRole:
    try:
        return UniverseRole(value)
    except ValueError as error:
        raise BenchmarkDbReadinessError(
            f"Unsupported snapshot membership status: {value}"
        ) from error


def _rows(connection, query: str, params: tuple[object, ...]) -> list[dict[str, Any]]:
    return list(connection.execute(query, params).fetchall())


def _snapshot_row(connection, snapshot_id: UUID) -> dict[str, Any]:
    row = connection.execute(
        """
        /* benchmark-v21:snapshot */
        SELECT snapshot.id, snapshot.status, snapshot.as_of_time,
               snapshot.ingestion_cutoff, snapshot.manifest_hash,
               snapshot.security_count, snapshot.source_count,
               snapshot.market_normalization_version,
               snapshot.market_data_provider,
               snapshot.market_adjustment_mode,
               member.universe_version,
               universe.configuration_hash
        FROM analytics.data_snapshot snapshot
        JOIN analytics.snapshot_universe_member member
          ON member.snapshot_id = snapshot.id
        JOIN analytics.universe_definition universe
          ON universe.version = member.universe_version
        WHERE snapshot.id = %s
        GROUP BY snapshot.id, member.universe_version,
                 universe.configuration_hash
        """,
        (snapshot_id,),
    ).fetchone()
    if row is None:
        raise BenchmarkDbReadinessError(f"Specified data snapshot does not exist: {snapshot_id}")
    if row["id"] != snapshot_id:
        raise BenchmarkDbReadinessError(
            "Database returned a snapshot other than the explicitly requested ID"
        )
    if row["status"] != "READY":
        raise BenchmarkDbReadinessError(f"Specified data snapshot is not READY: {snapshot_id}")
    return row


def _member_rows(connection, snapshot_id: UUID, universe_version: str):
    return _rows(
        connection,
        """
        /* benchmark-v21:members */
        SELECT security.id AS database_security_id,
               security.public_id,
               member.symbol_at_snapshot,
               member.membership_status,
               member.membership_reason,
               member.normalized_sector_at_snapshot,
               profile.id AS profile_id,
               profile.snapshot_as_of,
               profile.input_payload_hash,
               profile.objective_rating_status,
               profile.objective_rating_version,
               profile.objective_quality_score,
               profile.objective_valuation_score,
               profile.sector_code AS profile_sector_code,
               profile.sector_name AS profile_sector_name,
               profile.classification_effective_at,
               lineage.available_at AS classification_available_at,
               lineage.retrieved_at AS classification_retrieved_at,
               source.content_hash AS classification_source_hash,
               NULL::timestamptz AS objective_score_available_at,
               NULL::timestamptz AS objective_score_ingested_at,
               NULL::varchar AS objective_score_lineage_hash
        FROM analytics.snapshot_universe_member member
        JOIN analytics.security security
          ON security.id = member.security_id
        LEFT JOIN analytics.security_profile_snapshot profile
          ON profile.data_snapshot_id = member.snapshot_id
         AND profile.security_id = member.security_id
        LEFT JOIN analytics.security_profile_classification_lineage lineage
          ON lineage.profile_id = profile.id
        LEFT JOIN analytics.source_record source
          ON source.id = lineage.source_record_id
        WHERE member.snapshot_id = %s
          AND member.universe_version = %s
        ORDER BY security.public_id, lineage.lineage_ordinal
        """,
        (snapshot_id, universe_version),
    )


def _price_rows(
    connection,
    snapshot_id: UUID,
    decision_session: date,
    ingestion_cutoff: datetime,
):
    return _rows(
        connection,
        """
        /* benchmark-v21:prices */
        SELECT security.public_id,
               observation.trading_date,
               observation.open_price,
               observation.close_price,
               observation.adjusted_close,
               observation.adjustment_mode,
               observation.quality_status,
               observation.available_at,
               observation.ingested_at,
               observation.normalization_version,
               source.content_hash AS source_hash,
               NULL::boolean AS session_complete,
               NULL::varchar AS validation_decision_hash,
               NULL::varchar AS promotion_evidence_hash
        FROM analytics.daily_price_observation observation
        JOIN analytics.security security
          ON security.id = observation.security_id
        JOIN analytics.source_record source
          ON source.id = observation.source_record_id
        JOIN analytics.ingestion_batch batch
          ON batch.id = source.ingestion_batch_id
        JOIN analytics.data_snapshot_source snapshot_source
          ON snapshot_source.ingestion_batch_id = batch.id
        WHERE snapshot_source.snapshot_id = %s
          AND observation.trading_date <= %s
          AND observation.available_at <= %s
          AND observation.ingested_at <= %s
          AND observation.quality_status <> 'REJECTED'
        ORDER BY security.public_id, observation.trading_date,
                 observation.revision_number
        """,
        (
            snapshot_id,
            decision_session,
            ingestion_cutoff,
            ingestion_cutoff,
        ),
    )


def _liquidity_rows(connection, profile_ids: tuple[UUID, ...]):
    if not profile_ids:
        return []
    return _rows(
        connection,
        """
        /* benchmark-v21:liquidity */
        SELECT security.public_id, observation.observation_date,
               observation.status, observation.numeric_value,
               observation.available_at, observation.ingested_at,
               lineage.retrieved_at, source.content_hash AS source_hash
        FROM analytics.security_profile_fact fact
        JOIN analytics.security_profile_snapshot profile
          ON profile.id = fact.profile_id
        JOIN analytics.security security
          ON security.id = profile.security_id
        JOIN analytics.metric_observation observation
          ON observation.id = fact.metric_observation_id
        LEFT JOIN analytics.security_profile_fact_lineage lineage
          ON lineage.profile_id = fact.profile_id
         AND lineage.fact_name = fact.fact_name
        LEFT JOIN analytics.source_record source
          ON source.id = lineage.source_record_id
        WHERE fact.profile_id = ANY(%s::uuid[])
          AND fact.fact_name = 'average_daily_dollar_volume'
        ORDER BY security.public_id, lineage.lineage_ordinal
        """,
        (list(profile_ids),),
    )


def _identity_hash(row: dict[str, Any], snapshot_id: UUID) -> str:
    return canonical_hash(
        {
            "dataSnapshotId": str(snapshot_id),
            "databaseSecurityId": row["database_security_id"],
            "publicSecurityId": str(row["public_id"]),
            "symbolAtSnapshot": row["symbol_at_snapshot"],
            "membershipStatus": row["membership_status"],
            "membershipReason": row["membership_reason"],
            "profileInputPayloadHash": row.get("input_payload_hash"),
        }
    )


def _classification_evidence(
    rows: list[dict[str, Any]],
) -> tuple[str | None, datetime | None, datetime | None, datetime | None]:
    source_hashes = sorted(
        {row["classification_source_hash"] for row in rows if row.get("classification_source_hash")}
    )
    effective = [
        row["classification_effective_at"]
        for row in rows
        if row.get("classification_effective_at") is not None
    ]
    available = [
        row["classification_available_at"]
        for row in rows
        if row.get("classification_available_at") is not None
    ]
    retrieved = [
        row["classification_retrieved_at"]
        for row in rows
        if row.get("classification_retrieved_at") is not None
    ]
    if not source_hashes or not effective or not available or not retrieved:
        return None, None, None, None
    return (
        canonical_hash(source_hashes),
        max(effective),
        max(available),
        max(retrieved),
    )


def _build_members(
    rows: list[dict[str, Any]],
    *,
    snapshot_id: UUID,
    cutoff: datetime,
    schema_blockers: set[str],
    evidence_blockers: set[str],
) -> tuple[
    tuple[BenchmarkUniverseSecurity, ...],
    tuple[SectorBenchmarkAssignment, ...],
    str,
    tuple[UUID, ...],
    dict[str, dict[str, Any]],
]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row["public_id"])].append(row)
    members: list[BenchmarkUniverseSecurity] = []
    profiles: dict[str, dict[str, Any]] = {}
    profile_ids: list[UUID] = []
    for public_id, member_rows in sorted(grouped.items()):
        row = member_rows[0]
        if row.get("profile_id") is not None:
            profile_ids.append(row["profile_id"])
        profile_sector = row.get("profile_sector_name")
        snapshot_sector = row.get("normalized_sector_at_snapshot")
        sector = profile_sector or snapshot_sector
        (
            classification_hash,
            effective_at,
            available_at,
            retrieved_at,
        ) = _classification_evidence(member_rows)
        if sector and sector.strip().upper() == "VALIDATION":
            evidence_blockers.add("PLACEHOLDER_SECTOR_PRESENT")
        if profile_sector and classification_hash is None:
            evidence_blockers.add("CLASSIFICATION_LINEAGE_MISSING")
        if any(
            value is not None and value > cutoff
            for value in (effective_at, available_at, retrieved_at)
        ):
            evidence_blockers.add("CLASSIFICATION_AFTER_DECISION_CUTOFF")
        members.append(
            BenchmarkUniverseSecurity(
                public_security_id=public_id,
                symbol=row["symbol_at_snapshot"],
                role=_role(row["membership_status"]),
                sector=sector,
                identity_source_hash=_identity_hash(row, snapshot_id),
                classification_source_hash=classification_hash,
                classification_effective_at=effective_at,
                classification_available_at=available_at,
                classification_ingested_at=retrieved_at,
            )
        )
        profiles[public_id] = row
        if (
            row.get("objective_quality_score") is not None
            or row.get("objective_valuation_score") is not None
        ) and not (
            row.get("objective_score_available_at")
            and row.get("objective_score_ingested_at")
            and row.get("objective_score_lineage_hash")
        ):
            schema_blockers.add("OBJECTIVE_SCORE_LINEAGE_AND_TIMING_NOT_PERSISTED_V17")
    assignments: list[SectorBenchmarkAssignment] = []
    for member in members:
        source = profiles[member.public_security_id]
        if (
            member.role == UniverseRole.REFERENCE_ONLY
            and str(source["membership_reason"]).upper().startswith("SECTOR_BENCHMARK")
            and member.sector
            and member.sector.strip().upper() != "VALIDATION"
            and member.classification_source_hash
        ):
            assignments.append(
                SectorBenchmarkAssignment(
                    sector=member.sector,
                    benchmark_public_security_id=member.public_security_id,
                    mapping_version=(f"SNAPSHOT-SECTOR-ETF-MAP:{snapshot_id}"),
                    mapping_source_hash=canonical_hash(
                        {
                            "publicSecurityId": member.public_security_id,
                            "sector": member.sector,
                            "membershipReason": source["membership_reason"],
                            "classificationSourceHash": (member.classification_source_hash),
                        }
                    ),
                )
            )
    market_ids = [
        item.public_security_id
        for item in members
        if item.role == UniverseRole.REFERENCE_ONLY and item.symbol.upper() == "SPY"
    ]
    if len(market_ids) != 1:
        evidence_blockers.add("SPY_REFERENCE_IDENTITY_MISSING_OR_AMBIGUOUS")
        market_id = f"{MISSING_MARKET_REFERENCE_PREFIX}{snapshot_id}"
    else:
        market_id = market_ids[0]
    return (
        tuple(members),
        tuple(assignments),
        market_id,
        tuple(sorted(set(profile_ids), key=str)),
        profiles,
    )


def _build_prices(
    rows: list[dict[str, Any]],
    *,
    cutoff: datetime,
    decision_session: date,
    schema_blockers: set[str],
    evidence_blockers: set[str],
) -> tuple[BenchmarkPriceBar, ...]:
    result: list[BenchmarkPriceBar] = []
    for row in rows:
        if (
            row["trading_date"] > decision_session
            or row["available_at"] > cutoff
            or row["ingested_at"] > cutoff
        ):
            continue
        quality = row["quality_status"]
        if quality == "PROVISIONAL":
            evidence_blockers.add("PROVISIONAL_PRICE_EVIDENCE")
            continue
        if quality != "VALIDATED":
            evidence_blockers.add("PRICE_EVIDENCE_NOT_VALIDATED")
            continue
        if row.get("session_complete") is not True:
            schema_blockers.add("COMPLETED_SESSION_EVIDENCE_NOT_PERSISTED_V17")
            continue
        if not row.get("validation_decision_hash"):
            schema_blockers.add("PRICE_VALIDATION_DECISION_HASH_NOT_PERSISTED_V17")
            continue
        close = Decimal(row["close_price"])
        adjusted_close = (
            Decimal(row["adjusted_close"]) if row.get("adjusted_close") is not None else close
        )
        factor = adjusted_close / close
        result.append(
            BenchmarkPriceBar(
                public_security_id=str(row["public_id"]),
                session_date=row["trading_date"],
                open_price=Decimal(row["open_price"]) * factor,
                close_price=adjusted_close,
                completed_session=True,
                quality_status="VALIDATED",
                adjustment_mode=row["adjustment_mode"],
                price_evidence_version=row["normalization_version"],
                validation_decision_hash=row["validation_decision_hash"],
                promotion_evidence_hash=row.get("promotion_evidence_hash"),
                available_at=row["available_at"],
                ingested_at=row["ingested_at"],
                source_hash=row["source_hash"],
            )
        )
    return tuple(result)


def _build_liquidity(
    rows: list[dict[str, Any]],
    *,
    cutoff: datetime,
    decision_session: date,
    evidence_blockers: set[str],
) -> tuple[BenchmarkLiquidityEvidence, ...]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row["public_id"])].append(row)
    result: list[BenchmarkLiquidityEvidence] = []
    for public_id, items in sorted(grouped.items()):
        row = items[0]
        source_hashes = sorted({item["source_hash"] for item in items if item.get("source_hash")})
        retrieved = max(
            (item.get("retrieved_at") or item["ingested_at"] for item in items),
        )
        if (
            row["status"] != "VALID"
            or row["numeric_value"] is None
            or Decimal(row["numeric_value"]) <= 0
            or row["observation_date"] != decision_session
            or row["available_at"] > cutoff
            or row["ingested_at"] > cutoff
            or retrieved > cutoff
            or not source_hashes
        ):
            evidence_blockers.add("DECISION_TIME_ADTV_EVIDENCE_MISSING")
            continue
        result.append(
            BenchmarkLiquidityEvidence(
                public_security_id=public_id,
                as_of_session=row["observation_date"],
                average_daily_dollar_volume=Decimal(row["numeric_value"]),
                quality_status="VALIDATED",
                available_at=row["available_at"],
                ingested_at=retrieved,
                source_hash=canonical_hash(source_hashes),
            )
        )
    return tuple(result)


def _build_objective_scores(
    profiles: dict[str, dict[str, Any]],
    *,
    cutoff: datetime,
    evidence_blockers: set[str],
) -> tuple[
    tuple[ObjectiveScoreEvidence, ...],
    str | None,
    str | None,
]:
    result: list[ObjectiveScoreEvidence] = []
    for public_id, row in sorted(profiles.items()):
        if row.get("objective_rating_status") != "SCORED":
            continue
        required = (
            row.get("objective_quality_score"),
            row.get("objective_valuation_score"),
            row.get("objective_rating_version"),
            row.get("objective_score_available_at"),
            row.get("objective_score_ingested_at"),
            row.get("objective_score_lineage_hash"),
            row.get("input_payload_hash"),
        )
        if any(value is None for value in required):
            evidence_blockers.add("OBJECTIVE_SCORE_EVIDENCE_MISSING")
            continue
        if (
            row["objective_score_available_at"] > cutoff
            or row["objective_score_ingested_at"] > cutoff
        ):
            continue
        result.append(
            ObjectiveScoreEvidence(
                public_security_id=public_id,
                state="VALIDATED",
                score_cutoff=row["snapshot_as_of"],
                score_version=row["objective_rating_version"],
                snapshot_lineage_hash=row["objective_score_lineage_hash"],
                source_hash=row["input_payload_hash"],
                available_at=row["objective_score_available_at"],
                ingested_at=row["objective_score_ingested_at"],
                value_score=Decimal(row["objective_valuation_score"]),
                quality_score=Decimal(row["objective_quality_score"]),
            )
        )
    versions = {item.score_version for item in result}
    lineages = {item.snapshot_lineage_hash for item in result}
    if len(versions) > 1 or len(lineages) > 1:
        evidence_blockers.add("OBJECTIVE_SCORE_CONTRACT_NOT_UNIFORM")
        return (), None, None
    return (
        tuple(result),
        next(iter(versions), None),
        next(iter(lineages), None),
    )


def _family_rows(
    bundle: BenchmarkEvidenceBundleV21,
) -> tuple[BenchmarkFamilyReadinessV21, ...]:
    return tuple(
        BenchmarkFamilyReadinessV21(
            kind=item.kind,
            state=item.state,
            reason_codes=item.reason_codes,
            evidence_hash=item.evidence_hash,
            source_evidence_hash=item.source_evidence_hash,
            constituent_set_hash=item.constituent_set_hash,
            weight_hash=item.weight_hash,
            selection_hash=item.selection_hash,
            cost_evidence_hash=item.cost_evidence_hash,
            sector_assignment_hash=item.sector_assignment_hash,
            terminal_hash=item.terminal_hash,
        )
        for item in bundle.benchmarks
    )


class PostgresBenchmarkReadinessAdapterV21:
    def __init__(self, *, expected_population: int = EXPECTED_CLOSED_POPULATION):
        self.expected_population = expected_population

    def inspect(
        self,
        connection,
        *,
        data_snapshot_id: UUID,
        parent_liquidity_cost_policy_hash: str,
    ) -> BenchmarkDbReadinessV21:
        connection.execute("SET TRANSACTION READ ONLY", ())
        snapshot = _snapshot_row(connection, data_snapshot_id)
        declared_count = int(snapshot["security_count"])
        if declared_count != self.expected_population:
            raise BenchmarkDbReadinessError(
                "Specified READY snapshot does not declare the required "
                f"{self.expected_population} securities"
            )
        as_of = _aware(snapshot["as_of_time"], "Snapshot as-of")
        cutoff = _aware(snapshot["ingestion_cutoff"], "Ingestion cutoff")
        if cutoff < as_of:
            raise BenchmarkDbReadinessError("Snapshot ingestion cutoff precedes its as-of")
        universe_version = snapshot["universe_version"]
        member_rows = _member_rows(
            connection,
            data_snapshot_id,
            universe_version,
        )
        unique_ids = {str(item["public_id"]) for item in member_rows}
        if len(unique_ids) != self.expected_population:
            raise BenchmarkDbReadinessError(
                "Specified READY snapshot does not contain exactly "
                f"{self.expected_population} unique members"
            )
        schema_blockers: set[str] = {
            "COMPLETED_SESSION_EVIDENCE_NOT_PERSISTED_V17",
            "PRICE_VALIDATION_DECISION_HASH_NOT_PERSISTED_V17",
            "PRICE_PROMOTION_EVIDENCE_NOT_PERSISTED_V17",
            "OBJECTIVE_SCORE_LINEAGE_AND_TIMING_NOT_PERSISTED_V17",
        }
        evidence_blockers: set[str] = set()
        (
            members,
            assignments,
            market_id,
            profile_ids,
            profiles,
        ) = _build_members(
            member_rows,
            snapshot_id=data_snapshot_id,
            cutoff=cutoff,
            schema_blockers=schema_blockers,
            evidence_blockers=evidence_blockers,
        )
        raw_prices = _price_rows(
            connection,
            data_snapshot_id,
            as_of.date(),
            cutoff,
        )
        prices = _build_prices(
            raw_prices,
            cutoff=cutoff,
            decision_session=as_of.date(),
            schema_blockers=schema_blockers,
            evidence_blockers=evidence_blockers,
        )
        liquidity = _build_liquidity(
            _liquidity_rows(connection, profile_ids),
            cutoff=cutoff,
            decision_session=as_of.date(),
            evidence_blockers=evidence_blockers,
        )
        (
            objective_scores,
            objective_version,
            objective_lineage,
        ) = _build_objective_scores(
            profiles,
            cutoff=cutoff,
            evidence_blockers=evidence_blockers,
        )
        if snapshot["market_adjustment_mode"] != "TOTAL_RETURN_ADJUSTED":
            evidence_blockers.add("SNAPSHOT_PRICE_ADJUSTMENT_MODE_NOT_ACCEPTED")
        universe_hash = canonical_hash(
            {
                "dataSnapshotId": str(data_snapshot_id),
                "universeVersion": universe_version,
                "configurationHash": snapshot["configuration_hash"],
                "snapshotManifestHash": snapshot["manifest_hash"],
                "members": tuple(
                    {
                        "publicSecurityId": item.public_security_id,
                        "symbol": item.symbol,
                        "role": item.role.value,
                        "sector": item.sector,
                        "identitySourceHash": item.identity_source_hash,
                        "classificationSourceHash": (item.classification_source_hash),
                    }
                    for item in members
                ),
            }
        )
        construction = build_benchmark_evidence_bundle_v21(
            BenchmarkConstructionRequestV21(
                decision_cutoff=cutoff,
                decision_session=as_of.date(),
                universe_version=universe_version,
                universe_hash=universe_hash,
                market_security_id=market_id,
                members=(
                    members
                    if market_id in {item.public_security_id for item in members}
                    else members
                    + (
                        BenchmarkUniverseSecurity(
                            public_security_id=market_id,
                            symbol="MISSING_SPY_REFERENCE",
                            role=UniverseRole.REFERENCE_ONLY,
                            sector=None,
                            identity_source_hash=canonical_hash(
                                {
                                    "reason": ("SPY_REFERENCE_IDENTITY_MISSING_OR_AMBIGUOUS"),
                                    "snapshotId": str(data_snapshot_id),
                                }
                            ),
                            classification_source_hash=None,
                            classification_effective_at=None,
                            classification_available_at=None,
                            classification_ingested_at=None,
                        ),
                    )
                ),
                prices=prices,
                liquidity=liquidity,
                sector_benchmark_assignments=assignments,
                parent_liquidity_cost_policy_hash=(parent_liquidity_cost_policy_hash),
                objective_scores=objective_scores,
                objective_score_version=objective_version,
                objective_score_lineage_hash=objective_lineage,
            )
        )
        families = _family_rows(construction)
        ready = not schema_blockers and all(
            item.state == BenchmarkConstructionState.AVAILABLE for item in families
        )
        status = BenchmarkDbReadinessStatus.READY if ready else BenchmarkDbReadinessStatus.BLOCKED
        payload = {
            "version": BENCHMARK_DB_READINESS_V21,
            "status": status.value,
            "dataSnapshotId": str(data_snapshot_id),
            "snapshotAsOf": as_of,
            "ingestionCutoff": cutoff,
            "universeVersion": universe_version,
            "universeHash": universe_hash,
            "declaredSecurityCount": declared_count,
            "loadedSecurityCount": len(members),
            "schemaBlockers": tuple(sorted(schema_blockers)),
            "evidenceBlockers": tuple(sorted(evidence_blockers)),
            "families": tuple(
                {
                    "kind": item.kind.value,
                    "state": item.state.value,
                    "reasonCodes": item.reason_codes,
                    "evidenceHash": item.evidence_hash,
                    "terminalHash": item.terminal_hash,
                }
                for item in families
            ),
            "constructionVersion": BENCHMARK_CONSTRUCTION_V21,
            "constructionContractHash": (construction.benchmark_contract_hash),
            "constructionBundleHash": construction.bundle_hash,
            "parentLiquidityCostPolicyHash": (parent_liquidity_cost_policy_hash),
            "prospectiveEnrollmentAllowed": ready,
            "databaseWrites": 0,
            "providerNetworkRequests": 0,
        }
        return BenchmarkDbReadinessV21(
            version=BENCHMARK_DB_READINESS_V21,
            status=status,
            data_snapshot_id=data_snapshot_id,
            snapshot_as_of=as_of,
            ingestion_cutoff=cutoff,
            universe_version=universe_version,
            universe_hash=universe_hash,
            declared_security_count=declared_count,
            loaded_security_count=len(members),
            schema_blockers=tuple(sorted(schema_blockers)),
            evidence_blockers=tuple(sorted(evidence_blockers)),
            families=families,
            construction_contract_hash=(construction.benchmark_contract_hash),
            construction_bundle_hash=construction.bundle_hash,
            parent_liquidity_cost_policy_hash=(parent_liquidity_cost_policy_hash),
            prospective_enrollment_allowed=ready,
            database_writes=0,
            provider_network_requests=0,
            diagnostic_content_hash=canonical_hash(payload),
        )
