"""Governed Stage 8C identity projection v2 for the three accepted targets.

This module is deliberately narrower than the rejected projection v1.  It
rehydrates the accepted OpenFIGI v1.5, SEC v1.6.1, and target-database v1.6
evidence, then produces one deterministic V22 identity graph for GOOG, FOX,
and MSFT.  It never reads market values, creates an investment assessment, or
changes a model-evidence label.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row

from equity_analysis.fundamental_value.openfigi_us_composite_diagnostic_v15 import (
    FROZEN_PLAN_CONTENT_HASH,
    TransportResponse,
    build_frozen_us_composite_plan_v1,
    build_us_composite_review_v1,
    build_us_composite_wire_requests_v1,
    validate_us_composite_review_v1,
)
from equity_analysis.fundamental_value.openfigi_us_composite_diagnostic_v15 import (
    canonical_hash as stage8c_canonical_hash,
)
from equity_analysis.fundamental_value.openfigi_us_composite_execution_v15 import (
    CONTROLLER_AUTHORITY_CONTENT_HASH as OPENFIGI_CONTROLLER_AUTHORITY_HASH,
)
from equity_analysis.fundamental_value.openfigi_us_composite_execution_v15 import (
    seal_us_composite_phase_authorization_v1,
    verify_us_composite_review_from_storage_v1,
)
from equity_analysis.fundamental_value.stage8c_sec_inventory_v16 import (
    InventoryAdoptionState,
)
from equity_analysis.fundamental_value.stage8c_sec_response_repair_v161 import (
    build_sec_response_review_v161,
    validate_sec_response_review_v161,
)
from equity_analysis.fundamental_value.stage8c_target_inventory_execution_v16 import (
    CONTROLLER_AUTHORITY_CONTENT_HASH as INVENTORY_CONTROLLER_AUTHORITY_HASH,
)
from equity_analysis.fundamental_value.stage8c_target_inventory_execution_v16 import (
    execute_target_inventory_read_v16,
    seal_target_inventory_phase_authorization_v16,
)

CONTRACT_VERSION = "FV-STAGE8C-FORWARD-IDENTITY-PROJECTION-v2.0.0"
REGISTRY_VERSION = "security-identity-registry-v1.0.0"
IDENTITY_AUTHORITY_VERSION = "FV-STAGE8C-IDENTITY-AUTHORITY-v1.0.0"
EVIDENCE_CLAIM = "ENGINEERING_IDENTITY_AUTHORITY_ONLY"
MODEL_EVIDENCE_LABEL = "NOT_VALIDATED"
INVENTORY_AS_OF_DATE = "2026-08-02"
TICKER_VALID_FROM = "2026-08-02"
CANONICAL_MIC = "XNAS"
CURRENCY = "USD"
INSTRUMENT_TYPE = "COMMON_STOCK"

OPENFIGI_RUN_ID = "20260802T145200Z-STAGE8C-OPENFIGI-V15-001"
OPENFIGI_RESULT_HASH = (
    "AD83ACD175AFA01D706D689EE48B93233BB8D95D6B494655B7E15337B5FDC6B7"
)
OPENFIGI_REVIEW_HASH = (
    "E53CF93A88523B8F91F5F84AB59FD230F5335E218970B87FB77321BF1AA57747"
)
OPENFIGI_RESPONSE_HASHES = (
    "81EE819739AF3CD6E9621C1CA832392AEC7FD6D418880EE4F7DF3208C41C266F",
    "038300D73D8ABB2E6D3D9775078A1EFF6040CE4C8CA4CF6B1F62580EC2EC9364",
)

SEC_RUN_ID = "20260802T151948Z-STAGE8C-SEC-V16-001"
SEC_RESULT_HASH = (
    "826041EEBFFF3C135DBC6C5154E3CB7F8F0B0D9F6FBCB797549DF1A57DB50050"
)
SEC_ACCEPTANCE_HASH = (
    "FF4286FBC31CB413BF92C3ECBBDC618F7913E80622CC211A4B46E8A16EFB169A"
)
SEC_REVIEW_HASH = (
    "8060C22C1D911BF6108A9AD0BB407EED80B81CE6E2089C45AF4F3A19398E4745"
)
SEC_RESPONSE_SHA256 = (
    "E6FBAD74D63540E73239F257809CF217B9D6B4FED2410691F0C8C576C9A6CF3C"
)
SEC_REQUEST_IDENTITY = (
    "66E405FA9B8AC01A32DDAED38524BE0161CFAE1406BE6DCB9B6F2EAD3F1D4210"
)

INVENTORY_RUN_ID = "20260812-STAGE8C-DB-INVENTORY-V16-001"
INVENTORY_AUTHORIZATION_HASH = (
    "6AC4E9A95F727AA6D96850771F52A610662D0C96DBDF8C56D1CFFFC97DDE2C3D"
)
INVENTORY_REVIEW_HASH = (
    "8AC0DC15E6D0FABC89C2F42DC1D7D929F0AF54C6FB4F37803849F81740ED5FCE"
)
INVENTORY_RECEIPT_HASH = (
    "F1BEDECEE6343F4CC7D0F4C674066C75F44EE6DA979C61EB799B4D068667776B"
)

_IDENTITY_NAMESPACE = uuid.UUID("c24370d4-9c81-5fb4-a386-f18620921339")
_UUID = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-"
    r"[89ab][0-9a-f]{3}-[0-9a-f]{12}\Z"
)
_UPPER_HASH = re.compile(r"[0-9A-F]{64}\Z")
_LOWER_HASH = re.compile(r"sha256:[0-9a-f]{64}\Z")
_FIGI = re.compile(r"BBG[A-Z0-9]{9}\Z")
_CIK = re.compile(r"[0-9]{1,10}\Z")
_TICKER = re.compile(r"[A-Z][A-Z0-9.-]{0,31}\Z")


class IdentityProjectionV2Stop(RuntimeError):
    """Fail-closed projection stop with a stable code."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class IdentityProjectionV2PersistenceConflict(RuntimeError):
    """A durable V25 identity or graph conflicts with the sealed projection."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class ProjectedIdentityMemberV2:
    ordinal: int
    ticker: str
    security_id: str
    company_id: str
    instrument_id: str
    share_class_id: str
    listing_id: str
    ticker_assignment_id: str
    adoption_state: str
    existing_public_id: str | None
    company_name: str
    sec_cik: str
    mic: str
    currency: str
    instrument_type: str
    ticker_valid_from: str
    isin: str
    cusip: str
    figi: str
    composite_figi: str
    share_class_figi: str
    openfigi_provider_identity_hash: str
    openfigi_source_hash: str
    sec_source_hash: str
    inventory_decision_hash: str
    content_hash: str


@dataclass(frozen=True)
class IdentityProjectionV2:
    contract_version: str
    authority_version: str
    registry_version: str
    inventory_as_of_date: str
    evidence_claim: str
    model_evidence_label: str
    openfigi_result_hash: str
    openfigi_review_hash: str
    sec_result_hash: str
    sec_acceptance_hash: str
    sec_review_hash: str
    inventory_authorization_hash: str
    inventory_review_hash: str
    inventory_receipt_hash: str
    members: tuple[ProjectedIdentityMemberV2, ...]
    member_set_hash: str
    v22_write_authorized: bool
    v24_enrollment_authorized: bool
    investment_assessment_authorized: bool
    evidence_label_upgrade_authorized: bool
    content_hash: str


def _hash(value: object) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def _strict_json(path: Path) -> Any:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise IdentityProjectionV2Stop("PROJECTION_V2_DUPLICATE_JSON_KEY")
            result[key] = value
        return result

    def reject_constant(_: str) -> None:
        raise IdentityProjectionV2Stop("PROJECTION_V2_NONFINITE_JSON")

    try:
        return json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=pairs,
            parse_constant=reject_constant,
        )
    except IdentityProjectionV2Stop:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise IdentityProjectionV2Stop("PROJECTION_V2_JSON_UNREADABLE") from error


def _uuid(kind: str, value: str) -> str:
    return str(uuid.uuid5(_IDENTITY_NAMESPACE, f"{CONTRACT_VERSION}|{kind}|{value}"))


def _member_body(value: ProjectedIdentityMemberV2, *, include_hash: bool) -> dict[str, Any]:
    body = {
        "ordinal": value.ordinal,
        "ticker": value.ticker,
        "securityId": value.security_id,
        "companyId": value.company_id,
        "instrumentId": value.instrument_id,
        "shareClassId": value.share_class_id,
        "listingId": value.listing_id,
        "tickerAssignmentId": value.ticker_assignment_id,
        "adoptionState": value.adoption_state,
        "existingPublicId": value.existing_public_id,
        "companyName": value.company_name,
        "secCik": value.sec_cik,
        "mic": value.mic,
        "currency": value.currency,
        "instrumentType": value.instrument_type,
        "tickerValidFrom": value.ticker_valid_from,
        "isin": value.isin,
        "cusip": value.cusip,
        "figi": value.figi,
        "compositeFigi": value.composite_figi,
        "shareClassFigi": value.share_class_figi,
        "openFigiProviderIdentityHash": value.openfigi_provider_identity_hash,
        "openFigiSourceHash": value.openfigi_source_hash,
        "secSourceHash": value.sec_source_hash,
        "inventoryDecisionHash": value.inventory_decision_hash,
    }
    if include_hash:
        body["contentHash"] = value.content_hash
    return body


def _projection_body(value: IdentityProjectionV2, *, include_hash: bool) -> dict[str, Any]:
    body = {
        "contractVersion": value.contract_version,
        "authorityVersion": value.authority_version,
        "registryVersion": value.registry_version,
        "inventoryAsOfDate": value.inventory_as_of_date,
        "evidenceClaim": value.evidence_claim,
        "modelEvidenceLabel": value.model_evidence_label,
        "openFigiResultHash": value.openfigi_result_hash,
        "openFigiReviewHash": value.openfigi_review_hash,
        "secResultHash": value.sec_result_hash,
        "secAcceptanceHash": value.sec_acceptance_hash,
        "secReviewHash": value.sec_review_hash,
        "inventoryAuthorizationHash": value.inventory_authorization_hash,
        "inventoryReviewHash": value.inventory_review_hash,
        "inventoryReceiptHash": value.inventory_receipt_hash,
        "members": [_member_body(item, include_hash=True) for item in value.members],
        "memberSetHash": value.member_set_hash,
        "v22WriteAuthorized": value.v22_write_authorized,
        "v24EnrollmentAuthorized": value.v24_enrollment_authorized,
        "investmentAssessmentAuthorized": value.investment_assessment_authorized,
        "evidenceLabelUpgradeAuthorized": value.evidence_label_upgrade_authorized,
    }
    if include_hash:
        body["contentHash"] = value.content_hash
    return body


def validate_identity_projection_v2(value: IdentityProjectionV2) -> None:
    if type(value) is not IdentityProjectionV2 or type(value.members) is not tuple:
        raise IdentityProjectionV2Stop("PROJECTION_V2_TYPE_INVALID")
    if (
        value.contract_version != CONTRACT_VERSION
        or value.authority_version != IDENTITY_AUTHORITY_VERSION
        or value.registry_version != REGISTRY_VERSION
        or value.inventory_as_of_date != INVENTORY_AS_OF_DATE
        or value.evidence_claim != EVIDENCE_CLAIM
        or value.model_evidence_label != MODEL_EVIDENCE_LABEL
        or value.openfigi_result_hash != OPENFIGI_RESULT_HASH
        or value.openfigi_review_hash != OPENFIGI_REVIEW_HASH
        or value.sec_result_hash != SEC_RESULT_HASH
        or value.sec_acceptance_hash != SEC_ACCEPTANCE_HASH
        or value.sec_review_hash != SEC_REVIEW_HASH
        or value.inventory_authorization_hash != INVENTORY_AUTHORIZATION_HASH
        or value.inventory_review_hash != INVENTORY_REVIEW_HASH
        or value.inventory_receipt_hash != INVENTORY_RECEIPT_HASH
        or tuple(item.ticker for item in value.members) != ("GOOG", "FOX", "MSFT")
        or tuple(item.ordinal for item in value.members) != (1, 2, 3)
        or value.v22_write_authorized is not True
        or value.v24_enrollment_authorized is not False
        or value.investment_assessment_authorized is not False
        or value.evidence_label_upgrade_authorized is not False
    ):
        raise IdentityProjectionV2Stop("PROJECTION_V2_ROOT_BINDING_DRIFT")
    identities: set[str] = set()
    for member in value.members:
        if type(member) is not ProjectedIdentityMemberV2:
            raise IdentityProjectionV2Stop("PROJECTION_V2_MEMBER_TYPE_INVALID")
        if (
            _TICKER.fullmatch(member.ticker) is None
            or member.mic != CANONICAL_MIC
            or member.currency != CURRENCY
            or member.instrument_type != INSTRUMENT_TYPE
            or member.ticker_valid_from != TICKER_VALID_FROM
            or _CIK.fullmatch(member.sec_cik) is None
            or any(
                _UUID.fullmatch(item) is None
                for item in (
                    member.security_id,
                    member.company_id,
                    member.instrument_id,
                    member.share_class_id,
                    member.listing_id,
                    member.ticker_assignment_id,
                )
            )
            or any(
                _FIGI.fullmatch(item) is None
                for item in (
                    member.figi,
                    member.composite_figi,
                    member.share_class_figi,
                )
            )
            or _UPPER_HASH.fullmatch(member.openfigi_provider_identity_hash) is None
            or any(
                _LOWER_HASH.fullmatch(item) is None
                for item in (
                    member.openfigi_source_hash,
                    member.sec_source_hash,
                    member.inventory_decision_hash,
                    member.content_hash,
                )
            )
            or member.content_hash != _hash(_member_body(member, include_hash=False))
        ):
            raise IdentityProjectionV2Stop("PROJECTION_V2_MEMBER_BINDING_DRIFT")
        for item in (
            member.security_id,
            member.share_class_id,
            member.listing_id,
            member.ticker_assignment_id,
        ):
            if item in identities:
                raise IdentityProjectionV2Stop("PROJECTION_V2_IDENTITY_DUPLICATE")
            identities.add(item)
    if value.members[2].existing_public_id != value.members[2].security_id:
        raise IdentityProjectionV2Stop("PROJECTION_V2_MSFT_ADOPTION_DRIFT")
    if any(item.existing_public_id is not None for item in value.members[:2]):
        raise IdentityProjectionV2Stop("PROJECTION_V2_NEW_ID_ADOPTION_DRIFT")
    expected_set_hash = _hash([item.content_hash for item in value.members])
    if (
        value.member_set_hash != expected_set_hash
        or value.content_hash != _hash(_projection_body(value, include_hash=False))
    ):
        raise IdentityProjectionV2Stop("PROJECTION_V2_CONTENT_HASH_DRIFT")


def _validate_git_artifact(path: Path, expected_hash: str) -> dict[str, Any]:
    value = _strict_json(path)
    if type(value) is not dict or value.get("contentHash") != expected_hash:
        raise IdentityProjectionV2Stop("PROJECTION_V2_GIT_ARTIFACT_BINDING_DRIFT")
    body = {key: item for key, item in value.items() if key != "contentHash"}
    if stage8c_canonical_hash(body) != expected_hash:
        raise IdentityProjectionV2Stop("PROJECTION_V2_GIT_ARTIFACT_HASH_DRIFT")
    return value


def _load_openfigi(
    repository_root: Path, storage_root: Path
) -> tuple[dict[str, dict[str, str]], dict[str, str], dict[str, str]]:
    artifact = _validate_git_artifact(
        repository_root
        / "contracts/fundamental-value-v1/"
        "stage8c-openfigi-us-composite-diagnostic-v15-result-v1.json",
        OPENFIGI_RESULT_HASH,
    )
    plan = build_frozen_us_composite_plan_v1()
    if plan.content_hash != FROZEN_PLAN_CONTENT_HASH:
        raise IdentityProjectionV2Stop("PROJECTION_V2_OPENFIGI_PLAN_DRIFT")
    authorization = seal_us_composite_phase_authorization_v1(
        plan,
        run_id=OPENFIGI_RUN_ID,
        accepted_controller_authority_content_hash=OPENFIGI_CONTROLLER_AUTHORITY_HASH,
        network_authorized=True,
    )
    run_root = (
        storage_root
        / "FV-STAGE8C-OPENFIGI-US-COMPOSITE-EXECUTION-v1.0.0"
        / OPENFIGI_RUN_ID
    )
    responses: list[TransportResponse] = []
    raw_payloads: list[list[dict[str, Any]]] = []
    for index, wire in enumerate(build_us_composite_wire_requests_v1(plan)):
        path = run_root / "_private/checkpoints" / f"{wire.request_identity}.bin"
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest().upper() != OPENFIGI_RESPONSE_HASHES[index]:
            raise IdentityProjectionV2Stop("PROJECTION_V2_OPENFIGI_CHECKPOINT_HASH_DRIFT")
        parsed = json.loads(raw.decode("utf-8"))
        if type(parsed) is not list:
            raise IdentityProjectionV2Stop("PROJECTION_V2_OPENFIGI_RESPONSE_INVALID")
        raw_payloads.append(parsed)
        responses.append(
            TransportResponse(
                status_code=200,
                headers=(("content-type", "application/json"),),
                body=raw,
            )
        )
    review = build_us_composite_review_v1(plan, tuple(responses))
    validate_us_composite_review_v1(plan, review)
    if review.content_hash != OPENFIGI_REVIEW_HASH:
        raise IdentityProjectionV2Stop("PROJECTION_V2_OPENFIGI_REVIEW_DRIFT")
    verify_us_composite_review_from_storage_v1(
        plan,
        authorization,
        review,
        storage_root=storage_root,
    )
    if artifact["run"]["reviewContentHash"] != review.content_hash:
        raise IdentityProjectionV2Stop("PROJECTION_V2_OPENFIGI_ARTIFACT_DRIFT")
    candidates: dict[str, dict[str, str]] = {}
    source_parts: dict[str, list[str]] = {}
    provider_hashes: dict[str, str] = {}
    logical = 0
    for request, payload in zip(plan.requests, raw_payloads, strict=True):
        if len(payload) != len(request.jobs):
            raise IdentityProjectionV2Stop("PROJECTION_V2_OPENFIGI_CARDINALITY_DRIFT")
        for job, envelope in zip(request.jobs, payload, strict=True):
            logical += 1
            data = envelope.get("data") if type(envelope) is dict else None
            if type(data) is not list or len(data) != 1 or type(data[0]) is not dict:
                raise IdentityProjectionV2Stop("PROJECTION_V2_OPENFIGI_PRIMARY_INVALID")
            candidate = data[0]
            selected = {
                "figi": candidate.get("figi"),
                "compositeFigi": candidate.get("compositeFIGI"),
                "shareClassFigi": candidate.get("shareClassFIGI"),
                "ticker": candidate.get("ticker"),
            }
            if any(type(item) is not str for item in selected.values()):
                raise IdentityProjectionV2Stop("PROJECTION_V2_OPENFIGI_PRIMARY_INVALID")
            symbol = job.expected_symbol
            existing = candidates.get(symbol)
            if existing is not None and existing != selected:
                raise IdentityProjectionV2Stop("PROJECTION_V2_OPENFIGI_PAIR_CONFLICT")
            candidates[symbol] = selected
            source_parts.setdefault(symbol, []).append(
                _hash(
                    {
                        "runId": OPENFIGI_RUN_ID,
                        "requestIdentity": request.request_identity,
                        "logicalOrdinal": logical,
                        "jobOrdinal": job.job_ordinal,
                        "jobContentHash": job.content_hash,
                        "responseBodySha256": OPENFIGI_RESPONSE_HASHES[
                            request.request_ordinal - 1
                        ],
                    }
                )
            )
            matching_review = next(
                item for item in review.jobs if item.job_ordinal == job.job_ordinal
            )
            prior = provider_hashes.get(symbol)
            if prior is not None and prior != matching_review.primary_provider_identity_hash:
                raise IdentityProjectionV2Stop("PROJECTION_V2_OPENFIGI_PAIR_HASH_CONFLICT")
            provider_hashes[symbol] = str(
                matching_review.primary_provider_identity_hash
            )
    source_hashes = {
        symbol: _hash(parts) for symbol, parts in sorted(source_parts.items())
    }
    return candidates, source_hashes, provider_hashes


def _load_sec(
    repository_root: Path, storage_root: Path
) -> tuple[dict[str, dict[str, str]], dict[str, str]]:
    artifact = _validate_git_artifact(
        repository_root
        / "contracts/fundamental-value-v1/"
        "stage8c-sec-corroboration-v161-result-v1.json",
        SEC_RESULT_HASH,
    )
    if artifact["interpretationAcceptance"]["contentHash"] != SEC_ACCEPTANCE_HASH:
        raise IdentityProjectionV2Stop("PROJECTION_V2_SEC_ACCEPTANCE_DRIFT")
    path = (
        storage_root
        / "FV-STAGE8C-SEC-CORROBORATION-EXECUTION-v1.0.0"
        / SEC_RUN_ID
        / "_private/checkpoints"
        / f"{SEC_REQUEST_IDENTITY}.bin"
    )
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest().upper() != SEC_RESPONSE_SHA256:
        raise IdentityProjectionV2Stop("PROJECTION_V2_SEC_CHECKPOINT_HASH_DRIFT")
    review = build_sec_response_review_v161(raw)
    validate_sec_response_review_v161(review)
    if review.content_hash != SEC_REVIEW_HASH or review.accepted is not True:
        raise IdentityProjectionV2Stop("PROJECTION_V2_SEC_REVIEW_DRIFT")
    records: dict[str, dict[str, str]] = {}
    source_hashes: dict[str, str] = {}
    for item in review.target_records:
        records[item.ticker] = {
            "cik": str(int(item.cik)),
            "name": item.name,
            "mic": str(item.canonical_operating_mic),
        }
        source_hashes[item.ticker] = _hash(
            {
                "runId": SEC_RUN_ID,
                "responseBodySha256": SEC_RESPONSE_SHA256,
                "recordContentHash": item.content_hash,
                "claim": review.claim,
            }
        )
    return records, source_hashes


def _load_inventory(stage8c_storage_root: Path) -> tuple[dict[str, Any], dict[str, str]]:
    authorization = seal_target_inventory_phase_authorization_v16(
        run_id=INVENTORY_RUN_ID,
        accepted_controller_authority_content_hash=INVENTORY_CONTROLLER_AUTHORITY_HASH,
        database_read_authorized=True,
    )
    if authorization.content_hash != INVENTORY_AUTHORIZATION_HASH:
        raise IdentityProjectionV2Stop("PROJECTION_V2_INVENTORY_AUTHORIZATION_DRIFT")
    review, receipt = execute_target_inventory_read_v16(
        authorization,
        database_url="postgresql://unreachable.invalid:1/zero-send-replay",
        storage_root=stage8c_storage_root.parents[1],
    )
    if review.content_hash != INVENTORY_REVIEW_HASH:
        raise IdentityProjectionV2Stop("PROJECTION_V2_INVENTORY_REVIEW_DRIFT")
    if receipt.content_hash != INVENTORY_RECEIPT_HASH:
        raise IdentityProjectionV2Stop("PROJECTION_V2_INVENTORY_RECEIPT_DRIFT")
    decisions = {item.ticker: item for item in review.decisions}
    hashes = {item.ticker: _hash(asdict(item)) for item in review.decisions}
    return decisions, hashes


def load_accepted_identity_projection_v2(
    *, repository_root: Path, storage_root: Path
) -> IdentityProjectionV2:
    """Rehydrate all accepted evidence and build the governed projection."""

    root = repository_root.resolve()
    storage = storage_root.resolve()
    if not root.is_dir() or not storage.is_dir() or root.is_symlink() or storage.is_symlink():
        raise IdentityProjectionV2Stop("PROJECTION_V2_ROOT_INVALID")
    openfigi, openfigi_sources, provider_hashes = _load_openfigi(root, storage)
    sec, sec_sources = _load_sec(root, storage)
    inventory, inventory_hashes = _load_inventory(storage)
    plan = build_frozen_us_composite_plan_v1()
    members: list[ProjectedIdentityMemberV2] = []
    for ordinal, source_member in enumerate(plan.members, start=1):
        ticker = source_member.symbol
        figi = openfigi[ticker]
        sec_record = sec[ticker]
        decision = inventory[ticker]
        if sec_record["mic"] != CANONICAL_MIC:
            raise IdentityProjectionV2Stop("PROJECTION_V2_OPERATING_MIC_DRIFT")
        company_id = _uuid("company-sec-cik", sec_record["cik"])
        instrument_id = _uuid("instrument", f"{company_id}|{INSTRUMENT_TYPE}")
        share_class_id = _uuid("share-class-openfigi", figi["shareClassFigi"])
        listing_id = _uuid("listing", f"{share_class_id}|{CANONICAL_MIC}|{CURRENCY}")
        if decision.adoption_state is InventoryAdoptionState.NEW_ID_CANDIDATE:
            existing_public_id = None
            security_id = _uuid("security", listing_id)
        elif (
            decision.adoption_state
            is InventoryAdoptionState.ADOPT_EXISTING_PUBLIC_ID_V22_GRAPH_REQUIRED
            and ticker == "MSFT"
            and decision.existing_public_id is not None
        ):
            existing_public_id = decision.existing_public_id
            security_id = decision.existing_public_id
        else:
            raise IdentityProjectionV2Stop("PROJECTION_V2_INVENTORY_STATE_UNSUPPORTED")
        ticker_assignment_id = _uuid(
            "ticker-assignment", f"{listing_id}|{ticker}|{TICKER_VALID_FROM}"
        )
        provisional = ProjectedIdentityMemberV2(
            ordinal=ordinal,
            ticker=ticker,
            security_id=security_id,
            company_id=company_id,
            instrument_id=instrument_id,
            share_class_id=share_class_id,
            listing_id=listing_id,
            ticker_assignment_id=ticker_assignment_id,
            adoption_state=decision.adoption_state.value,
            existing_public_id=existing_public_id,
            company_name=sec_record["name"],
            sec_cik=sec_record["cik"],
            mic=CANONICAL_MIC,
            currency=CURRENCY,
            instrument_type=INSTRUMENT_TYPE,
            ticker_valid_from=TICKER_VALID_FROM,
            isin=source_member.isin,
            cusip=source_member.cusip,
            figi=figi["figi"],
            composite_figi=figi["compositeFigi"],
            share_class_figi=figi["shareClassFigi"],
            openfigi_provider_identity_hash=provider_hashes[ticker],
            openfigi_source_hash=openfigi_sources[ticker],
            sec_source_hash=sec_sources[ticker],
            inventory_decision_hash=inventory_hashes[ticker],
            content_hash="",
        )
        members.append(
            ProjectedIdentityMemberV2(
                **{
                    **asdict(provisional),
                    "content_hash": _hash(_member_body(provisional, include_hash=False)),
                }
            )
        )
    member_tuple = tuple(members)
    provisional_projection = IdentityProjectionV2(
        contract_version=CONTRACT_VERSION,
        authority_version=IDENTITY_AUTHORITY_VERSION,
        registry_version=REGISTRY_VERSION,
        inventory_as_of_date=INVENTORY_AS_OF_DATE,
        evidence_claim=EVIDENCE_CLAIM,
        model_evidence_label=MODEL_EVIDENCE_LABEL,
        openfigi_result_hash=OPENFIGI_RESULT_HASH,
        openfigi_review_hash=OPENFIGI_REVIEW_HASH,
        sec_result_hash=SEC_RESULT_HASH,
        sec_acceptance_hash=SEC_ACCEPTANCE_HASH,
        sec_review_hash=SEC_REVIEW_HASH,
        inventory_authorization_hash=INVENTORY_AUTHORIZATION_HASH,
        inventory_review_hash=INVENTORY_REVIEW_HASH,
        inventory_receipt_hash=INVENTORY_RECEIPT_HASH,
        members=member_tuple,
        member_set_hash=_hash([item.content_hash for item in member_tuple]),
        v22_write_authorized=True,
        v24_enrollment_authorized=False,
        investment_assessment_authorized=False,
        evidence_label_upgrade_authorized=False,
        content_hash="",
    )
    projection = IdentityProjectionV2(
        **{
            **asdict(provisional_projection),
            "members": member_tuple,
            "content_hash": _hash(
                _projection_body(provisional_projection, include_hash=False)
            ),
        }
    )
    validate_identity_projection_v2(projection)
    return projection


def projection_v2_to_wire(value: IdentityProjectionV2) -> dict[str, Any]:
    """Return the canonical Git-safe projection body."""

    validate_identity_projection_v2(value)
    return _projection_body(value, include_hash=True)


class PostgresIdentityAuthorityV2Repository:
    """Typed V25 writer for one projection and its exact V22 identity graph."""

    def __init__(self, database_url: str) -> None:
        if type(database_url) is not str or not database_url.startswith(
            ("postgresql://", "postgres://")
        ):
            raise IdentityProjectionV2PersistenceConflict(
                "PROJECTION_V2_DATABASE_URL_INVALID"
            )
        self._database_url = database_url

    @staticmethod
    def _authority_id(value: IdentityProjectionV2) -> str:
        return _uuid("authority", value.content_hash)

    @staticmethod
    def _seal_hash(value: IdentityProjectionV2) -> str:
        return _hash(
            {
                "authorityId": PostgresIdentityAuthorityV2Repository._authority_id(
                    value
                ),
                "projectionContentHash": value.content_hash,
                "memberSetHash": value.member_set_hash,
                "memberCount": len(value.members),
            }
        )

    @staticmethod
    def _insert_header(cursor: Any, value: IdentityProjectionV2) -> None:
        cursor.execute(
            """
            INSERT INTO analytics.fv_identity_authority_v2 (
                authority_id,contract_version,authority_version,registry_version,
                inventory_as_of_date,evidence_claim,model_evidence_label,
                openfigi_result_hash,openfigi_review_hash,sec_result_hash,
                sec_acceptance_hash,sec_review_hash,inventory_authorization_hash,
                inventory_review_hash,inventory_receipt_hash,
                projection_content_hash,member_set_hash,member_count,
                v22_write_authorized,v24_enrollment_authorized,
                investment_assessment_authorized,evidence_label_upgrade_authorized,
                idempotency_key,revision,supersedes_authority_id
            ) VALUES (
                %(authority_id)s,%(contract_version)s,%(authority_version)s,
                %(registry_version)s,%(inventory_as_of_date)s,%(evidence_claim)s,
                %(model_evidence_label)s,%(openfigi_result_hash)s,
                %(openfigi_review_hash)s,%(sec_result_hash)s,
                %(sec_acceptance_hash)s,%(sec_review_hash)s,
                %(inventory_authorization_hash)s,%(inventory_review_hash)s,
                %(inventory_receipt_hash)s,%(projection_content_hash)s,
                %(member_set_hash)s,%(member_count)s,%(v22_write_authorized)s,
                %(v24_enrollment_authorized)s,
                %(investment_assessment_authorized)s,
                %(evidence_label_upgrade_authorized)s,%(idempotency_key)s,1,NULL
            )
            """,
            {
                "authority_id": PostgresIdentityAuthorityV2Repository._authority_id(
                    value
                ),
                "contract_version": value.contract_version,
                "authority_version": value.authority_version,
                "registry_version": value.registry_version,
                "inventory_as_of_date": value.inventory_as_of_date,
                "evidence_claim": value.evidence_claim,
                "model_evidence_label": value.model_evidence_label,
                "openfigi_result_hash": value.openfigi_result_hash,
                "openfigi_review_hash": value.openfigi_review_hash,
                "sec_result_hash": value.sec_result_hash,
                "sec_acceptance_hash": value.sec_acceptance_hash,
                "sec_review_hash": value.sec_review_hash,
                "inventory_authorization_hash": value.inventory_authorization_hash,
                "inventory_review_hash": value.inventory_review_hash,
                "inventory_receipt_hash": value.inventory_receipt_hash,
                "projection_content_hash": value.content_hash,
                "member_set_hash": value.member_set_hash,
                "member_count": len(value.members),
                "v22_write_authorized": value.v22_write_authorized,
                "v24_enrollment_authorized": value.v24_enrollment_authorized,
                "investment_assessment_authorized": (
                    value.investment_assessment_authorized
                ),
                "evidence_label_upgrade_authorized": (
                    value.evidence_label_upgrade_authorized
                ),
                "idempotency_key": (
                    f"FV-STAGE8C-PROJECTION-V2:{value.content_hash.removeprefix('sha256:')}"
                ),
            },
        )

    @staticmethod
    def _insert_member(cursor: Any, authority_id: str, member: ProjectedIdentityMemberV2) -> None:
        cursor.execute(
            """
            INSERT INTO analytics.fv_identity_authority_member_v2 (
                authority_id,member_ordinal,ticker,security_id,company_id,
                instrument_id,share_class_id,listing_id,ticker_assignment_id,
                adoption_state,existing_public_id,company_name,sec_cik,mic,
                currency,instrument_type,ticker_valid_from,isin,cusip,figi,
                composite_figi,share_class_figi,
                openfigi_provider_identity_hash,openfigi_source_hash,
                sec_source_hash,inventory_decision_hash,member_content_hash
            ) VALUES (
                %(authority_id)s,%(ordinal)s,%(ticker)s,%(security_id)s,
                %(company_id)s,%(instrument_id)s,%(share_class_id)s,%(listing_id)s,
                %(ticker_assignment_id)s,%(adoption_state)s,%(existing_public_id)s,
                %(company_name)s,%(sec_cik)s,%(mic)s,%(currency)s,
                %(instrument_type)s,%(ticker_valid_from)s,%(isin)s,%(cusip)s,
                %(figi)s,%(composite_figi)s,%(share_class_figi)s,
                %(openfigi_provider_identity_hash)s,%(openfigi_source_hash)s,
                %(sec_source_hash)s,%(inventory_decision_hash)s,%(content_hash)s
            )
            """,
            {"authority_id": authority_id, **asdict(member)},
        )

    @staticmethod
    def _insert_or_validate_security(cursor: Any, member: ProjectedIdentityMemberV2) -> None:
        cursor.execute(
            """
            SELECT public_id::text AS public_id,symbol,exchange,name,
                   instrument_type,currency,active
            FROM analytics.security
            WHERE symbol=%s OR public_id=%s
            ORDER BY id
            """,
            (member.ticker, member.security_id),
        )
        rows = cursor.fetchall()
        if member.existing_public_id is None:
            if rows:
                raise IdentityProjectionV2PersistenceConflict(
                    "PROJECTION_V2_NEW_SECURITY_CONFLICT"
                )
            cursor.execute(
                """
                INSERT INTO analytics.security (
                    public_id,symbol,exchange,name,instrument_type,currency,active
                ) VALUES (%s,%s,%s,%s,%s,%s,true)
                """,
                (
                    member.security_id,
                    member.ticker,
                    member.mic,
                    member.company_name,
                    member.instrument_type,
                    member.currency,
                ),
            )
            return
        if len(rows) != 1:
            raise IdentityProjectionV2PersistenceConflict(
                "PROJECTION_V2_EXISTING_SECURITY_CARDINALITY_CONFLICT"
            )
        row = rows[0]
        if (
            row["public_id"] != member.security_id
            or row["symbol"] != member.ticker
            or row["exchange"] not in ("NASDAQ", "XNAS")
            or row["instrument_type"] != member.instrument_type
            or row["currency"] != member.currency
            or row["active"] is not True
        ):
            raise IdentityProjectionV2PersistenceConflict(
                "PROJECTION_V2_EXISTING_SECURITY_DRIFT"
            )

    @staticmethod
    def _insert_v22_graph(cursor: Any, member: ProjectedIdentityMemberV2) -> None:
        cursor.execute(
            "INSERT INTO analytics.evidence_company_identity_v1 "
            "(company_id,registry_version) VALUES (%s,%s)",
            (member.company_id, REGISTRY_VERSION),
        )
        cursor.execute(
            "INSERT INTO analytics.evidence_instrument_identity_v1 "
            "(instrument_id,company_id,registry_version) VALUES (%s,%s,%s)",
            (member.instrument_id, member.company_id, REGISTRY_VERSION),
        )
        cursor.execute(
            "INSERT INTO analytics.evidence_share_class_identity_v1 "
            "(share_class_id,instrument_id,registry_version) VALUES (%s,%s,%s)",
            (member.share_class_id, member.instrument_id, REGISTRY_VERSION),
        )
        cursor.execute(
            "INSERT INTO analytics.evidence_listing_identity_v1 "
            "(listing_id,share_class_id,security_id,mic,currency,registry_version) "
            "VALUES (%s,%s,%s,%s,%s,%s)",
            (
                member.listing_id,
                member.share_class_id,
                member.security_id,
                member.mic,
                member.currency,
                REGISTRY_VERSION,
            ),
        )
        cursor.execute(
            "INSERT INTO analytics.evidence_ticker_assignment_v1 "
            "(ticker_assignment_id,listing_id,ticker,valid_from,valid_to,"
            "registry_version) VALUES (%s,%s,%s,%s,NULL,%s)",
            (
                member.ticker_assignment_id,
                member.listing_id,
                member.ticker,
                member.ticker_valid_from,
                REGISTRY_VERSION,
            ),
        )

    @staticmethod
    def _load(cursor: Any, projection_content_hash: str) -> IdentityProjectionV2 | None:
        cursor.execute(
            """
            SELECT * FROM analytics.fv_identity_authority_v2
            WHERE projection_content_hash=%s
            """,
            (projection_content_hash,),
        )
        header = cursor.fetchone()
        if header is None:
            return None
        cursor.execute(
            """
            SELECT * FROM analytics.fv_identity_authority_member_v2
            WHERE authority_id=%s ORDER BY member_ordinal
            """,
            (header["authority_id"],),
        )
        rows = cursor.fetchall()
        cursor.execute(
            "SELECT * FROM analytics.fv_identity_authority_seal_v2 "
            "WHERE authority_id=%s",
            (header["authority_id"],),
        )
        seal = cursor.fetchone()
        if seal is None or len(rows) != header["member_count"]:
            raise IdentityProjectionV2PersistenceConflict(
                "PROJECTION_V2_DURABLE_GRAPH_INCOMPLETE"
            )
        members = tuple(
            ProjectedIdentityMemberV2(
                ordinal=row["member_ordinal"],
                ticker=row["ticker"],
                security_id=str(row["security_id"]),
                company_id=str(row["company_id"]),
                instrument_id=str(row["instrument_id"]),
                share_class_id=str(row["share_class_id"]),
                listing_id=str(row["listing_id"]),
                ticker_assignment_id=str(row["ticker_assignment_id"]),
                adoption_state=row["adoption_state"],
                existing_public_id=(
                    None
                    if row["existing_public_id"] is None
                    else str(row["existing_public_id"])
                ),
                company_name=row["company_name"],
                sec_cik=row["sec_cik"],
                mic=row["mic"],
                currency=row["currency"],
                instrument_type=row["instrument_type"],
                ticker_valid_from=row["ticker_valid_from"].isoformat(),
                isin=row["isin"],
                cusip=row["cusip"],
                figi=row["figi"],
                composite_figi=row["composite_figi"],
                share_class_figi=row["share_class_figi"],
                openfigi_provider_identity_hash=(
                    row["openfigi_provider_identity_hash"]
                ),
                openfigi_source_hash=row["openfigi_source_hash"],
                sec_source_hash=row["sec_source_hash"],
                inventory_decision_hash=row["inventory_decision_hash"],
                content_hash=row["member_content_hash"],
            )
            for row in rows
        )
        result = IdentityProjectionV2(
            contract_version=header["contract_version"],
            authority_version=header["authority_version"],
            registry_version=header["registry_version"],
            inventory_as_of_date=header["inventory_as_of_date"].isoformat(),
            evidence_claim=header["evidence_claim"],
            model_evidence_label=header["model_evidence_label"],
            openfigi_result_hash=header["openfigi_result_hash"],
            openfigi_review_hash=header["openfigi_review_hash"],
            sec_result_hash=header["sec_result_hash"],
            sec_acceptance_hash=header["sec_acceptance_hash"],
            sec_review_hash=header["sec_review_hash"],
            inventory_authorization_hash=header["inventory_authorization_hash"],
            inventory_review_hash=header["inventory_review_hash"],
            inventory_receipt_hash=header["inventory_receipt_hash"],
            members=members,
            member_set_hash=header["member_set_hash"],
            v22_write_authorized=header["v22_write_authorized"],
            v24_enrollment_authorized=header["v24_enrollment_authorized"],
            investment_assessment_authorized=(
                header["investment_assessment_authorized"]
            ),
            evidence_label_upgrade_authorized=(
                header["evidence_label_upgrade_authorized"]
            ),
            content_hash=header["projection_content_hash"],
        )
        validate_identity_projection_v2(result)
        if (
            seal["projection_content_hash"] != result.content_hash
            or seal["member_set_hash"] != result.member_set_hash
            or seal["member_count"] != len(result.members)
            or seal["seal_content_hash"]
            != PostgresIdentityAuthorityV2Repository._seal_hash(result)
        ):
            raise IdentityProjectionV2PersistenceConflict(
                "PROJECTION_V2_DURABLE_SEAL_DRIFT"
            )
        return result

    def persist(self, value: IdentityProjectionV2) -> IdentityProjectionV2:
        """Persist or exactly replay one governed V25/V22 identity graph."""

        validate_identity_projection_v2(value)
        try:
            with psycopg.connect(self._database_url, row_factory=dict_row) as connection:
                with connection.transaction():
                    with connection.cursor() as cursor:
                        cursor.execute(
                            "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                            (value.content_hash,),
                        )
                        existing = self._load(cursor, value.content_hash)
                        if existing is not None:
                            if existing != value:
                                raise IdentityProjectionV2PersistenceConflict(
                                    "PROJECTION_V2_DURABLE_REPLAY_CONFLICT"
                                )
                            return existing
                        authority_id = self._authority_id(value)
                        self._insert_header(cursor, value)
                        for member in value.members:
                            self._insert_member(cursor, authority_id, member)
                            self._insert_or_validate_security(cursor, member)
                            self._insert_v22_graph(cursor, member)
                        cursor.execute(
                            """
                            INSERT INTO analytics.fv_identity_authority_seal_v2 (
                                authority_id,projection_content_hash,member_set_hash,
                                member_count,seal_content_hash
                            ) VALUES (%s,%s,%s,%s,%s)
                            """,
                            (
                                authority_id,
                                value.content_hash,
                                value.member_set_hash,
                                len(value.members),
                                self._seal_hash(value),
                            ),
                        )
                with connection.cursor() as cursor:
                    stored = self._load(cursor, value.content_hash)
                    if stored is None or stored != value:
                        raise IdentityProjectionV2PersistenceConflict(
                            "PROJECTION_V2_DURABLE_READBACK_DRIFT"
                        )
                    return stored
        except IdentityProjectionV2PersistenceConflict:
            raise
        except (psycopg.Error, KeyError, TypeError, ValueError) as error:
            raise IdentityProjectionV2PersistenceConflict(
                "PROJECTION_V2_DATABASE_INTEGRITY_CONFLICT"
            ) from error

    def load(self, projection_content_hash: str) -> IdentityProjectionV2:
        if _LOWER_HASH.fullmatch(projection_content_hash) is None:
            raise IdentityProjectionV2PersistenceConflict(
                "PROJECTION_V2_CONTENT_HASH_INVALID"
            )
        try:
            with psycopg.connect(self._database_url, row_factory=dict_row) as connection:
                with connection.cursor() as cursor:
                    result = self._load(cursor, projection_content_hash)
                    if result is None:
                        raise LookupError(projection_content_hash)
                    return result
        except (IdentityProjectionV2PersistenceConflict, LookupError):
            raise
        except (psycopg.Error, KeyError, TypeError, ValueError) as error:
            raise IdentityProjectionV2PersistenceConflict(
                "PROJECTION_V2_DATABASE_INTEGRITY_CONFLICT"
            ) from error


__all__ = [
    "CONTRACT_VERSION",
    "IDENTITY_AUTHORITY_VERSION",
    "IdentityProjectionV2",
    "IdentityProjectionV2Stop",
    "IdentityProjectionV2PersistenceConflict",
    "PostgresIdentityAuthorityV2Repository",
    "ProjectedIdentityMemberV2",
    "load_accepted_identity_projection_v2",
    "projection_v2_to_wire",
    "validate_identity_projection_v2",
]
