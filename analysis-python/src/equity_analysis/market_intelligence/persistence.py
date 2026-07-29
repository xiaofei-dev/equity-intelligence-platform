from __future__ import annotations

import base64
import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import psycopg

from equity_analysis.market_intelligence.models import (
    AiNarrative,
    Classification,
    ComparableCohort,
    CurrentMarketData,
    DatasetFreshness,
    DeterministicView,
    DeterministicViewState,
    DurableProfileItem,
    EvidenceLineage,
    FactState,
    Horizon,
    HorizonView,
    MarketIntelligenceFacets,
    MarketIntelligenceProfileEnvelope,
    ProfileFact,
    ProfileState,
    RankedSecurity,
    RankingState,
    RankMetric,
    ScreeningRequest,
    ScreeningResult,
    ScreeningResultPage,
    ScreeningRunMetadata,
    SecurityMaster,
    SecurityProfile,
    SecuritySearchItem,
    SecuritySearchPage,
    SortDirection,
    ValuationEvidence,
)
from equity_analysis.market_intelligence.service import MARKET_INTELLIGENCE_VERSION

METHODOLOGY_REFERENCE = "docs/market-intelligence-screening-v1.md"


class MarketIntelligenceConflictError(ValueError):
    code = "IDEMPOTENCY_KEY_CONFLICT"


class MarketIntelligenceNotFoundError(ValueError):
    code = "MARKET_INTELLIGENCE_PROFILE_NOT_FOUND"


class MarketIntelligenceSnapshotError(ValueError):
    code = "MARKET_INTELLIGENCE_SNAPSHOT_NOT_READY"


class MarketIntelligenceCursorError(ValueError):
    code = "INVALID_CURSOR"


def canonical_hash(value: Any) -> str:
    canonical = json.dumps(
        _json_value(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return "sha256:" + hashlib.sha256(canonical.encode()).hexdigest()


class MarketIntelligenceRepository:
    def __init__(self, database_url: str) -> None:
        if not database_url:
            raise ValueError("Analytics database URL is required")
        self.database_url = database_url

    def persist_profile(
        self,
        profile: SecurityProfile,
        *,
        snapshot_as_of: datetime,
        data_snapshot_id: UUID,
    ) -> UUID:
        if profile.contract_version != MARKET_INTELLIGENCE_VERSION:
            raise ValueError("Unsupported market-intelligence contract version")
        if profile.valuation.evidence:
            raise ValueError(
                "Durable valuation evidence must reference selected profile facts; "
                "inline valuation facts are not persisted by V17"
            )
        payload_hash = canonical_hash(profile)
        with psycopg.connect(self.database_url) as connection:
            security_id = self._security_id(connection, profile.security.security_id)
            self._ready_snapshot(connection, data_snapshot_id, snapshot_as_of)
            membership = self._require_row(
                connection,
                """
                SELECT member.universe_version, member.membership_status
                FROM analytics.snapshot_universe_member member
                JOIN analytics.security security ON security.id = member.security_id
                WHERE member.snapshot_id = %s AND security.id = %s
                """,
                (data_snapshot_id, security_id),
                "Security is not a member of the data snapshot universe",
            )
            if membership[1] not in ("INCLUDED", "REFERENCE_ONLY", "EXCLUDED"):
                raise MarketIntelligenceSnapshotError(
                    "Snapshot membership has an unsupported state"
                )
            classification_source_ids = self._lineage_ids(
                connection,
                profile.classification.lineage if profile.classification else (),
            )
            classification = profile.classification
            profile_id = uuid4()
            inserted = connection.execute(
                """
                INSERT INTO analytics.security_profile_snapshot (
                    id, contract_version, security_id, data_snapshot_id,
                    snapshot_as_of, symbol, issuer_name, exchange_mic, currency,
                    instrument_type, cik, durable_provider_id, taxonomy_code,
                    taxonomy_version, sector_code, sector_name, industry_code,
                    industry_name, company_type, classification_effective_at,
                    classification_source_record_id, profile_state, ranking_state,
                    objective_rating_status, objective_rating_version,
                    objective_quality_score, objective_valuation_score,
                    explainability, input_payload_hash
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s::jsonb, %s
                )
                ON CONFLICT (
                    security_id, snapshot_as_of, contract_version, input_payload_hash
                ) DO NOTHING
                RETURNING id
                """,
                (
                    profile_id,
                    profile.contract_version,
                    security_id,
                    data_snapshot_id,
                    snapshot_as_of,
                    profile.security.symbol,
                    profile.security.issuer_name,
                    profile.security.exchange_mic,
                    profile.security.currency,
                    profile.security.instrument_type,
                    profile.security.cik,
                    profile.security.durable_provider_id,
                    classification.taxonomy_code if classification else None,
                    classification.taxonomy_version if classification else None,
                    classification.sector_code if classification else None,
                    classification.sector_name if classification else None,
                    classification.industry_code if classification else None,
                    classification.industry_name if classification else None,
                    classification.company_type if classification else None,
                    classification.effective_at if classification else None,
                    classification_source_ids[0] if classification_source_ids else None,
                    profile.profile_state,
                    profile.ranking_state,
                    profile.objective_rating_status,
                    profile.objective_rating_version,
                    profile.objective_quality_score,
                    profile.objective_valuation_score,
                    _json(profile.explainability),
                    payload_hash,
                ),
            ).fetchone()
            if inserted is None:
                row = connection.execute(
                    """
                    SELECT id FROM analytics.security_profile_snapshot
                    WHERE security_id = %s AND snapshot_as_of = %s
                      AND contract_version = %s AND input_payload_hash = %s
                    """,
                    (security_id, snapshot_as_of, profile.contract_version, payload_hash),
                ).fetchone()
                if row is None:
                    raise MarketIntelligenceConflictError("Profile idempotency lookup failed")
                return row[0]
            self._insert_profile_children(
                connection,
                profile_id,
                security_id,
                profile,
                classification_source_ids,
                snapshot_as_of,
            )
        return profile_id

    def persist_screening_run(
        self,
        request: ScreeningRequest,
        result: ScreeningResult,
        profile_ids: dict[str, UUID],
        *,
        idempotency_key: str,
        data_snapshot_id: UUID,
        universe_version: str,
    ) -> UUID:
        if not idempotency_key.strip():
            raise ValueError("Idempotency-Key is required")
        request_hash = canonical_hash(request)
        input_hash = canonical_hash(sorted(str(value) for value in profile_ids.values()))
        result_hash = canonical_hash(result)
        now = datetime.now(UTC)
        with psycopg.connect(self.database_url) as connection:
            self._ready_snapshot(connection, data_snapshot_id, request.as_of)
            snapshot_profiles = connection.execute(
                """
                SELECT DISTINCT ON (p.security_id) p.id, s.public_id
                FROM analytics.security_profile_snapshot p
                JOIN analytics.security s ON s.id = p.security_id
                JOIN analytics.snapshot_universe_member member
                  ON member.snapshot_id = p.data_snapshot_id
                 AND member.security_id = p.security_id
                WHERE p.data_snapshot_id = %s
                  AND member.universe_version = %s
                ORDER BY p.security_id, p.snapshot_as_of DESC,
                         p.created_at DESC, p.id
                """,
                (data_snapshot_id, universe_version),
            ).fetchall()
            expected = {str(row[1]): row[0] for row in snapshot_profiles}
            if profile_ids != expected:
                raise MarketIntelligenceSnapshotError(
                    "Screening profiles must exactly match the snapshot universe profile set"
                )
            existing = connection.execute(
                """
                SELECT id, canonical_request_hash, input_snapshot_hash, result_hash
                FROM analytics.market_intelligence_screening_run
                WHERE idempotency_key = %s
                """,
                (idempotency_key,),
            ).fetchone()
            if existing is not None:
                if tuple(existing[1:]) != (request_hash, input_hash, result_hash):
                    raise MarketIntelligenceConflictError(
                        "Idempotency key is associated with different screening content"
                    )
                return existing[0]
            run_id = uuid4()
            acceptance = result.acceptance
            connection.execute(
                """
                INSERT INTO analytics.market_intelligence_screening_run (
                    id, contract_version, idempotency_key, canonical_request_hash,
                    as_of_time, data_snapshot_id, filter_payload, rank_metric,
                    sort_direction, result_limit, methodology_reference,
                    input_snapshot_hash, eligible_count, excluded_count,
                    sector_coverage_count, security_coverage_count,
                    fresh_profile_count, explainable_count, gate_status,
                    result_hash, created_at, sealed_at
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                """,
                (
                    run_id,
                    result.contract_version,
                    idempotency_key,
                    request_hash,
                    request.as_of,
                    data_snapshot_id,
                    _json(
                        {
                            "filters": request.filters,
                            "universeVersion": universe_version,
                            "exclusions": result.exclusions,
                        }
                    ),
                    request.rank_by,
                    request.direction,
                    request.limit,
                    METHODOLOGY_REFERENCE,
                    input_hash,
                    result.eligible_count,
                    result.excluded_count,
                    acceptance["sectorCoverageCount"],
                    acceptance["securityCoverageCount"],
                    acceptance["freshProfileCount"],
                    acceptance["explainableCount"],
                    acceptance["gateStatus"],
                    result_hash,
                    now,
                    now,
                ),
            )
            for item in result.items:
                connection.execute(
                    """
                    INSERT INTO analytics.market_intelligence_screening_result (
                        run_id, profile_id, rank, metric_value,
                        sector_code, industry_code
                    ) VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (
                        run_id,
                        profile_ids[item.security_id],
                        item.rank,
                        item.value,
                        item.sector_code,
                        item.industry_code,
                    ),
                )
        return run_id

    def load_profiles_for_snapshot(
        self,
        data_snapshot_id: UUID,
        universe_version: str,
        as_of: datetime,
    ) -> tuple[tuple[UUID, SecurityProfile], ...]:
        with psycopg.connect(self.database_url) as connection:
            self._ready_snapshot(connection, data_snapshot_id, as_of)
            rows = connection.execute(
                """
                SELECT DISTINCT ON (profile.security_id)
                       profile.id, security.public_id
                FROM analytics.security_profile_snapshot profile
                JOIN analytics.security security ON security.id = profile.security_id
                JOIN analytics.snapshot_universe_member member
                  ON member.snapshot_id = profile.data_snapshot_id
                 AND member.security_id = profile.security_id
                WHERE profile.data_snapshot_id = %s
                  AND member.universe_version = %s
                  AND profile.snapshot_as_of <= %s
                ORDER BY profile.security_id, profile.snapshot_as_of DESC,
                         profile.created_at DESC, profile.id
                """,
                (data_snapshot_id, universe_version, as_of),
            ).fetchall()
        return tuple((row[0], self.load_profile(row[0])) for row in rows)

    def load_latest_profile(
        self,
        security_public_id: UUID,
        *,
        as_of: datetime,
    ) -> tuple[UUID, SecurityProfile]:
        with psycopg.connect(self.database_url) as connection:
            row = connection.execute(
                """
                SELECT profile.id
                FROM analytics.security_profile_snapshot profile
                JOIN analytics.security security ON security.id = profile.security_id
                JOIN analytics.data_snapshot snapshot ON snapshot.id = profile.data_snapshot_id
                WHERE security.public_id = %s
                  AND profile.snapshot_as_of <= %s
                  AND snapshot.status = 'READY'
                ORDER BY profile.snapshot_as_of DESC, profile.created_at DESC, profile.id
                LIMIT 1
                """,
                (security_public_id, as_of),
            ).fetchone()
        if row is None:
            raise MarketIntelligenceNotFoundError("Unknown durable security profile")
        return row[0], self.load_profile(row[0])

    def load_run_metadata(self, run_id: UUID) -> ScreeningRunMetadata:
        with psycopg.connect(self.database_url) as connection:
            row = connection.execute(
                """
                SELECT run.id, run.data_snapshot_id,
                       run.filter_payload->>'universeVersion',
                       run.as_of_time, run.rank_metric, run.sort_direction,
                       run.eligible_count, run.excluded_count, run.gate_status,
                       run.input_snapshot_hash, run.result_hash, run.sealed_at
                FROM analytics.market_intelligence_screening_run run
                WHERE run.id = %s
                """,
                (run_id,),
            ).fetchone()
        if row is None:
            error = MarketIntelligenceNotFoundError("Unknown durable screening run")
            error.code = "MARKET_INTELLIGENCE_RUN_NOT_FOUND"
            raise error
        if row[1] is None or not row[2]:
            raise MarketIntelligenceSnapshotError(
                "Legacy screening run has no sealed snapshot/universe binding"
            )
        return ScreeningRunMetadata(
            run_id=row[0],
            data_snapshot_id=row[1],
            universe_version=row[2],
            as_of=row[3],
            rank_by=row[4],
            direction=row[5],
            eligible_count=row[6],
            excluded_count=row[7],
            gate_status=row[8],
            profile_set_hash=row[9],
            result_hash=row[10],
            sealed_at=row[11],
        )

    def load_screening_page(
        self,
        run_id: UUID,
        *,
        cursor: str | None,
        limit: int,
    ) -> ScreeningResultPage:
        if not 1 <= limit <= 100:
            raise ValueError("Page limit must be between 1 and 100")
        after_rank = _decode_cursor(cursor, run_id) if cursor else 0
        metadata = self.load_run_metadata(run_id)
        with psycopg.connect(self.database_url) as connection:
            rows = connection.execute(
                """
                SELECT result.profile_id, result.rank
                FROM analytics.market_intelligence_screening_result result
                WHERE result.run_id = %s AND result.rank > %s
                ORDER BY result.rank
                LIMIT %s
                """,
                (run_id, after_rank, limit + 1),
            ).fetchall()
        visible = rows[:limit]
        items = tuple(
            DurableProfileItem(**envelope.model_dump())
            for row in visible
            for envelope in (self.load_profile_envelope(row[0]),)
        )
        next_cursor = (
            _encode_cursor(run_id, visible[-1][1])
            if len(rows) > limit and visible
            else None
        )
        return ScreeningResultPage(run=metadata, items=items, next_cursor=next_cursor)

    def search_securities(
        self,
        data_snapshot_id: UUID,
        *,
        query: str = "",
        cursor: str | None = None,
        limit: int = 20,
    ) -> SecuritySearchPage:
        if not 1 <= limit <= 100:
            raise ValueError("Page limit must be between 1 and 100")
        after_id = _decode_search_cursor(cursor, data_snapshot_id) if cursor else 0
        with psycopg.connect(self.database_url) as connection:
            snapshot = self._ready_snapshot(connection, data_snapshot_id)
            rows = connection.execute(
                """
                SELECT security.id, security.public_id, member.symbol_at_snapshot,
                       security.name, listing.mic, security.currency,
                       member.membership_status,
                       member.company_type_at_snapshot,
                       member.normalized_sector_at_snapshot,
                       classification.normalized_industry,
                       profile.id
                FROM analytics.snapshot_universe_member member
                JOIN analytics.security security ON security.id = member.security_id
                LEFT JOIN LATERAL (
                    SELECT item.mic FROM analytics.security_listing item
                    WHERE item.security_id = security.id
                      AND item.valid_from <= %s::date
                      AND (item.valid_to IS NULL OR item.valid_to > %s::date)
                    ORDER BY item.valid_from DESC LIMIT 1
                ) listing ON TRUE
                LEFT JOIN LATERAL (
                    SELECT item.normalized_industry
                    FROM analytics.security_classification item
                    WHERE item.security_id = security.id
                    ORDER BY item.effective_from DESC LIMIT 1
                ) classification ON TRUE
                LEFT JOIN LATERAL (
                    SELECT item.id FROM analytics.security_profile_snapshot item
                    WHERE item.security_id = security.id
                      AND item.data_snapshot_id = member.snapshot_id
                    ORDER BY item.snapshot_as_of DESC, item.created_at DESC LIMIT 1
                ) profile ON TRUE
                WHERE member.snapshot_id = %s
                  AND security.id > %s
                  AND (
                    %s = '' OR member.symbol_at_snapshot ILIKE '%%' || %s || '%%'
                    OR security.name ILIKE '%%' || %s || '%%'
                  )
                ORDER BY security.id
                LIMIT %s
                """,
                (
                    snapshot[2],
                    snapshot[2],
                    data_snapshot_id,
                    after_id,
                    query.strip(),
                    query.strip(),
                    query.strip(),
                    limit + 1,
                ),
            ).fetchall()
            universe_version = snapshot[3]
        visible = rows[:limit]
        items: list[SecuritySearchItem] = []
        for row in visible:
            envelope = self.load_profile_envelope(row[10]) if row[10] else None
            items.append(
                SecuritySearchItem(
                    security_id=str(row[1]),
                    symbol=row[2],
                    issuer_name=row[3],
                    exchange_mic=row[4] or "XXXX",
                    membership_status=row[6],
                    company_type=row[7],
                    sector=row[8],
                    industry=row[9],
                    latest_profile_id=row[10],
                    current_market_data=(
                        envelope.current_market_data
                        if envelope
                        else CurrentMarketData(
                            state=FactState.MISSING,
                            currency=row[5],
                            reason="DURABLE_PROFILE_NOT_BUILT",
                        )
                    ),
                    freshness=envelope.freshness if envelope else (),
                    model_versions=envelope.model_versions if envelope else {},
                )
            )
        return SecuritySearchPage(
            data_snapshot_id=data_snapshot_id,
            universe_version=universe_version,
            items=tuple(items),
            next_cursor=(
                _encode_search_cursor(data_snapshot_id, visible[-1][0])
                if len(rows) > limit and visible
                else None
            ),
        )

    def load_facets(self, data_snapshot_id: UUID) -> MarketIntelligenceFacets:
        with psycopg.connect(self.database_url) as connection:
            snapshot = self._ready_snapshot(connection, data_snapshot_id)
            rows = connection.execute(
                """
                SELECT DISTINCT normalized_sector_at_snapshot,
                       company_type_at_snapshot, membership_status
                FROM analytics.snapshot_universe_member
                WHERE snapshot_id = %s
                """,
                (data_snapshot_id,),
            ).fetchall()
            industries = connection.execute(
                """
                SELECT DISTINCT classification.normalized_industry
                FROM analytics.snapshot_universe_member member
                JOIN LATERAL (
                    SELECT item.normalized_industry
                    FROM analytics.security_classification item
                    WHERE item.security_id = member.security_id
                    ORDER BY item.effective_from DESC LIMIT 1
                ) classification ON TRUE
                WHERE member.snapshot_id = %s
                  AND classification.normalized_industry IS NOT NULL
                """,
                (data_snapshot_id,),
            ).fetchall()
        return MarketIntelligenceFacets(
            data_snapshot_id=data_snapshot_id,
            universe_version=snapshot[3],
            sectors=tuple(sorted({row[0] for row in rows if row[0]})),
            industries=tuple(sorted(row[0] for row in industries)),
            company_types=tuple(sorted({row[1] for row in rows})),
            membership_statuses=tuple(sorted({row[2] for row in rows})),
        )

    def persist_decision_snapshot_event(
        self,
        *,
        data_snapshot_id: UUID,
        universe_version: str,
        objective_screening_run_id: UUID | None,
        profile_ids: tuple[UUID, ...],
        screening_run_ids: tuple[UUID, ...],
        as_of: datetime,
    ) -> str:
        detail = {
            "contractVersion": MARKET_INTELLIGENCE_VERSION,
            "dataSnapshotId": str(data_snapshot_id),
            "universeVersion": universe_version,
            "objectiveScreeningRunId": (
                str(objective_screening_run_id) if objective_screening_run_id else None
            ),
            "profileSetHash": canonical_hash(sorted(str(item) for item in profile_ids)),
            "screeningRunSetHash": canonical_hash(
                sorted(str(item) for item in screening_run_ids)
            ),
            "asOf": as_of,
            "aiStatus": "NOT_EXECUTED",
        }
        event_hash = canonical_hash(detail)
        with psycopg.connect(self.database_url) as connection:
            self._ready_snapshot(connection, data_snapshot_id, as_of)
            if objective_screening_run_id is not None:
                self._require_row(
                    connection,
                    """
                    SELECT id FROM analytics.screening_run
                    WHERE id = %s AND snapshot_id = %s
                      AND universe_version = %s AND status = 'SUCCEEDED'
                    """,
                    (
                        objective_screening_run_id,
                        data_snapshot_id,
                        universe_version,
                    ),
                    "Objective screening run is not sealed for this snapshot/universe",
                )
            run_count = connection.execute(
                """
                SELECT COUNT(*) FROM analytics.market_intelligence_screening_run
                WHERE id = ANY(%s::uuid[]) AND data_snapshot_id = %s
                  AND filter_payload->>'universeVersion' = %s
                """,
                (
                    list(screening_run_ids),
                    data_snapshot_id,
                    universe_version,
                ),
            ).fetchone()[0]
            if run_count != len(set(screening_run_ids)):
                raise MarketIntelligenceSnapshotError(
                    "Market Intelligence runs do not match the decision snapshot"
                )
            connection.execute(
                """
                INSERT INTO analytics.analytics_audit_event (
                    event_type, entity_type, entity_id, actor_service,
                    occurred_at, correlation_id, event_hash, detail
                ) VALUES (
                    'MARKET_INTELLIGENCE_DECISION_SNAPSHOT_SEALED',
                    'DATA_SNAPSHOT', %s, 'PYTHON_ANALYTICS',
                    %s, %s, %s, %s::jsonb
                )
                ON CONFLICT (event_hash) DO NOTHING
                """,
                (
                    str(data_snapshot_id),
                    as_of,
                    str(data_snapshot_id),
                    event_hash,
                    _json(detail),
                ),
            )
        return event_hash

    @staticmethod
    def _ready_snapshot(connection, snapshot_id: UUID, as_of: datetime | None = None):
        row = connection.execute(
            """
            SELECT snapshot.id, snapshot.status, snapshot.as_of_time,
                   member.universe_version
            FROM analytics.data_snapshot snapshot
            LEFT JOIN analytics.snapshot_universe_member member
              ON member.snapshot_id = snapshot.id
            WHERE snapshot.id = %s
            GROUP BY snapshot.id, snapshot.status, snapshot.as_of_time,
                     member.universe_version
            ORDER BY member.universe_version
            LIMIT 1
            """,
            (snapshot_id,),
        ).fetchone()
        if row is None or row[1] != "READY":
            raise MarketIntelligenceSnapshotError("Data snapshot must exist and be READY")
        if as_of is not None and row[2] != as_of:
            raise MarketIntelligenceSnapshotError(
                "Request asOf must exactly match the sealed data snapshot"
            )
        if row[3] is None:
            raise MarketIntelligenceSnapshotError("READY snapshot has no universe membership")
        return row

    def load_profile(self, profile_id: UUID) -> SecurityProfile:
        with psycopg.connect(self.database_url) as connection:
            row = connection.execute(
                """
                SELECT p.contract_version, s.public_id, p.symbol, p.issuer_name,
                       p.exchange_mic, p.currency, p.instrument_type, p.cik,
                       p.durable_provider_id, p.taxonomy_code, p.taxonomy_version,
                       p.sector_code, p.sector_name, p.industry_code, p.industry_name,
                       p.company_type, p.classification_effective_at, p.profile_state,
                       p.ranking_state, p.objective_rating_status,
                       p.objective_rating_version, p.objective_quality_score,
                       p.objective_valuation_score, p.explainability
                FROM analytics.security_profile_snapshot p
                JOIN analytics.security s ON s.id = p.security_id
                WHERE p.id = %s
                """,
                (profile_id,),
            ).fetchone()
            if row is None:
                raise MarketIntelligenceNotFoundError("Unknown durable profile")
            classification = self._load_classification(connection, profile_id, row)
            facts = self._load_facts(connection, profile_id)
            cohorts = self._load_cohorts(connection, profile_id)
            horizons = self._load_horizons(connection, profile_id)
            valuation = self._load_valuation(connection, profile_id)
            exclusions = tuple(
                item[0]
                for item in connection.execute(
                    """
                    SELECT reason_code
                    FROM analytics.market_intelligence_ranking_exclusion
                    WHERE profile_id = %s ORDER BY reason_ordinal
                    """,
                    (profile_id,),
                ).fetchall()
            )
            ai = self._load_ai(connection, profile_id)
        return SecurityProfile(
            contract_version=row[0],
            security=SecurityMaster(
                security_id=str(row[1]),
                symbol=row[2],
                issuer_name=row[3],
                exchange_mic=row[4],
                currency=row[5],
                instrument_type=row[6],
                cik=row[7],
                durable_provider_id=row[8],
            ),
            classification=classification,
            comparable_cohorts=cohorts,
            facts=facts,
            objective_quality_score=row[21],
            objective_valuation_score=row[22],
            objective_rating_status=row[19],
            objective_rating_version=row[20],
            horizons=horizons,
            valuation=valuation,
            profile_state=ProfileState(row[17]),
            ranking_state=RankingState(row[18]),
            ranking_exclusions=exclusions,
            explainability=tuple(row[23]),
            ai_narrative=ai,
        )

    def load_profile_envelope(
        self,
        profile_id: UUID,
    ) -> MarketIntelligenceProfileEnvelope:
        profile = self.load_profile(profile_id)
        latest_price = next(
            (item for item in profile.facts if item.name == "latest_price"),
            None,
        )
        lineage = latest_price.lineage[0] if latest_price and latest_price.lineage else None
        with psycopg.connect(self.database_url) as connection:
            profile_row = connection.execute(
                """
                SELECT profile.security_id, snapshot.market_adjustment_mode
                FROM analytics.security_profile_snapshot profile
                JOIN analytics.data_snapshot snapshot ON snapshot.id = profile.data_snapshot_id
                WHERE profile.id = %s AND snapshot.status = 'READY'
                """,
                (profile_id,),
            ).fetchone()
            if profile_row is None:
                raise MarketIntelligenceSnapshotError(
                    "Durable profile is not bound to a READY data snapshot"
                )
            freshness_rows = connection.execute(
                """
                SELECT DISTINCT ON (freshness.dataset_code)
                       freshness.dataset_code, freshness.status, provider.code,
                       freshness.last_successful_effective_at,
                       freshness.last_successful_available_at,
                       freshness.last_successful_ingested_at,
                       freshness.evaluated_at, freshness.stale_after,
                       freshness.reason_code
                FROM analytics.security_dataset_freshness freshness
                LEFT JOIN analytics.data_provider provider
                  ON provider.id = freshness.provider_id
                WHERE freshness.security_id = %s
                ORDER BY freshness.dataset_code, freshness.evaluated_at DESC,
                         freshness.id DESC
                """,
                (profile_row[0],),
            ).fetchall()
        current_market_data = CurrentMarketData(
            state=latest_price.state if latest_price else FactState.MISSING,
            price=(
                Decimal(latest_price.value)
                if latest_price and latest_price.state == FactState.VALID
                else None
            ),
            currency=profile.security.currency,
            trading_date=(
                lineage.effective_at.date()
                if lineage and lineage.effective_at is not None
                else None
            ),
            provider_code=lineage.provider_code if lineage else None,
            available_at=lineage.available_at if lineage else None,
            ingested_at=lineage.retrieved_at if lineage else None,
            adjustment_mode=profile_row[1] if lineage else None,
            reason=(
                None
                if latest_price and latest_price.state == FactState.VALID
                else latest_price.reason
                if latest_price
                else "LATEST_PRICE_FACT_MISSING"
            ),
        )
        freshness = tuple(
            DatasetFreshness(
                dataset_code=row[0],
                state=row[1],
                provider_code=row[2],
                effective_at=row[3],
                available_at=row[4],
                ingested_at=row[5],
                evaluated_at=row[6],
                stale_after=row[7],
                reason_code=row[8],
            )
            for row in freshness_rows
        )
        model_versions = {
            "objectiveRating": profile.objective_rating_version,
            **{
                item.horizon.value: item.deterministic_view.model_version
                for item in profile.horizons
            },
        }
        return MarketIntelligenceProfileEnvelope(
            profile_id=profile_id,
            security_id=profile.security.security_id,
            profile=profile,
            current_market_data=current_market_data,
            freshness=freshness,
            model_versions=model_versions,
        )

    def load_screening_result(self, run_id: UUID) -> ScreeningResult:
        with psycopg.connect(self.database_url) as connection:
            run = connection.execute(
                """
                SELECT contract_version, as_of_time, filter_payload, rank_metric,
                       sort_direction, result_limit, eligible_count, excluded_count,
                       sector_coverage_count, security_coverage_count,
                       fresh_profile_count, explainable_count, gate_status
                FROM analytics.market_intelligence_screening_run WHERE id = %s
                """,
                (run_id,),
            ).fetchone()
            if run is None:
                raise MarketIntelligenceNotFoundError("Unknown durable screening run")
            profile_rows = connection.execute(
                """
                SELECT profile_id, rank, metric_value, sector_code, industry_code
                FROM analytics.market_intelligence_screening_result
                WHERE run_id = %s ORDER BY rank
                """,
                (run_id,),
            ).fetchall()
        metric = RankMetric(run[3])
        items = tuple(
            RankedSecurity(
                rank=item[1],
                security_id=profile.security.security_id,
                symbol=profile.security.symbol,
                sector_code=item[3],
                industry_code=item[4],
                metric=metric,
                value=item[2],
                profile=profile,
            )
            for item in profile_rows
            for profile in (self.load_profile(item[0]),)
        )
        return ScreeningResult(
            contract_version=run[0],
            as_of=run[1],
            rank_by=metric,
            direction=SortDirection(run[4]),
            eligible_count=run[6],
            excluded_count=run[7],
            items=items,
            exclusions={
                key: tuple(value)
                for key, value in run[2].get("exclusions", {}).items()
            },
            acceptance={
                "sectorCoverageCount": run[8],
                "securityCoverageCount": run[9],
                "freshProfileCount": run[10],
                "rankingEligibleCount": run[6],
                "explainableCount": run[11],
                "gateStatus": run[12],
            },
        )

    def _insert_profile_children(
        self,
        connection,
        profile_id,
        security_id,
        profile,
        classification_source_ids,
        snapshot_as_of,
    ) -> None:
        if profile.classification:
            for ordinal, (lineage, source_id) in enumerate(
                zip(profile.classification.lineage, classification_source_ids, strict=True),
                start=1,
            ):
                connection.execute(
                    """
                    INSERT INTO analytics.security_profile_classification_lineage (
                        profile_id, lineage_ordinal, source_record_id,
                        effective_at, available_at, retrieved_at
                    ) VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (
                        profile_id,
                        ordinal,
                        source_id,
                        lineage.effective_at or profile.classification.effective_at,
                        lineage.available_at,
                        lineage.retrieved_at,
                    ),
                )
        for order, fact in enumerate(profile.facts):
            observation_id = self._metric_observation_id(
                connection,
                security_id,
                fact,
                snapshot_as_of,
            )
            connection.execute(
                """
                INSERT INTO analytics.security_profile_fact (
                    profile_id, fact_name, metric_observation_id, display_order
                ) VALUES (%s, %s, %s, %s)
                """,
                (profile_id, fact.name, observation_id, order),
            )
            for ordinal, (lineage, source_id) in enumerate(
                zip(
                    fact.lineage,
                    self._lineage_ids(connection, fact.lineage),
                    strict=True,
                ),
                start=1,
            ):
                connection.execute(
                    """
                    INSERT INTO analytics.security_profile_fact_lineage (
                        profile_id, fact_name, lineage_ordinal, source_record_id,
                        effective_at, available_at, retrieved_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        profile_id,
                        fact.name,
                        ordinal,
                        source_id,
                        lineage.effective_at,
                        lineage.available_at,
                        lineage.retrieved_at,
                    ),
                )
        for cohort in profile.comparable_cohorts:
            connection.execute(
                """
                INSERT INTO analytics.comparable_cohort_snapshot (
                    profile_id, cohort_id, taxonomy_version, sector_code,
                    industry_code, company_type, size_band,
                    eligible_member_count, minimum_member_count
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    profile_id,
                    cohort.cohort_id,
                    cohort.taxonomy_version,
                    cohort.sector_code,
                    cohort.industry_code,
                    cohort.company_type,
                    cohort.size_band,
                    cohort.eligible_member_count,
                    cohort.minimum_member_count,
                ),
            )
        for item in profile.horizons:
            view = item.deterministic_view
            connection.execute(
                """
                INSERT INTO analytics.market_intelligence_horizon_view (
                    profile_id, horizon, model_id, model_version, view_state,
                    model_as_of, effective_at, expires_at, score, label,
                    input_hash, evidence_hash, missing_inputs, explanation
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s::jsonb, %s::jsonb
                )
                """,
                (
                    profile_id,
                    item.horizon,
                    view.model_id,
                    view.model_version,
                    view.state,
                    view.as_of,
                    view.effective_at,
                    view.expires_at,
                    view.score,
                    view.label,
                    view.input_hash,
                    view.evidence_hash,
                    _json(view.missing_inputs),
                    _json(view.explanation),
                ),
            )
        valuation = profile.valuation
        connection.execute(
            """
            INSERT INTO analytics.market_intelligence_valuation_evidence (
                profile_id, evidence_state, evidence_as_of,
                objective_valuation_score, long_horizon_valuation_score,
                own_history_percentile, limitations, evidence_hash
            ) VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s)
            """,
            (
                profile_id,
                valuation.state,
                valuation.as_of,
                valuation.objective_valuation_score,
                valuation.long_horizon_valuation_score,
                valuation.own_history_percentile,
                _json(valuation.limitations),
                canonical_hash(valuation),
            ),
        )
        for ordinal, reason in enumerate(profile.ranking_exclusions, start=1):
            connection.execute(
                """
                INSERT INTO analytics.market_intelligence_ranking_exclusion (
                    profile_id, reason_ordinal, reason_code, exclusion_category
                ) VALUES (%s, %s, %s, %s)
                """,
                (profile_id, ordinal, reason, _exclusion_category(reason)),
            )
        if profile.ai_narrative.status != "NOT_EXECUTED":
            ai = profile.ai_narrative
            connection.execute(
                """
                INSERT INTO analytics.market_intelligence_ai_narrative (
                    profile_id, status, narrative, source_references,
                    generated_at, prompt_version, model_version, confidence,
                    narrative_hash, may_affect_deterministic_fields
                ) VALUES (%s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s, FALSE)
                """,
                (
                    profile_id,
                    ai.status,
                    ai.narrative,
                    _json(ai.source_references),
                    ai.generated_at,
                    ai.prompt_version,
                    ai.model_version,
                    ai.confidence,
                    canonical_hash(ai) if ai.narrative else None,
                ),
            )

    def _security_id(self, connection, public_id: str) -> int:
        row = self._require_row(
            connection,
            "SELECT id FROM analytics.security WHERE public_id = %s",
            (UUID(public_id),),
            "Unknown security public ID",
        )
        return row[0]

    def _lineage_ids(self, connection, lineage: tuple[EvidenceLineage, ...]) -> tuple:
        ids = []
        for item in lineage:
            rows = connection.execute(
                """
                SELECT source.id
                FROM analytics.source_record source
                JOIN analytics.data_provider provider ON provider.id = source.provider_id
                JOIN analytics.ingestion_batch batch
                  ON batch.id = source.ingestion_batch_id
                WHERE provider.code = %s
                  AND provider.provider_schema_version = %s
                  AND batch.parser_version = %s
                  AND source.source_reference = %s
                  AND source.content_hash = %s
                  AND source.available_at = %s
                  AND source.ingested_at = %s
                """,
                (
                    item.provider_code,
                    item.provider_schema_version,
                    item.parser_version,
                    item.source_reference,
                    item.content_hash,
                    item.available_at,
                    item.retrieved_at,
                ),
            ).fetchall()
            if len(rows) != 1:
                raise ValueError("Lineage must resolve to exactly one source_record")
            ids.append(rows[0][0])
        return tuple(ids)

    def _metric_observation_id(
        self,
        connection,
        security_id: int,
        fact: ProfileFact,
        snapshot_as_of: datetime,
    ):
        source_ids = self._lineage_ids(connection, fact.lineage)
        effective_dates = tuple(
            item.effective_at.date()
            for item in fact.lineage
            if item.effective_at is not None
        )
        observation_date = (
            max(effective_dates) if effective_dates else snapshot_as_of.date()
        )
        rows = connection.execute(
            """
            SELECT id, status, numeric_value, text_value, boolean_value,
                   COALESCE(reason_detail, reason_code)
            FROM analytics.metric_observation
            WHERE security_id = %s AND metric_code = %s AND metric_version = %s
              AND observation_date = %s
              AND (%s::uuid[] = '{}' OR source_record_id = ANY(%s::uuid[]))
            ORDER BY available_at DESC, ingested_at DESC, revision_number DESC
            """,
            (
                security_id,
                fact.name,
                fact.metric_version,
                observation_date,
                list(source_ids),
                list(source_ids),
            ),
        ).fetchall()
        matches = [row for row in rows if _observation_matches(row, fact)]
        if len(matches) != 1:
            raise ValueError(f"Fact {fact.name} must resolve to exactly one metric_observation")
        return matches[0][0]

    @staticmethod
    def _require_row(connection, query, params, message):
        row = connection.execute(query, params).fetchone()
        if row is None:
            raise ValueError(message)
        return row

    def _load_classification(self, connection, profile_id, row):
        if row[9] is None:
            return None
        lineage = self._load_lineage(
            connection,
            """
            SELECT provider.code, provider.provider_schema_version,
                   batch.parser_version, source.source_reference,
                   source.content_hash, line.available_at, line.retrieved_at,
                   line.effective_at
            FROM analytics.security_profile_classification_lineage line
            JOIN analytics.source_record source ON source.id = line.source_record_id
            JOIN analytics.data_provider provider ON provider.id = source.provider_id
            JOIN analytics.ingestion_batch batch ON batch.id = source.ingestion_batch_id
            WHERE line.profile_id = %s ORDER BY line.lineage_ordinal
            """,
            profile_id,
        )
        return Classification(
            taxonomy_code=row[9],
            taxonomy_version=row[10],
            sector_code=row[11],
            sector_name=row[12],
            industry_code=row[13],
            industry_name=row[14],
            company_type=row[15],
            effective_at=row[16],
            lineage=lineage,
        )

    def _load_facts(self, connection, profile_id):
        rows = connection.execute(
            """
            SELECT fact.fact_name, observation.metric_version, observation.status,
                   observation.numeric_value, observation.text_value,
                   observation.boolean_value,
                   COALESCE(observation.reason_detail, observation.reason_code)
            FROM analytics.security_profile_fact fact
            JOIN analytics.metric_observation observation
              ON observation.id = fact.metric_observation_id
            WHERE fact.profile_id = %s ORDER BY fact.display_order, fact.fact_name
            """,
            (profile_id,),
        ).fetchall()
        return tuple(
            ProfileFact(
                name=row[0],
                metric_version=row[1],
                state=FactState(row[2]),
                value=next(
                    (value for value in row[3:6] if value is not None),
                    None,
                ),
                reason=row[6],
                lineage=self._load_lineage(
                    connection,
                    """
                    SELECT provider.code, provider.provider_schema_version,
                           batch.parser_version, source.source_reference,
                           source.content_hash, line.available_at, line.retrieved_at,
                           line.effective_at
                    FROM analytics.security_profile_fact_lineage line
                    JOIN analytics.source_record source ON source.id = line.source_record_id
                    JOIN analytics.data_provider provider ON provider.id = source.provider_id
                    JOIN analytics.ingestion_batch batch
                      ON batch.id = source.ingestion_batch_id
                    WHERE line.profile_id = %s AND line.fact_name = %s
                    ORDER BY line.lineage_ordinal
                    """,
                    profile_id,
                    row[0],
                ),
            )
            for row in rows
        )

    @staticmethod
    def _load_cohorts(connection, profile_id):
        rows = connection.execute(
            """
            SELECT cohort_id, taxonomy_version, sector_code, industry_code,
                   company_type, size_band, eligible_member_count, minimum_member_count
            FROM analytics.comparable_cohort_snapshot
            WHERE profile_id = %s ORDER BY cohort_id
            """,
            (profile_id,),
        ).fetchall()
        return tuple(
            ComparableCohort(
                **dict(
                    zip(
                        (
                            "cohort_id",
                            "taxonomy_version",
                            "sector_code",
                            "industry_code",
                            "company_type",
                            "size_band",
                            "eligible_member_count",
                            "minimum_member_count",
                        ),
                        row,
                        strict=True,
                    )
                )
            )
            for row in rows
        )

    @staticmethod
    def _load_horizons(connection, profile_id):
        rows = connection.execute(
            """
            SELECT horizon, model_id, model_version, view_state, model_as_of,
                   effective_at, expires_at, score, label, input_hash,
                   evidence_hash, missing_inputs, explanation
            FROM analytics.market_intelligence_horizon_view
            WHERE profile_id = %s ORDER BY horizon
            """,
            (profile_id,),
        ).fetchall()
        return tuple(
            HorizonView(
                horizon=Horizon(row[0]),
                deterministic_view=DeterministicView(
                    model_id=row[1],
                    model_version=row[2],
                    state=DeterministicViewState(row[3]),
                    as_of=row[4],
                    effective_at=row[5],
                    expires_at=row[6],
                    score=row[7],
                    label=row[8],
                    input_hash=row[9],
                    evidence_hash=row[10],
                    missing_inputs=tuple(row[11]),
                    explanation=tuple(row[12]),
                ),
            )
            for row in rows
        )

    @staticmethod
    def _load_valuation(connection, profile_id):
        row = connection.execute(
            """
            SELECT evidence_state, evidence_as_of, objective_valuation_score,
                   long_horizon_valuation_score, own_history_percentile, limitations
            FROM analytics.market_intelligence_valuation_evidence WHERE profile_id = %s
            """,
            (profile_id,),
        ).fetchone()
        if row is None:
            raise MarketIntelligenceNotFoundError("Durable profile has no valuation")
        return ValuationEvidence(
            state=FactState(row[0]),
            as_of=row[1],
            objective_valuation_score=row[2],
            long_horizon_valuation_score=row[3],
            own_history_percentile=row[4],
            limitations=tuple(row[5]),
        )

    @staticmethod
    def _load_ai(connection, profile_id):
        row = connection.execute(
            """
            SELECT status, narrative, source_references, generated_at,
                   prompt_version, model_version, confidence,
                   may_affect_deterministic_fields
            FROM analytics.market_intelligence_ai_narrative WHERE profile_id = %s
            """,
            (profile_id,),
        ).fetchone()
        return (
            AiNarrative(status="NOT_EXECUTED")
            if row is None
            else AiNarrative(
                status=row[0],
                narrative=row[1],
                source_references=tuple(row[2]),
                generated_at=row[3],
                prompt_version=row[4],
                model_version=row[5],
                confidence=row[6],
                may_affect_deterministic_fields=row[7],
            )
        )

    @staticmethod
    def _load_lineage(connection, query, *params):
        return tuple(
            EvidenceLineage(
                provider_code=row[0],
                provider_schema_version=row[1],
                parser_version=row[2],
                source_reference=row[3],
                content_hash=row[4],
                available_at=row[5],
                retrieved_at=row[6],
                effective_at=row[7],
            )
            for row in connection.execute(query, params).fetchall()
        )


def _observation_matches(row, fact: ProfileFact) -> bool:
    if row[1] != fact.state:
        return False
    stored = next((value for value in row[2:5] if value is not None), None)
    if fact.state == FactState.VALID:
        if isinstance(fact.value, bool):
            return stored is fact.value
        if isinstance(fact.value, Decimal | int):
            return Decimal(stored) == Decimal(fact.value)
        return stored == fact.value
    return stored is None and row[5] == fact.reason


def _exclusion_category(reason: str) -> str:
    for token, category in (
        ("CLASSIFICATION", "CLASSIFICATION"),
        ("FACT", "FACT"),
        ("STALE", "STALE"),
        ("COHORT", "COHORT"),
        ("OBJECTIVE", "FORMULA"),
        ("FORMULA", "FORMULA"),
        ("HORIZON", "MODEL"),
        ("FILTER", "FILTER"),
    ):
        if token in reason:
            return category
    return "RANKING"


def _json(value: Any) -> str:
    return json.dumps(_json_value(value), sort_keys=True, separators=(",", ":"))


def _json_value(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json", by_alias=True)
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [_json_value(item) for item in value]
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, UUID):
        return str(value)
    return value


def _encode_cursor(run_id: UUID, rank: int) -> str:
    payload = json.dumps(
        {"runId": str(run_id), "rank": rank},
        sort_keys=True,
        separators=(",", ":"),
    )
    return base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")


def _decode_cursor(cursor: str, run_id: UUID) -> int:
    try:
        padding = "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(cursor + padding))
        if payload != {"runId": str(run_id), "rank": int(payload["rank"])}:
            raise ValueError
        rank = int(payload["rank"])
        if rank < 0:
            raise ValueError
        return rank
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise MarketIntelligenceCursorError("Invalid screening result cursor") from error


def _encode_search_cursor(snapshot_id: UUID, security_id: int) -> str:
    payload = json.dumps(
        {"snapshotId": str(snapshot_id), "securityId": security_id},
        sort_keys=True,
        separators=(",", ":"),
    )
    return base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")


def _decode_search_cursor(cursor: str, snapshot_id: UUID) -> int:
    try:
        padding = "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(cursor + padding))
        if payload["snapshotId"] != str(snapshot_id):
            raise ValueError
        security_id = int(payload["securityId"])
        if security_id < 0:
            raise ValueError
        return security_id
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise MarketIntelligenceCursorError("Invalid security search cursor") from error
