"""Preregistered OpenFIGI Stage 8C v1.5 US-composite diagnostic.

This successor is deliberately narrow and transport-free.  It tests whether
the six public identifiers for GOOG, FOX, and MSFT converge when OpenFIGI's US
composite exchange code is used instead of an operating-MIC filter.  The
expected XNAS operating MIC remains a separate, unproven SEC-corroboration
responsibility.  This is a post-v1.4 engineering diagnostic, not a holdout or
an identity enrollment authority.
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

CONTRACT_VERSION = "FV-STAGE8C-OPENFIGI-US-COMPOSITE-DIAGNOSTIC-v1.5.0"
PLAN_VERSION = "FV-STAGE8C-OPENFIGI-US-COMPOSITE-DIAGNOSTIC-PLAN-v1.0.0"
REVIEW_VERSION = "FV-STAGE8C-OPENFIGI-US-COMPOSITE-DIAGNOSTIC-REVIEW-v1.0.0"
ACCEPTANCE_VERSION = (
    "FV-STAGE8C-OPENFIGI-US-COMPOSITE-DIAGNOSTIC-ACCEPTANCE-v1.0.0"
)
REQUEST_FILTER_POLICY_VERSION = (
    "FV-STAGE8C-OPENFIGI-US-COMPOSITE-REQUEST-FILTER-v1.0.0"
)
PAIR_IDENTITY_CONTRACT_VERSION = "FV-STAGE8C-OPENFIGI-PAIR-IDENTITY-v1.0.0"
PROVIDER_ORIGIN = "https://api.openfigi.com"
ENDPOINT_PATH = "/v3/mapping"
US_COMPOSITE_EXCHANGE_CODE = "US"
EXPECTED_OPERATING_MIC = "XNAS"
OPERATING_MIC_BINDING_STATUS = "REQUIRES_SEC_CORROBORATION"
REQUEST_FILTER_POLICY = "US_COMPOSITE_EXCHANGE_CODE_NO_OPERATING_MIC"
ACCEPTED_DECISION_CODE = "US_COMPOSITE_DIAGNOSTIC_COMPLETE_CONVERGENT"
REJECTED_DECISION_CODE = "US_COMPOSITE_DIAGNOSTIC_REJECTED_GATE_NOT_MET"
EVIDENCE_CLAIM = "POST_V14_ENGINEERING_DIAGNOSTIC_ONLY"

PREDECESSOR_REJECTED_PLAN_CONTENT_HASH = (
    "589B4E2C21C6888DAD3630302B61318340C0D7F1C118844053202E64D4F94542"
)
PREDECESSOR_REJECTED_REVIEW_CONTENT_HASH = (
    "7A3F6634C921A1C9CCF18B5F6FEEF715B84023082A271DD9BF3212F1F344CC49"
)
PREDECESSOR_CHECKPOINT_RECEIPT_SET_HASH = (
    "CCFC7F9C5E99B926793D89A235FBF6DC440996529B395C900977DFF295D5E4E5"
)
PREDECESSOR_DIAGNOSTIC_ACCEPTANCE_CONTENT_HASH = (
    "7217C36B06E261FEED0B65A4D79F1F11F17EF80AAD0096BBFF4A0E7D2CA62950"
)
PREDECESSOR_STORAGE_REJECTION_CONTENT_HASH = (
    "408209D2472B6C41087D788DFEA8FF17C906763F96357945CB9E9223E9E5E4E5"
)

MAX_JOBS_PER_REQUEST = 5
PHYSICAL_REQUEST_COUNT = 2
LOGICAL_JOB_COUNT = 6
MEMBER_COUNT = 3
RETRY_LIMIT = 0
MAX_PROVIDER_MESSAGE_LENGTH = 4096
MAX_PROVIDER_ENVELOPE_TICKER_LENGTH = 256

_UPPER_SHA256 = re.compile(r"[0-9A-F]{64}\Z")
_LOWER_SOURCE_SHA256 = re.compile(r"sha256:[0-9a-f]{64}\Z")
_FIGI = re.compile(r"BBG[A-Z0-9]{9}\Z")
_ISIN = re.compile(r"[A-Z]{2}[A-Z0-9]{10}\Z")
_CUSIP = re.compile(r"[A-Z0-9*@#]{9}\Z")
_SYMBOL = re.compile(r"[A-Z0-9][A-Z0-9.-]{0,31}\Z")
_MIC = re.compile(r"[A-Z0-9]{4}\Z")
_OPENFIGI_PROVIDER_TICKER = re.compile(
    r"(?=.{1,32}\Z)(?:[A-Z0-9][A-Z0-9.-]*|[A-Z0-9]+/[A-Z0-9]+)\Z"
)
_EXCHANGE_CODE = re.compile(r"[A-Z0-9]{1,16}\Z")


class UsCompositeDiagnosticStop(RuntimeError):
    """Fail-closed v1.5 stop with a stable code."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class UsCompositeOutcomeState(StrEnum):
    UNIQUE_PRIMARY = "UNIQUE_PRIMARY"
    AMBIGUOUS_PRIMARY = "AMBIGUOUS_PRIMARY"
    UNRESOLVED_WARNING = "UNRESOLVED_WARNING"
    UNRESOLVED_ERROR = "UNRESOLVED_ERROR"
    NO_PRIMARY = "NO_PRIMARY"


@dataclass(frozen=True)
class UsCompositeMember:
    member_ordinal: int
    security_id: str
    symbol: str
    expected_operating_mic: str
    request_exchange_code: str
    request_mic_code: None
    request_filter_policy: str
    isin: str
    cusip: str
    source_content_hash: str


@dataclass(frozen=True)
class UsCompositeJob:
    job_ordinal: int
    member_ordinal: int
    security_id: str
    expected_symbol: str
    expected_operating_mic: str
    request_exchange_code: str
    request_mic_code: None
    request_filter_policy: str
    identifier_type: str
    identifier_value: str
    content_hash: str


@dataclass(frozen=True)
class UsCompositeRequest:
    request_ordinal: int
    request_identity: str
    jobs: tuple[UsCompositeJob, ...]
    body_sha256: str
    wire_content_hash: str


@dataclass(frozen=True)
class UsCompositePlan:
    contract_version: str
    plan_version: str
    predecessor_rejected_plan_content_hash: str
    predecessor_rejected_review_content_hash: str
    predecessor_checkpoint_receipt_set_hash: str
    predecessor_diagnostic_acceptance_content_hash: str
    predecessor_storage_rejection_content_hash: str
    provider_origin: str
    endpoint_path: str
    request_filter_policy_version: str
    ticker_alias_policy_version: str
    pair_identity_contract_version: str
    evidence_claim: str
    max_jobs_per_request: int
    physical_request_count: int
    logical_job_count: int
    member_count: int
    retry_limit: int
    network_authorized: bool
    members: tuple[UsCompositeMember, ...]
    requests: tuple[UsCompositeRequest, ...]
    content_hash: str


@dataclass(frozen=True)
class UsCompositeJobReview:
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
    outcome_state: UsCompositeOutcomeState
    content_hash: str


@dataclass(frozen=True)
class UsCompositePairReview:
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
class UsCompositeReview:
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
    jobs: tuple[UsCompositeJobReview, ...]
    pairs: tuple[UsCompositePairReview, ...]
    content_hash: str


@dataclass(frozen=True)
class UsCompositeAcceptance:
    plan_content_hash: str
    review_content_hash: str
    accepted: bool
    decision_code: str
    diagnostic_only: bool
    post_predecessor_observation: bool
    durable_identity_authorized: bool
    remainder_authorized: bool
    evidence_upgrade_authorized: bool
    operating_mic_binding_status: str
    content_hash: str


def canonical_hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            default=str,
        ).encode("utf-8")
    ).hexdigest().upper()


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest().upper()


def _strict_json_loads(value: bytes) -> object:
    def object_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, item in pairs:
            if key in result:
                raise UsCompositeDiagnosticStop(
                    "US_COMPOSITE_RESPONSE_JSON_DUPLICATE_KEY"
                )
            result[key] = item
        return result

    def reject_constant(_: str) -> None:
        raise UsCompositeDiagnosticStop(
            "US_COMPOSITE_RESPONSE_JSON_NONFINITE_CONSTANT"
        )

    try:
        return json.loads(
            value.decode("utf-8"),
            object_pairs_hook=object_pairs,
            parse_constant=reject_constant,
        )
    except UsCompositeDiagnosticStop:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise UsCompositeDiagnosticStop("US_COMPOSITE_RESPONSE_JSON_INVALID") from error


FROZEN_MEMBERS = (
    UsCompositeMember(
        member_ordinal=1,
        security_id="EODHD:GOOG",
        symbol="GOOG",
        expected_operating_mic=EXPECTED_OPERATING_MIC,
        request_exchange_code=US_COMPOSITE_EXCHANGE_CODE,
        request_mic_code=None,
        request_filter_policy=REQUEST_FILTER_POLICY,
        isin="US02079K1079",
        cusip="02079K107",
        source_content_hash=(
            "sha256:f3bb64eb1df570c6dc320d3df57b3fa36442c6ef951962abde4ec1e068ef163f"
        ),
    ),
    UsCompositeMember(
        member_ordinal=2,
        security_id="EODHD:FOX",
        symbol="FOX",
        expected_operating_mic=EXPECTED_OPERATING_MIC,
        request_exchange_code=US_COMPOSITE_EXCHANGE_CODE,
        request_mic_code=None,
        request_filter_policy=REQUEST_FILTER_POLICY,
        isin="US35137L2043",
        cusip="35137L204",
        source_content_hash=(
            "sha256:ce9e61d7a386e0520e06198d77aa438d6053c445b32f783bb8e9c4f0990a6c76"
        ),
    ),
    UsCompositeMember(
        member_ordinal=3,
        security_id="EODHD:MSFT",
        symbol="MSFT",
        expected_operating_mic=EXPECTED_OPERATING_MIC,
        request_exchange_code=US_COMPOSITE_EXCHANGE_CODE,
        request_mic_code=None,
        request_filter_policy=REQUEST_FILTER_POLICY,
        isin="US5949181045",
        cusip="594918104",
        source_content_hash=(
            "sha256:7cf537dff253355990e3a4253a912165b8eaf8081e4baaa9d828be0ca2d6fa4f"
        ),
    ),
)


def _member_body(value: UsCompositeMember) -> dict[str, object]:
    return {
        "memberOrdinal": value.member_ordinal,
        "securityId": value.security_id,
        "symbol": value.symbol,
        "expectedOperatingMic": value.expected_operating_mic,
        "requestExchangeCode": value.request_exchange_code,
        "requestMicCode": value.request_mic_code,
        "requestFilterPolicy": value.request_filter_policy,
        "isin": value.isin,
        "cusip": value.cusip,
        "sourceContentHash": value.source_content_hash,
    }


def _job_body(value: UsCompositeJob, *, include_hash: bool) -> dict[str, object]:
    body: dict[str, object] = {
        "jobOrdinal": value.job_ordinal,
        "memberOrdinal": value.member_ordinal,
        "securityId": value.security_id,
        "expectedSymbol": value.expected_symbol,
        "expectedOperatingMic": value.expected_operating_mic,
        "requestExchangeCode": value.request_exchange_code,
        "requestMicCode": value.request_mic_code,
        "requestFilterPolicy": value.request_filter_policy,
        "identifierType": value.identifier_type,
        "identifierValue": value.identifier_value,
    }
    if include_hash:
        body["contentHash"] = value.content_hash
    return body


def _wire_job_body(value: UsCompositeJob) -> dict[str, object]:
    return {
        "currency": "USD",
        "exchCode": US_COMPOSITE_EXCHANGE_CODE,
        "idType": value.identifier_type,
        "idValue": value.identifier_value,
        "includeUnlistedEquities": False,
        "marketSecDes": "Equity",
    }


def _wire_bytes(jobs: tuple[UsCompositeJob, ...]) -> bytes:
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


def _request_body(value: UsCompositeRequest) -> dict[str, object]:
    return {
        "requestOrdinal": value.request_ordinal,
        "requestIdentity": value.request_identity,
        "jobs": [_job_body(item, include_hash=True) for item in value.jobs],
        "bodySha256": value.body_sha256,
        "wireContentHash": value.wire_content_hash,
    }


def _plan_body(value: UsCompositePlan, *, include_hash: bool) -> dict[str, object]:
    body: dict[str, object] = {
        "contractVersion": value.contract_version,
        "planVersion": value.plan_version,
        "predecessorRejectedPlanContentHash": (
            value.predecessor_rejected_plan_content_hash
        ),
        "predecessorRejectedReviewContentHash": (
            value.predecessor_rejected_review_content_hash
        ),
        "predecessorCheckpointReceiptSetHash": (
            value.predecessor_checkpoint_receipt_set_hash
        ),
        "predecessorDiagnosticAcceptanceContentHash": (
            value.predecessor_diagnostic_acceptance_content_hash
        ),
        "predecessorStorageRejectionContentHash": (
            value.predecessor_storage_rejection_content_hash
        ),
        "providerOrigin": value.provider_origin,
        "endpointPath": value.endpoint_path,
        "requestFilterPolicyVersion": value.request_filter_policy_version,
        "tickerAliasPolicyVersion": value.ticker_alias_policy_version,
        "pairIdentityContractVersion": value.pair_identity_contract_version,
        "evidenceClaim": value.evidence_claim,
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


def _build_frozen_plan_unchecked() -> UsCompositePlan:
    jobs: list[UsCompositeJob] = []
    for member in FROZEN_MEMBERS:
        for identifier_type, identifier_value in (
            ("ID_ISIN", member.isin),
            ("ID_CUSIP", member.cusip),
        ):
            provisional = UsCompositeJob(
                job_ordinal=len(jobs) + 1,
                member_ordinal=member.member_ordinal,
                security_id=member.security_id,
                expected_symbol=member.symbol,
                expected_operating_mic=member.expected_operating_mic,
                request_exchange_code=member.request_exchange_code,
                request_mic_code=None,
                request_filter_policy=member.request_filter_policy,
                identifier_type=identifier_type,
                identifier_value=identifier_value,
                content_hash="",
            )
            jobs.append(
                UsCompositeJob(
                    **{
                        **asdict(provisional),
                        "content_hash": canonical_hash(
                            _job_body(provisional, include_hash=False)
                        ),
                    }
                )
            )
    requests: list[UsCompositeRequest] = []
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
            UsCompositeRequest(
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
    provisional = UsCompositePlan(
        contract_version=CONTRACT_VERSION,
        plan_version=PLAN_VERSION,
        predecessor_rejected_plan_content_hash=(
            PREDECESSOR_REJECTED_PLAN_CONTENT_HASH
        ),
        predecessor_rejected_review_content_hash=(
            PREDECESSOR_REJECTED_REVIEW_CONTENT_HASH
        ),
        predecessor_checkpoint_receipt_set_hash=(
            PREDECESSOR_CHECKPOINT_RECEIPT_SET_HASH
        ),
        predecessor_diagnostic_acceptance_content_hash=(
            PREDECESSOR_DIAGNOSTIC_ACCEPTANCE_CONTENT_HASH
        ),
        predecessor_storage_rejection_content_hash=(
            PREDECESSOR_STORAGE_REJECTION_CONTENT_HASH
        ),
        provider_origin=PROVIDER_ORIGIN,
        endpoint_path=ENDPOINT_PATH,
        request_filter_policy_version=REQUEST_FILTER_POLICY_VERSION,
        ticker_alias_policy_version=OPENFIGI_TICKER_ALIAS_POLICY_VERSION,
        pair_identity_contract_version=PAIR_IDENTITY_CONTRACT_VERSION,
        evidence_claim=EVIDENCE_CLAIM,
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
    return UsCompositePlan(
        **{
            **asdict(provisional),
            "members": provisional.members,
            "requests": provisional.requests,
            "content_hash": canonical_hash(_plan_body(provisional, include_hash=False)),
        }
    )


# Resealed below after the canonical plan was generated.  Any change requires
# another successor rather than mutation of this identity.
FROZEN_PLAN_CONTENT_HASH = (
    "F7F2E728FB4B91D9FA7E9B7F63B5E38259655B7B64D798BD63BE54DCA187FB40"
)
FROZEN_REQUEST_IDENTITIES = (
    "B43CE86198BC0F02E6D999D72458215F58A36279FD6678F95A384177F40D6A07",
    "7EB07E02D916A330DFE78488235BD968F80F994E335CE6E1F5D42A54D80F03FC",
)
FROZEN_WIRE_BODY_SHA256 = (
    "8586AA7F7E68618C28208EAB8125AE5F36C9B9CE9D67BC71FFFC8885C91E6072",
    "DF758BDB6B0695B27EFD6D21866CCF29FE22435A4A7431642BCD2CF96FD1E098",
)
FROZEN_WIRE_CONTENT_HASHES = (
    "D3CE775763B644B050AD790D8E8620EEC55766E4D1DFA0A7370E5D766BEBD7EA",
    "E9C18F93FAEDD83F263D21C7FB2CE48DE859F2D255F49473F28974300A72253F",
)


def validate_us_composite_plan_v1(plan: UsCompositePlan) -> None:
    if type(plan) is not UsCompositePlan:
        raise UsCompositeDiagnosticStop("US_COMPOSITE_PLAN_TYPE_INVALID")
    if type(plan.members) is not tuple or type(plan.requests) is not tuple:
        raise UsCompositeDiagnosticStop("US_COMPOSITE_PLAN_COLLECTIONS_MUST_BE_TUPLE")
    if (
        plan.contract_version != CONTRACT_VERSION
        or plan.plan_version != PLAN_VERSION
        or plan.predecessor_rejected_plan_content_hash
        != PREDECESSOR_REJECTED_PLAN_CONTENT_HASH
        or plan.predecessor_rejected_review_content_hash
        != PREDECESSOR_REJECTED_REVIEW_CONTENT_HASH
        or plan.predecessor_checkpoint_receipt_set_hash
        != PREDECESSOR_CHECKPOINT_RECEIPT_SET_HASH
        or plan.predecessor_diagnostic_acceptance_content_hash
        != PREDECESSOR_DIAGNOSTIC_ACCEPTANCE_CONTENT_HASH
        or plan.predecessor_storage_rejection_content_hash
        != PREDECESSOR_STORAGE_REJECTION_CONTENT_HASH
        or plan.provider_origin != PROVIDER_ORIGIN
        or plan.endpoint_path != ENDPOINT_PATH
        or plan.request_filter_policy_version != REQUEST_FILTER_POLICY_VERSION
        or plan.ticker_alias_policy_version != OPENFIGI_TICKER_ALIAS_POLICY_VERSION
        or plan.pair_identity_contract_version != PAIR_IDENTITY_CONTRACT_VERSION
        or plan.evidence_claim != EVIDENCE_CLAIM
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
        raise UsCompositeDiagnosticStop("US_COMPOSITE_PLAN_ROOT_BINDING_DRIFT")
    expected_jobs: list[UsCompositeJob] = []
    for expected_ordinal, member in enumerate(plan.members, start=1):
        if (
            type(member) is not UsCompositeMember
            or type(member.member_ordinal) is not int
            or member.member_ordinal != expected_ordinal
            or type(member.security_id) is not str
            or type(member.symbol) is not str
            or _SYMBOL.fullmatch(member.symbol) is None
            or member.expected_operating_mic != EXPECTED_OPERATING_MIC
            or _MIC.fullmatch(member.expected_operating_mic) is None
            or member.request_exchange_code != US_COMPOSITE_EXCHANGE_CODE
            or member.request_mic_code is not None
            or member.request_filter_policy != REQUEST_FILTER_POLICY
            or _ISIN.fullmatch(member.isin) is None
            or _CUSIP.fullmatch(member.cusip) is None
            or _LOWER_SOURCE_SHA256.fullmatch(member.source_content_hash) is None
        ):
            raise UsCompositeDiagnosticStop("US_COMPOSITE_MEMBER_INVALID")
    for request_index, request in enumerate(plan.requests, start=1):
        expected_cardinality = 5 if request_index == 1 else 1
        if (
            type(request) is not UsCompositeRequest
            or type(request.jobs) is not tuple
            or len(request.jobs) != expected_cardinality
            or type(request.request_ordinal) is not int
            or request.request_ordinal != request_index
        ):
            raise UsCompositeDiagnosticStop("US_COMPOSITE_REQUEST_BINDING_DRIFT")
        for job in request.jobs:
            if (
                type(job) is not UsCompositeJob
                or type(job.member_ordinal) is not int
                or not 1 <= job.member_ordinal <= MEMBER_COUNT
                or type(job.job_ordinal) is not int
                or not 1 <= job.job_ordinal <= LOGICAL_JOB_COUNT
            ):
                raise UsCompositeDiagnosticStop("US_COMPOSITE_JOB_ORDINAL_INVALID")
            member = plan.members[job.member_ordinal - 1]
            expected_identifier_type = "ID_ISIN" if job.job_ordinal % 2 else "ID_CUSIP"
            expected_identifier_value = (
                member.isin if expected_identifier_type == "ID_ISIN" else member.cusip
            )
            if (
                job.security_id != member.security_id
                or job.expected_symbol != member.symbol
                or job.expected_operating_mic != EXPECTED_OPERATING_MIC
                or job.request_exchange_code != US_COMPOSITE_EXCHANGE_CODE
                or job.request_mic_code is not None
                or job.request_filter_policy != REQUEST_FILTER_POLICY
                or job.identifier_type != expected_identifier_type
                or job.identifier_value != expected_identifier_value
                or job.content_hash != canonical_hash(_job_body(job, include_hash=False))
            ):
                raise UsCompositeDiagnosticStop("US_COMPOSITE_JOB_BINDING_DRIFT")
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
            raise UsCompositeDiagnosticStop("US_COMPOSITE_REQUEST_HASH_DRIFT")
    if tuple(item.job_ordinal for item in expected_jobs) != tuple(
        range(1, LOGICAL_JOB_COUNT + 1)
    ):
        raise UsCompositeDiagnosticStop("US_COMPOSITE_JOB_ORDER_DRIFT")
    if len({item.request_identity for item in plan.requests}) != PHYSICAL_REQUEST_COUNT:
        raise UsCompositeDiagnosticStop("US_COMPOSITE_REQUEST_IDENTITY_DUPLICATE")
    if plan.content_hash != canonical_hash(_plan_body(plan, include_hash=False)):
        raise UsCompositeDiagnosticStop("US_COMPOSITE_PLAN_CONTENT_HASH_DRIFT")


def build_frozen_us_composite_plan_v1() -> UsCompositePlan:
    plan = _build_frozen_plan_unchecked()
    validate_us_composite_plan_v1(plan)
    if (
        plan.content_hash != FROZEN_PLAN_CONTENT_HASH
        or tuple(item.request_identity for item in plan.requests)
        != FROZEN_REQUEST_IDENTITIES
        or tuple(item.body_sha256 for item in plan.requests)
        != FROZEN_WIRE_BODY_SHA256
        or tuple(item.wire_content_hash for item in plan.requests)
        != FROZEN_WIRE_CONTENT_HASHES
    ):
        raise UsCompositeDiagnosticStop("US_COMPOSITE_FROZEN_HASH_DRIFT")
    return plan


def build_us_composite_wire_requests_v1(
    plan: UsCompositePlan,
) -> tuple[ProviderWireRequest, ...]:
    """Return exact public-identifier requests without owning a transport."""

    validate_us_composite_plan_v1(plan)
    if plan.content_hash != FROZEN_PLAN_CONTENT_HASH:
        raise UsCompositeDiagnosticStop("US_COMPOSITE_FROZEN_HASH_DRIFT")
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
            raise UsCompositeDiagnosticStop("US_COMPOSITE_WIRE_HASH_DRIFT")
    return wires


def _validate_provider_candidate(candidate: dict[str, Any]) -> None:
    if type(candidate.get("figi")) is not str or _FIGI.fullmatch(candidate["figi"]) is None:
        raise UsCompositeDiagnosticStop("US_COMPOSITE_CANDIDATE_SCHEMA_INVALID")
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
        item = candidate.get(field)
        if item is not None and type(item) is not str:
            raise UsCompositeDiagnosticStop("US_COMPOSITE_CANDIDATE_SCHEMA_INVALID")
        if type(item) is str and (not item or item != item.strip()):
            raise UsCompositeDiagnosticStop("US_COMPOSITE_CANDIDATE_SCHEMA_INVALID")
    for field in ("shareClassFIGI", "compositeFIGI"):
        item = candidate.get(field)
        if item is not None and _FIGI.fullmatch(item) is None:
            raise UsCompositeDiagnosticStop("US_COMPOSITE_CANDIDATE_SCHEMA_INVALID")
    ticker = candidate.get("ticker")
    if ticker is not None and (
        len(ticker) > MAX_PROVIDER_ENVELOPE_TICKER_LENGTH
        or any(ord(character) < 32 or ord(character) == 127 for character in ticker)
    ):
        raise UsCompositeDiagnosticStop("US_COMPOSITE_CANDIDATE_SCHEMA_INVALID")
    exchange_code = candidate.get("exchCode")
    if exchange_code is not None and _EXCHANGE_CODE.fullmatch(exchange_code) is None:
        raise UsCompositeDiagnosticStop("US_COMPOSITE_CANDIDATE_SCHEMA_INVALID")


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
        raise UsCompositeDiagnosticStop("US_COMPOSITE_CANDIDATE_SCHEMA_INVALID")
    if (
        _FIGI.fullmatch(candidate["figi"]) is None
        or _FIGI.fullmatch(candidate["shareClassFIGI"]) is None
        or _FIGI.fullmatch(candidate["compositeFIGI"]) is None
        or candidate["figi"] != candidate["compositeFIGI"]
        or _OPENFIGI_PROVIDER_TICKER.fullmatch(candidate["ticker"]) is None
        or candidate["exchCode"] != US_COMPOSITE_EXCHANGE_CODE
        or candidate["marketSector"] != "Equity"
        or candidate["securityType"] != "Common Stock"
    ):
        raise UsCompositeDiagnosticStop("US_COMPOSITE_CANDIDATE_SCHEMA_INVALID")
    return {
        field: candidate[field]
        for field in ("figi", "shareClassFIGI", "compositeFIGI", "ticker", "exchCode")
    }


def _job_review_body(
    value: UsCompositeJobReview, *, include_hash: bool
) -> dict[str, object]:
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


def _pair_review_body(
    value: UsCompositePairReview, *, include_hash: bool
) -> dict[str, object]:
    body: dict[str, object] = {
        "memberOrdinal": value.member_ordinal,
        "securityId": value.security_id,
        "firstIdentifierType": value.first_identifier_type,
        "secondIdentifierType": value.second_identifier_type,
        "firstPrimaryProviderIdentityHash": value.first_primary_provider_identity_hash,
        "secondPrimaryProviderIdentityHash": value.second_primary_provider_identity_hash,
        "completeConvergent": value.complete_convergent,
        "conflict": value.conflict,
    }
    if include_hash:
        body["contentHash"] = value.content_hash
    return body


def _review_body(value: UsCompositeReview, *, include_hash: bool) -> dict[str, object]:
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


def build_us_composite_review_v1(
    plan: UsCompositePlan,
    responses: tuple[TransportResponse, ...],
) -> UsCompositeReview:
    """Validate exact provider bytes and emit a value-free diagnostic review."""

    validate_us_composite_plan_v1(plan)
    if type(responses) is not tuple or len(responses) != PHYSICAL_REQUEST_COUNT:
        raise UsCompositeDiagnosticStop("US_COMPOSITE_RESPONSE_SET_CARDINALITY_DRIFT")
    reviews: list[UsCompositeJobReview] = []
    for request, response in zip(plan.requests, responses, strict=True):
        if type(response) is not TransportResponse:
            raise UsCompositeDiagnosticStop("US_COMPOSITE_RESPONSE_TYPE_INVALID")
        if type(response.status_code) is not int or response.status_code != 200:
            raise UsCompositeDiagnosticStop("US_COMPOSITE_HTTP_STATUS_INVALID")
        if type(response.body) is not bytes:
            raise UsCompositeDiagnosticStop("US_COMPOSITE_RESPONSE_BODY_MUST_BE_BYTES")
        payload = _strict_json_loads(response.body)
        if type(payload) is not list or len(payload) != len(request.jobs):
            raise UsCompositeDiagnosticStop("US_COMPOSITE_RESPONSE_CARDINALITY_DRIFT")
        for logical_ordinal, (job, item) in enumerate(
            zip(request.jobs, payload, strict=True), start=1
        ):
            if type(item) is not dict:
                raise UsCompositeDiagnosticStop("US_COMPOSITE_RESPONSE_ITEM_INVALID")
            keys = tuple(item)
            if len(keys) != 1 or keys[0] not in {"data", "warning", "error"}:
                raise UsCompositeDiagnosticStop("US_COMPOSITE_RESPONSE_KIND_INVALID")
            response_kind = keys[0].upper()
            candidates: list[object]
            if response_kind == "DATA":
                candidates = item["data"]
                if type(candidates) is not list or not candidates:
                    raise UsCompositeDiagnosticStop("US_COMPOSITE_RESPONSE_DATA_INVALID")
            else:
                message = item[keys[0]]
                if (
                    type(message) is not str
                    or not message
                    or message != message.strip()
                    or len(message) > MAX_PROVIDER_MESSAGE_LENGTH
                ):
                    raise UsCompositeDiagnosticStop(
                        "US_COMPOSITE_RESPONSE_MESSAGE_INVALID"
                    )
                candidates = []
            primary: list[dict[str, Any]] = []
            for candidate in candidates:
                if type(candidate) is not dict:
                    raise UsCompositeDiagnosticStop("US_COMPOSITE_CANDIDATE_INVALID")
                _validate_provider_candidate(candidate)
                if (
                    canonical_openfigi_ticker_for_expected_v1(
                        candidate.get("ticker"), job.expected_symbol
                    )
                    == job.expected_symbol
                    and candidate.get("figi") == candidate.get("compositeFIGI")
                    and candidate.get("exchCode") == US_COMPOSITE_EXCHANGE_CODE
                    and candidate.get("marketSector") == "Equity"
                    and candidate.get("securityType") == "Common Stock"
                ):
                    _provider_identity_body(candidate)
                    primary.append(candidate)
            if response_kind == "WARNING":
                state = UsCompositeOutcomeState.UNRESOLVED_WARNING
            elif response_kind == "ERROR":
                state = UsCompositeOutcomeState.UNRESOLVED_ERROR
            elif len(primary) == 1:
                state = UsCompositeOutcomeState.UNIQUE_PRIMARY
            elif len(primary) > 1:
                state = UsCompositeOutcomeState.AMBIGUOUS_PRIMARY
            else:
                state = UsCompositeOutcomeState.NO_PRIMARY
            provisional = UsCompositeJobReview(
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
                UsCompositeJobReview(
                    **{
                        **asdict(provisional),
                        "outcome_state": provisional.outcome_state,
                        "content_hash": canonical_hash(
                            _job_review_body(provisional, include_hash=False)
                        ),
                    }
                )
            )
    pairs: list[UsCompositePairReview] = []
    for member in plan.members:
        member_reviews = tuple(
            item for item in reviews if item.security_id == member.security_id
        )
        if len(member_reviews) != 2:
            raise UsCompositeDiagnosticStop("US_COMPOSITE_PAIR_CARDINALITY_DRIFT")
        hashes = tuple(item.primary_provider_identity_hash for item in member_reviews)
        complete = (
            all(
                item.outcome_state is UsCompositeOutcomeState.UNIQUE_PRIMARY
                for item in member_reviews
            )
            and hashes[0] is not None
            and hashes[0] == hashes[1]
        )
        conflict = hashes[0] is not None and hashes[1] is not None and hashes[0] != hashes[1]
        provisional_pair = UsCompositePairReview(
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
            UsCompositePairReview(
                **{
                    **asdict(provisional_pair),
                    "content_hash": canonical_hash(
                        _pair_review_body(provisional_pair, include_hash=False)
                    ),
                }
            )
        )
    states = Counter(item.outcome_state for item in reviews)
    provisional_review = UsCompositeReview(
        plan_content_hash=plan.content_hash,
        physical_request_count=PHYSICAL_REQUEST_COUNT,
        logical_job_count=LOGICAL_JOB_COUNT,
        unique_primary_count=states[UsCompositeOutcomeState.UNIQUE_PRIMARY],
        warning_count=states[UsCompositeOutcomeState.UNRESOLVED_WARNING],
        error_count=states[UsCompositeOutcomeState.UNRESOLVED_ERROR],
        ambiguous_primary_count=states[UsCompositeOutcomeState.AMBIGUOUS_PRIMARY],
        no_primary_count=states[UsCompositeOutcomeState.NO_PRIMARY],
        complete_convergent_pair_count=sum(item.complete_convergent for item in pairs),
        pair_conflict_count=sum(item.conflict for item in pairs),
        jobs=tuple(reviews),
        pairs=tuple(pairs),
        content_hash="",
    )
    result = UsCompositeReview(
        **{
            **asdict(provisional_review),
            "jobs": provisional_review.jobs,
            "pairs": provisional_review.pairs,
            "content_hash": canonical_hash(
                _review_body(provisional_review, include_hash=False)
            ),
        }
    )
    validate_us_composite_review_v1(plan, result)
    return result


def validate_us_composite_review_v1(
    plan: UsCompositePlan, review: UsCompositeReview
) -> None:
    validate_us_composite_plan_v1(plan)
    if type(review) is not UsCompositeReview:
        raise UsCompositeDiagnosticStop("US_COMPOSITE_REVIEW_TYPE_INVALID")
    if type(review.jobs) is not tuple or type(review.pairs) is not tuple:
        raise UsCompositeDiagnosticStop("US_COMPOSITE_REVIEW_COLLECTIONS_MUST_BE_TUPLE")
    counts = (
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
    if any(type(item) is not int or item < 0 for item in counts):
        raise UsCompositeDiagnosticStop("US_COMPOSITE_REVIEW_COUNT_INVALID")
    states = Counter(item.outcome_state for item in review.jobs)
    if (
        review.plan_content_hash != plan.content_hash
        or review.physical_request_count != PHYSICAL_REQUEST_COUNT
        or review.logical_job_count != LOGICAL_JOB_COUNT
        or len(review.jobs) != LOGICAL_JOB_COUNT
        or len(review.pairs) != MEMBER_COUNT
        or review.unique_primary_count
        != states[UsCompositeOutcomeState.UNIQUE_PRIMARY]
        or review.warning_count
        != states[UsCompositeOutcomeState.UNRESOLVED_WARNING]
        or review.error_count != states[UsCompositeOutcomeState.UNRESOLVED_ERROR]
        or review.ambiguous_primary_count
        != states[UsCompositeOutcomeState.AMBIGUOUS_PRIMARY]
        or review.no_primary_count != states[UsCompositeOutcomeState.NO_PRIMARY]
        or review.complete_convergent_pair_count
        != sum(item.complete_convergent for item in review.pairs)
        or review.pair_conflict_count != sum(item.conflict for item in review.pairs)
        or review.content_hash != canonical_hash(_review_body(review, include_hash=False))
    ):
        raise UsCompositeDiagnosticStop("US_COMPOSITE_REVIEW_AGGREGATE_DRIFT")
    expected_jobs = tuple(job for request in plan.requests for job in request.jobs)
    request_by_job = {
        job.job_ordinal: (request, logical_ordinal)
        for request in plan.requests
        for logical_ordinal, job in enumerate(request.jobs, start=1)
    }
    for job, item in zip(expected_jobs, review.jobs, strict=True):
        if type(item) is not UsCompositeJobReview:
            raise UsCompositeDiagnosticStop("US_COMPOSITE_REVIEW_JOB_DRIFT")
        request, logical_ordinal = request_by_job[job.job_ordinal]
        expected_state = (
            UsCompositeOutcomeState.UNRESOLVED_WARNING
            if item.response_kind == "WARNING"
            else UsCompositeOutcomeState.UNRESOLVED_ERROR
            if item.response_kind == "ERROR"
            else UsCompositeOutcomeState.UNIQUE_PRIMARY
            if item.primary_match_count == 1
            else UsCompositeOutcomeState.AMBIGUOUS_PRIMARY
            if item.primary_match_count > 1
            else UsCompositeOutcomeState.NO_PRIMARY
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
            or (
                item.primary_provider_identity_hash is not None
                and _UPPER_SHA256.fullmatch(item.primary_provider_identity_hash) is None
            )
            or item.content_hash
            != canonical_hash(_job_review_body(item, include_hash=False))
        ):
            raise UsCompositeDiagnosticStop("US_COMPOSITE_REVIEW_JOB_DRIFT")
    for member, pair in zip(plan.members, review.pairs, strict=True):
        if type(pair) is not UsCompositePairReview:
            raise UsCompositeDiagnosticStop("US_COMPOSITE_REVIEW_PAIR_DRIFT")
        member_jobs = tuple(
            item for item in review.jobs if item.security_id == member.security_id
        )
        first_hash = member_jobs[0].primary_provider_identity_hash
        second_hash = member_jobs[1].primary_provider_identity_hash
        expected_complete = (
            all(
                item.outcome_state is UsCompositeOutcomeState.UNIQUE_PRIMARY
                for item in member_jobs
            )
            and first_hash is not None
            and first_hash == second_hash
        )
        expected_conflict = (
            first_hash is not None
            and second_hash is not None
            and first_hash != second_hash
        )
        if (
            type(pair.member_ordinal) is not int
            or pair.member_ordinal != member.member_ordinal
            or pair.security_id != member.security_id
            or pair.first_identifier_type != "ID_ISIN"
            or pair.second_identifier_type != "ID_CUSIP"
            or pair.first_primary_provider_identity_hash != first_hash
            or pair.second_primary_provider_identity_hash != second_hash
            or pair.complete_convergent is not expected_complete
            or pair.conflict is not expected_conflict
            or pair.content_hash
            != canonical_hash(_pair_review_body(pair, include_hash=False))
        ):
            raise UsCompositeDiagnosticStop("US_COMPOSITE_REVIEW_PAIR_DRIFT")


def _acceptance_body(
    value: UsCompositeAcceptance, *, include_hash: bool
) -> dict[str, object]:
    body: dict[str, object] = {
        "contractVersion": ACCEPTANCE_VERSION,
        "planContentHash": value.plan_content_hash,
        "reviewContentHash": value.review_content_hash,
        "accepted": value.accepted,
        "decisionCode": value.decision_code,
        "diagnosticOnly": value.diagnostic_only,
        "postPredecessorObservation": value.post_predecessor_observation,
        "durableIdentityAuthorized": value.durable_identity_authorized,
        "remainderAuthorized": value.remainder_authorized,
        "evidenceUpgradeAuthorized": value.evidence_upgrade_authorized,
        "operatingMicBindingStatus": value.operating_mic_binding_status,
    }
    if include_hash:
        body["contentHash"] = value.content_hash
    return body


def _acceptance_gate_passes(review: UsCompositeReview) -> bool:
    return (
        review.unique_primary_count == LOGICAL_JOB_COUNT
        and review.warning_count == 0
        and review.error_count == 0
        and review.ambiguous_primary_count == 0
        and review.no_primary_count == 0
        and review.complete_convergent_pair_count == MEMBER_COUNT
        and review.pair_conflict_count == 0
        and all(item.complete_convergent for item in review.pairs)
    )


def seal_us_composite_acceptance_v1(
    plan: UsCompositePlan,
    review: UsCompositeReview,
    *,
    accepted: bool,
    decision_code: str,
) -> UsCompositeAcceptance:
    validate_us_composite_review_v1(plan, review)
    if type(accepted) is not bool or type(decision_code) is not str:
        raise UsCompositeDiagnosticStop("US_COMPOSITE_ACCEPTANCE_DECISION_INVALID")
    gate_passes = _acceptance_gate_passes(review)
    if accepted is True:
        if not gate_passes:
            raise UsCompositeDiagnosticStop(
                "US_COMPOSITE_ACCEPTANCE_COMPLETENESS_GATE_FAILED"
            )
        if decision_code != ACCEPTED_DECISION_CODE:
            raise UsCompositeDiagnosticStop(
                "US_COMPOSITE_ACCEPTANCE_SUCCESS_CODE_INVALID"
            )
    else:
        if gate_passes:
            raise UsCompositeDiagnosticStop(
                "US_COMPOSITE_REJECTION_REQUIRES_FAILED_GATE"
            )
        if decision_code != REJECTED_DECISION_CODE:
            raise UsCompositeDiagnosticStop(
                "US_COMPOSITE_ACCEPTANCE_REJECTION_CODE_INVALID"
            )
    provisional = UsCompositeAcceptance(
        plan_content_hash=plan.content_hash,
        review_content_hash=review.content_hash,
        accepted=accepted,
        decision_code=decision_code,
        diagnostic_only=True,
        post_predecessor_observation=True,
        durable_identity_authorized=False,
        remainder_authorized=False,
        evidence_upgrade_authorized=False,
        operating_mic_binding_status=OPERATING_MIC_BINDING_STATUS,
        content_hash="",
    )
    result = UsCompositeAcceptance(
        **{
            **asdict(provisional),
            "content_hash": canonical_hash(
                _acceptance_body(provisional, include_hash=False)
            ),
        }
    )
    validate_us_composite_acceptance_v1(plan, review, result)
    return result


def validate_us_composite_acceptance_v1(
    plan: UsCompositePlan,
    review: UsCompositeReview,
    value: UsCompositeAcceptance,
) -> None:
    validate_us_composite_review_v1(plan, review)
    if type(value) is not UsCompositeAcceptance:
        raise UsCompositeDiagnosticStop("US_COMPOSITE_ACCEPTANCE_TYPE_INVALID")
    if (
        value.plan_content_hash != plan.content_hash
        or value.review_content_hash != review.content_hash
        or type(value.accepted) is not bool
        or value.diagnostic_only is not True
        or value.post_predecessor_observation is not True
        or value.durable_identity_authorized is not False
        or value.remainder_authorized is not False
        or value.evidence_upgrade_authorized is not False
        or value.operating_mic_binding_status != OPERATING_MIC_BINDING_STATUS
        or _UPPER_SHA256.fullmatch(value.content_hash) is None
        or value.content_hash
        != canonical_hash(_acceptance_body(value, include_hash=False))
    ):
        raise UsCompositeDiagnosticStop("US_COMPOSITE_ACCEPTANCE_DRIFT")
    gate_passes = _acceptance_gate_passes(review)
    if (
        value.accepted is not gate_passes
        or value.decision_code
        != (ACCEPTED_DECISION_CODE if gate_passes else REJECTED_DECISION_CODE)
    ):
        raise UsCompositeDiagnosticStop("US_COMPOSITE_ACCEPTANCE_DRIFT")
