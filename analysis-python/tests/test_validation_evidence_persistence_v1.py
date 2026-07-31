from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

import pytest

from equity_analysis.analytics_interface.contracts import canonical_hash
from equity_analysis.validation_evidence_persistence_v1 import (
    ADVISORY_LOCK_SQL,
    INSERT_EVENT_SQL,
    SELECT_EVENT_BY_HASH_SQL,
    SELECT_EXISTING_EVENT_SQL,
    SELECT_SOURCE_RECORDS_SQL,
    ActionAdjustmentReconciliation,
    ActionEvidenceState,
    ActionReconciliationState,
    CalendarAuthorityEvidence,
    CompletedSessionCalendarEvidence,
    FakeValidationEvidenceRepository,
    PostgresValidationEvidenceRepository,
    PricePromotionDecision,
    PriceRowBinding,
    PriceValidationPromotionDecision,
    RawTransportBinding,
    SessionAuthority,
    SessionState,
    SourceHashSemantics,
    SourceRecordBinding,
    SourceRecordBindingError,
    ValidationEvidenceConflictError,
    ValidationEvidenceEventType,
    sql_contract_statements,
)

NOW = datetime(2026, 7, 29, 22, 30, tzinfo=UTC)
SESSION = date(2026, 7, 29)
SECURITY_ID = UUID("10000000-0000-0000-0000-000000000001")


def _hash(character: str) -> str:
    return f"sha256:{character * 64}"


def _source(
    number: int,
    *,
    semantics: SourceHashSemantics = SourceHashSemantics.NORMALIZED_CONTENT,
    digest: str | None = None,
) -> SourceRecordBinding:
    raw = semantics == SourceHashSemantics.RAW_TRANSPORT_BODY
    return SourceRecordBinding(
        source_record_id=UUID(f"20000000-0000-0000-0000-{number:012d}"),
        content_hash=digest or _hash(format(number % 16, "x")),
        source_reference=f"fixture://{'raw' if raw else 'source'}/{number}",
        schema_version=(
            "raw-transport-envelope-v1.0.0"
            if raw
            else "fixture-normalized-v1.0.0"
        ),
        available_at=NOW,
        ingested_at=NOW,
        hash_semantics=semantics,
        storage_reference=(f"object://raw/{number}.json" if raw else None),
    )


def _calendar_request(
    nyse: SourceRecordBinding,
    nasdaq: SourceRecordBinding,
) -> CompletedSessionCalendarEvidence:
    return CompletedSessionCalendarEvidence(
        idempotency_key="calendar:2026-07-29",
        target_session=SESSION,
        reviewed_at=NOW,
        reviewed_by="validation-controller",
        nyse=CalendarAuthorityEvidence(
            authority=SessionAuthority.NYSE,
            session_state=SessionState.COMPLETED,
            source=nyse,
        ),
        nasdaq=CalendarAuthorityEvidence(
            authority=SessionAuthority.NASDAQ,
            session_state=SessionState.COMPLETED,
            source=nasdaq,
        ),
    )


def _raw_request(
    raw: SourceRecordBinding,
    normalized: SourceRecordBinding,
) -> RawTransportBinding:
    return RawTransportBinding(
        idempotency_key="transport:request-1",
        request_journal_hash=_hash("a"),
        bound_at=NOW,
        raw_transport_source=raw,
        normalized_source=normalized,
        normalization_version="daily-price-normalization-v1.0.0",
    )


def _action_request(
    first: SourceRecordBinding,
    second: SourceRecordBinding,
) -> ActionAdjustmentReconciliation:
    return ActionAdjustmentReconciliation(
        idempotency_key="action-adjustment:security-1:2026-07-29",
        security_id=SECURITY_ID,
        target_session=SESSION,
        reconciled_at=NOW,
        reconciliation_state=ActionReconciliationState.RECONCILED,
        action_evidence_state=ActionEvidenceState.SELECTED_ACTIONS,
        action_checkpoint_hash=_hash("b"),
        action_source_manifest_hash=_hash("c"),
        selected_action_revision_hashes=(_hash("e"), _hash("d")),
        raw_price_revision_manifest_hash=_hash("f"),
        adjusted_price_revision_manifest_hash=_hash("1"),
        adjustment_policy_hash=_hash("2"),
        source_records=(second, first),
    )


def _promotion_request(
    first: SourceRecordBinding,
    second: SourceRecordBinding,
) -> PriceValidationPromotionDecision:
    return PriceValidationPromotionDecision(
        idempotency_key="price-promotion:security-1:2026-07-29:RAW",
        security_id=SECURITY_ID,
        trading_date=SESSION,
        adjustment_mode="RAW",
        decided_at=NOW,
        reviewed_cutoff=NOW,
        decision=PricePromotionDecision.PROMOTED,
        validation_decision_hash=_hash("3"),
        promotion_evidence_hash=_hash("4"),
        policy_hash=_hash("5"),
        selected_prior_rows=(
            PriceRowBinding(
                row_id=11,
                revision_number=1,
                source_record_id=first.source_record_id,
            ),
            PriceRowBinding(
                row_id=12,
                revision_number=2,
                source_record_id=second.source_record_id,
            ),
        ),
        source_records=(first, second),
        new_validated_row=PriceRowBinding(
            row_id=13,
            revision_number=3,
            source_record_id=second.source_record_id,
        ),
    )


@pytest.fixture
def source_records() -> tuple[SourceRecordBinding, ...]:
    return (
        _source(
            1,
            semantics=SourceHashSemantics.OFFICIAL_CALENDAR_BODY,
        ),
        _source(
            2,
            semantics=SourceHashSemantics.OFFICIAL_CALENDAR_BODY,
        ),
        _source(3, semantics=SourceHashSemantics.RAW_TRANSPORT_BODY),
        _source(4),
        _source(5),
        _source(6),
    )


@pytest.fixture
def four_requests(
    source_records: tuple[SourceRecordBinding, ...],
) -> tuple[
    CompletedSessionCalendarEvidence,
    RawTransportBinding,
    ActionAdjustmentReconciliation,
    PriceValidationPromotionDecision,
]:
    return (
        _calendar_request(source_records[0], source_records[1]),
        _raw_request(source_records[2], source_records[3]),
        _action_request(source_records[4], source_records[5]),
        _promotion_request(source_records[4], source_records[5]),
    )


def test_all_four_contracts_are_git_safe_append_only_and_exactly_replay(
    source_records: tuple[SourceRecordBinding, ...],
    four_requests: tuple[
        CompletedSessionCalendarEvidence,
        RawTransportBinding,
        ActionAdjustmentReconciliation,
        PriceValidationPromotionDecision,
    ],
) -> None:
    repository = FakeValidationEvidenceRepository(source_records)

    first = [repository.append(request) for request in four_requests]
    second = [repository.append(request) for request in four_requests]

    assert len(repository.all_events()) == 4
    assert {event.event_type for event in first} == set(ValidationEvidenceEventType)
    assert all(not event.replayed for event in first)
    assert all(event.replayed for event in second)
    assert [(event.event_id, event.event_hash) for event in first] == [
        (event.event_id, event.event_hash) for event in second
    ]
    assert all(event.detail["appendOnly"] is True for event in first)
    assert all(event.detail["gitSafe"] is True for event in first)
    assert all("value" not in event.detail for event in first)
    assert all(canonical_hash(event.detail) == event.event_hash for event in first)
    assert not hasattr(repository, "update")
    assert not hasattr(repository, "delete")


@pytest.mark.parametrize("request_index", range(4))
def test_same_idempotency_key_with_changed_evidence_is_rejected(
    source_records: tuple[SourceRecordBinding, ...],
    four_requests: tuple[
        CompletedSessionCalendarEvidence,
        RawTransportBinding,
        ActionAdjustmentReconciliation,
        PriceValidationPromotionDecision,
    ],
    request_index: int,
) -> None:
    repository = FakeValidationEvidenceRepository(source_records)
    original = four_requests[request_index]
    repository.append(original)
    if isinstance(original, CompletedSessionCalendarEvidence):
        changed = replace(original, reviewed_by="different-reviewer")
    elif isinstance(original, RawTransportBinding):
        changed = replace(original, normalization_version="different-v2")
    elif isinstance(original, ActionAdjustmentReconciliation):
        changed = replace(original, adjustment_policy_hash=_hash("6"))
    else:
        changed = replace(original, policy_hash=_hash("6"))

    with pytest.raises(ValidationEvidenceConflictError):
        repository.append(changed)

    assert len(repository.all_events()) == 1


def test_raw_and_normalized_hashes_are_distinct_semantics_not_relabels() -> None:
    same_digest = _hash("7")
    raw = _source(
        31,
        semantics=SourceHashSemantics.RAW_TRANSPORT_BODY,
        digest=same_digest,
    )
    normalized = _source(32, digest=same_digest)
    repository = FakeValidationEvidenceRepository((raw, normalized))

    event = repository.append(_raw_request(raw, normalized))

    assert event.detail["evidence"]["rawHashSemantics"] == "RAW_TRANSPORT_BODY"
    assert event.detail["evidence"]["normalizedHashSemantics"] == "NORMALIZED_CONTENT"
    assert (
        event.detail["evidence"]["rawSourceRecordId"]
        != event.detail["evidence"]["normalizedSourceRecordId"]
    )
    assert event.detail["evidence"]["sameDigestAllowedButNeverSameMeaning"] is True

    with pytest.raises(ValueError, match="Raw transport source schema"):
        replace(
            normalized,
            hash_semantics=SourceHashSemantics.RAW_TRANSPORT_BODY,
            storage_reference="object://raw/32.json",
        )


def test_source_binding_must_match_the_existing_source_record(
    source_records: tuple[SourceRecordBinding, ...],
) -> None:
    repository = FakeValidationEvidenceRepository(source_records)
    altered = replace(source_records[1], content_hash=_hash("8"))

    with pytest.raises(SourceRecordBindingError, match="binding does not match"):
        repository.append(_calendar_request(source_records[0], altered))

    assert repository.all_events() == ()


def test_action_contract_canonicalizes_unordered_hashes_and_sources(
    source_records: tuple[SourceRecordBinding, ...],
) -> None:
    original = _action_request(source_records[4], source_records[5])
    reordered = replace(
        original,
        selected_action_revision_hashes=tuple(
            reversed(original.selected_action_revision_hashes)
        ),
        source_records=tuple(reversed(original.source_records)),
    )
    first_repository = FakeValidationEvidenceRepository(source_records)
    second_repository = FakeValidationEvidenceRepository(source_records)

    first = first_repository.append(original)
    second = second_repository.append(reordered)

    assert first.canonical_request_hash == second.canonical_request_hash
    assert first.event_hash == second.event_hash


def test_reconciled_no_action_case_is_explicit_and_requires_absence_evidence(
    source_records: tuple[SourceRecordBinding, ...],
) -> None:
    no_action = replace(
        _action_request(source_records[4], source_records[5]),
        action_evidence_state=ActionEvidenceState.CONFIRMED_NO_ACTIONS,
        selected_action_revision_hashes=(),
    )
    repository = FakeValidationEvidenceRepository(source_records)

    event = repository.append(no_action)

    assert event.detail["evidence"]["reconciliationState"] == "RECONCILED"
    assert event.detail["evidence"]["actionEvidenceState"] == "CONFIRMED_NO_ACTIONS"
    assert event.detail["evidence"]["selectedActionCount"] == 0
    assert event.detail["evidence"]["selectedActionRevisionHashes"] == []
    assert event.detail["evidence"]["actionCheckpointHash"] == _hash("b")
    assert event.detail["evidence"]["actionSourceManifestHash"] == _hash("c")


def test_action_state_machine_does_not_treat_missing_evidence_as_no_action(
    source_records: tuple[SourceRecordBinding, ...],
) -> None:
    base = _action_request(source_records[4], source_records[5])
    incomplete = replace(
        base,
        reconciliation_state=ActionReconciliationState.BLOCKED,
        action_evidence_state=ActionEvidenceState.INCOMPLETE_ACTION_EVIDENCE,
        selected_action_revision_hashes=(),
    )

    event = FakeValidationEvidenceRepository(source_records).append(incomplete)

    assert event.detail["evidence"]["reconciliationState"] == "BLOCKED"
    assert event.detail["evidence"]["actionEvidenceState"] == (
        "INCOMPLETE_ACTION_EVIDENCE"
    )
    with pytest.raises(ValueError, match="must be RECONCILED"):
        replace(
            incomplete,
            action_evidence_state=ActionEvidenceState.CONFIRMED_NO_ACTIONS,
        )
    with pytest.raises(ValueError, match="requires revision hashes"):
        replace(
            incomplete,
            reconciliation_state=ActionReconciliationState.RECONCILED,
            action_evidence_state=ActionEvidenceState.SELECTED_ACTIONS,
        )


def test_sql_contract_is_limited_to_v4_source_records_and_v16_audit_events() -> None:
    statements = sql_contract_statements()
    normalized = {
        name: " ".join(statement.upper().split())
        for name, statement in statements.items()
    }

    assert statements == {
        "advisoryLock": ADVISORY_LOCK_SQL,
        "selectExistingEvent": SELECT_EXISTING_EVENT_SQL,
        "selectSourceRecords": SELECT_SOURCE_RECORDS_SQL,
        "insertEvent": INSERT_EVENT_SQL,
        "selectEventByHash": SELECT_EVENT_BY_HASH_SQL,
    }
    assert "ANALYTICS.SOURCE_RECORD" in normalized["selectSourceRecords"]
    assert "ANALYTICS.ANALYTICS_AUDIT_EVENT" in normalized["selectExistingEvent"]
    assert "INSERT INTO ANALYTICS.ANALYTICS_AUDIT_EVENT" in normalized["insertEvent"]
    assert "ON CONFLICT (EVENT_HASH) DO NOTHING" in normalized["insertEvent"]
    assert "PG_ADVISORY_XACT_LOCK" in normalized["advisoryLock"]
    assert all(" UPDATE " not in f" {sql} " for sql in normalized.values())
    assert all(" DELETE " not in f" {sql} " for sql in normalized.values())
    assert all("ALTER TABLE" not in sql for sql in normalized.values())
    assert all("CREATE TABLE" not in sql for sql in normalized.values())


class _Result:
    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self.rows = rows or []

    def fetchone(self) -> dict[str, Any] | None:
        return self.rows[0] if self.rows else None

    def fetchall(self) -> list[dict[str, Any]]:
        return self.rows


class _SqlBackend:
    def __init__(self, sources: tuple[SourceRecordBinding, ...]) -> None:
        self.sources = {source.source_record_id: source for source in sources}
        self.events: dict[tuple[str, str, str], dict[str, Any]] = {}
        self.statements: list[str] = []
        self.insert_count = 0

    def connect(self, _database_url: str, **_kwargs: Any) -> _SqlConnection:
        return _SqlConnection(self)


class _SqlConnection:
    def __init__(self, backend: _SqlBackend) -> None:
        self.backend = backend

    def __enter__(self) -> _SqlConnection:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, statement: str, params: tuple[Any, ...]) -> _Result:
        normalized = " ".join(statement.upper().split())
        self.backend.statements.append(normalized)
        if "PG_ADVISORY_XACT_LOCK" in normalized:
            return _Result()
        if "DETAIL->>'IDEMPOTENCYKEY'" in normalized:
            key = (params[0], params[1], params[2])
            row = self.backend.events.get(key)
            return _Result([row] if row else [])
        if "FROM ANALYTICS.SOURCE_RECORD" in normalized:
            rows = []
            for source_id in params[0]:
                source = self.backend.sources[source_id]
                rows.append(
                    {
                        "id": source.source_record_id,
                        "content_hash": source.content_hash,
                        "source_reference": source.source_reference,
                        "schema_version": source.schema_version,
                        "available_at": source.available_at,
                        "ingested_at": source.ingested_at,
                        "storage_reference": source.storage_reference,
                    }
                )
            return _Result(rows)
        if "INSERT INTO ANALYTICS.ANALYTICS_AUDIT_EVENT" in normalized:
            detail = json.loads(params[6])
            row = {
                "id": UUID("30000000-0000-0000-0000-000000000001"),
                "event_hash": params[5],
                "detail": detail,
            }
            key = (params[0], detail["contractVersion"], detail["idempotencyKey"])
            self.backend.events[key] = row
            self.backend.insert_count += 1
            return _Result([row])
        if "WHERE EVENT_HASH = %S" in normalized:
            row = next(
                (
                    item
                    for item in self.backend.events.values()
                    if item["event_hash"] == params[0]
                ),
                None,
            )
            return _Result([row] if row else [])
        raise AssertionError(f"Unexpected SQL statement: {normalized}")


def test_postgres_repository_verifies_sources_and_exactly_replays(
    source_records: tuple[SourceRecordBinding, ...],
) -> None:
    backend = _SqlBackend(source_records)
    repository = PostgresValidationEvidenceRepository(
        "postgresql://fixture",
        connect=backend.connect,
    )
    request = _calendar_request(source_records[0], source_records[1])

    first = repository.append(request)
    second = repository.append(request)

    assert first.replayed is False
    assert second.replayed is True
    assert first.event_id == second.event_id
    assert first.event_hash == second.event_hash
    assert backend.insert_count == 1
    assert any("FROM ANALYTICS.SOURCE_RECORD" in sql for sql in backend.statements)
    assert all(" UPDATE " not in f" {sql} " for sql in backend.statements)
    assert all(" DELETE " not in f" {sql} " for sql in backend.statements)


def test_promotion_rejects_new_row_for_non_promoted_decision(
    source_records: tuple[SourceRecordBinding, ...],
) -> None:
    promoted = _promotion_request(source_records[4], source_records[5])

    with pytest.raises(ValueError, match="Only PROMOTED"):
        replace(promoted, decision=PricePromotionDecision.BLOCKED)
