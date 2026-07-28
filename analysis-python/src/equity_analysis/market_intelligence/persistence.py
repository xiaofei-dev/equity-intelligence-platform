from __future__ import annotations

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
    DeterministicView,
    DeterministicViewState,
    EvidenceLineage,
    FactState,
    Horizon,
    HorizonView,
    ProfileFact,
    ProfileState,
    RankedSecurity,
    RankingState,
    RankMetric,
    ScreeningRequest,
    ScreeningResult,
    SecurityMaster,
    SecurityProfile,
    SortDirection,
    ValuationEvidence,
)
from equity_analysis.market_intelligence.service import MARKET_INTELLIGENCE_VERSION

METHODOLOGY_REFERENCE = "docs/market-intelligence-screening-v1.md"


class MarketIntelligenceConflictError(ValueError):
    pass


class MarketIntelligenceNotFoundError(ValueError):
    pass


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
        data_snapshot_id: UUID | None = None,
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
            if data_snapshot_id is not None:
                self._require_row(
                    connection,
                    "SELECT id FROM analytics.data_snapshot WHERE id = %s",
                    (data_snapshot_id,),
                    "Unknown data snapshot",
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
            )
        return profile_id

    def persist_screening_run(
        self,
        request: ScreeningRequest,
        result: ScreeningResult,
        profile_ids: dict[str, UUID],
        *,
        idempotency_key: str,
        data_snapshot_id: UUID | None = None,
    ) -> UUID:
        if not idempotency_key.strip():
            raise ValueError("Idempotency-Key is required")
        request_hash = canonical_hash(request)
        input_hash = canonical_hash(sorted(str(value) for value in profile_ids.values()))
        result_hash = canonical_hash(result)
        now = datetime.now(UTC)
        with psycopg.connect(self.database_url) as connection:
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
                            "profileIds": sorted(
                                str(value) for value in profile_ids.values()
                            ),
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
        self, connection, profile_id, security_id, profile, classification_source_ids
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
            observation_id = self._metric_observation_id(connection, security_id, fact)
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

    def _metric_observation_id(self, connection, security_id: int, fact: ProfileFact):
        source_ids = self._lineage_ids(connection, fact.lineage)
        rows = connection.execute(
            """
            SELECT id, status, numeric_value, text_value, boolean_value,
                   COALESCE(reason_detail, reason_code)
            FROM analytics.metric_observation
            WHERE security_id = %s AND metric_code = %s AND metric_version = %s
              AND (%s::uuid[] = '{}' OR source_record_id = ANY(%s::uuid[]))
            ORDER BY available_at DESC, ingested_at DESC, revision_number DESC
            """,
            (
                security_id,
                fact.name,
                fact.metric_version,
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
