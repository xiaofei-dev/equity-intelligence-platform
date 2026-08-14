"""Offline-tested execution boundary for the frozen OpenFIGI v1.5 US-composite diagnostic.

The diagnostic contract owns the provider request bodies and response semantics.
This module owns only the two-request transport safety boundary: an independently
sealed phase authorization, an execution lease, immutable manifests, append-only
journals, private response checkpoints, pacing, and exact replay.  It deliberately
does not expose raw response bytes through its Git-safe summary.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Protocol

from equity_analysis.fundamental_value.openfigi_us_composite_diagnostic_v15 import (
    ACCEPTED_DECISION_CODE,
    FROZEN_PLAN_CONTENT_HASH,
    LOGICAL_JOB_COUNT,
    OPERATING_MIC_BINDING_STATUS,
    PHYSICAL_REQUEST_COUNT,
    PROVIDER_ORIGIN,
    REJECTED_DECISION_CODE,
    RETRY_LIMIT,
    UsCompositeAcceptance,
    UsCompositeDiagnosticStop,
    UsCompositePlan,
    UsCompositeReview,
    build_us_composite_review_v1,
    build_us_composite_wire_requests_v1,
    canonical_hash,
    seal_us_composite_acceptance_v1,
    validate_us_composite_acceptance_v1,
    validate_us_composite_plan_v1,
)
from equity_analysis.fundamental_value.prospective_company_quality_acquisition_v1 import (
    AcquisitionStop,
    ProviderWireRequest,
    TransportResponse,
    validate_private_storage_root,
)
from equity_analysis.fundamental_value.prospective_company_quality_http_transport_v1 import (
    StdlibAcquisitionHttpTransport,
)
from equity_analysis.provider_validation.execution_safety import ExecutionLease

EXECUTION_CONTRACT_VERSION = "FV-STAGE8C-OPENFIGI-US-COMPOSITE-EXECUTION-v1.0.0"
AUTHORIZATION_VERSION = "FV-STAGE8C-OPENFIGI-US-COMPOSITE-AUTHORIZATION-v1.0.0"
MANIFEST_VERSION = "FV-STAGE8C-OPENFIGI-US-COMPOSITE-MANIFEST-v1.0.0"
JOURNAL_VERSION = "FV-STAGE8C-OPENFIGI-US-COMPOSITE-JOURNAL-v1.0.0"
SUMMARY_VERSION = "FV-STAGE8C-OPENFIGI-US-COMPOSITE-SUMMARY-v1.0.0"
AUTHORITY_BASIS = "USER_EXPLICIT_BROAD_FUTURE_PROVIDER_AUTHORIZATION_2026_08_02"
CONTROLLER_AUTHORITY_VERSION = "FV-STAGE8C-OPENFIGI-US-COMPOSITE-CONTROLLER-AUTHORITY-v1.0.0"
CONTROLLER_AUTHORITY_CONTENT_HASH = (
    "E7FDA19F3323AAFFBB05C9CD992768A6DF889F8933C301E95C14155C8A028486"
)
PREDECESSOR_US_COMPOSITE_EXECUTION_RUN_ID = "20260802T141600Z-STAGE8C-OPENFIGI-V14-001"
OPENFIGI_PACING_INTERVAL_MICROS = 2_400_000
OPENFIGI_PACING_VERSION = "OPENFIGI-UNAUTHENTICATED-25RPM-v1.0.0"
MAX_RESPONSE_BODY_BYTES = 4 * 1024 * 1024

_RUN_ID = re.compile(r"[A-Z0-9][A-Z0-9._-]{7,127}\Z")
_UPPER_SHA256 = re.compile(r"[0-9A-F]{64}\Z")
_EVENT_NAME = re.compile(r"(?P<sequence>\d{3})-(?P<state>INTENT|COMPLETED|FAILED)\.json\Z")
_CHECKPOINT_NAME = re.compile(r"[0-9A-F]{64}\.bin\Z")


class UsCompositeExecutionStop(RuntimeError):
    """Fail-closed execution stop with a stable code."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class UsCompositePhaseAuthorization:
    authorization_version: str
    run_id: str
    plan_content_hash: str
    authority_basis: str
    controller_authority_content_hash: str
    physical_request_count: int
    logical_job_count: int
    retry_limit: int
    test_only: bool = False
    network_authorized: bool = False
    content_hash: str = ""


@dataclass(frozen=True)
class UsCompositeExecutionResult:
    run_id: str
    plan_content_hash: str
    authorization_content_hash: str
    physical_request_count: int
    logical_job_count: int
    new_physical_request_count: int
    replayed_physical_request_count: int
    retry_limit: int
    response_body_sha256: tuple[str, ...]
    response_header_hashes: tuple[str, ...]
    terminal_event_hashes: tuple[str, ...]
    responses: tuple[TransportResponse, ...]
    content_hash: str


@dataclass(frozen=True)
class UsCompositeReplayVerification:
    run_id: str
    plan_content_hash: str
    authorization_content_hash: str
    checkpoint_receipt_set_hash: str
    review_content_hash: str
    response_body_sha256: tuple[str, ...]
    response_header_hashes: tuple[str, ...]
    terminal_event_hashes: tuple[str, ...]
    replayed_physical_request_count: int
    content_hash: str


@dataclass(frozen=True)
class StorageBackedUsCompositeAcceptance:
    run_id: str
    plan_content_hash: str
    authorization_content_hash: str
    replay_verification_content_hash: str
    checkpoint_receipt_set_hash: str
    review_content_hash: str
    diagnostic_acceptance_content_hash: str
    accepted: bool
    decision_code: str
    diagnostic_only: bool
    post_predecessor_observation: bool
    durable_identity_authorized: bool
    remainder_authorized: bool
    evidence_upgrade_authorized: bool
    operating_mic_binding_status: str
    content_hash: str


class UsCompositeTransport(Protocol):
    def send(self, request: ProviderWireRequest) -> TransportResponse: ...


def _controller_authority_body() -> dict[str, object]:
    return {
        "authorityRecordVersion": CONTROLLER_AUTHORITY_VERSION,
        "authorityBasis": AUTHORITY_BASIS,
        "providerOrigin": PROVIDER_ORIGIN,
        "planContentHash": FROZEN_PLAN_CONTENT_HASH,
        "physicalRequestCount": PHYSICAL_REQUEST_COUNT,
        "logicalJobCount": LOGICAL_JOB_COUNT,
        "retryLimit": RETRY_LIMIT,
        "executionScope": "US_COMPOSITE_DIAGNOSTIC_ONLY_NO_REMAINDER",
    }


def _authorization_body(
    value: UsCompositePhaseAuthorization, *, include_hash: bool
) -> dict[str, object]:
    body: dict[str, object] = {
        "authorizationVersion": value.authorization_version,
        "runId": value.run_id,
        "planContentHash": value.plan_content_hash,
        "authorityBasis": value.authority_basis,
        "controllerAuthorityContentHash": value.controller_authority_content_hash,
        "physicalRequestCount": value.physical_request_count,
        "logicalJobCount": value.logical_job_count,
        "retryLimit": value.retry_limit,
        "testOnly": value.test_only,
        "networkAuthorized": value.network_authorized,
    }
    if include_hash:
        body["contentHash"] = value.content_hash
    return body


def seal_us_composite_phase_authorization_v1(
    plan: UsCompositePlan,
    *,
    run_id: str,
    accepted_controller_authority_content_hash: str | None = None,
    test_only: bool = False,
    network_authorized: bool = False,
) -> UsCompositePhaseAuthorization:
    """Seal authority for this diagnostic plan under a new run identity."""

    _validate_plan(plan)
    if accepted_controller_authority_content_hash != CONTROLLER_AUTHORITY_CONTENT_HASH:
        raise UsCompositeExecutionStop("US_COMPOSITE_EXECUTION_CONTROLLER_AUTHORITY_HASH_REQUIRED")
    provisional = UsCompositePhaseAuthorization(
        authorization_version=AUTHORIZATION_VERSION,
        run_id=run_id,
        plan_content_hash=plan.content_hash,
        authority_basis=AUTHORITY_BASIS,
        controller_authority_content_hash=CONTROLLER_AUTHORITY_CONTENT_HASH,
        physical_request_count=PHYSICAL_REQUEST_COUNT,
        logical_job_count=LOGICAL_JOB_COUNT,
        retry_limit=RETRY_LIMIT,
        test_only=test_only,
        network_authorized=network_authorized,
    )
    result = UsCompositePhaseAuthorization(
        **{
            **asdict(provisional),
            "content_hash": canonical_hash(_authorization_body(provisional, include_hash=False)),
        }
    )
    validate_us_composite_phase_authorization_v1(plan, result)
    return result


def validate_us_composite_phase_authorization_v1(
    plan: UsCompositePlan, authorization: UsCompositePhaseAuthorization
) -> None:
    _validate_plan(plan)
    if type(authorization) is not UsCompositePhaseAuthorization:
        raise UsCompositeExecutionStop("US_COMPOSITE_EXECUTION_AUTHORIZATION_TYPE_INVALID")
    if (
        type(authorization.run_id) is not str
        or _RUN_ID.fullmatch(authorization.run_id) is None
        or authorization.run_id == PREDECESSOR_US_COMPOSITE_EXECUTION_RUN_ID
    ):
        raise UsCompositeExecutionStop("US_COMPOSITE_EXECUTION_RUN_ID_INVALID")
    if type(authorization.network_authorized) is not bool:
        raise UsCompositeExecutionStop("US_COMPOSITE_EXECUTION_NETWORK_AUTHORIZATION_TYPE_INVALID")
    if (
        type(authorization.authorization_version) is not str
        or authorization.authorization_version != AUTHORIZATION_VERSION
        or type(authorization.plan_content_hash) is not str
        or authorization.plan_content_hash != plan.content_hash
        or type(authorization.authority_basis) is not str
        or authorization.authority_basis != AUTHORITY_BASIS
        or type(authorization.controller_authority_content_hash) is not str
        or authorization.controller_authority_content_hash != CONTROLLER_AUTHORITY_CONTENT_HASH
        or type(authorization.physical_request_count) is not int
        or authorization.physical_request_count != PHYSICAL_REQUEST_COUNT
        or type(authorization.logical_job_count) is not int
        or authorization.logical_job_count != LOGICAL_JOB_COUNT
        or type(authorization.retry_limit) is not int
        or authorization.retry_limit != 0
        or type(authorization.test_only) is not bool
        or type(authorization.content_hash) is not str
        or not _is_upper_sha256(authorization.content_hash)
    ):
        raise UsCompositeExecutionStop("US_COMPOSITE_EXECUTION_AUTHORIZATION_BINDING_DRIFT")
    if authorization.content_hash != canonical_hash(
        _authorization_body(authorization, include_hash=False)
    ):
        raise UsCompositeExecutionStop("US_COMPOSITE_EXECUTION_AUTHORIZATION_CONTENT_HASH_DRIFT")


def _validate_plan(plan: UsCompositePlan) -> None:
    if canonical_hash(_controller_authority_body()) != CONTROLLER_AUTHORITY_CONTENT_HASH:
        raise UsCompositeExecutionStop(
            "US_COMPOSITE_EXECUTION_CONTROLLER_AUTHORITY_FROZEN_HASH_DRIFT"
        )
    try:
        validate_us_composite_plan_v1(plan)
    except (UsCompositeDiagnosticStop, TypeError, ValueError) as error:
        raise UsCompositeExecutionStop("US_COMPOSITE_EXECUTION_PLAN_INVALID") from error
    if (
        plan.content_hash != FROZEN_PLAN_CONTENT_HASH
        or plan.physical_request_count != 2
        or plan.logical_job_count != 6
        or plan.retry_limit != 0
        or plan.network_authorized is not False
    ):
        raise UsCompositeExecutionStop("US_COMPOSITE_EXECUTION_PLAN_NOT_FROZEN")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest().upper()


def _is_upper_sha256(value: object) -> bool:
    return type(value) is str and _UPPER_SHA256.fullmatch(value) is not None


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")


def _atomic_json_create(path: Path, value: dict[str, object]) -> None:
    _atomic_bytes_create(path, _canonical_json_bytes(value) + b"\n")


def _atomic_bytes_create(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(value)
        handle.flush()
        os.fsync(handle.fileno())


def _assert_no_symlink(path: Path, *, stop: Path) -> None:
    current = path
    while True:
        if current.exists() and current.is_symlink():
            raise UsCompositeExecutionStop("US_COMPOSITE_EXECUTION_STORAGE_SYMLINK_STOP")
        if current == stop or current.parent == current:
            return
        current = current.parent


def _validated_storage_root(storage_root: Path, *, test_only: bool) -> Path:
    if not isinstance(storage_root, Path):
        raise UsCompositeExecutionStop("US_COMPOSITE_EXECUTION_STORAGE_ROOT_TYPE_INVALID")
    try:
        return validate_private_storage_root(storage_root, test_only=test_only)
    except AcquisitionStop as error:
        raise UsCompositeExecutionStop(error.code) from error


def us_composite_run_root_v1(
    storage_root: Path, authorization: UsCompositePhaseAuthorization
) -> Path:
    """Resolve the private run root without creating it."""

    root = _validated_storage_root(storage_root, test_only=authorization.test_only)
    if (
        type(authorization) is not UsCompositePhaseAuthorization
        or _RUN_ID.fullmatch(authorization.run_id) is None
        or authorization.run_id == PREDECESSOR_US_COMPOSITE_EXECUTION_RUN_ID
    ):
        raise UsCompositeExecutionStop("US_COMPOSITE_EXECUTION_RUN_ID_INVALID")
    return root / EXECUTION_CONTRACT_VERSION / authorization.run_id


def _wire_binding(wire: ProviderWireRequest) -> dict[str, object]:
    if type(wire) is not ProviderWireRequest or type(wire.headers) is not tuple:
        raise UsCompositeExecutionStop("US_COMPOSITE_EXECUTION_WIRE_TYPE_INVALID")
    if (
        wire.provider != "OPENFIGI"
        or wire.method != "POST"
        or wire.endpoint_path != "/v3/mapping"
        or wire.headers != (("accept", "application/json"), ("content-type", "application/json"))
        or type(wire.body) is not bytes
        or type(wire.body_sha256) is not str
        or _sha256_bytes(wire.body) != wire.body_sha256
    ):
        raise UsCompositeExecutionStop("US_COMPOSITE_EXECUTION_WIRE_BINDING_DRIFT")
    return {
        "requestIdentity": wire.request_identity,
        "provider": wire.provider,
        "providerOrigin": PROVIDER_ORIGIN,
        "method": wire.method,
        "endpointPath": wire.endpoint_path,
        "headers": [list(item) for item in wire.headers],
        "bodySha256": wire.body_sha256,
    }


def _runtime_attribute(value: object, name: str) -> object | None:
    try:
        return getattr(value, name)
    except AttributeError:
        return None


def _validate_transport_boundary(
    transport: UsCompositeTransport,
    authorization: UsCompositePhaseAuthorization,
    wires: tuple[ProviderWireRequest, ...],
) -> None:
    if authorization.test_only:
        if (
            _runtime_attribute(transport, "test_only") is not True
            or _runtime_attribute(transport, "transport_kind") != "TEST_ONLY"
            or _runtime_attribute(transport, "provider_origin") != PROVIDER_ORIGIN
            or type(_runtime_attribute(transport, "retry_limit")) is not int
            or _runtime_attribute(transport, "retry_limit") != 0
            or _runtime_attribute(transport, "automatic_retry_allowed") is not False
            or type(_runtime_attribute(transport, "max_response_body_bytes")) is not int
            or _runtime_attribute(transport, "max_response_body_bytes") != MAX_RESPONSE_BODY_BYTES
            or not callable(_runtime_attribute(transport, "send"))
        ):
            raise UsCompositeExecutionStop("US_COMPOSITE_EXECUTION_TEST_TRANSPORT_BOUNDARY_DRIFT")
        return
    if type(transport) is not StdlibAcquisitionHttpTransport:
        raise UsCompositeExecutionStop("US_COMPOSITE_EXECUTION_PRODUCTION_TRANSPORT_TYPE_INVALID")
    if (
        transport.test_only is not False
        or transport.transport_kind != "PRODUCTION"
        or type(transport.retry_limit) is not int
        or transport.retry_limit != 0
        or transport.proxy_policy != "ENVIRONMENT_PROXIES_DISABLED"
        or type(transport._max_response_body_bytes) is not int
        or transport._max_response_body_bytes != MAX_RESPONSE_BODY_BYTES
        or any(
            transport._target_url(wire, eodhd_api_key=None) != PROVIDER_ORIGIN + wire.endpoint_path
            for wire in wires
        )
    ):
        raise UsCompositeExecutionStop("US_COMPOSITE_EXECUTION_PRODUCTION_TRANSPORT_BOUNDARY_DRIFT")


def _manifest_body(
    plan: UsCompositePlan,
    authorization: UsCompositePhaseAuthorization,
    wires: tuple[ProviderWireRequest, ...],
) -> dict[str, object]:
    body: dict[str, object] = {
        "manifestVersion": MANIFEST_VERSION,
        "executionContractVersion": EXECUTION_CONTRACT_VERSION,
        "runId": authorization.run_id,
        "planContentHash": plan.content_hash,
        "authorizationContentHash": authorization.content_hash,
        "authorityBasis": authorization.authority_basis,
        "controllerAuthorityContentHash": (authorization.controller_authority_content_hash),
        "networkAuthorized": authorization.network_authorized,
        "testOnly": authorization.test_only,
        "physicalRequestCount": PHYSICAL_REQUEST_COUNT,
        "logicalJobCount": LOGICAL_JOB_COUNT,
        "retryLimit": RETRY_LIMIT,
        "automaticRetryAllowed": False,
        "openFigiPacingVersion": OPENFIGI_PACING_VERSION,
        "openFigiPacingIntervalMicros": OPENFIGI_PACING_INTERVAL_MICROS,
        "maxResponseBodyBytes": MAX_RESPONSE_BODY_BYTES,
        "requests": [
            {
                "requestOrdinal": request.request_ordinal,
                "wireContentHash": request.wire_content_hash,
                **_wire_binding(wire),
            }
            for request, wire in zip(plan.requests, wires, strict=True)
        ],
    }
    body["contentHash"] = canonical_hash(body)
    return body


def _validated_headers(
    headers: tuple[tuple[str, str], ...],
) -> tuple[tuple[str, str], ...]:
    if type(headers) is not tuple:
        raise UsCompositeExecutionStop("US_COMPOSITE_EXECUTION_RESPONSE_HEADERS_MUST_BE_TUPLE")
    if any(
        type(item) is not tuple
        or len(item) != 2
        or not all(type(part) is str for part in item)
        or not item[0]
        or not item[1]
        or item[0] != item[0].lower()
        or item[0] != item[0].strip()
        or item[1] != item[1].strip()
        or any(character in item[0] + item[1] for character in "\r\n")
        for item in headers
    ):
        raise UsCompositeExecutionStop("US_COMPOSITE_EXECUTION_RESPONSE_HEADER_INVALID")
    if len({item[0] for item in headers}) != len(headers) or headers != tuple(sorted(headers)):
        raise UsCompositeExecutionStop("US_COMPOSITE_EXECUTION_RESPONSE_HEADERS_NOT_CANONICAL")
    content_type = dict(headers).get("content-type")
    if content_type is None or content_type.split(";", 1)[0].strip().lower() != "application/json":
        raise UsCompositeExecutionStop("US_COMPOSITE_EXECUTION_RESPONSE_CONTENT_TYPE_INVALID")
    return headers


def _response_binding(response: TransportResponse) -> dict[str, object]:
    if type(response) is not TransportResponse:
        raise UsCompositeExecutionStop("US_COMPOSITE_EXECUTION_TRANSPORT_RESPONSE_TYPE_INVALID")
    if type(response.status_code) is not int or response.status_code != 200:
        raise UsCompositeExecutionStop("US_COMPOSITE_EXECUTION_HTTP_STATUS_INVALID")
    headers = _validated_headers(response.headers)
    if type(response.body) is not bytes:
        raise UsCompositeExecutionStop("US_COMPOSITE_EXECUTION_RESPONSE_BODY_MUST_BE_BYTES")
    if len(response.body) > MAX_RESPONSE_BODY_BYTES:
        raise UsCompositeExecutionStop("US_COMPOSITE_EXECUTION_RESPONSE_BODY_TOO_LARGE")
    return {
        "statusCode": response.status_code,
        "responseHeaders": [list(item) for item in headers],
        "responseHeadersHash": canonical_hash([list(item) for item in headers]),
        "bodySha256": _sha256_bytes(response.body),
        "bodyByteCount": len(response.body),
    }


def _intent_detail(
    wire: ProviderWireRequest,
    *,
    dispatch_monotonic_micros: int,
    previous_request_identity: str | None,
    previous_dispatch_monotonic_micros: int | None,
) -> dict[str, object]:
    return {
        **_wire_binding(wire),
        "retryLimit": RETRY_LIMIT,
        "automaticRetryAllowed": False,
        "dispatchMonotonicMicros": dispatch_monotonic_micros,
        "previousRequestIdentity": previous_request_identity,
        "previousDispatchMonotonicMicros": previous_dispatch_monotonic_micros,
        "pacingVersion": OPENFIGI_PACING_VERSION,
        "pacingRequiredIntervalMicros": OPENFIGI_PACING_INTERVAL_MICROS,
        "pacingLineageHash": canonical_hash(
            {
                "pacingVersion": OPENFIGI_PACING_VERSION,
                "requestIdentity": wire.request_identity,
                "dispatchMonotonicMicros": dispatch_monotonic_micros,
                "previousRequestIdentity": previous_request_identity,
                "previousDispatchMonotonicMicros": previous_dispatch_monotonic_micros,
                "requiredIntervalMicros": OPENFIGI_PACING_INTERVAL_MICROS,
            }
        ),
    }


def _completed_detail(
    wire: ProviderWireRequest,
    response: TransportResponse,
    *,
    checkpoint_path: str,
) -> dict[str, object]:
    return {
        "requestIdentity": wire.request_identity,
        "wireBindingHash": canonical_hash(_wire_binding(wire)),
        "checkpointPath": checkpoint_path,
        **_response_binding(response),
        "retryLimit": RETRY_LIMIT,
        "automaticRetryAllowed": False,
    }


class _ExecutionJournal:
    def __init__(
        self,
        run_root: Path,
        plan: UsCompositePlan,
        authorization: UsCompositePhaseAuthorization,
        wires: tuple[ProviderWireRequest, ...],
        *,
        wall_clock: Callable[[], float],
    ) -> None:
        self._run_root = run_root.resolve()
        self._plan = plan
        self._authorization = authorization
        self._wires = wires
        self._wire_by_identity = {item.request_identity: item for item in wires}
        self._journal_root = self._run_root / "journal"
        self._checkpoint_root = self._run_root / "_private" / "checkpoints"
        self._wall_clock = wall_clock
        self._write_or_verify_manifest()
        self._audit_top_level()
        self._audit_private_root()
        self._audit_request_directories()
        self._audit_checkpoints()
        self._audit_prefix()

    @property
    def manifest_path(self) -> Path:
        return self._run_root / "plan-authorization.json"

    def _write_or_verify_manifest(self) -> None:
        expected = _manifest_body(self._plan, self._authorization, self._wires)
        path = self.manifest_path
        if path.exists():
            try:
                actual = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as error:
                raise UsCompositeExecutionStop(
                    "US_COMPOSITE_EXECUTION_MANIFEST_UNREADABLE"
                ) from error
            if actual != expected:
                raise UsCompositeExecutionStop("US_COMPOSITE_EXECUTION_IMMUTABLE_MANIFEST_DRIFT")
            return
        existing = tuple(item.name for item in self._run_root.iterdir() if item.name != ".lock")
        if existing:
            raise UsCompositeExecutionStop("US_COMPOSITE_EXECUTION_MANIFEST_MISSING_WITH_STATE")
        try:
            _atomic_json_create(path, expected)
        except FileExistsError as error:
            raise UsCompositeExecutionStop("US_COMPOSITE_EXECUTION_MANIFEST_CREATE_RACE") from error

    def _audit_top_level(self) -> None:
        permitted = {".lock", "plan-authorization.json", "journal", "_private"}
        for item in self._run_root.iterdir():
            if item.name not in permitted or item.is_symlink():
                raise UsCompositeExecutionStop("US_COMPOSITE_EXECUTION_RUN_PATH_OR_ORPHAN_DRIFT")

    def _audit_request_directories(self) -> None:
        if not self._journal_root.exists():
            return
        if not self._journal_root.is_dir() or self._journal_root.is_symlink():
            raise UsCompositeExecutionStop("US_COMPOSITE_EXECUTION_JOURNAL_ROOT_INVALID")
        for path in self._journal_root.iterdir():
            if not path.is_dir() or path.is_symlink() or path.name not in self._wire_by_identity:
                raise UsCompositeExecutionStop(
                    "US_COMPOSITE_EXECUTION_JOURNAL_REQUEST_ORPHAN_DRIFT"
                )

    def _audit_private_root(self) -> None:
        private_root = self._run_root / "_private"
        if not private_root.exists():
            return
        if not private_root.is_dir() or private_root.is_symlink():
            raise UsCompositeExecutionStop("US_COMPOSITE_EXECUTION_PRIVATE_ROOT_INVALID")
        if any(item.name != "checkpoints" for item in private_root.iterdir()):
            raise UsCompositeExecutionStop("US_COMPOSITE_EXECUTION_PRIVATE_ORPHAN_DRIFT")

    def _request_root(self, wire: ProviderWireRequest) -> Path:
        return self._journal_root / wire.request_identity

    def events(self, wire: ProviderWireRequest) -> tuple[dict[str, object], ...]:
        root = self._request_root(wire)
        if not root.exists():
            return ()
        paths = sorted(root.iterdir())
        events: list[dict[str, object]] = []
        previous_hash: str | None = None
        previous_recorded = -1
        for expected_sequence, path in enumerate(paths, start=1):
            matched = _EVENT_NAME.fullmatch(path.name)
            if not path.is_file() or path.is_symlink() or matched is None:
                raise UsCompositeExecutionStop("US_COMPOSITE_EXECUTION_JOURNAL_UNEXPECTED_ARTIFACT")
            try:
                event = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as error:
                raise UsCompositeExecutionStop(
                    "US_COMPOSITE_EXECUTION_JOURNAL_EVENT_UNREADABLE"
                ) from error
            claimed_hash = event.get("eventHash")
            body = {key: value for key, value in event.items() if key != "eventHash"}
            recorded = event.get("recordedAtEpochMicros")
            if (
                set(event)
                != {
                    "journalVersion",
                    "runId",
                    "planContentHash",
                    "authorizationContentHash",
                    "requestIdentity",
                    "requestOrdinal",
                    "sequence",
                    "previousEventHash",
                    "state",
                    "recordedAtEpochMicros",
                    "detail",
                    "eventHash",
                }
                or matched.group("sequence") != f"{expected_sequence:03d}"
                or matched.group("state") != event.get("state")
                or claimed_hash != canonical_hash(body)
                or event.get("journalVersion") != JOURNAL_VERSION
                or event.get("runId") != self._authorization.run_id
                or event.get("planContentHash") != self._plan.content_hash
                or event.get("authorizationContentHash") != self._authorization.content_hash
                or event.get("requestIdentity") != wire.request_identity
                or event.get("requestOrdinal")
                != next(
                    index
                    for index, item in enumerate(self._wires, 1)
                    if item.request_identity == wire.request_identity
                )
                or event.get("sequence") != expected_sequence
                or event.get("previousEventHash") != previous_hash
                or type(recorded) is not int
                or recorded < 0
                or recorded < previous_recorded
                or not isinstance(event.get("detail"), dict)
            ):
                raise UsCompositeExecutionStop("US_COMPOSITE_EXECUTION_JOURNAL_EVENT_CHAIN_DRIFT")
            events.append(event)
            previous_hash = str(claimed_hash)
            previous_recorded = recorded
        states = [item["state"] for item in events]
        if states not in ([], ["INTENT"], ["INTENT", "COMPLETED"], ["INTENT", "FAILED"]):
            raise UsCompositeExecutionStop("US_COMPOSITE_EXECUTION_JOURNAL_EVENT_GRAMMAR_DRIFT")
        if events:
            detail = events[0]["detail"]
            dispatch = detail.get("dispatchMonotonicMicros")
            previous_identity = detail.get("previousRequestIdentity")
            previous_dispatch = detail.get("previousDispatchMonotonicMicros")
            if (
                type(dispatch) is not int
                or dispatch < 0
                or (previous_identity is not None and type(previous_identity) is not str)
                or (previous_dispatch is not None and type(previous_dispatch) is not int)
                or detail
                != _intent_detail(
                    wire,
                    dispatch_monotonic_micros=dispatch,
                    previous_request_identity=previous_identity,
                    previous_dispatch_monotonic_micros=previous_dispatch,
                )
            ):
                raise UsCompositeExecutionStop("US_COMPOSITE_EXECUTION_JOURNAL_INTENT_DRIFT")
        return tuple(events)

    def _audit_checkpoints(self) -> None:
        if not self._checkpoint_root.exists():
            return
        if not self._checkpoint_root.is_dir() or self._checkpoint_root.is_symlink():
            raise UsCompositeExecutionStop("US_COMPOSITE_EXECUTION_CHECKPOINT_ROOT_INVALID")
        for path in self._checkpoint_root.iterdir():
            if (
                not path.is_file()
                or path.is_symlink()
                or _CHECKPOINT_NAME.fullmatch(path.name) is None
                or path.stem not in self._wire_by_identity
            ):
                raise UsCompositeExecutionStop(
                    "US_COMPOSITE_EXECUTION_CHECKPOINT_ORPHAN_OR_PATH_DRIFT"
                )
            events = self.events(self._wire_by_identity[path.stem])
            if len(events) != 2 or events[-1]["state"] != "COMPLETED":
                raise UsCompositeExecutionStop(
                    "US_COMPOSITE_EXECUTION_CHECKPOINT_ORPHAN_OR_PATH_DRIFT"
                )

    def _audit_prefix(self) -> None:
        saw_gap = False
        previous_identity: str | None = None
        previous_dispatch: int | None = None
        for wire in self._wires:
            events = self.events(wire)
            if not events:
                saw_gap = True
                continue
            if saw_gap:
                raise UsCompositeExecutionStop(
                    "US_COMPOSITE_EXECUTION_JOURNAL_EXECUTION_PREFIX_DRIFT"
                )
            if len(events) == 1:
                raise UsCompositeExecutionStop("US_COMPOSITE_EXECUTION_UNMATCHED_INTENT_STOP")
            if events[-1]["state"] == "FAILED":
                raise UsCompositeExecutionStop("US_COMPOSITE_EXECUTION_FAILED_REQUEST_STOP")
            detail = events[0]["detail"]
            dispatch = detail["dispatchMonotonicMicros"]
            if (
                detail["previousRequestIdentity"] != previous_identity
                or detail["previousDispatchMonotonicMicros"] != previous_dispatch
                or (
                    previous_dispatch is not None
                    and dispatch - previous_dispatch < OPENFIGI_PACING_INTERVAL_MICROS
                )
            ):
                raise UsCompositeExecutionStop("US_COMPOSITE_EXECUTION_PACING_JOURNAL_DRIFT")
            self.replay(wire, events[-1])
            previous_identity = wire.request_identity
            previous_dispatch = dispatch

    def append(
        self,
        wire: ProviderWireRequest,
        state: str,
        detail: dict[str, object],
    ) -> dict[str, object]:
        events = self.events(wire)
        if (not events and state != "INTENT") or (
            events and (len(events) != 1 or state not in {"COMPLETED", "FAILED"})
        ):
            raise UsCompositeExecutionStop("US_COMPOSITE_EXECUTION_JOURNAL_INVALID_TRANSITION")
        ordinal = next(
            index
            for index, item in enumerate(self._wires, 1)
            if item.request_identity == wire.request_identity
        )
        recorded = self._wall_clock()
        if type(recorded) not in {int, float} or not math.isfinite(recorded) or recorded < 0:
            raise UsCompositeExecutionStop("US_COMPOSITE_EXECUTION_WALL_CLOCK_INVALID")
        body: dict[str, object] = {
            "journalVersion": JOURNAL_VERSION,
            "runId": self._authorization.run_id,
            "planContentHash": self._plan.content_hash,
            "authorizationContentHash": self._authorization.content_hash,
            "requestIdentity": wire.request_identity,
            "requestOrdinal": ordinal,
            "sequence": len(events) + 1,
            "previousEventHash": events[-1]["eventHash"] if events else None,
            "state": state,
            "recordedAtEpochMicros": int(recorded * 1_000_000),
            "detail": detail,
        }
        body["eventHash"] = canonical_hash(body)
        path = self._request_root(wire) / f"{len(events) + 1:03d}-{state}.json"
        try:
            _atomic_json_create(path, body)
        except FileExistsError as error:
            raise UsCompositeExecutionStop(
                "US_COMPOSITE_EXECUTION_JOURNAL_EVENT_CREATE_RACE"
            ) from error
        return body

    def _checkpoint_relative(self, wire: ProviderWireRequest) -> str:
        return f"_private/checkpoints/{wire.request_identity}.bin"

    def write_checkpoint(self, wire: ProviderWireRequest, body: bytes) -> str:
        relative = self._checkpoint_relative(wire)
        path = self._run_root / PurePosixPath(relative)
        if path.exists():
            raise UsCompositeExecutionStop("US_COMPOSITE_EXECUTION_CHECKPOINT_ALREADY_EXISTS")
        try:
            _atomic_bytes_create(path, body)
        except FileExistsError as error:
            raise UsCompositeExecutionStop(
                "US_COMPOSITE_EXECUTION_CHECKPOINT_CREATE_RACE"
            ) from error
        return relative

    def replay(
        self, wire: ProviderWireRequest, completed_event: dict[str, object]
    ) -> TransportResponse:
        if completed_event.get("state") != "COMPLETED":
            raise UsCompositeExecutionStop("US_COMPOSITE_EXECUTION_COMPLETED_EVENT_REQUIRED")
        detail = completed_event.get("detail")
        if not isinstance(detail, dict):
            raise UsCompositeExecutionStop("US_COMPOSITE_EXECUTION_COMPLETED_DETAIL_INVALID")
        raw_relative = detail.get("checkpointPath")
        if type(raw_relative) is not str:
            raise UsCompositeExecutionStop("US_COMPOSITE_EXECUTION_CHECKPOINT_PATH_INVALID")
        relative = PurePosixPath(raw_relative)
        if (
            relative.is_absolute()
            or ".." in relative.parts
            or "." in relative.parts
            or "\\" in raw_relative
            or raw_relative != self._checkpoint_relative(wire)
        ):
            raise UsCompositeExecutionStop("US_COMPOSITE_EXECUTION_UNSAFE_CHECKPOINT_PATH")
        path = (self._run_root / relative).resolve()
        try:
            path.relative_to(self._run_root)
        except ValueError as error:
            raise UsCompositeExecutionStop(
                "US_COMPOSITE_EXECUTION_UNSAFE_CHECKPOINT_PATH"
            ) from error
        if not path.is_file() or path.is_symlink():
            raise UsCompositeExecutionStop("US_COMPOSITE_EXECUTION_CHECKPOINT_MISSING")
        body = path.read_bytes()
        raw_headers = detail.get("responseHeaders")
        if not isinstance(raw_headers, list) or any(
            not isinstance(item, list)
            or len(item) != 2
            or not all(type(part) is str for part in item)
            for item in raw_headers
        ):
            raise UsCompositeExecutionStop("US_COMPOSITE_EXECUTION_REPLAY_HEADERS_INVALID")
        response = TransportResponse(
            status_code=detail.get("statusCode"),
            headers=tuple((item[0], item[1]) for item in raw_headers),
            body=body,
        )
        expected = _completed_detail(wire, response, checkpoint_path=raw_relative)
        if detail != expected:
            raise UsCompositeExecutionStop("US_COMPOSITE_EXECUTION_COMPLETED_DETAIL_DRIFT")
        return response

    def last_completed_dispatch(self) -> tuple[str, int] | None:
        values: list[tuple[str, int]] = []
        for wire in self._wires:
            events = self.events(wire)
            if len(events) == 2 and events[-1]["state"] == "COMPLETED":
                values.append(
                    (
                        wire.request_identity,
                        events[0]["detail"]["dispatchMonotonicMicros"],
                    )
                )
        return values[-1] if values else None


def _result_body(value: UsCompositeExecutionResult, *, include_hash: bool) -> dict[str, object]:
    body: dict[str, object] = {
        "summaryVersion": SUMMARY_VERSION,
        "runId": value.run_id,
        "planContentHash": value.plan_content_hash,
        "authorizationContentHash": value.authorization_content_hash,
        "physicalRequestCount": value.physical_request_count,
        "logicalJobCount": value.logical_job_count,
        "newPhysicalRequestCount": value.new_physical_request_count,
        "replayedPhysicalRequestCount": value.replayed_physical_request_count,
        "retryLimit": value.retry_limit,
        "responseBodySha256": list(value.response_body_sha256),
        "responseHeaderHashes": list(value.response_header_hashes),
        "terminalEventHashes": list(value.terminal_event_hashes),
        "rawResponseContentIncluded": False,
    }
    if include_hash:
        body["contentHash"] = value.content_hash
    return body


def git_safe_us_composite_execution_summary_v1(
    value: UsCompositeExecutionResult,
) -> dict[str, object]:
    """Return a hash-only summary that cannot contain provider response bytes."""

    validate_us_composite_execution_result_v1(value)
    return _result_body(value, include_hash=True)


def validate_us_composite_execution_result_v1(value: UsCompositeExecutionResult) -> None:
    if type(value) is not UsCompositeExecutionResult:
        raise UsCompositeExecutionStop("US_COMPOSITE_EXECUTION_RESULT_TYPE_INVALID")
    if (
        type(value.run_id) is not str
        or _RUN_ID.fullmatch(value.run_id) is None
        or value.run_id == PREDECESSOR_US_COMPOSITE_EXECUTION_RUN_ID
        or value.plan_content_hash != FROZEN_PLAN_CONTENT_HASH
        or not _is_upper_sha256(value.authorization_content_hash)
        or type(value.response_body_sha256) is not tuple
        or type(value.response_header_hashes) is not tuple
        or type(value.terminal_event_hashes) is not tuple
        or type(value.responses) is not tuple
        or len(value.responses) != PHYSICAL_REQUEST_COUNT
        or len(value.response_body_sha256) != PHYSICAL_REQUEST_COUNT
        or len(value.response_header_hashes) != PHYSICAL_REQUEST_COUNT
        or len(value.terminal_event_hashes) != PHYSICAL_REQUEST_COUNT
        or type(value.physical_request_count) is not int
        or value.physical_request_count != PHYSICAL_REQUEST_COUNT
        or type(value.logical_job_count) is not int
        or value.logical_job_count != LOGICAL_JOB_COUNT
        or type(value.new_physical_request_count) is not int
        or not 0 <= value.new_physical_request_count <= PHYSICAL_REQUEST_COUNT
        or type(value.replayed_physical_request_count) is not int
        or not 0 <= value.replayed_physical_request_count <= PHYSICAL_REQUEST_COUNT
        or type(value.retry_limit) is not int
        or value.retry_limit != 0
        or value.new_physical_request_count + value.replayed_physical_request_count
        != PHYSICAL_REQUEST_COUNT
        or any(not _is_upper_sha256(item) for item in value.response_body_sha256)
        or any(not _is_upper_sha256(item) for item in value.response_header_hashes)
        or any(not _is_upper_sha256(item) for item in value.terminal_event_hashes)
        or not _is_upper_sha256(value.content_hash)
    ):
        raise UsCompositeExecutionStop("US_COMPOSITE_EXECUTION_RESULT_BINDING_DRIFT")
    for response, body_hash, header_hash in zip(
        value.responses,
        value.response_body_sha256,
        value.response_header_hashes,
        strict=True,
    ):
        binding = _response_binding(response)
        if binding["bodySha256"] != body_hash or binding["responseHeadersHash"] != header_hash:
            raise UsCompositeExecutionStop("US_COMPOSITE_EXECUTION_RESULT_RESPONSE_DRIFT")
    if value.content_hash != canonical_hash(_result_body(value, include_hash=False)):
        raise UsCompositeExecutionStop("US_COMPOSITE_EXECUTION_RESULT_HASH_DRIFT")


def _lease_id(plan: UsCompositePlan, authorization: UsCompositePhaseAuthorization) -> str:
    return canonical_hash(
        {
            "executionContractVersion": EXECUTION_CONTRACT_VERSION,
            "runId": authorization.run_id,
            "planContentHash": plan.content_hash,
            "authorizationContentHash": authorization.content_hash,
        }
    )


def _checkpoint_receipt_set_body(
    wires: tuple[ProviderWireRequest, ...],
    responses: tuple[TransportResponse, ...],
    terminal_event_hashes: tuple[str, ...],
) -> list[dict[str, object]]:
    return [
        {
            "requestIdentity": wire.request_identity,
            "wireBindingHash": canonical_hash(_wire_binding(wire)),
            "statusCode": response.status_code,
            "responseHeadersHash": canonical_hash(
                [list(item) for item in _validated_headers(response.headers)]
            ),
            "bodySha256": _sha256_bytes(response.body),
            "bodyByteCount": len(response.body),
            "terminalEventHash": event_hash,
        }
        for wire, response, event_hash in zip(wires, responses, terminal_event_hashes, strict=True)
    ]


def _replay_verification_body(
    value: UsCompositeReplayVerification, *, include_hash: bool
) -> dict[str, object]:
    body: dict[str, object] = {
        "executionContractVersion": EXECUTION_CONTRACT_VERSION,
        "runId": value.run_id,
        "planContentHash": value.plan_content_hash,
        "authorizationContentHash": value.authorization_content_hash,
        "checkpointReceiptSetHash": value.checkpoint_receipt_set_hash,
        "reviewContentHash": value.review_content_hash,
        "responseBodySha256": list(value.response_body_sha256),
        "responseHeaderHashes": list(value.response_header_hashes),
        "terminalEventHashes": list(value.terminal_event_hashes),
        "replayedPhysicalRequestCount": value.replayed_physical_request_count,
        "networkRequestsSent": 0,
        "rawResponseContentIncluded": False,
    }
    if include_hash:
        body["contentHash"] = value.content_hash
    return body


def _storage_acceptance_body(
    value: StorageBackedUsCompositeAcceptance, *, include_hash: bool
) -> dict[str, object]:
    body: dict[str, object] = {
        "executionContractVersion": EXECUTION_CONTRACT_VERSION,
        "runId": value.run_id,
        "planContentHash": value.plan_content_hash,
        "authorizationContentHash": value.authorization_content_hash,
        "replayVerificationContentHash": value.replay_verification_content_hash,
        "checkpointReceiptSetHash": value.checkpoint_receipt_set_hash,
        "reviewContentHash": value.review_content_hash,
        "diagnosticAcceptanceContentHash": value.diagnostic_acceptance_content_hash,
        "accepted": value.accepted,
        "decisionCode": value.decision_code,
        "diagnosticOnly": value.diagnostic_only,
        "postPredecessorObservation": value.post_predecessor_observation,
        "durableIdentityAuthorized": value.durable_identity_authorized,
        "remainderAuthorized": value.remainder_authorized,
        "evidenceUpgradeAuthorized": value.evidence_upgrade_authorized,
        "operatingMicBindingStatus": value.operating_mic_binding_status,
        "storageReplayRequired": True,
        "rawResponseContentIncluded": False,
    }
    if include_hash:
        body["contentHash"] = value.content_hash
    return body


def validate_us_composite_replay_verification_v1(value: UsCompositeReplayVerification) -> None:
    if type(value) is not UsCompositeReplayVerification:
        raise UsCompositeExecutionStop("US_COMPOSITE_EXECUTION_REPLAY_VERIFICATION_TYPE_INVALID")
    if (
        type(value.run_id) is not str
        or _RUN_ID.fullmatch(value.run_id) is None
        or value.run_id == PREDECESSOR_US_COMPOSITE_EXECUTION_RUN_ID
        or type(value.plan_content_hash) is not str
        or value.plan_content_hash != FROZEN_PLAN_CONTENT_HASH
        or not _is_upper_sha256(value.authorization_content_hash)
        or not _is_upper_sha256(value.checkpoint_receipt_set_hash)
        or not _is_upper_sha256(value.review_content_hash)
        or type(value.response_body_sha256) is not tuple
        or type(value.response_header_hashes) is not tuple
        or type(value.terminal_event_hashes) is not tuple
        or len(value.response_body_sha256) != PHYSICAL_REQUEST_COUNT
        or len(value.response_header_hashes) != PHYSICAL_REQUEST_COUNT
        or len(value.terminal_event_hashes) != PHYSICAL_REQUEST_COUNT
        or any(not _is_upper_sha256(item) for item in value.response_body_sha256)
        or any(not _is_upper_sha256(item) for item in value.response_header_hashes)
        or any(not _is_upper_sha256(item) for item in value.terminal_event_hashes)
        or type(value.replayed_physical_request_count) is not int
        or value.replayed_physical_request_count != PHYSICAL_REQUEST_COUNT
        or not _is_upper_sha256(value.content_hash)
        or value.content_hash
        != canonical_hash(_replay_verification_body(value, include_hash=False))
    ):
        raise UsCompositeExecutionStop("US_COMPOSITE_EXECUTION_REPLAY_VERIFICATION_DRIFT")


def verify_us_composite_review_from_storage_v1(
    plan: UsCompositePlan,
    authorization: UsCompositePhaseAuthorization,
    expected_review: UsCompositeReview,
    *,
    storage_root: Path,
    wall_clock: Callable[[], float] = time.time,
) -> tuple[UsCompositeReview, UsCompositeReplayVerification]:
    """Rebuild and compare the review from exact private persisted responses."""

    _validate_plan(plan)
    validate_us_composite_phase_authorization_v1(plan, authorization)
    if authorization.network_authorized is not True:
        raise UsCompositeExecutionStop("US_COMPOSITE_EXECUTION_NETWORK_NOT_AUTHORIZED")
    wires = build_us_composite_wire_requests_v1(plan)
    run_root = us_composite_run_root_v1(storage_root, authorization)
    if (
        not run_root.is_dir()
        or run_root.is_symlink()
        or not (run_root / "plan-authorization.json").is_file()
    ):
        raise UsCompositeExecutionStop("US_COMPOSITE_EXECUTION_COMPLETED_RUN_NOT_FOUND")
    try:
        with ExecutionLease(
            run_root / ".lock",
            _lease_id(plan, authorization),
            heartbeat_interval_seconds=3_600.0,
        ):
            journal = _ExecutionJournal(
                run_root,
                plan,
                authorization,
                wires,
                wall_clock=wall_clock,
            )
            responses: list[TransportResponse] = []
            terminal_hashes: list[str] = []
            for wire in wires:
                events = journal.events(wire)
                if len(events) != 2 or events[-1]["state"] != "COMPLETED":
                    raise UsCompositeExecutionStop(
                        "US_COMPOSITE_EXECUTION_COMPLETED_RUN_INCOMPLETE"
                    )
                responses.append(journal.replay(wire, events[-1]))
                terminal_hashes.append(str(events[-1]["eventHash"]))
    except UsCompositeExecutionStop:
        raise
    except RuntimeError as error:
        raise UsCompositeExecutionStop(str(error)) from error
    response_tuple = tuple(responses)
    terminal_tuple = tuple(terminal_hashes)
    try:
        replay_review = build_us_composite_review_v1(plan, response_tuple)
    except (UsCompositeDiagnosticStop, TypeError, ValueError) as error:
        raise UsCompositeExecutionStop(
            "US_COMPOSITE_EXECUTION_STORAGE_REVIEW_REBUILD_FAILED"
        ) from error
    if type(expected_review) is not UsCompositeReview or replay_review != expected_review:
        raise UsCompositeExecutionStop("US_COMPOSITE_EXECUTION_STORAGE_REVIEW_REPLAY_DRIFT")
    body_hashes = tuple(_sha256_bytes(item.body) for item in response_tuple)
    header_hashes = tuple(
        canonical_hash([list(header) for header in _validated_headers(item.headers)])
        for item in response_tuple
    )
    receipt_hash = canonical_hash(
        _checkpoint_receipt_set_body(wires, response_tuple, terminal_tuple)
    )
    provisional = UsCompositeReplayVerification(
        run_id=authorization.run_id,
        plan_content_hash=plan.content_hash,
        authorization_content_hash=authorization.content_hash,
        checkpoint_receipt_set_hash=receipt_hash,
        review_content_hash=replay_review.content_hash,
        response_body_sha256=body_hashes,
        response_header_hashes=header_hashes,
        terminal_event_hashes=terminal_tuple,
        replayed_physical_request_count=PHYSICAL_REQUEST_COUNT,
        content_hash="",
    )
    verification = UsCompositeReplayVerification(
        **{
            **asdict(provisional),
            "response_body_sha256": provisional.response_body_sha256,
            "response_header_hashes": provisional.response_header_hashes,
            "terminal_event_hashes": provisional.terminal_event_hashes,
            "content_hash": canonical_hash(
                _replay_verification_body(provisional, include_hash=False)
            ),
        }
    )
    validate_us_composite_replay_verification_v1(verification)
    return replay_review, verification


def seal_storage_backed_us_composite_acceptance_v1(
    plan: UsCompositePlan,
    authorization: UsCompositePhaseAuthorization,
    expected_review: UsCompositeReview,
    *,
    storage_root: Path,
    accepted: bool,
    decision_code: str,
) -> tuple[
    UsCompositeReplayVerification,
    UsCompositeAcceptance,
    StorageBackedUsCompositeAcceptance,
]:
    """Seal acceptance only from an exact storage-rebuilt diagnostic review."""

    replay_review, verification = verify_us_composite_review_from_storage_v1(
        plan,
        authorization,
        expected_review,
        storage_root=storage_root,
    )
    if accepted is True and decision_code != ACCEPTED_DECISION_CODE:
        raise UsCompositeExecutionStop("US_COMPOSITE_EXECUTION_ACCEPTED_DECISION_CODE_INVALID")
    if accepted is False and decision_code != REJECTED_DECISION_CODE:
        raise UsCompositeExecutionStop("US_COMPOSITE_EXECUTION_REJECTED_DECISION_CODE_INVALID")
    try:
        diagnostic_acceptance = seal_us_composite_acceptance_v1(
            plan,
            replay_review,
            accepted=accepted,
            decision_code=decision_code,
        )
    except (UsCompositeDiagnosticStop, TypeError, ValueError) as error:
        raise UsCompositeExecutionStop(
            "US_COMPOSITE_EXECUTION_STORAGE_ACCEPTANCE_REJECTED"
        ) from error
    provisional = StorageBackedUsCompositeAcceptance(
        run_id=authorization.run_id,
        plan_content_hash=plan.content_hash,
        authorization_content_hash=authorization.content_hash,
        replay_verification_content_hash=verification.content_hash,
        checkpoint_receipt_set_hash=verification.checkpoint_receipt_set_hash,
        review_content_hash=replay_review.content_hash,
        diagnostic_acceptance_content_hash=diagnostic_acceptance.content_hash,
        accepted=diagnostic_acceptance.accepted,
        decision_code=diagnostic_acceptance.decision_code,
        diagnostic_only=diagnostic_acceptance.diagnostic_only,
        post_predecessor_observation=(diagnostic_acceptance.post_predecessor_observation),
        durable_identity_authorized=(diagnostic_acceptance.durable_identity_authorized),
        remainder_authorized=diagnostic_acceptance.remainder_authorized,
        evidence_upgrade_authorized=(diagnostic_acceptance.evidence_upgrade_authorized),
        operating_mic_binding_status=(diagnostic_acceptance.operating_mic_binding_status),
        content_hash="",
    )
    storage_acceptance = StorageBackedUsCompositeAcceptance(
        **{
            **asdict(provisional),
            "content_hash": canonical_hash(
                _storage_acceptance_body(provisional, include_hash=False)
            ),
        }
    )
    validate_storage_backed_us_composite_acceptance_v1(
        plan,
        authorization,
        expected_review,
        verification,
        diagnostic_acceptance,
        storage_acceptance,
        storage_root=storage_root,
    )
    return verification, diagnostic_acceptance, storage_acceptance


def validate_storage_backed_us_composite_acceptance_v1(
    plan: UsCompositePlan,
    authorization: UsCompositePhaseAuthorization,
    expected_review: UsCompositeReview,
    verification: UsCompositeReplayVerification,
    diagnostic_acceptance: UsCompositeAcceptance,
    storage_acceptance: StorageBackedUsCompositeAcceptance,
    *,
    storage_root: Path,
) -> None:
    """Reopen storage before trusting a previously emitted acceptance wrapper."""

    replay_review, replay_verification = verify_us_composite_review_from_storage_v1(
        plan,
        authorization,
        expected_review,
        storage_root=storage_root,
    )
    validate_us_composite_replay_verification_v1(verification)
    if replay_verification != verification:
        raise UsCompositeExecutionStop("US_COMPOSITE_EXECUTION_REPLAY_VERIFICATION_DRIFT")
    try:
        validate_us_composite_acceptance_v1(plan, replay_review, diagnostic_acceptance)
    except (UsCompositeDiagnosticStop, TypeError, ValueError) as error:
        raise UsCompositeExecutionStop("US_COMPOSITE_EXECUTION_ACCEPTANCE_REPLAY_DRIFT") from error
    if type(storage_acceptance) is not StorageBackedUsCompositeAcceptance:
        raise UsCompositeExecutionStop("US_COMPOSITE_EXECUTION_STORAGE_ACCEPTANCE_TYPE_INVALID")
    if (
        type(storage_acceptance.run_id) is not str
        or storage_acceptance.run_id != authorization.run_id
        or type(storage_acceptance.plan_content_hash) is not str
        or storage_acceptance.plan_content_hash != plan.content_hash
        or not _is_upper_sha256(storage_acceptance.authorization_content_hash)
        or storage_acceptance.authorization_content_hash != authorization.content_hash
        or not _is_upper_sha256(storage_acceptance.replay_verification_content_hash)
        or storage_acceptance.replay_verification_content_hash != verification.content_hash
        or not _is_upper_sha256(storage_acceptance.checkpoint_receipt_set_hash)
        or storage_acceptance.checkpoint_receipt_set_hash
        != verification.checkpoint_receipt_set_hash
        or not _is_upper_sha256(storage_acceptance.review_content_hash)
        or storage_acceptance.review_content_hash != replay_review.content_hash
        or not _is_upper_sha256(storage_acceptance.diagnostic_acceptance_content_hash)
        or storage_acceptance.diagnostic_acceptance_content_hash
        != diagnostic_acceptance.content_hash
        or type(storage_acceptance.accepted) is not bool
        or storage_acceptance.accepted is not diagnostic_acceptance.accepted
        or type(storage_acceptance.decision_code) is not str
        or storage_acceptance.decision_code != diagnostic_acceptance.decision_code
        or storage_acceptance.diagnostic_only is not True
        or storage_acceptance.diagnostic_only is not diagnostic_acceptance.diagnostic_only
        or storage_acceptance.post_predecessor_observation is not True
        or storage_acceptance.post_predecessor_observation
        is not diagnostic_acceptance.post_predecessor_observation
        or storage_acceptance.durable_identity_authorized is not False
        or storage_acceptance.durable_identity_authorized
        is not diagnostic_acceptance.durable_identity_authorized
        or storage_acceptance.remainder_authorized is not False
        or storage_acceptance.remainder_authorized is not diagnostic_acceptance.remainder_authorized
        or storage_acceptance.evidence_upgrade_authorized is not False
        or storage_acceptance.evidence_upgrade_authorized
        is not diagnostic_acceptance.evidence_upgrade_authorized
        or storage_acceptance.operating_mic_binding_status != OPERATING_MIC_BINDING_STATUS
        or storage_acceptance.operating_mic_binding_status
        != diagnostic_acceptance.operating_mic_binding_status
        or (
            storage_acceptance.accepted is True
            and storage_acceptance.decision_code != ACCEPTED_DECISION_CODE
        )
        or (
            storage_acceptance.accepted is False
            and storage_acceptance.decision_code != REJECTED_DECISION_CODE
        )
        or not _is_upper_sha256(storage_acceptance.content_hash)
        or storage_acceptance.content_hash
        != canonical_hash(_storage_acceptance_body(storage_acceptance, include_hash=False))
    ):
        raise UsCompositeExecutionStop("US_COMPOSITE_EXECUTION_STORAGE_ACCEPTANCE_DRIFT")


def _monotonic_micros(clock: Callable[[], float]) -> int:
    value = clock()
    if type(value) not in {int, float} or not math.isfinite(value) or value < 0:
        raise UsCompositeExecutionStop("US_COMPOSITE_EXECUTION_MONOTONIC_CLOCK_INVALID")
    return int(value * 1_000_000)


def execute_openfigi_us_composite_diagnostic_v15(
    plan: UsCompositePlan,
    authorization: UsCompositePhaseAuthorization,
    *,
    storage_root: Path,
    transport: UsCompositeTransport,
    monotonic_clock: Callable[[], float] = time.monotonic,
    sleeper: Callable[[float], None] = time.sleep,
    wall_clock: Callable[[], float] = time.time,
) -> UsCompositeExecutionResult:
    """Execute or exactly replay the two-request US-composite diagnostic under one lease."""

    _validate_plan(plan)
    validate_us_composite_phase_authorization_v1(plan, authorization)
    if authorization.network_authorized is not True:
        raise UsCompositeExecutionStop("US_COMPOSITE_EXECUTION_NETWORK_NOT_AUTHORIZED")
    wires = build_us_composite_wire_requests_v1(plan)
    if type(wires) is not tuple or len(wires) != PHYSICAL_REQUEST_COUNT:
        raise UsCompositeExecutionStop("US_COMPOSITE_EXECUTION_WIRE_SET_DRIFT")
    for wire in wires:
        _wire_binding(wire)
    _validate_transport_boundary(transport, authorization, wires)
    if not authorization.test_only and (
        monotonic_clock is not time.monotonic
        or sleeper is not time.sleep
        or wall_clock is not time.time
    ):
        raise UsCompositeExecutionStop("US_COMPOSITE_EXECUTION_PRODUCTION_CLOCK_INJECTION_BLOCKED")
    run_root = us_composite_run_root_v1(storage_root, authorization)
    approved_storage_root = _validated_storage_root(storage_root, test_only=authorization.test_only)
    _assert_no_symlink(run_root, stop=approved_storage_root)
    run_root.mkdir(parents=True, exist_ok=True)
    if run_root.is_symlink() or run_root.resolve() != run_root:
        raise UsCompositeExecutionStop("US_COMPOSITE_EXECUTION_STORAGE_SYMLINK_STOP")
    lease_id = _lease_id(plan, authorization)
    try:
        lease_context = ExecutionLease(
            run_root / ".lock",
            lease_id,
            heartbeat_interval_seconds=3_600.0,
        )
        with lease_context as lease:
            journal = _ExecutionJournal(
                run_root,
                plan,
                authorization,
                wires,
                wall_clock=wall_clock,
            )
            responses: list[TransportResponse] = []
            terminal_hashes: list[str] = []
            new_count = 0
            replayed_count = 0
            previous = journal.last_completed_dispatch()
            for wire in wires:
                events = journal.events(wire)
                if len(events) == 2:
                    response = journal.replay(wire, events[-1])
                    responses.append(response)
                    terminal_hashes.append(str(events[-1]["eventHash"]))
                    replayed_count += 1
                    previous = (
                        wire.request_identity,
                        int(events[0]["detail"]["dispatchMonotonicMicros"]),
                    )
                    continue
                if events:
                    raise UsCompositeExecutionStop("US_COMPOSITE_EXECUTION_UNMATCHED_INTENT_STOP")
                now = _monotonic_micros(monotonic_clock)
                if previous is not None:
                    if now < previous[1]:
                        raise UsCompositeExecutionStop(
                            "US_COMPOSITE_EXECUTION_PACING_CLOCK_REGRESSION"
                        )
                    remaining = OPENFIGI_PACING_INTERVAL_MICROS - (now - previous[1])
                    if remaining > 0:
                        sleeper(remaining / 1_000_000)
                    now = _monotonic_micros(monotonic_clock)
                    if now - previous[1] < OPENFIGI_PACING_INTERVAL_MICROS:
                        raise UsCompositeExecutionStop(
                            "US_COMPOSITE_EXECUTION_PACING_INTERVAL_NOT_MET"
                        )
                intent = journal.append(
                    wire,
                    "INTENT",
                    _intent_detail(
                        wire,
                        dispatch_monotonic_micros=now,
                        previous_request_identity=previous[0] if previous else None,
                        previous_dispatch_monotonic_micros=previous[1] if previous else None,
                    ),
                )
                lease.heartbeat()
                try:
                    response = transport.send(wire)
                except Exception as error:
                    raise UsCompositeExecutionStop(
                        "US_COMPOSITE_EXECUTION_UNKNOWN_TRANSPORT_OUTCOME"
                    ) from error
                try:
                    _response_binding(response)
                except UsCompositeExecutionStop:
                    # The send occurred, but an uncheckpointed invalid response is not
                    # safe to reinterpret or automatically retry.
                    raise
                relative = journal.write_checkpoint(wire, response.body)
                completed = journal.append(
                    wire,
                    "COMPLETED",
                    _completed_detail(wire, response, checkpoint_path=relative),
                )
                if completed["previousEventHash"] != intent["eventHash"]:
                    raise UsCompositeExecutionStop(
                        "US_COMPOSITE_EXECUTION_JOURNAL_EVENT_CHAIN_DRIFT"
                    )
                replayed_response = journal.replay(wire, completed)
                if replayed_response != response:
                    raise UsCompositeExecutionStop("US_COMPOSITE_EXECUTION_POST_WRITE_REPLAY_DRIFT")
                responses.append(replayed_response)
                terminal_hashes.append(str(completed["eventHash"]))
                new_count += 1
                previous = (wire.request_identity, now)
            lease.heartbeat()
    except UsCompositeExecutionStop:
        raise
    except RuntimeError as error:
        raise UsCompositeExecutionStop(str(error)) from error
    response_tuple = tuple(responses)
    if len(response_tuple) != PHYSICAL_REQUEST_COUNT:
        raise UsCompositeExecutionStop("US_COMPOSITE_EXECUTION_RESPONSE_SET_INCOMPLETE")
    body_hashes = tuple(_sha256_bytes(item.body) for item in response_tuple)
    header_hashes = tuple(
        canonical_hash([list(header) for header in _validated_headers(item.headers)])
        for item in response_tuple
    )
    provisional = UsCompositeExecutionResult(
        run_id=authorization.run_id,
        plan_content_hash=plan.content_hash,
        authorization_content_hash=authorization.content_hash,
        physical_request_count=PHYSICAL_REQUEST_COUNT,
        logical_job_count=LOGICAL_JOB_COUNT,
        new_physical_request_count=new_count,
        replayed_physical_request_count=replayed_count,
        retry_limit=RETRY_LIMIT,
        response_body_sha256=body_hashes,
        response_header_hashes=header_hashes,
        terminal_event_hashes=tuple(terminal_hashes),
        responses=response_tuple,
        content_hash="",
    )
    result = UsCompositeExecutionResult(
        **{
            **asdict(provisional),
            "response_body_sha256": provisional.response_body_sha256,
            "response_header_hashes": provisional.response_header_hashes,
            "terminal_event_hashes": provisional.terminal_event_hashes,
            "responses": provisional.responses,
            "content_hash": canonical_hash(_result_body(provisional, include_hash=False)),
        }
    )
    validate_us_composite_execution_result_v1(result)
    return result
