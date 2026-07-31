from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Protocol
from uuid import NAMESPACE_URL, UUID, uuid5

import psycopg
from psycopg.rows import dict_row

from equity_analysis.analytics_interface.contracts import canonical_hash
from equity_analysis.future_price_evidence.contracts_v1 import (
    ADTV_POLICY_VERSION,
    FUTURE_PRICE_EVIDENCE_VERSION,
    RAW_HTTP_CAPTURE_VERSION,
    YAHOO_CHART_NORMALIZATION_VERSION,
    DualAuthorityCompletedSessionEvidence,
    NormalizedFuturePriceEvidence,
)
from equity_analysis.validation_evidence_persistence_v1 import (
    ActionAdjustmentReconciliation,
    ActionEvidenceState,
    ActionReconciliationState,
    CalendarAuthorityEvidence,
    CompletedSessionCalendarEvidence,
    FakeValidationEvidenceRepository,
    PricePromotionDecision,
    PriceRowBinding,
    PriceValidationPromotionDecision,
    RawTransportBinding,
    SessionAuthority,
    SessionState,
    SourceHashSemantics,
    SourceRecordBinding,
)

FUTURE_PRICE_PERSISTENCE_VERSION = "FUTURE-PRICE-EVIDENCE-PERSISTENCE-v1.0.0"
ADTV_METRIC_CODE = "average_daily_dollar_volume"
ADTV_UNIT = "USD_NOTIONAL_PER_SESSION"
EMPTY_ACTION_SET_HASH = canonical_hash({"dividends": (), "splits": ()})
PERSISTED_ADJUSTMENT_MODE = "TOTAL_RETURN_ADJUSTED"


class PersistenceExecutionState(StrEnum):
    PREFLIGHT = "PREFLIGHT"
    COMPLETED = "COMPLETED"
    UNKNOWN = "UNKNOWN"


class FuturePricePersistenceError(RuntimeError):
    pass


class FuturePricePersistenceConflictError(FuturePricePersistenceError):
    pass


@dataclass(frozen=True)
class FuturePriceSourceContext:
    yahoo_provider_id: int
    yahoo_ingestion_batch_id: UUID
    nyse_provider_id: int
    nyse_ingestion_batch_id: UUID
    nasdaq_provider_id: int
    nasdaq_ingestion_batch_id: UUID
    normalized_storage_reference: str
    normalized_source_reference: str

    def __post_init__(self) -> None:
        if min(
            self.yahoo_provider_id,
            self.nyse_provider_id,
            self.nasdaq_provider_id,
        ) <= 0:
            raise ValueError("Provider IDs must be positive")
        _require_text(
            self.normalized_storage_reference,
            "Normalized storage reference",
        )
        _require_text(
            self.normalized_source_reference,
            "Normalized source reference",
        )


@dataclass(frozen=True)
class FuturePriceEvidencePersistenceRequest:
    idempotency_key: str
    execution_state: PersistenceExecutionState
    refresh_run_id: UUID
    refresh_task_id: UUID
    database_security_id: int
    public_security_id: UUID
    universe_version: str
    symbol_plan_version: str
    evidence: NormalizedFuturePriceEvidence
    calendar_evidence: DualAuthorityCompletedSessionEvidence
    source_context: FuturePriceSourceContext
    action_evidence_state: ActionEvidenceState
    selected_action_revision_hashes: tuple[str, ...]
    promotion_decision: PricePromotionDecision
    promotion_policy_hash: str
    promotion_evidence_hash: str

    def __post_init__(self) -> None:
        _require_text(self.idempotency_key, "Idempotency key")
        _require_text(self.universe_version, "Universe version")
        _require_text(self.symbol_plan_version, "Symbol plan version")
        if self.database_security_id <= 0:
            raise ValueError("Database security ID must be positive")
        if self.evidence.version != FUTURE_PRICE_EVIDENCE_VERSION:
            raise ValueError("Future price evidence version is not supported")
        if self.evidence.target_session != self.calendar_evidence.target_session:
            raise ValueError("Price and calendar target sessions must match")
        if self.evidence.calendar_evidence_hash != self.calendar_evidence.evidence_hash:
            raise ValueError("Price evidence does not bind the supplied calendar evidence")
        object.__setattr__(
            self,
            "promotion_policy_hash",
            _normalized_hash(self.promotion_policy_hash),
        )
        object.__setattr__(
            self,
            "promotion_evidence_hash",
            _normalized_hash(self.promotion_evidence_hash),
        )
        selected = tuple(
            sorted(
                {
                    _normalized_hash(item)
                    for item in self.selected_action_revision_hashes
                }
            )
        )
        if len(selected) != len(self.selected_action_revision_hashes):
            raise ValueError("Selected action revision hashes must be unique")
        object.__setattr__(self, "selected_action_revision_hashes", selected)
        action_set_hash = _normalized_hash(
            self.evidence.action_binding.selected_action_set_hash
        )
        if self.action_evidence_state == ActionEvidenceState.CONFIRMED_NO_ACTIONS:
            if selected:
                raise ValueError("Confirmed no-action evidence cannot contain revisions")
            if action_set_hash != EMPTY_ACTION_SET_HASH:
                raise ValueError(
                    "Confirmed no-action state requires the canonical empty action set"
                )
        elif self.action_evidence_state == ActionEvidenceState.SELECTED_ACTIONS:
            if not selected:
                raise ValueError("Selected action evidence requires revision hashes")
            if action_set_hash == EMPTY_ACTION_SET_HASH:
                raise ValueError("Selected action evidence cannot bind the empty action set")
        elif selected:
            raise ValueError("Incomplete action evidence cannot contain revision hashes")


@dataclass(frozen=True)
class FuturePriceEvidencePersistenceReceipt:
    contract_version: str
    idempotency_key: str
    canonical_request_hash: str
    refresh_run_id: UUID
    refresh_task_id: UUID
    public_security_id: UUID
    symbol: str
    target_session: str
    universe_version: str
    symbol_plan_version: str
    source_record_ids: tuple[tuple[str, UUID], ...]
    price_row_ids: tuple[int, ...]
    target_prior_price_row_id: int
    target_validated_price_row_id: int | None
    adtv_metric_observation_id: int
    audit_event_hashes: tuple[tuple[str, str], ...]
    checkpoint_hash: str
    replayed: bool

    def git_safe_payload(self) -> dict[str, Any]:
        return {
            "contractVersion": self.contract_version,
            "idempotencyKey": self.idempotency_key,
            "canonicalRequestHash": self.canonical_request_hash,
            "refreshRunId": str(self.refresh_run_id),
            "refreshTaskId": str(self.refresh_task_id),
            "publicSecurityId": str(self.public_security_id),
            "symbol": self.symbol,
            "targetSession": self.target_session,
            "universeVersion": self.universe_version,
            "symbolPlanVersion": self.symbol_plan_version,
            "sourceRecordIds": {
                role: str(source_id) for role, source_id in self.source_record_ids
            },
            "priceRowIds": list(self.price_row_ids),
            "targetPriorPriceRowId": self.target_prior_price_row_id,
            "targetValidatedPriceRowId": self.target_validated_price_row_id,
            "adtvMetricObservationId": self.adtv_metric_observation_id,
            "auditEventHashes": dict(self.audit_event_hashes),
            "checkpointHash": self.checkpoint_hash,
            "rawProviderValuesIncluded": False,
            "scoresOrRanksIncluded": False,
        }


@dataclass(frozen=True)
class _SourceSpec:
    role: str
    ingestion_batch_id: UUID
    provider_id: int
    provider_record_id: str
    source_reference: str
    source_uri: str
    original_at: datetime
    available_at: datetime
    ingested_at: datetime
    schema_version: str
    revision_status: str
    quality_status: str
    content_hash: str
    storage_reference: str
    hash_semantics: SourceHashSemantics


@dataclass(frozen=True)
class _StoredPrice:
    row_id: int
    revision_number: int
    source_record_id: UUID
    quality_status: str


@dataclass(frozen=True)
class _CoreWriteResult:
    source_bindings: Mapping[str, SourceRecordBinding]
    price_rows: tuple[_StoredPrice, ...]
    target_prior_row: _StoredPrice
    target_validated_row: _StoredPrice | None
    adtv_metric_observation_id: int


class FuturePriceEvidencePersistenceRepository(Protocol):
    def persist(
        self,
        request: FuturePriceEvidencePersistenceRequest,
        canonical_request_hash: str,
    ) -> FuturePriceEvidencePersistenceReceipt: ...


class FuturePriceEvidencePersistenceAdapter:
    def __init__(self, repository: FuturePriceEvidencePersistenceRepository) -> None:
        self._repository = repository

    def persist(
        self,
        request: FuturePriceEvidencePersistenceRequest,
    ) -> FuturePriceEvidencePersistenceReceipt:
        if request.execution_state == PersistenceExecutionState.PREFLIGHT:
            raise FuturePricePersistenceError("PREFLIGHT_IS_NOT_EXECUTION")
        if request.execution_state == PersistenceExecutionState.UNKNOWN:
            raise FuturePricePersistenceError("PHYSICAL_REQUEST_STATE_UNKNOWN")
        return self._repository.persist(request, _request_hash(request))


class FakeFuturePriceEvidencePersistenceRepository:
    def __init__(self, *, fail_before_checkpoint_once: bool = False) -> None:
        self._checkpoints: dict[
            tuple[UUID, str],
            tuple[str, FuturePriceEvidencePersistenceReceipt],
        ] = {}
        self._sources: dict[tuple[int, str, str], SourceRecordBinding] = {}
        self._prices: dict[tuple[int, str, int, str], list[dict[str, Any]]] = {}
        self._metrics: dict[tuple[int, str, str, str], list[dict[str, Any]]] = {}
        self._audit_events: dict[str, Any] = {}
        self._next_price_id = 1
        self._next_metric_id = 1
        self._fail_before_checkpoint_once = fail_before_checkpoint_once

    def persist(
        self,
        request: FuturePriceEvidencePersistenceRequest,
        canonical_request_hash: str,
    ) -> FuturePriceEvidencePersistenceReceipt:
        checkpoint_key = (request.refresh_run_id, request.idempotency_key)
        existing = self._checkpoints.get(checkpoint_key)
        if existing is not None:
            if existing[0] != canonical_request_hash:
                raise FuturePricePersistenceConflictError(
                    "Idempotency key is associated with different future price evidence"
                )
            return replace(existing[1], replayed=True)

        sources = dict(self._sources)
        prices = {key: list(rows) for key, rows in self._prices.items()}
        metrics = {key: list(rows) for key, rows in self._metrics.items()}
        next_price_id = self._next_price_id
        next_metric_id = self._next_metric_id

        source_bindings = {}
        for spec in _source_specs(request):
            key = (spec.provider_id, spec.source_reference, spec.content_hash)
            binding = sources.get(key)
            expected = _binding_from_spec(
                spec,
                binding.source_record_id if binding is not None else _source_id(spec),
            )
            if binding is not None and binding != expected:
                raise FuturePricePersistenceConflictError(
                    f"Source record conflict for role {spec.role}"
                )
            sources[key] = expected
            source_bindings[spec.role] = expected

        normalized_source = source_bindings["NORMALIZED_PRICE_ACTION"]
        price_rows: list[_StoredPrice] = []
        for bar in request.evidence.bars:
            key = (
                request.database_security_id,
                bar.trading_date.isoformat(),
                request.source_context.yahoo_provider_id,
                PERSISTED_ADJUSTMENT_MODE,
            )
            rows = prices.setdefault(key, [])
            exact = next(
                (
                    row
                    for row in rows
                    if row["sourceRecordId"] == normalized_source.source_record_id
                    and row["qualityStatus"] == "PROVISIONAL"
                ),
                None,
            )
            if exact is None:
                exact = {
                    "id": next_price_id,
                    "revisionNumber": len(rows) + 1,
                    "sourceRecordId": normalized_source.source_record_id,
                    "qualityStatus": "PROVISIONAL",
                    "bar": bar,
                }
                next_price_id += 1
                rows.append(exact)
            price_rows.append(_stored_price(exact))
        target_prior = next(
            row
            for row, bar in zip(price_rows, request.evidence.bars, strict=True)
            if bar.trading_date == request.evidence.target_session
        )
        validated = None
        if request.promotion_decision == PricePromotionDecision.PROMOTED:
            key = (
                request.database_security_id,
                request.evidence.target_session.isoformat(),
                request.source_context.yahoo_provider_id,
                PERSISTED_ADJUSTMENT_MODE,
            )
            rows = prices[key]
            exact = next(
                (
                    row
                    for row in rows
                    if row["sourceRecordId"] == normalized_source.source_record_id
                    and row["qualityStatus"] == "VALIDATED"
                ),
                None,
            )
            if exact is None:
                exact = {
                    "id": next_price_id,
                    "revisionNumber": len(rows) + 1,
                    "sourceRecordId": normalized_source.source_record_id,
                    "qualityStatus": "VALIDATED",
                    "bar": request.evidence.bars[-1],
                }
                next_price_id += 1
                rows.append(exact)
            validated = _stored_price(exact)

        metric_key = (
            request.database_security_id,
            ADTV_METRIC_CODE,
            ADTV_POLICY_VERSION,
            request.evidence.target_session.isoformat(),
        )
        metric_rows = metrics.setdefault(metric_key, [])
        metric = next(
            (
                row
                for row in metric_rows
                if row["sourceRecordId"] == normalized_source.source_record_id
            ),
            None,
        )
        if metric is None:
            metric = {
                "id": next_metric_id,
                "revisionNumber": len(metric_rows) + 1,
                "sourceRecordId": normalized_source.source_record_id,
                "numericValue": request.evidence.adtv.numeric_value,
            }
            next_metric_id += 1
            metric_rows.append(metric)

        core = _CoreWriteResult(
            source_bindings=source_bindings,
            price_rows=tuple(price_rows),
            target_prior_row=target_prior,
            target_validated_row=validated,
            adtv_metric_observation_id=metric["id"],
        )
        audit_events = _audit_events(request, core)
        receipt = _receipt(
            request,
            canonical_request_hash,
            core,
            audit_events,
            replayed=False,
        )
        if self._fail_before_checkpoint_once:
            self._fail_before_checkpoint_once = False
            raise FuturePricePersistenceError("SIMULATED_ATOMIC_WRITE_FAILURE")

        self._sources = sources
        self._prices = prices
        self._metrics = metrics
        self._audit_events.update(
            {event.event_hash: event for event in audit_events}
        )
        self._next_price_id = next_price_id
        self._next_metric_id = next_metric_id
        self._checkpoints[checkpoint_key] = (canonical_request_hash, receipt)
        return receipt

    @property
    def checkpoint_count(self) -> int:
        return len(self._checkpoints)

    @property
    def source_count(self) -> int:
        return len(self._sources)

    @property
    def audit_event_count(self) -> int:
        return len(self._audit_events)

    @property
    def audit_events(self) -> tuple[Any, ...]:
        return tuple(
            self._audit_events[event_hash]
            for event_hash in sorted(self._audit_events)
        )

    @property
    def price_row_count(self) -> int:
        return sum(len(rows) for rows in self._prices.values())

    @property
    def metric_observation_count(self) -> int:
        return sum(len(rows) for rows in self._metrics.values())

    @property
    def price_adjustment_modes(self) -> tuple[str, ...]:
        return tuple(sorted({key[3] for key in self._prices}))


class PostgresFuturePriceEvidencePersistenceRepository:
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

    def persist(
        self,
        request: FuturePriceEvidencePersistenceRequest,
        canonical_request_hash: str,
    ) -> FuturePriceEvidencePersistenceReceipt:
        checkpoint_key = f"future-price-evidence:{request.idempotency_key}"
        with self._connect(self.database_url, row_factory=dict_row) as connection:
            connection.execute(
                SQL_ADVISORY_LOCK,
                (f"{FUTURE_PRICE_PERSISTENCE_VERSION}:{checkpoint_key}",),
            )
            existing = connection.execute(
                SQL_SELECT_CHECKPOINT,
                (request.refresh_run_id, checkpoint_key),
            ).fetchone()
            if existing is not None:
                return _receipt_from_checkpoint(
                    existing["checkpoint_value"],
                    canonical_request_hash,
                )
            task = connection.execute(
                SQL_SELECT_REFRESH_TASK,
                (request.refresh_task_id, request.refresh_run_id),
            ).fetchone()
            if task is None or task["security_id"] != request.database_security_id:
                raise FuturePricePersistenceError("REFRESH_TASK_SECURITY_MISMATCH")

            bindings = {
                spec.role: self._upsert_source(connection, spec)
                for spec in _source_specs(request)
            }
            core = self._write_core(connection, request, bindings)
            audit_events = _audit_events(request, core)
            for event in audit_events:
                connection.execute(
                    SQL_INSERT_AUDIT_EVENT,
                    (
                        event.event_id,
                        event.event_type.value,
                        event.detail["entityType"],
                        event.detail["entityId"],
                        event.detail["occurredAt"],
                        event.detail["correlationId"],
                        event.event_hash,
                        event.detail_json,
                    ),
                )
            receipt = _receipt(
                request,
                canonical_request_hash,
                core,
                audit_events,
                replayed=False,
            )
            checkpoint_value = receipt.git_safe_payload()
            sequence = connection.execute(
                SQL_NEXT_CHECKPOINT_SEQUENCE,
                (request.refresh_run_id,),
            ).fetchone()["sequence_number"]
            inserted = connection.execute(
                SQL_INSERT_CHECKPOINT,
                (
                    request.refresh_run_id,
                    sequence,
                    checkpoint_key,
                    _json(checkpoint_value),
                    receipt.checkpoint_hash,
                ),
            ).fetchone()
            if inserted is None:
                raise FuturePricePersistenceError("CHECKPOINT_APPEND_FAILED")
            return receipt

    @staticmethod
    def _upsert_source(connection: Any, spec: _SourceSpec) -> SourceRecordBinding:
        source_id = _source_id(spec)
        row = connection.execute(
            SQL_INSERT_SOURCE_RECORD,
            (
                source_id,
                spec.ingestion_batch_id,
                spec.provider_id,
                spec.provider_record_id,
                spec.source_reference,
                spec.source_uri,
                spec.original_at,
                spec.available_at,
                spec.ingested_at,
                spec.schema_version,
                spec.revision_status,
                spec.quality_status,
                spec.content_hash,
                spec.storage_reference,
            ),
        ).fetchone()
        if row is None:
            row = connection.execute(
                SQL_SELECT_SOURCE_RECORD,
                (spec.provider_id, spec.source_reference, spec.content_hash),
            ).fetchone()
        if row is None:
            raise FuturePricePersistenceError(f"SOURCE_APPEND_FAILED[{spec.role}]")
        binding = _binding_from_spec(spec, row["id"])
        actual = (
            _normalized_hash(row["content_hash"]),
            row["source_reference"],
            row["schema_version"],
            row["available_at"],
            row["ingested_at"],
            row["storage_reference"],
        )
        expected = (
            binding.content_hash,
            binding.source_reference,
            binding.schema_version,
            binding.available_at,
            binding.ingested_at,
            binding.storage_reference,
        )
        if actual != expected:
            raise FuturePricePersistenceConflictError(
                f"Source record conflict for role {spec.role}"
            )
        return binding

    def _write_core(
        self,
        connection: Any,
        request: FuturePriceEvidencePersistenceRequest,
        bindings: Mapping[str, SourceRecordBinding],
    ) -> _CoreWriteResult:
        source = bindings["NORMALIZED_PRICE_ACTION"]
        prices = []
        for bar in request.evidence.bars:
            prices.append(
                self._write_price(
                    connection,
                    request,
                    source,
                    bar,
                    quality_status="PROVISIONAL",
                )
            )
        target = next(
            row
            for row, bar in zip(prices, request.evidence.bars, strict=True)
            if bar.trading_date == request.evidence.target_session
        )
        validated = None
        if request.promotion_decision == PricePromotionDecision.PROMOTED:
            validated = self._write_price(
                connection,
                request,
                source,
                request.evidence.bars[-1],
                quality_status="VALIDATED",
            )
        metric_id = self._write_adtv(connection, request, source)
        return _CoreWriteResult(
            source_bindings=bindings,
            price_rows=tuple(prices),
            target_prior_row=target,
            target_validated_row=validated,
            adtv_metric_observation_id=metric_id,
        )

    @staticmethod
    def _write_price(
        connection: Any,
        request: FuturePriceEvidencePersistenceRequest,
        source: SourceRecordBinding,
        bar: Any,
        *,
        quality_status: str,
    ) -> _StoredPrice:
        exact = connection.execute(
            SQL_SELECT_EXACT_PRICE,
            (
                request.database_security_id,
                bar.trading_date,
                request.source_context.yahoo_provider_id,
                PERSISTED_ADJUSTMENT_MODE,
                source.source_record_id,
                quality_status,
            ),
        ).fetchone()
        if exact is None:
            revision = connection.execute(
                SQL_NEXT_PRICE_REVISION,
                (
                    request.database_security_id,
                    bar.trading_date,
                    request.source_context.yahoo_provider_id,
                    PERSISTED_ADJUSTMENT_MODE,
                ),
            ).fetchone()["revision_number"]
            exact = connection.execute(
                SQL_INSERT_PRICE,
                (
                    request.database_security_id,
                    bar.trading_date,
                    bar.open_price,
                    bar.high_price,
                    bar.low_price,
                    bar.close_price,
                    bar.adjusted_close,
                    bar.volume,
                    request.source_context.yahoo_provider_id,
                    PERSISTED_ADJUSTMENT_MODE,
                    revision,
                    source.source_record_id,
                    request.evidence.available_at,
                    request.evidence.ingested_at,
                    YAHOO_CHART_NORMALIZATION_VERSION,
                    quality_status,
                ),
            ).fetchone()
        if exact is None:
            raise FuturePricePersistenceError("PRICE_APPEND_FAILED")
        return _StoredPrice(
            row_id=exact["id"],
            revision_number=exact["revision_number"],
            source_record_id=source.source_record_id,
            quality_status=quality_status,
        )

    @staticmethod
    def _write_adtv(
        connection: Any,
        request: FuturePriceEvidencePersistenceRequest,
        source: SourceRecordBinding,
    ) -> int:
        definition_hash = canonical_hash(
            {
                "metricCode": ADTV_METRIC_CODE,
                "metricVersion": ADTV_POLICY_VERSION,
                "valueType": "NUMERIC",
                "unitPolicy": ADTV_UNIT,
                "formula": "MEAN(RAW_CLOSE * RAW_VOLUME)",
            }
        )
        connection.execute(
            SQL_INSERT_METRIC_DEFINITION,
            (ADTV_METRIC_CODE, ADTV_POLICY_VERSION, ADTV_UNIT, definition_hash),
        )
        definition = connection.execute(
            SQL_SELECT_METRIC_DEFINITION,
            (ADTV_METRIC_CODE, ADTV_POLICY_VERSION),
        ).fetchone()
        if definition is None or definition["definition_hash"] != definition_hash:
            raise FuturePricePersistenceConflictError("ADTV metric definition conflict")
        exact = connection.execute(
            SQL_SELECT_EXACT_METRIC,
            (
                request.database_security_id,
                ADTV_METRIC_CODE,
                ADTV_POLICY_VERSION,
                request.evidence.target_session,
                source.source_record_id,
            ),
        ).fetchone()
        if exact is not None:
            return exact["id"]
        revision = connection.execute(
            SQL_NEXT_METRIC_REVISION,
            (
                request.database_security_id,
                ADTV_METRIC_CODE,
                ADTV_POLICY_VERSION,
                request.evidence.target_session,
            ),
        ).fetchone()["revision_number"]
        row = connection.execute(
            SQL_INSERT_METRIC,
            (
                request.database_security_id,
                ADTV_METRIC_CODE,
                ADTV_POLICY_VERSION,
                request.evidence.target_session,
                request.evidence.adtv.numeric_value,
                ADTV_UNIT,
                request.evidence.adtv.currency,
                source.source_record_id,
                request.evidence.available_at,
                request.evidence.available_at,
                request.evidence.ingested_at,
                revision,
            ),
        ).fetchone()
        if row is None:
            raise FuturePricePersistenceError("ADTV_APPEND_FAILED")
        return row["id"]


def _request_hash(request: FuturePriceEvidencePersistenceRequest) -> str:
    return canonical_hash(
        {
            "contractVersion": FUTURE_PRICE_PERSISTENCE_VERSION,
            "idempotencyKey": request.idempotency_key,
            "executionState": request.execution_state.value,
            "refreshRunId": str(request.refresh_run_id),
            "refreshTaskId": str(request.refresh_task_id),
            "databaseSecurityId": request.database_security_id,
            "publicSecurityId": str(request.public_security_id),
            "universeVersion": request.universe_version,
            "symbolPlanVersion": request.symbol_plan_version,
            "futureEvidenceHash": request.evidence.evidence_hash,
            "calendarEvidenceHash": request.calendar_evidence.evidence_hash,
            "actionEvidenceState": request.action_evidence_state.value,
            "selectedActionRevisionHashes": request.selected_action_revision_hashes,
            "promotionDecision": request.promotion_decision.value,
            "promotionPolicyHash": request.promotion_policy_hash,
            "promotionEvidenceHash": request.promotion_evidence_hash,
            "sourceContext": {
                "yahooProviderId": request.source_context.yahoo_provider_id,
                "yahooBatchId": str(request.source_context.yahoo_ingestion_batch_id),
                "nyseProviderId": request.source_context.nyse_provider_id,
                "nyseBatchId": str(request.source_context.nyse_ingestion_batch_id),
                "nasdaqProviderId": request.source_context.nasdaq_provider_id,
                "nasdaqBatchId": str(request.source_context.nasdaq_ingestion_batch_id),
                "normalizedStorageReference": (
                    request.source_context.normalized_storage_reference
                ),
                "normalizedSourceReference": (
                    request.source_context.normalized_source_reference
                ),
            },
        }
    )


def _source_specs(
    request: FuturePriceEvidencePersistenceRequest,
) -> tuple[_SourceSpec, ...]:
    raw = request.evidence.raw_transport
    context = request.source_context
    reviews = (
        (
            "NYSE_CALENDAR_BODY",
            request.calendar_evidence.nyse,
            context.nyse_provider_id,
            context.nyse_ingestion_batch_id,
        ),
        (
            "NASDAQ_CALENDAR_BODY",
            request.calendar_evidence.nasdaq,
            context.nasdaq_provider_id,
            context.nasdaq_ingestion_batch_id,
        ),
    )
    calendar_specs = tuple(
        _SourceSpec(
            role=role,
            ingestion_batch_id=batch_id,
            provider_id=provider_id,
            provider_record_id=f"{review.authority.value}:{review.target_session}",
            source_reference=review.official_source_url,
            source_uri=review.official_source_url,
            original_at=review.retrieved_at,
            available_at=review.retrieved_at,
            ingested_at=review.reviewed_at,
            schema_version="official-calendar-body-v1.0.0",
            revision_status="AS_REPORTED",
            quality_status="VALIDATED",
            content_hash=_normalized_hash(review.raw_body_sha256),
            storage_reference=review.raw_body_storage_reference,
            hash_semantics=SourceHashSemantics.OFFICIAL_CALENDAR_BODY,
        )
        for role, review, provider_id, batch_id in reviews
    )
    return (
        *calendar_specs,
        _SourceSpec(
            role="YAHOO_RAW_BODY",
            ingestion_batch_id=context.yahoo_ingestion_batch_id,
            provider_id=context.yahoo_provider_id,
            provider_record_id=raw.request_identity,
            source_reference=f"{raw.final_url}#exact-response-body",
            source_uri=raw.final_url,
            original_at=raw.captured_at,
            available_at=raw.captured_at,
            ingested_at=raw.captured_at,
            schema_version="raw-transport-body-v1.0.0",
            revision_status="AS_REPORTED",
            quality_status="VALIDATED",
            content_hash=_normalized_hash(raw.response_body_sha256),
            storage_reference=raw.response_body_storage_reference,
            hash_semantics=SourceHashSemantics.RAW_TRANSPORT_BODY,
        ),
        _SourceSpec(
            role="YAHOO_RESPONSE_ENVELOPE",
            ingestion_batch_id=context.yahoo_ingestion_batch_id,
            provider_id=context.yahoo_provider_id,
            provider_record_id=f"{raw.request_identity}:envelope",
            source_reference=f"{raw.final_url}#sanitized-response-envelope",
            source_uri=raw.final_url,
            original_at=raw.captured_at,
            available_at=raw.captured_at,
            ingested_at=raw.captured_at,
            schema_version=RAW_HTTP_CAPTURE_VERSION,
            revision_status="AS_REPORTED",
            quality_status="VALIDATED",
            content_hash=_normalized_hash(raw.response_envelope_hash),
            storage_reference=raw.response_envelope_storage_reference,
            hash_semantics=SourceHashSemantics.NORMALIZED_CONTENT,
        ),
        _SourceSpec(
            role="NORMALIZED_PRICE_ACTION",
            ingestion_batch_id=context.yahoo_ingestion_batch_id,
            provider_id=context.yahoo_provider_id,
            provider_record_id=(
                f"{request.evidence.symbol}:{request.evidence.target_session}:normalized"
            ),
            source_reference=context.normalized_source_reference,
            source_uri=raw.final_url,
            original_at=raw.captured_at,
            available_at=request.evidence.available_at,
            ingested_at=request.evidence.ingested_at,
            schema_version="future-price-normalized-v1.0.0",
            revision_status="AS_REPORTED",
            quality_status="VALIDATED",
            content_hash=_normalized_hash(request.evidence.evidence_hash),
            storage_reference=context.normalized_storage_reference,
            hash_semantics=SourceHashSemantics.NORMALIZED_CONTENT,
        ),
    )


def _audit_events(
    request: FuturePriceEvidencePersistenceRequest,
    core: _CoreWriteResult,
) -> tuple[Any, ...]:
    sources = core.source_bindings
    calendar_event = CompletedSessionCalendarEvidence(
        idempotency_key=f"{request.idempotency_key}:calendar",
        target_session=request.calendar_evidence.target_session,
        reviewed_at=max(
            request.calendar_evidence.nyse.reviewed_at,
            request.calendar_evidence.nasdaq.reviewed_at,
        ),
        reviewed_by=(
            f"NYSE:{request.calendar_evidence.nyse.reviewed_by};"
            f"NASDAQ:{request.calendar_evidence.nasdaq.reviewed_by}"
        ),
        nyse=CalendarAuthorityEvidence(
            authority=SessionAuthority.NYSE,
            session_state=SessionState.COMPLETED,
            source=sources["NYSE_CALENDAR_BODY"],
        ),
        nasdaq=CalendarAuthorityEvidence(
            authority=SessionAuthority.NASDAQ,
            session_state=SessionState.COMPLETED,
            source=sources["NASDAQ_CALENDAR_BODY"],
        ),
    )
    raw_event = RawTransportBinding(
        idempotency_key=f"{request.idempotency_key}:raw",
        request_journal_hash=_normalized_hash(
            request.evidence.raw_transport.response_envelope_hash
        ),
        bound_at=request.evidence.ingested_at,
        raw_transport_source=sources["YAHOO_RAW_BODY"],
        normalized_source=sources["NORMALIZED_PRICE_ACTION"],
        normalization_version=request.evidence.normalization_version,
    )
    action_state = (
        ActionReconciliationState.BLOCKED
        if request.action_evidence_state
        == ActionEvidenceState.INCOMPLETE_ACTION_EVIDENCE
        else ActionReconciliationState.RECONCILED
    )
    action_event = ActionAdjustmentReconciliation(
        idempotency_key=f"{request.idempotency_key}:action",
        security_id=request.public_security_id,
        target_session=request.evidence.target_session,
        reconciled_at=request.evidence.ingested_at,
        reconciliation_state=action_state,
        action_evidence_state=request.action_evidence_state,
        action_checkpoint_hash=canonical_hash(
            {
                "responseEnvelopeHash": (
                    request.evidence.raw_transport.response_envelope_hash
                ),
                "actionBindingHash": request.evidence.action_binding.binding_hash,
            }
        ),
        action_source_manifest_hash=_normalized_hash(
            request.evidence.action_binding.selected_action_set_hash
        ),
        selected_action_revision_hashes=request.selected_action_revision_hashes,
        raw_price_revision_manifest_hash=_normalized_hash(
            request.evidence.action_binding.raw_bar_set_hash
        ),
        adjusted_price_revision_manifest_hash=_normalized_hash(
            request.evidence.action_binding.adjusted_bar_set_hash
        ),
        adjustment_policy_hash=canonical_hash(
            {
                "bindingVersion": request.evidence.action_binding.version,
                "policyVersion": (
                    request.evidence.action_binding.adjustment_policy_version
                ),
            }
        ),
        source_records=(
            sources["YAHOO_RAW_BODY"],
            sources["YAHOO_RESPONSE_ENVELOPE"],
            sources["NORMALIZED_PRICE_ACTION"],
        ),
    )
    promotion_event = PriceValidationPromotionDecision(
        idempotency_key=f"{request.idempotency_key}:promotion",
        security_id=request.public_security_id,
        trading_date=request.evidence.target_session,
        adjustment_mode=PERSISTED_ADJUSTMENT_MODE,
        decided_at=request.evidence.ingested_at,
        reviewed_cutoff=request.calendar_evidence.completed_session_cutoff,
        decision=request.promotion_decision,
        validation_decision_hash=canonical_hash(
            {
                "futureEvidenceHash": request.evidence.evidence_hash,
                "calendarEvidenceHash": request.calendar_evidence.evidence_hash,
                "actionBindingHash": request.evidence.action_binding.binding_hash,
                "adtvObservationHash": request.evidence.adtv.observation_hash,
            }
        ),
        promotion_evidence_hash=request.promotion_evidence_hash,
        policy_hash=request.promotion_policy_hash,
        selected_prior_rows=(
            PriceRowBinding(
                row_id=core.target_prior_row.row_id,
                revision_number=core.target_prior_row.revision_number,
                source_record_id=core.target_prior_row.source_record_id,
            ),
        ),
        source_records=(
            sources["YAHOO_RAW_BODY"],
            sources["NORMALIZED_PRICE_ACTION"],
        ),
        new_validated_row=(
            PriceRowBinding(
                row_id=core.target_validated_row.row_id,
                revision_number=core.target_validated_row.revision_number,
                source_record_id=core.target_validated_row.source_record_id,
            )
            if core.target_validated_row is not None
            else None
        ),
    )
    repository = FakeValidationEvidenceRepository(sources.values())
    return tuple(
        repository.append(event)
        for event in (calendar_event, raw_event, action_event, promotion_event)
    )


def _receipt(
    request: FuturePriceEvidencePersistenceRequest,
    canonical_request_hash: str,
    core: _CoreWriteResult,
    audit_events: tuple[Any, ...],
    *,
    replayed: bool,
) -> FuturePriceEvidencePersistenceReceipt:
    body = {
        "contractVersion": FUTURE_PRICE_PERSISTENCE_VERSION,
        "idempotencyKey": request.idempotency_key,
        "canonicalRequestHash": canonical_request_hash,
        "refreshRunId": str(request.refresh_run_id),
        "refreshTaskId": str(request.refresh_task_id),
        "publicSecurityId": str(request.public_security_id),
        "symbol": request.evidence.symbol,
        "targetSession": request.evidence.target_session,
        "universeVersion": request.universe_version,
        "symbolPlanVersion": request.symbol_plan_version,
        "sourceRecordIds": {
            role: str(binding.source_record_id)
            for role, binding in sorted(core.source_bindings.items())
        },
        "priceRowIds": [row.row_id for row in core.price_rows],
        "targetPriorPriceRowId": core.target_prior_row.row_id,
        "targetValidatedPriceRowId": (
            core.target_validated_row.row_id
            if core.target_validated_row is not None
            else None
        ),
        "adtvMetricObservationId": core.adtv_metric_observation_id,
        "auditEventHashes": {
            event.event_type.value: event.event_hash for event in audit_events
        },
        "rawProviderValuesIncluded": False,
        "scoresOrRanksIncluded": False,
    }
    checkpoint_hash = canonical_hash(body)
    return FuturePriceEvidencePersistenceReceipt(
        contract_version=FUTURE_PRICE_PERSISTENCE_VERSION,
        idempotency_key=request.idempotency_key,
        canonical_request_hash=canonical_request_hash,
        refresh_run_id=request.refresh_run_id,
        refresh_task_id=request.refresh_task_id,
        public_security_id=request.public_security_id,
        symbol=request.evidence.symbol,
        target_session=request.evidence.target_session.isoformat(),
        universe_version=request.universe_version,
        symbol_plan_version=request.symbol_plan_version,
        source_record_ids=tuple(
            (role, binding.source_record_id)
            for role, binding in sorted(core.source_bindings.items())
        ),
        price_row_ids=tuple(row.row_id for row in core.price_rows),
        target_prior_price_row_id=core.target_prior_row.row_id,
        target_validated_price_row_id=(
            core.target_validated_row.row_id
            if core.target_validated_row is not None
            else None
        ),
        adtv_metric_observation_id=core.adtv_metric_observation_id,
        audit_event_hashes=tuple(
            (event.event_type.value, event.event_hash) for event in audit_events
        ),
        checkpoint_hash=checkpoint_hash,
        replayed=replayed,
    )


def _receipt_from_checkpoint(
    value: object,
    canonical_request_hash: str,
) -> FuturePriceEvidencePersistenceReceipt:
    payload = json.loads(value) if isinstance(value, str) else value
    if not isinstance(payload, dict):
        raise FuturePricePersistenceError("CHECKPOINT_VALUE_INVALID")
    if payload.get("canonicalRequestHash") != canonical_request_hash:
        raise FuturePricePersistenceConflictError(
            "Idempotency key is associated with different future price evidence"
        )
    return FuturePriceEvidencePersistenceReceipt(
        contract_version=payload["contractVersion"],
        idempotency_key=payload["idempotencyKey"],
        canonical_request_hash=payload["canonicalRequestHash"],
        refresh_run_id=UUID(payload["refreshRunId"]),
        refresh_task_id=UUID(payload["refreshTaskId"]),
        public_security_id=UUID(payload["publicSecurityId"]),
        symbol=payload["symbol"],
        target_session=payload["targetSession"],
        universe_version=payload["universeVersion"],
        symbol_plan_version=payload["symbolPlanVersion"],
        source_record_ids=tuple(
            (role, UUID(source_id))
            for role, source_id in sorted(payload["sourceRecordIds"].items())
        ),
        price_row_ids=tuple(payload["priceRowIds"]),
        target_prior_price_row_id=payload["targetPriorPriceRowId"],
        target_validated_price_row_id=payload["targetValidatedPriceRowId"],
        adtv_metric_observation_id=payload["adtvMetricObservationId"],
        audit_event_hashes=tuple(sorted(payload["auditEventHashes"].items())),
        checkpoint_hash=payload["checkpointHash"],
        replayed=True,
    )


def _binding_from_spec(spec: _SourceSpec, source_id: UUID) -> SourceRecordBinding:
    return SourceRecordBinding(
        source_record_id=source_id,
        content_hash=spec.content_hash,
        source_reference=spec.source_reference,
        schema_version=spec.schema_version,
        available_at=spec.available_at,
        ingested_at=spec.ingested_at,
        hash_semantics=spec.hash_semantics,
        storage_reference=spec.storage_reference,
    )


def _source_id(spec: _SourceSpec) -> UUID:
    return uuid5(
        NAMESPACE_URL,
        (
            f"{FUTURE_PRICE_PERSISTENCE_VERSION}:{spec.provider_id}:"
            f"{spec.source_reference}:{spec.content_hash}"
        ),
    )


def _stored_price(row: Mapping[str, Any]) -> _StoredPrice:
    return _StoredPrice(
        row_id=row["id"],
        revision_number=row["revisionNumber"],
        source_record_id=row["sourceRecordId"],
        quality_status=row["qualityStatus"],
    )


def _normalized_hash(value: str) -> str:
    candidate = value.removeprefix("sha256:").lower()
    if len(candidate) != 64 or any(character not in "0123456789abcdef" for character in candidate):
        raise ValueError("Evidence hash must be a SHA-256 value")
    return f"sha256:{candidate}"


def _require_text(value: str, label: str) -> None:
    if not value or value.strip() != value:
        raise ValueError(f"{label} must be non-empty and trimmed")


def _json(value: object) -> str:
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
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Decimal):
        return str(value)
    raise TypeError(f"Unsupported JSON value: {type(value).__name__}")


SQL_ADVISORY_LOCK = """
SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))
"""
SQL_SELECT_CHECKPOINT = """
SELECT checkpoint_value, checkpoint_hash
FROM analytics.refresh_checkpoint
WHERE refresh_run_id = %s AND checkpoint_key = %s
"""
SQL_SELECT_REFRESH_TASK = """
SELECT security_id
FROM analytics.refresh_task
WHERE id = %s AND refresh_run_id = %s
"""
SQL_INSERT_SOURCE_RECORD = """
INSERT INTO analytics.source_record (
    id, ingestion_batch_id, provider_id, provider_record_id,
    source_reference, source_uri, original_at, available_at, ingested_at,
    schema_version, revision_status, quality_status, content_hash,
    storage_reference
) VALUES (
    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
)
ON CONFLICT (provider_id, source_reference, content_hash) DO NOTHING
RETURNING id, content_hash, source_reference, schema_version,
          available_at, ingested_at, storage_reference
"""
SQL_SELECT_SOURCE_RECORD = """
SELECT id, content_hash, source_reference, schema_version,
       available_at, ingested_at, storage_reference
FROM analytics.source_record
WHERE provider_id = %s AND source_reference = %s AND content_hash = %s
"""
SQL_SELECT_EXACT_PRICE = """
SELECT id, revision_number
FROM analytics.daily_price_observation
WHERE security_id = %s AND trading_date = %s AND provider_id = %s
  AND adjustment_mode = %s AND source_record_id = %s AND quality_status = %s
"""
SQL_NEXT_PRICE_REVISION = """
SELECT COALESCE(MAX(revision_number), 0) + 1 AS revision_number
FROM analytics.daily_price_observation
WHERE security_id = %s AND trading_date = %s
  AND provider_id = %s AND adjustment_mode = %s
"""
SQL_INSERT_PRICE = """
INSERT INTO analytics.daily_price_observation (
    security_id, trading_date, open_price, high_price, low_price,
    close_price, adjusted_close, volume, provider_id, adjustment_mode,
    source_timezone, revision_number, source_record_id, available_at,
    ingested_at, normalization_version, quality_status
) VALUES (
    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
    'America/New_York', %s, %s, %s, %s, %s, %s
)
RETURNING id, revision_number
"""
SQL_INSERT_METRIC_DEFINITION = """
INSERT INTO analytics.metric_definition (
    metric_code, metric_version, value_type, unit_policy,
    description, definition_hash
) VALUES (%s, %s, 'NUMERIC', %s, 'Decision-time 20-session ADTV', %s)
ON CONFLICT (metric_code, metric_version) DO NOTHING
"""
SQL_SELECT_METRIC_DEFINITION = """
SELECT definition_hash
FROM analytics.metric_definition
WHERE metric_code = %s AND metric_version = %s
"""
SQL_SELECT_EXACT_METRIC = """
SELECT id
FROM analytics.metric_observation
WHERE security_id = %s AND metric_code = %s AND metric_version = %s
  AND observation_date = %s AND period_start IS NULL AND period_end IS NULL
  AND source_record_id = %s AND status = 'VALID'
"""
SQL_NEXT_METRIC_REVISION = """
SELECT COALESCE(MAX(revision_number), 0) + 1 AS revision_number
FROM analytics.metric_observation
WHERE security_id = %s AND metric_code = %s AND metric_version = %s
  AND observation_date = %s AND period_start IS NULL AND period_end IS NULL
"""
SQL_INSERT_METRIC = """
INSERT INTO analytics.metric_observation (
    security_id, metric_code, metric_version, observation_date,
    status, numeric_value, unit, currency, source_record_id,
    effective_at, available_at, ingested_at, revision_number
) VALUES (%s, %s, %s, %s, 'VALID', %s, %s, %s, %s, %s, %s, %s, %s)
RETURNING id
"""
SQL_INSERT_AUDIT_EVENT = """
INSERT INTO analytics.analytics_audit_event (
    id, event_type, entity_type, entity_id, actor_service,
    occurred_at, correlation_id, event_hash, detail
) VALUES (%s, %s, %s, %s, 'PYTHON_ANALYTICS', %s, %s, %s, %s::jsonb)
ON CONFLICT (event_hash) DO NOTHING
"""
SQL_NEXT_CHECKPOINT_SEQUENCE = """
SELECT COALESCE(MAX(sequence_number), 0) + 1 AS sequence_number
FROM analytics.refresh_checkpoint
WHERE refresh_run_id = %s
"""
SQL_INSERT_CHECKPOINT = """
INSERT INTO analytics.refresh_checkpoint (
    refresh_run_id, sequence_number, checkpoint_key,
    checkpoint_value, checkpoint_hash
) VALUES (%s, %s, %s, %s::jsonb, %s)
ON CONFLICT (refresh_run_id, checkpoint_key) DO NOTHING
RETURNING sequence_number
"""


def future_price_persistence_sql_contract() -> Mapping[str, str]:
    return {
        "advisoryLock": SQL_ADVISORY_LOCK,
        "selectCheckpoint": SQL_SELECT_CHECKPOINT,
        "selectRefreshTask": SQL_SELECT_REFRESH_TASK,
        "insertSourceRecord": SQL_INSERT_SOURCE_RECORD,
        "selectSourceRecord": SQL_SELECT_SOURCE_RECORD,
        "selectExactPrice": SQL_SELECT_EXACT_PRICE,
        "nextPriceRevision": SQL_NEXT_PRICE_REVISION,
        "insertPrice": SQL_INSERT_PRICE,
        "insertMetricDefinition": SQL_INSERT_METRIC_DEFINITION,
        "selectMetricDefinition": SQL_SELECT_METRIC_DEFINITION,
        "selectExactMetric": SQL_SELECT_EXACT_METRIC,
        "nextMetricRevision": SQL_NEXT_METRIC_REVISION,
        "insertMetric": SQL_INSERT_METRIC,
        "insertAuditEvent": SQL_INSERT_AUDIT_EVENT,
        "nextCheckpointSequence": SQL_NEXT_CHECKPOINT_SEQUENCE,
        "insertCheckpoint": SQL_INSERT_CHECKPOINT,
    }
