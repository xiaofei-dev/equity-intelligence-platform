from __future__ import annotations

from typing import Any
from uuid import UUID

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from equity_analysis.forward_validation.outcomes_v21 import (
    ForwardDqvEnrollmentV21,
    ForwardOutcomeBatchV21,
    ForwardQualityReportV21,
    verify_enrollment_v21,
    verify_outcome_batch_v21,
    verify_quality_report_v21,
)


class ForwardDqvPersistenceConflict(ValueError):
    code = "FORWARD_DQV_V2_IDEMPOTENCY_CONFLICT"


class ForwardDqvPersistenceNotFound(ValueError):
    code = "FORWARD_DQV_V2_NOT_FOUND"


class ForwardDqvOutcomeRepositoryV21:
    def __init__(self, database_url: str) -> None:
        if not database_url:
            raise ValueError("Analytics database URL is required")
        self.database_url = database_url

    def persist_enrollment(self, enrollment: ForwardDqvEnrollmentV21) -> UUID:
        verify_enrollment_v21(enrollment)
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
                persisted = self._read_enrollment(connection, existing["id"])
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

    def read_enrollment(self, enrollment_id: UUID) -> ForwardDqvEnrollmentV21:
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            return self._read_enrollment(connection, enrollment_id)

    def persist_outcome_batch(self, batch: ForwardOutcomeBatchV21) -> UUID:
        verify_outcome_batch_v21(batch)
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            existing = connection.execute(
                """
                SELECT id, outcome_batch_content_hash
                FROM analytics.forward_dqv_outcome_batch_v2
                WHERE id = %s
                   OR (
                       enrollment_id = %s
                       AND completed_sessions = %s
                       AND result_version = %s
                   )
                ORDER BY CASE WHEN id = %s THEN 0 ELSE 1 END
                LIMIT 1
                """,
                (
                    batch.outcome_batch_id,
                    batch.enrollment_id,
                    batch.completed_sessions,
                    batch.result_version,
                    batch.outcome_batch_id,
                ),
            ).fetchone()
            if existing is not None:
                self._require_exact(
                    existing["outcome_batch_content_hash"],
                    batch.outcome_batch_content_hash,
                    "Outcome batch content hash",
                )
                persisted = self._read_outcome_batch(connection, existing["id"])
                if persisted != batch:
                    raise ForwardDqvPersistenceConflict(
                        "Outcome hash matched but the persisted payload differed"
                    )
                return existing["id"]

            self._validate_enrollment_binding(connection, batch)
            security_ids = self._security_ids(
                connection,
                tuple(item.public_security_id for item in batch.security_outcomes),
            )
            connection.execute(
                """
                INSERT INTO analytics.forward_dqv_outcome_batch_v2 (
                    id, enrollment_id, completed_sessions, contract_version,
                    result_version, supersedes_batch_id, observed_at,
                    matured_at_completed_session, evaluation_role,
                    operational_completeness, security_count, benchmark_count,
                    terminal_counts, preregistration_content_hash,
                    decision_manifest_content_hash, frozen_population_hash,
                    model_freeze_hashes, benchmark_contract_hash, cost_policy_hash,
                    source_manifest_hash, calendar_evidence_hash,
                    action_evidence_hash, price_evidence_hash, evidence_blockers,
                    outcome_batch_content_hash
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                """,
                (
                    batch.outcome_batch_id,
                    batch.enrollment_id,
                    batch.completed_sessions,
                    batch.schema_version,
                    batch.result_version,
                    batch.supersedes_batch_id,
                    batch.observed_at,
                    batch.matured_at_completed_session,
                    batch.evaluation_role.value,
                    batch.operational_completeness.value,
                    batch.security_count,
                    len(batch.benchmark_outcomes),
                    Jsonb(batch.terminal_counts),
                    batch.preregistration_content_hash,
                    batch.decision_manifest_content_hash,
                    batch.frozen_population_hash,
                    Jsonb(batch.model_freeze_hashes),
                    batch.benchmark_contract_hash,
                    batch.cost_policy_hash,
                    batch.source_manifest_hash,
                    batch.calendar_evidence_hash,
                    batch.action_evidence_hash,
                    batch.price_evidence_hash,
                    Jsonb(batch.evidence_blockers),
                    batch.outcome_batch_content_hash,
                ),
            )
            self._insert_security_outcomes(connection, batch, security_ids)
            self._insert_benchmark_outcomes(connection, batch)
            self._insert_path_metrics(connection, batch, security_ids)
        return batch.outcome_batch_id

    def read_outcome_batch(self, outcome_batch_id: UUID) -> ForwardOutcomeBatchV21:
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            return self._read_outcome_batch(connection, outcome_batch_id)

    def persist_quality_report(self, report: ForwardQualityReportV21) -> UUID:
        verify_quality_report_v21(report)
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            existing = connection.execute(
                """
                SELECT id, report_content_hash
                FROM analytics.forward_dqv_quality_report_v2
                WHERE id = %s
                   OR (
                       enrollment_id = %s
                       AND completed_sessions = %s
                       AND model_track = %s
                       AND result_version = %s
                   )
                ORDER BY CASE WHEN id = %s THEN 0 ELSE 1 END
                LIMIT 1
                """,
                (
                    report.report_id,
                    report.enrollment_id,
                    report.completed_sessions,
                    report.model_track.value,
                    report.result_version,
                    report.report_id,
                ),
            ).fetchone()
            if existing is not None:
                self._require_exact(
                    existing["report_content_hash"],
                    report.report_content_hash,
                    "Quality report content hash",
                )
                persisted = self._read_quality_report(connection, existing["id"])
                if persisted != report:
                    raise ForwardDqvPersistenceConflict(
                        "Quality-report hash matched but the persisted payload differed"
                    )
                return existing["id"]
            connection.execute(
                """
                INSERT INTO analytics.forward_dqv_quality_report_v2 (
                    id, enrollment_id, completed_sessions, contract_version,
                    model_track, model_version, evaluation_role, result_version,
                    supersedes_report_id, assessed_at, matured_through,
                    preregistration_content_hash, operational_completeness,
                    model_quality_status, target_results,
                    source_outcome_batch_hashes, source_decision_manifest_hashes,
                    resampling_policy_version, resampling_policy_hash,
                    report_content_hash, ordinary_iid_bootstrap_used, ai_influence
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                """,
                (
                    report.report_id,
                    report.enrollment_id,
                    report.completed_sessions,
                    report.schema_version,
                    report.model_track.value,
                    report.model_version,
                    report.evaluation_role.value,
                    report.result_version,
                    report.supersedes_report_id,
                    report.assessed_at,
                    report.matured_through,
                    report.preregistration_content_hash,
                    report.operational_completeness.value,
                    report.model_quality_status.value,
                    Jsonb(
                        [
                            item.model_dump(mode="json", by_alias=True)
                            for item in report.target_results
                        ]
                    ),
                    Jsonb(report.source_outcome_batch_hashes),
                    Jsonb(report.source_decision_manifest_hashes),
                    report.resampling_policy_version,
                    report.resampling_policy_hash,
                    report.report_content_hash,
                    report.ordinary_iid_bootstrap_used,
                    report.ai_influence,
                ),
            )
        return report.report_id

    def read_quality_report(self, report_id: UUID) -> ForwardQualityReportV21:
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            return self._read_quality_report(connection, report_id)

    def _read_enrollment(
        self,
        connection: psycopg.Connection[dict[str, Any]],
        enrollment_id: UUID,
    ) -> ForwardDqvEnrollmentV21:
        row = connection.execute(
            """
            SELECT * FROM analytics.forward_dqv_enrollment_v2 WHERE id = %s
            """,
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
        return ForwardDqvEnrollmentV21.model_validate(
            {
                "schemaVersion": row["contract_version"],
                "enrollmentId": row["id"],
                "idempotencyKey": row["idempotency_key"],
                "canonicalRequestHash": row["canonical_request_hash"],
                "preregistrationContentHash": row["preregistration_content_hash"],
                "decisionManifestContentHash": row["decision_manifest_content_hash"],
                "decisionControlledArtifactHash": (
                    row["decision_controlled_artifact_hash"]
                ),
                "decisionControlledArtifactReference": (
                    row["decision_controlled_artifact_reference"]
                ),
                "decisionDataSnapshotId": row["decision_data_snapshot_id"],
                "decisionAsOf": row["decision_as_of"],
                "effectiveAtCompletedSessionOpen": (
                    row["effective_at_completed_session_open"]
                ),
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
                        "maturesAtCompletedSession": (
                            item["matures_at_completed_session"]
                        ),
                        "scheduleContentHash": item["schedule_content_hash"],
                    }
                    for item in schedules
                ],
                "sealedAt": row["sealed_at"],
                "enrollmentContentHash": row["enrollment_content_hash"],
            }
        )

    def _read_outcome_batch(
        self,
        connection: psycopg.Connection[dict[str, Any]],
        outcome_batch_id: UUID,
    ) -> ForwardOutcomeBatchV21:
        row = connection.execute(
            """
            SELECT * FROM analytics.forward_dqv_outcome_batch_v2 WHERE id = %s
            """,
            (outcome_batch_id,),
        ).fetchone()
        if row is None:
            raise ForwardDqvPersistenceNotFound("Forward DQV outcome batch was not found")
        securities = connection.execute(
            """
            SELECT * FROM analytics.forward_dqv_security_outcome_v2
            WHERE outcome_batch_id = %s
            ORDER BY record_ordinal
            """,
            (outcome_batch_id,),
        ).fetchall()
        benchmarks = connection.execute(
            """
            SELECT * FROM analytics.forward_dqv_benchmark_outcome_v2
            WHERE outcome_batch_id = %s
            ORDER BY record_ordinal
            """,
            (outcome_batch_id,),
        ).fetchall()
        metrics = connection.execute(
            """
            SELECT metric.*, security.public_id
            FROM analytics.forward_dqv_path_metric_v2 metric
            LEFT JOIN analytics.security security ON security.id = metric.security_id
            WHERE metric.outcome_batch_id = %s
            ORDER BY metric.record_ordinal
            """,
            (outcome_batch_id,),
        ).fetchall()
        return ForwardOutcomeBatchV21.model_validate(
            {
                "schemaVersion": row["contract_version"],
                "outcomeBatchId": row["id"],
                "enrollmentId": row["enrollment_id"],
                "completedSessions": row["completed_sessions"],
                "evaluationRole": row["evaluation_role"],
                "resultVersion": row["result_version"],
                "supersedesBatchId": row["supersedes_batch_id"],
                "observedAt": row["observed_at"],
                "maturedAtCompletedSession": row["matured_at_completed_session"],
                "operationalCompleteness": row["operational_completeness"],
                "securityCount": row["security_count"],
                "terminalCounts": row["terminal_counts"],
                "preregistrationContentHash": row["preregistration_content_hash"],
                "decisionManifestContentHash": row["decision_manifest_content_hash"],
                "frozenPopulationHash": row["frozen_population_hash"],
                "modelFreezeHashes": row["model_freeze_hashes"],
                "benchmarkContractHash": row["benchmark_contract_hash"],
                "costPolicyHash": row["cost_policy_hash"],
                "sourceManifestHash": row["source_manifest_hash"],
                "calendarEvidenceHash": row["calendar_evidence_hash"],
                "actionEvidenceHash": row["action_evidence_hash"],
                "priceEvidenceHash": row["price_evidence_hash"],
                "evidenceBlockers": row["evidence_blockers"],
                "securityOutcomes": [
                    {
                        "publicSecurityId": item["public_security_id"],
                        "state": item["state"],
                        "grossReturn": item["gross_return"],
                        "roundTripCostRate": item["round_trip_cost_rate"],
                        "netReturn": item["net_return"],
                        "priceActionEvidenceHash": item["price_action_evidence_hash"],
                        "sourceManifestHash": item["source_manifest_hash"],
                        "reasonCodes": item["reason_codes"],
                        "recordHash": item["record_hash"],
                    }
                    for item in securities
                ],
                "benchmarkOutcomes": [
                    {
                        "kind": item["benchmark_kind"],
                        "identifier": item["benchmark_identifier"],
                        "state": item["state"],
                        "grossReturn": item["gross_return"],
                        "roundTripCostRate": item["round_trip_cost_rate"],
                        "netReturn": item["net_return"],
                        "priceActionEvidenceHash": item["price_action_evidence_hash"],
                        "sourceManifestHash": item["source_manifest_hash"],
                        "reasonCodes": item["reason_codes"],
                        "recordHash": item["record_hash"],
                    }
                    for item in benchmarks
                ],
                "pathMetrics": [
                    {
                        "subjectType": item["subject_type"],
                        "publicSecurityId": item["public_id"],
                        "benchmarkKind": item["benchmark_kind"],
                        "metricCode": item["metric_code"],
                        "state": item["state"],
                        "metricValue": item["metric_value"],
                        "sourceEvidenceHash": item["source_evidence_hash"],
                        "reasonCodes": item["reason_codes"],
                        "metricRecordHash": item["metric_record_hash"],
                    }
                    for item in metrics
                ],
                "outcomeBatchContentHash": row["outcome_batch_content_hash"],
            }
        )

    def _read_quality_report(
        self,
        connection: psycopg.Connection[dict[str, Any]],
        report_id: UUID,
    ) -> ForwardQualityReportV21:
        row = connection.execute(
            """
            SELECT * FROM analytics.forward_dqv_quality_report_v2 WHERE id = %s
            """,
            (report_id,),
        ).fetchone()
        if row is None:
            raise ForwardDqvPersistenceNotFound("Forward DQV quality report was not found")
        return ForwardQualityReportV21.model_validate(
            {
                "schemaVersion": row["contract_version"],
                "reportId": row["id"],
                "enrollmentId": row["enrollment_id"],
                "completedSessions": row["completed_sessions"],
                "modelTrack": row["model_track"],
                "modelVersion": row["model_version"],
                "evaluationRole": row["evaluation_role"],
                "resultVersion": row["result_version"],
                "supersedesReportId": row["supersedes_report_id"],
                "assessedAt": row["assessed_at"],
                "maturedThrough": row["matured_through"],
                "preregistrationContentHash": row["preregistration_content_hash"],
                "operationalCompleteness": row["operational_completeness"],
                "modelQualityStatus": row["model_quality_status"],
                "targetResults": row["target_results"],
                "sourceOutcomeBatchHashes": row["source_outcome_batch_hashes"],
                "sourceDecisionManifestHashes": (
                    row["source_decision_manifest_hashes"]
                ),
                "resamplingPolicyVersion": row["resampling_policy_version"],
                "resamplingPolicyHash": row["resampling_policy_hash"],
                "ordinaryIidBootstrapUsed": row["ordinary_iid_bootstrap_used"],
                "aiInfluence": row["ai_influence"],
                "reportContentHash": row["report_content_hash"],
            }
        )

    @staticmethod
    def _validate_enrollment_binding(
        connection: psycopg.Connection[dict[str, Any]],
        batch: ForwardOutcomeBatchV21,
    ) -> None:
        row = connection.execute(
            """
            SELECT enrollment.preregistration_content_hash,
                   enrollment.decision_manifest_content_hash,
                   enrollment.frozen_population_hash,
                   enrollment.model_freeze_hashes,
                   enrollment.benchmark_contract_hash,
                   enrollment.cost_policy_hash,
                   enrollment.security_count,
                   maturity.evaluation_role,
                   maturity.matures_at_completed_session
            FROM analytics.forward_dqv_enrollment_v2 enrollment
            JOIN analytics.forward_dqv_maturity_schedule_v2 maturity
              ON maturity.enrollment_id = enrollment.id
             AND maturity.completed_sessions = %s
            WHERE enrollment.id = %s
            """,
            (batch.completed_sessions, batch.enrollment_id),
        ).fetchone()
        if row is None:
            raise ForwardDqvPersistenceNotFound(
                "Forward DQV enrollment or maturity schedule was not found"
            )
        expected = (
            batch.preregistration_content_hash,
            batch.decision_manifest_content_hash,
            batch.frozen_population_hash,
            batch.model_freeze_hashes,
            batch.benchmark_contract_hash,
            batch.cost_policy_hash,
            batch.security_count,
            batch.evaluation_role.value,
            batch.matured_at_completed_session,
        )
        observed = (
            row["preregistration_content_hash"],
            row["decision_manifest_content_hash"],
            row["frozen_population_hash"],
            row["model_freeze_hashes"],
            row["benchmark_contract_hash"],
            row["cost_policy_hash"],
            row["security_count"],
            row["evaluation_role"],
            row["matures_at_completed_session"],
        )
        if observed != expected:
            raise ForwardDqvPersistenceConflict(
                "Outcome evidence does not match its sealed enrollment"
            )

    @staticmethod
    def _security_ids(
        connection: psycopg.Connection[dict[str, Any]],
        public_security_ids: tuple[UUID, ...],
    ) -> dict[UUID, int]:
        if not public_security_ids:
            return {}
        rows = connection.execute(
            """
            SELECT id, public_id FROM analytics.security
            WHERE public_id = ANY(%s)
            """,
            (list(public_security_ids),),
        ).fetchall()
        result = {row["public_id"]: row["id"] for row in rows}
        if set(result) != set(public_security_ids):
            raise ForwardDqvPersistenceNotFound(
                "One or more frozen public security IDs were not found"
            )
        return result

    @staticmethod
    def _insert_security_outcomes(
        connection: psycopg.Connection[dict[str, Any]],
        batch: ForwardOutcomeBatchV21,
        security_ids: dict[UUID, int],
    ) -> None:
        for ordinal, item in enumerate(batch.security_outcomes):
            connection.execute(
                """
                INSERT INTO analytics.forward_dqv_security_outcome_v2 (
                    outcome_batch_id, security_id, record_ordinal,
                    public_security_id, state,
                    gross_return, round_trip_cost_rate, net_return,
                    price_action_evidence_hash, source_manifest_hash,
                    reason_codes, record_hash
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    batch.outcome_batch_id,
                    security_ids[item.public_security_id],
                    ordinal,
                    item.public_security_id,
                    item.state.value,
                    item.gross_return,
                    item.round_trip_cost_rate,
                    item.net_return,
                    item.price_action_evidence_hash,
                    item.source_manifest_hash,
                    Jsonb(item.reason_codes),
                    item.record_hash,
                ),
            )

    @staticmethod
    def _insert_benchmark_outcomes(
        connection: psycopg.Connection[dict[str, Any]],
        batch: ForwardOutcomeBatchV21,
    ) -> None:
        for ordinal, item in enumerate(batch.benchmark_outcomes):
            connection.execute(
                """
                INSERT INTO analytics.forward_dqv_benchmark_outcome_v2 (
                    outcome_batch_id, record_ordinal, benchmark_kind,
                    benchmark_identifier,
                    state, gross_return, round_trip_cost_rate, net_return,
                    price_action_evidence_hash, source_manifest_hash,
                    reason_codes, record_hash
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    batch.outcome_batch_id,
                    ordinal,
                    item.kind.value,
                    item.identifier,
                    item.state.value,
                    item.gross_return,
                    item.round_trip_cost_rate,
                    item.net_return,
                    item.price_action_evidence_hash,
                    item.source_manifest_hash,
                    Jsonb(item.reason_codes),
                    item.record_hash,
                ),
            )

    @staticmethod
    def _insert_path_metrics(
        connection: psycopg.Connection[dict[str, Any]],
        batch: ForwardOutcomeBatchV21,
        security_ids: dict[UUID, int],
    ) -> None:
        for ordinal, item in enumerate(batch.path_metrics):
            connection.execute(
                """
                INSERT INTO analytics.forward_dqv_path_metric_v2 (
                    outcome_batch_id, record_ordinal, subject_type, security_id,
                    benchmark_kind,
                    metric_code, state, metric_value, source_evidence_hash,
                    reason_codes, metric_record_hash
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    batch.outcome_batch_id,
                    ordinal,
                    item.subject_type.value,
                    security_ids.get(item.public_security_id)
                    if item.public_security_id is not None
                    else None,
                    item.benchmark_kind.value
                    if item.benchmark_kind is not None
                    else None,
                    item.metric_code.value,
                    item.state.value,
                    item.metric_value,
                    item.source_evidence_hash,
                    Jsonb(item.reason_codes),
                    item.metric_record_hash,
                ),
            )

    @staticmethod
    def _require_exact(observed: str, expected: str, label: str) -> None:
        if observed != expected:
            raise ForwardDqvPersistenceConflict(
                f"{label} is associated with different immutable evidence"
            )
