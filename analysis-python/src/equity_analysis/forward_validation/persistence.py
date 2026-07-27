import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import psycopg

from equity_analysis.forward_validation.models import (
    EnrollmentAccepted,
    EnrollmentRequest,
    ExperimentMode,
    ExperimentStatus,
    ForwardExperimentAccepted,
    ForwardExperimentRequest,
    ForwardExperimentStatus,
)


class ForwardConflictError(ValueError):
    pass


class ForwardRepository:
    def __init__(self, database_url: str) -> None:
        if not database_url:
            raise ValueError("Analytics database URL is required")
        self.database_url = database_url

    @staticmethod
    def _canonical(value: dict) -> tuple[str, str]:
        canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
        return canonical, "sha256:" + hashlib.sha256(canonical.encode()).hexdigest()

    def create_experiment(
        self, request: ForwardExperimentRequest, idempotency_key: str
    ) -> ForwardExperimentAccepted:
        if not idempotency_key.strip():
            raise ValueError("Idempotency-Key is required")
        if request.mode == ExperimentMode.FORMAL and not request.provider_acceptance_id:
            raise ValueError("FORMAL mode requires a provider acceptance ID")
        payload = request.model_dump(mode="json", by_alias=True)
        _, request_hash = self._canonical(payload)
        now = datetime.now(UTC)
        with psycopg.connect(self.database_url) as connection:
            existing = connection.execute(
                """
                SELECT id, status, mode, submitted_at, canonical_request_hash
                FROM analytics.forward_experiment WHERE idempotency_key = %s
                """,
                (idempotency_key,),
            ).fetchone()
            if existing:
                if existing[4] != request_hash:
                    raise ForwardConflictError(
                        "Idempotency key is associated with a different request"
                    )
                return ForwardExperimentAccepted(
                    experiment_id=str(existing[0]),
                    status=ExperimentStatus(existing[1]),
                    mode=ExperimentMode(existing[2]),
                    submitted_at=existing[3],
                )
            run = connection.execute(
                "SELECT status FROM analytics.screening_run WHERE id = %s",
                (UUID(request.screening_run_id),),
            ).fetchone()
            if run is None or run[0] != "SUCCEEDED":
                raise ValueError("A succeeded sealed screening run is required")
            if request.mode == ExperimentMode.FORMAL:
                acceptance = connection.execute(
                    """
                    SELECT universe_size FROM analytics.forward_provider_acceptance
                    WHERE id=%s AND status='ACCEPTED'
                    """,
                    (UUID(request.provider_acceptance_id),),
                ).fetchone()
                if acceptance is None or not 300 <= acceptance[0] <= 500:
                    raise ValueError(
                        "FORMAL mode requires an accepted 300-to-500-security provider gate"
                    )
            experiment_id = uuid4()
            connection.execute(
                """
                INSERT INTO analytics.forward_experiment (
                    id, idempotency_key, canonical_request_hash, screening_run_id,
                    mode, status, experiment_version, entry_policy_version,
                    cost_model_version, cash_return_version,
                    sector_benchmark_map_version, provider_acceptance_id,
                    notional_usd, submitted_at
                ) VALUES (
                    %s, %s, %s, %s, %s, 'PENDING', %s, %s, %s, %s, %s, %s, %s, %s
                )
                """,
                (
                    experiment_id,
                    idempotency_key,
                    request_hash,
                    UUID(request.screening_run_id),
                    request.mode.value,
                    request.experiment_version,
                    request.entry_policy_version,
                    request.cost_model_version,
                    request.cash_return_version,
                    request.sector_benchmark_map_version,
                    UUID(request.provider_acceptance_id)
                    if request.provider_acceptance_id
                    else None,
                    request.notional_usd,
                    now,
                ),
            )
        return ForwardExperimentAccepted(
            experiment_id=str(experiment_id),
            status=ExperimentStatus.PENDING,
            mode=request.mode,
            submitted_at=now,
        )

    def status(self, experiment_id: UUID) -> ForwardExperimentStatus | None:
        with psycopg.connect(self.database_url) as connection:
            row = connection.execute(
                """
                SELECT id, status, mode, submitted_at, screening_run_id,
                       experiment_version, entry_policy_version,
                       provider_acceptance_id, notional_usd
                FROM analytics.forward_experiment WHERE id = %s
                """,
                (experiment_id,),
            ).fetchone()
        if row is None:
            return None
        return ForwardExperimentStatus(
            experiment_id=str(row[0]),
            status=ExperimentStatus(row[1]),
            mode=ExperimentMode(row[2]),
            submitted_at=row[3],
            screening_run_id=str(row[4]),
            experiment_version=row[5],
            entry_policy_version=row[6],
            provider_acceptance_id=row[7],
            notional_usd=row[8],
        )

    def enroll(
        self,
        experiment_id: UUID,
        request: EnrollmentRequest,
        idempotency_key: str,
    ) -> EnrollmentAccepted:
        if not idempotency_key.strip():
            raise ValueError("Idempotency-Key is required")
        payload = {
            "experimentId": str(experiment_id),
            **request.model_dump(mode="json", by_alias=True),
        }
        _, input_hash = self._canonical(payload)
        sealed_at = datetime.now(UTC)
        enrollment_id = uuid4()
        with psycopg.connect(self.database_url) as connection:
            experiment = connection.execute(
                """
                SELECT notional_usd FROM analytics.forward_experiment
                WHERE id = %s AND status IN ('PENDING', 'ACTIVE')
                """,
                (experiment_id,),
            ).fetchone()
            if experiment is None:
                raise ValueError("Experiment is not open for enrollment")
            run = connection.execute(
                "SELECT status FROM analytics.screening_run WHERE id = %s",
                (UUID(request.screening_run_id),),
            ).fetchone()
            if run is None or run[0] != "SUCCEEDED":
                raise ValueError("Enrollment requires a succeeded screening run")
            existing = connection.execute(
                """
                SELECT id, sealed_at, input_hash, canonical_request_hash
                FROM analytics.forward_enrollment
                WHERE experiment_id = %s AND idempotency_key = %s
                """,
                (experiment_id, idempotency_key),
            ).fetchone()
            if existing:
                if existing[3] != input_hash:
                    raise ForwardConflictError(
                        "Idempotency key is associated with a different enrollment"
                    )
                count = connection.execute(
                    """
                    SELECT COUNT(*) FROM analytics.forward_candidate_signal
                    WHERE enrollment_id=%s
                    """,
                    (existing[0],),
                ).fetchone()[0]
                return EnrollmentAccepted(
                    enrollment_id=str(existing[0]),
                    signal_count=count,
                    sealed_at=existing[1],
                    input_hash=existing[2],
                )
            connection.execute(
                """
                INSERT INTO analytics.forward_enrollment (
                    id, experiment_id, idempotency_key, canonical_request_hash,
                    screening_run_id, enrollment_time, input_hash, sealed_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    enrollment_id,
                    experiment_id,
                    idempotency_key,
                    input_hash,
                    UUID(request.screening_run_id),
                    request.enrollment_time,
                    input_hash,
                    sealed_at,
                ),
            )
            rows = connection.execute(
                """
                WITH scored AS (
                    SELECT rating.security_id, rating.strategy_version, rating.score,
                           rating.rank,
                           COUNT(*) OVER (PARTITION BY rating.strategy_version) AS n,
                           coverage.size_cohort,
                           COALESCE(member.normalized_sector_at_snapshot, 'UNCLASSIFIED') AS sector,
                           horizon.label AS near_term_label
                    FROM analytics.strategy_rating rating
                    JOIN analytics.coverage_result coverage
                      ON coverage.run_id=rating.run_id
                     AND coverage.security_id=rating.security_id
                    JOIN analytics.screening_run run ON run.id=rating.run_id
                    JOIN analytics.snapshot_universe_member member
                      ON member.snapshot_id=run.snapshot_id
                     AND member.security_id=rating.security_id
                     AND member.universe_version=run.universe_version
                    LEFT JOIN analytics.horizon_assessment horizon
                      ON horizon.run_id=rating.run_id
                     AND horizon.security_id=rating.security_id
                     AND horizon.horizon='NEAR_TERM'
                    WHERE rating.run_id=%s
                      AND rating.status='SCORED'
                      AND rating.rank IS NOT NULL
                      AND rating.strategy_version IN ('QC-v1.0.0', 'UQ-v1.0.0')
                )
                SELECT security_id, strategy_version, score, rank, n,
                       size_cohort, sector, near_term_label,
                       CASE WHEN rank <= CEIL(n * 0.2) THEN 'TOP' ELSE 'BOTTOM' END
                FROM scored
                WHERE rank <= CEIL(n * 0.2) OR rank > FLOOR(n * 0.8)
                """,
                (UUID(request.screening_run_id),),
            ).fetchall()
            inserted = 0
            for row in rows:
                bucket = row[8]
                active = connection.execute(
                    """
                    SELECT 1
                    FROM analytics.forward_candidate_signal signal
                    JOIN analytics.forward_enrollment enrollment
                      ON enrollment.id=signal.enrollment_id
                    WHERE enrollment.experiment_id=%s
                      AND signal.security_id=%s
                      AND signal.strategy_version=%s
                      AND signal.score_bucket=%s
                      AND (
                        SELECT COUNT(DISTINCT price.trading_date)
                        FROM analytics.daily_price_observation price
                        WHERE price.security_id=signal.security_id
                          AND price.trading_date > signal.signal_time::date
                          AND price.trading_date <= %s::date
                      ) < 60
                    LIMIT 1
                    """,
                    (
                        experiment_id,
                        row[0],
                        row[1],
                        bucket,
                        request.enrollment_time,
                    ),
                ).fetchone()
                if active:
                    continue
                percentile = (
                    Decimal("100")
                    if row[4] <= 1
                    else (Decimal(row[4] - row[3]) / Decimal(row[4] - 1) * 100)
                )
                signal_payload = {
                    "enrollmentId": str(enrollment_id),
                    "securityId": row[0],
                    "strategyVersion": row[1],
                    "bucket": bucket,
                    "signalTime": request.enrollment_time.isoformat(),
                }
                _, signal_hash = self._canonical(signal_payload)
                connection.execute(
                    """
                    INSERT INTO analytics.forward_candidate_signal (
                        enrollment_id, security_id, strategy_version, score_bucket,
                        score, percentile, near_term_label, sector, size_cohort,
                        notional_usd, signal_time, input_hash
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        enrollment_id,
                        row[0],
                        row[1],
                        bucket,
                        row[2],
                        percentile,
                        row[7] or "MISSING",
                        row[6],
                        row[5],
                        experiment[0],
                        request.enrollment_time,
                        signal_hash,
                    ),
                )
                inserted += 1
            connection.execute(
                """
                UPDATE analytics.forward_experiment
                SET status='ACTIVE', started_at=COALESCE(started_at, %s)
                WHERE id=%s AND status='PENDING'
                """,
                (sealed_at, experiment_id),
            )
        return EnrollmentAccepted(
            enrollment_id=str(enrollment_id),
            signal_count=inserted,
            sealed_at=sealed_at,
            input_hash=input_hash,
        )

    def rows(self, experiment_id: UUID, table: str) -> list[dict]:
        allowed = {
            "signals": """
                SELECT signal.* FROM analytics.forward_candidate_signal signal
                JOIN analytics.forward_enrollment enrollment
                  ON enrollment.id=signal.enrollment_id
                WHERE enrollment.experiment_id=%s ORDER BY signal.signal_time, signal.id
            """,
            "observations": """
                SELECT result.* FROM analytics.forward_observation_result result
                JOIN analytics.forward_candidate_signal signal ON signal.id=result.signal_id
                JOIN analytics.forward_enrollment enrollment ON enrollment.id=signal.enrollment_id
                WHERE enrollment.experiment_id=%s
                ORDER BY result.as_of_time, result.id
            """,
        }
        if table not in allowed:
            raise ValueError("Unsupported result projection")
        with psycopg.connect(self.database_url, row_factory=psycopg.rows.dict_row) as connection:
            return list(connection.execute(allowed[table], (experiment_id,)).fetchall())

    def report(self, experiment_id: UUID, report_type: str) -> dict | None:
        with psycopg.connect(self.database_url, row_factory=psycopg.rows.dict_row) as connection:
            return connection.execute(
                """
                SELECT * FROM analytics.forward_report_snapshot
                WHERE experiment_id=%s AND report_type=%s
                ORDER BY as_of_time DESC LIMIT 1
                """,
                (experiment_id, report_type),
            ).fetchone()
