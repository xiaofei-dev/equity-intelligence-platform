"""Offline-only operator for current Fundamental Value assessment receipts.

The operator never opens a provider connection. It verifies the immutable
capture plans, manifests, journals, and response checkpoints before it asks the
V22 registrar and V26 repository to persist a newly reconstructed assessment.
Previously generated assessment JSON is deliberately ignored.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Protocol

from equity_analysis.fundamental_value.current_assessment_execution_v1 import (
    CurrentPriceRequestV1,
    decode_current_eodhd_price_response_v1,
)
from equity_analysis.fundamental_value.current_assessment_persistence_v1 import (
    PersistedCurrentAssessmentV1,
)
from equity_analysis.fundamental_value.current_assessment_v1 import (
    CurrentApplicabilitySealV1,
    CurrentPriceSelectionSealV1,
    build_current_fundamental_assessment_v1,
    create_current_completed_session_seal_v1,
    source_seal_from_bytes_v1,
)
from equity_analysis.fundamental_value.current_fundamentals_execution_v1 import (
    CurrentFundamentalsRequestV1,
    decode_current_fundamentals_response_v1,
)
from equity_analysis.fundamental_value.identity_projection_v2 import (
    IdentityProjectionV2,
    ProjectedIdentityMemberV2,
    validate_identity_projection_v2,
)
from equity_analysis.fundamental_value.prospective_company_quality_acquisition_v1 import (
    TransportResponse,
)

OPERATOR_VERSION = "FV-CURRENT-ASSESSMENT-OFFLINE-OPERATOR-v1.0.0"
TARGET_SYMBOLS = ("GOOG", "FOX", "MSFT")
_UPPER_HASH = re.compile(r"[0-9A-F]{64}\Z")
_LOWER_HASH = re.compile(r"sha256:[0-9a-f]{64}\Z")
_SAFE_RUN_ID = re.compile(r"[A-Z0-9][A-Z0-9._-]{0,127}\Z")


class CurrentAssessmentOperatorStop(RuntimeError):
    """Stable fail-closed operator error."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class CurrentEvidenceRegistrarV1(Protocol):
    def register(
        self,
        *,
        identity: ProjectedIdentityMemberV2,
        completed_session: Any,
        fundamentals_raw: bytes,
        fundamentals_payload: dict[str, Any],
        fundamentals_source: Any,
        price_raw: bytes,
        price_payload: dict[str, Any],
        price_source: Any,
        decision_cutoff: datetime,
    ) -> tuple[CurrentApplicabilitySealV1, CurrentPriceSelectionSealV1]: ...


class CurrentAssessmentPersisterV1(Protocol):
    def persist(self, value: Any) -> PersistedCurrentAssessmentV1: ...


@dataclass(frozen=True)
class CurrentAssessmentReceiptSetV1:
    identity_projection_content_hash: str
    fundamentals_run_id: str
    fundamentals_plan_hash: str
    price_run_id: str
    price_plan_hash: str

    def __post_init__(self) -> None:
        if (
            _LOWER_HASH.fullmatch(self.identity_projection_content_hash) is None
            or _UPPER_HASH.fullmatch(self.fundamentals_plan_hash) is None
            or _UPPER_HASH.fullmatch(self.price_plan_hash) is None
            or _SAFE_RUN_ID.fullmatch(self.fundamentals_run_id) is None
            or _SAFE_RUN_ID.fullmatch(self.price_run_id) is None
            or self.fundamentals_run_id == self.price_run_id
        ):
            raise CurrentAssessmentOperatorStop("RECEIPT_SET_INVALID")


@dataclass(frozen=True)
class CurrentAssessmentOperatorResultV1:
    operator_version: str
    decision_cutoff: datetime
    assessment_ids: tuple[str, ...]
    assessment_content_hashes: tuple[str, ...]


@dataclass(frozen=True)
class _CachedResponse:
    raw: bytes
    response: TransportResponse
    checkpoint_reference: str


def _upper_hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode("utf-8")
    ).hexdigest().upper()


def _read_object(path: Path, code: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CurrentAssessmentOperatorStop(code) from error
    if type(value) is not dict:
        raise CurrentAssessmentOperatorStop(code)
    return value


def _verify_content_hash(value: dict[str, Any], field: str, code: str) -> None:
    expected = value.get(field)
    body = {key: item for key, item in value.items() if key != field}
    if _UPPER_HASH.fullmatch(str(expected)) is None or expected != _upper_hash(body):
        raise CurrentAssessmentOperatorStop(code)


def _safe_run_root(storage_root: Path, run_id: str) -> Path:
    root = storage_root.resolve()
    run_root = (root / run_id).resolve()
    if root not in run_root.parents or not run_root.is_dir():
        raise CurrentAssessmentOperatorStop("RECEIPT_RUN_ROOT_INVALID")
    return run_root


def _load_run(
    storage_root: Path,
    *,
    run_id: str,
    plan_hash: str,
    projection_hash: str,
) -> tuple[dict[str, Any], dict[str, Any], Path]:
    run_root = _safe_run_root(storage_root, run_id)
    plan = _read_object(run_root / "plan.json", "RECEIPT_PLAN_INVALID")
    manifest = _read_object(run_root / "manifest.json", "RECEIPT_MANIFEST_INVALID")
    _verify_content_hash(plan, "planHash", "RECEIPT_PLAN_HASH_DRIFT")
    _verify_content_hash(manifest, "contentHash", "RECEIPT_MANIFEST_HASH_DRIFT")
    if (
        plan.get("runId") != run_id
        or plan.get("planHash") != plan_hash
        or plan.get("identityProjectionContentHash") != projection_hash
        or plan.get("retryLimit") != 0
        or manifest.get("status") != "COMPLETE"
        or manifest.get("runId") != run_id
        or manifest.get("planHash") != plan_hash
    ):
        raise CurrentAssessmentOperatorStop("RECEIPT_RUN_BINDING_DRIFT")
    requests = plan.get("requests")
    if type(requests) is not list or len(requests) != 3:
        raise CurrentAssessmentOperatorStop("RECEIPT_REQUEST_CARDINALITY_DRIFT")
    return plan, manifest, run_root


def _load_response(
    storage_root: Path,
    run_root: Path,
    *,
    run_id: str,
    symbol: str,
    request_identity: str,
    plan_hash: str,
) -> _CachedResponse:
    request_root = (
        run_root / "journals" / run_id / "requests" / symbol / request_identity
    ).resolve()
    if run_root.resolve() not in request_root.parents or not request_root.is_dir():
        raise CurrentAssessmentOperatorStop("RECEIPT_REQUEST_PATH_INVALID")
    event_paths = sorted(request_root.glob("[0-9]*.json"))
    if len(event_paths) != 2:
        raise CurrentAssessmentOperatorStop("RECEIPT_EVENT_CARDINALITY_DRIFT")
    events = tuple(
        _read_object(path, "RECEIPT_EVENT_INVALID") for path in event_paths
    )
    for event in events:
        event_hash = event.get("eventHash")
        body = {key: item for key, item in event.items() if key != "eventHash"}
        if event_hash != _upper_hash(body):
            raise CurrentAssessmentOperatorStop("RECEIPT_EVENT_HASH_DRIFT")
    if (
        tuple(event.get("sequence") for event in events) != (1, 2)
        or tuple(event.get("state") for event in events) != ("INTENT", "COMPLETED")
        or any(
            event.get("runId") != run_id
            or event.get("symbol") != symbol
            or event.get("requestIdentity") != request_identity
            for event in events
        )
    ):
        raise CurrentAssessmentOperatorStop("RECEIPT_EVENT_GRAMMAR_DRIFT")
    intent = events[0].get("detail")
    completed = events[1].get("detail")
    if (
        type(intent) is not dict
        or type(completed) is not dict
        or intent.get("attemptId") != completed.get("attemptId")
        or completed.get("status") != 200
        or type(completed.get("headers")) is not dict
    ):
        raise CurrentAssessmentOperatorStop("RECEIPT_COMPLETION_DRIFT")
    checkpoint = Path(str(completed.get("responseCheckpointPath"))).resolve()
    storage = storage_root.resolve()
    if storage not in checkpoint.parents or not checkpoint.is_file():
        raise CurrentAssessmentOperatorStop("RECEIPT_CHECKPOINT_PATH_INVALID")
    raw = checkpoint.read_bytes()
    response_hash = hashlib.sha256(raw).hexdigest().upper()
    if (
        completed.get("responseContentHash") != response_hash
        or checkpoint.name != f"{response_hash}.bin"
    ):
        raise CurrentAssessmentOperatorStop("RECEIPT_CHECKPOINT_HASH_DRIFT")
    preflight_paths = sorted((run_root / "journals" / run_id / "run").glob("*-PREFLIGHT.json"))
    if len(preflight_paths) != 1:
        raise CurrentAssessmentOperatorStop("RECEIPT_PREFLIGHT_CARDINALITY_DRIFT")
    preflight = _read_object(preflight_paths[0], "RECEIPT_PREFLIGHT_INVALID")
    preflight_body = {
        key: item for key, item in preflight.items() if key != "eventHash"
    }
    if (
        preflight.get("eventHash") != _upper_hash(preflight_body)
        or preflight.get("state") != "PREFLIGHT"
        or preflight.get("runId") != run_id
        or preflight.get("detail", {}).get("sliceId") != plan_hash
    ):
        raise CurrentAssessmentOperatorStop("RECEIPT_PREFLIGHT_DRIFT")
    return _CachedResponse(
        raw=raw,
        response=TransportResponse(
            status_code=200,
            headers=tuple(
                sorted((str(key).lower(), str(item)) for key, item in completed["headers"].items())
            ),
            body=raw,
        ),
        checkpoint_reference=str(checkpoint.relative_to(storage)),
    )


def _requests_by_symbol(plan: dict[str, Any], code: str) -> dict[str, dict[str, Any]]:
    requests = plan["requests"]
    try:
        result = {str(item["symbol"]): item for item in requests if type(item) is dict}
    except KeyError as error:
        raise CurrentAssessmentOperatorStop(code) from error
    if tuple(result) != TARGET_SYMBOLS or len(result) != len(requests):
        raise CurrentAssessmentOperatorStop(code)
    return result


def replay_and_persist_current_assessments_v1(
    *,
    storage_root: Path,
    receipt_set: CurrentAssessmentReceiptSetV1,
    projection: IdentityProjectionV2,
    decision_cutoff: datetime,
    evidence_registrar: CurrentEvidenceRegistrarV1,
    assessment_persister: CurrentAssessmentPersisterV1,
) -> CurrentAssessmentOperatorResultV1:
    """Reconstruct and persist the three current assessments without network I/O."""

    validate_identity_projection_v2(projection)
    if (
        projection.content_hash != receipt_set.identity_projection_content_hash
        or tuple(member.ticker for member in projection.members) != TARGET_SYMBOLS
        or decision_cutoff.tzinfo is None
        or decision_cutoff.utcoffset() is None
        or decision_cutoff.microsecond
    ):
        raise CurrentAssessmentOperatorStop("OPERATOR_INPUT_BINDING_INVALID")
    decision_cutoff = decision_cutoff.astimezone(UTC)
    fundamentals_plan, fundamentals_manifest, fundamentals_root = _load_run(
        storage_root,
        run_id=receipt_set.fundamentals_run_id,
        plan_hash=receipt_set.fundamentals_plan_hash,
        projection_hash=projection.content_hash,
    )
    price_plan, price_manifest, price_root = _load_run(
        storage_root,
        run_id=receipt_set.price_run_id,
        plan_hash=receipt_set.price_plan_hash,
        projection_hash=projection.content_hash,
    )
    if (
        fundamentals_plan.get("executionVersion")
        != "FV-CURRENT-FUNDAMENTALS-EXECUTION-v1.0.0"
        or fundamentals_plan.get("physicalRequestCeiling") != 3
        or fundamentals_plan.get("configuredWeightCeiling") != 30
        or fundamentals_manifest.get("completedRequests") != 3
        or fundamentals_manifest.get("configuredWeightCompleted") != 30
        or price_plan.get("executionVersion")
        != "FV-CURRENT-ASSESSMENT-EXECUTION-v1.0.0"
        or price_plan.get("priceProvider") != "EODHD_EOD"
        or price_plan.get("physicalRequestCeiling") != 3
        or price_manifest.get("priceProvider") != "EODHD_EOD"
        or price_manifest.get("physicalRequests") != 3
    ):
        raise CurrentAssessmentOperatorStop("RECEIPT_EXECUTION_CONTRACT_DRIFT")
    fundamentals_requests = _requests_by_symbol(
        fundamentals_plan, "FUNDAMENTALS_REQUEST_SET_DRIFT"
    )
    price_requests = _requests_by_symbol(price_plan, "PRICE_REQUEST_SET_DRIFT")
    identities = {member.ticker: member for member in projection.members}
    prepared: dict[str, dict[str, Any]] = {}
    session_completed_at: dict[tuple[str, date], datetime] = {}
    fundamentals_hashes: list[str] = []
    for symbol in TARGET_SYMBOLS:
        identity = identities[symbol]
        fundamental_wire = fundamentals_requests[symbol]
        price_wire = price_requests[symbol]
        if (
            fundamental_wire.get("security_id") != identity.security_id
            or price_wire.get("security_id") != identity.security_id
            or price_wire.get("mic") != identity.mic
        ):
            raise CurrentAssessmentOperatorStop("RECEIPT_IDENTITY_DRIFT")
        fundamental_cached = _load_response(
            storage_root,
            fundamentals_root,
            run_id=receipt_set.fundamentals_run_id,
            symbol=symbol,
            request_identity=str(fundamental_wire["request_identity"]),
            plan_hash=receipt_set.fundamentals_plan_hash,
        )
        fundamental_request = CurrentFundamentalsRequestV1(
            ordinal=int(fundamental_wire["ordinal"]),
            symbol=symbol,
            security_id=identity.security_id,
            endpoint_path=str(fundamental_wire["endpoint_path"]),
            request_identity=str(fundamental_wire["request_identity"]),
            configured_weight=int(fundamental_wire["configured_weight"]),
        )
        capture = decode_current_fundamentals_response_v1(
            fundamental_request,
            fundamental_cached.response,
            plan_hash=receipt_set.fundamentals_plan_hash,
            checkpoint_reference=fundamental_cached.checkpoint_reference,
            ingested_at=decision_cutoff,
        )
        fundamentals_hashes.append(capture.source_seal.file_sha256)
        price_cached = _load_response(
            storage_root,
            price_root,
            run_id=receipt_set.price_run_id,
            symbol=symbol,
            request_identity=str(price_wire["request_identity"]),
            plan_hash=receipt_set.price_plan_hash,
        )
        price_request = CurrentPriceRequestV1(
            ordinal=int(price_wire["ordinal"]),
            symbol=symbol,
            security_id=identity.security_id,
            company_id=identity.company_id,
            instrument_id=identity.instrument_id,
            share_class_id=identity.share_class_id,
            listing_id=identity.listing_id,
            ticker_assignment_id=identity.ticker_assignment_id,
            mic=identity.mic,
            currency=identity.currency,
            endpoint_path=str(price_wire["endpoint_path"]),
            request_identity=str(price_wire["request_identity"]),
        )
        price_payload, price_available_at = decode_current_eodhd_price_response_v1(
            price_request, price_cached.response
        )
        price_source = source_seal_from_bytes_v1(
            provider_code="EODHD",
            schema_version=str(price_payload["schemaVersion"]),
            source_reference=price_cached.checkpoint_reference,
            raw=price_cached.raw,
            canonical_payload=price_payload,
            available_at=price_available_at,
            retrieved_at=None,
            ingested_at=decision_cutoff,
            source_revision=1,
            adapter_version="FV-CURRENT-EODHD-PRICE-ADAPTER-v1.0.0",
            normalization_version=str(price_payload["schemaVersion"]),
            freshness_policy_version="FV-CURRENT-PRICE-5D-v1.0.0",
            request_identity=price_request.request_identity,
            plan_hash=receipt_set.price_plan_hash,
            checkpoint_reference=price_cached.checkpoint_reference,
        )
        price_date = max(
            date.fromisoformat(str(row["tradingDate"]))
            for row in price_payload["bars"]
        )
        key = (identity.mic, price_date)
        session_completed_at[key] = max(
            price_available_at, session_completed_at.get(key, price_available_at)
        )
        prepared[symbol] = {
            "identity": identity,
            "fundamentals": capture,
            "price_raw": price_cached.raw,
            "price_payload": price_payload,
            "price_source": price_source,
            "price_date": price_date,
        }
    if fundamentals_manifest.get("sourceFileSha256") != fundamentals_hashes:
        raise CurrentAssessmentOperatorStop("FUNDAMENTALS_MANIFEST_SOURCE_DRIFT")

    persisted: list[PersistedCurrentAssessmentV1] = []
    for symbol in TARGET_SYMBOLS:
        item = prepared[symbol]
        identity = item["identity"]
        capture = item["fundamentals"]
        completed_session = create_current_completed_session_seal_v1(
            session_date=item["price_date"],
            completed_at=session_completed_at[(identity.mic, item["price_date"])],
            mic=identity.mic,
        )
        applicability, price_selection = evidence_registrar.register(
            identity=identity,
            completed_session=completed_session,
            fundamentals_raw=capture.raw,
            fundamentals_payload=capture.payload,
            fundamentals_source=capture.source_seal,
            price_raw=item["price_raw"],
            price_payload=item["price_payload"],
            price_source=item["price_source"],
            decision_cutoff=decision_cutoff,
        )
        assessment = build_current_fundamental_assessment_v1(
            identity=identity,
            completed_session=completed_session,
            applicability_seal=applicability,
            price_selection_seal=price_selection,
            fundamentals_raw=capture.raw,
            fundamentals_payload=capture.payload,
            fundamentals_source=capture.source_seal,
            price_raw=item["price_raw"],
            price_payload=item["price_payload"],
            price_source=item["price_source"],
            decision_cutoff=decision_cutoff,
        )
        persisted.append(assessment_persister.persist(assessment))
    return CurrentAssessmentOperatorResultV1(
        operator_version=OPERATOR_VERSION,
        decision_cutoff=decision_cutoff,
        assessment_ids=tuple(item.assessment_id for item in persisted),
        assessment_content_hashes=tuple(
            item.assessment_content_hash for item in persisted
        ),
    )


__all__ = [
    "CurrentAssessmentOperatorResultV1",
    "CurrentAssessmentOperatorStop",
    "CurrentAssessmentReceiptSetV1",
    "OPERATOR_VERSION",
    "replay_and_persist_current_assessments_v1",
]
