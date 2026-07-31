from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from equity_analysis.dual_system_contract import (
    DataState,
    EvidenceClaimClass,
    EvidenceStrictness,
    ModelApplicability,
)
from equity_analysis.evidence_foundation.contracts_v1 import (
    CONTRACT_VERSION,
    PRIVATE_RAW_STORAGE_CLASS,
    CompletedSession,
    ConflictCriticality,
    ConflictStatus,
    EvidenceCandidate,
    EvidenceLayer,
    EvidenceParentReference,
    EvidenceSelectionRequest,
    SecurityIdentity,
    SelectorPolicy,
    UnifiedEvidenceContractViolation,
    applicability_for_company_type,
)
from equity_analysis.evidence_foundation.domain_contracts_v1 import EvidenceDomain
from equity_analysis.evidence_foundation.selector_v1 import (
    EvidenceSelectionResult,
    select_evidence,
)

TOLERANCE_ALIGNMENT = {
    "semantic": True,
    "identity": True,
    "period": True,
    "unit": True,
    "currency": True,
    "adjustment": True,
    "chronology": True,
}


class EvidenceFoundationIntegrityConflict(RuntimeError):
    """Raised when durable V22 identity conflicts cannot be an exact replay."""


@dataclass(frozen=True)
class PersistedEvidenceEnvelope:
    candidate: EvidenceCandidate
    raw_storage_reference: str | None

    @classmethod
    def from_payload(
        cls,
        payload: dict[str, Any],
        *,
        raw_storage_reference: str | None = None,
    ) -> PersistedEvidenceEnvelope:
        candidate = EvidenceCandidate.parse(payload)
        if candidate.layer == EvidenceLayer.NORMALIZED_OBSERVATION:
            if (
                not isinstance(raw_storage_reference, str)
                or not raw_storage_reference.strip()
            ):
                raise UnifiedEvidenceContractViolation(
                    "Normalized evidence persistence requires a private raw storage reference"
                )
        elif raw_storage_reference is not None:
            raise UnifiedEvidenceContractViolation(
                "Engine-derived evidence cannot persist a raw storage reference"
            )
        return cls(
            candidate=candidate,
            raw_storage_reference=raw_storage_reference,
        )

    def to_payload(self) -> dict[str, Any]:
        return candidate_to_payload(self.candidate)


@dataclass(frozen=True)
class PersistedSelectorAggregate:
    request_id: str
    request: EvidenceSelectionRequest
    result: EvidenceSelectionResult
    replayed: bool = field(default=False, compare=False)


@dataclass(frozen=True)
class ModelApplicabilityRouting:
    routing_id: str
    company_id: str
    classification_evidence_id: str
    company_type: str
    applicability: ModelApplicability
    specialized_model_code: str | None
    routing_version: str
    routing_revision: int
    effective_at: datetime
    routing_content_hash: str
    supersedes_routing_id: str | None = None

    @classmethod
    def create(
        cls,
        *,
        routing_id: str,
        company_id: str,
        classification_evidence_id: str,
        company_type: str,
        applicability: ModelApplicability,
        specialized_model_code: str | None,
        routing_version: str,
        routing_revision: int,
        effective_at: datetime,
        supersedes_routing_id: str | None = None,
    ) -> ModelApplicabilityRouting:
        return cls(
            routing_id=routing_id,
            company_id=company_id,
            classification_evidence_id=classification_evidence_id,
            company_type=company_type,
            applicability=applicability,
            specialized_model_code=specialized_model_code,
            routing_version=routing_version,
            routing_revision=routing_revision,
            effective_at=effective_at,
            routing_content_hash=_routing_content_hash_values(
                routing_id=routing_id,
                company_id=company_id,
                classification_evidence_id=classification_evidence_id,
                company_type=company_type,
                applicability=applicability,
                specialized_model_code=specialized_model_code,
                routing_version=routing_version,
                routing_revision=routing_revision,
                effective_at=effective_at,
                supersedes_routing_id=supersedes_routing_id,
            ),
            supersedes_routing_id=supersedes_routing_id,
        )

    def __post_init__(self) -> None:
        for value in (
            self.routing_id,
            self.company_id,
            self.classification_evidence_id,
        ):
            UUID(value)
        if self.supersedes_routing_id is not None:
            UUID(self.supersedes_routing_id)
        if (
            not isinstance(self.routing_revision, int)
            or isinstance(self.routing_revision, bool)
            or self.routing_revision < 1
            or self.effective_at.tzinfo is None
        ):
            raise UnifiedEvidenceContractViolation(
                "Model applicability routing revision or chronology is invalid"
            )
        if self.applicability != applicability_for_company_type(
            self.company_type
        ):
            raise UnifiedEvidenceContractViolation(
                "Model applicability does not match the frozen company-type map"
            )
        specialized = (
            self.applicability
            == ModelApplicability.SPECIALIZED_MODEL_REQUIRED
        )
        if (
            specialized
            and (
                not isinstance(self.specialized_model_code, str)
                or not self.specialized_model_code.strip()
            )
        ) or (not specialized and self.specialized_model_code is not None):
            raise UnifiedEvidenceContractViolation(
                "Specialized model routing must carry exactly one specialized code"
            )
        if (
            not self.routing_version.strip()
            or re.fullmatch(
                r"sha256:[0-9a-f]{64}", self.routing_content_hash
            )
            is None
            or self.routing_content_hash
            != _routing_content_hash_values(
                routing_id=self.routing_id,
                company_id=self.company_id,
                classification_evidence_id=self.classification_evidence_id,
                company_type=self.company_type,
                applicability=self.applicability,
                specialized_model_code=self.specialized_model_code,
                routing_version=self.routing_version,
                routing_revision=self.routing_revision,
                effective_at=self.effective_at,
                supersedes_routing_id=self.supersedes_routing_id,
            )
        ):
            raise UnifiedEvidenceContractViolation(
                "Model applicability routing version or content hash is invalid"
            )


def _routing_content_hash_values(
    *,
    routing_id: str,
    company_id: str,
    classification_evidence_id: str,
    company_type: str,
    applicability: ModelApplicability,
    specialized_model_code: str | None,
    routing_version: str,
    routing_revision: int,
    effective_at: datetime,
    supersedes_routing_id: str | None,
) -> str:
    epoch = datetime(1970, 1, 1, tzinfo=UTC)
    utc_effective = effective_at.astimezone(UTC)
    delta = utc_effective - epoch
    epoch_microseconds = (
        delta.days * 86_400_000_000
        + delta.seconds * 1_000_000
        + delta.microseconds
    )
    canonical = "\x1f".join(
        (
            str(UUID(routing_id)),
            str(UUID(company_id)),
            str(UUID(classification_evidence_id)),
            "FUNDAMENTAL_VALUE",
            company_type,
            applicability.value,
            specialized_model_code or "",
            routing_version,
            str(routing_revision),
            str(epoch_microseconds),
            str(UUID(supersedes_routing_id))
            if supersedes_routing_id is not None
            else "",
        )
    )
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class EvidenceFoundationRepository:
    """Append-only V22 persistence for validated canonical evidence."""

    def __init__(
        self,
        database_url: str,
        *,
        connect: Any = psycopg.connect,
    ) -> None:
        if not database_url:
            raise ValueError("Analytics database URL is required")
        self._database_url = database_url
        self._connect = connect

    def persist_candidate(self, envelope: PersistedEvidenceEnvelope) -> None:
        candidate = envelope.candidate
        try:
            persisted = self.load_candidate(candidate.evidence_id)
        except LookupError:
            pass
        else:
            if persisted == envelope:
                return
            raise EvidenceFoundationIntegrityConflict(
                "Evidence identity reuse conflicts with persisted canonical content"
            )
        try:
            with self._connect(
                self._database_url,
                row_factory=dict_row,
            ) as connection:
                with connection.cursor() as cursor:
                    raw_manifest_id = (
                        _ensure_raw_manifest(cursor, envelope)
                        if candidate.layer
                        == EvidenceLayer.NORMALIZED_OBSERVATION
                        else None
                    )
                    _validate_correction_lineage(cursor, candidate)
                    cursor.execute(
                        _INSERT_CANONICAL_EVIDENCE,
                        _candidate_parameters(candidate, raw_manifest_id),
                    )
                    parent_session_dates: list[date] = []
                    for ordinal, parent_reference in enumerate(
                        candidate.input_evidence_references,
                        start=1,
                    ):
                        cursor.execute(
                            """
                            SELECT
                                evidence_id, normalized_record_hash, security_id,
                                listing_id, state, layer, domain, effective_at,
                                available_at, ingested_at, canonical_data
                            FROM analytics.canonical_evidence_v1
                            WHERE evidence_id = %(parent_evidence_id)s
                            """,
                            {
                                "parent_evidence_id": UUID(
                                    parent_reference.evidence_id
                                )
                            },
                        )
                        parent = cursor.fetchone()
                        if (
                            parent is None
                            or parent["normalized_record_hash"]
                            != parent_reference.normalized_record_hash
                            or str(parent["security_id"])
                            != candidate.security.security_id
                            or str(parent["listing_id"])
                            != candidate.security.listing_id
                            or parent["state"] != DataState.VALID.value
                            or parent["layer"]
                            != EvidenceLayer.NORMALIZED_OBSERVATION.value
                            or parent["domain"] != "DAILY_PRICE"
                            or parent["effective_at"] > candidate.effective_at
                            or parent["available_at"] > candidate.available_at
                            or parent["ingested_at"] > candidate.ingested_at
                        ):
                            raise UnifiedEvidenceContractViolation(
                                "Derived parent identity, hash, domain, or cutoff is invalid"
                            )
                        parent_session_dates.append(
                            date.fromisoformat(
                                parent["canonical_data"]["sessionDate"]
                            )
                        )
                        cursor.execute(
                            """
                            INSERT INTO analytics.canonical_evidence_parent_v1 (
                                evidence_id, parent_ordinal, parent_evidence_id,
                                parent_evidence_hash
                            ) VALUES (
                                %(evidence_id)s, %(parent_ordinal)s,
                                %(parent_evidence_id)s, %(parent_evidence_hash)s
                            )
                            """,
                            {
                                "evidence_id": UUID(candidate.evidence_id),
                                "parent_ordinal": ordinal,
                                "parent_evidence_id": UUID(
                                    parent_reference.evidence_id
                                ),
                                "parent_evidence_hash": (
                                    parent_reference.normalized_record_hash
                                ),
                            },
                        )
                    if (
                        candidate.layer == EvidenceLayer.ENGINE_DERIVED
                        and candidate.state == DataState.VALID
                    ):
                        _validate_liquidity_parent_window(
                            cursor,
                            candidate,
                            parent_session_dates,
                        )
                        cursor.execute(
                            """
                            INSERT INTO analytics.canonical_evidence_parent_seal_v1 (
                                evidence_id, parent_count
                            ) VALUES (%(evidence_id)s, %(parent_count)s)
                            """,
                            {
                                "evidence_id": UUID(candidate.evidence_id),
                                "parent_count": len(
                                    candidate.input_evidence_references
                                ),
                            },
                        )
        except psycopg.errors.UniqueViolation as error:
            try:
                persisted = self.load_candidate(candidate.evidence_id)
            except LookupError:
                raise EvidenceFoundationIntegrityConflict(
                    "Evidence persistence uniqueness conflict is not an exact replay"
                ) from error
            if persisted != envelope:
                raise EvidenceFoundationIntegrityConflict(
                    "Evidence identity reuse conflicts with persisted canonical content"
                ) from error

    def persist_selector_policy(self, policy: SelectorPolicy) -> str:
        with self._connect(
            self._database_url,
            row_factory=dict_row,
        ) as connection:
            with connection.cursor() as cursor:
                persisted_id = _persist_policy(
                    cursor, policy, _policy_id(policy)
                )
        return str(persisted_id)

    def load_selector_policy(self, policy_id: str) -> SelectorPolicy:
        with self._connect(
            self._database_url,
            row_factory=dict_row,
        ) as connection:
            with connection.cursor() as cursor:
                return _load_policy(cursor, UUID(policy_id))

    def load_candidate(self, evidence_id: str) -> PersistedEvidenceEnvelope:
        with self._connect(
            self._database_url,
            row_factory=dict_row,
        ) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    _SELECT_CANONICAL_EVIDENCE,
                    {"evidence_id": UUID(evidence_id)},
                )
                row = cursor.fetchone()
                if row is None:
                    raise LookupError(f"Evidence {evidence_id} was not found")
                cursor.execute(
                    """
                    SELECT parent_evidence_id, parent_evidence_hash
                    FROM analytics.canonical_evidence_parent_v1
                    WHERE evidence_id = %(evidence_id)s
                    ORDER BY parent_ordinal
                    """,
                    {"evidence_id": UUID(evidence_id)},
                )
                parent_references = tuple(
                    EvidenceParentReference(
                        evidence_id=str(parent["parent_evidence_id"]),
                        normalized_record_hash=parent["parent_evidence_hash"],
                    )
                    for parent in cursor.fetchall()
                )
        payload = persistence_row_to_payload(
            row, parent_references=parent_references
        )
        return PersistedEvidenceEnvelope(
            candidate=EvidenceCandidate.parse(payload),
            raw_storage_reference=row["storage_reference"],
        )

    def persist_selector_aggregate(
        self,
        request: EvidenceSelectionRequest,
        result: EvidenceSelectionResult,
    ) -> PersistedSelectorAggregate:
        expected = select_evidence(request)
        if result != expected:
            raise UnifiedEvidenceContractViolation(
                "Selector result must equal the deterministic selector output"
            )
        policy_id = _policy_id(request.policy)
        request_id = _request_id(request)
        with self._connect(
            self._database_url,
            row_factory=dict_row,
        ) as connection:
            with connection.cursor() as cursor:
                policy_id = _persist_policy(cursor, request.policy, policy_id)
                completed_session_id = _resolve_completed_session(
                    cursor, request.completed_session
                )
                cursor.execute(
                    _INSERT_SELECTION_REQUEST,
                    {
                        "request_id": request_id,
                        "contract_version": request.contract_version,
                        "policy_id": policy_id,
                        **_security_parameters(request.security),
                        "completed_session_id": completed_session_id,
                        "decision_cutoff": request.decision_cutoff,
                        "sealed_ingestion_cutoff": (
                            request.sealed_ingestion_cutoff
                        ),
                        "request_content_hash": _request_hash(request),
                    },
                )
                for ordinal, candidate in enumerate(request.candidates, start=1):
                    cursor.execute(
                        """
                        INSERT INTO analytics.evidence_selection_candidate_v1 (
                            request_id, candidate_ordinal, evidence_id
                        ) VALUES (
                            %(request_id)s, %(candidate_ordinal)s, %(evidence_id)s
                        )
                        """,
                        {
                            "request_id": request_id,
                            "candidate_ordinal": ordinal,
                            "evidence_id": UUID(candidate.evidence_id),
                        },
                    )
                cursor.execute(
                    """
                    INSERT INTO analytics.evidence_selection_result_v1 (
                        request_id, selector_version, state, reason_code,
                        selected_evidence_id, result_content_hash
                    ) VALUES (
                        %(request_id)s, %(selector_version)s, %(state)s,
                        %(reason_code)s, %(selected_evidence_id)s,
                        %(result_content_hash)s
                    )
                    """,
                    {
                        "request_id": request_id,
                        "selector_version": result.selector_version,
                        "state": result.state.value,
                        "reason_code": result.reason_code,
                        "selected_evidence_id": (
                            UUID(result.selected.evidence_id)
                            if result.selected is not None
                            else None
                        ),
                        "result_content_hash": _result_hash(request, result),
                    },
                )
                for ordinal, (evidence_id, reason) in enumerate(
                    result.rejection_reasons,
                    start=1,
                ):
                    cursor.execute(
                        """
                        INSERT INTO analytics.evidence_selection_rejection_v1 (
                            request_id, rejection_ordinal, evidence_id,
                            reason_code
                        ) VALUES (
                            %(request_id)s, %(rejection_ordinal)s,
                            %(evidence_id)s, %(reason_code)s
                        )
                        """,
                        {
                            "request_id": request_id,
                            "rejection_ordinal": ordinal,
                            "evidence_id": UUID(evidence_id),
                            "reason_code": reason,
                        },
                    )
                cursor.execute(
                    """
                    INSERT INTO analytics.evidence_selection_seal_v1 (
                        request_id, candidate_count, rejection_count
                    ) VALUES (
                        %(request_id)s, %(candidate_count)s, %(rejection_count)s
                    )
                    """,
                    {
                        "request_id": request_id,
                        "candidate_count": len(request.candidates),
                        "rejection_count": len(result.rejection_reasons),
                    },
                )
        return PersistedSelectorAggregate(
            request_id=str(request_id),
            request=request,
            result=result,
        )

    def load_selector_aggregate(
        self,
        request_id: str,
    ) -> PersistedSelectorAggregate:
        checked_request_id = UUID(request_id)
        with self._connect(
            self._database_url,
            row_factory=dict_row,
        ) as connection:
            with connection.cursor() as cursor:
                cursor.execute(_SELECT_SELECTION_REQUEST, {"request_id": checked_request_id})
                request_row = cursor.fetchone()
                if request_row is None:
                    raise LookupError(f"Selector request {request_id} was not found")
                policy = _load_policy(cursor, request_row["policy_id"])
                cursor.execute(
                    """
                    SELECT evidence_id
                    FROM analytics.evidence_selection_candidate_v1
                    WHERE request_id = %(request_id)s
                    ORDER BY candidate_ordinal
                    """,
                    {"request_id": checked_request_id},
                )
                candidate_ids = tuple(
                    str(row["evidence_id"]) for row in cursor.fetchall()
                )
                cursor.execute(
                    """
                    SELECT *
                    FROM analytics.evidence_selection_result_v1
                    WHERE request_id = %(request_id)s
                    """,
                    {"request_id": checked_request_id},
                )
                result_row = cursor.fetchone()
                if result_row is None:
                    raise UnifiedEvidenceContractViolation(
                        "Persisted selector aggregate is missing its result"
                    )
                cursor.execute(
                    """
                    SELECT evidence_id, reason_code
                    FROM analytics.evidence_selection_rejection_v1
                    WHERE request_id = %(request_id)s
                    ORDER BY rejection_ordinal
                    """,
                    {"request_id": checked_request_id},
                )
                rejection_reasons = tuple(
                    (str(row["evidence_id"]), row["reason_code"])
                    for row in cursor.fetchall()
                )
        candidates = tuple(
            self.load_candidate(evidence_id).candidate
            for evidence_id in candidate_ids
        )
        security = _security_from_row(request_row)
        completed_session = CompletedSession(
            calendar_id=request_row["calendar_id"],
            calendar_version=request_row["calendar_version"],
            mic=request_row["session_mic"],
            session_date=request_row["session_date"],
            timezone=request_row["session_timezone"],
            scheduled_open=request_row["scheduled_open"],
            scheduled_close=request_row["scheduled_close"],
            early_close=request_row["early_close"],
            completed_at=request_row["completed_at"],
        )
        request = EvidenceSelectionRequest(
            contract_version=request_row["contract_version"],
            decision_cutoff=request_row["decision_cutoff"],
            sealed_ingestion_cutoff=request_row["sealed_ingestion_cutoff"],
            security=security,
            completed_session=completed_session,
            policy=policy,
            candidates=candidates,
        )
        if request_row["request_content_hash"] != _request_hash(request):
            raise UnifiedEvidenceContractViolation(
                "Persisted selector request content hash does not match readback"
            )
        selected = next(
            (
                candidate
                for candidate in candidates
                if result_row["selected_evidence_id"] == UUID(candidate.evidence_id)
            ),
            None,
        )
        result = EvidenceSelectionResult(
            state=DataState(result_row["state"]),
            reason_code=result_row["reason_code"],
            selector_version=result_row["selector_version"],
            selected=selected,
            rejected_evidence_ids=tuple(
                sorted(evidence_id for evidence_id, _ in rejection_reasons)
            ),
            rejection_reasons=tuple(sorted(rejection_reasons)),
        )
        if result_row["result_content_hash"] != _result_hash(request, result):
            raise UnifiedEvidenceContractViolation(
                "Persisted selector result content hash does not match readback"
            )
        if select_evidence(request) != result:
            raise UnifiedEvidenceContractViolation(
                "Persisted selector aggregate does not reproduce deterministically"
            )
        return PersistedSelectorAggregate(
            request_id=str(checked_request_id),
            request=request,
            result=result,
        )

    def execute_selector(
        self,
        request: EvidenceSelectionRequest,
    ) -> PersistedSelectorAggregate:
        """Execute and durably seal one deterministic V22 selector request.

        Exact replays are idempotent because the request identifier is derived
        from the canonical request content. A conflicting unique-key failure
        is not treated as a replay.
        """

        result = select_evidence(request)
        request_id = str(_request_id(request))
        try:
            return self.persist_selector_aggregate(request, result)
        except psycopg.errors.UniqueViolation as error:
            try:
                persisted = self.load_selector_aggregate(request_id)
            except (
                KeyError,
                LookupError,
                RuntimeError,
                TypeError,
                ValueError,
                psycopg.Error,
            ) as replay_error:
                raise EvidenceFoundationIntegrityConflict(
                    "Selector persistence uniqueness conflict is not an exact replay"
                ) from replay_error
            if persisted.request != request or persisted.result != result:
                raise EvidenceFoundationIntegrityConflict(
                    "Persisted selector replay does not match the canonical request"
                ) from error
            return replace(persisted, replayed=True)

    def persist_applicability_routing(
        self,
        routing: ModelApplicabilityRouting,
    ) -> None:
        with self._connect(
            self._database_url,
            row_factory=dict_row,
        ) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO analytics.model_applicability_routing_v1 (
                        routing_id, company_id, classification_evidence_id,
                        model_family, company_type, applicability,
                        specialized_model_code, routing_version,
                        routing_revision, effective_at,
                        routing_content_hash, supersedes_routing_id
                    ) VALUES (
                        %(routing_id)s, %(company_id)s,
                        %(classification_evidence_id)s, 'FUNDAMENTAL_VALUE',
                        %(company_type)s, %(applicability)s,
                        %(specialized_model_code)s, %(routing_version)s,
                        %(routing_revision)s, %(effective_at)s,
                        %(routing_content_hash)s, %(supersedes_routing_id)s
                    )
                    """,
                    _routing_parameters(routing),
                )

    def load_applicability_routing(
        self,
        routing_id: str,
    ) -> ModelApplicabilityRouting:
        with self._connect(
            self._database_url,
            row_factory=dict_row,
        ) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT *
                    FROM analytics.model_applicability_routing_v1
                    WHERE routing_id = %(routing_id)s
                    """,
                    {"routing_id": UUID(routing_id)},
                )
                row = cursor.fetchone()
        if row is None:
            raise LookupError(f"Applicability routing {routing_id} was not found")
        return _routing_from_row(row)

    def load_latest_applicability_routing(
        self,
        company_id: str,
        routing_version: str,
    ) -> ModelApplicabilityRouting:
        """Load the unsuperseded applicability route for one governed version."""

        checked_company_id = UUID(company_id)
        if not isinstance(routing_version, str) or not routing_version.strip():
            raise ValueError("Routing version must be nonblank")
        with self._connect(
            self._database_url,
            row_factory=dict_row,
        ) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT route.*
                    FROM analytics.model_applicability_routing_v1 route
                    LEFT JOIN analytics.model_applicability_routing_v1 successor
                      ON successor.supersedes_routing_id = route.routing_id
                    WHERE route.company_id = %(company_id)s
                      AND route.routing_version = %(routing_version)s
                      AND successor.routing_id IS NULL
                    """,
                    {
                        "company_id": checked_company_id,
                        "routing_version": routing_version,
                    },
                )
                rows = cursor.fetchall()
        if not rows:
            raise LookupError(
                "No current applicability routing exists for the requested company and version"
            )
        if len(rows) != 1:
            raise UnifiedEvidenceContractViolation(
                "Applicability routing has multiple unsuperseded rows"
            )
        return _routing_from_row(rows[0])


def _routing_from_row(row: dict[str, Any]) -> ModelApplicabilityRouting:
    routing = ModelApplicabilityRouting(
        routing_id=str(row["routing_id"]),
        company_id=str(row["company_id"]),
        classification_evidence_id=str(row["classification_evidence_id"]),
        company_type=row["company_type"],
        applicability=ModelApplicability(row["applicability"]),
        specialized_model_code=row["specialized_model_code"],
        routing_version=row["routing_version"],
        routing_revision=row["routing_revision"],
        effective_at=row["effective_at"],
        routing_content_hash=row["routing_content_hash"],
        supersedes_routing_id=(
            str(row["supersedes_routing_id"])
            if row["supersedes_routing_id"] is not None
            else None
        ),
    )
    if routing.routing_content_hash != _routing_content_hash_values(
        routing_id=routing.routing_id,
        company_id=routing.company_id,
        classification_evidence_id=routing.classification_evidence_id,
        company_type=routing.company_type,
        applicability=routing.applicability,
        specialized_model_code=routing.specialized_model_code,
        routing_version=routing.routing_version,
        routing_revision=routing.routing_revision,
        effective_at=routing.effective_at,
        supersedes_routing_id=routing.supersedes_routing_id,
    ):
        raise UnifiedEvidenceContractViolation(
            "Persisted applicability routing content hash does not match readback"
        )
    return routing


def candidate_to_payload(candidate: EvidenceCandidate) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "evidenceId": candidate.evidence_id,
        "domain": candidate.domain,
        "layer": candidate.layer.value,
        "state": candidate.state.value,
        "security": {
            "securityId": candidate.security.security_id,
            "companyId": candidate.security.company_id,
            "instrumentId": candidate.security.instrument_id,
            "shareClassId": candidate.security.share_class_id,
            "listingId": candidate.security.listing_id,
            "tickerAssignmentId": candidate.security.ticker_assignment_id,
            "ticker": candidate.security.ticker,
            "mic": candidate.security.mic,
            "currency": candidate.security.currency,
        },
        "strictnessClass": candidate.strictness_class.value,
        "claimClass": candidate.claim_class.value,
        "observationReference": candidate.observation_reference,
        "canonicalData": candidate.canonical_data,
        "lineage": {
            "providerCode": candidate.provider_code,
            "providerSchemaVersion": candidate.provider_schema_version,
            "adapterVersion": candidate.adapter_version,
            "normalizationVersion": candidate.normalization_version,
            "sourceRecordId": candidate.source_record_id,
            "sourceRevision": candidate.source_revision,
            "sourceContentHash": candidate.source_content_hash,
            "normalizedRecordHash": candidate.normalized_record_hash,
            "effectiveAt": _instant(candidate.effective_at),
            "availableAt": _instant(candidate.available_at),
            "retrievedAt": _optional_instant(candidate.retrieved_at),
            "ingestedAt": _instant(candidate.ingested_at),
            "freshnessPolicyVersion": candidate.freshness_policy_version,
            "staleAfter": _optional_instant(candidate.stale_after),
            "conflict": {
                "status": candidate.conflict_status.value,
                "criticality": candidate.conflict_criticality.value,
                "affectedFactors": list(candidate.affected_factors),
            },
        },
    }
    if candidate.reason_code is not None:
        payload["reasonCode"] = candidate.reason_code
    if candidate.layer == EvidenceLayer.NORMALIZED_OBSERVATION:
        payload["rawManifest"] = {
            "storageClass": PRIVATE_RAW_STORAGE_CLASS,
            "payloadStoredInGit": False,
            "sourceContentHash": candidate.source_content_hash,
        }
    else:
        payload["derivation"] = {
            "derivationVersion": candidate.derivation_version,
            "inputEvidenceReferences": [
                {
                    "evidenceId": reference.evidence_id,
                    "normalizedRecordHash": reference.normalized_record_hash,
                }
                for reference in candidate.input_evidence_references
            ],
            "outputContentHash": candidate.normalized_record_hash,
        }
    if candidate.supersedes_evidence_id is not None:
        payload["supersedesEvidenceId"] = candidate.supersedes_evidence_id
    if candidate.tolerance_field_code is not None:
        payload["fieldTolerancePolicy"] = {
            "policyVersion": candidate.tolerance_policy_version,
            "fieldCode": candidate.tolerance_field_code,
            "alignmentSatisfied": True,
            "alignmentDimensions": dict(TOLERANCE_ALIGNMENT),
        }
    return payload


def persistence_row_to_payload(
    row: dict[str, Any],
    *,
    parent_references: tuple[EvidenceParentReference, ...],
) -> dict[str, Any]:
    candidate = EvidenceCandidate(
        evidence_id=str(row["evidence_id"]),
        domain=row["domain"],
        layer=EvidenceLayer(row["layer"]),
        state=DataState(row["state"]),
        reason_code=row["reason_code"],
        security=_security_from_row(row),
        provider_code=row["provider_code"],
        provider_schema_version=row["provider_schema_version"],
        adapter_version=row["adapter_version"],
        normalization_version=row["normalization_version"],
        source_record_id=row["source_record_id"],
        source_revision=row["source_revision"],
        source_content_hash=row["source_content_hash"],
        normalized_record_hash=row["normalized_record_hash"],
        effective_at=row["effective_at"],
        available_at=row["available_at"],
        retrieved_at=row["retrieved_at"],
        ingested_at=row["ingested_at"],
        freshness_policy_version=row["freshness_policy_version"],
        stale_after=row["stale_after"],
        strictness_class=EvidenceStrictness(row["strictness_class"]),
        claim_class=EvidenceClaimClass(row["claim_class"]),
        conflict_status=ConflictStatus(row["conflict_status"]),
        conflict_criticality=ConflictCriticality(
            row["conflict_criticality"]
        ),
        affected_factors=tuple(row["affected_factors"]),
        observation_reference=row["observation_reference"],
        derivation_version=row["derivation_version"],
        input_evidence_references=parent_references,
        canonical_data=row["canonical_data"],
        tolerance_policy_version=row["tolerance_policy_version"],
        tolerance_field_code=row["tolerance_field_code"],
        supersedes_evidence_id=(
            str(row["supersedes_evidence_id"])
            if row.get("supersedes_evidence_id") is not None
            else None
        ),
    )
    return candidate_to_payload(candidate)


def _security_from_row(row: dict[str, Any]):
    from equity_analysis.evidence_foundation.contracts_v1 import SecurityIdentity

    return SecurityIdentity(
        security_id=str(row["security_id"]),
        company_id=str(row["company_id"]),
        instrument_id=str(row["instrument_id"]),
        share_class_id=str(row["share_class_id"]),
        listing_id=str(row["listing_id"]),
        ticker_assignment_id=str(row["ticker_assignment_id"]),
        ticker=row["ticker"],
        mic=row["mic"],
        currency=row["currency"],
    )


def _raw_manifest_id(candidate: EvidenceCandidate) -> UUID:
    return uuid5(
        NAMESPACE_URL,
        "|".join(
            (
                CONTRACT_VERSION,
                candidate.provider_code,
                candidate.source_record_id,
                str(candidate.source_revision),
                candidate.source_content_hash,
            )
        ),
    )


def _policy_id(policy: SelectorPolicy) -> UUID:
    return uuid5(NAMESPACE_URL, f"{CONTRACT_VERSION}|policy|{policy.policy_version}")


def _request_id(request: EvidenceSelectionRequest) -> UUID:
    return uuid5(NAMESPACE_URL, _request_hash(request))


def _content_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _policy_hash(policy: SelectorPolicy) -> str:
    return _content_hash(
        {
            "selectorVersion": policy.selector_version,
            "policyVersion": policy.policy_version,
            "domain": policy.domain.value,
            "fieldCode": policy.field_code,
            "requiredLayer": policy.required_layer.value,
            "domainConstraints": policy.domain_constraints,
            "providerFallbackPriority": list(
                policy.provider_fallback_priority
            ),
            "requiredStrictnessClass": (
                policy.required_strictness_class.value
            ),
            "requiredClaimClass": policy.required_claim_class.value,
            "requiredNormalizationVersion": (
                policy.required_normalization_version
            ),
        }
    )


def _request_hash(request: EvidenceSelectionRequest) -> str:
    return _content_hash(
        {
            "contractVersion": request.contract_version,
            "decisionCutoff": _instant(request.decision_cutoff),
            "sealedIngestionCutoff": _instant(
                request.sealed_ingestion_cutoff
            ),
            "security": [
                str(UUID(value)) for value in request.security.durable_tuple
            ],
            "calendarId": request.completed_session.calendar_id,
            "calendarVersion": request.completed_session.calendar_version,
            "sessionDate": request.completed_session.session_date.isoformat(),
            "policyVersion": request.policy.policy_version,
            "candidateIds": [
                str(UUID(candidate.evidence_id))
                for candidate in request.candidates
            ],
        }
    )


def _result_hash(
    request: EvidenceSelectionRequest,
    result: EvidenceSelectionResult,
) -> str:
    parts = [
        str(_request_id(request)),
        _request_hash(request),
        request.contract_version,
        str(_policy_id(request.policy)),
        _policy_hash(request.policy),
        request.policy.policy_version,
        request.policy.selector_version,
        result.selector_version,
        result.state.value,
        result.reason_code or "",
        (
            str(UUID(result.selected.evidence_id))
            if result.selected is not None
            else ""
        ),
    ]
    parts.extend(
        value
        for evidence_id, reason_code in sorted(result.rejection_reasons)
        for value in (str(UUID(evidence_id)), reason_code)
    )
    canonical = "\x1f".join(parts)
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _persist_policy(
    cursor: Any,
    policy: SelectorPolicy,
    proposed_policy_id: UUID,
) -> UUID:
    parameters = {
        "id": proposed_policy_id,
        "selector_version": policy.selector_version,
        "policy_version": policy.policy_version,
        "domain": policy.domain.value,
        "field_code": policy.field_code,
        "required_layer": policy.required_layer.value,
        "domain_constraints": Jsonb(policy.domain_constraints),
        "required_strictness_class": (
            policy.required_strictness_class.value
        ),
        "required_claim_class": policy.required_claim_class.value,
        "required_normalization_version": (
            policy.required_normalization_version
        ),
        "policy_content_hash": _policy_hash(policy),
    }
    cursor.execute(_INSERT_SELECTOR_POLICY, parameters)
    row = cursor.fetchone()
    inserted = row is not None
    if row is None:
        cursor.execute(
            """
            SELECT *
            FROM analytics.evidence_selector_policy_v1
            WHERE policy_version = %(policy_version)s
            """,
            parameters,
        )
        row = cursor.fetchone()
    if row is None or any(
        row[name] != (
            value.obj if isinstance(value, Jsonb) else value
        )
        for name, value in parameters.items()
        if name != "id"
    ):
        raise UnifiedEvidenceContractViolation(
            "Existing selector policy conflicts with the typed policy"
        )
    policy_id = row["id"]
    if inserted:
        for ordinal, provider_code in enumerate(
            policy.provider_fallback_priority,
            start=1,
        ):
            cursor.execute(
                """
                INSERT INTO analytics.evidence_selector_provider_priority_v1 (
                    policy_id, priority_ordinal, provider_code
                ) VALUES (
                    %(policy_id)s, %(priority_ordinal)s, %(provider_code)s
                )
                """,
                {
                    "policy_id": policy_id,
                    "priority_ordinal": ordinal,
                    "provider_code": provider_code,
                },
            )
        cursor.execute(
            """
            INSERT INTO analytics.evidence_selector_policy_seal_v1 (
                policy_id, provider_priority_count
            ) VALUES (%(policy_id)s, %(provider_priority_count)s)
            """,
            {
                "policy_id": policy_id,
                "provider_priority_count": len(
                    policy.provider_fallback_priority
                ),
            },
        )
    cursor.execute(
        """
        SELECT provider_code
        FROM analytics.evidence_selector_provider_priority_v1
        WHERE policy_id = %(policy_id)s
        ORDER BY priority_ordinal
        """,
        {"policy_id": policy_id},
    )
    actual_priority = tuple(
        item["provider_code"] for item in cursor.fetchall()
    )
    if actual_priority != policy.provider_fallback_priority:
        raise UnifiedEvidenceContractViolation(
            "Existing selector provider priority conflicts with the typed policy"
        )
    return policy_id


def _load_policy(cursor: Any, policy_id: UUID) -> SelectorPolicy:
    cursor.execute(
        """
        SELECT *
        FROM analytics.evidence_selector_policy_v1
        WHERE id = %(policy_id)s
        """,
        {"policy_id": policy_id},
    )
    row = cursor.fetchone()
    if row is None:
        raise LookupError(f"Selector policy {policy_id} was not found")
    cursor.execute(
        """
        SELECT provider_code
        FROM analytics.evidence_selector_provider_priority_v1
        WHERE policy_id = %(policy_id)s
        ORDER BY priority_ordinal
        """,
        {"policy_id": policy_id},
    )
    priorities = tuple(item["provider_code"] for item in cursor.fetchall())
    policy = SelectorPolicy(
        selector_version=row["selector_version"],
        policy_version=row["policy_version"],
        domain=EvidenceDomain(row["domain"]),
        field_code=row["field_code"],
        required_layer=EvidenceLayer(row["required_layer"]),
        domain_constraints=row["domain_constraints"],
        provider_fallback_priority=priorities,
        required_strictness_class=EvidenceStrictness(
            row["required_strictness_class"]
        ),
        required_claim_class=EvidenceClaimClass(
            row["required_claim_class"]
        ),
        required_normalization_version=row[
            "required_normalization_version"
        ],
    )
    if row["policy_content_hash"] != _policy_hash(policy):
        raise UnifiedEvidenceContractViolation(
            "Persisted selector policy content hash does not match readback"
        )
    return policy


def _resolve_completed_session(
    cursor: Any,
    session: CompletedSession,
) -> UUID:
    cursor.execute(
        """
        SELECT id
        FROM analytics.evidence_completed_session_v1
        WHERE calendar_id = %(calendar_id)s
          AND calendar_version = %(calendar_version)s
          AND mic = %(mic)s
          AND session_date = %(session_date)s
          AND timezone = %(timezone)s
          AND scheduled_open = %(scheduled_open)s
          AND scheduled_close = %(scheduled_close)s
          AND early_close = %(early_close)s
          AND status = 'COMPLETED'
          AND completed_at = %(completed_at)s
        """,
        {
            "calendar_id": session.calendar_id,
            "calendar_version": session.calendar_version,
            "mic": session.mic,
            "session_date": session.session_date,
            "timezone": session.timezone,
            "scheduled_open": session.scheduled_open,
            "scheduled_close": session.scheduled_close,
            "early_close": session.early_close,
            "completed_at": session.completed_at,
        },
    )
    row = cursor.fetchone()
    if row is None:
        raise UnifiedEvidenceContractViolation(
            "Completed-session registry binding was not found"
        )
    return row["id"]


def _security_parameters(security: SecurityIdentity) -> dict[str, UUID]:
    return {
        "security_id": UUID(security.security_id),
        "company_id": UUID(security.company_id),
        "instrument_id": UUID(security.instrument_id),
        "share_class_id": UUID(security.share_class_id),
        "listing_id": UUID(security.listing_id),
        "ticker_assignment_id": UUID(security.ticker_assignment_id),
    }


def _routing_parameters(
    routing: ModelApplicabilityRouting,
) -> dict[str, Any]:
    return {
        "routing_id": UUID(routing.routing_id),
        "company_id": UUID(routing.company_id),
        "classification_evidence_id": UUID(
            routing.classification_evidence_id
        ),
        "company_type": routing.company_type,
        "applicability": routing.applicability.value,
        "specialized_model_code": routing.specialized_model_code,
        "routing_version": routing.routing_version,
        "routing_revision": routing.routing_revision,
        "effective_at": routing.effective_at,
        "routing_content_hash": routing.routing_content_hash,
        "supersedes_routing_id": (
            UUID(routing.supersedes_routing_id)
            if routing.supersedes_routing_id is not None
            else None
        ),
    }


def _ensure_raw_manifest(
    cursor: Any,
    envelope: PersistedEvidenceEnvelope,
) -> UUID:
    candidate = envelope.candidate
    parameters = {
        "id": _raw_manifest_id(candidate),
        "provider_code": candidate.provider_code,
        "provider_schema_version": candidate.provider_schema_version,
        "source_record_id": candidate.source_record_id,
        "source_revision": candidate.source_revision,
        "source_content_hash": candidate.source_content_hash,
        "storage_class": PRIVATE_RAW_STORAGE_CLASS,
        "storage_reference": envelope.raw_storage_reference,
        "effective_at": candidate.effective_at,
        "available_at": candidate.available_at,
        "retrieved_at": candidate.retrieved_at,
        "ingested_at": candidate.ingested_at,
    }
    cursor.execute(_INSERT_RAW_MANIFEST, parameters)
    inserted = cursor.fetchone()
    if inserted is None:
        cursor.execute(
            """
            SELECT *
            FROM analytics.evidence_raw_manifest_v1
            WHERE provider_code = %(provider_code)s
              AND source_record_id = %(source_record_id)s
              AND source_revision = %(source_revision)s
              AND source_content_hash = %(source_content_hash)s
            """,
            parameters,
        )
        inserted = cursor.fetchone()
    expected = {
        "provider_code": candidate.provider_code,
        "provider_schema_version": candidate.provider_schema_version,
        "source_record_id": candidate.source_record_id,
        "source_revision": candidate.source_revision,
        "source_content_hash": candidate.source_content_hash,
        "storage_class": PRIVATE_RAW_STORAGE_CLASS,
        "payload_stored_in_git": False,
        "storage_reference": envelope.raw_storage_reference,
        "effective_at": candidate.effective_at,
        "available_at": candidate.available_at,
        "retrieved_at": candidate.retrieved_at,
        "ingested_at": candidate.ingested_at,
    }
    if inserted is None or any(
        inserted[name] != value for name, value in expected.items()
    ):
        raise UnifiedEvidenceContractViolation(
            "Existing raw manifest conflicts with the canonical lineage envelope"
        )
    return inserted["id"]


def _validate_correction_lineage(
    cursor: Any,
    candidate: EvidenceCandidate,
) -> None:
    cursor.execute(
        """
        SELECT *
        FROM analytics.canonical_evidence_v1
        WHERE provider_code = %(provider_code)s
          AND source_record_id = %(source_record_id)s
          AND domain = %(domain)s
          AND security_id = %(security_id)s
          AND listing_id = %(listing_id)s
        ORDER BY source_revision DESC, recorded_at DESC, evidence_id
        LIMIT 1
        """,
        {
            "provider_code": candidate.provider_code,
            "source_record_id": candidate.source_record_id,
            "domain": candidate.domain,
            "security_id": UUID(candidate.security.security_id),
            "listing_id": UUID(candidate.security.listing_id),
        },
    )
    latest = cursor.fetchone()
    if latest is None:
        if candidate.supersedes_evidence_id is not None:
            raise UnifiedEvidenceContractViolation(
                "First persisted stream revision cannot supersede evidence"
            )
        return
    latest_revision = latest["source_revision"]
    if candidate.source_revision < latest_revision:
        raise UnifiedEvidenceContractViolation(
            "Evidence revision cannot backdate an existing stream"
        )
    if candidate.source_revision == latest_revision:
        if candidate.supersedes_evidence_id is not None:
            raise UnifiedEvidenceContractViolation(
                "Same-revision evidence cannot declare supersession"
            )
        return
    if (
        candidate.supersedes_evidence_id != str(latest["evidence_id"])
        or candidate.source_revision != latest_revision + 1
        or candidate.effective_at != latest["effective_at"]
        or candidate.available_at < latest["available_at"]
        or candidate.ingested_at <= latest["ingested_at"]
    ):
        raise UnifiedEvidenceContractViolation(
            "Later evidence revision must supersede the latest compatible "
            "stream record with monotonic chronology"
        )


def _validate_liquidity_parent_window(
    cursor: Any,
    candidate: EvidenceCandidate,
    parent_session_dates: list[date],
) -> None:
    if candidate.domain != EvidenceDomain.LIQUIDITY.value:
        raise UnifiedEvidenceContractViolation(
            "Only LIQUIDITY may use engine-derived evidence parents"
        )
    canonical_data = candidate.canonical_data or {}
    window = canonical_data["windowCompletedSessions"]
    valid_count = canonical_data["validObservationCount"]
    window_end = date.fromisoformat(canonical_data["windowEndSessionDate"])
    if (
        len(parent_session_dates) != valid_count
        or len(set(parent_session_dates)) != valid_count
        or max(parent_session_dates, default=None) != window_end
    ):
        raise UnifiedEvidenceContractViolation(
            "Liquidity parents must be distinct and bind to the declared window end"
        )
    cursor.execute(
        """
        SELECT DISTINCT session_date
        FROM analytics.evidence_completed_session_v1
        WHERE mic = %(mic)s
          AND session_date <= %(window_end)s
        ORDER BY session_date DESC
        LIMIT %(window)s
        """,
        {
            "mic": candidate.security.mic,
            "window_end": window_end,
            "window": window,
        },
    )
    allowed_dates = {row["session_date"] for row in cursor.fetchall()}
    if len(allowed_dates) != window or not set(parent_session_dates) <= allowed_dates:
        raise UnifiedEvidenceContractViolation(
            "Liquidity parents must fall within the completed-session window"
        )


def _candidate_parameters(
    candidate: EvidenceCandidate,
    raw_manifest_id: UUID | None,
) -> dict[str, Any]:
    return {
        "evidence_id": UUID(candidate.evidence_id),
        "contract_version": CONTRACT_VERSION,
        "domain": candidate.domain,
        "layer": candidate.layer.value,
        "state": candidate.state.value,
        "reason_code": candidate.reason_code,
        "security_id": UUID(candidate.security.security_id),
        "company_id": UUID(candidate.security.company_id),
        "instrument_id": UUID(candidate.security.instrument_id),
        "share_class_id": UUID(candidate.security.share_class_id),
        "listing_id": UUID(candidate.security.listing_id),
        "ticker_assignment_id": UUID(candidate.security.ticker_assignment_id),
        "ticker": candidate.security.ticker,
        "mic": candidate.security.mic,
        "currency": candidate.security.currency,
        "provider_code": candidate.provider_code,
        "provider_schema_version": candidate.provider_schema_version,
        "adapter_version": candidate.adapter_version,
        "normalization_version": candidate.normalization_version,
        "source_record_id": candidate.source_record_id,
        "source_revision": candidate.source_revision,
        "source_content_hash": candidate.source_content_hash,
        "normalized_record_hash": candidate.normalized_record_hash,
        "effective_at": candidate.effective_at,
        "available_at": candidate.available_at,
        "retrieved_at": candidate.retrieved_at,
        "ingested_at": candidate.ingested_at,
        "freshness_policy_version": candidate.freshness_policy_version,
        "stale_after": candidate.stale_after,
        "strictness_class": candidate.strictness_class.value,
        "claim_class": candidate.claim_class.value,
        "conflict_status": candidate.conflict_status.value,
        "conflict_criticality": candidate.conflict_criticality.value,
        "affected_factors": Jsonb(list(candidate.affected_factors)),
        "tolerance_policy_version": candidate.tolerance_policy_version,
        "tolerance_field_code": candidate.tolerance_field_code,
        "tolerance_alignment": (
            Jsonb(TOLERANCE_ALIGNMENT)
            if candidate.tolerance_field_code is not None
            else None
        ),
        "observation_reference": candidate.observation_reference,
        "raw_manifest_id": raw_manifest_id,
        "derivation_version": candidate.derivation_version,
        "derivation_output_hash": (
            candidate.normalized_record_hash
            if candidate.layer == EvidenceLayer.ENGINE_DERIVED
            else None
        ),
        "canonical_data": (
            Jsonb(candidate.canonical_data)
            if candidate.canonical_data is not None
            else None
        ),
        "supersedes_evidence_id": (
            UUID(candidate.supersedes_evidence_id)
            if candidate.supersedes_evidence_id is not None
            else None
        ),
    }


def _instant(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _optional_instant(value: datetime | None) -> str | None:
    return _instant(value) if value is not None else None


_INSERT_RAW_MANIFEST = """
INSERT INTO analytics.evidence_raw_manifest_v1 (
    id, provider_code, provider_schema_version, source_record_id,
    source_revision, source_content_hash, storage_class,
    payload_stored_in_git, storage_reference, effective_at, available_at,
    retrieved_at, ingested_at
) VALUES (
    %(id)s, %(provider_code)s, %(provider_schema_version)s,
    %(source_record_id)s, %(source_revision)s, %(source_content_hash)s,
    %(storage_class)s, FALSE, %(storage_reference)s, %(effective_at)s,
    %(available_at)s, %(retrieved_at)s, %(ingested_at)s
)
ON CONFLICT (
    provider_code, source_record_id, source_revision, source_content_hash
) DO NOTHING
RETURNING *
"""

_INSERT_SELECTOR_POLICY = """
INSERT INTO analytics.evidence_selector_policy_v1 (
    id, selector_version, policy_version, domain, field_code,
    required_layer, domain_constraints, required_strictness_class,
    required_claim_class, required_normalization_version,
    policy_content_hash
) VALUES (
    %(id)s, %(selector_version)s, %(policy_version)s, %(domain)s,
    %(field_code)s, %(required_layer)s, %(domain_constraints)s,
    %(required_strictness_class)s, %(required_claim_class)s,
    %(required_normalization_version)s, %(policy_content_hash)s
)
ON CONFLICT (policy_version) DO NOTHING
RETURNING *
"""

_INSERT_SELECTION_REQUEST = """
INSERT INTO analytics.evidence_selection_request_v1 (
    request_id, contract_version, policy_id, security_id, company_id,
    instrument_id, share_class_id, listing_id, ticker_assignment_id,
    completed_session_id, decision_cutoff, sealed_ingestion_cutoff,
    request_content_hash
) VALUES (
    %(request_id)s, %(contract_version)s, %(policy_id)s, %(security_id)s,
    %(company_id)s, %(instrument_id)s, %(share_class_id)s, %(listing_id)s,
    %(ticker_assignment_id)s, %(completed_session_id)s,
    %(decision_cutoff)s, %(sealed_ingestion_cutoff)s,
    %(request_content_hash)s
)
"""

_SELECT_SELECTION_REQUEST = """
SELECT
    request.*,
    listing.mic,
    listing.currency,
    ticker.ticker,
    session.calendar_id,
    session.calendar_version,
    session.mic AS session_mic,
    session.session_date,
    session.timezone AS session_timezone,
    session.scheduled_open,
    session.scheduled_close,
    session.early_close,
    session.completed_at
FROM analytics.evidence_selection_request_v1 request
JOIN analytics.evidence_listing_identity_v1 listing
  ON listing.listing_id = request.listing_id
JOIN analytics.evidence_ticker_assignment_v1 ticker
  ON ticker.ticker_assignment_id = request.ticker_assignment_id
JOIN analytics.evidence_completed_session_v1 session
  ON session.id = request.completed_session_id
WHERE request.request_id = %(request_id)s
"""

_INSERT_CANONICAL_EVIDENCE = """
INSERT INTO analytics.canonical_evidence_v1 (
    evidence_id, contract_version, domain, layer, state, reason_code,
    security_id, company_id, instrument_id, share_class_id, listing_id,
    ticker_assignment_id, ticker, mic, currency, provider_code,
    provider_schema_version, adapter_version, normalization_version,
    source_record_id, source_revision, source_content_hash,
    normalized_record_hash, effective_at, available_at, retrieved_at,
    ingested_at, freshness_policy_version, stale_after, strictness_class,
    claim_class, conflict_status, conflict_criticality, affected_factors,
    tolerance_policy_version, tolerance_field_code, tolerance_alignment,
    observation_reference, raw_manifest_id, derivation_version,
    derivation_output_hash, canonical_data, supersedes_evidence_id
) VALUES (
    %(evidence_id)s, %(contract_version)s, %(domain)s, %(layer)s,
    %(state)s, %(reason_code)s, %(security_id)s, %(company_id)s,
    %(instrument_id)s, %(share_class_id)s, %(listing_id)s,
    %(ticker_assignment_id)s, %(ticker)s, %(mic)s, %(currency)s,
    %(provider_code)s, %(provider_schema_version)s, %(adapter_version)s,
    %(normalization_version)s, %(source_record_id)s, %(source_revision)s,
    %(source_content_hash)s, %(normalized_record_hash)s, %(effective_at)s,
    %(available_at)s, %(retrieved_at)s, %(ingested_at)s,
    %(freshness_policy_version)s, %(stale_after)s, %(strictness_class)s,
    %(claim_class)s, %(conflict_status)s, %(conflict_criticality)s,
    %(affected_factors)s, %(tolerance_policy_version)s,
    %(tolerance_field_code)s, %(tolerance_alignment)s,
    %(observation_reference)s, %(raw_manifest_id)s,
    %(derivation_version)s, %(derivation_output_hash)s, %(canonical_data)s,
    %(supersedes_evidence_id)s
)
"""

_SELECT_CANONICAL_EVIDENCE = """
SELECT evidence.*, raw.storage_reference
FROM analytics.canonical_evidence_v1 evidence
LEFT JOIN analytics.evidence_raw_manifest_v1 raw
  ON raw.id = evidence.raw_manifest_id
WHERE evidence.evidence_id = %(evidence_id)s
"""
