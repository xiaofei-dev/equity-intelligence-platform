"""Preregistered, migration-free OpenFIGI Stage 8C v1.4 diagnostic.

This module deliberately owns no transport.  It freezes ten public-identifier
mapping jobs into two provider wire requests, validates supplied response bytes,
and admits an acceptance only when every identifier resolves to one primary
identity and both identifiers for every security converge.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any

from equity_analysis.fundamental_value.prospective_company_quality_acquisition_v1 import (
    OPENFIGI_TICKER_ALIAS_POLICY_VERSION,
    ProviderWireRequest,
    TransportResponse,
    canonical_openfigi_ticker_for_expected_v1,
)

CONTRACT_VERSION = "FV-STAGE8C-OPENFIGI-DIAGNOSTIC-v1.4.0"
PLAN_VERSION = "FV-STAGE8C-OPENFIGI-DIAGNOSTIC-PLAN-v1.0.0"
PROVIDER_ORIGIN = "https://api.openfigi.com"
REQUEST_FILTER_POLICY_VERSION = "FV-STAGE8C-OPENFIGI-REQUEST-FILTER-POLICY-v1.0.0"
PAIR_IDENTITY_CONTRACT_VERSION = "FV-STAGE8C-OPENFIGI-PAIR-IDENTITY-v1.0.0"
REVIEW_VERSION = "FV-STAGE8C-OPENFIGI-DIAGNOSTIC-REVIEW-v1.0.0"
ACCEPTANCE_VERSION = "FV-STAGE8C-OPENFIGI-DIAGNOSTIC-ACCEPTANCE-v1.0.0"
ACCEPTED_DECISION_CODE = "DIAGNOSTIC_COMPLETE_CONVERGENT"
OPERATING_MIC_BINDING_STATUS = "REQUIRES_SEC_CORROBORATION"
PREDECESSOR_REJECTED_PLAN_CONTENT_HASH = (
    "0B05F1896B9F43D3C13918A0CA8E6D377FADF6F08F75B44F62EBA4048BA88D57"
)
PREDECESSOR_RESULT_CANONICAL_HASH = (
    "8F054E4C63897FCD6217B48507FDDB52EF805AC35D7E12F0ACEC7909199F5B99"
)
ENDPOINT_PATH = "/v3/mapping"
MAX_JOBS_PER_REQUEST = 5
PHYSICAL_REQUEST_COUNT = 2
LOGICAL_JOB_COUNT = 10
MEMBER_COUNT = 5
RETRY_LIMIT = 0
MAX_PROVIDER_MESSAGE_LENGTH = 4096
MAX_PROVIDER_ENVELOPE_TICKER_LENGTH = 256
OMITTED_OPERATING_MIC_POLICY = "OMITTED_OPERATING_MIC_NO_SEGMENT_AUTHORITY"
EXACT_OPERATING_MIC_POLICY = "EXACT_OPERATING_MIC"

_SHA256_LOWER = re.compile(r"sha256:[0-9a-f]{64}\Z")
_UPPER_SHA256 = re.compile(r"[0-9A-F]{64}\Z")
_FIGI = re.compile(r"BBG[A-Z0-9]{9}\Z")
_ISIN = re.compile(r"[A-Z]{2}[A-Z0-9]{10}\Z")
_CUSIP_OR_CINS = re.compile(r"[A-Z0-9*@#]{9}\Z")
_SYMBOL = re.compile(r"[A-Z0-9][A-Z0-9.-]{0,31}\Z")
_MIC = re.compile(r"[A-Z0-9]{4}\Z")
_OPENFIGI_PROVIDER_TICKER = re.compile(
    r"(?=.{1,32}\Z)(?:[A-Z0-9][A-Z0-9.-]*|[A-Z0-9]+/[A-Z0-9]+)\Z"
)
_EXCHANGE_CODE = re.compile(r"[A-Z0-9]{1,16}\Z")
_DECISION = re.compile(r"[A-Z][A-Z0-9_]{2,127}\Z")


class DiagnosticStop(RuntimeError):
    """Fail-closed diagnostic stop with a stable machine-readable code."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class SecondaryIdentifierType(StrEnum):
    CUSIP = "ID_CUSIP"
    CINS = "ID_CINS"


class DiagnosticOutcomeState(StrEnum):
    UNIQUE_PRIMARY = "UNIQUE_PRIMARY"
    AMBIGUOUS_PRIMARY = "AMBIGUOUS_PRIMARY"
    UNRESOLVED_WARNING = "UNRESOLVED_WARNING"
    UNRESOLVED_ERROR = "UNRESOLVED_ERROR"
    NO_PRIMARY = "NO_PRIMARY"


@dataclass(frozen=True)
class DiagnosticMember:
    member_ordinal: int
    security_id: str
    symbol: str
    expected_operating_mic: str
    request_mic_code: str | None
    request_filter_policy: str
    isin: str
    secondary_identifier_type: SecondaryIdentifierType
    secondary_identifier_value: str
    source_content_hash: str


@dataclass(frozen=True)
class DiagnosticJob:
    job_ordinal: int
    member_ordinal: int
    security_id: str
    expected_symbol: str
    expected_operating_mic: str
    request_mic_code: str | None
    request_filter_policy: str
    identifier_type: str
    identifier_value: str
    content_hash: str


@dataclass(frozen=True)
class DiagnosticRequest:
    request_ordinal: int
    request_identity: str
    jobs: tuple[DiagnosticJob, ...]
    body_sha256: str
    wire_content_hash: str


@dataclass(frozen=True)
class DiagnosticPlan:
    contract_version: str
    plan_version: str
    predecessor_rejected_plan_content_hash: str
    predecessor_result_canonical_hash: str
    provider_origin: str
    endpoint_path: str
    request_filter_policy_version: str
    ticker_alias_policy_version: str
    pair_identity_contract_version: str
    max_jobs_per_request: int
    physical_request_count: int
    logical_job_count: int
    member_count: int
    retry_limit: int
    network_authorized: bool
    members: tuple[DiagnosticMember, ...]
    requests: tuple[DiagnosticRequest, ...]
    content_hash: str


@dataclass(frozen=True)
class DiagnosticJobReview:
    request_identity: str
    logical_ordinal: int
    job_ordinal: int
    security_id: str
    identifier_type: str
    identifier_value: str
    response_kind: str
    candidate_count: int
    primary_match_count: int
    primary_provider_identity_hash: str | None
    outcome_state: DiagnosticOutcomeState
    content_hash: str


@dataclass(frozen=True)
class DiagnosticPairReview:
    member_ordinal: int
    security_id: str
    first_identifier_type: str
    second_identifier_type: str
    first_primary_provider_identity_hash: str | None
    second_primary_provider_identity_hash: str | None
    complete_convergent: bool
    conflict: bool
    content_hash: str


@dataclass(frozen=True)
class DiagnosticReview:
    plan_content_hash: str
    physical_request_count: int
    logical_job_count: int
    unique_primary_count: int
    warning_count: int
    error_count: int
    ambiguous_primary_count: int
    no_primary_count: int
    complete_convergent_pair_count: int
    pair_conflict_count: int
    jobs: tuple[DiagnosticJobReview, ...]
    pairs: tuple[DiagnosticPairReview, ...]
    content_hash: str


@dataclass(frozen=True)
class DiagnosticAcceptance:
    plan_content_hash: str
    review_content_hash: str
    accepted: bool
    decision_code: str
    diagnostic_only: bool
    durable_identity_authorized: bool
    remainder_authorized: bool
    operating_mic_binding_status: str
    content_hash: str


def canonical_hash(value: object) -> str:
    return (
        hashlib.sha256(
            json.dumps(
                value,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
                default=str,
            ).encode("utf-8")
        )
        .hexdigest()
        .upper()
    )


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest().upper()


def _strict_json_loads(value: bytes) -> object:
    def object_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, item in pairs:
            if key in result:
                raise DiagnosticStop("DIAGNOSTIC_RESPONSE_JSON_DUPLICATE_KEY")
            result[key] = item
        return result

    def reject_constant(_value: str) -> object:
        raise DiagnosticStop("DIAGNOSTIC_RESPONSE_JSON_NONFINITE_CONSTANT")

    try:
        decoded = value.decode("utf-8")
        return json.loads(
            decoded,
            object_pairs_hook=object_pairs,
            parse_constant=reject_constant,
        )
    except DiagnosticStop:
        raise
    except (TypeError, UnicodeDecodeError, ValueError) as error:
        raise DiagnosticStop("DIAGNOSTIC_RESPONSE_JSON_INVALID") from error


def classify_secondary_identifier_v1(value: object) -> SecondaryIdentifierType:
    """Classify a nine-character US CUSIP or foreign CINS identifier."""

    if type(value) is not str or _CUSIP_OR_CINS.fullmatch(value) is None:
        raise DiagnosticStop("SECONDARY_IDENTIFIER_FORMAT_INVALID")
    return SecondaryIdentifierType.CINS if value[0].isalpha() else SecondaryIdentifierType.CUSIP


FROZEN_MEMBERS = (
    DiagnosticMember(
        1,
        "EODHD:ADM",
        "ADM",
        "XNYS",
        "XNYS",
        EXACT_OPERATING_MIC_POLICY,
        "US0394831020",
        SecondaryIdentifierType.CUSIP,
        "039483102",
        "sha256:4c689f59a817ad985778f7b9cf86ebaa2f122a4d64f3bf0585f8c388a49db1e4",
    ),
    DiagnosticMember(
        2,
        "EODHD:GOOG",
        "GOOG",
        "XNAS",
        None,
        OMITTED_OPERATING_MIC_POLICY,
        "US02079K1079",
        SecondaryIdentifierType.CUSIP,
        "02079K107",
        "sha256:f3bb64eb1df570c6dc320d3df57b3fa36442c6ef951962abde4ec1e068ef163f",
    ),
    DiagnosticMember(
        3,
        "EODHD:FOX",
        "FOX",
        "XNAS",
        None,
        OMITTED_OPERATING_MIC_POLICY,
        "US35137L2043",
        SecondaryIdentifierType.CUSIP,
        "35137L204",
        "sha256:ce9e61d7a386e0520e06198d77aa438d6053c445b32f783bb8e9c4f0990a6c76",
    ),
    DiagnosticMember(
        4,
        "EODHD:MSFT",
        "MSFT",
        "XNAS",
        None,
        OMITTED_OPERATING_MIC_POLICY,
        "US5949181045",
        SecondaryIdentifierType.CUSIP,
        "594918104",
        "sha256:7cf537dff253355990e3a4253a912165b8eaf8081e4baaa9d828be0ca2d6fa4f",
    ),
    DiagnosticMember(
        5,
        "EODHD:ALLE",
        "ALLE",
        "XNYS",
        "XNYS",
        EXACT_OPERATING_MIC_POLICY,
        "IE00BFRT3W74",
        SecondaryIdentifierType.CINS,
        "G0176J109",
        "sha256:1201882146d6cd81b9ce62e6616e1408d3bf25108bffc8fe37a924f5bfe4b05a",
    ),
)


def _member_body(value: DiagnosticMember) -> dict[str, object]:
    return {
        "memberOrdinal": value.member_ordinal,
        "securityId": value.security_id,
        "symbol": value.symbol,
        "expectedOperatingMic": value.expected_operating_mic,
        "requestMicCode": value.request_mic_code,
        "requestFilterPolicy": value.request_filter_policy,
        "isin": value.isin,
        "secondaryIdentifierType": value.secondary_identifier_type.value,
        "secondaryIdentifierValue": value.secondary_identifier_value,
        "sourceContentHash": value.source_content_hash,
    }


def _job_body(value: DiagnosticJob, *, include_hash: bool) -> dict[str, object]:
    body: dict[str, object] = {
        "jobOrdinal": value.job_ordinal,
        "memberOrdinal": value.member_ordinal,
        "securityId": value.security_id,
        "expectedSymbol": value.expected_symbol,
        "expectedOperatingMic": value.expected_operating_mic,
        "requestMicCode": value.request_mic_code,
        "requestFilterPolicy": value.request_filter_policy,
        "identifierType": value.identifier_type,
        "identifierValue": value.identifier_value,
    }
    if include_hash:
        body["contentHash"] = value.content_hash
    return body


def _wire_job_body(value: DiagnosticJob) -> dict[str, object]:
    body: dict[str, object] = {
        "currency": "USD",
        "idType": value.identifier_type,
        "idValue": value.identifier_value,
        "includeUnlistedEquities": False,
        "marketSecDes": "Equity",
    }
    if value.request_mic_code is not None:
        body["micCode"] = value.request_mic_code
    return body


def _wire_bytes(jobs: tuple[DiagnosticJob, ...]) -> bytes:
    return json.dumps(
        [_wire_job_body(item) for item in jobs],
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")


def _wire_hash_body(*, request_identity: str, body_sha256: str) -> dict[str, object]:
    return {
        "requestIdentity": request_identity,
        "provider": "OPENFIGI",
        "providerOrigin": PROVIDER_ORIGIN,
        "method": "POST",
        "endpointPath": ENDPOINT_PATH,
        "headers": [
            ["accept", "application/json"],
            ["content-type", "application/json"],
        ],
        "bodySha256": body_sha256,
    }


def _request_body(value: DiagnosticRequest) -> dict[str, object]:
    return {
        "requestOrdinal": value.request_ordinal,
        "requestIdentity": value.request_identity,
        "jobs": [_job_body(item, include_hash=True) for item in value.jobs],
        "bodySha256": value.body_sha256,
        "wireContentHash": value.wire_content_hash,
    }


def _plan_body(value: DiagnosticPlan, *, include_hash: bool) -> dict[str, object]:
    body: dict[str, object] = {
        "contractVersion": value.contract_version,
        "planVersion": value.plan_version,
        "predecessorRejectedPlanContentHash": (value.predecessor_rejected_plan_content_hash),
        "predecessorResultCanonicalHash": value.predecessor_result_canonical_hash,
        "providerOrigin": value.provider_origin,
        "endpointPath": value.endpoint_path,
        "requestFilterPolicyVersion": value.request_filter_policy_version,
        "tickerAliasPolicyVersion": value.ticker_alias_policy_version,
        "pairIdentityContractVersion": value.pair_identity_contract_version,
        "maxJobsPerRequest": value.max_jobs_per_request,
        "physicalRequestCount": value.physical_request_count,
        "logicalJobCount": value.logical_job_count,
        "memberCount": value.member_count,
        "retryLimit": value.retry_limit,
        "networkAuthorized": value.network_authorized,
        "members": [_member_body(item) for item in value.members],
        "requests": [_request_body(item) for item in value.requests],
    }
    if include_hash:
        body["contentHash"] = value.content_hash
    return body


def _build_frozen_plan_unchecked() -> DiagnosticPlan:
    jobs: list[DiagnosticJob] = []
    for member in FROZEN_MEMBERS:
        for identifier_type, identifier_value in (
            ("ID_ISIN", member.isin),
            (member.secondary_identifier_type.value, member.secondary_identifier_value),
        ):
            provisional = DiagnosticJob(
                job_ordinal=len(jobs) + 1,
                member_ordinal=member.member_ordinal,
                security_id=member.security_id,
                expected_symbol=member.symbol,
                expected_operating_mic=member.expected_operating_mic,
                request_mic_code=member.request_mic_code,
                request_filter_policy=member.request_filter_policy,
                identifier_type=identifier_type,
                identifier_value=identifier_value,
                content_hash="",
            )
            jobs.append(
                DiagnosticJob(
                    **{
                        **asdict(provisional),
                        "content_hash": canonical_hash(_job_body(provisional, include_hash=False)),
                    }
                )
            )
    requests: list[DiagnosticRequest] = []
    for offset in range(0, len(jobs), MAX_JOBS_PER_REQUEST):
        request_jobs = tuple(jobs[offset : offset + MAX_JOBS_PER_REQUEST])
        request_ordinal = len(requests) + 1
        request_identity = canonical_hash(
            {
                "contractVersion": CONTRACT_VERSION,
                "providerOrigin": PROVIDER_ORIGIN,
                "endpointPath": ENDPOINT_PATH,
                "requestOrdinal": request_ordinal,
                "jobContentHashes": [item.content_hash for item in request_jobs],
                "retryLimit": RETRY_LIMIT,
            }
        )
        wire = _wire_bytes(request_jobs)
        body_sha256 = _sha256_bytes(wire)
        requests.append(
            DiagnosticRequest(
                request_ordinal=request_ordinal,
                request_identity=request_identity,
                jobs=request_jobs,
                body_sha256=body_sha256,
                wire_content_hash=canonical_hash(
                    _wire_hash_body(
                        request_identity=request_identity,
                        body_sha256=body_sha256,
                    )
                ),
            )
        )
    provisional = DiagnosticPlan(
        contract_version=CONTRACT_VERSION,
        plan_version=PLAN_VERSION,
        predecessor_rejected_plan_content_hash=(PREDECESSOR_REJECTED_PLAN_CONTENT_HASH),
        predecessor_result_canonical_hash=PREDECESSOR_RESULT_CANONICAL_HASH,
        provider_origin=PROVIDER_ORIGIN,
        endpoint_path=ENDPOINT_PATH,
        request_filter_policy_version=REQUEST_FILTER_POLICY_VERSION,
        ticker_alias_policy_version=OPENFIGI_TICKER_ALIAS_POLICY_VERSION,
        pair_identity_contract_version=PAIR_IDENTITY_CONTRACT_VERSION,
        max_jobs_per_request=MAX_JOBS_PER_REQUEST,
        physical_request_count=PHYSICAL_REQUEST_COUNT,
        logical_job_count=LOGICAL_JOB_COUNT,
        member_count=MEMBER_COUNT,
        retry_limit=RETRY_LIMIT,
        network_authorized=False,
        members=FROZEN_MEMBERS,
        requests=tuple(requests),
        content_hash="",
    )
    return DiagnosticPlan(
        **{
            **asdict(provisional),
            "members": provisional.members,
            "requests": provisional.requests,
            "content_hash": canonical_hash(_plan_body(provisional, include_hash=False)),
        }
    )


# Resealed after the exact preregistered body is built.  Tests bind these values
# directly so any future change requires a new successor version.
FROZEN_PLAN_CONTENT_HASH = "589B4E2C21C6888DAD3630302B61318340C0D7F1C118844053202E64D4F94542"
FROZEN_WIRE_BODY_SHA256 = (
    "6BC1811F8D93EB260F9E000C8499D6DD41E8021986B7C747554EA7235B3EC86C",
    "54B91D8247A2917BC6BB9E02B90EFF2A485B49B9802FF6F79FEBBD32C0DE3D3A",
)
FROZEN_WIRE_CONTENT_HASHES = (
    "BB955C46C2D33403456FB4C55D4BCA0FC52D2E81802722CA16635790031CD68A",
    "899912BEB13C9DA67B552C9B5538FD570F6311FE9FE4679E0F5FE7ECE5772438",
)


def validate_diagnostic_plan(plan: DiagnosticPlan) -> None:
    if type(plan.members) is not tuple or type(plan.requests) is not tuple:
        raise DiagnosticStop("DIAGNOSTIC_PLAN_COLLECTIONS_MUST_BE_TUPLE")
    if (
        plan.contract_version != CONTRACT_VERSION
        or plan.plan_version != PLAN_VERSION
        or plan.predecessor_rejected_plan_content_hash != PREDECESSOR_REJECTED_PLAN_CONTENT_HASH
        or plan.predecessor_result_canonical_hash != PREDECESSOR_RESULT_CANONICAL_HASH
        or plan.provider_origin != PROVIDER_ORIGIN
        or plan.endpoint_path != ENDPOINT_PATH
        or plan.request_filter_policy_version != REQUEST_FILTER_POLICY_VERSION
        or plan.ticker_alias_policy_version != OPENFIGI_TICKER_ALIAS_POLICY_VERSION
        or plan.pair_identity_contract_version != PAIR_IDENTITY_CONTRACT_VERSION
        or type(plan.max_jobs_per_request) is not int
        or plan.max_jobs_per_request != MAX_JOBS_PER_REQUEST
        or type(plan.physical_request_count) is not int
        or plan.physical_request_count != PHYSICAL_REQUEST_COUNT
        or type(plan.logical_job_count) is not int
        or plan.logical_job_count != LOGICAL_JOB_COUNT
        or type(plan.member_count) is not int
        or plan.member_count != MEMBER_COUNT
        or type(plan.retry_limit) is not int
        or plan.retry_limit != 0
        or plan.network_authorized is not False
        or plan.members != FROZEN_MEMBERS
        or len(plan.requests) != PHYSICAL_REQUEST_COUNT
    ):
        raise DiagnosticStop("DIAGNOSTIC_PLAN_ROOT_BINDING_DRIFT")
    expected_jobs: list[DiagnosticJob] = []
    for member in plan.members:
        if (
            type(member.member_ordinal) is not int
            or member.member_ordinal < 1
            or type(member.security_id) is not str
            or type(member.symbol) is not str
            or _SYMBOL.fullmatch(member.symbol) is None
            or _MIC.fullmatch(member.expected_operating_mic) is None
            or (
                member.request_mic_code is not None
                and _MIC.fullmatch(member.request_mic_code) is None
            )
            or _ISIN.fullmatch(member.isin) is None
            or classify_secondary_identifier_v1(member.secondary_identifier_value)
            is not member.secondary_identifier_type
            or _SHA256_LOWER.fullmatch(member.source_content_hash) is None
        ):
            raise DiagnosticStop("DIAGNOSTIC_MEMBER_INVALID")
        expected_policy = (
            OMITTED_OPERATING_MIC_POLICY
            if member.expected_operating_mic == "XNAS"
            else EXACT_OPERATING_MIC_POLICY
        )
        expected_request_mic = (
            None
            if expected_policy == OMITTED_OPERATING_MIC_POLICY
            else member.expected_operating_mic
        )
        if (
            member.request_filter_policy != expected_policy
            or member.request_mic_code != expected_request_mic
        ):
            raise DiagnosticStop("DIAGNOSTIC_MEMBER_MIC_POLICY_DRIFT")
    for request_index, request in enumerate(plan.requests, start=1):
        if type(request.jobs) is not tuple or len(request.jobs) != 5:
            raise DiagnosticStop("DIAGNOSTIC_REQUEST_JOB_CARDINALITY_DRIFT")
        if type(request.request_ordinal) is not int or request.request_ordinal != request_index:
            raise DiagnosticStop("DIAGNOSTIC_REQUEST_ORDER_DRIFT")
        for job in request.jobs:
            if (
                type(job.member_ordinal) is not int
                or not 1 <= job.member_ordinal <= MEMBER_COUNT
                or type(job.job_ordinal) is not int
                or not 1 <= job.job_ordinal <= LOGICAL_JOB_COUNT
            ):
                raise DiagnosticStop("DIAGNOSTIC_JOB_MEMBER_ORDINAL_INVALID")
            member = plan.members[job.member_ordinal - 1]
            if (
                job.security_id != member.security_id
                or job.expected_symbol != member.symbol
                or job.expected_operating_mic != member.expected_operating_mic
                or job.request_mic_code != member.request_mic_code
                or job.request_filter_policy != member.request_filter_policy
                or job.identifier_type not in {"ID_ISIN", "ID_CUSIP", "ID_CINS"}
                or job.content_hash != canonical_hash(_job_body(job, include_hash=False))
            ):
                raise DiagnosticStop("DIAGNOSTIC_JOB_BINDING_DRIFT")
            expected_jobs.append(job)
        expected_request_identity = canonical_hash(
            {
                "contractVersion": CONTRACT_VERSION,
                "providerOrigin": PROVIDER_ORIGIN,
                "endpointPath": ENDPOINT_PATH,
                "requestOrdinal": request_index,
                "jobContentHashes": [item.content_hash for item in request.jobs],
                "retryLimit": RETRY_LIMIT,
            }
        )
        wire = _wire_bytes(request.jobs)
        expected_body_sha = _sha256_bytes(wire)
        if (
            request.request_identity != expected_request_identity
            or request.body_sha256 != expected_body_sha
            or request.wire_content_hash
            != canonical_hash(
                _wire_hash_body(
                    request_identity=expected_request_identity,
                    body_sha256=expected_body_sha,
                )
            )
        ):
            raise DiagnosticStop("DIAGNOSTIC_REQUEST_HASH_DRIFT")
    if tuple(item.job_ordinal for item in expected_jobs) != tuple(range(1, LOGICAL_JOB_COUNT + 1)):
        raise DiagnosticStop("DIAGNOSTIC_JOB_ORDER_DRIFT")
    for member in plan.members:
        member_jobs = tuple(
            item for item in expected_jobs if item.member_ordinal == member.member_ordinal
        )
        if (
            len(member_jobs) != 2
            or member_jobs[0].identifier_type != "ID_ISIN"
            or member_jobs[0].identifier_value != member.isin
            or member_jobs[1].identifier_type != member.secondary_identifier_type.value
            or member_jobs[1].identifier_value != member.secondary_identifier_value
        ):
            raise DiagnosticStop("DIAGNOSTIC_IDENTIFIER_PAIR_DRIFT")
    if plan.content_hash != canonical_hash(_plan_body(plan, include_hash=False)):
        raise DiagnosticStop("DIAGNOSTIC_PLAN_CONTENT_HASH_DRIFT")


def build_frozen_diagnostic_plan_v1() -> DiagnosticPlan:
    plan = _build_frozen_plan_unchecked()
    validate_diagnostic_plan(plan)
    if (
        plan.content_hash != FROZEN_PLAN_CONTENT_HASH
        or tuple(item.body_sha256 for item in plan.requests) != FROZEN_WIRE_BODY_SHA256
        or tuple(item.wire_content_hash for item in plan.requests) != FROZEN_WIRE_CONTENT_HASHES
    ):
        raise DiagnosticStop("DIAGNOSTIC_FROZEN_HASH_DRIFT")
    return plan


def build_diagnostic_wire_requests_v1(
    plan: DiagnosticPlan,
) -> tuple[ProviderWireRequest, ...]:
    """Return exact non-secret wire requests without owning a transport."""

    validate_diagnostic_plan(plan)
    if (
        plan.content_hash != FROZEN_PLAN_CONTENT_HASH
        or tuple(item.body_sha256 for item in plan.requests) != FROZEN_WIRE_BODY_SHA256
        or tuple(item.wire_content_hash for item in plan.requests)
        != FROZEN_WIRE_CONTENT_HASHES
    ):
        raise DiagnosticStop("DIAGNOSTIC_FROZEN_HASH_DRIFT")
    wires = tuple(
        ProviderWireRequest(
            request_identity=request.request_identity,
            provider="OPENFIGI",
            method="POST",
            endpoint_path=ENDPOINT_PATH,
            headers=(
                ("accept", "application/json"),
                ("content-type", "application/json"),
            ),
            body=_wire_bytes(request.jobs),
            body_sha256=request.body_sha256,
        )
        for request in plan.requests
    )
    for request, wire in zip(plan.requests, wires, strict=True):
        if (
            wire.body is None
            or _sha256_bytes(wire.body) != request.body_sha256
            or canonical_hash(
                _wire_hash_body(
                    request_identity=wire.request_identity,
                    body_sha256=wire.body_sha256 or "",
                )
            )
            != request.wire_content_hash
        ):
            raise DiagnosticStop("DIAGNOSTIC_WIRE_HASH_DRIFT")
    return wires


def _validate_provider_candidate(candidate: dict[str, Any]) -> None:
    """Validate the provider candidate envelope without promoting it to an identity."""

    if type(candidate.get("figi")) is not str or _FIGI.fullmatch(candidate["figi"]) is None:
        raise DiagnosticStop("DIAGNOSTIC_CANDIDATE_SCHEMA_INVALID")
    optional_fields = (
        "name",
        "ticker",
        "exchCode",
        "compositeFIGI",
        "securityType",
        "marketSector",
        "shareClassFIGI",
        "securityType2",
        "securityDescription",
    )
    for field in optional_fields:
        value = candidate.get(field)
        if value is not None and type(value) is not str:
            raise DiagnosticStop("DIAGNOSTIC_CANDIDATE_SCHEMA_INVALID")
        if type(value) is str and (not value or value != value.strip()):
            raise DiagnosticStop("DIAGNOSTIC_CANDIDATE_SCHEMA_INVALID")
    for field in ("shareClassFIGI", "compositeFIGI"):
        value = candidate.get(field)
        if value is not None and _FIGI.fullmatch(value) is None:
            raise DiagnosticStop("DIAGNOSTIC_CANDIDATE_SCHEMA_INVALID")
    ticker = candidate.get("ticker")
    if ticker is not None and (
        len(ticker) > MAX_PROVIDER_ENVELOPE_TICKER_LENGTH
        or any(ord(character) < 32 or ord(character) == 127 for character in ticker)
    ):
        raise DiagnosticStop("DIAGNOSTIC_CANDIDATE_SCHEMA_INVALID")
    exchange_code = candidate.get("exchCode")
    if exchange_code is not None and _EXCHANGE_CODE.fullmatch(exchange_code) is None:
        raise DiagnosticStop("DIAGNOSTIC_CANDIDATE_SCHEMA_INVALID")


def _provider_identity_body(candidate: dict[str, Any]) -> dict[str, str]:
    fields = (
        "figi",
        "shareClassFIGI",
        "compositeFIGI",
        "ticker",
        "exchCode",
        "marketSector",
        "securityType",
    )
    if any(type(candidate.get(field)) is not str for field in fields):
        raise DiagnosticStop("DIAGNOSTIC_CANDIDATE_SCHEMA_INVALID")
    body = {field: candidate[field] for field in fields}
    if (
        _FIGI.fullmatch(body["figi"]) is None
        or _FIGI.fullmatch(body["shareClassFIGI"]) is None
        or _FIGI.fullmatch(body["compositeFIGI"]) is None
        or _OPENFIGI_PROVIDER_TICKER.fullmatch(body["ticker"]) is None
        or _EXCHANGE_CODE.fullmatch(body["exchCode"]) is None
        or not body["marketSector"].strip()
        or body["marketSector"] != body["marketSector"].strip()
        or not body["securityType"].strip()
        or body["securityType"] != body["securityType"].strip()
    ):
        raise DiagnosticStop("DIAGNOSTIC_CANDIDATE_SCHEMA_INVALID")
    return {
        field: body[field]
        for field in ("figi", "shareClassFIGI", "compositeFIGI", "ticker", "exchCode")
    }


def _job_review_body(value: DiagnosticJobReview, *, include_hash: bool) -> dict[str, object]:
    body: dict[str, object] = {
        "requestIdentity": value.request_identity,
        "logicalOrdinal": value.logical_ordinal,
        "jobOrdinal": value.job_ordinal,
        "securityId": value.security_id,
        "identifierType": value.identifier_type,
        "identifierValue": value.identifier_value,
        "responseKind": value.response_kind,
        "candidateCount": value.candidate_count,
        "primaryMatchCount": value.primary_match_count,
        "primaryProviderIdentityHash": value.primary_provider_identity_hash,
        "outcomeState": value.outcome_state.value,
    }
    if include_hash:
        body["contentHash"] = value.content_hash
    return body


def _pair_review_body(value: DiagnosticPairReview, *, include_hash: bool) -> dict[str, object]:
    body: dict[str, object] = {
        "memberOrdinal": value.member_ordinal,
        "securityId": value.security_id,
        "firstIdentifierType": value.first_identifier_type,
        "secondIdentifierType": value.second_identifier_type,
        "firstPrimaryProviderIdentityHash": (value.first_primary_provider_identity_hash),
        "secondPrimaryProviderIdentityHash": (value.second_primary_provider_identity_hash),
        "completeConvergent": value.complete_convergent,
        "conflict": value.conflict,
    }
    if include_hash:
        body["contentHash"] = value.content_hash
    return body


def _review_body(value: DiagnosticReview, *, include_hash: bool) -> dict[str, object]:
    body: dict[str, object] = {
        "contractVersion": REVIEW_VERSION,
        "planContentHash": value.plan_content_hash,
        "physicalRequestCount": value.physical_request_count,
        "logicalJobCount": value.logical_job_count,
        "uniquePrimaryCount": value.unique_primary_count,
        "warningCount": value.warning_count,
        "errorCount": value.error_count,
        "ambiguousPrimaryCount": value.ambiguous_primary_count,
        "noPrimaryCount": value.no_primary_count,
        "completeConvergentPairCount": value.complete_convergent_pair_count,
        "pairConflictCount": value.pair_conflict_count,
        "jobs": [_job_review_body(item, include_hash=True) for item in value.jobs],
        "pairs": [_pair_review_body(item, include_hash=True) for item in value.pairs],
    }
    if include_hash:
        body["contentHash"] = value.content_hash
    return body


def build_diagnostic_review_v1(
    plan: DiagnosticPlan,
    responses: tuple[TransportResponse, ...],
) -> DiagnosticReview:
    """Validate supplied provider responses and produce a value-free review."""

    validate_diagnostic_plan(plan)
    if type(responses) is not tuple or len(responses) != PHYSICAL_REQUEST_COUNT:
        raise DiagnosticStop("DIAGNOSTIC_RESPONSE_SET_CARDINALITY_DRIFT")
    reviews: list[DiagnosticJobReview] = []
    for request, response in zip(plan.requests, responses, strict=True):
        if type(response) is not TransportResponse:
            raise DiagnosticStop("DIAGNOSTIC_RESPONSE_TYPE_INVALID")
        if type(response.status_code) is not int or response.status_code != 200:
            raise DiagnosticStop("DIAGNOSTIC_HTTP_STATUS_INVALID")
        if type(response.body) is not bytes:
            raise DiagnosticStop("DIAGNOSTIC_RESPONSE_BODY_MUST_BE_BYTES")
        payload = _strict_json_loads(response.body)
        if type(payload) is not list or len(payload) != len(request.jobs):
            raise DiagnosticStop("DIAGNOSTIC_RESPONSE_CARDINALITY_DRIFT")
        for logical_ordinal, (job, item) in enumerate(
            zip(request.jobs, payload, strict=True), start=1
        ):
            if type(item) is not dict:
                raise DiagnosticStop("DIAGNOSTIC_RESPONSE_ITEM_INVALID")
            response_keys = tuple(item)
            if len(response_keys) != 1 or response_keys[0] not in {
                "data",
                "warning",
                "error",
            }:
                raise DiagnosticStop("DIAGNOSTIC_RESPONSE_KIND_INVALID")
            response_kind = response_keys[0].upper()
            candidates: list[object]
            if response_kind == "DATA":
                candidates = item["data"]
                if type(candidates) is not list:
                    raise DiagnosticStop("DIAGNOSTIC_RESPONSE_DATA_INVALID")
                if not candidates:
                    raise DiagnosticStop("DIAGNOSTIC_RESPONSE_DATA_EMPTY")
            else:
                message = item[response_keys[0]]
                if (
                    type(message) is not str
                    or not message
                    or message != message.strip()
                    or len(message) > MAX_PROVIDER_MESSAGE_LENGTH
                ):
                    raise DiagnosticStop("DIAGNOSTIC_RESPONSE_MESSAGE_INVALID")
                candidates = []
            primary: list[dict[str, Any]] = []
            for candidate in candidates:
                if type(candidate) is not dict:
                    raise DiagnosticStop("DIAGNOSTIC_CANDIDATE_INVALID")
                _validate_provider_candidate(candidate)
                if (
                    canonical_openfigi_ticker_for_expected_v1(
                        candidate.get("ticker"), job.expected_symbol
                    )
                    == job.expected_symbol
                    and candidate.get("marketSector") == "Equity"
                    and candidate.get("securityType") == "Common Stock"
                ):
                    _provider_identity_body(candidate)
                    primary.append(candidate)
            if response_kind == "WARNING":
                state = DiagnosticOutcomeState.UNRESOLVED_WARNING
            elif response_kind == "ERROR":
                state = DiagnosticOutcomeState.UNRESOLVED_ERROR
            elif len(primary) == 1:
                state = DiagnosticOutcomeState.UNIQUE_PRIMARY
            elif len(primary) > 1:
                state = DiagnosticOutcomeState.AMBIGUOUS_PRIMARY
            else:
                state = DiagnosticOutcomeState.NO_PRIMARY
            provisional = DiagnosticJobReview(
                request_identity=request.request_identity,
                logical_ordinal=logical_ordinal,
                job_ordinal=job.job_ordinal,
                security_id=job.security_id,
                identifier_type=job.identifier_type,
                identifier_value=job.identifier_value,
                response_kind=response_kind,
                candidate_count=len(candidates),
                primary_match_count=len(primary),
                primary_provider_identity_hash=(
                    canonical_hash(_provider_identity_body(primary[0]))
                    if len(primary) == 1
                    else None
                ),
                outcome_state=state,
                content_hash="",
            )
            reviews.append(
                DiagnosticJobReview(
                    **{
                        **asdict(provisional),
                        "outcome_state": provisional.outcome_state,
                        "content_hash": canonical_hash(
                            _job_review_body(provisional, include_hash=False)
                        ),
                    }
                )
            )
    pairs: list[DiagnosticPairReview] = []
    for member in plan.members:
        member_reviews = tuple(item for item in reviews if item.security_id == member.security_id)
        if len(member_reviews) != 2:
            raise DiagnosticStop("DIAGNOSTIC_PAIR_CARDINALITY_DRIFT")
        hashes = tuple(item.primary_provider_identity_hash for item in member_reviews)
        complete = (
            all(
                item.outcome_state is DiagnosticOutcomeState.UNIQUE_PRIMARY
                for item in member_reviews
            )
            and hashes[0] is not None
            and hashes[0] == hashes[1]
        )
        conflict = hashes[0] is not None and hashes[1] is not None and hashes[0] != hashes[1]
        provisional_pair = DiagnosticPairReview(
            member_ordinal=member.member_ordinal,
            security_id=member.security_id,
            first_identifier_type=member_reviews[0].identifier_type,
            second_identifier_type=member_reviews[1].identifier_type,
            first_primary_provider_identity_hash=hashes[0],
            second_primary_provider_identity_hash=hashes[1],
            complete_convergent=complete,
            conflict=conflict,
            content_hash="",
        )
        pairs.append(
            DiagnosticPairReview(
                **{
                    **asdict(provisional_pair),
                    "content_hash": canonical_hash(
                        _pair_review_body(provisional_pair, include_hash=False)
                    ),
                }
            )
        )
    states = Counter(item.outcome_state for item in reviews)
    provisional_review = DiagnosticReview(
        plan_content_hash=plan.content_hash,
        physical_request_count=PHYSICAL_REQUEST_COUNT,
        logical_job_count=LOGICAL_JOB_COUNT,
        unique_primary_count=states[DiagnosticOutcomeState.UNIQUE_PRIMARY],
        warning_count=states[DiagnosticOutcomeState.UNRESOLVED_WARNING],
        error_count=states[DiagnosticOutcomeState.UNRESOLVED_ERROR],
        ambiguous_primary_count=states[DiagnosticOutcomeState.AMBIGUOUS_PRIMARY],
        no_primary_count=states[DiagnosticOutcomeState.NO_PRIMARY],
        complete_convergent_pair_count=sum(item.complete_convergent for item in pairs),
        pair_conflict_count=sum(item.conflict for item in pairs),
        jobs=tuple(reviews),
        pairs=tuple(pairs),
        content_hash="",
    )
    result = DiagnosticReview(
        **{
            **asdict(provisional_review),
            "jobs": provisional_review.jobs,
            "pairs": provisional_review.pairs,
            "content_hash": canonical_hash(_review_body(provisional_review, include_hash=False)),
        }
    )
    validate_diagnostic_review(plan, result)
    return result


def validate_diagnostic_review(plan: DiagnosticPlan, review: DiagnosticReview) -> None:
    validate_diagnostic_plan(plan)
    if type(review.jobs) is not tuple or type(review.pairs) is not tuple:
        raise DiagnosticStop("DIAGNOSTIC_REVIEW_COLLECTIONS_MUST_BE_TUPLE")
    count_values = (
        review.physical_request_count,
        review.logical_job_count,
        review.unique_primary_count,
        review.warning_count,
        review.error_count,
        review.ambiguous_primary_count,
        review.no_primary_count,
        review.complete_convergent_pair_count,
        review.pair_conflict_count,
    )
    if any(type(item) is not int or item < 0 for item in count_values):
        raise DiagnosticStop("DIAGNOSTIC_REVIEW_COUNT_INVALID")
    states = Counter(item.outcome_state for item in review.jobs)
    if (
        review.plan_content_hash != plan.content_hash
        or review.physical_request_count != PHYSICAL_REQUEST_COUNT
        or review.logical_job_count != LOGICAL_JOB_COUNT
        or len(review.jobs) != LOGICAL_JOB_COUNT
        or len(review.pairs) != MEMBER_COUNT
        or review.unique_primary_count != states[DiagnosticOutcomeState.UNIQUE_PRIMARY]
        or review.warning_count != states[DiagnosticOutcomeState.UNRESOLVED_WARNING]
        or review.error_count != states[DiagnosticOutcomeState.UNRESOLVED_ERROR]
        or review.ambiguous_primary_count != states[DiagnosticOutcomeState.AMBIGUOUS_PRIMARY]
        or review.no_primary_count != states[DiagnosticOutcomeState.NO_PRIMARY]
        or review.complete_convergent_pair_count
        != sum(item.complete_convergent for item in review.pairs)
        or review.pair_conflict_count != sum(item.conflict for item in review.pairs)
        or review.content_hash != canonical_hash(_review_body(review, include_hash=False))
    ):
        raise DiagnosticStop("DIAGNOSTIC_REVIEW_AGGREGATE_DRIFT")
    expected_jobs = tuple(job for request in plan.requests for job in request.jobs)
    request_by_job_ordinal = {
        job.job_ordinal: (request, logical_ordinal)
        for request in plan.requests
        for logical_ordinal, job in enumerate(request.jobs, start=1)
    }
    for job, item in zip(expected_jobs, review.jobs, strict=True):
        request, logical_ordinal = request_by_job_ordinal[job.job_ordinal]
        expected_state = (
            DiagnosticOutcomeState.UNRESOLVED_WARNING
            if item.response_kind == "WARNING"
            else DiagnosticOutcomeState.UNRESOLVED_ERROR
            if item.response_kind == "ERROR"
            else DiagnosticOutcomeState.UNIQUE_PRIMARY
            if item.primary_match_count == 1
            else DiagnosticOutcomeState.AMBIGUOUS_PRIMARY
            if item.primary_match_count > 1
            else DiagnosticOutcomeState.NO_PRIMARY
        )
        if (
            item.request_identity != request.request_identity
            or type(item.logical_ordinal) is not int
            or item.logical_ordinal != logical_ordinal
            or type(item.job_ordinal) is not int
            or item.job_ordinal != job.job_ordinal
            or item.security_id != job.security_id
            or item.identifier_type != job.identifier_type
            or item.identifier_value != job.identifier_value
            or item.response_kind not in {"DATA", "WARNING", "ERROR"}
            or type(item.candidate_count) is not int
            or item.candidate_count < 0
            or type(item.primary_match_count) is not int
            or not 0 <= item.primary_match_count <= item.candidate_count
            or item.outcome_state is not expected_state
            or (
                item.primary_provider_identity_hash is None
                if item.primary_match_count == 1
                else item.primary_provider_identity_hash is not None
            )
            or item.content_hash != canonical_hash(_job_review_body(item, include_hash=False))
            or (
                item.primary_provider_identity_hash is not None
                and _UPPER_SHA256.fullmatch(item.primary_provider_identity_hash) is None
            )
        ):
            raise DiagnosticStop("DIAGNOSTIC_REVIEW_JOB_DRIFT")
    for member, pair in zip(plan.members, review.pairs, strict=True):
        member_jobs = tuple(item for item in review.jobs if item.security_id == member.security_id)
        if len(member_jobs) != 2:
            raise DiagnosticStop("DIAGNOSTIC_REVIEW_PAIR_DRIFT")
        first_hash = member_jobs[0].primary_provider_identity_hash
        second_hash = member_jobs[1].primary_provider_identity_hash
        expected_complete = (
            all(item.outcome_state is DiagnosticOutcomeState.UNIQUE_PRIMARY for item in member_jobs)
            and first_hash is not None
            and first_hash == second_hash
        )
        expected_conflict = (
            first_hash is not None and second_hash is not None and first_hash != second_hash
        )
        if (
            type(pair.member_ordinal) is not int
            or pair.member_ordinal != member.member_ordinal
            or pair.security_id != member.security_id
            or pair.first_identifier_type != "ID_ISIN"
            or pair.second_identifier_type != member.secondary_identifier_type.value
            or pair.first_primary_provider_identity_hash != first_hash
            or pair.second_primary_provider_identity_hash != second_hash
            or pair.complete_convergent is not expected_complete
            or pair.conflict is not expected_conflict
            or pair.content_hash != canonical_hash(_pair_review_body(pair, include_hash=False))
        ):
            raise DiagnosticStop("DIAGNOSTIC_REVIEW_PAIR_DRIFT")


def _acceptance_body(value: DiagnosticAcceptance, *, include_hash: bool) -> dict[str, object]:
    body: dict[str, object] = {
        "contractVersion": ACCEPTANCE_VERSION,
        "planContentHash": value.plan_content_hash,
        "reviewContentHash": value.review_content_hash,
        "accepted": value.accepted,
        "decisionCode": value.decision_code,
        "diagnosticOnly": value.diagnostic_only,
        "durableIdentityAuthorized": value.durable_identity_authorized,
        "remainderAuthorized": value.remainder_authorized,
        "operatingMicBindingStatus": value.operating_mic_binding_status,
    }
    if include_hash:
        body["contentHash"] = value.content_hash
    return body


def _acceptance_gate_passes(review: DiagnosticReview) -> bool:
    return (
        review.unique_primary_count == LOGICAL_JOB_COUNT
        and review.complete_convergent_pair_count == MEMBER_COUNT
        and review.warning_count == 0
        and review.error_count == 0
        and review.ambiguous_primary_count == 0
        and review.no_primary_count == 0
        and review.pair_conflict_count == 0
    )


def seal_diagnostic_acceptance_v1(
    plan: DiagnosticPlan,
    review: DiagnosticReview,
    *,
    accepted: bool,
    decision_code: str,
) -> DiagnosticAcceptance:
    validate_diagnostic_review(plan, review)
    if (
        type(accepted) is not bool
        or type(decision_code) is not str
        or _DECISION.fullmatch(decision_code) is None
    ):
        raise DiagnosticStop("DIAGNOSTIC_ACCEPTANCE_DECISION_INVALID")
    if accepted and not _acceptance_gate_passes(review):
        raise DiagnosticStop("DIAGNOSTIC_ACCEPTANCE_COMPLETENESS_GATE_FAILED")
    if accepted and decision_code != ACCEPTED_DECISION_CODE:
        raise DiagnosticStop("DIAGNOSTIC_ACCEPTANCE_SUCCESS_CODE_INVALID")
    provisional = DiagnosticAcceptance(
        plan_content_hash=plan.content_hash,
        review_content_hash=review.content_hash,
        accepted=accepted,
        decision_code=decision_code,
        diagnostic_only=True,
        durable_identity_authorized=False,
        remainder_authorized=False,
        operating_mic_binding_status=OPERATING_MIC_BINDING_STATUS,
        content_hash="",
    )
    result = DiagnosticAcceptance(
        **{
            **asdict(provisional),
            "content_hash": canonical_hash(_acceptance_body(provisional, include_hash=False)),
        }
    )
    validate_diagnostic_acceptance_v1(plan, review, result)
    return result


def validate_diagnostic_acceptance_v1(
    plan: DiagnosticPlan,
    review: DiagnosticReview,
    value: DiagnosticAcceptance,
) -> None:
    validate_diagnostic_review(plan, review)
    if (
        value.plan_content_hash != plan.content_hash
        or value.review_content_hash != review.content_hash
        or type(value.accepted) is not bool
        or type(value.decision_code) is not str
        or _DECISION.fullmatch(value.decision_code) is None
        or (value.accepted and not _acceptance_gate_passes(review))
        or (value.accepted and value.decision_code != ACCEPTED_DECISION_CODE)
        or value.diagnostic_only is not True
        or value.durable_identity_authorized is not False
        or value.remainder_authorized is not False
        or value.operating_mic_binding_status != OPERATING_MIC_BINDING_STATUS
        or value.content_hash != canonical_hash(_acceptance_body(value, include_hash=False))
    ):
        raise DiagnosticStop("DIAGNOSTIC_ACCEPTANCE_DRIFT")
