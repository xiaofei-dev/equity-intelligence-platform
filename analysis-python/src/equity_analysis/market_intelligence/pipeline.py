from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID

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
    ProfileInput,
    ValuationEvidence,
)
from equity_analysis.market_intelligence.persistence import (
    MarketIntelligenceRepository,
    MarketIntelligenceSnapshotError,
    canonical_hash,
)
from equity_analysis.market_intelligence.service import build_security_profile
from equity_analysis.tactical.signal_v2 import (
    TACTICAL_SIGNAL_VERSION,
    TacticalBar,
    evaluate_tactical_signal,
)

METRIC_VERSION = "MARKET-INTELLIGENCE-INPUT-v1.0.0"
TACTICAL_MODEL_ID = "DAILY_TACTICAL_SIGNAL"
LONG_MODEL_ID = "LONG_HORIZON_RESEARCH"
_HASH_EMPTY = "sha256:" + "0" * 64


@dataclass(frozen=True)
class SnapshotContext:
    snapshot_id: UUID
    as_of: datetime
    ingestion_cutoff: datetime
    universe_version: str
    market_provider: str
    adjustment_mode: str


@dataclass(frozen=True)
class AssembledProfileSet:
    snapshot: SnapshotContext
    objective_screening_run_id: UUID | None
    profile_ids: tuple[UUID, ...]
    profiles_by_security: dict[str, UUID]
    profile_set_hash: str


class PostgresTacticalInputAdapter:
    """Load only completed, snapshot-bound daily observations from PostgreSQL."""

    def __init__(self, connection) -> None:
        self._connection = connection

    def load(
        self,
        *,
        snapshot: SnapshotContext,
        security_id: int,
        benchmark_security_id: int,
        sessions: int = 260,
    ) -> tuple[tuple[TacticalBar, ...], tuple[TacticalBar, ...], tuple[EvidenceLineage, ...]]:
        security = self._bars(snapshot, security_id, sessions)
        benchmark = self._bars(snapshot, benchmark_security_id, sessions)
        security_by_date = {item[0].trading_date: item for item in security}
        benchmark_by_date = {item[0].trading_date: item for item in benchmark}
        dates = sorted(set(security_by_date) & set(benchmark_by_date))
        bars = tuple(security_by_date[item][0] for item in dates)
        benchmark_bars = tuple(benchmark_by_date[item][0] for item in dates)
        lineage = _unique_lineage(
            tuple(
                item[1]
                for trading_date in dates
                for item in (
                    security_by_date[trading_date],
                    benchmark_by_date[trading_date],
                )
            )
        )
        return bars, benchmark_bars, lineage

    def _bars(
        self,
        snapshot: SnapshotContext,
        security_id: int,
        sessions: int,
    ) -> tuple[tuple[TacticalBar, EvidenceLineage], ...]:
        rows = self._connection.execute(
            """
            SELECT observation.trading_date, observation.open_price,
                   observation.high_price, observation.low_price,
                   observation.close_price, observation.adjusted_close,
                   observation.volume, provider.code,
                   provider.provider_schema_version, batch.parser_version,
                   source.source_reference, source.content_hash,
                   observation.available_at, observation.ingested_at
            FROM analytics.daily_price_observation observation
            JOIN analytics.data_provider provider ON provider.id = observation.provider_id
            JOIN analytics.source_record source ON source.id = observation.source_record_id
            JOIN analytics.ingestion_batch batch ON batch.id = source.ingestion_batch_id
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
            ORDER BY observation.trading_date DESC,
                     observation.revision_number DESC
            LIMIT %s
            """,
            (
                snapshot.snapshot_id,
                security_id,
                snapshot.market_provider,
                snapshot.adjustment_mode,
                snapshot.as_of,
                snapshot.as_of,
                snapshot.ingestion_cutoff,
                sessions,
            ),
        ).fetchall()
        result = []
        for row in reversed(rows):
            factor = (
                Decimal(row[5]) / Decimal(row[4])
                if row[5] is not None and row[4] != 0
                else Decimal(1)
            )
            result.append(
                (
                TacticalBar(
                    trading_date=row[0],
                    open_price=float(Decimal(row[1]) * factor),
                    high_price=float(Decimal(row[2]) * factor),
                    low_price=float(Decimal(row[3]) * factor),
                    close_price=float(row[5] if row[5] is not None else row[4]),
                    volume=row[6],
                    session_complete=True,
                ),
                EvidenceLineage(
                    provider_code=row[7],
                    provider_schema_version=row[8],
                    parser_version=row[9],
                    source_reference=row[10],
                    content_hash=row[11],
                    available_at=row[12],
                    retrieved_at=row[13],
                    effective_at=datetime.combine(row[0], datetime.min.time(), UTC),
                ),
                )
            )
        return tuple(result)


class MarketIntelligenceAssembler:
    """Build immutable V17 profiles from one READY V6 snapshot.

    No provider is reachable from this class. Every observed input must resolve
    through a source batch sealed into the requested snapshot.
    """

    def __init__(self, database_url: str) -> None:
        if not database_url:
            raise ValueError("Analytics database URL is required")
        self.database_url = database_url
        self.repository = MarketIntelligenceRepository(database_url)

    def assemble_snapshot(
        self,
        *,
        data_snapshot_id: UUID,
        universe_version: str,
    ) -> AssembledProfileSet:
        with psycopg.connect(self.database_url) as connection:
            snapshot = self._snapshot(connection, data_snapshot_id, universe_version)
            members = self._members(connection, snapshot)
            benchmark = next(
                (item for item in members if item["symbol"] == "SPY"),
                None,
            )
            objective_run_id = self._objective_run_id(connection, snapshot)
            profile_ids: list[UUID] = []
            profiles_by_security: dict[str, UUID] = {}
            for member in members:
                payload = self._profile_input(
                    connection,
                    snapshot=snapshot,
                    member=member,
                    benchmark=benchmark,
                    objective_run_id=objective_run_id,
                )
                # V17 persistence resolves facts by immutable V15 observation.
                # Commit only those idempotent observations before the repository
                # opens its own transaction; profiles remain independently sealed.
                connection.commit()
                profile = build_security_profile(payload, snapshot.as_of)
                profile_id = self.repository.persist_profile(
                    profile,
                    snapshot_as_of=snapshot.as_of,
                    data_snapshot_id=snapshot.snapshot_id,
                )
                profile_ids.append(profile_id)
                profiles_by_security[profile.security.security_id] = profile_id
        ordered = tuple(sorted(profile_ids, key=str))
        return AssembledProfileSet(
            snapshot=snapshot,
            objective_screening_run_id=objective_run_id,
            profile_ids=ordered,
            profiles_by_security=profiles_by_security,
            profile_set_hash=canonical_hash(tuple(str(item) for item in ordered)),
        )

    @staticmethod
    def _snapshot(
        connection,
        snapshot_id: UUID,
        universe_version: str,
    ) -> SnapshotContext:
        row = connection.execute(
            """
            SELECT snapshot.status, snapshot.as_of_time,
                   snapshot.ingestion_cutoff, snapshot.market_data_provider,
                   snapshot.market_adjustment_mode,
                   COUNT(member.security_id)
            FROM analytics.data_snapshot snapshot
            LEFT JOIN analytics.snapshot_universe_member member
              ON member.snapshot_id = snapshot.id
             AND member.universe_version = %s
            WHERE snapshot.id = %s
            GROUP BY snapshot.status, snapshot.as_of_time,
                     snapshot.ingestion_cutoff, snapshot.market_data_provider,
                     snapshot.market_adjustment_mode
            """,
            (universe_version, snapshot_id),
        ).fetchone()
        if row is None or row[0] != "READY":
            raise MarketIntelligenceSnapshotError("Data snapshot must exist and be READY")
        if row[5] == 0:
            raise MarketIntelligenceSnapshotError(
                "Snapshot does not contain the requested universe version"
            )
        return SnapshotContext(
            snapshot_id=snapshot_id,
            as_of=row[1],
            ingestion_cutoff=row[2],
            universe_version=universe_version,
            market_provider=row[3],
            adjustment_mode=row[4],
        )

    @staticmethod
    def _members(connection, snapshot: SnapshotContext) -> tuple[dict, ...]:
        rows = connection.execute(
            """
            SELECT security.id, security.public_id, member.symbol_at_snapshot,
                   security.name, security.instrument_type, security.currency,
                   member.membership_status, member.membership_reason,
                   member.company_type_at_snapshot,
                   member.normalized_sector_at_snapshot,
                   listing.mic
            FROM analytics.snapshot_universe_member member
            JOIN analytics.security security ON security.id = member.security_id
            LEFT JOIN LATERAL (
                SELECT item.mic FROM analytics.security_listing item
                WHERE item.security_id = security.id
                  AND item.valid_from <= %s::date
                  AND (item.valid_to IS NULL OR item.valid_to > %s::date)
                ORDER BY item.valid_from DESC LIMIT 1
            ) listing ON TRUE
            WHERE member.snapshot_id = %s
              AND member.universe_version = %s
            ORDER BY security.public_id
            """,
            (
                snapshot.as_of,
                snapshot.as_of,
                snapshot.snapshot_id,
                snapshot.universe_version,
            ),
        ).fetchall()
        return tuple(
            {
                "database_id": row[0],
                "public_id": row[1],
                "symbol": row[2],
                "name": row[3],
                "instrument_type": row[4],
                "currency": row[5],
                "membership_status": row[6],
                "membership_reason": row[7],
                "company_type": row[8],
                "sector": row[9],
                "mic": row[10] or "XXXX",
            }
            for row in rows
        )

    def _profile_input(
        self,
        connection,
        *,
        snapshot: SnapshotContext,
        member: dict,
        benchmark: dict | None,
        objective_run_id: UUID | None,
    ) -> ProfileInput:
        from equity_analysis.market_intelligence.models import SecurityMaster

        facts = self._market_facts(connection, snapshot, member["database_id"])
        classification = self._classification(
            connection, snapshot, member["database_id"], member["company_type"]
        )
        cohorts = self._cohorts(connection, snapshot, member, classification)
        quality, valuation_score, objective_status = self._objective(
            connection, objective_run_id, member["database_id"]
        )
        horizons = self._horizons(
            connection,
            snapshot=snapshot,
            member=member,
            benchmark=benchmark,
            objective_run_id=objective_run_id,
        )
        valuation = self._valuation(
            snapshot.as_of,
            valuation_score,
            horizons,
        )
        if member["membership_status"] != "INCLUDED":
            objective_status = "NOT_APPLICABLE"
            quality = None
            valuation_score = None
            horizons = tuple(
                _unassessed_horizon(
                    horizon,
                    snapshot.as_of,
                    "UNIVERSE_MEMBERSHIP_NOT_RANKABLE",
                )
                for horizon in Horizon
            )
            valuation = ValuationEvidence(
                state=FactState.NOT_APPLICABLE,
                as_of=snapshot.as_of,
                limitations=(member["membership_reason"],),
            )
        return ProfileInput(
            security=SecurityMaster(
                security_id=str(member["public_id"]),
                symbol=member["symbol"],
                issuer_name=member["name"],
                exchange_mic=member["mic"],
                currency=member["currency"],
                instrument_type=member["instrument_type"],
            ),
            classification=classification,
            comparable_cohorts=cohorts,
            facts=facts,
            objective_quality_score=quality,
            objective_valuation_score=valuation_score,
            objective_rating_status=objective_status,
            horizons=horizons,
            valuation=valuation,
            ai_narrative=AiNarrative(status="NOT_EXECUTED"),
        )

    def _market_facts(
        self,
        connection,
        snapshot: SnapshotContext,
        security_id: int,
    ) -> tuple[ProfileFact, ...]:
        price_rows = connection.execute(
            """
            SELECT observation.trading_date, observation.close_price,
                   observation.volume, source.id, provider.code,
                   provider.provider_schema_version, batch.parser_version,
                   source.source_reference, source.content_hash,
                   observation.available_at, observation.ingested_at
            FROM analytics.daily_price_observation observation
            JOIN analytics.data_provider provider ON provider.id = observation.provider_id
            JOIN analytics.source_record source ON source.id = observation.source_record_id
            JOIN analytics.ingestion_batch batch ON batch.id = source.ingestion_batch_id
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
            ORDER BY observation.trading_date DESC, observation.revision_number DESC
            LIMIT 20
            """,
            (
                snapshot.snapshot_id,
                security_id,
                snapshot.market_provider,
                snapshot.adjustment_mode,
                snapshot.as_of,
                snapshot.as_of,
                snapshot.ingestion_cutoff,
            ),
        ).fetchall()
        market_cap = connection.execute(
            """
            SELECT observation.observation_date, observation.numeric_value,
                   source.id, provider.code, provider.provider_schema_version,
                   batch.parser_version, source.source_reference,
                   source.content_hash, observation.available_at,
                   observation.ingested_at
            FROM analytics.market_value_observation observation
            JOIN analytics.data_provider provider ON provider.id = observation.provider_id
            JOIN analytics.source_record source ON source.id = observation.source_record_id
            JOIN analytics.ingestion_batch batch ON batch.id = source.ingestion_batch_id
            JOIN analytics.data_snapshot_source snapshot_source
              ON snapshot_source.ingestion_batch_id = batch.id
            WHERE snapshot_source.snapshot_id = %s
              AND observation.security_id = %s
              AND observation.metric_code = 'MARKET_CAP'
              AND observation.observation_date <= %s::date
              AND observation.available_at <= %s
              AND observation.ingested_at <= %s
            ORDER BY observation.observation_date DESC,
                     observation.revision_number DESC
            LIMIT 1
            """,
            (
                snapshot.snapshot_id,
                security_id,
                snapshot.as_of,
                snapshot.as_of,
                snapshot.ingestion_cutoff,
            ),
        ).fetchone()
        latest = price_rows[0] if price_rows else None
        latest_fact = self._materialize_metric(
            connection,
            security_id=security_id,
            name="latest_price",
            observation_date=latest[0] if latest else snapshot.as_of.date(),
            value=latest[1] if latest else None,
            unit="PRICE",
            currency=None,
            reason=None if latest else "PRICE_OBSERVATION_MISSING",
            source_id=latest[3] if latest else None,
            lineage=(_price_lineage(latest),) if latest else (),
        )
        adv_ready = len(price_rows) == 20 and all(row[1] is not None for row in price_rows)
        adv_value = (
            sum((Decimal(row[1]) * Decimal(row[2]) for row in price_rows), Decimal())
            / Decimal(20)
            if adv_ready
            else None
        )
        adv_lineage = (
            _unique_lineage(tuple(_price_lineage(row) for row in price_rows))
            if adv_ready
            else ()
        )
        adv_fact = self._materialize_metric(
            connection,
            security_id=security_id,
            name="average_daily_dollar_volume",
            observation_date=latest[0] if latest else snapshot.as_of.date(),
            value=adv_value,
            unit="USD",
            currency="USD",
            reason=None if adv_ready else "INSUFFICIENT_COMPLETED_PRICE_SESSIONS",
            source_id=latest[3] if adv_ready else None,
            lineage=adv_lineage,
        )
        cap_fact = self._materialize_metric(
            connection,
            security_id=security_id,
            name="market_cap",
            observation_date=market_cap[0] if market_cap else snapshot.as_of.date(),
            value=market_cap[1] if market_cap else None,
            unit="USD",
            currency="USD",
            reason=None if market_cap else "MARKET_CAP_OBSERVATION_MISSING",
            source_id=market_cap[2] if market_cap else None,
            lineage=(_market_cap_lineage(market_cap),) if market_cap else (),
        )
        return (cap_fact, latest_fact, adv_fact)

    @staticmethod
    def _materialize_metric(
        connection,
        *,
        security_id: int,
        name: str,
        observation_date: date,
        value: Decimal | None,
        unit: str,
        currency: str | None,
        reason: str | None,
        source_id,
        lineage: tuple[EvidenceLineage, ...],
    ) -> ProfileFact:
        definition_hash = canonical_hash(
            {"code": name, "version": METRIC_VERSION, "unit": unit}
        )
        connection.execute(
            """
            INSERT INTO analytics.metric_definition (
                metric_code, metric_version, value_type, unit_policy,
                description, definition_hash
            ) VALUES (%s, %s, 'NUMERIC', %s, %s, %s)
            ON CONFLICT (metric_code, metric_version) DO NOTHING
            """,
            (
                name,
                METRIC_VERSION,
                unit,
                f"Market Intelligence v1 observed or derived {name}.",
                definition_hash,
            ),
        )
        effective_at = datetime.combine(observation_date, datetime.min.time(), UTC)
        available_at = (
            max(item.available_at for item in lineage)
            if lineage
            else effective_at
        )
        ingested_at = (
            max(item.retrieved_at for item in lineage)
            if lineage
            else available_at
        )
        state = FactState.VALID if value is not None else FactState.MISSING
        existing = connection.execute(
            """
            SELECT id
            FROM analytics.metric_observation
            WHERE security_id = %s
              AND metric_code = %s
              AND metric_version = %s
              AND observation_date = %s
              AND status = %s
              AND numeric_value IS NOT DISTINCT FROM %s
              AND unit IS NOT DISTINCT FROM %s
              AND currency IS NOT DISTINCT FROM %s
              AND reason_code IS NOT DISTINCT FROM %s
              AND source_record_id IS NOT DISTINCT FROM %s
            LIMIT 1
            """,
            (
                security_id,
                name,
                METRIC_VERSION,
                observation_date,
                state,
                value,
                unit,
                currency,
                reason,
                source_id,
            ),
        ).fetchone()
        if existing is None:
            revision_number = connection.execute(
                """
                SELECT COALESCE(MAX(revision_number), 0) + 1
                FROM analytics.metric_observation
                WHERE security_id = %s
                  AND metric_code = %s
                  AND metric_version = %s
                  AND observation_date = %s
                  AND period_start IS NULL
                  AND period_end IS NULL
                """,
                (
                    security_id,
                    name,
                    METRIC_VERSION,
                    observation_date,
                ),
            ).fetchone()[0]
            connection.execute(
                """
                INSERT INTO analytics.metric_observation (
                    security_id, metric_code, metric_version, observation_date,
                    status, numeric_value, unit, currency, reason_code,
                    source_record_id, effective_at, available_at, ingested_at,
                    revision_number
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                """,
                (
                    security_id,
                    name,
                    METRIC_VERSION,
                    observation_date,
                    state,
                    value,
                    unit,
                    currency,
                    reason,
                    source_id,
                    effective_at,
                    available_at,
                    ingested_at,
                    revision_number,
                ),
            )
        return ProfileFact(
            name=name,
            metric_version=METRIC_VERSION,
            state=state,
            value=value,
            reason=reason,
            lineage=lineage,
        )

    @staticmethod
    def _classification(
        connection,
        snapshot: SnapshotContext,
        security_id: int,
        company_type: str,
    ) -> Classification | None:
        row = connection.execute(
            """
            SELECT profile.taxonomy_code, profile.taxonomy_version,
                   profile.sector_code, sector.name, profile.industry_code,
                   industry.name, profile.effective_from, provider.code,
                   provider.provider_schema_version, batch.parser_version,
                   source.source_reference, source.content_hash,
                   profile.available_at, profile.ingested_at
            FROM analytics.company_profile_observation profile
            JOIN analytics.source_record source ON source.id = profile.source_record_id
            JOIN analytics.data_provider provider ON provider.id = source.provider_id
            JOIN analytics.ingestion_batch batch ON batch.id = source.ingestion_batch_id
            JOIN analytics.data_snapshot_source snapshot_source
              ON snapshot_source.ingestion_batch_id = batch.id
            JOIN analytics.classification_node sector
              ON sector.taxonomy_code = profile.taxonomy_code
             AND sector.taxonomy_version = profile.taxonomy_version
             AND sector.node_code = profile.sector_code
            JOIN analytics.classification_node industry
              ON industry.taxonomy_code = profile.taxonomy_code
             AND industry.taxonomy_version = profile.taxonomy_version
             AND industry.node_code = profile.industry_code
            WHERE snapshot_source.snapshot_id = %s
              AND profile.security_id = %s
              AND profile.effective_from <= %s::date
              AND (profile.effective_to IS NULL OR profile.effective_to > %s::date)
              AND profile.available_at <= %s
              AND profile.ingested_at <= %s
              AND profile.quality_status <> 'REJECTED'
            ORDER BY profile.effective_from DESC, profile.revision_number DESC
            LIMIT 1
            """,
            (
                snapshot.snapshot_id,
                security_id,
                snapshot.as_of,
                snapshot.as_of,
                snapshot.as_of,
                snapshot.ingestion_cutoff,
            ),
        ).fetchone()
        if row is None or any(item is None for item in row[:6]):
            return None
        effective_at = datetime.combine(row[6], datetime.min.time(), UTC)
        lineage = EvidenceLineage(
            provider_code=row[7],
            provider_schema_version=row[8],
            parser_version=row[9],
            source_reference=row[10],
            content_hash=row[11],
            effective_at=effective_at,
            available_at=row[12],
            retrieved_at=row[13],
        )
        return Classification(
            taxonomy_code=row[0],
            taxonomy_version=row[1],
            sector_code=row[2],
            sector_name=row[3],
            industry_code=row[4],
            industry_name=row[5],
            company_type=company_type,
            effective_at=effective_at,
            lineage=(lineage,),
        )

    @staticmethod
    def _cohorts(
        connection,
        snapshot: SnapshotContext,
        member: dict,
        classification: Classification | None,
    ) -> tuple[ComparableCohort, ...]:
        if classification is None:
            return ()
        row = connection.execute(
            """
            SELECT COUNT(*)
            FROM analytics.snapshot_universe_member
            WHERE snapshot_id = %s AND universe_version = %s
              AND membership_status = 'INCLUDED'
              AND company_type_at_snapshot = %s
              AND normalized_sector_at_snapshot = %s
            """,
            (
                snapshot.snapshot_id,
                snapshot.universe_version,
                member["company_type"],
                member["sector"],
            ),
        ).fetchone()
        return (
            ComparableCohort(
                cohort_id=(
                    f"{snapshot.universe_version}:{classification.sector_code}:"
                    f"{member['company_type']}"
                ),
                taxonomy_version=classification.taxonomy_version,
                sector_code=classification.sector_code,
                industry_code=classification.industry_code,
                company_type=member["company_type"],
                eligible_member_count=row[0],
                minimum_member_count=20,
            ),
        )

    @staticmethod
    def _objective_run_id(
        connection,
        snapshot: SnapshotContext,
    ) -> UUID | None:
        row = connection.execute(
            """
            SELECT run.id
            FROM analytics.screening_run run
            WHERE run.snapshot_id = %s
              AND run.universe_version = %s
              AND run.status = 'SUCCEEDED'
            ORDER BY run.completed_at DESC, run.id
            LIMIT 1
            """,
            (snapshot.snapshot_id, snapshot.universe_version),
        ).fetchone()
        return row[0] if row else None

    @staticmethod
    def _objective(
        connection,
        run_id: UUID | None,
        security_id: int,
    ) -> tuple[Decimal | None, Decimal | None, str]:
        if run_id is None:
            return None, None, "INSUFFICIENT_DATA"
        row = connection.execute(
            """
            SELECT coverage_state, quality_score, valuation_score
            FROM analytics.coverage_result
            WHERE run_id = %s AND security_id = %s
            """,
            (run_id, security_id),
        ).fetchone()
        if row is None or row[0] != "QUANT_ELIGIBLE":
            return None, None, "INSUFFICIENT_DATA"
        return row[1], row[2], "SCORED"

    @staticmethod
    def _horizons(
        connection,
        *,
        snapshot: SnapshotContext,
        member: dict,
        benchmark: dict | None,
        objective_run_id: UUID | None,
    ) -> tuple[HorizonView, ...]:
        tactical: dict[Horizon, HorizonView] = {}
        if benchmark is not None and member["database_id"] != benchmark["database_id"]:
            bars, benchmark_bars, lineage = PostgresTacticalInputAdapter(connection).load(
                snapshot=snapshot,
                security_id=member["database_id"],
                benchmark_security_id=benchmark["database_id"],
            )
            if len(bars) >= 61:
                assessment = evaluate_tactical_signal(bars, benchmark_bars)
                evidence_hash = canonical_hash(lineage)
                for horizon, signal in zip(
                    (Horizon.ONE_WEEK, Horizon.ONE_MONTH, Horizon.THREE_MONTHS),
                    assessment.horizons,
                    strict=True,
                ):
                    state = (
                        DeterministicViewState.ASSESSED
                        if signal.opportunity_score is not None
                        else DeterministicViewState.INSUFFICIENT_DATA
                    )
                    tactical[horizon] = HorizonView(
                        horizon=horizon,
                        deterministic_view=DeterministicView(
                            model_id=TACTICAL_MODEL_ID,
                            model_version=TACTICAL_SIGNAL_VERSION,
                            state=state,
                            as_of=snapshot.as_of,
                            effective_at=snapshot.as_of,
                            expires_at=snapshot.as_of + timedelta(days=7),
                            score=(
                                Decimal(str(signal.opportunity_score))
                                if signal.opportunity_score is not None
                                else None
                            ),
                            label=signal.outlook,
                            input_hash=canonical_hash(
                                {
                                    "security": member["public_id"],
                                    "snapshot": snapshot.snapshot_id,
                                    "horizon": horizon,
                                }
                            ),
                            evidence_hash=evidence_hash,
                            missing_inputs=(
                                ()
                                if signal.opportunity_score is not None
                                else ("completed_daily_prices",)
                            ),
                            explanation=assessment.reasons,
                        ),
                    )
        for horizon in (Horizon.ONE_WEEK, Horizon.ONE_MONTH, Horizon.THREE_MONTHS):
            tactical.setdefault(
                horizon,
                _unassessed_horizon(
                    horizon,
                    snapshot.as_of,
                    "INSUFFICIENT_COMPLETED_DAILY_PRICE_HISTORY",
                ),
            )
        long_row = (
            connection.execute(
                """
                SELECT status, score, label
                FROM analytics.horizon_assessment
                WHERE run_id = %s AND security_id = %s AND horizon = 'LONG_TERM'
                """,
                (objective_run_id, member["database_id"]),
            ).fetchone()
            if objective_run_id
            else None
        )
        if long_row and long_row[0] == "SCORED" and long_row[1] is not None:
            long_view = HorizonView(
                horizon=Horizon.TWELVE_MONTHS_PLUS,
                deterministic_view=DeterministicView(
                    model_id=LONG_MODEL_ID,
                    model_version="LONG-HORIZON-RESEARCH-v1.0.0",
                    state=DeterministicViewState.ASSESSED,
                    as_of=snapshot.as_of,
                    effective_at=snapshot.as_of,
                    score=long_row[1],
                    label=long_row[2],
                    input_hash=canonical_hash(
                        {
                            "objectiveScreeningRunId": objective_run_id,
                            "security": member["public_id"],
                        }
                    ),
                    evidence_hash=canonical_hash(
                        {"dataSnapshotId": snapshot.snapshot_id}
                    ),
                ),
            )
        else:
            long_view = _unassessed_horizon(
                Horizon.TWELVE_MONTHS_PLUS,
                snapshot.as_of,
                "LONG_HORIZON_ASSESSMENT_MISSING",
            )
        return (
            tactical[Horizon.ONE_WEEK],
            tactical[Horizon.ONE_MONTH],
            tactical[Horizon.THREE_MONTHS],
            long_view,
        )

    @staticmethod
    def _valuation(
        as_of: datetime,
        objective_valuation: Decimal | None,
        horizons: tuple[HorizonView, ...],
    ) -> ValuationEvidence:
        long_score = next(
            (
                item.deterministic_view.score
                for item in horizons
                if item.horizon == Horizon.TWELVE_MONTHS_PLUS
            ),
            None,
        )
        if objective_valuation is None or long_score is None:
            return ValuationEvidence(
                state=FactState.MISSING,
                as_of=as_of,
                limitations=("VALUATION_COMPONENTS_INCOMPLETE",),
            )
        return ValuationEvidence(
            state=FactState.MISSING,
            as_of=as_of,
            limitations=("HISTORICAL_OWN_PERCENTILE_MISSING",),
        )


def _unassessed_horizon(
    horizon: Horizon,
    as_of: datetime,
    reason: str,
) -> HorizonView:
    model_id = LONG_MODEL_ID if horizon == Horizon.TWELVE_MONTHS_PLUS else TACTICAL_MODEL_ID
    model_version = (
        "LONG-HORIZON-RESEARCH-v1.0.0"
        if horizon == Horizon.TWELVE_MONTHS_PLUS
        else TACTICAL_SIGNAL_VERSION
    )
    return HorizonView(
        horizon=horizon,
        deterministic_view=DeterministicView(
            model_id=model_id,
            model_version=model_version,
            state=DeterministicViewState.INSUFFICIENT_DATA,
            as_of=as_of,
            effective_at=as_of,
            label="INSUFFICIENT_DATA",
            input_hash=_HASH_EMPTY,
            evidence_hash=_HASH_EMPTY,
            missing_inputs=(reason,),
            explanation=("Missing inputs are not converted to a neutral score.",),
        ),
    )


def _price_lineage(row) -> EvidenceLineage:
    return EvidenceLineage(
        provider_code=row[4],
        provider_schema_version=row[5],
        parser_version=row[6],
        source_reference=row[7],
        content_hash=row[8],
        effective_at=datetime.combine(row[0], datetime.min.time(), UTC),
        available_at=row[9],
        retrieved_at=row[10],
    )


def _market_cap_lineage(row) -> EvidenceLineage:
    return EvidenceLineage(
        provider_code=row[3],
        provider_schema_version=row[4],
        parser_version=row[5],
        source_reference=row[6],
        content_hash=row[7],
        effective_at=datetime.combine(row[0], datetime.min.time(), UTC),
        available_at=row[8],
        retrieved_at=row[9],
    )


def _unique_lineage(
    lineage: tuple[EvidenceLineage, ...],
) -> tuple[EvidenceLineage, ...]:
    selected: dict[tuple[str, str, str], EvidenceLineage] = {}
    for item in lineage:
        key = (
            item.provider_code,
            item.source_reference,
            item.content_hash,
        )
        current = selected.get(key)
        if current is None or (
            item.effective_at is not None
            and (
                current.effective_at is None
                or item.effective_at > current.effective_at
            )
        ):
            selected[key] = item
    return tuple(selected.values())
