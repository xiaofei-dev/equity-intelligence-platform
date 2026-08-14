"""Fail-closed execution boundary for the frozen Stage 8C SEC v1.6 request.

The v1.6 contract owns the one-request SEC response semantics.  This module owns
only transport safety and private persistence: a distinct controller authority,
an execution lease, an immutable value-free manifest, an append-only journal,
one private raw checkpoint, and storage-backed review and acceptance.  The SEC
contact string is supplied by the caller and validated against the exact
transport instance, but is never persisted or included in a content hash.
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

from equity_analysis.fundamental_value.prospective_company_quality_acquisition_v1 import (
    AcquisitionStop,
    ProviderWireRequest,
    TransportResponse,
    validate_private_storage_root,
)
from equity_analysis.fundamental_value.prospective_company_quality_http_transport_v1 import (
    StdlibAcquisitionHttpTransport,
)
from equity_analysis.fundamental_value.stage8c_sec_inventory_v16 import (
    CANONICAL_OPERATING_MIC,
    PREDECESSOR_V15_RESULT_ARTIFACT_CANONICAL_HASH,
    SEC_MAPPING_CLAIM,
    SEC_METHOD,
    SEC_PHYSICAL_REQUEST_COUNT,
    SEC_RAW_CHECKPOINT_POLICY,
    SEC_RETRY_LIMIT,
    SEC_URL,
    SEC_USER_AGENT_ENVIRONMENT_VARIABLE,
    SEC_USER_AGENT_POLICY,
    SecCorroborationReviewV16,
    Stage8CV16Stop,
    build_sec_corroboration_review_v16,
    build_sec_request_contract_v16,
    build_stage8c_v16_contract,
    canonical_hash,
    validate_runtime_sec_user_agent_v16,
    validate_sec_corroboration_review_v16,
    validate_sec_request_contract_v16,
    validate_stage8c_v16_contract,
)
from equity_analysis.provider_validation.execution_safety import ExecutionLease

EXECUTION_CONTRACT_VERSION = "FV-STAGE8C-SEC-CORROBORATION-EXECUTION-v1.0.0"
AUTHORIZATION_VERSION = "FV-STAGE8C-SEC-CORROBORATION-AUTHORIZATION-v1.0.0"
MANIFEST_VERSION = "FV-STAGE8C-SEC-CORROBORATION-MANIFEST-v1.0.0"
JOURNAL_VERSION = "FV-STAGE8C-SEC-CORROBORATION-JOURNAL-v1.0.0"
SUMMARY_VERSION = "FV-STAGE8C-SEC-CORROBORATION-SUMMARY-v1.0.0"
REPLAY_VERSION = "FV-STAGE8C-SEC-CORROBORATION-REPLAY-v1.0.0"
STORAGE_ACCEPTANCE_VERSION = (
    "FV-STAGE8C-SEC-CORROBORATION-STORAGE-ACCEPTANCE-v1.0.0"
)
CONTROLLER_AUTHORITY_VERSION = (
    "FV-STAGE8C-SEC-CORROBORATION-CONTROLLER-AUTHORITY-v1.0.0"
)
AUTHORITY_BASIS = "USER_EXPLICIT_BROAD_FUTURE_PROVIDER_AUTHORIZATION_2026_08_02"
EXECUTION_SCOPE = "SEC_CORROBORATION_ONLY_NO_DB_NO_PROJECTION"
STAGE8C_V16_CONTRACT_CONTENT_HASH = (
    "9045FCFA5CC3BD63EB100522CC96D25DAFB53AB212C83047DFFC42B5215121BC"
)
SEC_REQUEST_CONTRACT_CONTENT_HASH = (
    "027988A7E7FCF99446BF7B7C81022A604035DD27F2E3919E1F4AF22C187024E5"
)
PREDECESSOR_V15_RESULT_CONTENT_HASH = (
    "AD83ACD175AFA01D706D689EE48B93233BB8D95D6B494655B7E15337B5FDC6B7"
)
SEC_PROVIDER_ORIGIN = "https://www.sec.gov"
SEC_ENDPOINT_PATH = "/files/company_tickers_exchange.json"
MAX_RESPONSE_BODY_BYTES = 4 * 1024 * 1024
ACCEPTED_DECISION_CODE = "SEC_CORROBORATION_ACCEPTED_CURRENT_OPERATING_MIC_ONLY"
REJECTED_DECISION_CODE = "SEC_CORROBORATION_REJECTED_TARGET_MAPPING_INCOMPLETE"
CONTROLLER_AUTHORITY_CONTENT_HASH = (
    "C48B2D709811A57D111DCB277D88F40334A7E0A5E8C2D7CADDA042FE03C29C5B"
)

_RUN_ID = re.compile(r"[A-Z0-9][A-Z0-9._-]{7,127}\Z")
_UPPER_SHA256 = re.compile(r"[0-9A-F]{64}\Z")
_EVENT_NAME = re.compile(r"(?P<sequence>\d{3})-(?P<state>INTENT|COMPLETED|FAILED)\.json\Z")
_CHECKPOINT_NAME = re.compile(r"[0-9A-F]{64}\.bin\Z")


class SecExecutionStop(RuntimeError):
    """Fail-closed execution stop with a stable, contact-free code."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class SecPhaseAuthorizationV16:
    authorization_version: str
    run_id: str
    stage8c_contract_content_hash: str
    request_contract_content_hash: str
    predecessor_v15_result_content_hash: str
    authority_basis: str
    controller_authority_content_hash: str
    execution_scope: str
    physical_request_count: int
    retry_limit: int
    test_only: bool = False
    network_authorized: bool = False
    content_hash: str = ""


@dataclass(frozen=True)
class SecExecutionResultV16:
    run_id: str
    stage8c_contract_content_hash: str
    request_contract_content_hash: str
    authorization_content_hash: str
    physical_request_count: int
    new_physical_request_count: int
    replayed_physical_request_count: int
    retry_limit: int
    response_body_sha256: str
    response_headers_hash: str
    terminal_event_hash: str
    response: TransportResponse
    content_hash: str


@dataclass(frozen=True)
class SecReplayVerificationV16:
    run_id: str
    stage8c_contract_content_hash: str
    request_contract_content_hash: str
    authorization_content_hash: str
    checkpoint_receipt_hash: str
    review_content_hash: str
    response_body_sha256: str
    response_headers_hash: str
    terminal_event_hash: str
    replayed_physical_request_count: int
    content_hash: str


@dataclass(frozen=True)
class StorageBackedSecCorroborationAcceptanceV16:
    storage_acceptance_version: str
    run_id: str
    stage8c_contract_content_hash: str
    request_contract_content_hash: str
    predecessor_v15_result_content_hash: str
    authorization_content_hash: str
    replay_verification_content_hash: str
    checkpoint_receipt_hash: str
    review_content_hash: str
    accepted: bool
    decision_code: str
    supported_mapping_count: int
    canonical_operating_mic: str | None
    claim: str
    corroboration_only: bool
    diagnostic_only: bool
    segment_claimed: bool
    tier_claimed: bool
    exchange_history_claimed: bool
    listing_figi_claimed: bool
    currency_claimed: bool
    completed_session_claimed: bool
    database_read_authorized: bool
    database_write_authorized: bool
    v22_write_authorized: bool
    v24_write_authorized: bool
    projection_authorized: bool
    evidence_label_upgrade_authorized: bool
    content_hash: str


class SecTransportV16(Protocol):
    def send(self, request: ProviderWireRequest) -> TransportResponse: ...


def _controller_authority_body() -> dict[str, object]:
    return {
        "authorityRecordVersion": CONTROLLER_AUTHORITY_VERSION,
        "authorityBasis": AUTHORITY_BASIS,
        "providerOrigin": SEC_PROVIDER_ORIGIN,
        "method": SEC_METHOD,
        "url": SEC_URL,
        "stage8cContractContentHash": STAGE8C_V16_CONTRACT_CONTENT_HASH,
        "requestContractContentHash": SEC_REQUEST_CONTRACT_CONTENT_HASH,
        "predecessorV15ResultContentHash": PREDECESSOR_V15_RESULT_CONTENT_HASH,
        "physicalRequestCount": SEC_PHYSICAL_REQUEST_COUNT,
        "retryLimit": SEC_RETRY_LIMIT,
        "executionScope": EXECUTION_SCOPE,
        "runtimeUserAgentEnvironmentVariable": SEC_USER_AGENT_ENVIRONMENT_VARIABLE,
        "runtimeUserAgentPolicy": SEC_USER_AGENT_POLICY,
        "rawCheckpointPolicy": SEC_RAW_CHECKPOINT_POLICY,
    }


def _authorization_body(
    value: SecPhaseAuthorizationV16, *, include_hash: bool
) -> dict[str, object]:
    body: dict[str, object] = {
        "authorizationVersion": value.authorization_version,
        "runId": value.run_id,
        "stage8cContractContentHash": value.stage8c_contract_content_hash,
        "requestContractContentHash": value.request_contract_content_hash,
        "predecessorV15ResultContentHash": value.predecessor_v15_result_content_hash,
        "authorityBasis": value.authority_basis,
        "controllerAuthorityContentHash": value.controller_authority_content_hash,
        "executionScope": value.execution_scope,
        "physicalRequestCount": value.physical_request_count,
        "retryLimit": value.retry_limit,
        "testOnly": value.test_only,
        "networkAuthorized": value.network_authorized,
    }
    if include_hash:
        body["contentHash"] = value.content_hash
    return body


def _is_upper_sha256(value: object) -> bool:
    return type(value) is str and _UPPER_SHA256.fullmatch(value) is not None


def _validate_frozen_contracts() -> None:
    stage8c = build_stage8c_v16_contract()
    request = build_sec_request_contract_v16()
    try:
        validate_stage8c_v16_contract(stage8c)
        validate_sec_request_contract_v16(request)
    except (Stage8CV16Stop, TypeError, ValueError) as error:
        raise SecExecutionStop("SEC_EXECUTION_FROZEN_CONTRACT_INVALID") from error
    if (
        stage8c.content_hash != STAGE8C_V16_CONTRACT_CONTENT_HASH
        or request.content_hash != SEC_REQUEST_CONTRACT_CONTENT_HASH
        or stage8c.predecessor_result_artifact_canonical_hash
        != PREDECESSOR_V15_RESULT_CONTENT_HASH
        or PREDECESSOR_V15_RESULT_ARTIFACT_CANONICAL_HASH
        != PREDECESSOR_V15_RESULT_CONTENT_HASH
        or request.method != "GET"
        or request.url != SEC_URL
        or request.physical_request_count != 1
        or request.retry_limit != 0
        or request.network_authorized is not False
    ):
        raise SecExecutionStop("SEC_EXECUTION_FROZEN_CONTRACT_DRIFT")
    if canonical_hash(_controller_authority_body()) != CONTROLLER_AUTHORITY_CONTENT_HASH:
        raise SecExecutionStop("SEC_EXECUTION_CONTROLLER_AUTHORITY_FROZEN_HASH_DRIFT")


def seal_sec_phase_authorization_v16(
    *,
    run_id: str,
    accepted_controller_authority_content_hash: str | None = None,
    test_only: bool = False,
    network_authorized: bool = False,
) -> SecPhaseAuthorizationV16:
    """Seal one run without reading the SEC contact environment variable."""

    _validate_frozen_contracts()
    if accepted_controller_authority_content_hash != CONTROLLER_AUTHORITY_CONTENT_HASH:
        raise SecExecutionStop("SEC_EXECUTION_CONTROLLER_AUTHORITY_HASH_REQUIRED")
    provisional = SecPhaseAuthorizationV16(
        authorization_version=AUTHORIZATION_VERSION,
        run_id=run_id,
        stage8c_contract_content_hash=STAGE8C_V16_CONTRACT_CONTENT_HASH,
        request_contract_content_hash=SEC_REQUEST_CONTRACT_CONTENT_HASH,
        predecessor_v15_result_content_hash=PREDECESSOR_V15_RESULT_CONTENT_HASH,
        authority_basis=AUTHORITY_BASIS,
        controller_authority_content_hash=CONTROLLER_AUTHORITY_CONTENT_HASH,
        execution_scope=EXECUTION_SCOPE,
        physical_request_count=1,
        retry_limit=0,
        test_only=test_only,
        network_authorized=network_authorized,
    )
    result = SecPhaseAuthorizationV16(
        **{
            **asdict(provisional),
            "content_hash": canonical_hash(
                _authorization_body(provisional, include_hash=False)
            ),
        }
    )
    validate_sec_phase_authorization_v16(result)
    return result


def validate_sec_phase_authorization_v16(value: SecPhaseAuthorizationV16) -> None:
    _validate_frozen_contracts()
    if type(value) is not SecPhaseAuthorizationV16:
        raise SecExecutionStop("SEC_EXECUTION_AUTHORIZATION_TYPE_INVALID")
    if (
        type(value.run_id) is not str
        or _RUN_ID.fullmatch(value.run_id) is None
        or type(value.network_authorized) is not bool
        or type(value.test_only) is not bool
        or value.authorization_version != AUTHORIZATION_VERSION
        or value.stage8c_contract_content_hash != STAGE8C_V16_CONTRACT_CONTENT_HASH
        or value.request_contract_content_hash != SEC_REQUEST_CONTRACT_CONTENT_HASH
        or value.predecessor_v15_result_content_hash
        != PREDECESSOR_V15_RESULT_CONTENT_HASH
        or value.authority_basis != AUTHORITY_BASIS
        or value.controller_authority_content_hash
        != CONTROLLER_AUTHORITY_CONTENT_HASH
        or value.execution_scope != EXECUTION_SCOPE
        or type(value.physical_request_count) is not int
        or value.physical_request_count != 1
        or type(value.retry_limit) is not int
        or value.retry_limit != 0
        or not _is_upper_sha256(value.content_hash)
        or value.content_hash
        != canonical_hash(_authorization_body(value, include_hash=False))
    ):
        raise SecExecutionStop("SEC_EXECUTION_AUTHORIZATION_BINDING_DRIFT")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest().upper()


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")


def _atomic_bytes_create(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(value)
        handle.flush()
        os.fsync(handle.fileno())


def _atomic_json_create(path: Path, value: dict[str, object]) -> None:
    _atomic_bytes_create(path, _canonical_json_bytes(value) + b"\n")


def _validated_storage_root(storage_root: Path, *, test_only: bool) -> Path:
    if not isinstance(storage_root, Path):
        raise SecExecutionStop("SEC_EXECUTION_STORAGE_ROOT_TYPE_INVALID")
    try:
        return validate_private_storage_root(storage_root, test_only=test_only)
    except AcquisitionStop as error:
        raise SecExecutionStop(error.code) from error


def _assert_no_symlink(path: Path, *, stop: Path) -> None:
    current = path
    while True:
        if current.exists() and current.is_symlink():
            raise SecExecutionStop("SEC_EXECUTION_STORAGE_SYMLINK_STOP")
        if current == stop or current.parent == current:
            return
        current = current.parent


def sec_run_root_v16(
    storage_root: Path, authorization: SecPhaseAuthorizationV16
) -> Path:
    root = _validated_storage_root(storage_root, test_only=authorization.test_only)
    if type(authorization.run_id) is not str or _RUN_ID.fullmatch(authorization.run_id) is None:
        raise SecExecutionStop("SEC_EXECUTION_RUN_ID_INVALID")
    return root / EXECUTION_CONTRACT_VERSION / authorization.run_id


def _build_wire() -> ProviderWireRequest:
    request_identity = canonical_hash(
        {
            "executionContractVersion": EXECUTION_CONTRACT_VERSION,
            "stage8cContractContentHash": STAGE8C_V16_CONTRACT_CONTENT_HASH,
            "requestContractContentHash": SEC_REQUEST_CONTRACT_CONTENT_HASH,
            "provider": "SEC",
            "method": "GET",
            "url": SEC_URL,
            "retryLimit": 0,
        }
    )
    return ProviderWireRequest(
        request_identity=request_identity,
        provider="SEC",
        method="GET",
        endpoint_path=SEC_ENDPOINT_PATH,
        headers=(("accept", "application/json"),),
        body=None,
        body_sha256=None,
    )


def _wire_binding(wire: ProviderWireRequest) -> dict[str, object]:
    expected = _build_wire()
    if type(wire) is not ProviderWireRequest or wire != expected:
        raise SecExecutionStop("SEC_EXECUTION_WIRE_BINDING_DRIFT")
    return {
        "requestIdentity": wire.request_identity,
        "provider": wire.provider,
        "providerOrigin": SEC_PROVIDER_ORIGIN,
        "method": wire.method,
        "endpointPath": wire.endpoint_path,
        "headers": [["accept", "application/json"]],
        "bodyPresent": False,
        "retryLimit": 0,
    }


def _runtime_attribute(value: object, name: str) -> object | None:
    try:
        return getattr(value, name)
    except AttributeError:
        return None


def _validate_transport_boundary(
    transport: SecTransportV16,
    authorization: SecPhaseAuthorizationV16,
    wire: ProviderWireRequest,
    runtime_user_agent: str,
) -> None:
    if authorization.test_only:
        if (
            _runtime_attribute(transport, "test_only") is not True
            or _runtime_attribute(transport, "transport_kind") != "TEST_ONLY"
            or _runtime_attribute(transport, "provider_origin") != SEC_PROVIDER_ORIGIN
            or type(_runtime_attribute(transport, "retry_limit")) is not int
            or _runtime_attribute(transport, "retry_limit") != 0
            or _runtime_attribute(transport, "automatic_retry_allowed") is not False
            or type(_runtime_attribute(transport, "max_response_body_bytes")) is not int
            or _runtime_attribute(transport, "max_response_body_bytes")
            != MAX_RESPONSE_BODY_BYTES
            or _runtime_attribute(transport, "sec_user_agent_contact")
            != runtime_user_agent
            or not callable(_runtime_attribute(transport, "send"))
        ):
            raise SecExecutionStop("SEC_EXECUTION_TEST_TRANSPORT_BOUNDARY_DRIFT")
        return
    if type(transport) is not StdlibAcquisitionHttpTransport:
        raise SecExecutionStop("SEC_EXECUTION_PRODUCTION_TRANSPORT_TYPE_INVALID")
    if (
        transport.test_only is not False
        or transport.transport_kind != "PRODUCTION"
        or type(transport.retry_limit) is not int
        or transport.retry_limit != 0
        or transport.proxy_policy != "ENVIRONMENT_PROXIES_DISABLED"
        or type(transport._max_response_body_bytes) is not int
        or transport._max_response_body_bytes != MAX_RESPONSE_BODY_BYTES
        or transport._sec_user_agent_contact != runtime_user_agent
        or transport._target_url(wire, eodhd_api_key=None) != SEC_URL
    ):
        raise SecExecutionStop("SEC_EXECUTION_PRODUCTION_TRANSPORT_BOUNDARY_DRIFT")


def _manifest_body(
    authorization: SecPhaseAuthorizationV16, wire: ProviderWireRequest
) -> dict[str, object]:
    body: dict[str, object] = {
        "manifestVersion": MANIFEST_VERSION,
        "executionContractVersion": EXECUTION_CONTRACT_VERSION,
        "runId": authorization.run_id,
        "stage8cContractContentHash": STAGE8C_V16_CONTRACT_CONTENT_HASH,
        "requestContractContentHash": SEC_REQUEST_CONTRACT_CONTENT_HASH,
        "predecessorV15ResultContentHash": PREDECESSOR_V15_RESULT_CONTENT_HASH,
        "authorizationContentHash": authorization.content_hash,
        "authorityBasis": authorization.authority_basis,
        "controllerAuthorityContentHash": authorization.controller_authority_content_hash,
        "executionScope": EXECUTION_SCOPE,
        "networkAuthorized": authorization.network_authorized,
        "testOnly": authorization.test_only,
        "physicalRequestCount": 1,
        "retryLimit": 0,
        "automaticRetryAllowed": False,
        "maxResponseBodyBytes": MAX_RESPONSE_BODY_BYTES,
        "redirectPolicy": "REDIRECTS_BLOCKED_BY_EXACT_STDLIB_TRANSPORT",
        "runtimeUserAgentEnvironmentVariable": SEC_USER_AGENT_ENVIRONMENT_VARIABLE,
        "runtimeUserAgentPolicy": SEC_USER_AGENT_POLICY,
        "runtimeUserAgentValuePersisted": False,
        "runtimeUserAgentValueHashed": False,
        "rawCheckpointPolicy": SEC_RAW_CHECKPOINT_POLICY,
        "request": _wire_binding(wire),
    }
    body["contentHash"] = canonical_hash(body)
    return body


def _validated_headers(
    headers: tuple[tuple[str, str], ...],
) -> tuple[tuple[str, str], ...]:
    if type(headers) is not tuple:
        raise SecExecutionStop("SEC_EXECUTION_RESPONSE_HEADERS_MUST_BE_TUPLE")
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
        raise SecExecutionStop("SEC_EXECUTION_RESPONSE_HEADER_INVALID")
    if len({item[0] for item in headers}) != len(headers) or headers != tuple(
        sorted(headers)
    ):
        raise SecExecutionStop("SEC_EXECUTION_RESPONSE_HEADERS_NOT_CANONICAL")
    content_type = dict(headers).get("content-type")
    if (
        content_type is None
        or content_type.split(";", 1)[0].strip().lower() != "application/json"
    ):
        raise SecExecutionStop("SEC_EXECUTION_RESPONSE_CONTENT_TYPE_INVALID")
    return headers


def _reject_runtime_user_agent_reflection(
    response: TransportResponse, runtime_user_agent: str
) -> None:
    """Reject before hashing or persistence if SEC reflects the private contact."""

    try:
        user_agent = validate_runtime_sec_user_agent_v16(runtime_user_agent)
    except Stage8CV16Stop as error:
        raise SecExecutionStop(error.code) from error
    if type(response) is not TransportResponse:
        raise SecExecutionStop("SEC_EXECUTION_TRANSPORT_RESPONSE_TYPE_INVALID")
    encoded = user_agent.encode("ascii")
    body_reflected = type(response.body) is bytes and encoded in response.body
    header_reflected = type(response.headers) is tuple and any(
        type(item) is tuple
        and len(item) == 2
        and all(type(part) is str for part in item)
        and (user_agent in item[0] or user_agent in item[1])
        for item in response.headers
    )
    if body_reflected or header_reflected:
        raise SecExecutionStop("SEC_EXECUTION_USER_AGENT_REFLECTION_BLOCKED")


def _response_binding(
    response: TransportResponse, *, runtime_user_agent: str
) -> dict[str, object]:
    _reject_runtime_user_agent_reflection(response, runtime_user_agent)
    if type(response) is not TransportResponse:
        raise SecExecutionStop("SEC_EXECUTION_TRANSPORT_RESPONSE_TYPE_INVALID")
    if type(response.status_code) is not int or response.status_code != 200:
        raise SecExecutionStop("SEC_EXECUTION_HTTP_STATUS_INVALID")
    headers = _validated_headers(response.headers)
    if type(response.body) is not bytes:
        raise SecExecutionStop("SEC_EXECUTION_RESPONSE_BODY_MUST_BE_BYTES")
    if len(response.body) > MAX_RESPONSE_BODY_BYTES:
        raise SecExecutionStop("SEC_EXECUTION_RESPONSE_BODY_TOO_LARGE")
    return {
        "statusCode": response.status_code,
        "responseHeaders": [list(item) for item in headers],
        "responseHeadersHash": canonical_hash([list(item) for item in headers]),
        "bodySha256": _sha256_bytes(response.body),
        "bodyByteCount": len(response.body),
    }


def _intent_detail(wire: ProviderWireRequest, dispatch_monotonic_micros: int) -> dict[str, object]:
    return {
        **_wire_binding(wire),
        "dispatchMonotonicMicros": dispatch_monotonic_micros,
        "retryLimit": 0,
        "automaticRetryAllowed": False,
        "runtimeUserAgentValidatedOutsidePersistedState": True,
    }


def _completed_detail(
    wire: ProviderWireRequest,
    response: TransportResponse,
    *,
    checkpoint_path: str,
    runtime_user_agent: str,
) -> dict[str, object]:
    return {
        "requestIdentity": wire.request_identity,
        "wireBindingHash": canonical_hash(_wire_binding(wire)),
        "checkpointPath": checkpoint_path,
        **_response_binding(response, runtime_user_agent=runtime_user_agent),
        "retryLimit": 0,
        "automaticRetryAllowed": False,
    }


class _SecExecutionJournal:
    def __init__(
        self,
        run_root: Path,
        authorization: SecPhaseAuthorizationV16,
        wire: ProviderWireRequest,
        *,
        runtime_user_agent: str,
        wall_clock: Callable[[], float],
    ) -> None:
        self._run_root = run_root.resolve()
        self._authorization = authorization
        self._wire = wire
        self._journal_root = self._run_root / "journal" / wire.request_identity
        self._checkpoint_root = self._run_root / "_private" / "checkpoints"
        self._runtime_user_agent = runtime_user_agent
        self._wall_clock = wall_clock
        self._write_or_verify_manifest()
        self._audit_top_level()
        self._audit_private_root()
        self._audit_journal_root()
        self._audit_checkpoint()
        self._audit_terminal_state()

    @property
    def manifest_path(self) -> Path:
        return self._run_root / "plan-authorization.json"

    def _write_or_verify_manifest(self) -> None:
        expected = _manifest_body(self._authorization, self._wire)
        path = self.manifest_path
        if path.exists():
            try:
                actual = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as error:
                raise SecExecutionStop("SEC_EXECUTION_MANIFEST_UNREADABLE") from error
            if actual != expected:
                raise SecExecutionStop("SEC_EXECUTION_IMMUTABLE_MANIFEST_DRIFT")
            return
        existing = tuple(item.name for item in self._run_root.iterdir() if item.name != ".lock")
        if existing:
            raise SecExecutionStop("SEC_EXECUTION_MANIFEST_MISSING_WITH_STATE")
        try:
            _atomic_json_create(path, expected)
        except FileExistsError as error:
            raise SecExecutionStop("SEC_EXECUTION_MANIFEST_CREATE_RACE") from error

    def _audit_top_level(self) -> None:
        permitted = {".lock", "plan-authorization.json", "journal", "_private"}
        for item in self._run_root.iterdir():
            if item.name not in permitted or item.is_symlink():
                raise SecExecutionStop("SEC_EXECUTION_RUN_PATH_OR_ORPHAN_DRIFT")

    def _audit_private_root(self) -> None:
        private = self._run_root / "_private"
        if not private.exists():
            return
        if not private.is_dir() or private.is_symlink():
            raise SecExecutionStop("SEC_EXECUTION_PRIVATE_ROOT_INVALID")
        if any(item.name != "checkpoints" for item in private.iterdir()):
            raise SecExecutionStop("SEC_EXECUTION_PRIVATE_ORPHAN_DRIFT")

    def _audit_journal_root(self) -> None:
        parent = self._run_root / "journal"
        if not parent.exists():
            return
        if not parent.is_dir() or parent.is_symlink():
            raise SecExecutionStop("SEC_EXECUTION_JOURNAL_ROOT_INVALID")
        paths = tuple(parent.iterdir())
        if any(
            not path.is_dir()
            or path.is_symlink()
            or path.name != self._wire.request_identity
            for path in paths
        ):
            raise SecExecutionStop("SEC_EXECUTION_JOURNAL_REQUEST_ORPHAN_DRIFT")

    def events(self) -> tuple[dict[str, object], ...]:
        if not self._journal_root.exists():
            return ()
        paths = sorted(self._journal_root.iterdir())
        events: list[dict[str, object]] = []
        previous_hash: str | None = None
        previous_recorded = -1
        for expected_sequence, path in enumerate(paths, start=1):
            matched = _EVENT_NAME.fullmatch(path.name)
            if not path.is_file() or path.is_symlink() or matched is None:
                raise SecExecutionStop("SEC_EXECUTION_JOURNAL_UNEXPECTED_ARTIFACT")
            try:
                event = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as error:
                raise SecExecutionStop("SEC_EXECUTION_JOURNAL_EVENT_UNREADABLE") from error
            claimed_hash = event.get("eventHash")
            body = {key: value for key, value in event.items() if key != "eventHash"}
            recorded = event.get("recordedAtEpochMicros")
            if (
                set(event)
                != {
                    "journalVersion",
                    "runId",
                    "stage8cContractContentHash",
                    "requestContractContentHash",
                    "authorizationContentHash",
                    "requestIdentity",
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
                or event.get("stage8cContractContentHash")
                != STAGE8C_V16_CONTRACT_CONTENT_HASH
                or event.get("requestContractContentHash")
                != SEC_REQUEST_CONTRACT_CONTENT_HASH
                or event.get("authorizationContentHash")
                != self._authorization.content_hash
                or event.get("requestIdentity") != self._wire.request_identity
                or event.get("sequence") != expected_sequence
                or event.get("previousEventHash") != previous_hash
                or type(recorded) is not int
                or recorded < 0
                or recorded < previous_recorded
                or not isinstance(event.get("detail"), dict)
            ):
                raise SecExecutionStop("SEC_EXECUTION_JOURNAL_EVENT_CHAIN_DRIFT")
            events.append(event)
            previous_hash = str(claimed_hash)
            previous_recorded = recorded
        states = [item["state"] for item in events]
        if states not in ([], ["INTENT"], ["INTENT", "COMPLETED"], ["INTENT", "FAILED"]):
            raise SecExecutionStop("SEC_EXECUTION_JOURNAL_EVENT_GRAMMAR_DRIFT")
        if events:
            dispatch = events[0]["detail"].get("dispatchMonotonicMicros")
            if (
                type(dispatch) is not int
                or dispatch < 0
                or events[0]["detail"] != _intent_detail(self._wire, dispatch)
            ):
                raise SecExecutionStop("SEC_EXECUTION_JOURNAL_INTENT_DRIFT")
        return tuple(events)

    def _checkpoint_relative(self) -> str:
        return f"_private/checkpoints/{self._wire.request_identity}.bin"

    def _audit_checkpoint(self) -> None:
        if not self._checkpoint_root.exists():
            return
        if not self._checkpoint_root.is_dir() or self._checkpoint_root.is_symlink():
            raise SecExecutionStop("SEC_EXECUTION_CHECKPOINT_ROOT_INVALID")
        paths = tuple(self._checkpoint_root.iterdir())
        if any(
            not path.is_file()
            or path.is_symlink()
            or _CHECKPOINT_NAME.fullmatch(path.name) is None
            or path.stem != self._wire.request_identity
            for path in paths
        ):
            raise SecExecutionStop("SEC_EXECUTION_CHECKPOINT_ORPHAN_OR_PATH_DRIFT")
        if paths:
            events = self.events()
            if len(events) != 2 or events[-1]["state"] != "COMPLETED":
                raise SecExecutionStop("SEC_EXECUTION_CHECKPOINT_ORPHAN_OR_PATH_DRIFT")

    def _audit_terminal_state(self) -> None:
        events = self.events()
        if len(events) == 1:
            raise SecExecutionStop("SEC_EXECUTION_UNMATCHED_INTENT_STOP")
        if events and events[-1]["state"] == "FAILED":
            raise SecExecutionStop("SEC_EXECUTION_FAILED_REQUEST_STOP")
        if events:
            self.replay(events[-1])

    def append(self, state: str, detail: dict[str, object]) -> dict[str, object]:
        events = self.events()
        if (not events and state != "INTENT") or (
            events and (len(events) != 1 or state not in {"COMPLETED", "FAILED"})
        ):
            raise SecExecutionStop("SEC_EXECUTION_JOURNAL_INVALID_TRANSITION")
        recorded = self._wall_clock()
        if type(recorded) not in {int, float} or not math.isfinite(recorded) or recorded < 0:
            raise SecExecutionStop("SEC_EXECUTION_WALL_CLOCK_INVALID")
        body: dict[str, object] = {
            "journalVersion": JOURNAL_VERSION,
            "runId": self._authorization.run_id,
            "stage8cContractContentHash": STAGE8C_V16_CONTRACT_CONTENT_HASH,
            "requestContractContentHash": SEC_REQUEST_CONTRACT_CONTENT_HASH,
            "authorizationContentHash": self._authorization.content_hash,
            "requestIdentity": self._wire.request_identity,
            "sequence": len(events) + 1,
            "previousEventHash": events[-1]["eventHash"] if events else None,
            "state": state,
            "recordedAtEpochMicros": int(recorded * 1_000_000),
            "detail": detail,
        }
        body["eventHash"] = canonical_hash(body)
        path = self._journal_root / f"{len(events) + 1:03d}-{state}.json"
        try:
            _atomic_json_create(path, body)
        except FileExistsError as error:
            raise SecExecutionStop("SEC_EXECUTION_JOURNAL_EVENT_CREATE_RACE") from error
        return body

    def write_checkpoint(self, body: bytes) -> str:
        relative = self._checkpoint_relative()
        path = self._run_root / PurePosixPath(relative)
        if path.exists():
            raise SecExecutionStop("SEC_EXECUTION_CHECKPOINT_ALREADY_EXISTS")
        try:
            _atomic_bytes_create(path, body)
        except FileExistsError as error:
            raise SecExecutionStop("SEC_EXECUTION_CHECKPOINT_CREATE_RACE") from error
        return relative

    def replay(self, completed_event: dict[str, object]) -> TransportResponse:
        if completed_event.get("state") != "COMPLETED":
            raise SecExecutionStop("SEC_EXECUTION_COMPLETED_EVENT_REQUIRED")
        detail = completed_event.get("detail")
        if not isinstance(detail, dict):
            raise SecExecutionStop("SEC_EXECUTION_COMPLETED_DETAIL_INVALID")
        raw_relative = detail.get("checkpointPath")
        if type(raw_relative) is not str:
            raise SecExecutionStop("SEC_EXECUTION_CHECKPOINT_PATH_INVALID")
        relative = PurePosixPath(raw_relative)
        if (
            relative.is_absolute()
            or ".." in relative.parts
            or "." in relative.parts
            or "\\" in raw_relative
            or raw_relative != self._checkpoint_relative()
        ):
            raise SecExecutionStop("SEC_EXECUTION_UNSAFE_CHECKPOINT_PATH")
        path = (self._run_root / relative).resolve()
        try:
            path.relative_to(self._run_root)
        except ValueError as error:
            raise SecExecutionStop("SEC_EXECUTION_UNSAFE_CHECKPOINT_PATH") from error
        if not path.is_file() or path.is_symlink():
            raise SecExecutionStop("SEC_EXECUTION_CHECKPOINT_MISSING")
        raw_headers = detail.get("responseHeaders")
        if not isinstance(raw_headers, list) or any(
            not isinstance(item, list)
            or len(item) != 2
            or not all(type(part) is str for part in item)
            for item in raw_headers
        ):
            raise SecExecutionStop("SEC_EXECUTION_REPLAY_HEADERS_INVALID")
        response = TransportResponse(
            status_code=detail.get("statusCode"),
            headers=tuple((item[0], item[1]) for item in raw_headers),
            body=path.read_bytes(),
        )
        if detail != _completed_detail(
            self._wire,
            response,
            checkpoint_path=raw_relative,
            runtime_user_agent=self._runtime_user_agent,
        ):
            raise SecExecutionStop("SEC_EXECUTION_COMPLETED_DETAIL_DRIFT")
        return response


def _lease_id(authorization: SecPhaseAuthorizationV16) -> str:
    return canonical_hash(
        {
            "executionContractVersion": EXECUTION_CONTRACT_VERSION,
            "runId": authorization.run_id,
            "stage8cContractContentHash": STAGE8C_V16_CONTRACT_CONTENT_HASH,
            "requestContractContentHash": SEC_REQUEST_CONTRACT_CONTENT_HASH,
            "authorizationContentHash": authorization.content_hash,
        }
    )


def _result_body(value: SecExecutionResultV16, *, include_hash: bool) -> dict[str, object]:
    body: dict[str, object] = {
        "summaryVersion": SUMMARY_VERSION,
        "runId": value.run_id,
        "stage8cContractContentHash": value.stage8c_contract_content_hash,
        "requestContractContentHash": value.request_contract_content_hash,
        "authorizationContentHash": value.authorization_content_hash,
        "physicalRequestCount": value.physical_request_count,
        "newPhysicalRequestCount": value.new_physical_request_count,
        "replayedPhysicalRequestCount": value.replayed_physical_request_count,
        "retryLimit": value.retry_limit,
        "responseBodySha256": value.response_body_sha256,
        "responseHeadersHash": value.response_headers_hash,
        "terminalEventHash": value.terminal_event_hash,
        "runtimeUserAgentValuePersisted": False,
        "runtimeUserAgentValueHashed": False,
        "rawResponseContentIncluded": False,
    }
    if include_hash:
        body["contentHash"] = value.content_hash
    return body


def git_safe_sec_execution_summary_v16(
    value: SecExecutionResultV16, *, runtime_user_agent: object
) -> dict[str, object]:
    validate_sec_execution_result_v16(value, runtime_user_agent=runtime_user_agent)
    return _result_body(value, include_hash=True)


def validate_sec_execution_result_v16(
    value: SecExecutionResultV16, *, runtime_user_agent: object
) -> None:
    try:
        user_agent = validate_runtime_sec_user_agent_v16(runtime_user_agent)
    except Stage8CV16Stop as error:
        raise SecExecutionStop(error.code) from error
    if type(value) is not SecExecutionResultV16:
        raise SecExecutionStop("SEC_EXECUTION_RESULT_TYPE_INVALID")
    if (
        type(value.run_id) is not str
        or _RUN_ID.fullmatch(value.run_id) is None
        or value.stage8c_contract_content_hash != STAGE8C_V16_CONTRACT_CONTENT_HASH
        or value.request_contract_content_hash != SEC_REQUEST_CONTRACT_CONTENT_HASH
        or not _is_upper_sha256(value.authorization_content_hash)
        or type(value.physical_request_count) is not int
        or value.physical_request_count != 1
        or type(value.new_physical_request_count) is not int
        or value.new_physical_request_count not in {0, 1}
        or type(value.replayed_physical_request_count) is not int
        or value.replayed_physical_request_count not in {0, 1}
        or value.new_physical_request_count + value.replayed_physical_request_count != 1
        or type(value.retry_limit) is not int
        or value.retry_limit != 0
        or not _is_upper_sha256(value.response_body_sha256)
        or not _is_upper_sha256(value.response_headers_hash)
        or not _is_upper_sha256(value.terminal_event_hash)
        or type(value.response) is not TransportResponse
        or not _is_upper_sha256(value.content_hash)
    ):
        raise SecExecutionStop("SEC_EXECUTION_RESULT_BINDING_DRIFT")
    binding = _response_binding(value.response, runtime_user_agent=user_agent)
    if (
        binding["bodySha256"] != value.response_body_sha256
        or binding["responseHeadersHash"] != value.response_headers_hash
        or value.content_hash != canonical_hash(_result_body(value, include_hash=False))
    ):
        raise SecExecutionStop("SEC_EXECUTION_RESULT_RESPONSE_DRIFT")


def _checkpoint_receipt_body(
    wire: ProviderWireRequest,
    response: TransportResponse,
    terminal_event_hash: str,
    *,
    runtime_user_agent: str,
) -> dict[str, object]:
    binding = _response_binding(response, runtime_user_agent=runtime_user_agent)
    return {
        "requestIdentity": wire.request_identity,
        "wireBindingHash": canonical_hash(_wire_binding(wire)),
        "statusCode": response.status_code,
        "responseHeadersHash": binding["responseHeadersHash"],
        "bodySha256": binding["bodySha256"],
        "bodyByteCount": binding["bodyByteCount"],
        "terminalEventHash": terminal_event_hash,
    }


def _replay_body(
    value: SecReplayVerificationV16, *, include_hash: bool
) -> dict[str, object]:
    body: dict[str, object] = {
        "replayVersion": REPLAY_VERSION,
        "runId": value.run_id,
        "stage8cContractContentHash": value.stage8c_contract_content_hash,
        "requestContractContentHash": value.request_contract_content_hash,
        "authorizationContentHash": value.authorization_content_hash,
        "checkpointReceiptHash": value.checkpoint_receipt_hash,
        "reviewContentHash": value.review_content_hash,
        "responseBodySha256": value.response_body_sha256,
        "responseHeadersHash": value.response_headers_hash,
        "terminalEventHash": value.terminal_event_hash,
        "replayedPhysicalRequestCount": value.replayed_physical_request_count,
        "networkRequestsSent": 0,
        "rawResponseContentIncluded": False,
    }
    if include_hash:
        body["contentHash"] = value.content_hash
    return body


def validate_sec_replay_verification_v16(value: SecReplayVerificationV16) -> None:
    if type(value) is not SecReplayVerificationV16:
        raise SecExecutionStop("SEC_EXECUTION_REPLAY_TYPE_INVALID")
    if (
        type(value.run_id) is not str
        or _RUN_ID.fullmatch(value.run_id) is None
        or value.stage8c_contract_content_hash != STAGE8C_V16_CONTRACT_CONTENT_HASH
        or value.request_contract_content_hash != SEC_REQUEST_CONTRACT_CONTENT_HASH
        or not _is_upper_sha256(value.authorization_content_hash)
        or not _is_upper_sha256(value.checkpoint_receipt_hash)
        or not _is_upper_sha256(value.review_content_hash)
        or not _is_upper_sha256(value.response_body_sha256)
        or not _is_upper_sha256(value.response_headers_hash)
        or not _is_upper_sha256(value.terminal_event_hash)
        or type(value.replayed_physical_request_count) is not int
        or value.replayed_physical_request_count != 1
        or not _is_upper_sha256(value.content_hash)
        or value.content_hash != canonical_hash(_replay_body(value, include_hash=False))
    ):
        raise SecExecutionStop("SEC_EXECUTION_REPLAY_DRIFT")


def _storage_acceptance_body(
    value: StorageBackedSecCorroborationAcceptanceV16, *, include_hash: bool
) -> dict[str, object]:
    body: dict[str, object] = {
        "storageAcceptanceVersion": value.storage_acceptance_version,
        "runId": value.run_id,
        "stage8cContractContentHash": value.stage8c_contract_content_hash,
        "requestContractContentHash": value.request_contract_content_hash,
        "predecessorV15ResultContentHash": value.predecessor_v15_result_content_hash,
        "authorizationContentHash": value.authorization_content_hash,
        "replayVerificationContentHash": value.replay_verification_content_hash,
        "checkpointReceiptHash": value.checkpoint_receipt_hash,
        "reviewContentHash": value.review_content_hash,
        "accepted": value.accepted,
        "decisionCode": value.decision_code,
        "supportedMappingCount": value.supported_mapping_count,
        "canonicalOperatingMic": value.canonical_operating_mic,
        "claim": value.claim,
        "corroborationOnly": value.corroboration_only,
        "diagnosticOnly": value.diagnostic_only,
        "segmentClaimed": value.segment_claimed,
        "tierClaimed": value.tier_claimed,
        "exchangeHistoryClaimed": value.exchange_history_claimed,
        "listingFigiClaimed": value.listing_figi_claimed,
        "currencyClaimed": value.currency_claimed,
        "completedSessionClaimed": value.completed_session_claimed,
        "databaseReadAuthorized": value.database_read_authorized,
        "databaseWriteAuthorized": value.database_write_authorized,
        "v22WriteAuthorized": value.v22_write_authorized,
        "v24WriteAuthorized": value.v24_write_authorized,
        "projectionAuthorized": value.projection_authorized,
        "evidenceLabelUpgradeAuthorized": value.evidence_label_upgrade_authorized,
        "storageReplayRequired": True,
        "runtimeUserAgentValuePersisted": False,
        "runtimeUserAgentValueHashed": False,
        "rawResponseContentIncluded": False,
    }
    if include_hash:
        body["contentHash"] = value.content_hash
    return body


def verify_sec_review_from_storage_v16(
    authorization: SecPhaseAuthorizationV16,
    expected_review: SecCorroborationReviewV16,
    *,
    storage_root: Path,
    runtime_user_agent: object,
    wall_clock: Callable[[], float] = time.time,
) -> tuple[SecCorroborationReviewV16, SecReplayVerificationV16]:
    validate_sec_phase_authorization_v16(authorization)
    if authorization.network_authorized is not True:
        raise SecExecutionStop("SEC_EXECUTION_NETWORK_NOT_AUTHORIZED")
    if not authorization.test_only and wall_clock is not time.time:
        raise SecExecutionStop("SEC_EXECUTION_PRODUCTION_CLOCK_INJECTION_BLOCKED")
    try:
        user_agent = validate_runtime_sec_user_agent_v16(runtime_user_agent)
    except Stage8CV16Stop as error:
        raise SecExecutionStop(error.code) from error
    wire = _build_wire()
    run_root = sec_run_root_v16(storage_root, authorization)
    if (
        not run_root.is_dir()
        or run_root.is_symlink()
        or not (run_root / "plan-authorization.json").is_file()
    ):
        raise SecExecutionStop("SEC_EXECUTION_COMPLETED_RUN_NOT_FOUND")
    try:
        with ExecutionLease(
            run_root / ".lock", _lease_id(authorization), heartbeat_interval_seconds=3_600.0
        ):
            journal = _SecExecutionJournal(
                run_root,
                authorization,
                wire,
                runtime_user_agent=user_agent,
                wall_clock=wall_clock,
            )
            events = journal.events()
            if len(events) != 2 or events[-1]["state"] != "COMPLETED":
                raise SecExecutionStop("SEC_EXECUTION_COMPLETED_RUN_INCOMPLETE")
            response = journal.replay(events[-1])
            terminal_hash = str(events[-1]["eventHash"])
    except SecExecutionStop:
        raise
    except RuntimeError as error:
        raise SecExecutionStop(str(error)) from error
    try:
        replay_review = build_sec_corroboration_review_v16(response.body)
        validate_sec_corroboration_review_v16(replay_review)
    except (Stage8CV16Stop, TypeError, ValueError) as error:
        raise SecExecutionStop("SEC_EXECUTION_STORAGE_REVIEW_REBUILD_FAILED") from error
    if type(expected_review) is not SecCorroborationReviewV16 or replay_review != expected_review:
        raise SecExecutionStop("SEC_EXECUTION_STORAGE_REVIEW_REPLAY_DRIFT")
    binding = _response_binding(response, runtime_user_agent=user_agent)
    receipt_hash = canonical_hash(
        _checkpoint_receipt_body(
            wire,
            response,
            terminal_hash,
            runtime_user_agent=user_agent,
        )
    )
    provisional = SecReplayVerificationV16(
        run_id=authorization.run_id,
        stage8c_contract_content_hash=STAGE8C_V16_CONTRACT_CONTENT_HASH,
        request_contract_content_hash=SEC_REQUEST_CONTRACT_CONTENT_HASH,
        authorization_content_hash=authorization.content_hash,
        checkpoint_receipt_hash=receipt_hash,
        review_content_hash=replay_review.content_hash,
        response_body_sha256=str(binding["bodySha256"]),
        response_headers_hash=str(binding["responseHeadersHash"]),
        terminal_event_hash=terminal_hash,
        replayed_physical_request_count=1,
        content_hash="",
    )
    verification = SecReplayVerificationV16(
        **{
            **asdict(provisional),
            "content_hash": canonical_hash(_replay_body(provisional, include_hash=False)),
        }
    )
    validate_sec_replay_verification_v16(verification)
    return replay_review, verification


def seal_storage_backed_sec_corroboration_v16(
    authorization: SecPhaseAuthorizationV16,
    expected_review: SecCorroborationReviewV16,
    *,
    storage_root: Path,
    runtime_user_agent: object,
) -> tuple[SecReplayVerificationV16, StorageBackedSecCorroborationAcceptanceV16]:
    """Mechanically accept or reject only after exact private-storage replay."""

    review, verification = verify_sec_review_from_storage_v16(
        authorization,
        expected_review,
        storage_root=storage_root,
        runtime_user_agent=runtime_user_agent,
    )
    accepted = review.accepted
    decision_code = ACCEPTED_DECISION_CODE if accepted else REJECTED_DECISION_CODE
    provisional = StorageBackedSecCorroborationAcceptanceV16(
        storage_acceptance_version=STORAGE_ACCEPTANCE_VERSION,
        run_id=authorization.run_id,
        stage8c_contract_content_hash=STAGE8C_V16_CONTRACT_CONTENT_HASH,
        request_contract_content_hash=SEC_REQUEST_CONTRACT_CONTENT_HASH,
        predecessor_v15_result_content_hash=PREDECESSOR_V15_RESULT_CONTENT_HASH,
        authorization_content_hash=authorization.content_hash,
        replay_verification_content_hash=verification.content_hash,
        checkpoint_receipt_hash=verification.checkpoint_receipt_hash,
        review_content_hash=review.content_hash,
        accepted=accepted,
        decision_code=decision_code,
        supported_mapping_count=review.supported_mapping_count,
        canonical_operating_mic=CANONICAL_OPERATING_MIC if accepted else None,
        claim=SEC_MAPPING_CLAIM,
        corroboration_only=True,
        diagnostic_only=True,
        segment_claimed=False,
        tier_claimed=False,
        exchange_history_claimed=False,
        listing_figi_claimed=False,
        currency_claimed=False,
        completed_session_claimed=False,
        database_read_authorized=False,
        database_write_authorized=False,
        v22_write_authorized=False,
        v24_write_authorized=False,
        projection_authorized=False,
        evidence_label_upgrade_authorized=False,
        content_hash="",
    )
    acceptance = StorageBackedSecCorroborationAcceptanceV16(
        **{
            **asdict(provisional),
            "content_hash": canonical_hash(
                _storage_acceptance_body(provisional, include_hash=False)
            ),
        }
    )
    validate_storage_backed_sec_corroboration_v16(
        authorization,
        expected_review,
        verification,
        acceptance,
        storage_root=storage_root,
        runtime_user_agent=runtime_user_agent,
    )
    return verification, acceptance


def validate_storage_backed_sec_corroboration_v16(
    authorization: SecPhaseAuthorizationV16,
    expected_review: SecCorroborationReviewV16,
    verification: SecReplayVerificationV16,
    acceptance: StorageBackedSecCorroborationAcceptanceV16,
    *,
    storage_root: Path,
    runtime_user_agent: object,
) -> None:
    review, replay_verification = verify_sec_review_from_storage_v16(
        authorization,
        expected_review,
        storage_root=storage_root,
        runtime_user_agent=runtime_user_agent,
    )
    validate_sec_replay_verification_v16(verification)
    if replay_verification != verification:
        raise SecExecutionStop("SEC_EXECUTION_REPLAY_VERIFICATION_DRIFT")
    accepted = review.accepted
    if type(acceptance) is not StorageBackedSecCorroborationAcceptanceV16 or (
        acceptance.storage_acceptance_version != STORAGE_ACCEPTANCE_VERSION
        or acceptance.run_id != authorization.run_id
        or acceptance.stage8c_contract_content_hash != STAGE8C_V16_CONTRACT_CONTENT_HASH
        or acceptance.request_contract_content_hash != SEC_REQUEST_CONTRACT_CONTENT_HASH
        or acceptance.predecessor_v15_result_content_hash
        != PREDECESSOR_V15_RESULT_CONTENT_HASH
        or acceptance.authorization_content_hash != authorization.content_hash
        or acceptance.replay_verification_content_hash != verification.content_hash
        or acceptance.checkpoint_receipt_hash != verification.checkpoint_receipt_hash
        or acceptance.review_content_hash != review.content_hash
        or type(acceptance.accepted) is not bool
        or acceptance.accepted is not accepted
        or acceptance.decision_code
        != (ACCEPTED_DECISION_CODE if accepted else REJECTED_DECISION_CODE)
        or acceptance.supported_mapping_count != review.supported_mapping_count
        or acceptance.canonical_operating_mic
        != (CANONICAL_OPERATING_MIC if accepted else None)
        or acceptance.claim != SEC_MAPPING_CLAIM
        or acceptance.corroboration_only is not True
        or acceptance.diagnostic_only is not True
        or acceptance.segment_claimed is not False
        or acceptance.tier_claimed is not False
        or acceptance.exchange_history_claimed is not False
        or acceptance.listing_figi_claimed is not False
        or acceptance.currency_claimed is not False
        or acceptance.completed_session_claimed is not False
        or acceptance.database_read_authorized is not False
        or acceptance.database_write_authorized is not False
        or acceptance.v22_write_authorized is not False
        or acceptance.v24_write_authorized is not False
        or acceptance.projection_authorized is not False
        or acceptance.evidence_label_upgrade_authorized is not False
        or not _is_upper_sha256(acceptance.content_hash)
        or acceptance.content_hash
        != canonical_hash(_storage_acceptance_body(acceptance, include_hash=False))
    ):
        raise SecExecutionStop("SEC_EXECUTION_STORAGE_ACCEPTANCE_DRIFT")


def _monotonic_micros(clock: Callable[[], float]) -> int:
    value = clock()
    if type(value) not in {int, float} or not math.isfinite(value) or value < 0:
        raise SecExecutionStop("SEC_EXECUTION_MONOTONIC_CLOCK_INVALID")
    return int(value * 1_000_000)


def execute_sec_corroboration_v16(
    authorization: SecPhaseAuthorizationV16,
    *,
    storage_root: Path,
    transport: SecTransportV16,
    runtime_user_agent: object,
    monotonic_clock: Callable[[], float] = time.monotonic,
    wall_clock: Callable[[], float] = time.time,
) -> SecExecutionResultV16:
    """Execute once or exactly replay the one frozen SEC GET under one lease."""

    validate_sec_phase_authorization_v16(authorization)
    if authorization.network_authorized is not True:
        raise SecExecutionStop("SEC_EXECUTION_NETWORK_NOT_AUTHORIZED")
    try:
        validated_user_agent = validate_runtime_sec_user_agent_v16(runtime_user_agent)
    except Stage8CV16Stop as error:
        raise SecExecutionStop(error.code) from error
    wire = _build_wire()
    _wire_binding(wire)
    _validate_transport_boundary(transport, authorization, wire, validated_user_agent)
    if not authorization.test_only and (
        monotonic_clock is not time.monotonic or wall_clock is not time.time
    ):
        raise SecExecutionStop("SEC_EXECUTION_PRODUCTION_CLOCK_INJECTION_BLOCKED")
    approved_root = _validated_storage_root(
        storage_root, test_only=authorization.test_only
    )
    run_root = sec_run_root_v16(storage_root, authorization)
    _assert_no_symlink(run_root, stop=approved_root)
    run_root.mkdir(parents=True, exist_ok=True)
    if run_root.is_symlink() or run_root.resolve() != run_root:
        raise SecExecutionStop("SEC_EXECUTION_STORAGE_SYMLINK_STOP")
    try:
        with ExecutionLease(
            run_root / ".lock", _lease_id(authorization), heartbeat_interval_seconds=3_600.0
        ) as lease:
            journal = _SecExecutionJournal(
                run_root,
                authorization,
                wire,
                runtime_user_agent=validated_user_agent,
                wall_clock=wall_clock,
            )
            events = journal.events()
            if len(events) == 2:
                response = journal.replay(events[-1])
                terminal = str(events[-1]["eventHash"])
                new_count = 0
                replayed_count = 1
            elif events:
                raise SecExecutionStop("SEC_EXECUTION_UNMATCHED_INTENT_STOP")
            else:
                dispatch = _monotonic_micros(monotonic_clock)
                intent = journal.append("INTENT", _intent_detail(wire, dispatch))
                lease.heartbeat()
                try:
                    response = transport.send(wire)
                except Exception as error:
                    raise SecExecutionStop("SEC_EXECUTION_UNKNOWN_TRANSPORT_OUTCOME") from error
                _response_binding(response, runtime_user_agent=validated_user_agent)
                relative = journal.write_checkpoint(response.body)
                completed = journal.append(
                    "COMPLETED",
                    _completed_detail(
                        wire,
                        response,
                        checkpoint_path=relative,
                        runtime_user_agent=validated_user_agent,
                    ),
                )
                if completed["previousEventHash"] != intent["eventHash"]:
                    raise SecExecutionStop("SEC_EXECUTION_JOURNAL_EVENT_CHAIN_DRIFT")
                replayed = journal.replay(completed)
                if replayed != response:
                    raise SecExecutionStop("SEC_EXECUTION_POST_WRITE_REPLAY_DRIFT")
                response = replayed
                terminal = str(completed["eventHash"])
                new_count = 1
                replayed_count = 0
            lease.heartbeat()
    except SecExecutionStop:
        raise
    except RuntimeError as error:
        raise SecExecutionStop(str(error)) from error
    binding = _response_binding(response, runtime_user_agent=validated_user_agent)
    provisional = SecExecutionResultV16(
        run_id=authorization.run_id,
        stage8c_contract_content_hash=STAGE8C_V16_CONTRACT_CONTENT_HASH,
        request_contract_content_hash=SEC_REQUEST_CONTRACT_CONTENT_HASH,
        authorization_content_hash=authorization.content_hash,
        physical_request_count=1,
        new_physical_request_count=new_count,
        replayed_physical_request_count=replayed_count,
        retry_limit=0,
        response_body_sha256=str(binding["bodySha256"]),
        response_headers_hash=str(binding["responseHeadersHash"]),
        terminal_event_hash=terminal,
        response=response,
        content_hash="",
    )
    result = SecExecutionResultV16(
        **{
            **asdict(provisional),
            "response": provisional.response,
            "content_hash": canonical_hash(_result_body(provisional, include_hash=False)),
        }
    )
    validate_sec_execution_result_v16(
        result, runtime_user_agent=validated_user_agent
    )
    return result


__all__ = [
    "ACCEPTED_DECISION_CODE",
    "AUTHORITY_BASIS",
    "CONTROLLER_AUTHORITY_CONTENT_HASH",
    "EXECUTION_CONTRACT_VERSION",
    "EXECUTION_SCOPE",
    "PREDECESSOR_V15_RESULT_CONTENT_HASH",
    "REJECTED_DECISION_CODE",
    "SEC_REQUEST_CONTRACT_CONTENT_HASH",
    "STAGE8C_V16_CONTRACT_CONTENT_HASH",
    "SecExecutionResultV16",
    "SecExecutionStop",
    "SecPhaseAuthorizationV16",
    "SecReplayVerificationV16",
    "StorageBackedSecCorroborationAcceptanceV16",
    "execute_sec_corroboration_v16",
    "git_safe_sec_execution_summary_v16",
    "seal_sec_phase_authorization_v16",
    "seal_storage_backed_sec_corroboration_v16",
    "sec_run_root_v16",
    "validate_sec_execution_result_v16",
    "validate_sec_phase_authorization_v16",
    "validate_sec_replay_verification_v16",
    "validate_storage_backed_sec_corroboration_v16",
    "verify_sec_review_from_storage_v16",
]
