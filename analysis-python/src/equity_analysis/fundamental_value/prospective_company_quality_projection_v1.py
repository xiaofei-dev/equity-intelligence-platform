# ruff: noqa: E501
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Mapping
from contextlib import nullcontext
from dataclasses import asdict, dataclass, replace
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol, runtime_checkable
from uuid import NAMESPACE_URL, UUID, uuid5

import psycopg
from psycopg.rows import dict_row

from equity_analysis.dual_system_contract import DataState
from equity_analysis.evidence_foundation import persistence_v1 as v22_persistence
from equity_analysis.evidence_foundation.contracts_v1 import (
    CONTRACT_VERSION as V22_CONTRACT_VERSION,
)
from equity_analysis.evidence_foundation.contracts_v1 import (
    EvidenceCandidate,
    EvidenceSelectionRequest,
)
from equity_analysis.evidence_foundation.domain_contracts_v1 import EvidenceDomain
from equity_analysis.evidence_foundation.persistence_v1 import (
    EvidenceFoundationRepository,
    PersistedEvidenceEnvelope,
    PersistedSelectorAggregate,
)
from equity_analysis.evidence_foundation.selector_v1 import EvidenceSelectionResult
from equity_analysis.fundamental_value import (
    prospective_company_quality_acquisition_v1 as acquisition_v1,
)
from equity_analysis.fundamental_value.prospective_company_quality_v1 import (
    ARITHMETIC_VERSION,
    C5_POPULATION_HASH,
    C5_PREDICTOR_CONTRACT_HASH,
    COST_POLICY_VERSION,
    OUTCOME_POLICY_VERSION,
    PARENT_EVIDENCE_COUNT,
    PARENT_ROLE_CONTRACT,
    PRODUCER_VERSION,
    STAGE7_ACCEPTANCE_HASH,
    DecisionSession,
    Enrollment,
    EvidenceBinding,
    Member,
    PlannedEntry,
    TerminalState,
    canonical_decimal_text,
    company_quality_score_from_parents,
    evidence_aggregate_hashes,
    producer_output_hash,
    seal_enrollment,
    seal_member,
    validate_enrollment,
)

CONTRACT_VERSION = "FV-CQ-FORWARD-PROJECTION-v1.0.0"
IDENTITY_REGISTRY_VERSION = "security-identity-registry-v1.0.0"
IDENTITY_NAMESPACE = UUID("96ad4a2e-f76f-5d0c-88d5-cf406c7ca6de")
EXPECTED_MEMBER_COUNT = 191
EXPECTED_MIC_DISTRIBUTION = {"XNYS": 122, "XNAS": 69}
EXPECTED_SESSION_COUNT = 2
EXPECTED_PLANNED_ENTRY_COUNT = 2
MINIMUM_USABLE_COUNT = 100
V22_PERSISTENCE_ROLE = "analytics_writer"
V24_NORMALIZED_PARENT_PERSISTENCE_ROLE = (
    "analytics_fv_cq_normalized_parent_writer_v1"
)
ACCEPTED_NEXT_SESSION_CALENDAR_REGISTRY_CONTENT_HASH: str | None = None
V22_PARENT_COUNT = sum(
    count
    for _, _, provenance, count in PARENT_ROLE_CONTRACT
    if provenance == "V22_SELECTED_EVIDENCE"
)
V24_NORMALIZED_PARENT_COUNT = PARENT_EVIDENCE_COUNT - V22_PARENT_COUNT
OPENFIGI_PRIMARY_FILTER_VERSION = "openfigi-primary-listing-filter-v1.1.0"
OPENFIGI_TICKER_ALIAS_POLICY_VERSION = (
    acquisition_v1.OPENFIGI_TICKER_ALIAS_POLICY_VERSION
)
OPENFIGI_WIRE_CONTRACT_VERSION = "openfigi-mapping-v3-wire-v1.1.0"
OPENFIGI_REQUEST_CURRENCY = "USD"
OPENFIGI_REQUEST_MARKET_SEC_DES = "Equity"
OPENFIGI_INCLUDE_UNLISTED_EQUITIES = False
OPENFIGI_ID_TYPE = {
    "ISIN_LOOKUP": "ID_ISIN",
    "CUSIP_LOOKUP": "ID_CUSIP",
}
SEC_EXCHANGE_TO_MIC = {"NYSE": "XNYS", "Nasdaq": "XNAS"}
MIC_TO_SECURITY_EXCHANGE = {"XNYS": "NYSE", "XNAS": "NASDAQ"}

_SHA256 = re.compile(r"sha256:[0-9a-f]{64}\Z")
_TICKER = re.compile(r"[A-Z0-9][A-Z0-9.-]{0,31}\Z")
_OPENFIGI_PROVIDER_TICKER = re.compile(
    r"(?=.{1,32}\Z)(?:[A-Z0-9][A-Z0-9.-]*|[A-Z0-9]+/[A-Z0-9]+)\Z"
)
_MIC = re.compile(r"[A-Z0-9]{4}\Z")
_CUSIP = re.compile(r"[A-Z0-9*#@]{9}\Z")
_ISIN = re.compile(r"[A-Z]{2}[A-Z0-9]{9}[0-9]\Z")
_CIK = re.compile(r"[0-9]{10}\Z")
_FIGI = re.compile(r"BBG[A-Z0-9]{9}\Z")
_ASCII_BLANK = " \t\n\r\f\v"


class ProjectionContractViolation(ValueError):
    """Raised when a Stage 8C projection is not canonical or complete."""


class ProjectionIntegrityConflict(RuntimeError):
    """Raised when durable state is not an exact replay of projected content."""


class IdentityResolutionState(StrEnum):
    ACCEPTED = "ACCEPTED"
    TERMINAL_CONFLICT = "TERMINAL_CONFLICT"


class OpenFigiIdentifierJobKind(StrEnum):
    ISIN_LOOKUP = "ISIN_LOOKUP"
    CUSIP_LOOKUP = "CUSIP_LOOKUP"


class OpenFigiResponseKind(StrEnum):
    DATA = "DATA"
    ERROR = "ERROR"
    WARNING = "WARNING"


class ProjectionAuthorityKind(StrEnum):
    OPENFIGI = "OPENFIGI"
    SEC = "SEC"
    PROVIDER_FINANCIALS = "PROVIDER_FINANCIALS"
    COMPLETED_SESSION = "COMPLETED_SESSION"


class ProjectionPersistenceState(StrEnum):
    EXACT_REPLAY = "EXACT_REPLAY"
    INSERTED_AND_VERIFIED = "INSERTED_AND_VERIFIED"
    MISSING = "MISSING"


@dataclass(frozen=True)
class AcquisitionReceiptBinding:
    authority_kind: ProjectionAuthorityKind
    plan_content_hash: str
    request_identity_hash: str
    request_content_hash: str
    checkpoint_content_hash: str
    physical_receipt_content_hash: str
    response_headers_content_hash: str
    semantic_content_hash: str
    response_content_hash: str
    completed_at: datetime
    recorded_at: datetime
    transport_state: str
    acquisition_scope_content_hash: str
    logical_ordinal: int
    logical_key: str
    acquisition_logical_request_hash: str
    raw_payload_content_hash: str
    raw_record_content_hash: str
    normalized_record_content_hash: str
    logical_receipt_content_hash: str
    content_hash: str


def seal_acquisition_receipt(value: AcquisitionReceiptBinding) -> AcquisitionReceiptBinding:
    if type(value.authority_kind) is not ProjectionAuthorityKind:
        raise ProjectionContractViolation("Receipt authority kind must be exact")
    for name, digest in (
        ("receipt plan hash", value.plan_content_hash),
        ("receipt request identity", value.request_identity_hash),
        ("receipt request hash", value.request_content_hash),
        ("receipt checkpoint hash", value.checkpoint_content_hash),
        ("receipt physical semantic-receipt hash", value.physical_receipt_content_hash),
        ("receipt response-headers hash", value.response_headers_content_hash),
        ("receipt semantic-content hash", value.semantic_content_hash),
        ("receipt response hash", value.response_content_hash),
        ("receipt acquisition-scope hash", value.acquisition_scope_content_hash),
        ("receipt acquisition logical-request hash", value.acquisition_logical_request_hash),
        ("receipt raw-payload hash", value.raw_payload_content_hash),
        ("receipt raw-record hash", value.raw_record_content_hash),
        ("receipt normalized-record hash", value.normalized_record_content_hash),
        ("receipt logical-record receipt hash", value.logical_receipt_content_hash),
    ):
        _sha256(digest, name)
    _positive_int(value.logical_ordinal, "receipt logical ordinal")
    if (
        type(value.logical_key) is not str
        or not value.logical_key.strip(_ASCII_BLANK)
        or len(value.logical_key) > 512
        or "\x00" in value.logical_key
    ):
        raise ProjectionContractViolation("Receipt logical key is invalid")
    completed = _instant(value.completed_at, "receipt completedAt")
    recorded = _instant(value.recorded_at, "receipt recordedAt")
    if value.transport_state != "COMPLETED" or completed > recorded:
        raise ProjectionContractViolation("Receipt is not an exact completed transport")
    payload = {**asdict(value), "content_hash": ""}
    return replace(value, content_hash=_canonical_hash(payload))


def _canonical_hash(payload: object) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=_json_default,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _canonical_json_text(payload: object) -> str:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=_json_default,
    )


def _json_default(value: object) -> object:
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return _instant_text(value, "canonical timestamp")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return canonical_decimal_text(value)
    if isinstance(value, StrEnum):
        return value.value
    raise TypeError(f"Unsupported canonical JSON value {type(value).__name__}")


def _sha256(value: str, name: str) -> None:
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        raise ProjectionContractViolation(f"{name} must be an exact lowercase SHA-256")


def _acquisition_hash(value: object, name: str) -> str:
    if type(value) is not str or re.fullmatch(r"[0-9A-F]{64}", value) is None:
        raise ProjectionIntegrityConflict(f"{name} is not an exact acquisition SHA-256")
    return f"sha256:{value.lower()}"


def _acquisition_recorded_at(value: object) -> datetime:
    if type(value) is not str or not value.endswith("Z"):
        raise ProjectionIntegrityConflict("Acquisition recordedAt is not canonical UTC")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as error:
        raise ProjectionIntegrityConflict(
            "Acquisition recordedAt is not canonical UTC"
        ) from error
    normalized = _instant(parsed, "acquisition recordedAt")
    if _instant_text(normalized, "acquisition recordedAt") != value:
        raise ProjectionIntegrityConflict("Acquisition recordedAt is not canonical UTC")
    return normalized


def _acquisition_scope_content_hash(plan: acquisition_v1.AcquisitionPlan) -> str:
    return _canonical_hash(
        {
            "contractVersion": CONTRACT_VERSION,
            "acquisitionContractVersion": acquisition_v1.CONTRACT_VERSION,
            "planContentHash": plan.content_hash,
            "populationMetadataManifestContentHash": (
                plan.population_metadata_manifest_content_hash
            ),
            "populationInputManifestContentHash": (
                plan.population_input_manifest_content_hash
            ),
        }
    )


def _atom(value: str, name: str, *, maximum: int = 255) -> None:
    if (
        type(value) is not str
        or not value.strip(_ASCII_BLANK)
        or len(value) > maximum
        or "\x00" in value
        or "\x1f" in value
        or ":" in value
        or "|" in value
    ):
        raise ProjectionContractViolation(f"{name} is not a canonical bounded atom")


def _uuid(value: UUID, name: str) -> None:
    if type(value) is not UUID:
        raise ProjectionContractViolation(f"{name} must be an exact UUID")


def _storage_reference(value: str, name: str) -> None:
    if (
        type(value) is not str
        or not value.strip(_ASCII_BLANK)
        or len(value) > 2048
        or "\x00" in value
    ):
        raise ProjectionContractViolation(f"{name} is not a canonical private reference")


def _positive_int(value: int, name: str) -> None:
    if type(value) is not int or not 1 <= value <= 2_147_483_647:
        raise ProjectionContractViolation(f"{name} must be a positive signed int32")


def _instant(value: datetime, name: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ProjectionContractViolation(f"{name} must be timezone-aware")
    normalized = value.astimezone(UTC)
    if normalized.microsecond:
        raise ProjectionContractViolation(f"{name} must use whole-second precision")
    return normalized


def _instant_text(value: datetime, name: str) -> str:
    return _instant(value, name).isoformat().replace("+00:00", "Z")


def _exact_tuple(value: object, name: str) -> tuple[Any, ...]:
    if type(value) is not tuple:
        raise ProjectionContractViolation(f"{name} must be an exact tuple")
    return value


def _identity_uuid(rule: str, *parts: str) -> UUID:
    for ordinal, part in enumerate(parts, start=1):
        _atom(part, f"{rule} UUID5 atom {ordinal}")
    return uuid5(
        IDENTITY_NAMESPACE,
        "\x1f".join((CONTRACT_VERSION, rule, *parts)),
    )


@dataclass(frozen=True)
class OpenFigiRawCandidate:
    result_ordinal: int
    listing_figi: str
    composite_figi: str
    share_class_figi: str
    ticker: str
    exch_code: str
    market_sector: str
    security_type: str
    wire_json: str
    wire_content_hash: str
    content_hash: str

    @classmethod
    def create(
        cls,
        *,
        result_ordinal: int,
        listing_figi: str,
        composite_figi: str,
        share_class_figi: str,
        ticker: str,
        exch_code: str,
        market_sector: str,
        security_type: str,
        wire_payload: Mapping[str, object] | None = None,
    ) -> OpenFigiRawCandidate:
        selected_payload = {
            "resultOrdinal": result_ordinal,
            "figi": listing_figi,
            "compositeFIGI": composite_figi,
            "shareClassFIGI": share_class_figi,
            "ticker": ticker,
            "exchCode": exch_code,
            "marketSector": market_sector,
            "securityType": security_type,
        }
        actual_wire_payload = (
            {
                "figi": listing_figi,
                "compositeFIGI": composite_figi,
                "shareClassFIGI": share_class_figi,
                "ticker": ticker,
                "exchCode": exch_code,
                "marketSector": market_sector,
                "securityType": security_type,
            }
            if wire_payload is None
            else dict(wire_payload)
        )
        wire_json = _canonical_json_text(actual_wire_payload)
        wire_content_hash = _canonical_hash(actual_wire_payload)
        payload = {
            **selected_payload,
            "wireContentHash": wire_content_hash,
        }
        return cls(
            result_ordinal=result_ordinal,
            listing_figi=listing_figi,
            composite_figi=composite_figi,
            share_class_figi=share_class_figi,
            ticker=ticker,
            exch_code=exch_code,
            market_sector=market_sector,
            security_type=security_type,
            wire_json=wire_json,
            wire_content_hash=wire_content_hash,
            content_hash=_canonical_hash(payload),
        )

    def __post_init__(self) -> None:
        _positive_int(self.result_ordinal, "OpenFIGI result ordinal")
        if any(
            _FIGI.fullmatch(value) is None
            for value in (self.listing_figi, self.composite_figi, self.share_class_figi)
        ):
            raise ProjectionContractViolation("OpenFIGI result identifiers are invalid")
        if _OPENFIGI_PROVIDER_TICKER.fullmatch(self.ticker) is None:
            raise ProjectionContractViolation("OpenFIGI result ticker is invalid")
        for name, value in (
            ("exchCode", self.exch_code),
            ("market sector", self.market_sector),
            ("security type", self.security_type),
        ):
            _atom(value, f"OpenFIGI result {name}", maximum=64)
        if type(self.wire_json) is not str:
            raise ProjectionContractViolation("OpenFIGI wire candidate must be canonical JSON")
        try:
            wire = json.loads(self.wire_json)
        except (TypeError, ValueError) as exc:
            raise ProjectionContractViolation("OpenFIGI wire candidate JSON is invalid") from exc
        if type(wire) is not dict or self.wire_json != _canonical_json_text(wire):
            raise ProjectionContractViolation("OpenFIGI wire candidate JSON is not canonical")
        expected_wire_fields = {
            "figi": self.listing_figi,
            "compositeFIGI": self.composite_figi,
            "shareClassFIGI": self.share_class_figi,
            "ticker": self.ticker,
            "exchCode": self.exch_code,
            "marketSector": self.market_sector,
            "securityType": self.security_type,
        }
        if any(wire.get(key) != value for key, value in expected_wire_fields.items()):
            raise ProjectionContractViolation("OpenFIGI selected fields drift from wire JSON")
        _sha256(self.wire_content_hash, "OpenFIGI wire candidate hash")
        if self.wire_content_hash != _canonical_hash(wire):
            raise ProjectionContractViolation("OpenFIGI wire candidate hash drift")
        _sha256(self.content_hash, "OpenFIGI result content hash")
        if self.content_hash != _canonical_hash(
            {
                "resultOrdinal": self.result_ordinal,
                "figi": self.listing_figi,
                "compositeFIGI": self.composite_figi,
                "shareClassFIGI": self.share_class_figi,
                "ticker": self.ticker,
                "exchCode": self.exch_code,
                "marketSector": self.market_sector,
                "securityType": self.security_type,
                "wireContentHash": self.wire_content_hash,
            }
        ):
            raise ProjectionContractViolation("OpenFIGI result content hash drift")


@dataclass(frozen=True)
class OpenFigiIdentifierJob:
    job_kind: OpenFigiIdentifierJobKind
    requested_identifier: str
    expected_ticker: str
    expected_mic: str
    request_id_type: str
    request_mic_code: str
    request_currency: str
    request_market_sec_des: str
    request_include_unlisted_equities: bool
    wire_contract_version: str
    primary_filter_version: str
    ticker_alias_policy_version: str
    response_kind: OpenFigiResponseKind
    candidates: tuple[OpenFigiRawCandidate, ...]
    error: str | None
    warning: str | None
    raw_result_count: int
    request_content_hash: str
    response_content_hash: str
    source_record_id: str
    source_revision: int
    available_at: datetime
    ingested_at: datetime
    source_content_hash: str
    acquisition_receipt: AcquisitionReceiptBinding

    @classmethod
    def create(
        cls,
        *,
        job_kind: OpenFigiIdentifierJobKind,
        requested_identifier: str,
        expected_ticker: str,
        expected_mic: str,
        candidates: tuple[OpenFigiRawCandidate, ...],
        error: str | None = None,
        warning: str | None = None,
        source_record_id: str,
        source_revision: int,
        available_at: datetime,
        ingested_at: datetime,
        source_content_hash: str,
        acquisition_receipt: AcquisitionReceiptBinding,
    ) -> OpenFigiIdentifierJob:
        request_hash = openfigi_wire_request_content_hash(
            job_kind=job_kind,
            requested_identifier=requested_identifier,
            expected_ticker=expected_ticker,
            expected_mic=expected_mic,
        )
        response_kind = (
            OpenFigiResponseKind.DATA
            if candidates and error is None and warning is None
            else OpenFigiResponseKind.ERROR
            if not candidates and error is not None and warning is None
            else OpenFigiResponseKind.WARNING
            if not candidates and error is None and warning is not None
            else None
        )
        if response_kind is None:
            raise ProjectionContractViolation(
                "OpenFIGI job must contain exactly one of data, error, or warning"
            )
        wire_response: dict[str, object]
        if response_kind is OpenFigiResponseKind.DATA:
            wire_response = {
                "data": [json.loads(item.wire_json) for item in candidates]
            }
        elif response_kind is OpenFigiResponseKind.ERROR:
            wire_response = {"error": error}
        else:
            wire_response = {"warning": warning}
        wire_response_hash = _canonical_hash(wire_response)
        if (
            source_content_hash != wire_response_hash
            or acquisition_receipt.response_content_hash != wire_response_hash
        ):
            raise ProjectionContractViolation(
                "OpenFIGI source lineage does not bind the full wire response"
            )
        response_hash = _canonical_hash(
            {
                "contractVersion": CONTRACT_VERSION,
                "requestContentHash": request_hash,
                "responseKind": response_kind,
                "candidates": tuple(asdict(item) for item in candidates),
                "error": error,
                "warning": warning,
                "rawResultCount": len(candidates),
                "sourceRecordId": source_record_id,
                "sourceRevision": source_revision,
                "availableAt": available_at,
                "ingestedAt": ingested_at,
                "sourceContentHash": source_content_hash,
                "acquisitionReceiptHash": acquisition_receipt.content_hash,
            }
        )
        return cls(
            job_kind=job_kind,
            requested_identifier=requested_identifier,
            expected_ticker=expected_ticker,
            expected_mic=expected_mic,
            request_id_type=OPENFIGI_ID_TYPE[job_kind.value],
            request_mic_code=expected_mic,
            request_currency=OPENFIGI_REQUEST_CURRENCY,
            request_market_sec_des=OPENFIGI_REQUEST_MARKET_SEC_DES,
            request_include_unlisted_equities=OPENFIGI_INCLUDE_UNLISTED_EQUITIES,
            wire_contract_version=OPENFIGI_WIRE_CONTRACT_VERSION,
            primary_filter_version=OPENFIGI_PRIMARY_FILTER_VERSION,
            ticker_alias_policy_version=OPENFIGI_TICKER_ALIAS_POLICY_VERSION,
            response_kind=response_kind,
            candidates=candidates,
            error=error,
            warning=warning,
            raw_result_count=len(candidates),
            request_content_hash=request_hash,
            response_content_hash=response_hash,
            source_record_id=source_record_id,
            source_revision=source_revision,
            available_at=available_at,
            ingested_at=ingested_at,
            source_content_hash=source_content_hash,
            acquisition_receipt=acquisition_receipt,
        )

    def __post_init__(self) -> None:
        if type(self.job_kind) is not OpenFigiIdentifierJobKind:
            raise ProjectionContractViolation("OpenFIGI job kind must be exact")
        if self.job_kind is OpenFigiIdentifierJobKind.ISIN_LOOKUP:
            if _ISIN.fullmatch(self.requested_identifier) is None:
                raise ProjectionContractViolation("OpenFIGI ISIN request is invalid")
        elif _CUSIP.fullmatch(self.requested_identifier) is None:
            raise ProjectionContractViolation("OpenFIGI CUSIP request is invalid")
        if (
            _TICKER.fullmatch(self.expected_ticker) is None
            or _MIC.fullmatch(self.expected_mic) is None
        ):
            raise ProjectionContractViolation("OpenFIGI expected ticker/MIC is invalid")
        if (
            self.request_id_type != OPENFIGI_ID_TYPE[self.job_kind.value]
            or self.request_mic_code != self.expected_mic
            or self.request_currency != OPENFIGI_REQUEST_CURRENCY
            or self.request_market_sec_des != OPENFIGI_REQUEST_MARKET_SEC_DES
            or self.request_include_unlisted_equities
            is not OPENFIGI_INCLUDE_UNLISTED_EQUITIES
            or self.wire_contract_version != OPENFIGI_WIRE_CONTRACT_VERSION
            or self.primary_filter_version != OPENFIGI_PRIMARY_FILTER_VERSION
            or self.ticker_alias_policy_version
            != OPENFIGI_TICKER_ALIAS_POLICY_VERSION
        ):
            raise ProjectionContractViolation("OpenFIGI request/filter contract is unsupported")
        if type(self.response_kind) is not OpenFigiResponseKind:
            raise ProjectionContractViolation("OpenFIGI response kind must be exact")
        _exact_tuple(self.candidates, "OpenFIGI candidates")
        if any(type(item) is not OpenFigiRawCandidate for item in self.candidates):
            raise ProjectionContractViolation("OpenFIGI response members are not exact")
        expected_kind = (
            OpenFigiResponseKind.DATA
            if self.candidates and self.error is None and self.warning is None
            else OpenFigiResponseKind.ERROR
            if not self.candidates and type(self.error) is str and self.warning is None
            else OpenFigiResponseKind.WARNING
            if not self.candidates and self.error is None and type(self.warning) is str
            else None
        )
        if expected_kind is None or expected_kind is not self.response_kind:
            raise ProjectionContractViolation(
                "OpenFIGI response must contain exactly one of data, error, or warning"
            )
        if self.error is not None:
            _atom(self.error, "OpenFIGI error", maximum=1024)
        if self.warning is not None:
            _atom(self.warning, "OpenFIGI warning", maximum=1024)
        if (
            type(self.raw_result_count) is not int
            or not 0 <= self.raw_result_count <= 2_147_483_647
        ):
            raise ProjectionContractViolation("OpenFIGI raw result count is invalid")
        ordinals = [item.result_ordinal for item in self.candidates]
        if self.raw_result_count != len(self.candidates) or sorted(ordinals) != list(
            range(1, self.raw_result_count + 1)
        ):
            raise ProjectionContractViolation("OpenFIGI raw response cardinality is not exact")
        _sha256(self.request_content_hash, "OpenFIGI request hash")
        _sha256(self.response_content_hash, "OpenFIGI response hash")
        _atom(self.source_record_id, "OpenFIGI source record")
        _positive_int(self.source_revision, "OpenFIGI source revision")
        if _instant(self.available_at, "OpenFIGI availableAt") > _instant(
            self.ingested_at, "OpenFIGI ingestedAt"
        ):
            raise ProjectionContractViolation("OpenFIGI chronology is invalid")
        _sha256(self.source_content_hash, "OpenFIGI source hash")
        if seal_acquisition_receipt(self.acquisition_receipt) != self.acquisition_receipt:
            raise ProjectionContractViolation("OpenFIGI acquisition receipt is not sealed")
        if (
            self.acquisition_receipt.authority_kind is not ProjectionAuthorityKind.OPENFIGI
            or self.acquisition_receipt.request_content_hash != self.request_content_hash
            or self.acquisition_receipt.response_content_hash != self.source_content_hash
            or _instant(self.acquisition_receipt.completed_at, "OpenFIGI receipt completedAt")
            > _instant(self.available_at, "OpenFIGI availableAt")
            or _instant(self.acquisition_receipt.recorded_at, "OpenFIGI receipt recordedAt")
            > _instant(self.ingested_at, "OpenFIGI ingestedAt")
        ):
            raise ProjectionContractViolation("OpenFIGI acquisition receipt binding drift")
        if self.request_content_hash != openfigi_request_content_hash(self):
            raise ProjectionContractViolation("OpenFIGI request hash drift")
        if self.response_content_hash != openfigi_response_content_hash(self):
            raise ProjectionContractViolation("OpenFIGI response hash drift")
        if self.source_content_hash != openfigi_wire_response_content_hash(self):
            raise ProjectionContractViolation("OpenFIGI full wire response hash drift")


def openfigi_wire_request_content_hash(
    *,
    job_kind: OpenFigiIdentifierJobKind,
    requested_identifier: str,
    expected_ticker: str,
    expected_mic: str,
) -> str:
    return _canonical_hash(
        {
            "contractVersion": CONTRACT_VERSION,
            "wireContractVersion": OPENFIGI_WIRE_CONTRACT_VERSION,
            "jobKind": job_kind,
            "idType": OPENFIGI_ID_TYPE[job_kind.value],
            "idValue": requested_identifier,
            "micCode": expected_mic,
            "currency": OPENFIGI_REQUEST_CURRENCY,
            "marketSecDes": OPENFIGI_REQUEST_MARKET_SEC_DES,
            "includeUnlistedEquities": OPENFIGI_INCLUDE_UNLISTED_EQUITIES,
            "expectedTicker": expected_ticker,
            "primaryFilterVersion": OPENFIGI_PRIMARY_FILTER_VERSION,
            "tickerAliasPolicyVersion": OPENFIGI_TICKER_ALIAS_POLICY_VERSION,
        }
    )


def openfigi_request_content_hash(job: OpenFigiIdentifierJob) -> str:
    return openfigi_wire_request_content_hash(
        job_kind=job.job_kind,
        requested_identifier=job.requested_identifier,
        expected_ticker=job.expected_ticker,
        expected_mic=job.expected_mic,
    )


def openfigi_response_content_hash(job: OpenFigiIdentifierJob) -> str:
    return _canonical_hash(
        {
            "contractVersion": CONTRACT_VERSION,
            "requestContentHash": job.request_content_hash,
            "responseKind": job.response_kind,
            "candidates": tuple(asdict(item) for item in job.candidates),
            "error": job.error,
            "warning": job.warning,
            "rawResultCount": job.raw_result_count,
            "sourceRecordId": job.source_record_id,
            "sourceRevision": job.source_revision,
            "availableAt": job.available_at,
            "ingestedAt": job.ingested_at,
            "sourceContentHash": job.source_content_hash,
            "acquisitionReceiptHash": job.acquisition_receipt.content_hash,
        }
    )


def openfigi_wire_response_content_hash(job: OpenFigiIdentifierJob) -> str:
    if job.response_kind is OpenFigiResponseKind.DATA:
        payload: dict[str, object] = {
            "data": [json.loads(item.wire_json) for item in job.candidates]
        }
    elif job.response_kind is OpenFigiResponseKind.ERROR:
        payload = {"error": job.error}
    else:
        payload = {"warning": job.warning}
    return _canonical_hash(payload)


def decode_openfigi_v3_job_response(
    *,
    job_kind: OpenFigiIdentifierJobKind,
    requested_identifier: str,
    expected_ticker: str,
    expected_mic: str,
    wire_response: Mapping[str, object],
    source_record_id: str,
    source_revision: int,
    available_at: datetime,
    ingested_at: datetime,
    acquisition_receipt: AcquisitionReceiptBinding,
) -> OpenFigiIdentifierJob:
    if type(wire_response) is not dict:
        raise ProjectionContractViolation("OpenFIGI job response must be an exact object")
    present = [key for key in ("data", "error", "warning") if key in wire_response]
    if len(present) != 1 or set(wire_response) != {present[0]}:
        raise ProjectionContractViolation(
            "OpenFIGI wire response must contain exactly one data/error/warning member"
        )
    response_hash = _canonical_hash(wire_response)
    if acquisition_receipt.response_content_hash != response_hash:
        raise ProjectionContractViolation("OpenFIGI receipt does not bind full wire response")
    candidates: tuple[OpenFigiRawCandidate, ...] = ()
    error: str | None = None
    warning: str | None = None
    if present[0] == "data":
        data = wire_response["data"]
        if type(data) is not list or not data:
            raise ProjectionContractViolation("OpenFIGI data response must be a nonempty array")
        parsed: list[OpenFigiRawCandidate] = []
        required = (
            "figi",
            "compositeFIGI",
            "shareClassFIGI",
            "ticker",
            "exchCode",
            "marketSector",
            "securityType",
        )
        for ordinal, raw in enumerate(data, start=1):
            if type(raw) is not dict or any(type(raw.get(key)) is not str for key in required):
                raise ProjectionContractViolation("OpenFIGI candidate wire fields are incomplete")
            parsed.append(
                OpenFigiRawCandidate.create(
                    result_ordinal=ordinal,
                    listing_figi=raw["figi"],
                    composite_figi=raw["compositeFIGI"],
                    share_class_figi=raw["shareClassFIGI"],
                    ticker=raw["ticker"],
                    exch_code=raw["exchCode"],
                    market_sector=raw["marketSector"],
                    security_type=raw["securityType"],
                    wire_payload=raw,
                )
            )
        candidates = tuple(parsed)
    else:
        message = wire_response[present[0]]
        if type(message) is not str or not message.strip(_ASCII_BLANK):
            raise ProjectionContractViolation("OpenFIGI error/warning must be nonblank text")
        if present[0] == "error":
            error = message
        else:
            warning = message
    return OpenFigiIdentifierJob.create(
        job_kind=job_kind,
        requested_identifier=requested_identifier,
        expected_ticker=expected_ticker,
        expected_mic=expected_mic,
        candidates=candidates,
        error=error,
        warning=warning,
        source_record_id=source_record_id,
        source_revision=source_revision,
        available_at=available_at,
        ingested_at=ingested_at,
        source_content_hash=response_hash,
        acquisition_receipt=acquisition_receipt,
    )


@dataclass(frozen=True)
class SecIdentityLineage:
    cik: str
    ticker: str
    exchange: str
    source_record_id: str
    source_revision: int
    available_at: datetime
    ingested_at: datetime
    source_content_hash: str
    acquisition_receipt: AcquisitionReceiptBinding

    def __post_init__(self) -> None:
        if _CIK.fullmatch(self.cik) is None:
            raise ProjectionContractViolation("SEC CIK must be ten digits")
        if _TICKER.fullmatch(self.ticker) is None:
            raise ProjectionContractViolation("SEC ticker is invalid")
        if self.exchange not in {"Nasdaq", "NYSE"}:
            raise ProjectionContractViolation("SEC exchange is unsupported")
        _atom(self.source_record_id, "SEC source record")
        _positive_int(self.source_revision, "SEC source revision")
        if _instant(self.available_at, "SEC availableAt") > _instant(
            self.ingested_at, "SEC ingestedAt"
        ):
            raise ProjectionContractViolation("SEC chronology is invalid")
        _sha256(self.source_content_hash, "SEC source hash")
        if seal_acquisition_receipt(self.acquisition_receipt) != self.acquisition_receipt:
            raise ProjectionContractViolation("SEC acquisition receipt is not sealed")
        if (
            self.acquisition_receipt.authority_kind is not ProjectionAuthorityKind.SEC
            or self.acquisition_receipt.response_content_hash != self.source_content_hash
            or _instant(self.acquisition_receipt.completed_at, "SEC receipt completedAt")
            > _instant(self.available_at, "SEC availableAt")
            or _instant(self.acquisition_receipt.recorded_at, "SEC receipt recordedAt")
            > _instant(self.ingested_at, "SEC ingestedAt")
        ):
            raise ProjectionContractViolation("SEC acquisition receipt binding drift")


@dataclass(frozen=True)
class DurableIdentityTuple:
    security_id: UUID
    company_id: UUID
    instrument_id: UUID
    share_class_id: UUID
    listing_id: UUID
    ticker_assignment_id: UUID
    symbol: str
    mic: str
    currency: str
    valid_from: date
    exchange_code: str
    legal_name: str
    legacy_public_id_adopted: bool

    def __post_init__(self) -> None:
        for name in (
            "security_id",
            "company_id",
            "instrument_id",
            "share_class_id",
            "listing_id",
            "ticker_assignment_id",
        ):
            _uuid(getattr(self, name), f"identity {name}")
        if _TICKER.fullmatch(self.symbol) is None or _MIC.fullmatch(self.mic) is None:
            raise ProjectionContractViolation("Durable identity symbol or MIC is invalid")
        if self.currency != "USD" or type(self.valid_from) is not date:
            raise ProjectionContractViolation("Durable identity listing terms are invalid")
        _atom(self.exchange_code, "security exchange", maximum=32)
        _atom(self.legal_name, "security legal name")
        if type(self.legacy_public_id_adopted) is not bool:
            raise ProjectionContractViolation("legacy adoption must be an exact boolean")


@dataclass(frozen=True)
class IdentityManifestRow:
    member_ordinal: int
    symbol: str
    mic: str
    currency: str
    valid_from: date
    exchange_code: str
    legal_name: str
    openfigi_isin_job: OpenFigiIdentifierJob
    openfigi_cusip_job: OpenFigiIdentifierJob
    sec: SecIdentityLineage
    resolution_state: IdentityResolutionState
    resolution_code: str
    resolution_authority_content_hash: str
    resolved_at: datetime
    reasons: tuple[str, ...]
    identity: DurableIdentityTuple | None
    row_content_hash: str
    legacy_security_id: UUID | None = None


def identity_resolution_content_hash(row: IdentityManifestRow) -> str:
    return _canonical_hash(
        {
            "contractVersion": CONTRACT_VERSION,
            "symbol": row.symbol,
            "mic": row.mic,
            "openFigiIsinJob": asdict(row.openfigi_isin_job),
            "openFigiCusipJob": asdict(row.openfigi_cusip_job),
            "sec": asdict(row.sec),
            "resolutionState": row.resolution_state,
            "resolutionCode": row.resolution_code,
            "resolvedAt": row.resolved_at,
            "reasons": row.reasons,
        }
    )


def _canonical_openfigi_ticker(
    provider_ticker: object,
    expected_ticker: object,
) -> str | None:
    return acquisition_v1.canonical_openfigi_ticker_for_expected_v1(
        provider_ticker,
        expected_ticker,
    )


def _openfigi_result_identity(
    candidate: OpenFigiRawCandidate,
) -> tuple[str, str, str, str, str]:
    return (
        candidate.listing_figi,
        candidate.composite_figi,
        candidate.share_class_figi,
        candidate.ticker,
        candidate.exch_code,
    )


def _openfigi_primary_matches(
    job: OpenFigiIdentifierJob,
) -> tuple[OpenFigiRawCandidate, ...]:
    if job.response_kind is not OpenFigiResponseKind.DATA:
        return ()
    return tuple(
        candidate
        for candidate in job.candidates
        if _canonical_openfigi_ticker(candidate.ticker, job.expected_ticker)
        == job.expected_ticker
        and candidate.market_sector == "Equity"
        and candidate.security_type == "Common Stock"
    )


def _openfigi_selected(job: OpenFigiIdentifierJob) -> OpenFigiRawCandidate | None:
    matches = _openfigi_primary_matches(job)
    return matches[0] if len(matches) == 1 else None


def _openfigi_jobs_concordant(row: IdentityManifestRow) -> bool:
    isin = _openfigi_selected(row.openfigi_isin_job)
    cusip = _openfigi_selected(row.openfigi_cusip_job)
    return (
        isin is not None
        and cusip is not None
        and _openfigi_result_identity(isin) == _openfigi_result_identity(cusip)
    )


def _sec_mic(sec: SecIdentityLineage) -> str:
    return SEC_EXCHANGE_TO_MIC[sec.exchange]


def _sec_corroborates_openfigi(row: IdentityManifestRow) -> bool:
    selected = tuple(
        _openfigi_selected(job) for job in (row.openfigi_isin_job, row.openfigi_cusip_job)
    )
    return (
        all(candidate is not None for candidate in selected)
        and all(
            job.expected_ticker == row.symbol and job.expected_mic == row.mic
            for job in (row.openfigi_isin_job, row.openfigi_cusip_job)
        )
        and all(
            _canonical_openfigi_ticker(candidate.ticker, row.symbol) == row.symbol
            for candidate in selected
            if candidate
        )
        and row.sec.ticker == row.symbol
        and _sec_mic(row.sec) == row.mic
    )


def derive_accepted_identity(row: IdentityManifestRow) -> DurableIdentityTuple:
    if row.resolution_state is not IdentityResolutionState.ACCEPTED:
        raise ProjectionContractViolation(
            "UUID5 identity derivation requires accepted OpenFIGI/SEC resolution"
        )
    if not _openfigi_jobs_concordant(row):
        raise ProjectionContractViolation(
            "Independent OpenFIGI identifier jobs must return one exact identity"
        )
    if not _sec_corroborates_openfigi(row):
        raise ProjectionContractViolation(
            "SEC ticker/exchange must corroborate both OpenFIGI job results"
        )
    _sha256(
        row.resolution_authority_content_hash,
        "identity resolution authority hash",
    )
    if row.resolution_authority_content_hash != identity_resolution_content_hash(row):
        raise ProjectionContractViolation("Identity resolution authority hash drift")
    selected = _openfigi_selected(row.openfigi_isin_job)
    if selected is None:
        raise ProjectionContractViolation("Accepted OpenFIGI ISIN match is not unique")
    company_id = _identity_uuid("company", row.sec.cik)
    instrument_id = _identity_uuid("instrument", row.sec.cik, "COMMON_STOCK")
    share_class_id = _identity_uuid("share-class", selected.share_class_figi)
    listing_id = _identity_uuid("listing", selected.listing_figi, row.mic, row.currency)
    ticker_assignment_id = _identity_uuid(
        "ticker-assignment", str(listing_id), row.symbol, row.valid_from.isoformat()
    )
    generated_security_id = _identity_uuid("security", str(listing_id))
    if row.symbol == "MSFT":
        if row.legacy_security_id is None:
            raise ProjectionContractViolation("MSFT must adopt its legacy public_id")
        _uuid(row.legacy_security_id, "MSFT legacy public_id")
        security_id = row.legacy_security_id
        legacy_adopted = True
    else:
        if row.legacy_security_id is not None:
            raise ProjectionContractViolation("Only MSFT may adopt the frozen legacy public_id")
        security_id = generated_security_id
        legacy_adopted = False
    return DurableIdentityTuple(
        security_id=security_id,
        company_id=company_id,
        instrument_id=instrument_id,
        share_class_id=share_class_id,
        listing_id=listing_id,
        ticker_assignment_id=ticker_assignment_id,
        symbol=row.symbol,
        mic=row.mic,
        currency=row.currency,
        valid_from=row.valid_from,
        exchange_code=row.exchange_code,
        legal_name=row.legal_name,
        legacy_public_id_adopted=legacy_adopted,
    )


def _identity_row_payload(row: IdentityManifestRow) -> dict[str, object]:
    return {
        "memberOrdinal": row.member_ordinal,
        "symbol": row.symbol,
        "mic": row.mic,
        "currency": row.currency,
        "validFrom": row.valid_from,
        "exchangeCode": row.exchange_code,
        "legalName": row.legal_name,
        "openFigiIsinJob": asdict(row.openfigi_isin_job),
        "openFigiCusipJob": asdict(row.openfigi_cusip_job),
        "sec": asdict(row.sec),
        "resolutionState": row.resolution_state,
        "resolutionCode": row.resolution_code,
        "resolutionAuthorityContentHash": row.resolution_authority_content_hash,
        "resolvedAt": row.resolved_at,
        "reasons": row.reasons,
        "identity": None if row.identity is None else asdict(row.identity),
        "legacySecurityId": row.legacy_security_id,
    }


def seal_identity_row(row: IdentityManifestRow) -> IdentityManifestRow:
    _positive_int(row.member_ordinal, "member ordinal")
    _exact_tuple(row.reasons, "identity reasons")
    if _TICKER.fullmatch(row.symbol) is None or _MIC.fullmatch(row.mic) is None:
        raise ProjectionContractViolation("Manifest symbol or MIC is invalid")
    if row.currency != "USD" or type(row.valid_from) is not date:
        raise ProjectionContractViolation("Manifest listing terms are invalid")
    _atom(row.exchange_code, "manifest exchange", maximum=32)
    _atom(row.legal_name, "manifest legal name")
    if (
        row.exchange_code != MIC_TO_SECURITY_EXCHANGE.get(row.mic)
        or row.sec.ticker != row.symbol
        or _sec_mic(row.sec) != row.mic
    ):
        raise ProjectionContractViolation("SEC exchange, MIC, and durable exchange drift")
    _atom(row.resolution_code, "resolution code", maximum=128)
    if type(row.resolution_state) is not IdentityResolutionState:
        raise ProjectionContractViolation("Identity resolution state must be exact")
    if (
        type(row.openfigi_isin_job) is not OpenFigiIdentifierJob
        or type(row.openfigi_cusip_job) is not OpenFigiIdentifierJob
    ):
        raise ProjectionContractViolation("Both OpenFIGI identifier jobs are required")
    if row.openfigi_isin_job.job_kind is not OpenFigiIdentifierJobKind.ISIN_LOOKUP:
        raise ProjectionContractViolation("ISIN job occupies the wrong manifest slot")
    if row.openfigi_cusip_job.job_kind is not OpenFigiIdentifierJobKind.CUSIP_LOOKUP:
        raise ProjectionContractViolation("CUSIP job occupies the wrong manifest slot")
    if (
        row.openfigi_isin_job.source_record_id == row.openfigi_cusip_job.source_record_id
        or row.openfigi_isin_job.request_content_hash == row.openfigi_cusip_job.request_content_hash
    ):
        raise ProjectionContractViolation("OpenFIGI identifier jobs are not independent")
    if type(row.sec) is not SecIdentityLineage:
        raise ProjectionContractViolation("SEC lineage is required")
    _sha256(row.resolution_authority_content_hash, "resolution authority hash")
    resolved_at = _instant(row.resolved_at, "identity resolvedAt")
    if resolved_at < max(
        _instant(row.openfigi_isin_job.ingested_at, "OpenFIGI ISIN ingestedAt"),
        _instant(row.openfigi_cusip_job.ingested_at, "OpenFIGI CUSIP ingestedAt"),
        _instant(row.sec.ingested_at, "SEC ingestedAt"),
    ):
        raise ProjectionContractViolation("Identity resolution predates authority ingestion")
    if row.resolution_authority_content_hash != identity_resolution_content_hash(row):
        raise ProjectionContractViolation("Identity resolution authority hash drift")
    for reason in row.reasons:
        _atom(reason, "identity reason", maximum=128)
    if len(row.reasons) != len(set(row.reasons)):
        raise ProjectionContractViolation("Identity reasons must be unique")
    jobs_concordant = _openfigi_jobs_concordant(row)
    sec_corroborates = _sec_corroborates_openfigi(row)
    match_counts = {
        "ISIN": len(_openfigi_primary_matches(row.openfigi_isin_job)),
        "CUSIP": len(_openfigi_primary_matches(row.openfigi_cusip_job)),
    }
    if row.resolution_state is IdentityResolutionState.ACCEPTED:
        if row.reasons:
            raise ProjectionContractViolation("Accepted identity cannot retain terminal reasons")
        if any(count != 1 for count in match_counts.values()):
            raise ProjectionContractViolation(
                "Each OpenFIGI identifier job must select exactly one primary listing"
            )
        if not jobs_concordant:
            raise ProjectionContractViolation(
                "SEC-only corroboration cannot decide an OpenFIGI identifier conflict"
            )
        if not sec_corroborates:
            raise ProjectionContractViolation("SEC ticker/MIC corroboration failed")
        if row.resolution_code != "INDEPENDENT_OPENFIGI_JOBS_SEC_CORROBORATED":
            raise ProjectionContractViolation("Accepted resolution code is not exact")
        expected = derive_accepted_identity(row)
        if row.identity != expected:
            raise ProjectionContractViolation("Accepted identity tuple is not exact UUID5 replay")
    else:
        if row.identity is not None or not row.reasons:
            raise ProjectionContractViolation(
                "Terminal identity conflict must omit UUIDs and retain reasons"
            )
        expected_reasons: set[str] = set()
        if any(count == 0 for count in match_counts.values()):
            expected_reasons.add("OPENFIGI_PRIMARY_LISTING_MISSING")
        if any(count > 1 for count in match_counts.values()):
            expected_reasons.add("OPENFIGI_PRIMARY_LISTING_AMBIGUOUS")
        if all(count == 1 for count in match_counts.values()) and not jobs_concordant:
            expected_reasons.add("OPENFIGI_IDENTIFIER_JOB_CONFLICT")
        if all(count == 1 for count in match_counts.values()) and not sec_corroborates:
            expected_reasons.add("SEC_TICKER_MIC_CORROBORATION_FAILED")
        if not expected_reasons or not expected_reasons.issubset(row.reasons):
            raise ProjectionContractViolation("Terminal authority conflict reason is missing")
    return replace(row, row_content_hash=_canonical_hash(_identity_row_payload(row)))


@dataclass(frozen=True)
class AdjudicatedIdentityManifest:
    snapshot_id: str
    snapshot_as_of: datetime
    sealed_at: datetime
    population_content_hash: str
    rows: tuple[IdentityManifestRow, ...]
    content_hash: str


def seal_identity_manifest(
    manifest: AdjudicatedIdentityManifest,
) -> AdjudicatedIdentityManifest:
    _atom(manifest.snapshot_id, "identity snapshot id", maximum=128)
    snapshot_as_of = _instant(manifest.snapshot_as_of, "identity snapshot asOf")
    sealed_at = _instant(manifest.sealed_at, "identity snapshot sealedAt")
    if snapshot_as_of > sealed_at:
        raise ProjectionContractViolation("Identity manifest is sealed before its snapshot")
    _sha256(manifest.population_content_hash, "population content hash")
    if manifest.population_content_hash != C5_POPULATION_HASH:
        raise ProjectionContractViolation("Identity manifest must bind the frozen C5 population")
    _exact_tuple(manifest.rows, "identity manifest rows")
    if len(manifest.rows) != EXPECTED_MEMBER_COUNT:
        raise ProjectionContractViolation("Identity manifest must contain exactly 191 rows")
    if [row.member_ordinal for row in manifest.rows] != list(range(1, EXPECTED_MEMBER_COUNT + 1)):
        raise ProjectionContractViolation("Identity manifest ordinals must be complete")
    sealed_rows = tuple(seal_identity_row(row) for row in manifest.rows)
    if sealed_rows != manifest.rows:
        raise ProjectionContractViolation("Identity rows must be sealed before manifest sealing")
    symbols = [row.symbol for row in manifest.rows]
    if len(set(symbols)) != len(symbols):
        raise ProjectionContractViolation("Identity manifest symbols must be unique")
    mic_counts = {
        mic: sum(row.mic == mic for row in manifest.rows) for mic in EXPECTED_MIC_DISTRIBUTION
    }
    if mic_counts != EXPECTED_MIC_DISTRIBUTION:
        raise ProjectionContractViolation("Identity manifest MIC denominator drift")
    if any(
        _instant(row.resolved_at, "identity resolvedAt") > snapshot_as_of for row in manifest.rows
    ):
        raise ProjectionContractViolation("Identity resolution exceeds snapshot cutoff")
    accepted = [row.identity for row in manifest.rows if row.identity is not None]
    for name, values in (
        ("security", [item.security_id for item in accepted]),
        ("share class", [item.share_class_id for item in accepted]),
        ("listing", [item.listing_id for item in accepted]),
        ("ticker assignment", [item.ticker_assignment_id for item in accepted]),
    ):
        if len(values) != len(set(values)):
            raise ProjectionContractViolation(f"Identity manifest {name} is duplicated")
    _validate_company_instrument_sharing(manifest.rows)
    _validate_shared_class_rules(manifest.rows)
    content_hash = _canonical_hash(
        {
            "contractVersion": CONTRACT_VERSION,
            "snapshotId": manifest.snapshot_id,
            "snapshotAsOf": manifest.snapshot_as_of,
            "sealedAt": manifest.sealed_at,
            "populationContentHash": manifest.population_content_hash,
            "rowHashes": [row.row_content_hash for row in manifest.rows],
        }
    )
    return replace(manifest, content_hash=content_hash)


def _validate_shared_class_rules(rows: tuple[IdentityManifestRow, ...]) -> None:
    by_symbol = {row.symbol: row for row in rows}
    for left_symbol, right_symbol in (("GOOG", "GOOGL"), ("FOX", "FOXA")):
        if left_symbol not in by_symbol or right_symbol not in by_symbol:
            raise ProjectionContractViolation(f"Manifest must include {left_symbol}/{right_symbol}")
        left = by_symbol[left_symbol]
        right = by_symbol[right_symbol]
        if left.resolution_state is not right.resolution_state:
            raise ProjectionContractViolation("Shared issuer pair resolution states must align")
        if left.resolution_state is IdentityResolutionState.ACCEPTED:
            assert left.identity is not None and right.identity is not None
            if (
                left.identity.company_id != right.identity.company_id
                or left.identity.instrument_id != right.identity.instrument_id
                or left.identity.share_class_id == right.identity.share_class_id
                or left.identity.listing_id == right.identity.listing_id
                or left.identity.security_id == right.identity.security_id
            ):
                raise ProjectionContractViolation(
                    f"{left_symbol}/{right_symbol} must share issuer/instrument only"
                )
    if "MSFT" not in by_symbol:
        raise ProjectionContractViolation("Manifest must include legacy MSFT identity")
    msft = by_symbol["MSFT"]
    if msft.resolution_state is IdentityResolutionState.ACCEPTED and (
        msft.identity is None
        or not msft.identity.legacy_public_id_adopted
        or msft.identity.security_id != msft.legacy_security_id
    ):
        raise ProjectionContractViolation("MSFT legacy public_id adoption is incomplete")


def _validate_company_instrument_sharing(rows: tuple[IdentityManifestRow, ...]) -> None:
    allowed = {
        frozenset(("GOOG", "GOOGL")),
        frozenset(("FOX", "FOXA")),
    }
    accepted = [row for row in rows if row.identity is not None]
    for name, accessor in (
        ("company", lambda row: row.identity.company_id),
        ("instrument", lambda row: row.identity.instrument_id),
    ):
        grouped: dict[UUID, set[str]] = {}
        for row in accepted:
            grouped.setdefault(accessor(row), set()).add(row.symbol)
        for symbols in grouped.values():
            if len(symbols) > 1 and frozenset(symbols) not in allowed:
                raise ProjectionContractViolation(
                    f"Unrelated securities cannot share one {name} identity"
                )


@dataclass(frozen=True)
class CompletedSessionProof:
    mic: str
    completed_session_id: UUID
    calendar_id: str
    calendar_version: str
    timezone: str
    session_date: date
    scheduled_open: datetime
    scheduled_close: datetime
    early_close: bool
    completed_at: datetime
    recorded_at: datetime
    calendar_content_hash: str
    session_content_hash: str
    authority_code: str
    authority_source_id: str
    authority_source_revision: int
    authority_content_hash: str
    authority_receipt: AcquisitionReceiptBinding
    proof_content_hash: str


def seal_completed_session_proof(value: CompletedSessionProof) -> CompletedSessionProof:
    _uuid(value.completed_session_id, "completed session id")
    if _MIC.fullmatch(value.mic) is None or value.mic not in EXPECTED_MIC_DISTRIBUTION:
        raise ProjectionContractViolation("Completed-session MIC is not supported")
    for name, atom in (
        ("calendar id", value.calendar_id),
        ("calendar version", value.calendar_version),
        ("timezone", value.timezone),
        ("authority code", value.authority_code),
        ("authority source id", value.authority_source_id),
    ):
        _atom(atom, name, maximum=128)
    _positive_int(value.authority_source_revision, "session authority revision")
    for name, digest in (
        ("calendar hash", value.calendar_content_hash),
        ("session hash", value.session_content_hash),
        ("session authority hash", value.authority_content_hash),
    ):
        _sha256(digest, name)
    if seal_acquisition_receipt(value.authority_receipt) != value.authority_receipt:
        raise ProjectionContractViolation("Completed-session authority receipt is not sealed")
    if (
        value.authority_receipt.authority_kind
        is not ProjectionAuthorityKind.COMPLETED_SESSION
        or value.authority_receipt.response_content_hash != value.authority_content_hash
    ):
        raise ProjectionContractViolation("Completed-session authority receipt binding drift")
    opened = _instant(value.scheduled_open, "completed scheduledOpen")
    closed = _instant(value.scheduled_close, "completed scheduledClose")
    completed = _instant(value.completed_at, "completed completedAt")
    recorded = _instant(value.recorded_at, "completed recordedAt")
    receipt_completed = _instant(
        value.authority_receipt.completed_at, "completed receipt completedAt"
    )
    receipt_recorded = _instant(
        value.authority_receipt.recorded_at, "completed receipt recordedAt"
    )
    if type(value.early_close) is not bool or not opened < closed <= completed <= recorded:
        raise ProjectionContractViolation("Completed-session chronology is invalid")
    if not closed <= receipt_completed <= receipt_recorded <= recorded:
        raise ProjectionContractViolation(
            "Completed-session authority receipt chronology is invalid"
        )
    if opened.date() != value.session_date or closed.date() != value.session_date:
        raise ProjectionContractViolation("Completed-session UTC date is inconsistent")
    payload = {**asdict(value), "proof_content_hash": ""}
    return replace(value, proof_content_hash=_canonical_hash(payload))


@dataclass(frozen=True)
class VersionedCalendarScheduleReceipt:
    mic: str
    predecessor_completed_session_id: UUID
    predecessor_session_content_hash: str
    schedule_source_id: str
    schedule_source_version: str
    schedule_source_content_hash: str
    entry_date: date
    scheduled_open: datetime
    scheduled_close: datetime
    early_close: bool
    recorded_at: datetime
    content_hash: str


def seal_calendar_schedule_receipt(
    value: VersionedCalendarScheduleReceipt,
) -> VersionedCalendarScheduleReceipt:
    if _MIC.fullmatch(value.mic) is None or value.mic not in EXPECTED_MIC_DISTRIBUTION:
        raise ProjectionContractViolation("Calendar-schedule MIC is not supported")
    _uuid(value.predecessor_completed_session_id, "schedule predecessor session id")
    _sha256(value.predecessor_session_content_hash, "schedule predecessor session hash")
    for name, atom in (
        ("schedule source id", value.schedule_source_id),
        ("schedule source version", value.schedule_source_version),
    ):
        _atom(atom, name, maximum=128)
    _sha256(value.schedule_source_content_hash, "schedule source hash")
    opened = _instant(value.scheduled_open, "schedule scheduledOpen")
    closed = _instant(value.scheduled_close, "schedule scheduledClose")
    recorded = _instant(value.recorded_at, "schedule recordedAt")
    if (
        type(value.early_close) is not bool
        or recorded > opened
        or opened >= closed
        or opened.date() != value.entry_date
        or closed.date() != value.entry_date
    ):
        raise ProjectionContractViolation("Versioned calendar schedule is invalid")
    payload = {**asdict(value), "content_hash": ""}
    return replace(value, content_hash=_canonical_hash(payload))


@dataclass(frozen=True)
class ImmediateNextSessionProof:
    mic: str
    predecessor_completed_session_id: UUID
    predecessor_session_content_hash: str
    schedule_source_id: str
    schedule_source_version: str
    schedule_source_content_hash: str
    entry_date: date
    scheduled_open: datetime
    scheduled_close: datetime
    early_close: bool
    ordinal_after_predecessor: int
    schedule_receipt: VersionedCalendarScheduleReceipt
    proof_content_hash: str


def seal_next_session_proof(value: ImmediateNextSessionProof) -> ImmediateNextSessionProof:
    _uuid(value.predecessor_completed_session_id, "entry predecessor session id")
    if _MIC.fullmatch(value.mic) is None or value.mic not in EXPECTED_MIC_DISTRIBUTION:
        raise ProjectionContractViolation("Planned-session MIC is not supported")
    for name, atom in (
        ("schedule source id", value.schedule_source_id),
        ("schedule source version", value.schedule_source_version),
    ):
        _atom(atom, name, maximum=128)
    for name, digest in (
        ("predecessor session hash", value.predecessor_session_content_hash),
        ("schedule source hash", value.schedule_source_content_hash),
    ):
        _sha256(digest, name)
    if (
        type(value.schedule_receipt) is not VersionedCalendarScheduleReceipt
        or seal_calendar_schedule_receipt(value.schedule_receipt)
        != value.schedule_receipt
    ):
        raise ProjectionContractViolation("Next-session calendar receipt is not sealed")
    receipt = value.schedule_receipt
    if (
        receipt.mic != value.mic
        or receipt.predecessor_completed_session_id
        != value.predecessor_completed_session_id
        or receipt.predecessor_session_content_hash
        != value.predecessor_session_content_hash
        or receipt.schedule_source_id != value.schedule_source_id
        or receipt.schedule_source_version != value.schedule_source_version
        or receipt.schedule_source_content_hash != value.schedule_source_content_hash
        or receipt.entry_date != value.entry_date
        or receipt.scheduled_open != value.scheduled_open
        or receipt.scheduled_close != value.scheduled_close
        or receipt.early_close is not value.early_close
    ):
        raise ProjectionContractViolation("Next-session calendar receipt binding drift")
    opened = _instant(value.scheduled_open, "entry scheduledOpen")
    closed = _instant(value.scheduled_close, "entry scheduledClose")
    receipt_recorded = _instant(receipt.recorded_at, "entry receipt recordedAt")
    if (
        type(value.early_close) is not bool
        or value.ordinal_after_predecessor != 1
        or receipt_recorded > opened
        or opened >= closed
        or opened.date() != value.entry_date
        or closed.date() != value.entry_date
    ):
        raise ProjectionContractViolation("Immediate-next session proof is invalid")
    payload = {**asdict(value), "proof_content_hash": ""}
    return replace(value, proof_content_hash=_canonical_hash(payload))


class VersionedCalendarScheduleVerifierV1:
    """Exact registry verifier; it never treats Yahoo transport as schedule authority."""

    _TOKEN = object()

    def __init__(
        self,
        receipts: tuple[VersionedCalendarScheduleReceipt, ...],
        *,
        accepted_registry_content_hash: str,
        test_only: bool,
        _token: object,
    ) -> None:
        if _token is not self._TOKEN:
            raise TypeError("Use a VersionedCalendarScheduleVerifierV1 factory")
        if type(test_only) is not bool:
            raise TypeError("Calendar schedule verifier test_only must be exact bool")
        _exact_tuple(receipts, "calendar schedule receipts")
        if any(type(item) is not VersionedCalendarScheduleReceipt for item in receipts):
            raise ProjectionContractViolation("Calendar schedule receipts must be exact")
        sealed = tuple(seal_calendar_schedule_receipt(item) for item in receipts)
        if sealed != receipts or len({item.mic for item in receipts}) != len(receipts):
            raise ProjectionContractViolation("Calendar schedule registry is invalid")
        actual_hash = _canonical_hash([item.content_hash for item in receipts])
        _sha256(accepted_registry_content_hash, "accepted calendar registry hash")
        if actual_hash != accepted_registry_content_hash:
            raise ProjectionIntegrityConflict("Calendar schedule registry hash drift")
        self._receipts = {item.content_hash: item for item in receipts}
        self.registry_content_hash = actual_hash
        self.test_only = test_only

    @classmethod
    def from_accepted_registry(
        cls,
        receipts: tuple[VersionedCalendarScheduleReceipt, ...],
    ) -> VersionedCalendarScheduleVerifierV1:
        accepted = ACCEPTED_NEXT_SESSION_CALENDAR_REGISTRY_CONTENT_HASH
        if accepted is None:
            raise ProjectionIntegrityConflict(
                "No production next-session calendar registry is accepted"
            )
        return cls(
            receipts,
            accepted_registry_content_hash=accepted,
            test_only=False,
            _token=cls._TOKEN,
        )

    @classmethod
    def _from_sealed_test_registry(
        cls,
        receipts: tuple[VersionedCalendarScheduleReceipt, ...],
    ) -> VersionedCalendarScheduleVerifierV1:
        _exact_tuple(receipts, "test calendar schedule receipts")
        accepted = _canonical_hash([item.content_hash for item in receipts])
        return cls(
            receipts,
            accepted_registry_content_hash=accepted,
            test_only=True,
            _token=cls._TOKEN,
        )

    def verify(self, receipt: VersionedCalendarScheduleReceipt) -> None:
        if type(receipt) is not VersionedCalendarScheduleReceipt:
            raise ProjectionIntegrityConflict("Calendar schedule receipt type drift")
        observed = self._receipts.get(receipt.content_hash)
        if observed is None or observed != receipt:
            raise ProjectionIntegrityConflict("Calendar schedule receipt is not authoritative")


class ProjectionAuthorityVerifier:
    """Concrete verifier over a fully replayed acquisition run and schedule registry."""

    _TOKEN = object()

    def __init__(
        self,
        *,
        plan: acquisition_v1.AcquisitionPlan | None,
        verified_run: acquisition_v1.VerifiedAcquisitionRun | None,
        receipts: tuple[AcquisitionReceiptBinding, ...],
        schedule_verifier: VersionedCalendarScheduleVerifierV1,
        existing_security_public_ids: Mapping[tuple[str, str], UUID],
        storage_root: Path | None,
        _token: object,
    ) -> None:
        if _token is not self._TOKEN:
            raise TypeError("Use a ProjectionAuthorityVerifier factory")
        if type(schedule_verifier) is not VersionedCalendarScheduleVerifierV1:
            raise TypeError("Concrete calendar schedule verifier is required")
        if (plan is None) is not (verified_run is None):
            raise TypeError("Acquisition plan/run verification boundary is incomplete")
        if plan is not None and verified_run is not None:
            if (
                type(plan) is not acquisition_v1.AcquisitionPlan
                or type(verified_run) is not acquisition_v1.VerifiedAcquisitionRun
                or verified_run.plan_content_hash != plan.content_hash
                or type(verified_run.receipts) is not tuple
                or type(verified_run.logical_records) is not tuple
                or any(
                    type(item) is not acquisition_v1.SemanticReceipt
                    for item in verified_run.receipts
                )
                or any(
                    type(item) is not acquisition_v1.VerifiedLogicalRecord
                    for item in verified_run.logical_records
                )
                or len({item.request_identity for item in verified_run.receipts})
                != len(verified_run.receipts)
                or len(
                    {item.receipt_content_hash for item in verified_run.logical_records}
                )
                != len(verified_run.logical_records)
            ):
                raise ProjectionIntegrityConflict("Verified acquisition view is invalid")
            if schedule_verifier.test_only is not plan.test_only:
                raise ProjectionIntegrityConflict(
                    "Calendar schedule/acquisition environment binding drift"
                )
        _exact_tuple(receipts, "projection authority receipts")
        if any(type(item) is not AcquisitionReceiptBinding for item in receipts):
            raise ProjectionContractViolation("Projection authority receipts must be exact")
        sealed = tuple(seal_acquisition_receipt(item) for item in receipts)
        if sealed != receipts or len({item.content_hash for item in receipts}) != len(receipts):
            raise ProjectionContractViolation("Projection authority receipt registry is invalid")
        if type(existing_security_public_ids) is not dict:
            raise TypeError("Existing security identity registry must be an exact dict")
        for key, value in existing_security_public_ids.items():
            if (
                type(key) is not tuple
                or len(key) != 2
                or any(type(atom) is not str for atom in key)
                or type(value) is not UUID
            ):
                raise ProjectionContractViolation("Existing security identity registry is invalid")
        self._plan = plan
        self._verified_run = verified_run
        self._receipts = {item.content_hash: item for item in receipts}
        self._schedule_verifier = schedule_verifier
        self._existing_security_public_ids = dict(existing_security_public_ids)
        self._storage_root = None if storage_root is None else storage_root.resolve()

    @classmethod
    def from_verified_acquisition(
        cls,
        plan: acquisition_v1.AcquisitionPlan,
        *,
        storage_root: Path,
        schedule_verifier: VersionedCalendarScheduleVerifierV1,
        existing_security_public_ids: dict[tuple[str, str], UUID],
    ) -> ProjectionAuthorityVerifier:
        if type(plan) is not acquisition_v1.AcquisitionPlan:
            raise TypeError("Exact acquisition plan is required")
        verified = acquisition_v1.verify_acquisition_run(plan, storage_root=storage_root)
        if type(verified) is not acquisition_v1.VerifiedAcquisitionRun:
            raise ProjectionIntegrityConflict("Verified acquisition run type drift")
        return cls(
            plan=plan,
            verified_run=verified,
            receipts=(),
            schedule_verifier=schedule_verifier,
            existing_security_public_ids=existing_security_public_ids,
            storage_root=storage_root,
            _token=cls._TOKEN,
        )

    @classmethod
    def from_verified_acquisition_prefix(
        cls,
        plan: acquisition_v1.AcquisitionPlan,
        *,
        storage_root: Path,
        schedule_verifier: VersionedCalendarScheduleVerifierV1,
        existing_security_public_ids: dict[tuple[str, str], UUID],
    ) -> ProjectionAuthorityVerifier:
        if type(plan) is not acquisition_v1.AcquisitionPlan:
            raise TypeError("Exact acquisition plan is required")
        prefix = acquisition_v1.verify_acquisition_prefix(
            plan, storage_root=storage_root
        )
        if type(prefix) is not acquisition_v1.VerifiedAcquisitionPrefix:
            raise ProjectionIntegrityConflict("Verified acquisition prefix type drift")
        verified = acquisition_v1.VerifiedAcquisitionRun(
            plan_content_hash=plan.content_hash,
            receipts=prefix.receipts,
            logical_records=prefix.logical_records,
            content_hash=prefix.content_hash,
        )
        return cls(
            plan=plan,
            verified_run=verified,
            receipts=(),
            schedule_verifier=schedule_verifier,
            existing_security_public_ids=existing_security_public_ids,
            storage_root=storage_root,
            _token=cls._TOKEN,
        )

    @classmethod
    def _from_sealed_test_receipts(
        cls,
        receipts: tuple[AcquisitionReceiptBinding, ...],
        *,
        schedule_verifier: VersionedCalendarScheduleVerifierV1,
        existing_security_public_ids: dict[tuple[str, str], UUID],
    ) -> ProjectionAuthorityVerifier:
        return cls(
            plan=None,
            verified_run=None,
            receipts=receipts,
            schedule_verifier=schedule_verifier,
            existing_security_public_ids=existing_security_public_ids,
            storage_root=None,
            _token=cls._TOKEN,
        )

    def bind_verified_record_receipt(
        self,
        record: acquisition_v1.VerifiedLogicalRecord,
        *,
        authority_kind: ProjectionAuthorityKind,
        request_content_hash: str,
    ) -> AcquisitionReceiptBinding:
        if self._plan is None or self._verified_run is None:
            raise ProjectionIntegrityConflict("Journal-verified acquisition run is required")
        if type(record) is not acquisition_v1.VerifiedLogicalRecord:
            raise ProjectionIntegrityConflict("Verified logical record type drift")
        matches = tuple(
            item
            for item in self._verified_run.logical_records
            if item.receipt_content_hash == record.receipt_content_hash
        )
        if len(matches) != 1 or matches[0] != record:
            raise ProjectionIntegrityConflict("Logical record is not in the verified run")
        requests = tuple(
            item
            for item in self._plan.requests
            if item.request_identity == record.request_identity
        )
        physical_receipts = tuple(
            item
            for item in self._verified_run.receipts
            if item.request_identity == record.request_identity
        )
        if len(requests) != 1 or len(physical_receipts) != 1:
            raise ProjectionIntegrityConflict("Physical acquisition receipt cardinality drift")
        request = requests[0]
        physical = physical_receipts[0]
        logical_receipts = tuple(
            item
            for item in physical.logical_records
            if item.logical_ordinal == record.logical_ordinal
        )
        if len(logical_receipts) != 1:
            raise ProjectionIntegrityConflict("Logical acquisition receipt cardinality drift")
        logical = logical_receipts[0]
        if (
            logical.request_identity != record.request_identity
            or logical.security_id != record.security_id
            or logical.logical_key != record.logical_key
            or logical.logical_request_hash != record.logical_request_hash
            or logical.raw_payload_sha256 != record.raw_payload_sha256
            or logical.raw_record_sha256 != record.raw_record_sha256
            or logical.normalized_record_hash != record.normalized_record_hash
            or logical.recorded_at != record.recorded_at
            or logical.content_hash != record.receipt_content_hash
            or physical.payload_sha256 != record.raw_payload_sha256
            or physical.response_headers_hash != record.response_headers_hash
            or physical.semantic_content_hash != record.semantic_content_hash
            or physical.journal_event_hash != record.journal_event_hash
            or physical.recorded_at != record.recorded_at
        ):
            raise ProjectionIntegrityConflict("Logical/physical acquisition lineage drift")
        expected_provider = {
            ProjectionAuthorityKind.OPENFIGI: "OPENFIGI",
            ProjectionAuthorityKind.SEC: "SEC",
            ProjectionAuthorityKind.PROVIDER_FINANCIALS: "EODHD",
            ProjectionAuthorityKind.COMPLETED_SESSION: "YAHOO_CHART",
        }.get(authority_kind)
        if expected_provider is None or request.provider != expected_provider:
            raise ProjectionIntegrityConflict("Acquisition authority/provider mismatch")
        try:
            raw_wire = json.loads(record.raw_record_json)
            normalized_wire = json.loads(record.normalized_record_json)
        except (TypeError, ValueError) as error:
            raise ProjectionIntegrityConflict("Verified logical record JSON is invalid") from error
        response_hash = _canonical_hash(raw_wire)
        if (
            response_hash
            != _acquisition_hash(record.raw_record_sha256, "acquisition raw-record hash")
            or _canonical_hash(normalized_wire)
            != _acquisition_hash(
                record.normalized_record_hash, "acquisition normalized-record hash"
            )
        ):
            raise ProjectionIntegrityConflict("Verified logical record hash drift")
        _sha256(request_content_hash, "projected receipt request hash")
        if authority_kind is ProjectionAuthorityKind.OPENFIGI:
            if not 1 <= record.logical_ordinal <= len(request.jobs):
                raise ProjectionIntegrityConflict("OpenFIGI logical ordinal drift")
            job = request.jobs[record.logical_ordinal - 1]
            job_kind = {
                "ID_ISIN": OpenFigiIdentifierJobKind.ISIN_LOOKUP,
                "ID_CUSIP": OpenFigiIdentifierJobKind.CUSIP_LOOKUP,
            }.get(job.identifier_type)
            if job_kind is None:
                raise ProjectionIntegrityConflict("OpenFIGI logical job type drift")
            expected_request_hash = openfigi_wire_request_content_hash(
                job_kind=job_kind,
                requested_identifier=job.identifier_value,
                expected_ticker=job.symbol,
                expected_mic=job.mic,
            )
            if expected_request_hash != request_content_hash:
                raise ProjectionIntegrityConflict("OpenFIGI projected request hash drift")
        recorded_at = _acquisition_recorded_at(record.recorded_at)
        receipt = seal_acquisition_receipt(
            AcquisitionReceiptBinding(
                authority_kind=authority_kind,
                plan_content_hash=_acquisition_hash(
                    self._verified_run.plan_content_hash, "acquisition plan hash"
                ),
                request_identity_hash=_acquisition_hash(
                    record.request_identity, "physical request identity"
                ),
                request_content_hash=request_content_hash,
                checkpoint_content_hash=_acquisition_hash(
                    record.journal_event_hash, "acquisition journal-event hash"
                ),
                physical_receipt_content_hash=_acquisition_hash(
                    physical.content_hash, "physical semantic receipt hash"
                ),
                response_headers_content_hash=_acquisition_hash(
                    record.response_headers_hash, "response-headers hash"
                ),
                semantic_content_hash=_acquisition_hash(
                    record.semantic_content_hash, "semantic-content hash"
                ),
                response_content_hash=response_hash,
                completed_at=recorded_at,
                recorded_at=recorded_at,
                transport_state="COMPLETED",
                acquisition_scope_content_hash=_acquisition_scope_content_hash(self._plan),
                logical_ordinal=record.logical_ordinal,
                logical_key=record.logical_key,
                acquisition_logical_request_hash=_acquisition_hash(
                    record.logical_request_hash, "acquisition logical-request hash"
                ),
                raw_payload_content_hash=_acquisition_hash(
                    record.raw_payload_sha256, "acquisition raw-payload hash"
                ),
                raw_record_content_hash=_acquisition_hash(
                    record.raw_record_sha256, "acquisition raw-record hash"
                ),
                normalized_record_content_hash=_acquisition_hash(
                    record.normalized_record_hash, "acquisition normalized-record hash"
                ),
                logical_receipt_content_hash=_acquisition_hash(
                    record.receipt_content_hash, "acquisition logical receipt hash"
                ),
                content_hash="",
            )
        )
        self._receipts[receipt.content_hash] = receipt
        return receipt

    def decode_verified_openfigi_job(
        self, record: acquisition_v1.VerifiedLogicalRecord
    ) -> OpenFigiIdentifierJob:
        if self._plan is None:
            raise ProjectionIntegrityConflict("Journal-verified acquisition plan is required")
        requests = tuple(
            item
            for item in self._plan.requests
            if item.request_identity == record.request_identity
        )
        if len(requests) != 1 or requests[0].provider != "OPENFIGI":
            raise ProjectionIntegrityConflict("OpenFIGI verified request is missing")
        request = requests[0]
        if not 1 <= record.logical_ordinal <= len(request.jobs):
            raise ProjectionIntegrityConflict("OpenFIGI verified logical ordinal drift")
        job = request.jobs[record.logical_ordinal - 1]
        job_kind = {
            "ID_ISIN": OpenFigiIdentifierJobKind.ISIN_LOOKUP,
            "ID_CUSIP": OpenFigiIdentifierJobKind.CUSIP_LOOKUP,
        }.get(job.identifier_type)
        if job_kind is None:
            raise ProjectionIntegrityConflict("OpenFIGI verified job type drift")
        request_hash = openfigi_wire_request_content_hash(
            job_kind=job_kind,
            requested_identifier=job.identifier_value,
            expected_ticker=job.symbol,
            expected_mic=job.mic,
        )
        receipt = self.bind_verified_record_receipt(
            record,
            authority_kind=ProjectionAuthorityKind.OPENFIGI,
            request_content_hash=request_hash,
        )
        try:
            wire = json.loads(record.raw_record_json)
        except (TypeError, ValueError) as error:
            raise ProjectionIntegrityConflict("OpenFIGI verified raw record is invalid") from error
        recorded_at = _acquisition_recorded_at(record.recorded_at)
        return decode_openfigi_v3_job_response(
            job_kind=job_kind,
            requested_identifier=job.identifier_value,
            expected_ticker=job.symbol,
            expected_mic=job.mic,
            wire_response=wire,
            source_record_id=(
                f"openfigi-{record.request_identity.lower()}-{record.logical_ordinal}"
            ),
            source_revision=1,
            available_at=recorded_at,
            ingested_at=recorded_at,
            acquisition_receipt=receipt,
        )

    def decode_verified_sec_lineage(
        self, record: acquisition_v1.VerifiedLogicalRecord
    ) -> tuple[SecIdentityLineage, str]:
        if self._plan is None:
            raise ProjectionIntegrityConflict("Journal-verified acquisition plan is required")
        requests = tuple(
            item
            for item in self._plan.requests
            if item.request_identity == record.request_identity
        )
        if len(requests) != 1 or requests[0].provider != "SEC":
            raise ProjectionIntegrityConflict("SEC verified request is missing")
        try:
            normalized = json.loads(record.normalized_record_json)
        except (TypeError, ValueError) as error:
            raise ProjectionIntegrityConflict("SEC verified normalized record is invalid") from error
        if type(normalized) is not dict or set(normalized) != {
            "securityId",
            "symbol",
            "mic",
            "cik",
            "issuerName",
        }:
            raise ProjectionIntegrityConflict("SEC verified normalized schema drift")
        mic = normalized["mic"]
        exchange = {"XNYS": "NYSE", "XNAS": "Nasdaq"}.get(mic)
        if exchange is None:
            raise ProjectionIntegrityConflict("SEC verified MIC is unsupported")
        request_hash = _canonical_hash(
            {
                "contractVersion": CONTRACT_VERSION,
                "authorityKind": ProjectionAuthorityKind.SEC,
                "acquisitionLogicalRequestHash": _acquisition_hash(
                    record.logical_request_hash, "SEC acquisition logical-request hash"
                ),
            }
        )
        receipt = self.bind_verified_record_receipt(
            record,
            authority_kind=ProjectionAuthorityKind.SEC,
            request_content_hash=request_hash,
        )
        recorded_at = _acquisition_recorded_at(record.recorded_at)
        result = SecIdentityLineage(
            cik=normalized["cik"],
            ticker=normalized["symbol"],
            exchange=exchange,
            source_record_id=(
                f"sec-{record.request_identity.lower()}-{record.logical_ordinal}"
            ),
            source_revision=1,
            available_at=recorded_at,
            ingested_at=recorded_at,
            source_content_hash=receipt.response_content_hash,
            acquisition_receipt=receipt,
        )
        self.verify_sec_lineage(result, expected_legal_name=normalized["issuerName"])
        return result, normalized["issuerName"]

    def decode_verified_provider_raw_manifest(
        self,
        record: acquisition_v1.VerifiedLogicalRecord,
        *,
        provider_contract_version: str,
        licensing_classification: str,
    ) -> ProviderRawManifest:
        if self._plan is None or self._storage_root is None:
            raise ProjectionIntegrityConflict("Journal-verified provider storage is required")
        requests = tuple(
            item
            for item in self._plan.requests
            if item.request_identity == record.request_identity
        )
        if len(requests) != 1 or requests[0].provider != "EODHD":
            raise ProjectionIntegrityConflict("EODHD verified request is missing")
        request = requests[0]
        request_hash = _canonical_hash(
            {
                "contractVersion": CONTRACT_VERSION,
                "authorityKind": ProjectionAuthorityKind.PROVIDER_FINANCIALS,
                "acquisitionLogicalRequestHash": _acquisition_hash(
                    record.logical_request_hash,
                    "provider acquisition logical-request hash",
                ),
            }
        )
        receipt = self.bind_verified_record_receipt(
            record,
            authority_kind=ProjectionAuthorityKind.PROVIDER_FINANCIALS,
            request_content_hash=request_hash,
        )
        recorded_at = _acquisition_recorded_at(record.recorded_at)
        source_record_id = (
            f"eodhd-{record.request_identity.lower()}-{record.logical_ordinal}"
        )
        raw_manifest_id = uuid5(
            NAMESPACE_URL,
            "|".join(
                (
                    V22_CONTRACT_VERSION,
                    "EODHD",
                    source_record_id,
                    "1",
                    receipt.response_content_hash,
                )
            ),
        )
        result = seal_raw_manifest(
            ProviderRawManifest(
                raw_manifest_id=raw_manifest_id,
                provider_code="EODHD",
                provider_contract_version=provider_contract_version,
                licensing_classification=licensing_classification,
                provider_schema_version=request.expected_schema_version,
                source_record_id=source_record_id,
                source_revision=1,
                source_content_hash=receipt.response_content_hash,
                storage_reference=str(
                    (
                        self._storage_root
                        / acquisition_v1.CONTRACT_VERSION
                        / self._plan.run_id
                        / "_private"
                        / "checkpoints"
                        / f"{record.request_identity}.bin"
                    ).resolve()
                ),
                effective_at=recorded_at,
                available_at=recorded_at,
                retrieved_at=recorded_at,
                ingested_at=recorded_at,
                acquisition_receipt=receipt,
                content_hash="",
            )
        )
        self.verify_raw_manifest(result)
        return result

    def verified_logical_records(
        self, *, authority_kind: ProjectionAuthorityKind
    ) -> tuple[acquisition_v1.VerifiedLogicalRecord, ...]:
        if self._plan is None or self._verified_run is None:
            raise ProjectionIntegrityConflict("Journal-verified acquisition run is required")
        provider = {
            ProjectionAuthorityKind.OPENFIGI: "OPENFIGI",
            ProjectionAuthorityKind.SEC: "SEC",
            ProjectionAuthorityKind.PROVIDER_FINANCIALS: "EODHD",
            ProjectionAuthorityKind.COMPLETED_SESSION: "YAHOO_CHART",
        }.get(authority_kind)
        if provider is None:
            raise ProjectionContractViolation("Authority kind has no acquisition provider")
        identities = {
            item.request_identity for item in self._plan.requests if item.provider == provider
        }
        return tuple(
            item
            for item in self._verified_run.logical_records
            if item.request_identity in identities
        )

    def verify_receipt(self, receipt: AcquisitionReceiptBinding) -> None:
        if type(receipt) is not AcquisitionReceiptBinding:
            raise ProjectionIntegrityConflict("Acquisition receipt type drift")
        observed = self._receipts.get(receipt.content_hash)
        if observed is None and self._verified_run is not None:
            matches = tuple(
                item
                for item in self._verified_run.logical_records
                if _acquisition_hash(
                    item.receipt_content_hash, "acquisition logical receipt hash"
                )
                == receipt.logical_receipt_content_hash
            )
            if len(matches) == 1:
                observed = self.bind_verified_record_receipt(
                    matches[0],
                    authority_kind=receipt.authority_kind,
                    request_content_hash=receipt.request_content_hash,
                )
        if observed is None or observed != receipt:
            raise ProjectionIntegrityConflict("Acquisition receipt is not journal-verified")

    def _record_for_receipt(
        self, receipt: AcquisitionReceiptBinding
    ) -> acquisition_v1.VerifiedLogicalRecord | None:
        self.verify_receipt(receipt)
        if self._verified_run is None:
            return None
        matches = tuple(
            item
            for item in self._verified_run.logical_records
            if _acquisition_hash(
                item.receipt_content_hash, "acquisition logical receipt hash"
            )
            == receipt.logical_receipt_content_hash
        )
        if len(matches) != 1:
            raise ProjectionIntegrityConflict("Verified logical receipt cardinality drift")
        return matches[0]

    def verify_sec_lineage(
        self, lineage: SecIdentityLineage, *, expected_legal_name: str
    ) -> None:
        record = self._record_for_receipt(lineage.acquisition_receipt)
        if record is None:
            return
        try:
            normalized = json.loads(record.normalized_record_json)
        except (TypeError, ValueError) as error:
            raise ProjectionIntegrityConflict("SEC normalized lineage is invalid") from error
        expected_source_record_id = (
            f"sec-{record.request_identity.lower()}-{record.logical_ordinal}"
        )
        recorded_at = _acquisition_recorded_at(record.recorded_at)
        if (
            type(normalized) is not dict
            or set(normalized)
            != {"securityId", "symbol", "mic", "cik", "issuerName"}
            or normalized.get("symbol") != lineage.ticker
            or normalized.get("mic") != _sec_mic(lineage)
            or normalized.get("cik") != lineage.cik
            or normalized.get("issuerName") != expected_legal_name
            or lineage.source_record_id != expected_source_record_id
            or lineage.source_revision != 1
            or lineage.available_at != recorded_at
            or lineage.ingested_at != recorded_at
        ):
            raise ProjectionIntegrityConflict("SEC normalized/source lineage drift")

    def verify_raw_manifest(self, raw: ProviderRawManifest) -> None:
        record = self._record_for_receipt(raw.acquisition_receipt)
        if record is None:
            return
        try:
            normalized = json.loads(record.normalized_record_json)
            raw_wire = json.loads(record.raw_record_json)
        except (TypeError, ValueError) as error:
            raise ProjectionIntegrityConflict(
                "Provider normalized raw-manifest lineage is invalid"
            ) from error
        expected_source_record_id = (
            f"eodhd-{record.request_identity.lower()}-{record.logical_ordinal}"
        )
        if self._storage_root is None or self._plan is None:
            raise ProjectionIntegrityConflict("Provider raw storage authority is missing")
        expected_storage_reference = str(
            (
                self._storage_root
                / acquisition_v1.CONTRACT_VERSION
                / self._plan.run_id
                / "_private"
                / "checkpoints"
                / f"{record.request_identity}.bin"
            ).resolve()
        )
        recorded_at = _acquisition_recorded_at(record.recorded_at)
        if (
            type(normalized) is not dict
            or set(normalized)
            != {"securityId", "symbol", "mic", "fundamentalsPayloadHash"}
            or raw.provider_code != "EODHD"
            or raw.provider_schema_version != "eodhd-fundamentals-v1"
            or raw.source_record_id != expected_source_record_id
            or raw.storage_reference != expected_storage_reference
            or raw.source_revision != 1
            or raw.source_content_hash != _canonical_hash(raw_wire)
            or normalized.get("fundamentalsPayloadHash")
            != record.raw_record_sha256
            or raw.effective_at != recorded_at
            or raw.available_at != recorded_at
            or raw.retrieved_at != recorded_at
            or raw.ingested_at != recorded_at
        ):
            raise ProjectionIntegrityConflict("Provider raw-manifest lineage drift")

    def verify_completed_session(self, proof: CompletedSessionProof) -> None:
        record = self._record_for_receipt(proof.authority_receipt)
        if record is None:
            return
        if self._plan is None or self._verified_run is None:
            raise ProjectionIntegrityConflict("Verified completed-session plan is missing")
        requests = tuple(
            item
            for item in self._plan.requests
            if item.request_identity == record.request_identity
        )
        physical_receipts = tuple(
            item
            for item in self._verified_run.receipts
            if item.request_identity == record.request_identity
        )
        if len(requests) != 1 or len(physical_receipts) != 1:
            raise ProjectionIntegrityConflict(
                "Completed-session acquisition cardinality drift"
            )
        request = requests[0]
        physical = physical_receipts[0]
        recorded_at = _acquisition_recorded_at(record.recorded_at)
        expected_source_id = (
            f"yahoo-{record.request_identity.lower()}-{record.logical_ordinal}"
        )
        if (
            request.provider != "YAHOO_CHART"
            or request.mic != proof.mic
            or physical.completed_session_date != proof.session_date.isoformat()
            or physical.calendar_version != proof.calendar_version
            or proof.authority_code != "YAHOO_COMPLETED_SESSION_OBSERVATION"
            or proof.authority_source_id != expected_source_id
            or proof.authority_source_revision != 1
            or proof.completed_at != recorded_at
            or proof.recorded_at != recorded_at
        ):
            raise ProjectionIntegrityConflict(
                "Completed-session acquisition/source lineage drift"
            )

    def verify_schedule_receipt(
        self, receipt: VersionedCalendarScheduleReceipt
    ) -> None:
        self._schedule_verifier.verify(receipt)

    def load_existing_security_public_id(self, symbol: str, exchange: str) -> UUID:
        try:
            return self._existing_security_public_ids[(symbol, exchange)]
        except KeyError as error:
            raise ProjectionIntegrityConflict(
                "Existing security public_id authority is missing"
            ) from error


@dataclass(frozen=True)
class ProviderRawManifest:
    raw_manifest_id: UUID
    provider_code: str
    provider_contract_version: str
    licensing_classification: str
    provider_schema_version: str
    source_record_id: str
    source_revision: int
    source_content_hash: str
    storage_reference: str
    effective_at: datetime
    available_at: datetime
    retrieved_at: datetime | None
    ingested_at: datetime
    acquisition_receipt: AcquisitionReceiptBinding
    content_hash: str


def seal_raw_manifest(value: ProviderRawManifest) -> ProviderRawManifest:
    _uuid(value.raw_manifest_id, "raw manifest id")
    for name, atom, maximum in (
        ("provider code", value.provider_code, 128),
        ("provider contract version", value.provider_contract_version, 128),
        ("provider schema version", value.provider_schema_version, 128),
        ("source record id", value.source_record_id, 255),
    ):
        _atom(atom, name, maximum=maximum)
    _storage_reference(value.storage_reference, "storage reference")
    if value.licensing_classification not in {"PRIVATE_LICENSED", "PUBLIC_PERMITTED"}:
        raise ProjectionContractViolation("Raw manifest licensing class is unsupported")
    _positive_int(value.source_revision, "raw source revision")
    _sha256(value.source_content_hash, "raw source hash")
    expected_id = uuid5(
        NAMESPACE_URL,
        "|".join(
            (
                V22_CONTRACT_VERSION,
                value.provider_code,
                value.source_record_id,
                str(value.source_revision),
                value.source_content_hash,
            )
        ),
    )
    if value.raw_manifest_id != expected_id:
        raise ProjectionContractViolation("Raw manifest UUID5 identity drift")
    effective = _instant(value.effective_at, "raw effectiveAt")
    available = _instant(value.available_at, "raw availableAt")
    ingested = _instant(value.ingested_at, "raw ingestedAt")
    retrieved = (
        None if value.retrieved_at is None else _instant(value.retrieved_at, "raw retrievedAt")
    )
    if not effective <= available <= ingested or (
        retrieved is not None and not available <= retrieved <= ingested
    ):
        raise ProjectionContractViolation("Raw manifest chronology is invalid")
    if seal_acquisition_receipt(value.acquisition_receipt) != value.acquisition_receipt:
        raise ProjectionContractViolation("Financial raw acquisition receipt is not sealed")
    receipt_completed = _instant(
        value.acquisition_receipt.completed_at, "financial receipt completedAt"
    )
    receipt_recorded = _instant(
        value.acquisition_receipt.recorded_at, "financial receipt recordedAt"
    )
    if (
        value.acquisition_receipt.authority_kind
        is not ProjectionAuthorityKind.PROVIDER_FINANCIALS
        or value.acquisition_receipt.response_content_hash != value.source_content_hash
        or retrieved is None
        or not available <= receipt_completed == retrieved <= receipt_recorded <= ingested
    ):
        raise ProjectionContractViolation("Financial raw acquisition receipt binding drift")
    payload = {**asdict(value), "content_hash": ""}
    return replace(value, content_hash=_canonical_hash(payload))


@dataclass(frozen=True)
class V22SelectedParentReference:
    security_id: UUID
    operand_code: str
    canonical_field_code: str
    parent_period_end: date
    selection_request_id: UUID
    selection_result_hash: str
    canonical_evidence_id: UUID
    raw_manifest_id: UUID
    raw_storage_reference: str

    def __post_init__(self) -> None:
        for name in (
            "security_id",
            "selection_request_id",
            "canonical_evidence_id",
            "raw_manifest_id",
        ):
            _uuid(getattr(self, name), f"V22 selected parent {name}")
        _atom(self.operand_code, "V22 operand", maximum=64)
        _atom(self.canonical_field_code, "V22 field", maximum=64)
        _sha256(self.selection_result_hash, "V22 selection result hash")
        _storage_reference(self.raw_storage_reference, "V22 raw storage reference")
        if type(self.parent_period_end) is not date:
            raise ProjectionContractViolation("V22 parent periodEnd must be a date")


@dataclass(frozen=True)
class NormalizedParentProjection:
    normalized_parent_id: UUID
    identity: DurableIdentityTuple
    raw_manifest_id: UUID
    canonical_field_code: str
    numeric_value: Decimal
    period_start: date | None
    period_end: date
    source_content_hash: str
    normalized_record_hash: str
    provider_code: str
    provider_schema_version: str
    source_record_id: str
    source_revision: int
    effective_at: datetime
    available_at: datetime
    ingested_at: datetime
    currency: str
    unit: str
    content_hash: str


def seal_normalized_parent(value: NormalizedParentProjection) -> NormalizedParentProjection:
    _uuid(value.normalized_parent_id, "normalized parent id")
    _uuid(value.raw_manifest_id, "normalized parent raw manifest id")
    if value.canonical_field_code not in {"INCOME_TAX", "PRETAX_INCOME"}:
        raise ProjectionContractViolation("V24 normalized parent field is unsupported")
    expected_id = _identity_uuid(
        "normalized-parent",
        str(value.identity.security_id),
        str(value.raw_manifest_id),
        value.canonical_field_code,
        value.period_end.isoformat(),
    )
    if value.normalized_parent_id != expected_id:
        raise ProjectionContractViolation("Normalized parent UUID5 identity drift")
    canonical_decimal_text(value.numeric_value)
    if value.numeric_value.copy_abs() > Decimal("1e100"):
        raise ProjectionContractViolation("Normalized parent magnitude is outside V24")
    if type(value.period_end) is not date or (
        value.period_start is not None
        and (type(value.period_start) is not date or value.period_start > value.period_end)
    ):
        raise ProjectionContractViolation("Normalized parent period is invalid")
    for name, digest in (
        ("normalized parent source hash", value.source_content_hash),
        ("normalized parent record hash", value.normalized_record_hash),
    ):
        _sha256(digest, name)
    for name, atom, maximum in (
        ("normalized provider", value.provider_code, 128),
        ("normalized schema", value.provider_schema_version, 128),
        ("normalized source record", value.source_record_id, 255),
        ("normalized unit", value.unit, 32),
    ):
        _atom(atom, name, maximum=maximum)
    _positive_int(value.source_revision, "normalized source revision")
    if value.currency != "USD":
        raise ProjectionContractViolation("Normalized parent currency must be USD")
    effective = _instant(value.effective_at, "normalized effectiveAt")
    available = _instant(value.available_at, "normalized availableAt")
    ingested = _instant(value.ingested_at, "normalized ingestedAt")
    if not effective <= available <= ingested:
        raise ProjectionContractViolation("Normalized parent chronology is invalid")
    payload = {**asdict(value), "content_hash": ""}
    return replace(value, content_hash=_canonical_hash(payload))


@dataclass(frozen=True)
class ProjectionMemberPlan:
    security_id: UUID
    terminal_state: TerminalState
    reasons: tuple[str, ...]
    selected_parents: tuple[V22SelectedParentReference, ...]
    normalized_parent_ids: tuple[UUID, ...]

    def __post_init__(self) -> None:
        _uuid(self.security_id, "member plan security id")
        _exact_tuple(self.reasons, "member plan reasons")
        _exact_tuple(self.selected_parents, "member plan selected parents")
        _exact_tuple(self.normalized_parent_ids, "member plan normalized parents")
        if type(self.terminal_state) is not TerminalState:
            raise ProjectionContractViolation("Member plan terminal state must be exact")
        for reason in self.reasons:
            _atom(reason, "member plan reason", maximum=128)
        if len(self.reasons) != len(set(self.reasons)):
            raise ProjectionContractViolation("Member plan reasons must be unique")
        request_ids = [item.selection_request_id for item in self.selected_parents]
        evidence_ids = [item.canonical_evidence_id for item in self.selected_parents]
        if len(request_ids) != len(set(request_ids)) or len(evidence_ids) != len(set(evidence_ids)):
            raise ProjectionContractViolation("Member plan V22 parents must be unique")
        if len(self.normalized_parent_ids) != len(set(self.normalized_parent_ids)):
            raise ProjectionContractViolation("Member plan normalized parents must be unique")
        for parent_id in self.normalized_parent_ids:
            _uuid(parent_id, "member plan normalized parent id")


@dataclass(frozen=True)
class ProjectionFoundation:
    manifest: AdjudicatedIdentityManifest
    completed_sessions: tuple[CompletedSessionProof, ...]
    planned_sessions: tuple[ImmediateNextSessionProof, ...]
    raw_manifests: tuple[ProviderRawManifest, ...]
    normalized_parents: tuple[NormalizedParentProjection, ...]


@dataclass(frozen=True)
class EnrollmentProjectionRequest:
    foundation: ProjectionFoundation
    member_plans: tuple[ProjectionMemberPlan, ...]
    enrollment_id: UUID
    decision_cutoff: datetime
    evidence_cutoff: datetime
    sealed_at: datetime
    outcome_protocol_content_hash: str
    idempotency_key: str


@runtime_checkable
class V22SelectedEvidenceReader(Protocol):
    def load_binding(
        self,
        reference: V22SelectedParentReference,
        identity: DurableIdentityTuple,
        session: CompletedSessionProof,
        decision_cutoff: datetime,
        evidence_cutoff: datetime,
    ) -> EvidenceBinding: ...


class EvidenceFoundationProjectionReaderV1:
    """Typed projection adapter over the accepted V22 repository and selector."""

    def __init__(self, repository: EvidenceFoundationRepository) -> None:
        if not isinstance(repository, EvidenceFoundationRepository):
            raise TypeError("V22 projection requires EvidenceFoundationRepository")
        self._repository = repository

    def load_binding(
        self,
        reference: V22SelectedParentReference,
        identity: DurableIdentityTuple,
        session: CompletedSessionProof,
        decision_cutoff: datetime,
        evidence_cutoff: datetime,
    ) -> EvidenceBinding:
        aggregate = self._repository.load_selector_aggregate(str(reference.selection_request_id))
        envelope = self._repository.load_candidate(str(reference.canonical_evidence_id))
        return _binding_from_v22(
            aggregate,
            envelope,
            reference,
            identity,
            session,
            decision_cutoff,
            evidence_cutoff,
        )


def _binding_from_v22(
    aggregate: PersistedSelectorAggregate,
    envelope: PersistedEvidenceEnvelope,
    reference: V22SelectedParentReference,
    identity: DurableIdentityTuple,
    session: CompletedSessionProof,
    decision_cutoff: datetime,
    evidence_cutoff: datetime,
) -> EvidenceBinding:
    if (
        type(aggregate) is not PersistedSelectorAggregate
        or type(envelope) is not PersistedEvidenceEnvelope
        or type(aggregate.request) is not EvidenceSelectionRequest
        or type(aggregate.result) is not EvidenceSelectionResult
        or type(envelope.candidate) is not EvidenceCandidate
    ):
        raise ProjectionIntegrityConflict(
            "V22 persisted selector and evidence records must be exact typed readback"
        )
    request = aggregate.request
    result = aggregate.result
    candidate = envelope.candidate
    if aggregate.request_id != str(reference.selection_request_id):
        raise ProjectionIntegrityConflict("V22 selector request identity drift")
    if (
        result.state is not DataState.VALID
        or result.selected is None
        or result.selected.evidence_id != str(reference.canonical_evidence_id)
        or candidate != result.selected
    ):
        raise ProjectionIntegrityConflict("V22 selected evidence is not exact readback")
    result_hash = v22_persistence._result_hash(request, result)
    if result_hash != reference.selection_result_hash:
        raise ProjectionIntegrityConflict("V22 selector result hash drift")
    if v22_persistence._raw_manifest_id(candidate) != reference.raw_manifest_id:
        raise ProjectionIntegrityConflict("V22 raw manifest identity drift")
    if envelope.raw_storage_reference != reference.raw_storage_reference:
        raise ProjectionIntegrityConflict("V22 private storage reference drift")
    expected_security = tuple(
        str(value)
        for value in (
            identity.security_id,
            identity.company_id,
            identity.instrument_id,
            identity.share_class_id,
            identity.listing_id,
            identity.ticker_assignment_id,
        )
    )
    if request.security.durable_tuple != expected_security or (
        request.security.ticker,
        request.security.mic,
        request.security.currency,
    ) != (identity.symbol, identity.mic, identity.currency):
        raise ProjectionIntegrityConflict("V22 selector durable identity drift")
    completed = request.completed_session
    if (
        completed.calendar_id,
        completed.calendar_version,
        completed.mic,
        completed.session_date,
        completed.scheduled_open,
        completed.scheduled_close,
        completed.early_close,
        completed.completed_at,
    ) != (
        session.calendar_id,
        session.calendar_version,
        session.mic,
        session.session_date,
        session.scheduled_open,
        session.scheduled_close,
        session.early_close,
        session.completed_at,
    ):
        raise ProjectionIntegrityConflict("V22 selector completed-session drift")
    if (
        request.decision_cutoff != decision_cutoff
        or request.sealed_ingestion_cutoff != evidence_cutoff
    ):
        raise ProjectionIntegrityConflict("V22 selector cutoff drift")
    if request.policy.domain is not EvidenceDomain.FUNDAMENTAL or (
        request.policy.field_code != reference.canonical_field_code
        or request.policy.domain_constraints.get("metricCode") != reference.canonical_field_code
        or request.policy.domain_constraints.get("periodEnd")
        != reference.parent_period_end.isoformat()
    ):
        raise ProjectionIntegrityConflict("V22 selector fundamental binding drift")
    canonical = candidate.canonical_data
    if (
        candidate.state is not DataState.VALID
        or canonical is None
        or (
            candidate.domain != EvidenceDomain.FUNDAMENTAL.value
            or canonical.get("metricCode") != reference.canonical_field_code
            or canonical.get("periodEnd") != reference.parent_period_end.isoformat()
        )
    ):
        raise ProjectionIntegrityConflict("V22 canonical fundamental drift")
    if candidate.available_at > decision_cutoff or candidate.ingested_at > evidence_cutoff:
        raise ProjectionIntegrityConflict("V22 evidence exceeds enrollment cutoff")
    return EvidenceBinding(
        evidence_ordinal=1,
        operand_code=reference.operand_code,
        canonical_field_code=reference.canonical_field_code,
        provenance_kind="V22_SELECTED_EVIDENCE",
        numeric_value=Decimal(canonical["numericValue"]),
        selection_request_id=reference.selection_request_id,
        selection_result_hash=reference.selection_result_hash,
        canonical_evidence_id=reference.canonical_evidence_id,
        normalized_parent_id=None,
        raw_manifest_id=reference.raw_manifest_id,
        provider_code=candidate.provider_code,
        provider_schema_version=candidate.provider_schema_version,
        source_record_id=candidate.source_record_id,
        source_revision=candidate.source_revision,
        parent_period_start=(
            None
            if canonical["periodStart"] is None
            else date.fromisoformat(canonical["periodStart"])
        ),
        parent_period_end=date.fromisoformat(canonical["periodEnd"]),
        parent_source_content_hash=candidate.source_content_hash,
        parent_normalized_record_hash=candidate.normalized_record_hash,
        parent_effective_at=candidate.effective_at,
        parent_available_at=candidate.available_at,
        parent_ingested_at=candidate.ingested_at,
        currency=canonical["currency"],
        unit=canonical["unit"],
    )


def _normalized_binding(value: NormalizedParentProjection) -> EvidenceBinding:
    operand = value.canonical_field_code
    return EvidenceBinding(
        evidence_ordinal=1,
        operand_code=operand,
        canonical_field_code=value.canonical_field_code,
        provenance_kind="V24_PROVIDER_NORMALIZED_PARENT",
        numeric_value=value.numeric_value,
        selection_request_id=None,
        selection_result_hash=None,
        canonical_evidence_id=None,
        normalized_parent_id=value.normalized_parent_id,
        raw_manifest_id=value.raw_manifest_id,
        provider_code=value.provider_code,
        provider_schema_version=value.provider_schema_version,
        source_record_id=value.source_record_id,
        source_revision=value.source_revision,
        parent_period_start=value.period_start,
        parent_period_end=value.period_end,
        parent_source_content_hash=value.source_content_hash,
        parent_normalized_record_hash=value.normalized_record_hash,
        parent_effective_at=value.effective_at,
        parent_available_at=value.available_at,
        parent_ingested_at=value.ingested_at,
        currency=value.currency,
        unit=value.unit,
    )


def _validated_foundation(value: ProjectionFoundation) -> None:
    if seal_identity_manifest(value.manifest) != value.manifest:
        raise ProjectionContractViolation("Identity manifest content hash is invalid")
    for collection_name, collection in (
        ("completed sessions", value.completed_sessions),
        ("planned sessions", value.planned_sessions),
        ("raw manifests", value.raw_manifests),
        ("normalized parents", value.normalized_parents),
    ):
        _exact_tuple(collection, collection_name)
    if (
        len(value.completed_sessions) != EXPECTED_SESSION_COUNT
        or len(value.planned_sessions) != EXPECTED_PLANNED_ENTRY_COUNT
    ):
        raise ProjectionContractViolation("Projection requires exactly two sessions and entries")
    sessions = tuple(seal_completed_session_proof(item) for item in value.completed_sessions)
    planned = tuple(seal_next_session_proof(item) for item in value.planned_sessions)
    if sessions != value.completed_sessions or planned != value.planned_sessions:
        raise ProjectionContractViolation("Session proofs must be sealed")
    session_by_mic = {item.mic: item for item in sessions}
    planned_by_mic = {item.mic: item for item in planned}
    if set(session_by_mic) != set(EXPECTED_MIC_DISTRIBUTION) or set(planned_by_mic) != set(
        EXPECTED_MIC_DISTRIBUTION
    ):
        raise ProjectionContractViolation("Session proofs must cover XNYS and XNAS")
    if len(session_by_mic) != 2 or len(planned_by_mic) != 2:
        raise ProjectionContractViolation("Session MICs must be unique")
    for mic, entry in planned_by_mic.items():
        predecessor = session_by_mic[mic]
        if (
            entry.predecessor_completed_session_id != predecessor.completed_session_id
            or entry.predecessor_session_content_hash != predecessor.session_content_hash
            or entry.entry_date <= predecessor.session_date
        ):
            raise ProjectionContractViolation("Immediate-next entry does not bind its predecessor")
    raw_ids: set[UUID] = set()
    raw_by_id: dict[UUID, ProviderRawManifest] = {}
    for item in value.raw_manifests:
        if seal_raw_manifest(item) != item or item.raw_manifest_id in raw_ids:
            raise ProjectionContractViolation("Raw manifest is unsealed or duplicated")
        raw_ids.add(item.raw_manifest_id)
        raw_by_id[item.raw_manifest_id] = item
    normalized_ids: set[UUID] = set()
    normalized_hashes: set[str] = set()
    normalized_keys: set[tuple[UUID, str, date]] = set()
    for item in value.normalized_parents:
        key = (item.raw_manifest_id, item.canonical_field_code, item.period_end)
        raw = raw_by_id.get(item.raw_manifest_id)
        if (
            seal_normalized_parent(item) != item
            or item.normalized_parent_id in normalized_ids
            or item.normalized_record_hash in normalized_hashes
            or key in normalized_keys
            or raw is None
        ):
            raise ProjectionContractViolation(
                "Normalized parent is unsealed, orphaned, or duplicated"
            )
        if (
            raw.provider_code != item.provider_code
            or raw.provider_schema_version != item.provider_schema_version
            or raw.source_record_id != item.source_record_id
            or raw.source_revision != item.source_revision
            or raw.source_content_hash != item.source_content_hash
            or raw.effective_at != item.effective_at
            or raw.available_at != item.available_at
            or raw.ingested_at != item.ingested_at
        ):
            raise ProjectionContractViolation(
                "Normalized parent does not exactly cross-bind its raw manifest"
            )
        normalized_ids.add(item.normalized_parent_id)
        normalized_hashes.add(item.normalized_record_hash)
        normalized_keys.add(key)


def _verify_projection_authority(
    foundation: ProjectionFoundation,
    verifier: ProjectionAuthorityVerifier,
) -> None:
    if type(verifier) is not ProjectionAuthorityVerifier:
        raise ProjectionContractViolation("Trusted projection authority verifier is required")
    for row in foundation.manifest.rows:
        verifier.verify_receipt(row.openfigi_isin_job.acquisition_receipt)
        verifier.verify_receipt(row.openfigi_cusip_job.acquisition_receipt)
        verifier.verify_sec_lineage(row.sec, expected_legal_name=row.legal_name)
    for session in foundation.completed_sessions:
        verifier.verify_completed_session(session)
    for session in foundation.planned_sessions:
        verifier.verify_schedule_receipt(session.schedule_receipt)
    for raw in foundation.raw_manifests:
        verifier.verify_raw_manifest(raw)
    msft = next(row for row in foundation.manifest.rows if row.symbol == "MSFT")
    if msft.identity is not None:
        expected = verifier.load_existing_security_public_id(
            "MSFT", MIC_TO_SECURITY_EXCHANGE[msft.mic]
        )
        _uuid(expected, "authoritative MSFT public_id")
        if expected != msft.identity.security_id or expected != msft.legacy_security_id:
            raise ProjectionIntegrityConflict("MSFT legacy public_id authority drift")


def build_enrollment_candidate(
    request: EnrollmentProjectionRequest,
    v22_reader: V22SelectedEvidenceReader,
    authority_verifier: ProjectionAuthorityVerifier,
) -> Enrollment:
    _validated_foundation(request.foundation)
    _verify_projection_authority(request.foundation, authority_verifier)
    manifest = request.foundation.manifest
    if manifest.population_content_hash != C5_POPULATION_HASH:
        raise ProjectionContractViolation("Projection does not bind the frozen C5 population")
    if any(
        row.resolution_state is not IdentityResolutionState.ACCEPTED or row.identity is None
        for row in manifest.rows
    ):
        raise ProjectionContractViolation("Full 191 UUID tuple projection is not accepted")
    _exact_tuple(request.member_plans, "member plans")
    if len(request.member_plans) != EXPECTED_MEMBER_COUNT:
        raise ProjectionContractViolation("Member plan denominator must be exactly 191")
    plan_by_security = {item.security_id: item for item in request.member_plans}
    if len(plan_by_security) != EXPECTED_MEMBER_COUNT:
        raise ProjectionContractViolation("Member plans contain duplicate identities")
    manifest_ids = {row.identity.security_id for row in manifest.rows if row.identity is not None}
    if set(plan_by_security) != manifest_ids:
        raise ProjectionContractViolation("Member plans do not equal the identity manifest")
    if [plan.security_id for plan in request.member_plans] != [
        row.identity.security_id for row in manifest.rows if row.identity is not None
    ]:
        raise ProjectionContractViolation("Member plans must preserve manifest order")
    if (
        _instant(request.decision_cutoff, "decision cutoff")
        != _instant(request.evidence_cutoff, "evidence cutoff")
        or _instant(request.sealed_at, "sealedAt")
        < _instant(request.decision_cutoff, "decision cutoff")
        or manifest.snapshot_as_of > request.decision_cutoff
        or manifest.sealed_at > request.sealed_at
    ):
        raise ProjectionContractViolation("Projection request chronology is invalid")
    session_by_mic = {item.mic: item for item in request.foundation.completed_sessions}
    raw_by_id = {item.raw_manifest_id: item for item in request.foundation.raw_manifests}
    normalized_by_id = {
        item.normalized_parent_id: item for item in request.foundation.normalized_parents
    }
    members: list[Member] = []
    used_raw_ids: set[UUID] = set()
    used_normalized_ids: set[UUID] = set()
    for row in manifest.rows:
        assert row.identity is not None
        plan = plan_by_security[row.identity.security_id]
        if plan.terminal_state is TerminalState.USABLE_VALID:
            if (
                plan.reasons
                or len(plan.selected_parents) != V22_PARENT_COUNT
                or len(plan.normalized_parent_ids) != V24_NORMALIZED_PARENT_COUNT
            ):
                raise ProjectionContractViolation("Usable plan must bind exact 55+8 parents")
            bindings = [
                v22_reader.load_binding(
                    reference,
                    row.identity,
                    session_by_mic[row.mic],
                    request.decision_cutoff,
                    request.evidence_cutoff,
                )
                for reference in plan.selected_parents
            ]
            for normalized_id in plan.normalized_parent_ids:
                normalized = normalized_by_id.get(normalized_id)
                if normalized is None or normalized.identity != row.identity:
                    raise ProjectionIntegrityConflict(
                        "Normalized parent identity is missing or drifted"
                    )
                bindings.append(_normalized_binding(normalized))
                used_normalized_ids.add(normalized_id)
            for binding in bindings:
                raw = raw_by_id.get(binding.raw_manifest_id)
                if raw is None or (
                    raw.provider_code != binding.provider_code
                    or raw.provider_schema_version != binding.provider_schema_version
                    or raw.source_record_id != binding.source_record_id
                    or raw.source_revision != binding.source_revision
                    or raw.source_content_hash != binding.parent_source_content_hash
                    or raw.effective_at != binding.parent_effective_at
                    or raw.available_at != binding.parent_available_at
                    or raw.ingested_at != binding.parent_ingested_at
                ):
                    raise ProjectionIntegrityConflict("Source parent raw-manifest lineage drift")
                used_raw_ids.add(binding.raw_manifest_id)
            role_order = {
                role: ordinal for ordinal, (role, _, _, _) in enumerate(PARENT_ROLE_CONTRACT)
            }
            bindings.sort(
                key=lambda item: (
                    role_order[item.operand_code],
                    -item.parent_period_end.toordinal(),
                )
            )
            evidence = tuple(
                replace(binding, evidence_ordinal=ordinal)
                for ordinal, binding in enumerate(bindings, start=1)
            )
            if len(evidence) != PARENT_EVIDENCE_COUNT:
                raise ProjectionContractViolation("Usable plan does not resolve 63 parents")
            score = company_quality_score_from_parents(evidence)
            evidence_hash, source_hash = evidence_aggregate_hashes(evidence)
            member = Member(
                member_ordinal=row.member_ordinal,
                security_id=row.identity.security_id,
                company_id=row.identity.company_id,
                instrument_id=row.identity.instrument_id,
                share_class_id=row.identity.share_class_id,
                listing_id=row.identity.listing_id,
                ticker_assignment_id=row.identity.ticker_assignment_id,
                listing_mic=row.identity.mic,
                terminal_state=TerminalState.USABLE_VALID,
                reasons=(),
                predictor_score=score,
                predictor_rank=None,
                predictor_group=None,
                evidence_available_at=max(item.parent_available_at for item in evidence),
                evidence_ingested_at=max(item.parent_ingested_at for item in evidence),
                evidence_content_hash=evidence_hash,
                source_content_hash=source_hash,
                producer_contract_content_hash=C5_PREDICTOR_CONTRACT_HASH,
                producer_output_content_hash=producer_output_hash(
                    score, evidence_hash, source_hash
                ),
                evidence=evidence,
            )
        else:
            if not plan.reasons or plan.selected_parents or plan.normalized_parent_ids:
                raise ProjectionContractViolation(
                    "Nonusable plan must retain reasons and no parents"
                )
            member = Member(
                member_ordinal=row.member_ordinal,
                security_id=row.identity.security_id,
                company_id=row.identity.company_id,
                instrument_id=row.identity.instrument_id,
                share_class_id=row.identity.share_class_id,
                listing_id=row.identity.listing_id,
                ticker_assignment_id=row.identity.ticker_assignment_id,
                listing_mic=row.identity.mic,
                terminal_state=plan.terminal_state,
                reasons=plan.reasons,
            )
        members.append(member)
    if used_raw_ids != set(raw_by_id) or used_normalized_ids != set(normalized_by_id):
        raise ProjectionContractViolation(
            "Projection foundation contains unused evidence artifacts"
        )
    usable = [item for item in members if item.terminal_state is TerminalState.USABLE_VALID]
    if len(usable) < MINIMUM_USABLE_COUNT:
        raise ProjectionContractViolation("Projection has fewer than 100 usable members")
    ranked = sorted(
        sorted(usable, key=lambda item: str(item.security_id)),
        key=lambda item: item.predictor_score,
        reverse=True,
    )
    rank_by_security = {item.security_id: rank for rank, item in enumerate(ranked, start=1)}
    extreme_count = len(usable) // 5
    sealed_members: list[Member] = []
    for member in members:
        rank = rank_by_security.get(member.security_id)
        if rank is not None:
            group = (
                "HIGH"
                if rank <= extreme_count
                else "LOW"
                if rank > len(usable) - extreme_count
                else "MIDDLE"
            )
            member = replace(member, predictor_rank=rank, predictor_group=group)
        sealed_members.append(seal_member(member))
    sessions = tuple(
        DecisionSession(
            mic=item.mic,
            completed_session_id=item.completed_session_id,
            calendar_id=item.calendar_id,
            calendar_version=item.calendar_version,
            session_date=item.session_date,
            scheduled_open=item.scheduled_open,
            scheduled_close=item.scheduled_close,
            early_close=item.early_close,
            completed_at=item.completed_at,
            recorded_at=item.recorded_at,
            session_content_hash=item.session_content_hash,
            calendar_content_hash=item.calendar_content_hash,
        )
        for item in sorted(request.foundation.completed_sessions, key=lambda item: item.mic)
    )
    entries = tuple(
        PlannedEntry(
            mic=item.mic,
            schedule_source_id=item.schedule_source_id,
            schedule_source_version=item.schedule_source_version,
            schedule_source_content_hash=item.schedule_source_content_hash,
            entry_date=item.entry_date,
            scheduled_open=item.scheduled_open,
            scheduled_close=item.scheduled_close,
            early_close=item.early_close,
            schedule_content_hash=item.proof_content_hash,
        )
        for item in sorted(request.foundation.planned_sessions, key=lambda item: item.mic)
    )
    evidence_manifest_hash = _canonical_hash(
        {
            "identityManifest": manifest.content_hash,
            "rawManifests": [item.content_hash for item in request.foundation.raw_manifests],
            "normalizedParents": [
                item.content_hash for item in request.foundation.normalized_parents
            ],
            "memberPlans": [
                {
                    "securityId": item.security_id,
                    "state": item.terminal_state,
                    "reasons": item.reasons,
                    "selectionRequestIds": [
                        ref.selection_request_id for ref in item.selected_parents
                    ],
                    "normalizedParentIds": item.normalized_parent_ids,
                }
                for item in request.member_plans
            ],
        }
    )
    value = Enrollment(
        enrollment_id=request.enrollment_id,
        decision_sessions=sessions,
        planned_entries=entries,
        decision_cutoff=request.decision_cutoff,
        evidence_cutoff=request.evidence_cutoff,
        sealed_at=request.sealed_at,
        population_content_hash=C5_POPULATION_HASH,
        evidence_manifest_content_hash=evidence_manifest_hash,
        predictor_contract_content_hash=C5_PREDICTOR_CONTRACT_HASH,
        producer_version=PRODUCER_VERSION,
        arithmetic_version=ARITHMETIC_VERSION,
        cost_policy_version=COST_POLICY_VERSION,
        outcome_policy_version=OUTCOME_POLICY_VERSION,
        outcome_protocol_content_hash=request.outcome_protocol_content_hash,
        stage7_acceptance_content_hash=STAGE7_ACCEPTANCE_HASH,
        idempotency_key=request.idempotency_key,
        members=tuple(sealed_members),
        content_hash="",
    )
    value = seal_enrollment(value)
    validate_enrollment(value)
    return value


@dataclass(frozen=True)
class ProjectionPreflightResult:
    state: ProjectionPersistenceState
    missing_objects: tuple[str, ...]
    checked_object_count: int
    content_hash: str


_V22_PROJECTION_KINDS = frozenset(
    {
        "security",
        "company",
        "instrument",
        "share_class",
        "listing",
        "ticker",
        "calendar",
        "completed_session",
        "provider_contract",
        "raw_manifest",
    }
)
_V24_NORMALIZED_PARENT_KINDS = frozenset({"normalized_parent"})


class V22ProjectionPersistenceRepositoryV1:
    """Identity/calendar/raw phase using only the V22 semantic-writer boundary."""

    def __init__(
        self,
        database_url: str,
        authority_verifier: ProjectionAuthorityVerifier,
        *,
        connect: Callable[..., Any] = psycopg.connect,
    ) -> None:
        if not database_url:
            raise ValueError("V22 semantic-writer database URL is required")
        if type(authority_verifier) is not ProjectionAuthorityVerifier:
            raise TypeError("V22 persistence requires a trusted authority verifier")
        self._database_url = database_url
        self._authority_verifier = authority_verifier
        self._connect = connect

    def read_only_preflight(self, foundation: ProjectionFoundation) -> ProjectionPreflightResult:
        return self._run(foundation, persist=False)

    def persist_exact(self, foundation: ProjectionFoundation) -> ProjectionPreflightResult:
        return self._run(foundation, persist=True)

    def _run(
        self, foundation: ProjectionFoundation, *, persist: bool
    ) -> ProjectionPreflightResult:
        _validated_foundation(foundation)
        if any(row.identity is None for row in foundation.manifest.rows):
            if persist:
                raise ProjectionContractViolation("Cannot persist an unresolved identity manifest")
            return _preflight_result(("FULL_191_UUID_TUPLE_PROJECTION_MISSING",), 0)
        _verify_projection_authority(foundation, self._authority_verifier)
        expected = _records_for_kinds(foundation, _V22_PROJECTION_KINDS)
        inserted = False
        missing: list[str] = []
        with self._connect(self._database_url, row_factory=dict_row) as connection:
            transaction = connection.transaction() if persist else nullcontext()
            with transaction:
                with connection.cursor() as cursor:
                    _attest_persistence_role(
                        cursor,
                        required_role=V22_PERSISTENCE_ROLE,
                        forbidden_role=V24_NORMALIZED_PARENT_PERSISTENCE_ROLE,
                    )
                    _verify_existing_msft_security(cursor, foundation)
                    for kind, key, record in expected:
                        observed = _select_projection_record(cursor, kind, key)
                        if observed is None and persist:
                            if kind == "security" and record["symbol"] == "MSFT":
                                raise ProjectionIntegrityConflict(
                                    "MSFT legacy public_id is not existing durable state"
                                )
                            _insert_projection_record(cursor, kind, record)
                            inserted = True
                            observed = _select_projection_record(cursor, kind, key)
                        if observed is None:
                            missing.append(f"{kind}:{key}")
                        elif (
                            kind == "security"
                            and record["symbol"] == "MSFT"
                            and _existing_security_identity_matches(
                                observed,
                                {
                                    "public_id": record["public_id"],
                                    "symbol": record["symbol"],
                                    "exchange": record["exchange"],
                                    "instrument_type": record["instrument_type"],
                                    "currency": record["currency"],
                                    "active": record["active"],
                                },
                            )
                        ):
                            continue
                        elif _normalized_record(kind, observed) != record:
                            raise ProjectionIntegrityConflict(
                                f"{kind} durable readback conflicts"
                            )
        if missing:
            return _preflight_result(tuple(missing), len(expected))
        return _phase_result(expected, inserted)


class V24NormalizedParentPersistenceRepositoryV1:
    """Normalized-parent phase using only the specialized V24 INSERT role."""

    def __init__(
        self,
        database_url: str,
        *,
        connect: Callable[..., Any] = psycopg.connect,
    ) -> None:
        if not database_url:
            raise ValueError("V24 normalized-parent writer database URL is required")
        self._database_url = database_url
        self._connect = connect

    def read_only_preflight(self, foundation: ProjectionFoundation) -> ProjectionPreflightResult:
        return self._run(foundation, persist=False)

    def persist_exact(self, foundation: ProjectionFoundation) -> ProjectionPreflightResult:
        return self._run(foundation, persist=True)

    def _run(
        self, foundation: ProjectionFoundation, *, persist: bool
    ) -> ProjectionPreflightResult:
        _validated_foundation(foundation)
        if any(row.identity is None for row in foundation.manifest.rows):
            if persist:
                raise ProjectionContractViolation("Cannot persist unresolved normalized parents")
            return _preflight_result(("FULL_191_UUID_TUPLE_PROJECTION_MISSING",), 0)
        expected = _records_for_kinds(foundation, _V24_NORMALIZED_PARENT_KINDS)
        inserted = False
        missing: list[str] = []
        with self._connect(self._database_url, row_factory=dict_row) as connection:
            transaction = connection.transaction() if persist else nullcontext()
            with transaction:
                with connection.cursor() as cursor:
                    _attest_persistence_role(
                        cursor,
                        required_role=V24_NORMALIZED_PARENT_PERSISTENCE_ROLE,
                        forbidden_role=V22_PERSISTENCE_ROLE,
                    )
                    for kind, key, record in expected:
                        observed = _select_projection_record(cursor, kind, key)
                        if observed is None and persist:
                            _insert_projection_record(cursor, kind, record)
                            inserted = True
                            observed = _select_projection_record(cursor, kind, key)
                        if observed is None:
                            missing.append(f"{kind}:{key}")
                        elif _normalized_record(kind, observed) != record:
                            raise ProjectionIntegrityConflict(
                                "normalized_parent durable readback conflicts"
                            )
        if missing:
            return _preflight_result(tuple(missing), len(expected))
        return _phase_result(expected, inserted)


class ProjectionPersistenceCoordinatorV1:
    """Two-role idempotent coordinator; it never shares one production connection."""

    def __init__(
        self,
        v22_repository: V22ProjectionPersistenceRepositoryV1,
        v24_repository: V24NormalizedParentPersistenceRepositoryV1,
    ) -> None:
        if (
            type(v22_repository) is not V22ProjectionPersistenceRepositoryV1
            or type(v24_repository) is not V24NormalizedParentPersistenceRepositoryV1
        ):
            raise TypeError("Projection persistence requires exact phase repositories")
        if v22_repository._database_url == v24_repository._database_url:
            raise ValueError("Projection persistence requires distinct role credentials")
        self._v22 = v22_repository
        self._v24 = v24_repository

    def read_only_preflight(self, foundation: ProjectionFoundation) -> ProjectionPreflightResult:
        return _combine_phase_results(
            self._v22.read_only_preflight(foundation),
            self._v24.read_only_preflight(foundation),
        )

    def persist_exact(self, foundation: ProjectionFoundation) -> ProjectionPreflightResult:
        first = self._v22.persist_exact(foundation)
        if first.state not in {
            ProjectionPersistenceState.EXACT_REPLAY,
            ProjectionPersistenceState.INSERTED_AND_VERIFIED,
        }:
            raise ProjectionIntegrityConflict("V22 projection phase is incomplete")
        second = self._v24.persist_exact(foundation)
        return _combine_phase_results(first, second)

    def readback_exact(self, foundation: ProjectionFoundation) -> ProjectionPreflightResult:
        result = self.read_only_preflight(foundation)
        if result.state is not ProjectionPersistenceState.EXACT_REPLAY:
            raise ProjectionIntegrityConflict("Projection foundation readback is incomplete")
        return result


def _phase_result(
    expected: list[tuple[str, object, dict[str, object]]], inserted: bool
) -> ProjectionPreflightResult:
    return ProjectionPreflightResult(
        state=(
            ProjectionPersistenceState.INSERTED_AND_VERIFIED
            if inserted
            else ProjectionPersistenceState.EXACT_REPLAY
        ),
        missing_objects=(),
        checked_object_count=len(expected),
        content_hash=_canonical_hash([record for _, _, record in expected]),
    )


def _combine_phase_results(
    first: ProjectionPreflightResult,
    second: ProjectionPreflightResult,
) -> ProjectionPreflightResult:
    missing = (*first.missing_objects, *second.missing_objects)
    inserted = ProjectionPersistenceState.INSERTED_AND_VERIFIED in {first.state, second.state}
    return ProjectionPreflightResult(
        state=(
            ProjectionPersistenceState.MISSING
            if missing
            else ProjectionPersistenceState.INSERTED_AND_VERIFIED
            if inserted
            else ProjectionPersistenceState.EXACT_REPLAY
        ),
        missing_objects=tuple(missing),
        checked_object_count=first.checked_object_count + second.checked_object_count,
        content_hash=_canonical_hash(
            {"v22": first.content_hash, "v24": second.content_hash}
        ),
    )


def _preflight_result(missing: tuple[str, ...], checked: int) -> ProjectionPreflightResult:
    return ProjectionPreflightResult(
        state=(
            ProjectionPersistenceState.MISSING
            if missing
            else ProjectionPersistenceState.EXACT_REPLAY
        ),
        missing_objects=missing,
        checked_object_count=checked,
        content_hash=_canonical_hash({"missing": missing, "checked": checked}),
    )


def _foundation_records(
    foundation: ProjectionFoundation,
) -> list[tuple[str, object, dict[str, object]]]:
    records: list[tuple[str, object, dict[str, object]]] = []
    provider_contracts: dict[str, dict[str, object]] = {}
    for raw in foundation.raw_manifests:
        contract = {
            "provider_code": raw.provider_code,
            "provider_contract_version": raw.provider_contract_version,
            "licensing_classification": raw.licensing_classification,
            "status": "ACTIVE",
        }
        prior = provider_contracts.setdefault(raw.provider_code, contract)
        if prior != contract:
            raise ProjectionContractViolation("Provider contract lineage is ambiguous")
    for code, record in sorted(provider_contracts.items()):
        records.append(("provider_contract", code, record))
    for row in foundation.manifest.rows:
        assert row.identity is not None
        identity = row.identity
        records.extend(
            (
                (
                    "security",
                    identity.security_id,
                    {
                        "public_id": identity.security_id,
                        "symbol": identity.symbol,
                        "exchange": identity.exchange_code,
                        "name": identity.legal_name,
                        "instrument_type": "COMMON_STOCK",
                        "currency": identity.currency,
                        "active": True,
                    },
                ),
                (
                    "company",
                    identity.company_id,
                    {
                        "company_id": identity.company_id,
                        "registry_version": IDENTITY_REGISTRY_VERSION,
                    },
                ),
                (
                    "instrument",
                    identity.instrument_id,
                    {
                        "instrument_id": identity.instrument_id,
                        "company_id": identity.company_id,
                        "registry_version": IDENTITY_REGISTRY_VERSION,
                    },
                ),
                (
                    "share_class",
                    identity.share_class_id,
                    {
                        "share_class_id": identity.share_class_id,
                        "instrument_id": identity.instrument_id,
                        "registry_version": IDENTITY_REGISTRY_VERSION,
                    },
                ),
                (
                    "listing",
                    identity.listing_id,
                    {
                        "listing_id": identity.listing_id,
                        "share_class_id": identity.share_class_id,
                        "security_id": identity.security_id,
                        "mic": identity.mic,
                        "currency": identity.currency,
                        "registry_version": IDENTITY_REGISTRY_VERSION,
                    },
                ),
                (
                    "ticker",
                    identity.ticker_assignment_id,
                    {
                        "ticker_assignment_id": identity.ticker_assignment_id,
                        "listing_id": identity.listing_id,
                        "ticker": identity.symbol,
                        "valid_from": identity.valid_from,
                        "valid_to": None,
                        "registry_version": IDENTITY_REGISTRY_VERSION,
                    },
                ),
            )
        )
    for session in foundation.completed_sessions:
        records.append(
            (
                "calendar",
                (session.calendar_id, session.calendar_version),
                {
                    "calendar_id": session.calendar_id,
                    "calendar_version": session.calendar_version,
                    "mic": session.mic,
                    "timezone": session.timezone,
                    "calendar_content_hash": session.calendar_content_hash,
                },
            )
        )
        records.append(
            (
                "completed_session",
                session.completed_session_id,
                {
                    "id": session.completed_session_id,
                    "calendar_id": session.calendar_id,
                    "calendar_version": session.calendar_version,
                    "mic": session.mic,
                    "session_date": session.session_date,
                    "timezone": session.timezone,
                    "scheduled_open": session.scheduled_open,
                    "scheduled_close": session.scheduled_close,
                    "early_close": session.early_close,
                    "status": "COMPLETED",
                    "completed_at": session.completed_at,
                    "session_content_hash": session.session_content_hash,
                    "recorded_at": session.recorded_at,
                },
            )
        )
    for raw in foundation.raw_manifests:
        records.append(
            (
                "raw_manifest",
                raw.raw_manifest_id,
                {
                    "id": raw.raw_manifest_id,
                    "provider_code": raw.provider_code,
                    "provider_schema_version": raw.provider_schema_version,
                    "source_record_id": raw.source_record_id,
                    "source_revision": raw.source_revision,
                    "source_content_hash": raw.source_content_hash,
                    "storage_class": "PRIVATE_GIT_IGNORED",
                    "payload_stored_in_git": False,
                    "storage_reference": raw.storage_reference,
                    "effective_at": raw.effective_at,
                    "available_at": raw.available_at,
                    "retrieved_at": raw.retrieved_at,
                    "ingested_at": raw.ingested_at,
                },
            )
        )
    for item in foundation.normalized_parents:
        records.append(
            (
                "normalized_parent",
                item.normalized_parent_id,
                {
                    "normalized_parent_id": item.normalized_parent_id,
                    "security_id": item.identity.security_id,
                    "company_id": item.identity.company_id,
                    "instrument_id": item.identity.instrument_id,
                    "share_class_id": item.identity.share_class_id,
                    "listing_id": item.identity.listing_id,
                    "ticker_assignment_id": item.identity.ticker_assignment_id,
                    "raw_manifest_id": item.raw_manifest_id,
                    "canonical_field_code": item.canonical_field_code,
                    "numeric_value": item.numeric_value,
                    "period_start": item.period_start,
                    "period_end": item.period_end,
                    "source_content_hash": item.source_content_hash,
                    "normalized_record_hash": item.normalized_record_hash,
                    "provider_code": item.provider_code,
                    "provider_schema_version": item.provider_schema_version,
                    "source_record_id": item.source_record_id,
                    "source_revision": item.source_revision,
                    "effective_at": item.effective_at,
                    "available_at": item.available_at,
                    "ingested_at": item.ingested_at,
                    "currency": item.currency,
                    "unit": item.unit,
                },
            )
        )
    return records


def _records_for_kinds(
    foundation: ProjectionFoundation,
    kinds: frozenset[str],
) -> list[tuple[str, object, dict[str, object]]]:
    return [record for record in _foundation_records(foundation) if record[0] in kinds]


def _attest_persistence_role(
    cursor: Any,
    *,
    required_role: str,
    forbidden_role: str,
) -> str:
    cursor.execute(
        "/* fv_stage8c:attest-role */ "
        "SELECT current_user AS current_user, "
        "pg_has_role(current_user,%(required_role)s,'MEMBER') AS has_required_role, "
        "pg_has_role(current_user,%(forbidden_role)s,'MEMBER') AS has_forbidden_role",
        {"required_role": required_role, "forbidden_role": forbidden_role},
    )
    observed = cursor.fetchone()
    if (
        type(observed) is not dict
        or type(observed.get("current_user")) is not str
        or observed["current_user"] != required_role
        or observed.get("has_required_role") is not True
        or observed.get("has_forbidden_role") is not False
    ):
        raise ProjectionIntegrityConflict(
            f"Persistence connection does not attest exact isolated {required_role}"
        )
    return observed["current_user"]


def _verify_existing_msft_security(cursor: Any, foundation: ProjectionFoundation) -> None:
    msft = next(row for row in foundation.manifest.rows if row.symbol == "MSFT")
    assert msft.identity is not None
    cursor.execute(
        "/* fv_stage8c:select-security-symbol */ "
        "SELECT public_id,symbol,exchange,name,instrument_type,currency,active "
        "FROM analytics.security WHERE symbol=%(symbol)s",
        {"symbol": "MSFT"},
    )
    observed = cursor.fetchone()
    expected_identity = {
        "public_id": msft.identity.security_id,
        "symbol": "MSFT",
        "exchange": MIC_TO_SECURITY_EXCHANGE[msft.mic],
        "instrument_type": "COMMON_STOCK",
        "currency": "USD",
        "active": True,
    }
    if observed is None or not _existing_security_identity_matches(
        observed, expected_identity
    ):
        raise ProjectionIntegrityConflict(
            "MSFT legacy public_id must be exact existing analytics.security readback"
        )


def _existing_security_identity_matches(
    observed: Mapping[str, object], expected_identity: Mapping[str, object]
) -> bool:
    """Compare immutable identity terms without overwriting an existing display name."""

    normalized = _normalized_record("security", observed)
    return all(normalized.get(key) == value for key, value in expected_identity.items())


_SELECTS = {
    "security": "SELECT public_id,symbol,exchange,name,instrument_type,currency,active FROM analytics.security WHERE public_id=%(key)s",
    "company": "SELECT company_id,registry_version FROM analytics.evidence_company_identity_v1 WHERE company_id=%(key)s",
    "instrument": "SELECT instrument_id,company_id,registry_version FROM analytics.evidence_instrument_identity_v1 WHERE instrument_id=%(key)s",
    "share_class": "SELECT share_class_id,instrument_id,registry_version FROM analytics.evidence_share_class_identity_v1 WHERE share_class_id=%(key)s",
    "listing": "SELECT listing_id,share_class_id,security_id,mic,currency,registry_version FROM analytics.evidence_listing_identity_v1 WHERE listing_id=%(key)s",
    "ticker": "SELECT ticker_assignment_id,listing_id,ticker,valid_from,valid_to,registry_version FROM analytics.evidence_ticker_assignment_v1 WHERE ticker_assignment_id=%(key)s",
    "calendar": "SELECT calendar_id,calendar_version,mic,timezone,calendar_content_hash FROM analytics.evidence_trading_calendar_v1 WHERE calendar_id=%(calendar_id)s AND calendar_version=%(calendar_version)s",
    "completed_session": "SELECT id,calendar_id,calendar_version,mic,session_date,timezone,scheduled_open,scheduled_close,early_close,status,completed_at,session_content_hash,recorded_at FROM analytics.evidence_completed_session_v1 WHERE id=%(key)s",
    "provider_contract": "SELECT provider_code,provider_contract_version,licensing_classification,status FROM analytics.evidence_provider_contract_v1 WHERE provider_code=%(key)s",
    "raw_manifest": "SELECT id,provider_code,provider_schema_version,source_record_id,source_revision,source_content_hash,storage_class,payload_stored_in_git,storage_reference,effective_at,available_at,retrieved_at,ingested_at FROM analytics.evidence_raw_manifest_v1 WHERE id=%(key)s",
    "normalized_parent": "SELECT normalized_parent_id,security_id,company_id,instrument_id,share_class_id,listing_id,ticker_assignment_id,raw_manifest_id,canonical_field_code,numeric_value,period_start,period_end,source_content_hash,normalized_record_hash,provider_code,provider_schema_version,source_record_id,source_revision,effective_at,available_at,ingested_at,currency,unit FROM analytics.fv_cq_forward_normalized_parent_v1 WHERE normalized_parent_id=%(key)s",
}

_INSERTS = {
    "security": "INSERT INTO analytics.security (public_id,symbol,exchange,name,instrument_type,currency,active) VALUES (%(public_id)s,%(symbol)s,%(exchange)s,%(name)s,%(instrument_type)s,%(currency)s,%(active)s) ON CONFLICT DO NOTHING",
    "company": "INSERT INTO analytics.evidence_company_identity_v1 (company_id,registry_version) VALUES (%(company_id)s,%(registry_version)s) ON CONFLICT DO NOTHING",
    "instrument": "INSERT INTO analytics.evidence_instrument_identity_v1 (instrument_id,company_id,registry_version) VALUES (%(instrument_id)s,%(company_id)s,%(registry_version)s) ON CONFLICT DO NOTHING",
    "share_class": "INSERT INTO analytics.evidence_share_class_identity_v1 (share_class_id,instrument_id,registry_version) VALUES (%(share_class_id)s,%(instrument_id)s,%(registry_version)s) ON CONFLICT DO NOTHING",
    "listing": "INSERT INTO analytics.evidence_listing_identity_v1 (listing_id,share_class_id,security_id,mic,currency,registry_version) VALUES (%(listing_id)s,%(share_class_id)s,%(security_id)s,%(mic)s,%(currency)s,%(registry_version)s) ON CONFLICT DO NOTHING",
    "ticker": "INSERT INTO analytics.evidence_ticker_assignment_v1 (ticker_assignment_id,listing_id,ticker,valid_from,valid_to,registry_version) VALUES (%(ticker_assignment_id)s,%(listing_id)s,%(ticker)s,%(valid_from)s,%(valid_to)s,%(registry_version)s) ON CONFLICT DO NOTHING",
    "calendar": "INSERT INTO analytics.evidence_trading_calendar_v1 (calendar_id,calendar_version,mic,timezone,calendar_content_hash) VALUES (%(calendar_id)s,%(calendar_version)s,%(mic)s,%(timezone)s,%(calendar_content_hash)s) ON CONFLICT DO NOTHING",
    "completed_session": "INSERT INTO analytics.evidence_completed_session_v1 (id,calendar_id,calendar_version,mic,session_date,timezone,scheduled_open,scheduled_close,early_close,status,completed_at,session_content_hash,recorded_at) VALUES (%(id)s,%(calendar_id)s,%(calendar_version)s,%(mic)s,%(session_date)s,%(timezone)s,%(scheduled_open)s,%(scheduled_close)s,%(early_close)s,%(status)s,%(completed_at)s,%(session_content_hash)s,%(recorded_at)s) ON CONFLICT DO NOTHING",
    "provider_contract": "INSERT INTO analytics.evidence_provider_contract_v1 (provider_code,provider_contract_version,licensing_classification,status) VALUES (%(provider_code)s,%(provider_contract_version)s,%(licensing_classification)s,%(status)s) ON CONFLICT DO NOTHING",
    "raw_manifest": "INSERT INTO analytics.evidence_raw_manifest_v1 (id,provider_code,provider_schema_version,source_record_id,source_revision,source_content_hash,storage_class,payload_stored_in_git,storage_reference,effective_at,available_at,retrieved_at,ingested_at) VALUES (%(id)s,%(provider_code)s,%(provider_schema_version)s,%(source_record_id)s,%(source_revision)s,%(source_content_hash)s,%(storage_class)s,%(payload_stored_in_git)s,%(storage_reference)s,%(effective_at)s,%(available_at)s,%(retrieved_at)s,%(ingested_at)s) ON CONFLICT DO NOTHING",
    "normalized_parent": "INSERT INTO analytics.fv_cq_forward_normalized_parent_v1 (normalized_parent_id,security_id,company_id,instrument_id,share_class_id,listing_id,ticker_assignment_id,raw_manifest_id,canonical_field_code,numeric_value,period_start,period_end,source_content_hash,normalized_record_hash,provider_code,provider_schema_version,source_record_id,source_revision,effective_at,available_at,ingested_at,currency,unit) VALUES (%(normalized_parent_id)s,%(security_id)s,%(company_id)s,%(instrument_id)s,%(share_class_id)s,%(listing_id)s,%(ticker_assignment_id)s,%(raw_manifest_id)s,%(canonical_field_code)s,%(numeric_value)s,%(period_start)s,%(period_end)s,%(source_content_hash)s,%(normalized_record_hash)s,%(provider_code)s,%(provider_schema_version)s,%(source_record_id)s,%(source_revision)s,%(effective_at)s,%(available_at)s,%(ingested_at)s,%(currency)s,%(unit)s) ON CONFLICT DO NOTHING",
}


def _select_projection_record(cursor: Any, kind: str, key: object) -> Mapping[str, object] | None:
    params = (
        {"calendar_id": key[0], "calendar_version": key[1]} if kind == "calendar" else {"key": key}
    )
    cursor.execute(f"/* fv_stage8c:select:{kind} */ {_SELECTS[kind]}", params)
    return cursor.fetchone()


def _insert_projection_record(cursor: Any, kind: str, record: dict[str, object]) -> None:
    cursor.execute(f"/* fv_stage8c:insert:{kind} */ {_INSERTS[kind]}", record)


def _normalized_record(kind: str, record: Mapping[str, object]) -> dict[str, object]:
    normalized: dict[str, object] = {}
    for key in record:
        value = record[key]
        if isinstance(value, datetime):
            value = _instant(value, f"{kind}.{key}")
        elif isinstance(value, Decimal):
            value = Decimal(canonical_decimal_text(value))
        elif isinstance(value, str) and key in {"mic", "currency"}:
            value = value.strip()
        normalized[key] = value
    return normalized
