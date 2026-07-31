from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from equity_analysis.forward_validation.outcome_persistence_v21 import (
    ForwardDqvOutcomeRepositoryV21,
    ForwardDqvPersistenceConflict,
    ForwardDqvPersistenceNotFound,
)
from equity_analysis.forward_validation.outcomes_v211 import (
    FORWARD_DQV_ENROLLMENT_V211,
    ForwardDqvEnrollmentV211,
    verify_enrollment_v211,
)


@dataclass(frozen=True)
class DueMaturityScheduleV211:
    """Hash-verified V19 maturity row returned by the production read port."""

    enrollment: ForwardDqvEnrollmentV211
    completed_sessions: int
    matures_at_completed_session: datetime
    evaluation_role: str
    formal_gate_eligible: bool
    latest_outcome_batch_id: UUID | None
    latest_result_version: int | None
    latest_outcome_batch_content_hash: str | None


class ForwardDqvOutcomeRepositoryV211(ForwardDqvOutcomeRepositoryV21):
    """V19 repository boundary for chronology-safe prospective enrollment."""

    def persist_enrollment(self, enrollment: ForwardDqvEnrollmentV211) -> UUID:
        verify_enrollment_v211(enrollment)
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            existing = connection.execute(
                """
                SELECT id, canonical_request_hash, enrollment_content_hash
                FROM analytics.forward_dqv_enrollment_v2
                WHERE id = %s OR idempotency_key = %s
                ORDER BY CASE WHEN id = %s THEN 0 ELSE 1 END
                LIMIT 1
                """,
                (
                    enrollment.enrollment_id,
                    enrollment.idempotency_key,
                    enrollment.enrollment_id,
                ),
            ).fetchone()
            if existing is not None:
                self._require_exact(
                    existing["canonical_request_hash"],
                    enrollment.canonical_request_hash,
                    "Enrollment request hash",
                )
                self._require_exact(
                    existing["enrollment_content_hash"],
                    enrollment.enrollment_content_hash,
                    "Enrollment content hash",
                )
                persisted = self._read_enrollment_v211(connection, existing["id"])
                if persisted != enrollment:
                    raise ForwardDqvPersistenceConflict(
                        "Enrollment hash matched but the persisted payload differed"
                    )
                return existing["id"]

            connection.execute(
                """
                INSERT INTO analytics.forward_dqv_enrollment_v2 (
                    id, idempotency_key, canonical_request_hash, contract_version,
                    preregistration_content_hash, decision_manifest_content_hash,
                    decision_controlled_artifact_hash,
                    decision_controlled_artifact_reference,
                    decision_data_snapshot_id, decision_as_of,
                    effective_at_completed_session_open, universe_version,
                    frozen_population_hash, model_freeze_hashes,
                    benchmark_contract_version, benchmark_contract_hash,
                    cost_policy_version, cost_policy_hash, security_count,
                    terminal_counts, enrollment_content_hash, sealed_at
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                """,
                (
                    enrollment.enrollment_id,
                    enrollment.idempotency_key,
                    enrollment.canonical_request_hash,
                    enrollment.schema_version,
                    enrollment.preregistration_content_hash,
                    enrollment.decision_manifest_content_hash,
                    enrollment.decision_controlled_artifact_hash,
                    enrollment.decision_controlled_artifact_reference,
                    enrollment.decision_data_snapshot_id,
                    enrollment.decision_as_of,
                    enrollment.effective_at_completed_session_open,
                    enrollment.universe_version,
                    enrollment.frozen_population_hash,
                    Jsonb(enrollment.model_freeze_hashes),
                    enrollment.benchmark_contract_version,
                    enrollment.benchmark_contract_hash,
                    enrollment.cost_policy_version,
                    enrollment.cost_policy_hash,
                    enrollment.security_count,
                    Jsonb(enrollment.terminal_counts),
                    enrollment.enrollment_content_hash,
                    enrollment.sealed_at,
                ),
            )
            for schedule in enrollment.maturity_schedule:
                connection.execute(
                    """
                    INSERT INTO analytics.forward_dqv_maturity_schedule_v2 (
                        enrollment_id, completed_sessions, evaluation_role,
                        formal_gate_eligible, matures_at_completed_session,
                        schedule_content_hash
                    ) VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (
                        enrollment.enrollment_id,
                        schedule.completed_sessions,
                        schedule.evaluation_role.value,
                        schedule.formal_gate_eligible,
                        schedule.matures_at_completed_session,
                        schedule.schedule_content_hash,
                    ),
                )
        return enrollment.enrollment_id

    def read_enrollment(self, enrollment_id: UUID) -> ForwardDqvEnrollmentV211:
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            return self._read_enrollment_v211(connection, enrollment_id)

    def list_due_maturities(
        self,
        *,
        observed_at: datetime,
        include_materialized: bool = False,
    ) -> tuple[DueMaturityScheduleV211, ...]:
        """Discover due V19 schedules without trusting unverified database JSON."""

        if observed_at.tzinfo is None or observed_at.utcoffset() is None:
            raise ValueError("Observed timestamp must be timezone-aware")
        cutoff = observed_at.astimezone(UTC)
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            rows = connection.execute(
                """
                SELECT schedule.enrollment_id, schedule.completed_sessions,
                       schedule.matures_at_completed_session,
                       schedule.evaluation_role,
                       schedule.formal_gate_eligible,
                       enrollment.contract_version,
                       latest.id AS latest_outcome_batch_id,
                       latest.result_version AS latest_result_version,
                       latest.outcome_batch_content_hash
                           AS latest_outcome_batch_content_hash
                FROM analytics.forward_dqv_maturity_schedule_v2 schedule
                JOIN analytics.forward_dqv_enrollment_v2 enrollment
                  ON enrollment.id = schedule.enrollment_id
                LEFT JOIN LATERAL (
                    SELECT batch.id, batch.result_version,
                           batch.outcome_batch_content_hash
                    FROM analytics.forward_dqv_outcome_batch_v2 batch
                    WHERE batch.enrollment_id = schedule.enrollment_id
                      AND batch.completed_sessions = schedule.completed_sessions
                    ORDER BY batch.result_version DESC
                    LIMIT 1
                ) latest ON TRUE
                WHERE schedule.matures_at_completed_session <= %s
                  AND (%s OR latest.id IS NULL)
                ORDER BY schedule.matures_at_completed_session,
                         schedule.enrollment_id,
                         schedule.completed_sessions
                """,
                (cutoff, include_materialized),
            ).fetchall()
            result: list[DueMaturityScheduleV211] = []
            for row in rows:
                if row["contract_version"] != FORWARD_DQV_ENROLLMENT_V211:
                    raise ForwardDqvPersistenceConflict("LEGACY_FORWARD_DQV_ENROLLMENT_REJECTED")
                enrollment = self._read_enrollment_v211(
                    connection,
                    row["enrollment_id"],
                )
                result.append(
                    DueMaturityScheduleV211(
                        enrollment=enrollment,
                        completed_sessions=row["completed_sessions"],
                        matures_at_completed_session=row["matures_at_completed_session"],
                        evaluation_role=row["evaluation_role"],
                        formal_gate_eligible=row["formal_gate_eligible"],
                        latest_outcome_batch_id=row["latest_outcome_batch_id"],
                        latest_result_version=row["latest_result_version"],
                        latest_outcome_batch_content_hash=row["latest_outcome_batch_content_hash"],
                    )
                )
            return tuple(result)

    @staticmethod
    def _read_enrollment_v211(
        connection: psycopg.Connection[dict[str, Any]],
        enrollment_id: UUID,
    ) -> ForwardDqvEnrollmentV211:
        row = connection.execute(
            "SELECT * FROM analytics.forward_dqv_enrollment_v2 WHERE id = %s",
            (enrollment_id,),
        ).fetchone()
        if row is None:
            raise ForwardDqvPersistenceNotFound("Forward DQV enrollment was not found")
        schedules = connection.execute(
            """
            SELECT completed_sessions, evaluation_role, formal_gate_eligible,
                   matures_at_completed_session, schedule_content_hash
            FROM analytics.forward_dqv_maturity_schedule_v2
            WHERE enrollment_id = %s
            ORDER BY completed_sessions
            """,
            (enrollment_id,),
        ).fetchall()
        enrollment = ForwardDqvEnrollmentV211.model_validate(
            {
                "schemaVersion": row["contract_version"],
                "enrollmentId": row["id"],
                "idempotencyKey": row["idempotency_key"],
                "canonicalRequestHash": row["canonical_request_hash"],
                "preregistrationContentHash": row["preregistration_content_hash"],
                "decisionManifestContentHash": row["decision_manifest_content_hash"],
                "decisionControlledArtifactHash": row["decision_controlled_artifact_hash"],
                "decisionControlledArtifactReference": row[
                    "decision_controlled_artifact_reference"
                ],
                "decisionDataSnapshotId": row["decision_data_snapshot_id"],
                "decisionAsOf": row["decision_as_of"],
                "effectiveAtCompletedSessionOpen": row["effective_at_completed_session_open"],
                "universeVersion": row["universe_version"],
                "frozenPopulationHash": row["frozen_population_hash"],
                "modelFreezeHashes": row["model_freeze_hashes"],
                "benchmarkContractVersion": row["benchmark_contract_version"],
                "benchmarkContractHash": row["benchmark_contract_hash"],
                "costPolicyVersion": row["cost_policy_version"],
                "costPolicyHash": row["cost_policy_hash"],
                "securityCount": row["security_count"],
                "terminalCounts": row["terminal_counts"],
                "maturitySchedule": [
                    {
                        "completedSessions": item["completed_sessions"],
                        "evaluationRole": item["evaluation_role"],
                        "formalGateEligible": item["formal_gate_eligible"],
                        "maturesAtCompletedSession": item["matures_at_completed_session"],
                        "scheduleContentHash": item["schedule_content_hash"],
                    }
                    for item in schedules
                ],
                "sealedAt": row["sealed_at"],
                "enrollmentContentHash": row["enrollment_content_hash"],
            }
        )
        verify_enrollment_v211(enrollment)
        return enrollment
