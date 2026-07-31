from __future__ import annotations

from typing import Any
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

from equity_analysis.analytics_interface.contracts import canonical_hash
from equity_analysis.forward_validation.human_decision_governance_v1 import (
    HumanDecisionRecordV1,
    PortfolioSuitabilityBoundaryV1,
)
from equity_analysis.forward_validation.outcome_persistence_v21 import (
    ForwardDqvPersistenceConflict,
    ForwardDqvPersistenceNotFound,
)


class ForwardDqvGovernanceRepositoryV3:
    """Append-only V20 persistence for post-model human and portfolio sidecars."""

    def __init__(self, database_url: str) -> None:
        if not database_url:
            raise ValueError("Analytics database URL is required")
        self.database_url = database_url

    def persist_human_record(self, record: HumanDecisionRecordV1) -> UUID:
        if record.enrollment_id is None:
            raise ValueError("Formal human decision persistence requires enrollment")
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            existing = connection.execute(
                """
                SELECT record_id, record_content_hash
                FROM analytics.forward_dqv_human_decision_record_v3
                WHERE record_id = %s OR record_content_hash = %s
                ORDER BY CASE WHEN record_id = %s THEN 0 ELSE 1 END
                LIMIT 1
                """,
                (record.record_id, record.record_content_hash, record.record_id),
            ).fetchone()
            if existing is not None:
                if existing["record_content_hash"] != record.record_content_hash:
                    raise ForwardDqvPersistenceConflict(
                        "Human decision idempotency hash differs"
                    )
                if self.read_human_record(existing["record_id"]) != record:
                    raise ForwardDqvPersistenceConflict(
                        "Human decision hash matched but payload differed"
                    )
                return existing["record_id"]
            security_id = self._security_id(connection, record.public_security_id)
            connection.execute(
                """
                INSERT INTO analytics.forward_dqv_human_decision_record_v3 (
                    record_id, enrollment_id, public_security_id, security_id,
                    contract_version, deterministic_output_set_hash,
                    deterministic_security_output_hash,
                    deterministic_output_seal_evidence_hash,
                    deterministic_output_sealed_at, actor_identity, test_identity,
                    human_recorded_at, rationale, confidence, disposition,
                    predecessor_record_hash, supersedes_record_hash,
                    model_score_or_rank_copied_into_record,
                    may_mutate_model_output, may_mutate_model_evidence_label,
                    portfolio_weights_included, trade_decision_included,
                    automatic_execution_authorized, record_content_hash
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                """,
                (
                    record.record_id,
                    record.enrollment_id,
                    record.public_security_id,
                    security_id,
                    record.schema_version,
                    record.deterministic_output_set_hash,
                    record.deterministic_security_output_hash,
                    record.deterministic_output_seal_evidence_hash,
                    record.deterministic_output_sealed_at,
                    record.actor_identity,
                    record.test_identity,
                    record.recorded_at,
                    record.rationale,
                    record.confidence,
                    record.disposition.value,
                    record.predecessor_record_hash,
                    record.supersedes_record_hash,
                    record.model_score_or_rank_copied_into_record,
                    record.may_mutate_model_output,
                    record.may_mutate_model_evidence_label,
                    record.portfolio_weights_included,
                    record.trade_decision_included,
                    record.automatic_execution_authorized,
                    record.record_content_hash,
                ),
            )
            for ordinal, citation in enumerate(record.cited_evidence, start=1):
                citation_body = citation.model_dump(mode="json", by_alias=True)
                connection.execute(
                    """
                    INSERT INTO analytics.forward_dqv_human_evidence_citation_v3 (
                        record_id, citation_ordinal, evidence_kind,
                        evidence_reference, evidence_content_hash, available_at,
                        cited_at, citation_content_hash
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        record.record_id,
                        ordinal,
                        citation.evidence_kind.value,
                        citation.reference,
                        citation.content_hash,
                        citation.available_at,
                        citation.cited_at,
                        canonical_hash(citation_body),
                    ),
                )
        return record.record_id

    def read_human_record(self, record_id: UUID) -> HumanDecisionRecordV1:
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            row = connection.execute(
                """
                SELECT *
                FROM analytics.forward_dqv_human_decision_record_v3
                WHERE record_id = %s
                """,
                (record_id,),
            ).fetchone()
            if row is None:
                raise ForwardDqvPersistenceNotFound(
                    "Forward DQV human decision was not found"
                )
            citations = connection.execute(
                """
                SELECT *
                FROM analytics.forward_dqv_human_evidence_citation_v3
                WHERE record_id = %s
                ORDER BY citation_ordinal
                """,
                (record_id,),
            ).fetchall()
        return HumanDecisionRecordV1.model_validate(
            {
                "schemaVersion": row["contract_version"],
                "recordId": row["record_id"],
                "enrollmentId": row["enrollment_id"],
                "publicSecurityId": row["public_security_id"],
                "deterministicOutputSetHash": row[
                    "deterministic_output_set_hash"
                ],
                "deterministicSecurityOutputHash": row[
                    "deterministic_security_output_hash"
                ],
                "deterministicOutputSealEvidenceHash": row[
                    "deterministic_output_seal_evidence_hash"
                ],
                "deterministicOutputSealedAt": row[
                    "deterministic_output_sealed_at"
                ],
                "actorIdentity": row["actor_identity"],
                "testIdentity": row["test_identity"],
                "recordedAt": row["human_recorded_at"],
                "citedEvidence": [
                    {
                        "evidenceKind": item["evidence_kind"],
                        "reference": item["evidence_reference"],
                        "contentHash": item["evidence_content_hash"],
                        "availableAt": item["available_at"],
                        "citedAt": item["cited_at"],
                    }
                    for item in citations
                ],
                "rationale": row["rationale"],
                "confidence": row["confidence"],
                "disposition": row["disposition"],
                "predecessorRecordHash": row["predecessor_record_hash"],
                "supersedesRecordHash": row["supersedes_record_hash"],
                "modelScoreOrRankCopiedIntoRecord": row[
                    "model_score_or_rank_copied_into_record"
                ],
                "mayMutateModelOutput": row["may_mutate_model_output"],
                "mayMutateModelEvidenceLabel": row[
                    "may_mutate_model_evidence_label"
                ],
                "portfolioWeightsIncluded": row["portfolio_weights_included"],
                "tradeDecisionIncluded": row["trade_decision_included"],
                "automaticExecutionAuthorized": row[
                    "automatic_execution_authorized"
                ],
                "recordContentHash": row["record_content_hash"],
            }
        )

    def persist_portfolio_boundary(
        self,
        boundary: PortfolioSuitabilityBoundaryV1,
        *,
        boundary_version: int,
        supersedes_boundary_hash: str | None = None,
    ) -> UUID:
        if boundary.enrollment_id is None:
            raise ValueError("Formal portfolio boundary requires enrollment")
        if (boundary_version == 1) != (supersedes_boundary_hash is None):
            raise ValueError("Portfolio boundary correction shape is invalid")
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            existing = connection.execute(
                """
                SELECT id, boundary_content_hash
                FROM analytics.forward_dqv_portfolio_suitability_boundary_v3
                WHERE boundary_content_hash = %s
                   OR (
                       enrollment_id = %s
                       AND deterministic_output_set_hash = %s
                       AND boundary_version = %s
                   )
                LIMIT 1
                """,
                (
                    boundary.boundary_content_hash,
                    boundary.enrollment_id,
                    boundary.deterministic_output_set_hash,
                    boundary_version,
                ),
            ).fetchone()
            if existing is not None:
                if existing["boundary_content_hash"] != boundary.boundary_content_hash:
                    raise ForwardDqvPersistenceConflict(
                        "Portfolio boundary idempotency hash differs"
                    )
                return existing["id"]
            row = connection.execute(
                """
                INSERT INTO analytics.forward_dqv_portfolio_suitability_boundary_v3 (
                    enrollment_id, deterministic_output_set_hash,
                    boundary_version, supersedes_boundary_hash,
                    contract_version, model_assessment_state,
                    user_owned_workflow_state, user_owned_workflow_reference,
                    user_owned_workflow_hash, user_owned_workflow_identity,
                    model_may_determine_portfolio_suitability,
                    portfolio_weights_included, trade_decision_included,
                    automatic_execution_authorized, boundary_content_hash
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s
                ) RETURNING id
                """,
                (
                    boundary.enrollment_id,
                    boundary.deterministic_output_set_hash,
                    boundary_version,
                    supersedes_boundary_hash,
                    boundary.schema_version,
                    boundary.model_assessment_state,
                    boundary.user_owned_workflow_state.value,
                    boundary.user_owned_workflow_reference,
                    boundary.user_owned_workflow_hash,
                    boundary.user_owned_workflow_identity,
                    boundary.model_may_determine_portfolio_suitability,
                    boundary.portfolio_weights_included,
                    boundary.trade_decision_included,
                    boundary.automatic_execution_authorized,
                    boundary.boundary_content_hash,
                ),
            ).fetchone()
            return row["id"]

    @staticmethod
    def _security_id(
        connection: psycopg.Connection[dict[str, Any]],
        public_id: UUID,
    ) -> int:
        row = connection.execute(
            "SELECT id FROM analytics.security WHERE public_id = %s",
            (public_id,),
        ).fetchone()
        if row is None:
            raise ForwardDqvPersistenceConflict(
                "Human decision references an unknown security"
            )
        return row["id"]
