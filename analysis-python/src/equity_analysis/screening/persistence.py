import base64
import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import psycopg

from equity_analysis.screening.engine import rate
from equity_analysis.screening.factors import (
    InvalidFactorInput,
    maximum_drawdown,
    realized_volatility,
    total_return,
    trend_stability,
)
from equity_analysis.screening.models import (
    AssessmentStatus,
    CohortLevel,
    CompanyType,
    CoverageState,
    CoverageSummary,
    DataLineage,
    ErrorCode,
    FactorContribution,
    FactorInput,
    FactorResult,
    FactorStatus,
    Horizon,
    HorizonAssessment,
    RatingPage,
    RatingRequest,
    RiskFlag,
    RunStatus,
    ScreeningRunAccepted,
    ScreeningRunRequest,
    ScreeningRunStatus,
    SecurityObservation,
    SecurityRating,
    SizeCohort,
    StrategyRating,
)


class ScreeningConflictError(ValueError):
    pass


class ScreeningNotReadyError(ValueError):
    pass


class ScreeningRepository:
    def __init__(self, database_url: str) -> None:
        if not database_url:
            raise ValueError("Analytics database URL is required")
        self.database_url = database_url

    @staticmethod
    def canonical_request(request: ScreeningRunRequest) -> tuple[dict, str]:
        payload = {
            "asOfTime": request.as_of_time.astimezone(UTC).isoformat().replace("+00:00", "Z"),
            "dataSnapshotId": request.data_snapshot_id,
            "universeVersion": request.universe_version,
            "strategyVersions": sorted(set(request.strategy_versions)),
            "includeNearTermMarketCondition": request.include_near_term_market_condition,
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return payload, "sha256:" + hashlib.sha256(canonical.encode()).hexdigest()

    def create_run(
        self, request: ScreeningRunRequest, idempotency_key: str
    ) -> ScreeningRunAccepted:
        if not idempotency_key.strip():
            raise ValueError("Idempotency-Key is required")
        payload, request_hash = self.canonical_request(request)
        with psycopg.connect(self.database_url) as connection:
            existing = connection.execute(
                """
                SELECT id, status, submitted_at, canonical_request_hash
                FROM analytics.screening_run WHERE idempotency_key = %s
                """,
                (idempotency_key,),
            ).fetchone()
            if existing:
                if existing[3] != request_hash:
                    raise ScreeningConflictError(
                        "Idempotency key is already associated with a different request"
                    )
                return ScreeningRunAccepted(
                    run_id=str(existing[0]),
                    status=RunStatus(existing[1]),
                    submitted_at=existing[2],
                )
            snapshot = connection.execute(
                """
                SELECT id, as_of_time FROM analytics.data_snapshot
                WHERE snapshot_key = %s AND status = 'READY'
                """,
                (request.data_snapshot_id,),
            ).fetchone()
            if snapshot is None:
                raise ValueError("A READY data snapshot is required")
            if snapshot[1] != request.as_of_time:
                raise ValueError("Run asOfTime must equal the snapshot asOfTime")
            versions = payload["strategyVersions"]
            supported = connection.execute(
                """
                SELECT strategy_version FROM analytics.strategy_definition
                WHERE strategy_version = ANY(%s)
                """,
                (versions,),
            ).fetchall()
            if {row[0] for row in supported} != set(versions):
                raise ValueError("One or more strategy versions are unsupported")
            run_id = uuid4()
            submitted = datetime.now(UTC)
            connection.execute(
                """
                INSERT INTO analytics.screening_run (
                    id, run_key, idempotency_key, canonical_request_hash,
                    status, as_of_time, snapshot_id, universe_version,
                    include_near_term_market_condition, submitted_at
                ) VALUES (%s, %s, %s, %s, 'PENDING', %s, %s, %s, %s, %s)
                """,
                (
                    run_id,
                    f"screening:{run_id}",
                    idempotency_key,
                    request_hash,
                    request.as_of_time,
                    snapshot[0],
                    request.universe_version,
                    request.include_near_term_market_condition,
                    submitted,
                ),
            )
            for version in versions:
                connection.execute(
                    """
                    INSERT INTO analytics.screening_run_strategy
                        (run_id, strategy_version) VALUES (%s, %s)
                    """,
                    (run_id, version),
                )
        return ScreeningRunAccepted(
            run_id=str(run_id), status=RunStatus.PENDING, submitted_at=submitted
        )

    def get_status(self, run_id: UUID) -> ScreeningRunStatus | None:
        with psycopg.connect(self.database_url) as connection:
            row = connection.execute(
                """
                SELECT status.run_id, status.status, status.as_of_time,
                       status.data_snapshot_id, status.universe_version,
                       status.submitted_at, status.started_at, status.completed_at,
                       status.error_code, status.error_message,
                       status.universe_count, status.scored_count,
                       status.ineligible_count, status.insufficient_data_count,
                       status.specialized_model_count,
                       ARRAY(SELECT strategy_version
                             FROM analytics.screening_run_strategy
                             WHERE run_id = status.run_id
                             ORDER BY strategy_version)
                FROM analytics.screening_run_status_v1 status
                WHERE status.run_id = %s
                """,
                (run_id,),
            ).fetchone()
        if row is None:
            return None
        coverage = CoverageSummary(
            universe_count=row[10],
            scored_count=row[11],
            ineligible_count=row[12],
            insufficient_data_count=row[13],
            specialized_model_count=row[14],
        )
        return ScreeningRunStatus(
            run_id=str(row[0]),
            status=RunStatus(row[1]),
            as_of_time=row[2],
            data_snapshot_id=row[3],
            universe_version=row[4],
            strategy_versions=tuple(row[15]),
            submitted_at=row[5],
            started_at=row[6],
            completed_at=row[7],
            coverage=coverage,
            error_code=ErrorCode(row[8]) if row[8] else None,
            error_message=row[9],
        )

    def build_observations(self, run_id: UUID) -> RatingRequest:
        with psycopg.connect(self.database_url) as connection:
            run = connection.execute(
                """
                SELECT run.as_of_time, snapshot.snapshot_key, run.universe_version,
                       ARRAY(SELECT strategy_version
                             FROM analytics.screening_run_strategy
                             WHERE run_id = run.id ORDER BY strategy_version)
                FROM analytics.screening_run run
                JOIN analytics.data_snapshot snapshot ON snapshot.id = run.snapshot_id
                WHERE run.id = %s
                """,
                (run_id,),
            ).fetchone()
            if run is None:
                raise ValueError("Unknown screening run")
            rows = connection.execute(
                """
                SELECT security.public_id, member.symbol_at_snapshot,
                       COALESCE(member.normalized_sector_at_snapshot, 'UNCLASSIFIED'),
                       member.company_type_at_snapshot,
                       (
                         SELECT numeric_value FROM analytics.market_value_observation value
                         JOIN analytics.data_snapshot_source snapshot_source
                           ON snapshot_source.snapshot_id = member.snapshot_id
                         JOIN analytics.source_record source
                           ON source.id = value.source_record_id
                          AND source.ingestion_batch_id = snapshot_source.ingestion_batch_id
                         JOIN analytics.data_snapshot snapshot
                           ON snapshot.id = member.snapshot_id
                         WHERE value.security_id = security.id
                           AND value.metric_code = 'MARKET_CAP'
                           AND value.observation_date <= snapshot.as_of_time::date
                           AND value.available_at <= snapshot.as_of_time
                           AND value.ingested_at <= snapshot.ingestion_cutoff
                         ORDER BY value.observation_date DESC, value.available_at DESC,
                                  value.revision_number DESC LIMIT 1
                       ) AS market_cap
                FROM analytics.snapshot_universe_member member
                JOIN analytics.security security ON security.id = member.security_id
                JOIN analytics.screening_run run ON run.snapshot_id = member.snapshot_id
                    AND run.universe_version = member.universe_version
                WHERE run.id = %s ORDER BY security.public_id
                """,
                (run_id,),
            ).fetchall()
            observations = []
            for public_id, symbol, sector, company_type, market_cap in rows:
                fact_rows = connection.execute(
                    """
                    SELECT fact.metric_code, fact.numeric_value, fact.unit,
                           fact.period_end, fact.filed_at, fact.available_at,
                           fact.ingested_at, fact.revision_status,
                           fact.quality_status, source.source_reference,
                           source.content_hash, provider.code
                    FROM analytics.fundamental_fact fact
                    JOIN analytics.source_record source ON source.id = fact.source_record_id
                    JOIN analytics.data_provider provider ON provider.id = source.provider_id
                    JOIN analytics.data_snapshot_source snapshot_source
                      ON snapshot_source.ingestion_batch_id = source.ingestion_batch_id
                    JOIN analytics.screening_run run
                      ON run.snapshot_id = snapshot_source.snapshot_id
                    JOIN analytics.security security ON security.id = fact.security_id
                    JOIN analytics.data_snapshot snapshot ON snapshot.id = run.snapshot_id
                    WHERE run.id = %s AND security.public_id = %s
                      AND fact.available_at <= snapshot.as_of_time
                      AND fact.ingested_at <= snapshot.ingestion_cutoff
                      AND fact.metric_code IN (
                        SELECT factor_code FROM analytics.factor_definition
                        WHERE version = 'v1.0.0'
                      )
                    ORDER BY fact.metric_code, fact.period_end DESC,
                             fact.available_at DESC
                    """,
                    (run_id, public_id),
                ).fetchall()
                by_factor = {}
                for fact in fact_rows:
                    by_factor.setdefault(fact[0], fact)
                price_factors = self._price_factor_inputs(connection, run_id, public_id)
                factors = tuple(
                    price_factors[name]
                    if name in price_factors
                    else FactorInput(
                        name=name,
                        value=(
                            by_factor[name][1]
                            if market_cap is not None and name in by_factor
                            else None
                        ),
                        status=(
                            FactorStatus.VALID
                            if market_cap is not None and name in by_factor
                            else FactorStatus.MISSING
                        ),
                        reason=(
                            "Point-in-time market capitalization is unavailable"
                            if market_cap is None
                            else None
                            if name in by_factor
                            else "Snapshot input is unavailable"
                        ),
                        lineage=(
                            (
                                DataLineage(
                                    provider=by_factor[name][11],
                                    source_reference=by_factor[name][9],
                                    period_end=by_factor[name][3],
                                    filed_at=by_factor[name][4],
                                    available_at=by_factor[name][5],
                                    ingested_at=by_factor[name][6],
                                    unit=by_factor[name][2],
                                    currency=(
                                        by_factor[name][2] if len(by_factor[name][2]) == 3 else None
                                    ),
                                    revision_status=by_factor[name][7],
                                    quality_status=by_factor[name][8],
                                    content_hash=by_factor[name][10],
                                ),
                            )
                            if market_cap is not None and name in by_factor
                            else ()
                        ),
                    )
                    for name in self._factor_codes(connection)
                )
                observations.append(
                    SecurityObservation(
                        security_id=str(public_id),
                        symbol=symbol,
                        as_of_time=run[0],
                        sector=sector,
                        # The public v1 wire model requires a cohort enum. All factors
                        # are forced missing above, so this placeholder is never ranked.
                        size_cohort=(
                            self._size_cohort(Decimal(market_cap))
                            if market_cap is not None
                            else SizeCohort.SMALL
                        ),
                        company_type=CompanyType(company_type),
                        factors=factors,
                    )
                )
        if not observations:
            raise ValueError("Snapshot universe is empty")
        return RatingRequest(
            as_of_time=run[0],
            data_snapshot_id=run[1],
            universe_version=run[2],
            strategy_versions=tuple(run[3]),
            observations=tuple(observations),
        )

    def _price_factor_inputs(
        self, connection, run_id: UUID, public_id: UUID
    ) -> dict[str, FactorInput]:
        def history(target_public_id: UUID | None, symbol: str | None = None):
            return connection.execute(
                """
                SELECT COALESCE(price.adjusted_close, price.close_price),
                       provider.code, source.source_reference,
                       source.available_at, source.ingested_at,
                       source.revision_status, source.quality_status,
                       source.content_hash, price.trading_date
                FROM analytics.daily_price_observation price
                JOIN analytics.security security ON security.id = price.security_id
                JOIN analytics.source_record source ON source.id = price.source_record_id
                JOIN analytics.data_provider provider ON provider.id = price.provider_id
                JOIN analytics.data_snapshot_source snapshot_source
                  ON snapshot_source.ingestion_batch_id = source.ingestion_batch_id
                JOIN analytics.screening_run run
                  ON run.snapshot_id = snapshot_source.snapshot_id
                JOIN analytics.data_snapshot snapshot ON snapshot.id = run.snapshot_id
                WHERE run.id = %s
                  AND (%s::uuid IS NULL OR security.public_id = %s)
                  AND (%s::text IS NULL OR security.symbol = %s)
                  AND price.trading_date <= snapshot.as_of_time::date
                  AND price.available_at <= snapshot.as_of_time
                  AND price.ingested_at <= snapshot.ingestion_cutoff
                  AND provider.code = snapshot.market_data_provider
                  AND (
                    CASE LOWER(price.adjustment_mode)
                      WHEN 'none' THEN 'UNADJUSTED'
                      WHEN 'splits' THEN 'SPLIT_ADJUSTED'
                      WHEN 'all' THEN 'TOTAL_RETURN_ADJUSTED'
                      ELSE UPPER(price.adjustment_mode)
                    END
                  ) = snapshot.market_adjustment_mode
                ORDER BY price.trading_date, price.available_at,
                         price.ingested_at, price.revision_number
                """,
                (run_id, target_public_id, target_public_id, symbol, symbol),
            ).fetchall()

        rows = history(public_id)
        if not rows:
            return {}
        # Keep the last PIT-eligible revision for each trading date.
        by_date = {row[8]: row for row in rows}
        ordered = [by_date[key] for key in sorted(by_date)]
        prices = tuple(Decimal(row[0]) for row in ordered)
        source = ordered[-1]
        lineage = (
            DataLineage(
                provider=source[1],
                source_reference=source[2],
                available_at=source[3],
                ingested_at=source[4],
                revision_status=source[5],
                quality_status=source[6],
                content_hash=source[7],
                period_end=source[8],
                unit="USD",
                currency="USD",
            ),
        )
        calculations = {
            "return_20d": lambda: total_return(prices, 20),
            "return_60d": lambda: total_return(prices, 60),
            "return_120d": lambda: total_return(prices, 120),
            "volatility_60d": lambda: realized_volatility(prices, 60),
            "max_drawdown_120d": lambda: maximum_drawdown(prices, 120),
            "trend_stability": lambda: trend_stability(prices, 120),
        }
        inputs: dict[str, FactorInput] = {}
        for name, calculation in calculations.items():
            try:
                inputs[name] = FactorInput(
                    name=name,
                    value=calculation(),
                    status=FactorStatus.VALID,
                    lineage=lineage,
                )
            except InvalidFactorInput as error:
                inputs[name] = FactorInput(
                    name=name,
                    value=None,
                    status=FactorStatus.MISSING,
                    reason=str(error),
                    lineage=lineage,
                )
        benchmark_rows = history(None, "SPY")
        if benchmark_rows:
            benchmark_by_date = {row[8]: row for row in benchmark_rows}
            benchmark_prices = tuple(
                Decimal(benchmark_by_date[key][0]) for key in sorted(benchmark_by_date)
            )
            try:
                relative = total_return(prices, 60) - total_return(benchmark_prices, 60)
                inputs["relative_strength_60d"] = FactorInput(
                    name="relative_strength_60d",
                    value=relative,
                    status=FactorStatus.VALID,
                    lineage=lineage,
                )
            except InvalidFactorInput as error:
                inputs["relative_strength_60d"] = FactorInput(
                    name="relative_strength_60d",
                    value=None,
                    status=FactorStatus.MISSING,
                    reason=str(error),
                    lineage=lineage,
                )
        return inputs

    @staticmethod
    def _factor_codes(connection) -> tuple[str, ...]:
        return tuple(
            row[0]
            for row in connection.execute(
                """
                SELECT factor_code FROM analytics.factor_definition
                WHERE version = 'v1.0.0' ORDER BY factor_code
                """
            ).fetchall()
        )

    @staticmethod
    def _size_cohort(market_cap: Decimal) -> SizeCohort:
        if market_cap >= Decimal("200000000000"):
            return SizeCohort.MEGA
        if market_cap >= Decimal("10000000000"):
            return SizeCohort.LARGE
        if market_cap >= Decimal("2000000000"):
            return SizeCohort.MID
        return SizeCohort.SMALL

    def execute(self, run_id: UUID) -> None:
        lock_key = run_id.int & 0x7FFF_FFFF_FFFF_FFFF
        with psycopg.connect(self.database_url) as connection:
            locked = connection.execute("SELECT pg_try_advisory_lock(%s)", (lock_key,)).fetchone()
            if not locked or not locked[0]:
                return
            try:
                status = connection.execute(
                    "SELECT status FROM analytics.screening_run WHERE id = %s",
                    (run_id,),
                ).fetchone()
                if status is None or status[0] in ("SUCCEEDED", "FAILED"):
                    return
                connection.execute(
                    """
                    UPDATE analytics.screening_run
                    SET status = 'RUNNING', started_at = COALESCE(started_at, CURRENT_TIMESTAMP)
                    WHERE id = %s
                    """,
                    (run_id,),
                )
                connection.commit()
                ratings = rate(self.build_observations(run_id))
                self._persist_results(connection, run_id, ratings)
            except Exception as error:
                connection.rollback()
                connection.execute(
                    """
                    UPDATE analytics.screening_run
                    SET status = 'FAILED', completed_at = CURRENT_TIMESTAMP,
                        error_code = 'ANALYSIS_FAILED', error_message = %s
                    WHERE id = %s AND status NOT IN ('SUCCEEDED', 'FAILED')
                    """,
                    (str(error)[:2000], run_id),
                )
                connection.commit()
            finally:
                connection.execute("SELECT pg_advisory_unlock(%s)", (lock_key,))

    def _persist_results(
        self, connection, run_id: UUID, ratings: tuple[SecurityRating, ...]
    ) -> None:
        canonical = json.dumps(
            [json.loads(item.model_dump_json(by_alias=True)) for item in ratings],
            sort_keys=True,
            separators=(",", ":"),
        )
        result_hash = "sha256:" + hashlib.sha256(canonical.encode()).hexdigest()
        for rating in ratings:
            security_id = connection.execute(
                "SELECT id FROM analytics.security WHERE public_id = %s",
                (rating.security_id,),
            ).fetchone()[0]
            error_code = (
                None
                if rating.coverage_state == CoverageState.QUANT_ELIGIBLE
                else (
                    "UNSUPPORTED_COMPANY_TYPE"
                    if rating.coverage_state == CoverageState.SPECIALIZED_MODEL_REQUIRED
                    else "INSUFFICIENT_DATA"
                )
            )
            connection.execute(
                """
                INSERT INTO analytics.coverage_result (
                    run_id, security_id, coverage_state, company_type, size_cohort,
                    quality_score, valuation_score, error_code
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    run_id,
                    security_id,
                    rating.coverage_state.value,
                    rating.company_type.value,
                    rating.size_cohort.value,
                    rating.quality_score,
                    rating.valuation_score,
                    error_code,
                ),
            )
            for order, reason in enumerate(rating.missing_reasons):
                connection.execute(
                    """
                    INSERT INTO analytics.coverage_reason (
                        run_id, security_id, reason_type, reason_code, detail,
                        display_order
                    ) VALUES (%s, %s, 'MISSING_DATA', %s, %s, %s)
                    ON CONFLICT DO NOTHING
                    """,
                    (run_id, security_id, "INSUFFICIENT_DATA", reason, order),
                )
            for order, risk_flag in enumerate(rating.risk_flags):
                connection.execute(
                    """
                    INSERT INTO analytics.coverage_reason (
                        run_id, security_id, reason_type, reason_code,
                        display_order
                    ) VALUES (%s, %s, 'RISK_FLAG', %s, %s)
                    ON CONFLICT DO NOTHING
                    """,
                    (run_id, security_id, risk_flag.value, order),
                )
            factor_ids = {}
            for factor in rating.factor_results:
                row = connection.execute(
                    """
                    INSERT INTO analytics.factor_result (
                        run_id, security_id, factor_code, factor_version, status,
                        raw_value, winsorized_value, normalized_score,
                        cohort_level, cohort_size, reason
                    ) VALUES (%s, %s, %s, 'v1.0.0', %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (
                        run_id,
                        security_id,
                        factor.name,
                        factor.status.value,
                        (factor.raw_value if factor.status == FactorStatus.VALID else None),
                        (factor.winsorized_value if factor.status == FactorStatus.VALID else None),
                        (factor.normalized_score if factor.status == FactorStatus.VALID else None),
                        (
                            factor.cohort_level.value
                            if factor.status == FactorStatus.VALID and factor.cohort_level
                            else None
                        ),
                        (factor.cohort_size if factor.status == FactorStatus.VALID else None),
                        factor.reason,
                    ),
                ).fetchone()
                factor_ids[factor.name] = row[0]
            for lineage in rating.lineage:
                source = connection.execute(
                    """
                    SELECT id FROM analytics.source_record
                    WHERE source_reference = %s AND content_hash = %s LIMIT 1
                    """,
                    (lineage.source_reference, lineage.content_hash),
                ).fetchone()
                if source:
                    for factor_id in factor_ids.values():
                        connection.execute(
                            """
                            INSERT INTO analytics.factor_result_lineage
                                (factor_result_id, source_record_id)
                            VALUES (%s, %s) ON CONFLICT DO NOTHING
                            """,
                            (factor_id, source[0]),
                        )
            for horizon in rating.horizon_assessments:
                connection.execute(
                    """
                    INSERT INTO analytics.horizon_assessment (
                        run_id, security_id, horizon, status, score, label
                    ) VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (
                        run_id,
                        security_id,
                        horizon.horizon.value,
                        horizon.status.value,
                        horizon.score,
                        horizon.label,
                    ),
                )
                for strategy in horizon.strategy_ratings:
                    row = connection.execute(
                        """
                        INSERT INTO analytics.strategy_rating (
                            run_id, security_id, strategy_version, status,
                            score, rank, error_code
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                        RETURNING id
                        """,
                        (
                            run_id,
                            security_id,
                            strategy.strategy_version,
                            strategy.status.value,
                            strategy.score,
                            strategy.rank,
                            strategy.error_code.value if strategy.error_code else None,
                        ),
                    ).fetchone()
                    for contribution in strategy.contributions:
                        connection.execute(
                            """
                            INSERT INTO analytics.factor_contribution (
                                strategy_rating_id, factor_code, normalized_score,
                                weight, contribution
                            ) VALUES (%s, %s, %s, %s, %s)
                            """,
                            (
                                row[0],
                                contribution.factor_name,
                                contribution.normalized_score,
                                contribution.weight,
                                contribution.contribution,
                            ),
                        )
        connection.execute(
            """
            UPDATE analytics.screening_run
            SET status = 'SUCCEEDED', completed_at = CURRENT_TIMESTAMP,
                result_hash = %s WHERE id = %s
            """,
            (result_hash, run_id),
        )
        connection.commit()

    def claim_pending(self) -> tuple[UUID, ...]:
        with psycopg.connect(self.database_url) as connection:
            return tuple(
                row[0]
                for row in connection.execute(
                    """
                    SELECT id FROM analytics.screening_run
                    WHERE status = 'PENDING'
                       OR (status = 'RUNNING'
                           AND started_at < CURRENT_TIMESTAMP - INTERVAL '15 minutes')
                    ORDER BY submitted_at LIMIT 10
                    """
                ).fetchall()
            )

    def ratings(self, run_id: UUID, cursor: str | None, limit: int) -> RatingPage:
        status = self.get_status(run_id)
        if status is None:
            raise KeyError("Unknown screening run")
        if status.status != RunStatus.SUCCEEDED:
            raise ScreeningNotReadyError("Screening results are not ready")
        after = UUID(base64.urlsafe_b64decode(cursor.encode()).decode()) if cursor else UUID(int=0)
        with psycopg.connect(self.database_url) as connection:
            rows = connection.execute(
                """
                SELECT security.public_id, security.symbol, run.as_of_time,
                       coverage.coverage_state, coverage.company_type,
                       coverage.size_cohort, coverage.quality_score,
                       coverage.valuation_score
                FROM analytics.coverage_result coverage
                JOIN analytics.security security ON security.id = coverage.security_id
                JOIN analytics.screening_run run ON run.id = coverage.run_id
                WHERE coverage.run_id = %s AND security.public_id > %s
                ORDER BY security.public_id LIMIT %s
                """,
                (run_id, after, limit + 1),
            ).fetchall()
            ids = [row[0] for row in rows]
            items = tuple(
                self._rating_from_results(connection, run_id, row) for row in rows[:limit]
            )
        next_cursor = (
            base64.urlsafe_b64encode(str(ids[limit - 1]).encode()).decode()
            if len(ids) > limit
            else None
        )
        return RatingPage(run_id=str(run_id), items=items, next_cursor=next_cursor)

    def _rating_from_results(self, connection, run_id: UUID, coverage_row) -> SecurityRating:
        public_id = coverage_row[0]
        security_id = connection.execute(
            "SELECT id FROM analytics.security WHERE public_id = %s",
            (public_id,),
        ).fetchone()[0]
        factor_rows = connection.execute(
            """
            SELECT factor_code, status, raw_value, winsorized_value,
                   normalized_score, cohort_level, cohort_size, reason
            FROM analytics.factor_result
            WHERE run_id = %s AND security_id = %s
            ORDER BY factor_code
            """,
            (run_id, security_id),
        ).fetchall()
        factors = tuple(
            FactorResult(
                name=row[0],
                status=FactorStatus(row[1]),
                raw_value=row[2],
                winsorized_value=row[3],
                normalized_score=row[4],
                cohort_level=CohortLevel(row[5]) if row[5] else None,
                cohort_size=row[6],
                reason=row[7],
            )
            for row in factor_rows
        )
        valid_factor_names = {
            factor.name for factor in factors if factor.status == FactorStatus.VALID
        }
        strategy_rows = connection.execute(
            """
            SELECT rating.id, rating.strategy_version, definition.horizon,
                   rating.status, rating.score, rating.rank, rating.error_code
            FROM analytics.strategy_rating rating
            JOIN analytics.strategy_definition definition
              ON definition.strategy_version = rating.strategy_version
            WHERE rating.run_id = %s AND rating.security_id = %s
            ORDER BY definition.horizon, rating.strategy_version
            """,
            (run_id, security_id),
        ).fetchall()
        strategies_by_horizon: dict[Horizon, list[StrategyRating]] = {}
        for row in strategy_rows:
            contribution_rows = connection.execute(
                """
                SELECT factor_code, normalized_score, weight, contribution
                FROM analytics.factor_contribution
                WHERE strategy_rating_id = %s ORDER BY factor_code
                """,
                (row[0],),
            ).fetchall()
            required_rows = connection.execute(
                """
                SELECT factor_code FROM analytics.strategy_factor_weight
                WHERE strategy_version = %s AND required = TRUE
                ORDER BY factor_code
                """,
                (row[1],),
            ).fetchall()
            status = AssessmentStatus(row[3])
            missing = (
                tuple(factor[0] for factor in required_rows if factor[0] not in valid_factor_names)
                if status == AssessmentStatus.INSUFFICIENT_DATA
                else ()
            )
            strategy = StrategyRating(
                strategy_version=row[1],
                status=status,
                score=row[4],
                rank=row[5],
                contributions=tuple(
                    FactorContribution(
                        factor_name=item[0],
                        normalized_score=item[1],
                        weight=item[2],
                        contribution=item[3],
                    )
                    for item in contribution_rows
                ),
                missing_factors=missing,
                error_code=ErrorCode(row[6]) if row[6] else None,
            )
            strategies_by_horizon.setdefault(Horizon(row[2]), []).append(strategy)
        horizon_rows = connection.execute(
            """
            SELECT horizon, status, score, label
            FROM analytics.horizon_assessment
            WHERE run_id = %s AND security_id = %s
            ORDER BY CASE horizon
                WHEN 'NEAR_TERM' THEN 1
                WHEN 'MEDIUM_TERM' THEN 2
                ELSE 3 END
            """,
            (run_id, security_id),
        ).fetchall()
        horizons = tuple(
            HorizonAssessment(
                horizon=Horizon(row[0]),
                status=AssessmentStatus(row[1]),
                score=row[2],
                label=row[3],
                strategy_ratings=tuple(strategies_by_horizon.get(Horizon(row[0]), [])),
            )
            for row in horizon_rows
        )
        reason_rows = connection.execute(
            """
            SELECT reason_type, reason_code, detail
            FROM analytics.coverage_reason
            WHERE run_id = %s AND security_id = %s
            ORDER BY display_order, reason_code
            """,
            (run_id, security_id),
        ).fetchall()
        missing_reasons = tuple(row[2] or row[1] for row in reason_rows if row[0] == "MISSING_DATA")
        risk_flags = tuple(RiskFlag(row[1]) for row in reason_rows if row[0] == "RISK_FLAG")
        lineage_rows = connection.execute(
            """
            SELECT DISTINCT provider.code, source.source_reference,
                   fact.period_end, source.original_at, source.available_at,
                   source.ingested_at, fact.currency, fact.unit,
                   source.revision_status, source.quality_status,
                   source.content_hash
            FROM analytics.factor_result result
            JOIN analytics.factor_result_lineage lineage
              ON lineage.factor_result_id = result.id
            JOIN analytics.source_record source
              ON source.id = lineage.source_record_id
            JOIN analytics.data_provider provider ON provider.id = source.provider_id
            LEFT JOIN LATERAL (
                SELECT period_end, currency, unit
                FROM analytics.fundamental_fact
                WHERE source_record_id = source.id
                ORDER BY period_end DESC LIMIT 1
            ) fact ON TRUE
            WHERE result.run_id = %s AND result.security_id = %s
            ORDER BY provider.code, source.source_reference, source.content_hash
            """,
            (run_id, security_id),
        ).fetchall()
        lineage = tuple(
            DataLineage(
                provider=row[0],
                source_reference=row[1],
                period_end=row[2],
                filed_at=row[3],
                available_at=row[4],
                ingested_at=row[5],
                currency=row[6],
                unit=row[7],
                revision_status=row[8],
                quality_status=row[9],
                content_hash=row[10],
            )
            for row in lineage_rows
        )
        return SecurityRating(
            security_id=str(public_id),
            symbol=coverage_row[1],
            as_of_time=coverage_row[2],
            coverage_state=CoverageState(coverage_row[3]),
            company_type=CompanyType(coverage_row[4]),
            size_cohort=SizeCohort(coverage_row[5]),
            quality_score=coverage_row[6],
            valuation_score=coverage_row[7],
            factor_results=factors,
            horizon_assessments=horizons,
            risk_flags=risk_flags,
            missing_reasons=missing_reasons,
            lineage=lineage,
        )
