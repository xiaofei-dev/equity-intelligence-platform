"""Offline Stage 8C v1.6 SEC corroboration and target-inventory contract.

This module freezes two future read-only operations without performing either:

* one official SEC company/ticker/exchange file request; and
* one target PostgreSQL identity inventory query.

The scope is exactly GOOG, FOX, and MSFT.  A successful SEC review can support
only the frozen ``Nasdaq`` to ``XNAS`` operating-MIC normalization.  It cannot
establish a Nasdaq segment, tier, history, listing FIGI, currency, completed
session, or a writable V22/V24 identity projection.  The database inventory is
read-only and never generates or inserts an identifier.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import Any

CONTRACT_VERSION = "FV-STAGE8C-SEC-DB-INVENTORY-v1.6.0"
SEC_CONTRACT_VERSION = "FV-STAGE8C-SEC-EXCHANGE-CORROBORATION-v1.0.0"
INVENTORY_CONTRACT_VERSION = "FV-STAGE8C-TARGET-DB-INVENTORY-v1.0.0"
INVENTORY_ADOPTION_POLICY_VERSION = "FV-STAGE8C-TARGET-DB-ADOPTION-v1.1.0"
INVENTORY_AS_OF_DATE = "2026-08-02"
PROJECTION_RULING_VERSION = "FV-STAGE8C-IDENTITY-PROJECTION-RULING-v2.0.0"

SEC_URL = "https://www.sec.gov/files/company_tickers_exchange.json"
SEC_METHOD = "GET"
SEC_RETRY_LIMIT = 0
SEC_PHYSICAL_REQUEST_COUNT = 1
SEC_USER_AGENT_ENVIRONMENT_VARIABLE = "SEC_USER_AGENT"
SEC_USER_AGENT_PREFIX: None = None
SEC_USER_AGENT_POLICY = (
    "EXACT_VALIDATED_RUNTIME_VALUE_NO_TRANSFORMATION_NOT_PERSISTED_OR_HASHED"
)
SEC_RAW_CHECKPOINT_POLICY = "PRIVATE_GIT_IGNORED_HASH_BOUND_CHECKPOINT"

TARGET_TICKERS = ("GOOG", "FOX", "MSFT")
SEC_EXCHANGE_VALUE = "Nasdaq"
CANONICAL_OPERATING_MIC = "XNAS"
SEC_MAPPING_CLAIM = "CURRENT_OPERATING_MIC_CORROBORATION_ONLY"
ACCEPTED_LEGACY_SECURITY_EXCHANGES = ("NASDAQ", "XNAS")
REQUIRED_SECURITY_INSTRUMENT_TYPE = "COMMON_STOCK"
REQUIRED_SECURITY_CURRENCY = "USD"
REQUIRED_LISTING_CURRENCY = "USD"
CURRENT_TICKER_RULE = "VALID_FROM_LE_AS_OF_LT_VALID_TO_OR_OPEN_ENDED"

PREDECESSOR_V15_DECISION_CODE = (
    "US_COMPOSITE_DIAGNOSTIC_COMPLETE_CONVERGENT"
)
PREDECESSOR_V15_PLAN_CONTENT_HASH = (
    "F7F2E728FB4B91D9FA7E9B7F63B5E38259655B7B64D798BD63BE54DCA187FB40"
)
PREDECESSOR_V15_REVIEW_CONTENT_HASH = (
    "E53CF93A88523B8F91F5F84AB59FD230F5335E218970B87FB77321BF1AA57747"
)
PREDECESSOR_V15_CHECKPOINT_RECEIPT_SET_HASH = (
    "4BE2E3926EB0EDC823CC90A937AB647F1A9F0C8C05D913E4E65DE5C767374CF9"
)
PREDECESSOR_V15_REPLAY_VERIFICATION_HASH = (
    "66564E8FC3E08D3D2E15EB387534B956A85F1FF1AA40614597D11ED381A25128"
)
PREDECESSOR_V15_DIAGNOSTIC_ACCEPTANCE_HASH = (
    "FFF937E1AB4646440946E3E9571610996B6A8809183765B578908BDCE03156A7"
)
PREDECESSOR_V15_STORAGE_ACCEPTANCE_HASH = (
    "35F466820289ACDF9FF427327E5B03020F6A920BFCE7A0D52BD4E472CFD4492B"
)
PREDECESSOR_V15_RESULT_ARTIFACT_CANONICAL_HASH = (
    "AD83ACD175AFA01D706D689EE48B93233BB8D95D6B494655B7E15337B5FDC6B7"
)

PROJECTION_V1_STATUS = "INCOMPATIBLE"
SUCCESSOR_REQUIREMENT = "PROJECTION_V2_AND_APPEND_ONLY_V25_REQUIRED"
REAL_PROJECTION_AUTHORIZED = False
NETWORK_AUTHORIZED = False
DATABASE_READ_AUTHORIZED = False
DATABASE_WRITE_AUTHORIZED = False

_UPPER_SHA256 = re.compile(r"[0-9A-F]{64}\Z")
_TICKER = re.compile(r"[A-Z][A-Z0-9.-]{0,31}\Z")
_UUID = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-"
    r"[89ab][0-9a-f]{3}-[0-9a-f]{12}\Z"
)
_ISO_DATE = re.compile(r"\d{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])\Z")
_UTC_SECOND = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z\Z")
_CIK = re.compile(r"[0-9]{10}\Z")
_SAFE_TEXT = re.compile(r"[^\x00\r\n]{1,512}\Z")
_FORBIDDEN_SQL = re.compile(
    r"\b(?:INSERT|UPDATE|DELETE|MERGE|TRUNCATE|ALTER|CREATE|DROP|GRANT|REVOKE|CALL|COPY)\b",
    re.IGNORECASE,
)


class Stage8CV16Stop(RuntimeError):
    """Fail-closed v1.6 stop with a stable code."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class InventoryAdoptionState(StrEnum):
    """Read-only identity disposition for one target ticker."""

    ADOPT_EXISTING_V22_GRAPH = "ADOPT_EXISTING_V22_GRAPH"
    ADOPT_EXISTING_PUBLIC_ID_V22_GRAPH_REQUIRED = (
        "ADOPT_EXISTING_PUBLIC_ID_V22_GRAPH_REQUIRED"
    )
    NEW_ID_CANDIDATE = "NEW_ID_CANDIDATE"
    CONFLICT = "CONFLICT"


@dataclass(frozen=True)
class SecRequestContractV16:
    contract_version: str
    method: str
    url: str
    physical_request_count: int
    retry_limit: int
    target_tickers: tuple[str, ...]
    user_agent_environment_variable: str
    user_agent_prefix: None
    user_agent_policy: str
    raw_checkpoint_policy: str
    network_authorized: bool
    content_hash: str


@dataclass(frozen=True)
class SecWireRequestV16:
    method: str
    url: str
    headers: tuple[tuple[str, str], ...]
    retry_limit: int


@dataclass(frozen=True)
class SecCorroborationRecordV16:
    target_ordinal: int
    ticker: str
    cik: str
    name: str
    provider_exchange: str
    canonical_operating_mic: str | None
    mapping_supported: bool
    content_hash: str


@dataclass(frozen=True)
class SecCorroborationReviewV16:
    request_content_hash: str
    records: tuple[SecCorroborationRecordV16, ...]
    unique_target_count: int
    supported_mapping_count: int
    accepted: bool
    claim: str
    segment_claimed: bool
    tier_claimed: bool
    exchange_history_claimed: bool
    listing_figi_claimed: bool
    currency_claimed: bool
    completed_session_claimed: bool
    content_hash: str


@dataclass(frozen=True)
class InventoryRowV16:
    target_ordinal: int
    target_ticker: str
    security_internal_id: str | None
    security_public_id: str | None
    security_symbol: str | None
    security_exchange: str | None
    security_name: str | None
    security_instrument_type: str | None
    security_currency: str | None
    security_active: bool | None
    company_id: str | None
    company_registry_version: str | None
    company_recorded_at: str | None
    instrument_id: str | None
    instrument_company_id: str | None
    instrument_registry_version: str | None
    instrument_recorded_at: str | None
    share_class_id: str | None
    share_class_instrument_id: str | None
    share_class_registry_version: str | None
    share_class_recorded_at: str | None
    listing_id: str | None
    listing_share_class_id: str | None
    listing_security_id: str | None
    listing_mic: str | None
    listing_currency: str | None
    listing_registry_version: str | None
    listing_recorded_at: str | None
    ticker_assignment_id: str | None
    ticker_listing_id: str | None
    ticker: str | None
    ticker_valid_from: str | None
    ticker_valid_to: str | None
    ticker_registry_version: str | None
    ticker_recorded_at: str | None


@dataclass(frozen=True)
class TargetInventoryDecisionV16:
    target_ordinal: int
    ticker: str
    adoption_state: InventoryAdoptionState
    existing_public_id: str | None
    row_count: int
    security_count: int
    listing_count: int
    current_target_ticker_count: int
    reason_codes: tuple[str, ...]
    insert_authorized: bool
    update_authorized: bool
    content_hash: str


@dataclass(frozen=True)
class InventoryReviewV16:
    query_content_hash: str
    decisions: tuple[TargetInventoryDecisionV16, ...]
    adopt_existing_count: int
    new_id_candidate_count: int
    conflict_count: int
    read_only: bool
    projection_v1_status: str
    successor_requirement: str
    content_hash: str


@dataclass(frozen=True)
class DatabaseInventoryContractV16:
    contract_version: str
    target_tickers: tuple[str, ...]
    query_content_hash: str
    result_schema_fields: tuple[str, ...]
    adoption_policy_version: str
    inventory_as_of_date: str
    accepted_legacy_security_exchanges: tuple[str, ...]
    required_security_active: bool
    required_security_instrument_type: str
    required_security_currency: str
    required_listing_mic: str
    required_listing_currency: str
    registry_evidence_required: bool
    current_ticker_rule: str
    database_read_authorized: bool
    database_write_authorized: bool
    content_hash: str


@dataclass(frozen=True)
class Stage8CV16Contract:
    contract_version: str
    state: str
    predecessor_v15_decision_code: str
    predecessor_v15_plan_content_hash: str
    predecessor_v15_review_content_hash: str
    predecessor_v15_checkpoint_receipt_set_hash: str
    predecessor_v15_replay_verification_hash: str
    predecessor_v15_diagnostic_acceptance_hash: str
    predecessor_v15_storage_acceptance_hash: str
    predecessor_result_artifact_canonical_hash: str
    predecessor_result_artifact_binding_status: str
    sec_request: SecRequestContractV16
    database_inventory: DatabaseInventoryContractV16
    projection_v1_status: str
    successor_requirement: str
    real_projection_authorized: bool
    network_authorized: bool
    database_read_authorized: bool
    database_write_authorized: bool
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


def _require_hash(value: object, code: str) -> str:
    if type(value) is not str or _UPPER_SHA256.fullmatch(value) is None:
        raise Stage8CV16Stop(code)
    return value


def _require_text(value: object, *, maximum: int, code: str) -> str:
    if (
        type(value) is not str
        or not value
        or value != value.strip(" \t\n\r\f\v")
        or len(value) > maximum
        or _SAFE_TEXT.fullmatch(value) is None
    ):
        raise Stage8CV16Stop(code)
    return value


def _sec_request_body(value: SecRequestContractV16, *, include_hash: bool) -> dict[str, object]:
    body: dict[str, object] = {
        "contractVersion": value.contract_version,
        "method": value.method,
        "url": value.url,
        "physicalRequestCount": value.physical_request_count,
        "retryLimit": value.retry_limit,
        "targetTickers": list(value.target_tickers),
        "userAgentEnvironmentVariable": value.user_agent_environment_variable,
        "userAgentPrefix": value.user_agent_prefix,
        "userAgentPolicy": value.user_agent_policy,
        "rawCheckpointPolicy": value.raw_checkpoint_policy,
        "networkAuthorized": value.network_authorized,
    }
    if include_hash:
        body["contentHash"] = value.content_hash
    return body


def build_sec_request_contract_v16() -> SecRequestContractV16:
    provisional = SecRequestContractV16(
        contract_version=SEC_CONTRACT_VERSION,
        method=SEC_METHOD,
        url=SEC_URL,
        physical_request_count=SEC_PHYSICAL_REQUEST_COUNT,
        retry_limit=SEC_RETRY_LIMIT,
        target_tickers=TARGET_TICKERS,
        user_agent_environment_variable=SEC_USER_AGENT_ENVIRONMENT_VARIABLE,
        user_agent_prefix=SEC_USER_AGENT_PREFIX,
        user_agent_policy=SEC_USER_AGENT_POLICY,
        raw_checkpoint_policy=SEC_RAW_CHECKPOINT_POLICY,
        network_authorized=False,
        content_hash="",
    )
    result = SecRequestContractV16(
        **{
            **asdict(provisional),
            "target_tickers": provisional.target_tickers,
            "content_hash": canonical_hash(
                _sec_request_body(provisional, include_hash=False)
            ),
        }
    )
    validate_sec_request_contract_v16(result)
    return result


def validate_sec_request_contract_v16(value: SecRequestContractV16) -> None:
    if type(value) is not SecRequestContractV16:
        raise Stage8CV16Stop("SEC_REQUEST_CONTRACT_TYPE_INVALID")
    if type(value.target_tickers) is not tuple:
        raise Stage8CV16Stop("SEC_TARGET_TICKERS_MUST_BE_TUPLE")
    if (
        value.contract_version != SEC_CONTRACT_VERSION
        or value.method != SEC_METHOD
        or value.url != SEC_URL
        or type(value.physical_request_count) is not int
        or value.physical_request_count != 1
        or type(value.retry_limit) is not int
        or value.retry_limit != 0
        or value.target_tickers != TARGET_TICKERS
        or value.user_agent_environment_variable
        != SEC_USER_AGENT_ENVIRONMENT_VARIABLE
        or value.user_agent_prefix != SEC_USER_AGENT_PREFIX
        or value.user_agent_policy != SEC_USER_AGENT_POLICY
        or value.raw_checkpoint_policy != SEC_RAW_CHECKPOINT_POLICY
        or value.network_authorized is not False
        or _UPPER_SHA256.fullmatch(value.content_hash) is None
        or value.content_hash
        != canonical_hash(_sec_request_body(value, include_hash=False))
    ):
        raise Stage8CV16Stop("SEC_REQUEST_CONTRACT_DRIFT")


def validate_runtime_sec_user_agent_v16(value: object) -> str:
    text = _require_text(value, maximum=256, code="SEC_RUNTIME_USER_AGENT_INVALID")
    if any(ord(character) < 32 or ord(character) > 126 for character in text):
        raise Stage8CV16Stop("SEC_RUNTIME_USER_AGENT_PRINTABLE_ASCII_REQUIRED")
    if "@" not in text:
        raise Stage8CV16Stop("SEC_RUNTIME_USER_AGENT_CONTACT_REQUIRED")
    return text


def build_sec_wire_request_v16(runtime_user_agent: object) -> SecWireRequestV16:
    """Build a wire description; this function never performs transport."""

    user_agent = validate_runtime_sec_user_agent_v16(runtime_user_agent)
    return SecWireRequestV16(
        method=SEC_METHOD,
        url=SEC_URL,
        headers=(
            ("Accept", "application/json"),
            ("User-Agent", user_agent),
        ),
        retry_limit=0,
    )


def _strict_json_loads(value: bytes) -> object:
    def object_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, item in pairs:
            if key in result:
                raise Stage8CV16Stop("SEC_RESPONSE_JSON_DUPLICATE_KEY")
            result[key] = item
        return result

    def reject_constant(_: str) -> None:
        raise Stage8CV16Stop("SEC_RESPONSE_JSON_NONFINITE_CONSTANT")

    try:
        return json.loads(
            value.decode("utf-8"),
            object_pairs_hook=object_pairs,
            parse_constant=reject_constant,
        )
    except Stage8CV16Stop:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise Stage8CV16Stop("SEC_RESPONSE_JSON_INVALID") from error


def _sec_record_body(
    value: SecCorroborationRecordV16, *, include_hash: bool
) -> dict[str, object]:
    body: dict[str, object] = {
        "targetOrdinal": value.target_ordinal,
        "ticker": value.ticker,
        "cik": value.cik,
        "name": value.name,
        "providerExchange": value.provider_exchange,
        "canonicalOperatingMic": value.canonical_operating_mic,
        "mappingSupported": value.mapping_supported,
    }
    if include_hash:
        body["contentHash"] = value.content_hash
    return body


def _sec_review_body(
    value: SecCorroborationReviewV16, *, include_hash: bool
) -> dict[str, object]:
    body: dict[str, object] = {
        "requestContentHash": value.request_content_hash,
        "records": [_sec_record_body(item, include_hash=True) for item in value.records],
        "uniqueTargetCount": value.unique_target_count,
        "supportedMappingCount": value.supported_mapping_count,
        "accepted": value.accepted,
        "claim": value.claim,
        "segmentClaimed": value.segment_claimed,
        "tierClaimed": value.tier_claimed,
        "exchangeHistoryClaimed": value.exchange_history_claimed,
        "listingFigiClaimed": value.listing_figi_claimed,
        "currencyClaimed": value.currency_claimed,
        "completedSessionClaimed": value.completed_session_claimed,
    }
    if include_hash:
        body["contentHash"] = value.content_hash
    return body


def build_sec_corroboration_review_v16(
    response_body: bytes,
) -> SecCorroborationReviewV16:
    request = build_sec_request_contract_v16()
    if type(response_body) is not bytes:
        raise Stage8CV16Stop("SEC_RESPONSE_BODY_MUST_BE_BYTES")
    payload = _strict_json_loads(response_body)
    if type(payload) is not dict or set(payload) != {"fields", "data"}:
        raise Stage8CV16Stop("SEC_RESPONSE_ROOT_SCHEMA_INVALID")
    if payload["fields"] != ["cik", "name", "ticker", "exchange"]:
        raise Stage8CV16Stop("SEC_RESPONSE_FIELDS_INVALID")
    data = payload["data"]
    if type(data) is not list:
        raise Stage8CV16Stop("SEC_RESPONSE_DATA_INVALID")
    found: dict[str, tuple[str, str, str]] = {}
    for row in data:
        if type(row) is not list or len(row) != 4:
            raise Stage8CV16Stop("SEC_RESPONSE_ROW_SCHEMA_INVALID")
        cik_value, name_value, ticker_value, exchange_value = row
        if type(cik_value) is not int or cik_value <= 0 or cik_value > 9_999_999_999:
            raise Stage8CV16Stop("SEC_RESPONSE_CIK_INVALID")
        name = _require_text(name_value, maximum=512, code="SEC_RESPONSE_NAME_INVALID")
        ticker = _require_text(
            ticker_value, maximum=32, code="SEC_RESPONSE_TICKER_INVALID"
        )
        exchange = _require_text(
            exchange_value, maximum=64, code="SEC_RESPONSE_EXCHANGE_INVALID"
        )
        if _TICKER.fullmatch(ticker) is None:
            raise Stage8CV16Stop("SEC_RESPONSE_TICKER_INVALID")
        if ticker in TARGET_TICKERS:
            if ticker in found:
                raise Stage8CV16Stop("SEC_TARGET_TICKER_NOT_UNIQUE")
            found[ticker] = (f"{cik_value:010d}", name, exchange)
    if set(found) != set(TARGET_TICKERS):
        raise Stage8CV16Stop("SEC_TARGET_TICKER_SET_INCOMPLETE")
    records: list[SecCorroborationRecordV16] = []
    for ordinal, ticker in enumerate(TARGET_TICKERS, start=1):
        cik, name, exchange = found[ticker]
        supported = exchange == SEC_EXCHANGE_VALUE
        provisional = SecCorroborationRecordV16(
            target_ordinal=ordinal,
            ticker=ticker,
            cik=cik,
            name=name,
            provider_exchange=exchange,
            canonical_operating_mic=CANONICAL_OPERATING_MIC if supported else None,
            mapping_supported=supported,
            content_hash="",
        )
        records.append(
            SecCorroborationRecordV16(
                **{
                    **asdict(provisional),
                    "content_hash": canonical_hash(
                        _sec_record_body(provisional, include_hash=False)
                    ),
                }
            )
        )
    supported_count = sum(item.mapping_supported for item in records)
    provisional_review = SecCorroborationReviewV16(
        request_content_hash=request.content_hash,
        records=tuple(records),
        unique_target_count=len(records),
        supported_mapping_count=supported_count,
        accepted=supported_count == len(TARGET_TICKERS),
        claim=SEC_MAPPING_CLAIM,
        segment_claimed=False,
        tier_claimed=False,
        exchange_history_claimed=False,
        listing_figi_claimed=False,
        currency_claimed=False,
        completed_session_claimed=False,
        content_hash="",
    )
    result = SecCorroborationReviewV16(
        **{
            **asdict(provisional_review),
            "records": provisional_review.records,
            "content_hash": canonical_hash(
                _sec_review_body(provisional_review, include_hash=False)
            ),
        }
    )
    validate_sec_corroboration_review_v16(result)
    return result


def validate_sec_corroboration_review_v16(value: SecCorroborationReviewV16) -> None:
    request = build_sec_request_contract_v16()
    if type(value) is not SecCorroborationReviewV16:
        raise Stage8CV16Stop("SEC_REVIEW_TYPE_INVALID")
    if type(value.records) is not tuple or len(value.records) != len(TARGET_TICKERS):
        raise Stage8CV16Stop("SEC_REVIEW_RECORDS_INVALID")
    supported = 0
    for ordinal, (ticker, record) in enumerate(
        zip(TARGET_TICKERS, value.records, strict=True), start=1
    ):
        if type(record) is not SecCorroborationRecordV16:
            raise Stage8CV16Stop("SEC_REVIEW_RECORD_TYPE_INVALID")
        _require_text(
            record.name,
            maximum=512,
            code="SEC_REVIEW_RECORD_NAME_INVALID",
        )
        _require_text(
            record.provider_exchange,
            maximum=64,
            code="SEC_REVIEW_RECORD_EXCHANGE_INVALID",
        )
        mapping_supported = record.provider_exchange == SEC_EXCHANGE_VALUE
        if (
            type(record.target_ordinal) is not int
            or record.target_ordinal != ordinal
            or record.ticker != ticker
            or _CIK.fullmatch(record.cik) is None
            or type(record.mapping_supported) is not bool
            or record.mapping_supported is not mapping_supported
            or record.canonical_operating_mic
            != (CANONICAL_OPERATING_MIC if mapping_supported else None)
            or record.content_hash
            != canonical_hash(_sec_record_body(record, include_hash=False))
        ):
            raise Stage8CV16Stop("SEC_REVIEW_RECORD_DRIFT")
        supported += int(mapping_supported)
    if (
        value.request_content_hash != request.content_hash
        or value.unique_target_count != len(TARGET_TICKERS)
        or value.supported_mapping_count != supported
        or type(value.accepted) is not bool
        or value.accepted is not (supported == len(TARGET_TICKERS))
        or value.claim != SEC_MAPPING_CLAIM
        or value.segment_claimed is not False
        or value.tier_claimed is not False
        or value.exchange_history_claimed is not False
        or value.listing_figi_claimed is not False
        or value.currency_claimed is not False
        or value.completed_session_claimed is not False
        or value.content_hash
        != canonical_hash(_sec_review_body(value, include_hash=False))
    ):
        raise Stage8CV16Stop("SEC_REVIEW_DRIFT")


# This query is deliberately a single SELECT.  It inventories candidates found
# by either the legacy security symbol or any V22 ticker assignment and then
# returns every V22 ticker row for each connected listing.
TARGET_DATABASE_INVENTORY_QUERY_V16 = """WITH target(target_ordinal, target_ticker) AS (
    VALUES (1, 'GOOG'), (2, 'FOX'), (3, 'MSFT')
), candidate_security AS (
    SELECT t.target_ordinal, t.target_ticker, s.id AS security_internal_id
    FROM target t
    JOIN analytics.security s ON s.symbol = t.target_ticker
    UNION
    SELECT t.target_ordinal, t.target_ticker, s.id AS security_internal_id
    FROM target t
    JOIN analytics.evidence_ticker_assignment_v1 ta ON ta.ticker = t.target_ticker
    JOIN analytics.evidence_listing_identity_v1 l ON l.listing_id = ta.listing_id
    JOIN analytics.security s ON s.public_id = l.security_id
)
SELECT
    t.target_ordinal AS "targetOrdinal",
    t.target_ticker AS "targetTicker",
    s.id::text AS "securityInternalId",
    s.public_id::text AS "securityPublicId",
    s.symbol AS "securitySymbol",
    s.exchange AS "securityExchange",
    s.name AS "securityName",
    s.instrument_type AS "securityInstrumentType",
    s.currency AS "securityCurrency",
    s.active AS "securityActive",
    c.company_id::text AS "companyId",
    c.registry_version AS "companyRegistryVersion",
    to_char(
        c.recorded_at AT TIME ZONE 'UTC',
        'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"'
    ) AS "companyRecordedAt",
    i.instrument_id::text AS "instrumentId",
    i.company_id::text AS "instrumentCompanyId",
    i.registry_version AS "instrumentRegistryVersion",
    to_char(
        i.recorded_at AT TIME ZONE 'UTC',
        'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"'
    ) AS "instrumentRecordedAt",
    sc.share_class_id::text AS "shareClassId",
    sc.instrument_id::text AS "shareClassInstrumentId",
    sc.registry_version AS "shareClassRegistryVersion",
    to_char(
        sc.recorded_at AT TIME ZONE 'UTC',
        'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"'
    ) AS "shareClassRecordedAt",
    l.listing_id::text AS "listingId",
    l.share_class_id::text AS "listingShareClassId",
    l.security_id::text AS "listingSecurityId",
    l.mic AS "listingMic",
    l.currency AS "listingCurrency",
    l.registry_version AS "listingRegistryVersion",
    to_char(
        l.recorded_at AT TIME ZONE 'UTC',
        'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"'
    ) AS "listingRecordedAt",
    ta.ticker_assignment_id::text AS "tickerAssignmentId",
    ta.listing_id::text AS "tickerListingId",
    ta.ticker AS "ticker",
    to_char(ta.valid_from, 'YYYY-MM-DD') AS "tickerValidFrom",
    CASE WHEN ta.valid_to IS NULL
        THEN NULL
        ELSE to_char(ta.valid_to, 'YYYY-MM-DD')
    END AS "tickerValidTo",
    ta.registry_version AS "tickerRegistryVersion",
    to_char(
        ta.recorded_at AT TIME ZONE 'UTC',
        'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"'
    ) AS "tickerRecordedAt"
FROM target t
LEFT JOIN candidate_security cs
  ON cs.target_ordinal = t.target_ordinal AND cs.target_ticker = t.target_ticker
LEFT JOIN analytics.security s ON s.id = cs.security_internal_id
LEFT JOIN analytics.evidence_listing_identity_v1 l ON l.security_id = s.public_id
LEFT JOIN analytics.evidence_share_class_identity_v1 sc ON sc.share_class_id = l.share_class_id
LEFT JOIN analytics.evidence_instrument_identity_v1 i ON i.instrument_id = sc.instrument_id
LEFT JOIN analytics.evidence_company_identity_v1 c ON c.company_id = i.company_id
LEFT JOIN analytics.evidence_ticker_assignment_v1 ta ON ta.listing_id = l.listing_id
ORDER BY t.target_ordinal, s.public_id, l.listing_id, ta.valid_from, ta.ticker_assignment_id
"""


INVENTORY_RESULT_SCHEMA_FIELDS = (
    "targetOrdinal",
    "targetTicker",
    "securityInternalId",
    "securityPublicId",
    "securitySymbol",
    "securityExchange",
    "securityName",
    "securityInstrumentType",
    "securityCurrency",
    "securityActive",
    "companyId",
    "companyRegistryVersion",
    "companyRecordedAt",
    "instrumentId",
    "instrumentCompanyId",
    "instrumentRegistryVersion",
    "instrumentRecordedAt",
    "shareClassId",
    "shareClassInstrumentId",
    "shareClassRegistryVersion",
    "shareClassRecordedAt",
    "listingId",
    "listingShareClassId",
    "listingSecurityId",
    "listingMic",
    "listingCurrency",
    "listingRegistryVersion",
    "listingRecordedAt",
    "tickerAssignmentId",
    "tickerListingId",
    "ticker",
    "tickerValidFrom",
    "tickerValidTo",
    "tickerRegistryVersion",
    "tickerRecordedAt",
)


def _inventory_contract_body(
    value: DatabaseInventoryContractV16, *, include_hash: bool
) -> dict[str, object]:
    body: dict[str, object] = {
        "contractVersion": value.contract_version,
        "targetTickers": list(value.target_tickers),
        "queryContentHash": value.query_content_hash,
        "resultSchemaFields": list(value.result_schema_fields),
        "adoptionPolicy": {
            "version": value.adoption_policy_version,
            "inventoryAsOfDate": value.inventory_as_of_date,
            "acceptedLegacySecurityExchanges": list(
                value.accepted_legacy_security_exchanges
            ),
            "requiredSecurityActive": value.required_security_active,
            "requiredSecurityInstrumentType": (
                value.required_security_instrument_type
            ),
            "requiredSecurityCurrency": value.required_security_currency,
            "requiredListingMic": value.required_listing_mic,
            "requiredListingCurrency": value.required_listing_currency,
            "registryEvidenceRequired": value.registry_evidence_required,
            "currentTickerRule": value.current_ticker_rule,
        },
        "databaseReadAuthorized": value.database_read_authorized,
        "databaseWriteAuthorized": value.database_write_authorized,
    }
    if include_hash:
        body["contentHash"] = value.content_hash
    return body


def build_database_inventory_contract_v16() -> DatabaseInventoryContractV16:
    query_hash = hashlib.sha256(
        TARGET_DATABASE_INVENTORY_QUERY_V16.encode("utf-8")
    ).hexdigest().upper()
    provisional = DatabaseInventoryContractV16(
        contract_version=INVENTORY_CONTRACT_VERSION,
        target_tickers=TARGET_TICKERS,
        query_content_hash=query_hash,
        result_schema_fields=INVENTORY_RESULT_SCHEMA_FIELDS,
        adoption_policy_version=INVENTORY_ADOPTION_POLICY_VERSION,
        inventory_as_of_date=INVENTORY_AS_OF_DATE,
        accepted_legacy_security_exchanges=ACCEPTED_LEGACY_SECURITY_EXCHANGES,
        required_security_active=True,
        required_security_instrument_type=REQUIRED_SECURITY_INSTRUMENT_TYPE,
        required_security_currency=REQUIRED_SECURITY_CURRENCY,
        required_listing_mic=CANONICAL_OPERATING_MIC,
        required_listing_currency=REQUIRED_LISTING_CURRENCY,
        registry_evidence_required=True,
        current_ticker_rule=CURRENT_TICKER_RULE,
        database_read_authorized=False,
        database_write_authorized=False,
        content_hash="",
    )
    result = DatabaseInventoryContractV16(
        **{
            **asdict(provisional),
            "target_tickers": provisional.target_tickers,
            "result_schema_fields": provisional.result_schema_fields,
            "accepted_legacy_security_exchanges": (
                provisional.accepted_legacy_security_exchanges
            ),
            "content_hash": canonical_hash(
                _inventory_contract_body(provisional, include_hash=False)
            ),
        }
    )
    validate_database_inventory_contract_v16(result)
    return result


def validate_database_inventory_contract_v16(
    value: DatabaseInventoryContractV16,
) -> None:
    if type(value) is not DatabaseInventoryContractV16:
        raise Stage8CV16Stop("DB_INVENTORY_CONTRACT_TYPE_INVALID")
    if (
        type(value.target_tickers) is not tuple
        or type(value.result_schema_fields) is not tuple
        or type(value.accepted_legacy_security_exchanges) is not tuple
    ):
        raise Stage8CV16Stop("DB_INVENTORY_COLLECTIONS_MUST_BE_TUPLE")
    query_hash = hashlib.sha256(
        TARGET_DATABASE_INVENTORY_QUERY_V16.encode("utf-8")
    ).hexdigest().upper()
    if _FORBIDDEN_SQL.search(TARGET_DATABASE_INVENTORY_QUERY_V16) is not None:
        raise Stage8CV16Stop("DB_INVENTORY_QUERY_NOT_READ_ONLY")
    if (
        value.contract_version != INVENTORY_CONTRACT_VERSION
        or value.target_tickers != TARGET_TICKERS
        or value.query_content_hash != query_hash
        or value.result_schema_fields != INVENTORY_RESULT_SCHEMA_FIELDS
        or value.adoption_policy_version != INVENTORY_ADOPTION_POLICY_VERSION
        or value.inventory_as_of_date != INVENTORY_AS_OF_DATE
        or value.accepted_legacy_security_exchanges
        != ACCEPTED_LEGACY_SECURITY_EXCHANGES
        or value.required_security_active is not True
        or value.required_security_instrument_type
        != REQUIRED_SECURITY_INSTRUMENT_TYPE
        or value.required_security_currency != REQUIRED_SECURITY_CURRENCY
        or value.required_listing_mic != CANONICAL_OPERATING_MIC
        or value.required_listing_currency != REQUIRED_LISTING_CURRENCY
        or value.registry_evidence_required is not True
        or value.current_ticker_rule != CURRENT_TICKER_RULE
        or value.database_read_authorized is not False
        or value.database_write_authorized is not False
        or value.content_hash
        != canonical_hash(_inventory_contract_body(value, include_hash=False))
    ):
        raise Stage8CV16Stop("DB_INVENTORY_CONTRACT_DRIFT")


def _optional_text(value: object, *, maximum: int, code: str) -> str | None:
    if value is None:
        return None
    return _require_text(value, maximum=maximum, code=code)


def _optional_uuid(value: object, code: str) -> str | None:
    text = _optional_text(value, maximum=36, code=code)
    if text is not None and _UUID.fullmatch(text) is None:
        raise Stage8CV16Stop(code)
    return text


def _optional_date(value: object, code: str) -> str | None:
    text = _optional_text(value, maximum=10, code=code)
    if text is not None:
        if _ISO_DATE.fullmatch(text) is None:
            raise Stage8CV16Stop(code)
        try:
            date.fromisoformat(text)
        except ValueError as error:
            raise Stage8CV16Stop(code) from error
    return text


def _optional_instant(value: object, code: str) -> str | None:
    text = _optional_text(value, maximum=20, code=code)
    if text is not None:
        if _UTC_SECOND.fullmatch(text) is None:
            raise Stage8CV16Stop(code)
        try:
            datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ")
        except ValueError as error:
            raise Stage8CV16Stop(code) from error
    return text


def parse_inventory_row_v16(value: Mapping[str, Any]) -> InventoryRowV16:
    if type(value) is not dict or set(value) != set(INVENTORY_RESULT_SCHEMA_FIELDS):
        raise Stage8CV16Stop("DB_INVENTORY_ROW_SCHEMA_INVALID")
    ordinal = value["targetOrdinal"]
    ticker = value["targetTicker"]
    active = value["securityActive"]
    if type(ordinal) is not int or ordinal not in (1, 2, 3):
        raise Stage8CV16Stop("DB_INVENTORY_TARGET_ORDINAL_INVALID")
    if type(ticker) is not str or ticker != TARGET_TICKERS[ordinal - 1]:
        raise Stage8CV16Stop("DB_INVENTORY_TARGET_TICKER_INVALID")
    if active is not None and type(active) is not bool:
        raise Stage8CV16Stop("DB_INVENTORY_SECURITY_ACTIVE_INVALID")
    internal_id = _optional_text(
        value["securityInternalId"], maximum=20, code="DB_INVENTORY_SECURITY_ID_INVALID"
    )
    if internal_id is not None and (not internal_id.isdigit() or int(internal_id) <= 0):
        raise Stage8CV16Stop("DB_INVENTORY_SECURITY_ID_INVALID")
    return InventoryRowV16(
        target_ordinal=ordinal,
        target_ticker=ticker,
        security_internal_id=internal_id,
        security_public_id=_optional_uuid(
            value["securityPublicId"], "DB_INVENTORY_PUBLIC_ID_INVALID"
        ),
        security_symbol=_optional_text(
            value["securitySymbol"], maximum=32, code="DB_INVENTORY_SYMBOL_INVALID"
        ),
        security_exchange=_optional_text(
            value["securityExchange"], maximum=32, code="DB_INVENTORY_EXCHANGE_INVALID"
        ),
        security_name=_optional_text(
            value["securityName"], maximum=255, code="DB_INVENTORY_NAME_INVALID"
        ),
        security_instrument_type=_optional_text(
            value["securityInstrumentType"],
            maximum=32,
            code="DB_INVENTORY_INSTRUMENT_TYPE_INVALID",
        ),
        security_currency=_optional_text(
            value["securityCurrency"], maximum=3, code="DB_INVENTORY_CURRENCY_INVALID"
        ),
        security_active=active,
        company_id=_optional_uuid(value["companyId"], "DB_INVENTORY_COMPANY_ID_INVALID"),
        company_registry_version=_optional_text(
            value["companyRegistryVersion"],
            maximum=128,
            code="DB_INVENTORY_REGISTRY_VERSION_INVALID",
        ),
        company_recorded_at=_optional_instant(
            value["companyRecordedAt"], "DB_INVENTORY_RECORDED_AT_INVALID"
        ),
        instrument_id=_optional_uuid(
            value["instrumentId"], "DB_INVENTORY_INSTRUMENT_ID_INVALID"
        ),
        instrument_company_id=_optional_uuid(
            value["instrumentCompanyId"], "DB_INVENTORY_COMPANY_ID_INVALID"
        ),
        instrument_registry_version=_optional_text(
            value["instrumentRegistryVersion"],
            maximum=128,
            code="DB_INVENTORY_REGISTRY_VERSION_INVALID",
        ),
        instrument_recorded_at=_optional_instant(
            value["instrumentRecordedAt"], "DB_INVENTORY_RECORDED_AT_INVALID"
        ),
        share_class_id=_optional_uuid(
            value["shareClassId"], "DB_INVENTORY_SHARE_CLASS_ID_INVALID"
        ),
        share_class_instrument_id=_optional_uuid(
            value["shareClassInstrumentId"], "DB_INVENTORY_INSTRUMENT_ID_INVALID"
        ),
        share_class_registry_version=_optional_text(
            value["shareClassRegistryVersion"],
            maximum=128,
            code="DB_INVENTORY_REGISTRY_VERSION_INVALID",
        ),
        share_class_recorded_at=_optional_instant(
            value["shareClassRecordedAt"], "DB_INVENTORY_RECORDED_AT_INVALID"
        ),
        listing_id=_optional_uuid(value["listingId"], "DB_INVENTORY_LISTING_ID_INVALID"),
        listing_share_class_id=_optional_uuid(
            value["listingShareClassId"], "DB_INVENTORY_SHARE_CLASS_ID_INVALID"
        ),
        listing_security_id=_optional_uuid(
            value["listingSecurityId"], "DB_INVENTORY_PUBLIC_ID_INVALID"
        ),
        listing_mic=_optional_text(
            value["listingMic"], maximum=4, code="DB_INVENTORY_MIC_INVALID"
        ),
        listing_currency=_optional_text(
            value["listingCurrency"], maximum=3, code="DB_INVENTORY_CURRENCY_INVALID"
        ),
        listing_registry_version=_optional_text(
            value["listingRegistryVersion"],
            maximum=128,
            code="DB_INVENTORY_REGISTRY_VERSION_INVALID",
        ),
        listing_recorded_at=_optional_instant(
            value["listingRecordedAt"], "DB_INVENTORY_RECORDED_AT_INVALID"
        ),
        ticker_assignment_id=_optional_uuid(
            value["tickerAssignmentId"], "DB_INVENTORY_TICKER_ASSIGNMENT_ID_INVALID"
        ),
        ticker_listing_id=_optional_uuid(
            value["tickerListingId"], "DB_INVENTORY_LISTING_ID_INVALID"
        ),
        ticker=_optional_text(
            value["ticker"], maximum=32, code="DB_INVENTORY_TICKER_INVALID"
        ),
        ticker_valid_from=_optional_date(
            value["tickerValidFrom"], "DB_INVENTORY_TICKER_DATE_INVALID"
        ),
        ticker_valid_to=_optional_date(
            value["tickerValidTo"], "DB_INVENTORY_TICKER_DATE_INVALID"
        ),
        ticker_registry_version=_optional_text(
            value["tickerRegistryVersion"],
            maximum=128,
            code="DB_INVENTORY_REGISTRY_VERSION_INVALID",
        ),
        ticker_recorded_at=_optional_instant(
            value["tickerRecordedAt"], "DB_INVENTORY_RECORDED_AT_INVALID"
        ),
    )


def _decision_body(
    value: TargetInventoryDecisionV16, *, include_hash: bool
) -> dict[str, object]:
    body: dict[str, object] = {
        "targetOrdinal": value.target_ordinal,
        "ticker": value.ticker,
        "adoptionState": value.adoption_state.value,
        "existingPublicId": value.existing_public_id,
        "rowCount": value.row_count,
        "securityCount": value.security_count,
        "listingCount": value.listing_count,
        "currentTargetTickerCount": value.current_target_ticker_count,
        "reasonCodes": list(value.reason_codes),
        "insertAuthorized": value.insert_authorized,
        "updateAuthorized": value.update_authorized,
    }
    if include_hash:
        body["contentHash"] = value.content_hash
    return body


def _seal_decision(
    *,
    ordinal: int,
    ticker: str,
    state: InventoryAdoptionState,
    public_id: str | None,
    rows: tuple[InventoryRowV16, ...],
    security_count: int,
    listing_count: int,
    current_count: int,
    reasons: tuple[str, ...],
) -> TargetInventoryDecisionV16:
    provisional = TargetInventoryDecisionV16(
        target_ordinal=ordinal,
        ticker=ticker,
        adoption_state=state,
        existing_public_id=public_id,
        row_count=len(rows),
        security_count=security_count,
        listing_count=listing_count,
        current_target_ticker_count=current_count,
        reason_codes=reasons,
        insert_authorized=False,
        update_authorized=False,
        content_hash="",
    )
    return TargetInventoryDecisionV16(
        **{
            **asdict(provisional),
            "adoption_state": provisional.adoption_state,
            "reason_codes": provisional.reason_codes,
            "content_hash": canonical_hash(
                _decision_body(provisional, include_hash=False)
            ),
        }
    )


def _v22_layer_lineage_complete(row: InventoryRowV16) -> bool:
    layers = (
        (
            row.company_id,
            row.company_registry_version,
            row.company_recorded_at,
        ),
        (
            row.instrument_id,
            row.instrument_registry_version,
            row.instrument_recorded_at,
            row.instrument_company_id,
        ),
        (
            row.share_class_id,
            row.share_class_registry_version,
            row.share_class_recorded_at,
            row.share_class_instrument_id,
        ),
        (
            row.listing_id,
            row.listing_registry_version,
            row.listing_recorded_at,
            row.listing_share_class_id,
            row.listing_security_id,
            row.listing_mic,
            row.listing_currency,
        ),
        (
            row.ticker_assignment_id,
            row.ticker_registry_version,
            row.ticker_recorded_at,
            row.ticker_listing_id,
            row.ticker,
            row.ticker_valid_from,
            row.ticker_valid_to,
        ),
    )
    for identity, registry_version, recorded_at, *other_values in layers:
        layer_present = any(
            item is not None
            for item in (identity, registry_version, recorded_at, *other_values)
        )
        if layer_present and (
            identity is None or registry_version is None or recorded_at is None
        ):
            return False
    return True


def _legacy_security_adoption_semantics_complete(
    rows: tuple[InventoryRowV16, ...],
) -> bool:
    return all(
        row.security_active is True
        and row.security_instrument_type == REQUIRED_SECURITY_INSTRUMENT_TYPE
        and row.security_currency == REQUIRED_SECURITY_CURRENCY
        and row.security_exchange in ACCEPTED_LEGACY_SECURITY_EXCHANGES
        for row in rows
    )


def _ticker_assignment_is_current_as_of(row: InventoryRowV16) -> bool:
    if row.ticker_valid_from is None:
        return False
    as_of_date = date.fromisoformat(INVENTORY_AS_OF_DATE)
    valid_from = date.fromisoformat(row.ticker_valid_from)
    valid_to = (
        date.fromisoformat(row.ticker_valid_to)
        if row.ticker_valid_to is not None
        else None
    )
    return valid_from <= as_of_date and (
        valid_to is None or as_of_date < valid_to
    )


def _classify_inventory_target(
    ticker: str, rows: tuple[InventoryRowV16, ...]
) -> TargetInventoryDecisionV16:
    ordinal = TARGET_TICKERS.index(ticker) + 1
    security_keys = {
        (row.security_internal_id, row.security_public_id)
        for row in rows
        if row.security_internal_id is not None or row.security_public_id is not None
    }
    if not security_keys:
        graph_values = [
            row.company_id
            or row.instrument_id
            or row.share_class_id
            or row.listing_id
            or row.ticker_assignment_id
            for row in rows
        ]
        if any(graph_values):
            state = InventoryAdoptionState.CONFLICT
            reasons = ("ORPHAN_V22_GRAPH_WITHOUT_SECURITY",)
        elif ticker == "MSFT":
            state = InventoryAdoptionState.CONFLICT
            reasons = ("MSFT_EXISTING_PUBLIC_ID_REQUIRED",)
        else:
            state = InventoryAdoptionState.NEW_ID_CANDIDATE
            reasons = ("NO_EXISTING_TARGET_IDENTITY",)
        return _seal_decision(
            ordinal=ordinal,
            ticker=ticker,
            state=state,
            public_id=None,
            rows=rows,
            security_count=0,
            listing_count=0,
            current_count=0,
            reasons=reasons,
        )
    if len(security_keys) != 1 or any(None in key for key in security_keys):
        return _seal_decision(
            ordinal=ordinal,
            ticker=ticker,
            state=InventoryAdoptionState.CONFLICT,
            public_id=None,
            rows=rows,
            security_count=len(security_keys),
            listing_count=len({row.listing_id for row in rows if row.listing_id}),
            current_count=0,
            reasons=("SECURITY_CARDINALITY_CONFLICT",),
        )
    _, public_id = next(iter(security_keys))
    if any(row.security_symbol != ticker for row in rows):
        return _seal_decision(
            ordinal=ordinal,
            ticker=ticker,
            state=InventoryAdoptionState.CONFLICT,
            public_id=public_id,
            rows=rows,
            security_count=1,
            listing_count=len({row.listing_id for row in rows if row.listing_id}),
            current_count=0,
            reasons=("LEGACY_SECURITY_SYMBOL_MISMATCH",),
        )
    if not _legacy_security_adoption_semantics_complete(rows):
        return _seal_decision(
            ordinal=ordinal,
            ticker=ticker,
            state=InventoryAdoptionState.CONFLICT,
            public_id=public_id,
            rows=rows,
            security_count=1,
            listing_count=len({row.listing_id for row in rows if row.listing_id}),
            current_count=0,
            reasons=("LEGACY_SECURITY_ADOPTION_SEMANTICS_CONFLICT",),
        )
    if any(not _v22_layer_lineage_complete(row) for row in rows):
        return _seal_decision(
            ordinal=ordinal,
            ticker=ticker,
            state=InventoryAdoptionState.CONFLICT,
            public_id=public_id,
            rows=rows,
            security_count=1,
            listing_count=len({row.listing_id for row in rows if row.listing_id}),
            current_count=0,
            reasons=("V22_LAYER_LINEAGE_INCOMPLETE",),
        )
    listing_ids = {row.listing_id for row in rows if row.listing_id is not None}
    if not listing_ids:
        if any(
            row.company_id
            or row.instrument_id
            or row.share_class_id
            or row.ticker_assignment_id
            for row in rows
        ):
            state = InventoryAdoptionState.CONFLICT
            reasons = ("PARTIAL_V22_GRAPH",)
        else:
            state = InventoryAdoptionState.ADOPT_EXISTING_PUBLIC_ID_V22_GRAPH_REQUIRED
            reasons = ("EXISTING_PUBLIC_ID_V22_GRAPH_ABSENT",)
        return _seal_decision(
            ordinal=ordinal,
            ticker=ticker,
            state=state,
            public_id=public_id,
            rows=rows,
            security_count=1,
            listing_count=0,
            current_count=0,
            reasons=reasons,
        )
    if len(listing_ids) != 1:
        return _seal_decision(
            ordinal=ordinal,
            ticker=ticker,
            state=InventoryAdoptionState.CONFLICT,
            public_id=public_id,
            rows=rows,
            security_count=1,
            listing_count=len(listing_ids),
            current_count=0,
            reasons=("V22_LISTING_CARDINALITY_CONFLICT",),
        )
    if any(
        row.listing_mic != CANONICAL_OPERATING_MIC
        or row.listing_currency != REQUIRED_LISTING_CURRENCY
        for row in rows
    ):
        return _seal_decision(
            ordinal=ordinal,
            ticker=ticker,
            state=InventoryAdoptionState.CONFLICT,
            public_id=public_id,
            rows=rows,
            security_count=1,
            listing_count=1,
            current_count=0,
            reasons=("V22_LISTING_ADOPTION_SEMANTICS_CONFLICT",),
        )
    listing_id = next(iter(listing_ids))
    graph_keys = {
        (
            row.company_id,
            row.instrument_id,
            row.share_class_id,
            row.listing_id,
            row.listing_security_id,
            row.listing_mic,
        )
        for row in rows
    }
    graph = next(iter(graph_keys)) if len(graph_keys) == 1 else None
    graph_complete = (
        graph is not None
        and all(item is not None for item in graph)
        and all(
            row.security_exchange is not None
            and row.security_name is not None
            and row.security_instrument_type is not None
            and row.security_currency is not None
            and row.security_active is not None
            and row.company_registry_version is not None
            and row.company_recorded_at is not None
            and row.instrument_company_id == row.company_id
            and row.instrument_registry_version is not None
            and row.instrument_recorded_at is not None
            and row.share_class_instrument_id == row.instrument_id
            and row.share_class_registry_version is not None
            and row.share_class_recorded_at is not None
            and row.listing_share_class_id == row.share_class_id
            and row.listing_security_id == public_id
            and row.listing_mic == CANONICAL_OPERATING_MIC
            and row.listing_currency is not None
            and row.listing_registry_version is not None
            and row.listing_recorded_at is not None
            for row in rows
        )
    )
    assignment_ids = [row.ticker_assignment_id for row in rows if row.ticker_assignment_id]
    current_target = [
        row
        for row in rows
        if row.ticker_assignment_id is not None
        and row.ticker == ticker
        and _ticker_assignment_is_current_as_of(row)
    ]
    assignment_complete = all(
        row.ticker_assignment_id is not None
        and row.ticker_listing_id == listing_id
        and row.ticker is not None
        and row.ticker_valid_from is not None
        and (
            row.ticker_valid_to is None
            or row.ticker_valid_to > row.ticker_valid_from
        )
        and row.ticker_registry_version is not None
        and row.ticker_recorded_at is not None
        for row in rows
    )
    if (
        not graph_complete
        or not assignment_complete
        or len(assignment_ids) != len(set(assignment_ids))
        or len(current_target) != 1
    ):
        return _seal_decision(
            ordinal=ordinal,
            ticker=ticker,
            state=InventoryAdoptionState.CONFLICT,
            public_id=public_id,
            rows=rows,
            security_count=1,
            listing_count=1,
            current_count=len(current_target),
            reasons=("V22_GRAPH_OR_CURRENT_TICKER_CONFLICT",),
        )
    return _seal_decision(
        ordinal=ordinal,
        ticker=ticker,
        state=InventoryAdoptionState.ADOPT_EXISTING_V22_GRAPH,
        public_id=public_id,
        rows=rows,
        security_count=1,
        listing_count=1,
        current_count=1,
        reasons=("EXACT_EXISTING_V22_GRAPH",),
    )


def _inventory_review_body(
    value: InventoryReviewV16, *, include_hash: bool
) -> dict[str, object]:
    body: dict[str, object] = {
        "queryContentHash": value.query_content_hash,
        "decisions": [_decision_body(item, include_hash=True) for item in value.decisions],
        "adoptExistingCount": value.adopt_existing_count,
        "newIdCandidateCount": value.new_id_candidate_count,
        "conflictCount": value.conflict_count,
        "readOnly": value.read_only,
        "projectionV1Status": value.projection_v1_status,
        "successorRequirement": value.successor_requirement,
    }
    if include_hash:
        body["contentHash"] = value.content_hash
    return body


def build_inventory_review_v16(
    rows: tuple[Mapping[str, Any], ...],
) -> InventoryReviewV16:
    contract = build_database_inventory_contract_v16()
    if type(rows) is not tuple:
        raise Stage8CV16Stop("DB_INVENTORY_ROWS_MUST_BE_TUPLE")
    parsed = tuple(parse_inventory_row_v16(row) for row in rows)
    grouped: dict[str, list[InventoryRowV16]] = {ticker: [] for ticker in TARGET_TICKERS}
    fingerprints: set[str] = set()
    for row in parsed:
        fingerprint = canonical_hash(asdict(row))
        if fingerprint in fingerprints:
            raise Stage8CV16Stop("DB_INVENTORY_DUPLICATE_ROW")
        fingerprints.add(fingerprint)
        grouped[row.target_ticker].append(row)
    if any(not grouped[ticker] for ticker in TARGET_TICKERS):
        raise Stage8CV16Stop("DB_INVENTORY_TARGET_SET_INCOMPLETE")
    decisions = tuple(
        _classify_inventory_target(ticker, tuple(grouped[ticker]))
        for ticker in TARGET_TICKERS
    )
    adopt = sum(
        item.adoption_state
        in {
            InventoryAdoptionState.ADOPT_EXISTING_V22_GRAPH,
            InventoryAdoptionState.ADOPT_EXISTING_PUBLIC_ID_V22_GRAPH_REQUIRED,
        }
        for item in decisions
    )
    new_count = sum(
        item.adoption_state is InventoryAdoptionState.NEW_ID_CANDIDATE
        for item in decisions
    )
    conflicts = sum(
        item.adoption_state is InventoryAdoptionState.CONFLICT for item in decisions
    )
    provisional = InventoryReviewV16(
        query_content_hash=contract.query_content_hash,
        decisions=decisions,
        adopt_existing_count=adopt,
        new_id_candidate_count=new_count,
        conflict_count=conflicts,
        read_only=True,
        projection_v1_status=PROJECTION_V1_STATUS,
        successor_requirement=SUCCESSOR_REQUIREMENT,
        content_hash="",
    )
    result = InventoryReviewV16(
        **{
            **asdict(provisional),
            "decisions": provisional.decisions,
            "content_hash": canonical_hash(
                _inventory_review_body(provisional, include_hash=False)
            ),
        }
    )
    validate_inventory_review_v16(result)
    return result


def validate_inventory_review_v16(value: InventoryReviewV16) -> None:
    contract = build_database_inventory_contract_v16()
    if type(value) is not InventoryReviewV16 or type(value.decisions) is not tuple:
        raise Stage8CV16Stop("DB_INVENTORY_REVIEW_TYPE_INVALID")
    if len(value.decisions) != 3:
        raise Stage8CV16Stop("DB_INVENTORY_DECISION_CARDINALITY_INVALID")
    for ordinal, (ticker, decision) in enumerate(
        zip(TARGET_TICKERS, value.decisions, strict=True), start=1
    ):
        if (
            type(decision) is not TargetInventoryDecisionV16
            or type(decision.reason_codes) is not tuple
            or decision.target_ordinal != ordinal
            or decision.ticker != ticker
            or decision.insert_authorized is not False
            or decision.update_authorized is not False
            or decision.content_hash
            != canonical_hash(_decision_body(decision, include_hash=False))
        ):
            raise Stage8CV16Stop("DB_INVENTORY_DECISION_DRIFT")
    adopt = sum(
        item.adoption_state
        in {
            InventoryAdoptionState.ADOPT_EXISTING_V22_GRAPH,
            InventoryAdoptionState.ADOPT_EXISTING_PUBLIC_ID_V22_GRAPH_REQUIRED,
        }
        for item in value.decisions
    )
    new_count = sum(
        item.adoption_state is InventoryAdoptionState.NEW_ID_CANDIDATE
        for item in value.decisions
    )
    conflicts = sum(
        item.adoption_state is InventoryAdoptionState.CONFLICT
        for item in value.decisions
    )
    if (
        value.query_content_hash != contract.query_content_hash
        or value.adopt_existing_count != adopt
        or value.new_id_candidate_count != new_count
        or value.conflict_count != conflicts
        or value.read_only is not True
        or value.projection_v1_status != PROJECTION_V1_STATUS
        or value.successor_requirement != SUCCESSOR_REQUIREMENT
        or value.content_hash
        != canonical_hash(_inventory_review_body(value, include_hash=False))
    ):
        raise Stage8CV16Stop("DB_INVENTORY_REVIEW_DRIFT")


def _contract_body(value: Stage8CV16Contract, *, include_hash: bool) -> dict[str, object]:
    body: dict[str, object] = {
        "contractVersion": value.contract_version,
        "state": value.state,
        "predecessorV15DecisionCode": value.predecessor_v15_decision_code,
        "predecessorV15PlanContentHash": value.predecessor_v15_plan_content_hash,
        "predecessorV15ReviewContentHash": value.predecessor_v15_review_content_hash,
        "predecessorV15CheckpointReceiptSetHash": value.predecessor_v15_checkpoint_receipt_set_hash,
        "predecessorV15ReplayVerificationHash": value.predecessor_v15_replay_verification_hash,
        "predecessorV15DiagnosticAcceptanceHash": value.predecessor_v15_diagnostic_acceptance_hash,
        "predecessorV15StorageAcceptanceHash": value.predecessor_v15_storage_acceptance_hash,
        "predecessorResultArtifactCanonicalHash": value.predecessor_result_artifact_canonical_hash,
        "predecessorResultArtifactBindingStatus": value.predecessor_result_artifact_binding_status,
        "secRequest": _sec_request_body(value.sec_request, include_hash=True),
        "databaseInventory": _inventory_contract_body(
            value.database_inventory, include_hash=True
        ),
        "projectionV1Status": value.projection_v1_status,
        "successorRequirement": value.successor_requirement,
        "realProjectionAuthorized": value.real_projection_authorized,
        "networkAuthorized": value.network_authorized,
        "databaseReadAuthorized": value.database_read_authorized,
        "databaseWriteAuthorized": value.database_write_authorized,
    }
    if include_hash:
        body["contentHash"] = value.content_hash
    return body


def build_stage8c_v16_contract() -> Stage8CV16Contract:
    provisional = Stage8CV16Contract(
        contract_version=CONTRACT_VERSION,
        state="PREREGISTERED_OFFLINE_NETWORK_AND_DATABASE_CLOSED",
        predecessor_v15_decision_code=PREDECESSOR_V15_DECISION_CODE,
        predecessor_v15_plan_content_hash=PREDECESSOR_V15_PLAN_CONTENT_HASH,
        predecessor_v15_review_content_hash=PREDECESSOR_V15_REVIEW_CONTENT_HASH,
        predecessor_v15_checkpoint_receipt_set_hash=(
            PREDECESSOR_V15_CHECKPOINT_RECEIPT_SET_HASH
        ),
        predecessor_v15_replay_verification_hash=(
            PREDECESSOR_V15_REPLAY_VERIFICATION_HASH
        ),
        predecessor_v15_diagnostic_acceptance_hash=(
            PREDECESSOR_V15_DIAGNOSTIC_ACCEPTANCE_HASH
        ),
        predecessor_v15_storage_acceptance_hash=(
            PREDECESSOR_V15_STORAGE_ACCEPTANCE_HASH
        ),
        predecessor_result_artifact_canonical_hash=(
            PREDECESSOR_V15_RESULT_ARTIFACT_CANONICAL_HASH
        ),
        predecessor_result_artifact_binding_status=(
            "BOUND_EXACT_GIT_SAFE_RESULT_ARTIFACT"
        ),
        sec_request=build_sec_request_contract_v16(),
        database_inventory=build_database_inventory_contract_v16(),
        projection_v1_status=PROJECTION_V1_STATUS,
        successor_requirement=SUCCESSOR_REQUIREMENT,
        real_projection_authorized=False,
        network_authorized=False,
        database_read_authorized=False,
        database_write_authorized=False,
        content_hash="",
    )
    result = Stage8CV16Contract(
        **{
            **asdict(provisional),
            "sec_request": provisional.sec_request,
            "database_inventory": provisional.database_inventory,
            "content_hash": canonical_hash(_contract_body(provisional, include_hash=False)),
        }
    )
    validate_stage8c_v16_contract(result)
    return result


def validate_stage8c_v16_contract(value: Stage8CV16Contract) -> None:
    if type(value) is not Stage8CV16Contract:
        raise Stage8CV16Stop("STAGE8C_V16_CONTRACT_TYPE_INVALID")
    validate_sec_request_contract_v16(value.sec_request)
    validate_database_inventory_contract_v16(value.database_inventory)
    predecessor_hashes = (
        value.predecessor_v15_plan_content_hash,
        value.predecessor_v15_review_content_hash,
        value.predecessor_v15_checkpoint_receipt_set_hash,
        value.predecessor_v15_replay_verification_hash,
        value.predecessor_v15_diagnostic_acceptance_hash,
        value.predecessor_v15_storage_acceptance_hash,
        value.predecessor_result_artifact_canonical_hash,
    )
    for item in predecessor_hashes:
        _require_hash(item, "STAGE8C_V16_PREDECESSOR_HASH_INVALID")
    if (
        value.contract_version != CONTRACT_VERSION
        or value.state != "PREREGISTERED_OFFLINE_NETWORK_AND_DATABASE_CLOSED"
        or value.predecessor_v15_decision_code != PREDECESSOR_V15_DECISION_CODE
        or predecessor_hashes
        != (
            PREDECESSOR_V15_PLAN_CONTENT_HASH,
            PREDECESSOR_V15_REVIEW_CONTENT_HASH,
            PREDECESSOR_V15_CHECKPOINT_RECEIPT_SET_HASH,
            PREDECESSOR_V15_REPLAY_VERIFICATION_HASH,
            PREDECESSOR_V15_DIAGNOSTIC_ACCEPTANCE_HASH,
            PREDECESSOR_V15_STORAGE_ACCEPTANCE_HASH,
            PREDECESSOR_V15_RESULT_ARTIFACT_CANONICAL_HASH,
        )
        or value.predecessor_result_artifact_binding_status
        != "BOUND_EXACT_GIT_SAFE_RESULT_ARTIFACT"
        or value.projection_v1_status != PROJECTION_V1_STATUS
        or value.successor_requirement != SUCCESSOR_REQUIREMENT
        or value.real_projection_authorized is not False
        or value.network_authorized is not False
        or value.database_read_authorized is not False
        or value.database_write_authorized is not False
        or value.content_hash
        != canonical_hash(_contract_body(value, include_hash=False))
    ):
        raise Stage8CV16Stop("STAGE8C_V16_CONTRACT_DRIFT")
