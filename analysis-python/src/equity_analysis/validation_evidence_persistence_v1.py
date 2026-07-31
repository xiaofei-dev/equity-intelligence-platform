from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Any, Protocol
from uuid import NAMESPACE_URL, UUID, uuid5

import psycopg
from psycopg.rows import dict_row

from equity_analysis.analytics_interface.contracts import canonical_hash

VALIDATION_EVIDENCE_CONTRACT_VERSION = "VALIDATION-EVIDENCE-PERSISTENCE-v1.0.0"
RAW_TRANSPORT_SCHEMA_PREFIX = "raw-transport-"


class ValidationEvidenceEventType(StrEnum):
    COMPLETED_SESSION_CALENDAR_EVIDENCE = "COMPLETED_SESSION_CALENDAR_EVIDENCE"
    RAW_TRANSPORT_BINDING = "RAW_TRANSPORT_BINDING"
    ACTION_ADJUSTMENT_RECONCILIATION = "ACTION_ADJUSTMENT_RECONCILIATION"
    PRICE_VALIDATION_PROMOTION_DECISION = "PRICE_VALIDATION_PROMOTION_DECISION"


class SourceHashSemantics(StrEnum):
    OFFICIAL_CALENDAR_BODY = "OFFICIAL_CALENDAR_BODY"
    RAW_TRANSPORT_BODY = "RAW_TRANSPORT_BODY"
    NORMALIZED_CONTENT = "NORMALIZED_CONTENT"


class SessionAuthority(StrEnum):
    NYSE = "NYSE"
    NASDAQ = "NASDAQ"


class SessionState(StrEnum):
    COMPLETED = "COMPLETED"


class ActionReconciliationState(StrEnum):
    RECONCILED = "RECONCILED"
    BLOCKED = "BLOCKED"


class ActionEvidenceState(StrEnum):
    SELECTED_ACTIONS = "SELECTED_ACTIONS"
    CONFIRMED_NO_ACTIONS = "CONFIRMED_NO_ACTIONS"
    INCOMPLETE_ACTION_EVIDENCE = "INCOMPLETE_ACTION_EVIDENCE"


class PricePromotionDecision(StrEnum):
    PROMOTED = "PROMOTED"
    BLOCKED = "BLOCKED"
    REJECTED = "REJECTED"


class ValidationEvidenceConflictError(RuntimeError):
    pass


class SourceRecordBindingError(RuntimeError):
    pass


@dataclass(frozen=True)
class SourceRecordBinding:
    source_record_id: UUID
    content_hash: str
    source_reference: str
    schema_version: str
    available_at: datetime
    ingested_at: datetime
    hash_semantics: SourceHashSemantics
    storage_reference: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "content_hash", _normalized_hash(self.content_hash))
        _require_text(self.source_reference, "Source reference")
        _require_text(self.schema_version, "Source schema version")
        _require_aware(self.available_at, "Source availableAt")
        _require_aware(self.ingested_at, "Source ingestedAt")
        if self.ingested_at < self.available_at:
            raise ValueError("Source ingestedAt cannot precede availableAt")
        if self.storage_reference is not None:
            _require_text(self.storage_reference, "Source storage reference")
        if self.hash_semantics == SourceHashSemantics.RAW_TRANSPORT_BODY:
            if self.storage_reference is None:
                raise ValueError("Raw transport source requires durable storage_reference")
            if not self.schema_version.startswith(RAW_TRANSPORT_SCHEMA_PREFIX):
                raise ValueError(
                    f"Raw transport source schema must start with {RAW_TRANSPORT_SCHEMA_PREFIX}"
                )
        elif self.schema_version.startswith(RAW_TRANSPORT_SCHEMA_PREFIX):
            raise ValueError("Only raw transport evidence may use a raw transport schema")


@dataclass(frozen=True)
class CalendarAuthorityEvidence:
    authority: SessionAuthority
    session_state: SessionState
    source: SourceRecordBinding

    def __post_init__(self) -> None:
        if self.source.hash_semantics != SourceHashSemantics.OFFICIAL_CALENDAR_BODY:
            raise ValueError(
                "Calendar authority evidence requires official calendar body semantics"
            )


@dataclass(frozen=True)
class CompletedSessionCalendarEvidence:
    idempotency_key: str
    target_session: date
    reviewed_at: datetime
    reviewed_by: str
    nyse: CalendarAuthorityEvidence
    nasdaq: CalendarAuthorityEvidence

    def __post_init__(self) -> None:
        _require_idempotency_key(self.idempotency_key)
        _require_aware(self.reviewed_at, "Calendar reviewedAt")
        _require_text(self.reviewed_by, "Calendar reviewer")
        if self.nyse.authority != SessionAuthority.NYSE:
            raise ValueError("NYSE evidence must use the NYSE authority")
        if self.nasdaq.authority != SessionAuthority.NASDAQ:
            raise ValueError("Nasdaq evidence must use the NASDAQ authority")
        if self.nyse.source.source_record_id == self.nasdaq.source.source_record_id:
            raise ValueError("NYSE and Nasdaq evidence must use distinct source records")


@dataclass(frozen=True)
class RawTransportBinding:
    idempotency_key: str
    request_journal_hash: str
    bound_at: datetime
    raw_transport_source: SourceRecordBinding
    normalized_source: SourceRecordBinding
    normalization_version: str

    def __post_init__(self) -> None:
        _require_idempotency_key(self.idempotency_key)
        object.__setattr__(
            self,
            "request_journal_hash",
            _normalized_hash(self.request_journal_hash),
        )
        _require_aware(self.bound_at, "Raw transport binding boundAt")
        _require_text(self.normalization_version, "Normalization version")
        if (
            self.raw_transport_source.hash_semantics
            != SourceHashSemantics.RAW_TRANSPORT_BODY
        ):
            raise ValueError("Raw source must declare RAW_TRANSPORT_BODY semantics")
        if (
            self.normalized_source.hash_semantics
            != SourceHashSemantics.NORMALIZED_CONTENT
        ):
            raise ValueError("Normalized source must declare NORMALIZED_CONTENT semantics")
        if (
            self.raw_transport_source.source_record_id
            == self.normalized_source.source_record_id
        ):
            raise ValueError("Raw and normalized evidence must use distinct source records")
        if (
            self.raw_transport_source.source_reference
            == self.normalized_source.source_reference
        ):
            raise ValueError("Raw and normalized evidence must use distinct source references")


@dataclass(frozen=True)
class ActionAdjustmentReconciliation:
    idempotency_key: str
    security_id: UUID
    target_session: date
    reconciled_at: datetime
    reconciliation_state: ActionReconciliationState
    action_evidence_state: ActionEvidenceState
    action_checkpoint_hash: str
    action_source_manifest_hash: str
    selected_action_revision_hashes: tuple[str, ...]
    raw_price_revision_manifest_hash: str
    adjusted_price_revision_manifest_hash: str
    adjustment_policy_hash: str
    source_records: tuple[SourceRecordBinding, ...]

    def __post_init__(self) -> None:
        _require_idempotency_key(self.idempotency_key)
        _require_aware(self.reconciled_at, "Action reconciliation reconciledAt")
        for field_name in (
            "action_checkpoint_hash",
            "action_source_manifest_hash",
            "raw_price_revision_manifest_hash",
            "adjusted_price_revision_manifest_hash",
            "adjustment_policy_hash",
        ):
            object.__setattr__(
                self,
                field_name,
                _normalized_hash(getattr(self, field_name)),
            )
        object.__setattr__(
            self,
            "selected_action_revision_hashes",
            _normalized_hashes(self.selected_action_revision_hashes),
        )
        if self.action_evidence_state == ActionEvidenceState.SELECTED_ACTIONS:
            if not self.selected_action_revision_hashes:
                raise ValueError("Selected action evidence requires revision hashes")
        elif self.action_evidence_state == ActionEvidenceState.CONFIRMED_NO_ACTIONS:
            if self.selected_action_revision_hashes:
                raise ValueError("Confirmed no-action evidence cannot contain revision hashes")
            if self.reconciliation_state != ActionReconciliationState.RECONCILED:
                raise ValueError("Confirmed no-action evidence must be RECONCILED")
        else:
            if self.selected_action_revision_hashes:
                raise ValueError("Incomplete action evidence cannot contain revision hashes")
            if self.reconciliation_state != ActionReconciliationState.BLOCKED:
                raise ValueError("Incomplete action evidence must be BLOCKED")
        _require_unique_sources(self.source_records)


@dataclass(frozen=True)
class PriceRowBinding:
    row_id: int
    revision_number: int
    source_record_id: UUID

    def __post_init__(self) -> None:
        if self.row_id <= 0:
            raise ValueError("Price row ID must be positive")
        if self.revision_number <= 0:
            raise ValueError("Price revision number must be positive")


@dataclass(frozen=True)
class PriceValidationPromotionDecision:
    idempotency_key: str
    security_id: UUID
    trading_date: date
    adjustment_mode: str
    decided_at: datetime
    reviewed_cutoff: datetime
    decision: PricePromotionDecision
    validation_decision_hash: str
    promotion_evidence_hash: str
    policy_hash: str
    selected_prior_rows: tuple[PriceRowBinding, ...]
    source_records: tuple[SourceRecordBinding, ...]
    new_validated_row: PriceRowBinding | None = None

    def __post_init__(self) -> None:
        _require_idempotency_key(self.idempotency_key)
        _require_text(self.adjustment_mode, "Adjustment mode")
        _require_aware(self.decided_at, "Promotion decidedAt")
        _require_aware(self.reviewed_cutoff, "Promotion reviewed cutoff")
        if self.decided_at < self.reviewed_cutoff:
            raise ValueError("Promotion decision cannot precede its reviewed cutoff")
        for field_name in (
            "validation_decision_hash",
            "promotion_evidence_hash",
            "policy_hash",
        ):
            object.__setattr__(
                self,
                field_name,
                _normalized_hash(getattr(self, field_name)),
            )
        if not self.selected_prior_rows:
            raise ValueError("Promotion decision requires at least one selected prior row")
        row_ids = [row.row_id for row in self.selected_prior_rows]
        if len(row_ids) != len(set(row_ids)):
            raise ValueError("Selected prior price rows must be unique")
        _require_unique_sources(self.source_records)
        known_sources = {source.source_record_id for source in self.source_records}
        bound_rows = (*self.selected_prior_rows,)
        if self.new_validated_row is not None:
            bound_rows += (self.new_validated_row,)
        if any(row.source_record_id not in known_sources for row in bound_rows):
            raise ValueError("Every price row must bind to a declared source record")
        if self.decision == PricePromotionDecision.PROMOTED:
            if self.new_validated_row is None:
                raise ValueError("PROMOTED decision requires a new validated row")
        elif self.new_validated_row is not None:
            raise ValueError("Only PROMOTED decisions may bind a new validated row")


ValidationEvidenceRequest = (
    CompletedSessionCalendarEvidence
    | RawTransportBinding
    | ActionAdjustmentReconciliation
    | PriceValidationPromotionDecision
)


@dataclass(frozen=True)
class PersistedValidationEvidence:
    event_id: UUID
    event_type: ValidationEvidenceEventType
    event_hash: str
    canonical_request_hash: str
    detail_json: str
    replayed: bool

    @property
    def detail(self) -> dict[str, Any]:
        return json.loads(self.detail_json)


@dataclass(frozen=True)
class _EventDraft:
    event_type: ValidationEvidenceEventType
    entity_type: str
    entity_id: str
    occurred_at: datetime
    correlation_id: str
    idempotency_key: str
    canonical_request_hash: str
    event_hash: str
    detail: dict[str, Any]
    sources: tuple[SourceRecordBinding, ...]


class ValidationEvidenceRepository(Protocol):
    def append(self, request: ValidationEvidenceRequest) -> PersistedValidationEvidence: ...


class FakeValidationEvidenceRepository:
    def __init__(self, source_records: Iterable[SourceRecordBinding]) -> None:
        self._sources = {
            source.source_record_id: source
            for source in source_records
        }
        self._events_by_key: dict[
            tuple[ValidationEvidenceEventType, str, str],
            PersistedValidationEvidence,
        ] = {}

    def append(self, request: ValidationEvidenceRequest) -> PersistedValidationEvidence:
        draft = _draft(request)
        key = (
            draft.event_type,
            VALIDATION_EVIDENCE_CONTRACT_VERSION,
            draft.idempotency_key,
        )
        existing = self._events_by_key.get(key)
        if existing is not None:
            if existing.canonical_request_hash != draft.canonical_request_hash:
                raise ValidationEvidenceConflictError(
                    "Idempotency key is associated with different validation evidence"
                )
            return _with_replay(existing)
        self._verify_sources(draft.sources)
        persisted = _persisted(
            event_id=uuid5(NAMESPACE_URL, draft.event_hash),
            draft=draft,
            replayed=False,
        )
        self._events_by_key[key] = persisted
        return persisted

    def all_events(self) -> tuple[PersistedValidationEvidence, ...]:
        return tuple(self._events_by_key.values())

    def _verify_sources(self, requested: tuple[SourceRecordBinding, ...]) -> None:
        for source in requested:
            stored = self._sources.get(source.source_record_id)
            if stored is None:
                raise SourceRecordBindingError(
                    f"Source record {source.source_record_id} does not exist"
                )
            if stored != source:
                raise SourceRecordBindingError(
                    f"Source record {source.source_record_id} binding does not match"
                )


ADVISORY_LOCK_SQL = """
SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))
"""

SELECT_EXISTING_EVENT_SQL = """
SELECT id, event_hash, detail
FROM analytics.analytics_audit_event
WHERE event_type = %s
  AND detail->>'contractVersion' = %s
  AND detail->>'idempotencyKey' = %s
ORDER BY recorded_at, id
LIMIT 1
"""

SELECT_SOURCE_RECORDS_SQL = """
SELECT id, content_hash, source_reference, schema_version,
       available_at, ingested_at, storage_reference
FROM analytics.source_record
WHERE id = ANY(%s::uuid[])
"""

INSERT_EVENT_SQL = """
INSERT INTO analytics.analytics_audit_event (
    event_type, entity_type, entity_id, actor_service,
    occurred_at, correlation_id, event_hash, detail
) VALUES (%s, %s, %s, 'PYTHON_ANALYTICS', %s, %s, %s, %s::jsonb)
ON CONFLICT (event_hash) DO NOTHING
RETURNING id, event_hash, detail
"""

SELECT_EVENT_BY_HASH_SQL = """
SELECT id, event_hash, detail
FROM analytics.analytics_audit_event
WHERE event_hash = %s
"""


class PostgresValidationEvidenceRepository:
    def __init__(
        self,
        database_url: str,
        *,
        connect: Any = psycopg.connect,
    ) -> None:
        if not database_url:
            raise ValueError("Analytics database URL is required")
        self.database_url = database_url
        self._connect = connect

    def append(self, request: ValidationEvidenceRequest) -> PersistedValidationEvidence:
        draft = _draft(request)
        lock_key = (
            f"{VALIDATION_EVIDENCE_CONTRACT_VERSION}:"
            f"{draft.event_type.value}:{draft.idempotency_key}"
        )
        with self._connect(self.database_url, row_factory=dict_row) as connection:
            connection.execute(ADVISORY_LOCK_SQL, (lock_key,))
            existing = connection.execute(
                SELECT_EXISTING_EVENT_SQL,
                (
                    draft.event_type.value,
                    VALIDATION_EVIDENCE_CONTRACT_VERSION,
                    draft.idempotency_key,
                ),
            ).fetchone()
            if existing is not None:
                return _existing_result(existing, draft)
            self._verify_sources(connection, draft.sources)
            row = connection.execute(
                INSERT_EVENT_SQL,
                (
                    draft.event_type.value,
                    draft.entity_type,
                    draft.entity_id,
                    draft.occurred_at,
                    draft.correlation_id,
                    draft.event_hash,
                    _canonical_json(draft.detail),
                ),
            ).fetchone()
            if row is None:
                row = connection.execute(
                    SELECT_EVENT_BY_HASH_SQL,
                    (draft.event_hash,),
                ).fetchone()
            if row is None:
                raise RuntimeError("Validation evidence audit event was not persisted")
            return _persisted_from_row(row, draft, replayed=False)

    @staticmethod
    def _verify_sources(
        connection: Any,
        requested: tuple[SourceRecordBinding, ...],
    ) -> None:
        ids = [source.source_record_id for source in requested]
        rows = connection.execute(SELECT_SOURCE_RECORDS_SQL, (ids,)).fetchall()
        stored = {row["id"]: row for row in rows}
        for source in requested:
            row = stored.get(source.source_record_id)
            if row is None:
                raise SourceRecordBindingError(
                    f"Source record {source.source_record_id} does not exist"
                )
            actual = (
                _normalized_hash(row["content_hash"]),
                row["source_reference"],
                row["schema_version"],
                row["available_at"],
                row["ingested_at"],
                row["storage_reference"],
            )
            expected = (
                source.content_hash,
                source.source_reference,
                source.schema_version,
                source.available_at,
                source.ingested_at,
                source.storage_reference,
            )
            if actual != expected:
                raise SourceRecordBindingError(
                    f"Source record {source.source_record_id} binding does not match"
                )


def sql_contract_statements() -> Mapping[str, str]:
    return {
        "advisoryLock": ADVISORY_LOCK_SQL,
        "selectExistingEvent": SELECT_EXISTING_EVENT_SQL,
        "selectSourceRecords": SELECT_SOURCE_RECORDS_SQL,
        "insertEvent": INSERT_EVENT_SQL,
        "selectEventByHash": SELECT_EVENT_BY_HASH_SQL,
    }


def _draft(request: ValidationEvidenceRequest) -> _EventDraft:
    event_type, entity_type, entity_id, occurred_at, correlation_id, body, sources = (
        _request_parts(request)
    )
    request_payload = {
        "contractVersion": VALIDATION_EVIDENCE_CONTRACT_VERSION,
        "eventType": event_type.value,
        "idempotencyKey": request.idempotency_key,
        "entityType": entity_type,
        "entityId": entity_id,
        "occurredAt": occurred_at,
        "correlationId": correlation_id,
        "sourceRecordBindings": [_source_payload(item) for item in _sorted_sources(sources)],
        "evidence": body,
    }
    request_hash = canonical_hash(request_payload)
    detail = {
        **request_payload,
        "canonicalRequestHash": request_hash,
        "appendOnly": True,
        "gitSafe": True,
    }
    return _EventDraft(
        event_type=event_type,
        entity_type=entity_type,
        entity_id=entity_id,
        occurred_at=occurred_at,
        correlation_id=correlation_id,
        idempotency_key=request.idempotency_key,
        canonical_request_hash=request_hash,
        event_hash=canonical_hash(detail),
        detail=detail,
        sources=_sorted_sources(sources),
    )


def _request_parts(
    request: ValidationEvidenceRequest,
) -> tuple[
    ValidationEvidenceEventType,
    str,
    str,
    datetime,
    str,
    dict[str, Any],
    tuple[SourceRecordBinding, ...],
]:
    if isinstance(request, CompletedSessionCalendarEvidence):
        sources = (request.nyse.source, request.nasdaq.source)
        evidence = {
            "targetSession": request.target_session,
            "agreementState": "BOTH_AUTHORITIES_COMPLETED",
            "reviewedBy": request.reviewed_by,
            "authorities": [
                _authority_payload(request.nyse),
                _authority_payload(request.nasdaq),
            ],
        }
        return (
            ValidationEvidenceEventType.COMPLETED_SESSION_CALENDAR_EVIDENCE,
            "TRADING_SESSION",
            request.target_session.isoformat(),
            request.reviewed_at,
            canonical_hash([source.content_hash for source in _sorted_sources(sources)]),
            evidence,
            sources,
        )
    if isinstance(request, RawTransportBinding):
        sources = (request.raw_transport_source, request.normalized_source)
        evidence = {
            "requestJournalHash": request.request_journal_hash,
            "normalizationVersion": request.normalization_version,
            "rawSourceRecordId": str(request.raw_transport_source.source_record_id),
            "normalizedSourceRecordId": str(request.normalized_source.source_record_id),
            "rawHashSemantics": SourceHashSemantics.RAW_TRANSPORT_BODY.value,
            "normalizedHashSemantics": SourceHashSemantics.NORMALIZED_CONTENT.value,
            "sameDigestAllowedButNeverSameMeaning": True,
        }
        return (
            ValidationEvidenceEventType.RAW_TRANSPORT_BINDING,
            "PROVIDER_REQUEST",
            request.request_journal_hash,
            request.bound_at,
            request.request_journal_hash,
            evidence,
            sources,
        )
    if isinstance(request, ActionAdjustmentReconciliation):
        evidence = {
            "securityId": str(request.security_id),
            "targetSession": request.target_session,
            "reconciliationState": request.reconciliation_state.value,
            "actionEvidenceState": request.action_evidence_state.value,
            "actionCheckpointHash": request.action_checkpoint_hash,
            "actionSourceManifestHash": request.action_source_manifest_hash,
            "selectedActionRevisionHashes": sorted(
                request.selected_action_revision_hashes
            ),
            "selectedActionCount": len(request.selected_action_revision_hashes),
            "rawPriceRevisionManifestHash": request.raw_price_revision_manifest_hash,
            "adjustedPriceRevisionManifestHash": (
                request.adjusted_price_revision_manifest_hash
            ),
            "adjustmentPolicyHash": request.adjustment_policy_hash,
        }
        return (
            ValidationEvidenceEventType.ACTION_ADJUSTMENT_RECONCILIATION,
            "SECURITY_SESSION",
            f"{request.security_id}:{request.target_session.isoformat()}",
            request.reconciled_at,
            request.action_checkpoint_hash,
            evidence,
            request.source_records,
        )
    evidence = {
        "securityId": str(request.security_id),
        "tradingDate": request.trading_date,
        "adjustmentMode": request.adjustment_mode,
        "reviewedCutoff": request.reviewed_cutoff,
        "decision": request.decision.value,
        "validationDecisionHash": request.validation_decision_hash,
        "promotionEvidenceHash": request.promotion_evidence_hash,
        "policyHash": request.policy_hash,
        "selectedPriorRows": [
            _price_row_payload(row)
            for row in sorted(request.selected_prior_rows, key=lambda item: item.row_id)
        ],
        "newValidatedRow": (
            _price_row_payload(request.new_validated_row)
            if request.new_validated_row is not None
            else None
        ),
        "existingRowsMutated": False,
    }
    return (
        ValidationEvidenceEventType.PRICE_VALIDATION_PROMOTION_DECISION,
        "SECURITY_PRICE_SESSION",
        f"{request.security_id}:{request.trading_date.isoformat()}:{request.adjustment_mode}",
        request.decided_at,
        request.promotion_evidence_hash,
        evidence,
        request.source_records,
    )


def _source_payload(source: SourceRecordBinding) -> dict[str, Any]:
    return {
        "sourceRecordId": str(source.source_record_id),
        "contentHash": source.content_hash,
        "sourceReference": source.source_reference,
        "schemaVersion": source.schema_version,
        "availableAt": source.available_at,
        "ingestedAt": source.ingested_at,
        "hashSemantics": source.hash_semantics.value,
        "storageReference": source.storage_reference,
    }


def _authority_payload(evidence: CalendarAuthorityEvidence) -> dict[str, Any]:
    return {
        "authority": evidence.authority.value,
        "sessionState": evidence.session_state.value,
        "sourceRecordId": str(evidence.source.source_record_id),
        "contentHash": evidence.source.content_hash,
    }


def _price_row_payload(row: PriceRowBinding) -> dict[str, Any]:
    return {
        "rowId": row.row_id,
        "revisionNumber": row.revision_number,
        "sourceRecordId": str(row.source_record_id),
    }


def _existing_result(
    row: Mapping[str, Any],
    draft: _EventDraft,
) -> PersistedValidationEvidence:
    detail = _detail_dict(row["detail"])
    stored_event_hash = _normalized_hash(row["event_hash"])
    if canonical_hash(detail) != stored_event_hash:
        raise ValidationEvidenceConflictError(
            "Persisted validation evidence event hash is invalid"
        )
    if detail.get("canonicalRequestHash") != draft.canonical_request_hash:
        raise ValidationEvidenceConflictError(
            "Idempotency key is associated with different validation evidence"
        )
    return PersistedValidationEvidence(
        event_id=row["id"],
        event_type=draft.event_type,
        event_hash=stored_event_hash,
        canonical_request_hash=draft.canonical_request_hash,
        detail_json=_canonical_json(detail),
        replayed=True,
    )


def _persisted_from_row(
    row: Mapping[str, Any],
    draft: _EventDraft,
    *,
    replayed: bool,
) -> PersistedValidationEvidence:
    detail = _detail_dict(row["detail"])
    if _canonical_json(detail) != _canonical_json(draft.detail):
        raise ValidationEvidenceConflictError(
            "Persisted event hash resolved to different validation evidence"
        )
    stored_event_hash = _normalized_hash(row["event_hash"])
    if canonical_hash(detail) != stored_event_hash:
        raise ValidationEvidenceConflictError(
            "Persisted validation evidence event hash is invalid"
        )
    return PersistedValidationEvidence(
        event_id=row["id"],
        event_type=draft.event_type,
        event_hash=stored_event_hash,
        canonical_request_hash=draft.canonical_request_hash,
        detail_json=_canonical_json(detail),
        replayed=replayed,
    )


def _persisted(
    *,
    event_id: UUID,
    draft: _EventDraft,
    replayed: bool,
) -> PersistedValidationEvidence:
    return PersistedValidationEvidence(
        event_id=event_id,
        event_type=draft.event_type,
        event_hash=draft.event_hash,
        canonical_request_hash=draft.canonical_request_hash,
        detail_json=_canonical_json(draft.detail),
        replayed=replayed,
    )


def _with_replay(
    event: PersistedValidationEvidence,
) -> PersistedValidationEvidence:
    return PersistedValidationEvidence(
        event_id=event.event_id,
        event_type=event.event_type,
        event_hash=event.event_hash,
        canonical_request_hash=event.canonical_request_hash,
        detail_json=event.detail_json,
        replayed=True,
    )


def _detail_dict(value: object) -> dict[str, Any]:
    if isinstance(value, str):
        parsed = json.loads(value)
    else:
        parsed = value
    if not isinstance(parsed, dict):
        raise TypeError("Audit event detail must be a JSON object")
    return parsed


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=_json_default,
    )


def _json_default(value: object) -> str:
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, StrEnum):
        return value.value
    raise TypeError(f"Unsupported JSON value: {type(value).__name__}")


def _sorted_sources(
    sources: tuple[SourceRecordBinding, ...],
) -> tuple[SourceRecordBinding, ...]:
    return tuple(sorted(sources, key=lambda item: str(item.source_record_id)))


def _require_unique_sources(sources: tuple[SourceRecordBinding, ...]) -> None:
    if not sources:
        raise ValueError("At least one source record binding is required")
    ids = [source.source_record_id for source in sources]
    if len(ids) != len(set(ids)):
        raise ValueError("Source record bindings must be unique")


def _normalized_hashes(values: tuple[str, ...]) -> tuple[str, ...]:
    normalized = tuple(sorted({_normalized_hash(value) for value in values}))
    if len(normalized) != len(values):
        raise ValueError("Evidence hashes must be unique")
    return normalized


def _normalized_hash(value: str) -> str:
    candidate = value.removeprefix("sha256:").lower()
    if len(candidate) != 64 or any(character not in "0123456789abcdef" for character in candidate):
        raise ValueError("Evidence hash must be a SHA-256 value")
    return f"sha256:{candidate}"


def _require_aware(value: datetime, label: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")


def _require_text(value: str, label: str) -> None:
    if not value or value.strip() != value:
        raise ValueError(f"{label} must be non-empty and trimmed")


def _require_idempotency_key(value: str) -> None:
    _require_text(value, "Idempotency key")
    if len(value) > 255:
        raise ValueError("Idempotency key must be at most 255 characters")
