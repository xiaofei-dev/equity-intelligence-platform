"""Bounded EODHD fundamentals capture for current Fundamental Value assessment."""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Protocol

from equity_analysis.fundamental_value.current_assessment_v1 import (
    CurrentSourceSealV1,
    source_seal_from_bytes_v1,
)
from equity_analysis.fundamental_value.identity_projection_v2 import (
    ProjectedIdentityMemberV2,
)
from equity_analysis.fundamental_value.prospective_company_quality_acquisition_v1 import (
    ProviderWireRequest,
    TransportResponse,
)
from equity_analysis.fundamental_value.prospective_company_quality_http_transport_v1 import (
    StdlibAcquisitionHttpTransport,
)
from equity_analysis.provider_validation.execution_safety import (
    ExecutionLease,
    PhysicalRequestJournal,
)

EXECUTION_VERSION = "FV-CURRENT-FUNDAMENTALS-EXECUTION-v1.0.0"
SCHEMA_VERSION = "EODHD-CURRENT-FUNDAMENTALS-CAPTURE-v1.0.0"
TARGET_SYMBOLS = ("GOOG", "FOX", "MSFT")
PHYSICAL_REQUEST_CEILING = 3
WEIGHT_CEILING = 30
RETRY_LIMIT = 0
_UPPER_HASH = re.compile(r"[0-9A-F]{64}\Z")
_LOWER_HASH = re.compile(r"sha256:[0-9a-f]{64}\Z")
_SAFE_RUN_ID = re.compile(r"[A-Z0-9][A-Z0-9._-]{0,127}\Z")
_UUID = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-"
    r"[89ab][0-9a-f]{3}-[0-9a-f]{12}\Z"
)


class CurrentFundamentalsExecutionStop(RuntimeError):
    """Fail-closed current-fundamentals transport stop."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class EodhdTransportV1(Protocol):
    def send(self, request: ProviderWireRequest) -> TransportResponse: ...


@dataclass(frozen=True)
class CurrentFundamentalsRequestV1:
    ordinal: int
    symbol: str
    security_id: str
    endpoint_path: str
    request_identity: str
    configured_weight: int = 10


@dataclass(frozen=True)
class CurrentFundamentalsPlanV1:
    run_id: str
    preflight_sealed_at: datetime
    identity_projection_content_hash: str
    requests: tuple[CurrentFundamentalsRequestV1, ...]
    plan_hash: str
    network_authorized: bool = False
    retry_limit: int = RETRY_LIMIT
    physical_request_ceiling: int = PHYSICAL_REQUEST_CEILING
    configured_weight_ceiling: int = WEIGHT_CEILING


@dataclass(frozen=True)
class CapturedFundamentalsV1:
    symbol: str
    raw: bytes
    payload: dict[str, Any]
    source_seal: CurrentSourceSealV1


@dataclass(frozen=True)
class CurrentFundamentalsRunV1:
    status: str
    run_id: str
    plan_hash: str
    captures: tuple[CapturedFundamentalsV1, ...]
    physical_requests: int
    replayed_requests: int


def _canonical(value: object) -> object:
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None or value.microsecond:
            raise CurrentFundamentalsExecutionStop("TIMESTAMP_BOUNDARY_INVALID")
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if isinstance(value, tuple):
        return [_canonical(item) for item in value]
    if isinstance(value, list):
        return [_canonical(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _canonical(item) for key, item in sorted(value.items())}
    if hasattr(value, "__dataclass_fields__"):
        return {key: _canonical(getattr(value, key)) for key in value.__dataclass_fields__}
    return value


def _hash(value: object) -> str:
    raw = json.dumps(
        _canonical(value), sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest().upper()


def _immutable_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(_canonical(value), indent=2, sort_keys=True) + "\n").encode("utf-8")
    if path.exists():
        if path.read_bytes() != raw:
            raise CurrentFundamentalsExecutionStop("IMMUTABLE_FILE_CONFLICT")
        return
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _plan_body(value: CurrentFundamentalsPlanV1) -> dict[str, Any]:
    return {
        "executionVersion": EXECUTION_VERSION,
        "runId": value.run_id,
        "preflightSealedAt": value.preflight_sealed_at,
        "identityProjectionContentHash": value.identity_projection_content_hash,
        "requests": value.requests,
        "networkAuthorized": value.network_authorized,
        "retryLimit": value.retry_limit,
        "physicalRequestCeiling": value.physical_request_ceiling,
        "configuredWeightCeiling": value.configured_weight_ceiling,
    }


def validate_current_fundamentals_plan_v1(value: CurrentFundamentalsPlanV1) -> None:
    if type(value) is not CurrentFundamentalsPlanV1:
        raise CurrentFundamentalsExecutionStop("FUNDAMENTALS_PLAN_TYPE_INVALID")
    if _SAFE_RUN_ID.fullmatch(value.run_id) is None:
        raise CurrentFundamentalsExecutionStop("FUNDAMENTALS_RUN_ID_INVALID")
    if _LOWER_HASH.fullmatch(value.identity_projection_content_hash) is None:
        raise CurrentFundamentalsExecutionStop("FUNDAMENTALS_PROJECTION_HASH_INVALID")
    if type(value.requests) is not tuple or len(value.requests) != 3:
        raise CurrentFundamentalsExecutionStop("FUNDAMENTALS_REQUEST_COUNT_DRIFT")
    if tuple(item.symbol for item in value.requests) != TARGET_SYMBOLS:
        raise CurrentFundamentalsExecutionStop("FUNDAMENTALS_SYMBOL_SET_DRIFT")
    if tuple(item.ordinal for item in value.requests) != (1, 2, 3):
        raise CurrentFundamentalsExecutionStop("FUNDAMENTALS_ORDER_DRIFT")
    if value.retry_limit != 0 or value.physical_request_ceiling != 3:
        raise CurrentFundamentalsExecutionStop("FUNDAMENTALS_PHYSICAL_BUDGET_DRIFT")
    if value.configured_weight_ceiling != 30:
        raise CurrentFundamentalsExecutionStop("FUNDAMENTALS_WEIGHT_BUDGET_DRIFT")
    if len({item.request_identity for item in value.requests}) != 3:
        raise CurrentFundamentalsExecutionStop("FUNDAMENTALS_REQUEST_ID_DUPLICATE")
    for request in value.requests:
        if (
            request.endpoint_path != f"/api/fundamentals/{request.symbol}.US?fmt=json"
            or request.configured_weight != 10
            or _UUID.fullmatch(request.security_id) is None
            or _UPPER_HASH.fullmatch(request.request_identity) is None
        ):
            raise CurrentFundamentalsExecutionStop("FUNDAMENTALS_REQUEST_SCOPE_DRIFT")
        expected = _hash(
            {
                "executionVersion": EXECUTION_VERSION,
                "runId": value.run_id,
                "ordinal": request.ordinal,
                "symbol": request.symbol,
                "securityId": request.security_id,
                "endpointPath": request.endpoint_path,
                "preflightSealedAt": value.preflight_sealed_at,
                "configuredWeight": 10,
            }
        )
        if request.request_identity != expected:
            raise CurrentFundamentalsExecutionStop("FUNDAMENTALS_REQUEST_ID_DRIFT")
    if value.plan_hash != _hash(_plan_body(value)):
        raise CurrentFundamentalsExecutionStop("FUNDAMENTALS_PLAN_HASH_DRIFT")


def build_current_fundamentals_plan_v1(
    *,
    run_id: str,
    preflight_sealed_at: datetime,
    identity_projection_content_hash: str,
    identities: tuple[ProjectedIdentityMemberV2, ...],
    network_authorized: bool,
) -> CurrentFundamentalsPlanV1:
    if (
        type(run_id) is not str
        or _SAFE_RUN_ID.fullmatch(run_id) is None
        or type(identities) is not tuple
        or tuple(item.ticker for item in identities) != TARGET_SYMBOLS
        or type(network_authorized) is not bool
    ):
        raise CurrentFundamentalsExecutionStop("FUNDAMENTALS_PLAN_INPUT_INVALID")
    if preflight_sealed_at.tzinfo is None or preflight_sealed_at.utcoffset() is None:
        raise CurrentFundamentalsExecutionStop("PREFLIGHT_SEALED_AT_TIMEZONE_REQUIRED")
    sealed_at = preflight_sealed_at.astimezone(UTC)
    if sealed_at.microsecond:
        raise CurrentFundamentalsExecutionStop("PREFLIGHT_SEALED_AT_WHOLE_SECOND_REQUIRED")
    requests: list[CurrentFundamentalsRequestV1] = []
    for ordinal, identity in enumerate(identities, start=1):
        path = f"/api/fundamentals/{identity.ticker}.US?fmt=json"
        request_identity = _hash(
            {
                "executionVersion": EXECUTION_VERSION,
                "runId": run_id,
                "ordinal": ordinal,
                "symbol": identity.ticker,
                "securityId": identity.security_id,
                "endpointPath": path,
                "preflightSealedAt": sealed_at,
                "configuredWeight": 10,
            }
        )
        requests.append(
            CurrentFundamentalsRequestV1(
                ordinal,
                identity.ticker,
                identity.security_id,
                path,
                request_identity,
            )
        )
    provisional = CurrentFundamentalsPlanV1(
        run_id,
        sealed_at,
        identity_projection_content_hash,
        tuple(requests),
        "",
        network_authorized,
    )
    plan = CurrentFundamentalsPlanV1(
        **{**provisional.__dict__, "plan_hash": _hash(_plan_body(provisional))}
    )
    validate_current_fundamentals_plan_v1(plan)
    return plan


def _response_date(response: TransportResponse) -> datetime:
    values = tuple(value for name, value in response.headers if name.lower() == "date")
    if len(values) != 1:
        raise CurrentFundamentalsExecutionStop("EODHD_RESPONSE_DATE_HEADER_INVALID")
    try:
        result = parsedate_to_datetime(values[0]).astimezone(UTC)
    except (TypeError, ValueError, OverflowError) as error:
        raise CurrentFundamentalsExecutionStop("EODHD_RESPONSE_DATE_HEADER_INVALID") from error
    if result.microsecond:
        raise CurrentFundamentalsExecutionStop("EODHD_RESPONSE_DATE_FRACTIONAL")
    return result


def _decode_capture(
    request: CurrentFundamentalsRequestV1,
    response: TransportResponse,
    *,
    plan_hash: str,
    checkpoint_reference: str,
    ingested_at: datetime,
) -> CapturedFundamentalsV1:
    if response.status_code != 200:
        raise CurrentFundamentalsExecutionStop(f"EODHD_HTTP_{response.status_code}")
    try:
        payload = json.loads(response.body)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CurrentFundamentalsExecutionStop("EODHD_RESPONSE_JSON_INVALID") from error
    if type(payload) is not dict:
        raise CurrentFundamentalsExecutionStop("EODHD_RESPONSE_OBJECT_REQUIRED")
    general = payload.get("General")
    financials = payload.get("Financials")
    if (
        type(general) is not dict
        or general.get("Code") != request.symbol
        or general.get("CurrencyCode") != "USD"
        or type(financials) is not dict
        or not financials
    ):
        raise CurrentFundamentalsExecutionStop("EODHD_RESPONSE_SEMANTIC_INVALID")
    observed_at = _response_date(response)
    source = source_seal_from_bytes_v1(
        provider_code="EODHD",
        schema_version=SCHEMA_VERSION,
        source_reference=f"eodhd:fundamentals:{request.symbol}.US:response",
        raw=response.body,
        canonical_payload=payload,
        available_at=observed_at,
        retrieved_at=None,
        ingested_at=ingested_at,
        source_revision=1,
        adapter_version="EODHD-CURRENT-FUNDAMENTALS-ADAPTER-v1.0.0",
        normalization_version="EODHD-CURRENT-FUNDAMENTALS-NORMALIZATION-v1.0.0",
        freshness_policy_version="FV-CURRENT-FUNDAMENTALS-180D-v1.0.0",
        request_identity=request.request_identity,
        plan_hash=plan_hash,
        checkpoint_reference=checkpoint_reference,
    )
    return CapturedFundamentalsV1(request.symbol, response.body, payload, source)


def decode_current_fundamentals_response_v1(
    request: CurrentFundamentalsRequestV1,
    response: TransportResponse,
    *,
    plan_hash: str,
    checkpoint_reference: str,
    ingested_at: datetime,
) -> CapturedFundamentalsV1:
    """Decode one already-captured fundamentals response without transport access."""

    return _decode_capture(
        request,
        response,
        plan_hash=plan_hash,
        checkpoint_reference=checkpoint_reference,
        ingested_at=ingested_at,
    )


def _replay_response(response: object) -> TransportResponse:
    if not hasattr(response, "read"):
        raise CurrentFundamentalsExecutionStop("EODHD_REPLAY_INVALID")
    return TransportResponse(
        int(response.status),
        tuple(sorted((str(k).lower(), str(v)) for k, v in response.headers.items())),
        response.read(),
    )


def execute_current_fundamentals_v1(
    plan: CurrentFundamentalsPlanV1,
    *,
    storage_root: Path,
    transport: EodhdTransportV1 | None = None,
    sealed_at: datetime | None = None,
) -> CurrentFundamentalsRunV1:
    """Execute or replay the exact three-call fundamentals plan."""

    validate_current_fundamentals_plan_v1(plan)
    if sealed_at is not None and (
        sealed_at.tzinfo is None or sealed_at.utcoffset() is None
    ):
        raise CurrentFundamentalsExecutionStop("SEALED_AT_TIMEZONE_REQUIRED")
    ingestion_time = (
        datetime.now(UTC).replace(microsecond=0)
        if sealed_at is None
        else sealed_at.astimezone(UTC)
    )
    if ingestion_time.microsecond:
        raise CurrentFundamentalsExecutionStop("SEALED_AT_WHOLE_SECOND_REQUIRED")
    root = storage_root.resolve() / plan.run_id
    _immutable_json(root / "plan.json", {**_plan_body(plan), "planHash": plan.plan_hash})
    journal = PhysicalRequestJournal(root / "journals", plan.run_id)
    preflight = {
        "sliceId": plan.plan_hash,
        "symbols": list(TARGET_SYMBOLS),
        "executionVersion": EXECUTION_VERSION,
        "networkAuthorized": plan.network_authorized,
        "retryLimit": 0,
        "physicalRequestCeiling": 3,
        "configuredWeightCeiling": 30,
    }
    if (root / "journals" / plan.run_id / "run").exists():
        try:
            journal.resume_preflight(preflight)
        except RuntimeError as error:
            raise CurrentFundamentalsExecutionStop(str(error)) from error
    else:
        journal.preflight(preflight)
    resolved = transport or StdlibAcquisitionHttpTransport()
    captures: list[CapturedFundamentalsV1] = []
    physical = 0
    replayed = 0
    with ExecutionLease(root / ".execution.lock", plan.run_id):
        for request in plan.requests:
            state, replay = journal.resume(request.symbol, request.request_identity)
            if state == "UNKNOWN":
                raise CurrentFundamentalsExecutionStop("UNKNOWN_TRANSPORT_OUTCOME")
            if state == "SKIP":
                assert replay is not None
                response = _replay_response(replay)
                replayed += 1
            else:
                if not plan.network_authorized:
                    raise CurrentFundamentalsExecutionStop("NETWORK_NOT_AUTHORIZED")
                if physical >= 3:
                    raise CurrentFundamentalsExecutionStop("PHYSICAL_REQUEST_CEILING_EXCEEDED")
                attempt = journal.next_attempt_id(request.symbol, request.request_identity)
                journal.intent(
                    symbol=request.symbol,
                    request_identity=request.request_identity,
                    endpoint_category="fundamentals",
                    attempt_id=attempt,
                    configured_weight=10,
                )
                started = time.perf_counter()
                try:
                    response = resolved.send(
                        ProviderWireRequest(
                            request.request_identity,
                            "EODHD",
                            "GET",
                            request.endpoint_path,
                            (("accept", "application/json"),),
                            None,
                            None,
                        )
                    )
                    physical += 1
                    journal.completed(
                        symbol=request.symbol,
                        request_identity=request.request_identity,
                        endpoint_category="fundamentals",
                        attempt_id=attempt,
                        configured_weight=10,
                        duration_ms=max(0, round((time.perf_counter() - started) * 1000)),
                        status=response.status_code,
                        headers=dict(response.headers),
                        body=response.body,
                    )
                except BaseException as error:
                    raise CurrentFundamentalsExecutionStop("UNKNOWN_TRANSPORT_OUTCOME") from error
            response_hash = hashlib.sha256(response.body).hexdigest().upper()
            checkpoint_reference = str(
                (
                    root
                    / "journals"
                    / plan.run_id
                    / "requests"
                    / request.symbol
                    / request.request_identity
                    / "responses"
                    / f"{response_hash}.bin"
                ).relative_to(storage_root.resolve())
            )
            capture = _decode_capture(
                request,
                response,
                plan_hash=plan.plan_hash,
                checkpoint_reference=checkpoint_reference,
                ingested_at=ingestion_time,
            )
            if not (
                plan.preflight_sealed_at - timedelta(minutes=2)
                <= capture.source_seal.ingested_at
                <= plan.preflight_sealed_at + timedelta(minutes=15)
            ):
                raise CurrentFundamentalsExecutionStop("EODHD_RESPONSE_DATE_OUTSIDE_PLAN")
            captures.append(capture)
    manifest_body = {
        "executionVersion": EXECUTION_VERSION,
        "status": "COMPLETE",
        "runId": plan.run_id,
        "planHash": plan.plan_hash,
        "symbols": list(TARGET_SYMBOLS),
        "sourceFileSha256": [item.source_seal.file_sha256 for item in captures],
        "sourceContentHashes": [item.source_seal.content_hash for item in captures],
        "completedRequests": 3,
        "configuredWeightCompleted": 30,
        "retryLimit": 0,
        "networkAuthorized": plan.network_authorized,
    }
    manifest = {**manifest_body, "contentHash": _hash(manifest_body)}
    _immutable_json(root / "manifest.json", manifest)
    journal.finalize("COMPLETE", manifest)
    return CurrentFundamentalsRunV1(
        "COMPLETE", plan.run_id, plan.plan_hash, tuple(captures), physical, replayed
    )


__all__ = [
    "EXECUTION_VERSION",
    "CapturedFundamentalsV1",
    "CurrentFundamentalsExecutionStop",
    "CurrentFundamentalsPlanV1",
    "CurrentFundamentalsRequestV1",
    "CurrentFundamentalsRunV1",
    "build_current_fundamentals_plan_v1",
    "decode_current_fundamentals_response_v1",
    "execute_current_fundamentals_v1",
    "validate_current_fundamentals_plan_v1",
]
