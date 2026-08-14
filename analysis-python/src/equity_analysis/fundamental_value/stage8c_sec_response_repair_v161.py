"""Append-only v1.6.1 interpretation repair for the sealed SEC response.

The original v1.6 request and executor are immutable.  Their one live GET was
sealed successfully, but the original response parser rejected an irrelevant
row whose exchange value was JSON null.  This successor changes response
interpretation only: every row still has the exact four-column shape and typed
CIK/name/ticker values, while non-target exchange may be null.  The three target
rows still require a non-null typed exchange and remain unique.

The live entry point performs storage-only replay.  It never constructs a
transport and never reads an environment variable.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from equity_analysis.fundamental_value.prospective_company_quality_acquisition_v1 import (
    AcquisitionStop,
    validate_private_storage_root,
)
from equity_analysis.fundamental_value.stage8c_sec_execution_v16 import (
    AUTHORITY_BASIS,
    CONTROLLER_AUTHORITY_CONTENT_HASH,
    EXECUTION_CONTRACT_VERSION,
    SEC_REQUEST_CONTRACT_CONTENT_HASH,
    STAGE8C_V16_CONTRACT_CONTENT_HASH,
)
from equity_analysis.fundamental_value.stage8c_sec_inventory_v16 import (
    CANONICAL_OPERATING_MIC,
    SEC_EXCHANGE_VALUE,
    SEC_MAPPING_CLAIM,
    TARGET_TICKERS,
    SecCorroborationRecordV16,
    canonical_hash,
)

REPAIR_CONTRACT_VERSION = "FV-STAGE8C-SEC-RESPONSE-INTERPRETATION-REPAIR-v1.6.1"
REVIEW_VERSION = "FV-STAGE8C-SEC-CORROBORATION-REVIEW-v1.6.1"
STORAGE_REPLAY_VERSION = "FV-STAGE8C-SEC-CORROBORATION-STORAGE-REPLAY-v1.6.1"
RESULT_ARTIFACT_VERSION = "FV-STAGE8C-SEC-CORROBORATION-v1.6.1-RESULT-v1.0.0"
EXECUTION_SUMMARY_VERSION = "FV-STAGE8C-SEC-CORROBORATION-SUMMARY-v1.0.0"
EXECUTION_RESULT_HASH_PROVENANCE = (
    "DETERMINISTICALLY_RECONSTRUCTED_NOT_PRESERVED"
)
ORIGINAL_FAILURE_CODE = "SEC_RESPONSE_EXCHANGE_INVALID"
REPAIR_REASON = "IRRELEVANT_SEC_ROWS_MAY_HAVE_NULL_EXCHANGE"
ACCEPTED_DECISION_CODE = "SEC_CORROBORATION_V161_ACCEPTED_CURRENT_OPERATING_MIC_ONLY"
REJECTED_DECISION_CODE = "SEC_CORROBORATION_V161_REJECTED_TARGET_MAPPING_INCOMPLETE"

LIVE_RUN_ID = "20260802T151948Z-STAGE8C-SEC-V16-001"
LIVE_AUTHORIZATION_CONTENT_HASH = (
    "C5F9A7A7991666FB3AC3099E80432B7FF75146C93D14CA992086F0785FEE9D30"
)
LIVE_SEND_EXECUTION_RESULT_CONTENT_HASH = (
    "4CAD0EE0E7BADAE11A162E49AD95C4CEB8B0E1FDB7ABBD76F08E0F0F06D5368D"
)
LIVE_REPLAY_EXECUTION_RESULT_CONTENT_HASH = (
    "6E5F91582490DAE0D519A3495C966B1F734A5BEA2D5BDCD0774815D55E7FA2E8"
)
LIVE_MANIFEST_FILE_SHA256 = (
    "CD9D7BDEEE3012A040272D088AA9ED9646A57936E0220B450C16D22E358E7329"
)
LIVE_MANIFEST_CONTENT_HASH = (
    "5C9304FAA44FBCA8E6629C75895D0D92920F3B800090098A4493C9557A9F5BD6"
)
LIVE_REQUEST_IDENTITY = (
    "66E405FA9B8AC01A32DDAED38524BE0161CFAE1406BE6DCB9B6F2EAD3F1D4210"
)
LIVE_INTENT_FILE_SHA256 = (
    "BD35D233B001D7A0EBEED61779740FB4FE1600E76CFB0C382347DD8712B0A5A3"
)
LIVE_INTENT_EVENT_HASH = (
    "7205B32C42D2D0DED0D49976E17DE2E002D520DF9ACD794EBEC4580E9E31C1A3"
)
LIVE_COMPLETED_FILE_SHA256 = (
    "694B6077479285E485DAC19F48E97B361F86CFA9AD41A687F1AD44C2DEB25E9C"
)
LIVE_TERMINAL_EVENT_HASH = (
    "EECA0ADF31D3B5A80D98EEDF1A87184CD00CB05EA5621D3F6B90A5428B016EDC"
)
LIVE_RESPONSE_BODY_SHA256 = (
    "E6FBAD74D63540E73239F257809CF217B9D6B4FED2410691F0C8C576C9A6CF3C"
)
LIVE_RESPONSE_HEADERS_HASH = (
    "26ACF569567B36656130D3F5D404148E150C9372169954139CD47A86A59DBAFC"
)
LIVE_RESPONSE_BODY_BYTE_COUNT = 522_982
LIVE_TOTAL_ROW_COUNT = 10_432
LIVE_IRRELEVANT_NULL_EXCHANGE_COUNT = 190
LIVE_TARGET_RECORD_SET_HASH = (
    "B4AE07349277215F5140DF21FABE3D76DDEE9E3918BC631E4F832D9257AB4EF0"
)

_UPPER_SHA256 = re.compile(r"[0-9A-F]{64}\Z")
_CIK = re.compile(r"[0-9]{10}\Z")
_TICKER = re.compile(r"[A-Z][A-Z0-9.-]{0,31}\Z")
_SAFE_TEXT = re.compile(r"[^\x00\r\n]{1,512}\Z")


class SecResponseRepairStop(RuntimeError):
    """Fail-closed v1.6.1 interpretation stop."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class SecResponseReviewV161:
    review_version: str
    predecessor_contract_content_hash: str
    request_contract_content_hash: str
    original_failure_code: str
    repair_reason: str
    response_body_sha256: str
    total_row_count: int
    irrelevant_row_count: int
    irrelevant_null_exchange_count: int
    target_records: tuple[SecCorroborationRecordV16, ...]
    target_record_set_hash: str
    unique_target_count: int
    supported_mapping_count: int
    accepted: bool
    claim: str
    diagnostic_only: bool
    segment_claimed: bool
    tier_claimed: bool
    exchange_history_claimed: bool
    listing_figi_claimed: bool
    currency_claimed: bool
    completed_session_claimed: bool
    content_hash: str


@dataclass(frozen=True)
class SecRepairStorageBindingV161:
    run_id: str
    authorization_content_hash: str
    send_execution_result_content_hash: str
    replay_execution_result_content_hash: str
    manifest_file_sha256: str
    manifest_content_hash: str
    request_identity: str
    intent_file_sha256: str
    intent_event_hash: str
    completed_file_sha256: str
    terminal_event_hash: str
    response_body_sha256: str
    response_headers_hash: str
    response_body_byte_count: int


@dataclass(frozen=True)
class SecResponseRepairAcceptanceV161:
    repair_contract_version: str
    run_id: str
    predecessor_contract_content_hash: str
    request_contract_content_hash: str
    controller_authority_content_hash: str
    authority_basis: str
    original_failure_code: str
    repair_reason: str
    storage_binding_content_hash: str
    authorization_content_hash: str
    send_execution_result_content_hash: str
    replay_execution_result_content_hash: str
    execution_result_hash_provenance: str
    manifest_content_hash: str
    request_identity: str
    terminal_event_hash: str
    response_body_sha256: str
    response_headers_hash: str
    review_content_hash: str
    total_row_count: int
    irrelevant_row_count: int
    irrelevant_null_exchange_count: int
    target_record_set_hash: str
    unique_target_count: int
    supported_mapping_count: int
    accepted: bool
    decision_code: str
    canonical_operating_mic: str | None
    claim: str
    append_only_successor: bool
    post_original_failure_observation: bool
    holdout_claimed: bool
    diagnostic_only: bool
    network_requests_sent_during_repair: int
    retry_limit: int
    database_read_authorized: bool
    database_write_authorized: bool
    v22_write_authorized: bool
    v24_write_authorized: bool
    projection_authorized: bool
    evidence_label_upgrade_authorized: bool
    segment_claimed: bool
    tier_claimed: bool
    exchange_history_claimed: bool
    listing_figi_claimed: bool
    currency_claimed: bool
    completed_session_claimed: bool
    content_hash: str


LIVE_STORAGE_BINDING = SecRepairStorageBindingV161(
    run_id=LIVE_RUN_ID,
    authorization_content_hash=LIVE_AUTHORIZATION_CONTENT_HASH,
    send_execution_result_content_hash=LIVE_SEND_EXECUTION_RESULT_CONTENT_HASH,
    replay_execution_result_content_hash=LIVE_REPLAY_EXECUTION_RESULT_CONTENT_HASH,
    manifest_file_sha256=LIVE_MANIFEST_FILE_SHA256,
    manifest_content_hash=LIVE_MANIFEST_CONTENT_HASH,
    request_identity=LIVE_REQUEST_IDENTITY,
    intent_file_sha256=LIVE_INTENT_FILE_SHA256,
    intent_event_hash=LIVE_INTENT_EVENT_HASH,
    completed_file_sha256=LIVE_COMPLETED_FILE_SHA256,
    terminal_event_hash=LIVE_TERMINAL_EVENT_HASH,
    response_body_sha256=LIVE_RESPONSE_BODY_SHA256,
    response_headers_hash=LIVE_RESPONSE_HEADERS_HASH,
    response_body_byte_count=LIVE_RESPONSE_BODY_BYTE_COUNT,
)


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest().upper()


def _require_hash(value: object, code: str) -> str:
    if type(value) is not str or _UPPER_SHA256.fullmatch(value) is None:
        raise SecResponseRepairStop(code)
    return value


def _require_text(value: object, *, maximum: int, code: str) -> str:
    if (
        type(value) is not str
        or not value
        or value != value.strip(" \t\n\r\f\v")
        or len(value) > maximum
        or _SAFE_TEXT.fullmatch(value) is None
    ):
        raise SecResponseRepairStop(code)
    return value


def _strict_json_loads(value: bytes, *, code: str) -> object:
    def pairs(items: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, item in items:
            if key in result:
                raise SecResponseRepairStop(f"{code}_DUPLICATE_KEY")
            result[key] = item
        return result

    def reject_constant(_: str) -> None:
        raise SecResponseRepairStop(f"{code}_NONFINITE_CONSTANT")

    try:
        return json.loads(
            value.decode("utf-8"),
            object_pairs_hook=pairs,
            parse_constant=reject_constant,
        )
    except SecResponseRepairStop:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SecResponseRepairStop(f"{code}_INVALID") from error


def _record_body(
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


def _review_body(value: SecResponseReviewV161, *, include_hash: bool) -> dict[str, object]:
    body: dict[str, object] = {
        "reviewVersion": value.review_version,
        "predecessorContractContentHash": value.predecessor_contract_content_hash,
        "requestContractContentHash": value.request_contract_content_hash,
        "originalFailureCode": value.original_failure_code,
        "repairReason": value.repair_reason,
        "responseBodySha256": value.response_body_sha256,
        "totalRowCount": value.total_row_count,
        "irrelevantRowCount": value.irrelevant_row_count,
        "irrelevantNullExchangeCount": value.irrelevant_null_exchange_count,
        "targetRecords": [
            _record_body(item, include_hash=True) for item in value.target_records
        ],
        "targetRecordSetHash": value.target_record_set_hash,
        "uniqueTargetCount": value.unique_target_count,
        "supportedMappingCount": value.supported_mapping_count,
        "accepted": value.accepted,
        "claim": value.claim,
        "diagnosticOnly": value.diagnostic_only,
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


def build_sec_response_review_v161(response_body: bytes) -> SecResponseReviewV161:
    """Parse one response without relaxing any target-row requirement."""

    if type(response_body) is not bytes:
        raise SecResponseRepairStop("SEC_V161_RESPONSE_BODY_MUST_BE_BYTES")
    payload = _strict_json_loads(response_body, code="SEC_V161_RESPONSE_JSON")
    if type(payload) is not dict or set(payload) != {"fields", "data"}:
        raise SecResponseRepairStop("SEC_V161_RESPONSE_ROOT_SCHEMA_INVALID")
    if payload["fields"] != ["cik", "name", "ticker", "exchange"]:
        raise SecResponseRepairStop("SEC_V161_RESPONSE_FIELDS_INVALID")
    rows = payload["data"]
    if type(rows) is not list:
        raise SecResponseRepairStop("SEC_V161_RESPONSE_DATA_INVALID")
    found: dict[str, tuple[str, str, str]] = {}
    irrelevant_null_exchange_count = 0
    for row in rows:
        if type(row) is not list or len(row) != 4:
            raise SecResponseRepairStop("SEC_V161_RESPONSE_ROW_SCHEMA_INVALID")
        cik_value, name_value, ticker_value, exchange_value = row
        if type(cik_value) is not int or cik_value <= 0 or cik_value > 9_999_999_999:
            raise SecResponseRepairStop("SEC_V161_RESPONSE_CIK_INVALID")
        name = _require_text(
            name_value, maximum=512, code="SEC_V161_RESPONSE_NAME_INVALID"
        )
        ticker = _require_text(
            ticker_value, maximum=32, code="SEC_V161_RESPONSE_TICKER_INVALID"
        )
        if _TICKER.fullmatch(ticker) is None:
            raise SecResponseRepairStop("SEC_V161_RESPONSE_TICKER_INVALID")
        if exchange_value is None:
            exchange = None
        else:
            exchange = _require_text(
                exchange_value,
                maximum=64,
                code="SEC_V161_RESPONSE_EXCHANGE_INVALID",
            )
        if ticker in TARGET_TICKERS:
            if exchange is None:
                raise SecResponseRepairStop("SEC_V161_TARGET_EXCHANGE_REQUIRED")
            if ticker in found:
                raise SecResponseRepairStop("SEC_V161_TARGET_TICKER_NOT_UNIQUE")
            found[ticker] = (f"{cik_value:010d}", name, exchange)
        elif exchange is None:
            irrelevant_null_exchange_count += 1
    if set(found) != set(TARGET_TICKERS):
        raise SecResponseRepairStop("SEC_V161_TARGET_TICKER_SET_INCOMPLETE")
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
                        _record_body(provisional, include_hash=False)
                    ),
                }
            )
        )
    supported_count = sum(item.mapping_supported for item in records)
    records_by_ticker = {item.ticker: item for item in records}
    target_record_set_hash = canonical_hash(
        [
            _record_body(records_by_ticker[ticker], include_hash=True)
            for ticker in sorted(TARGET_TICKERS)
        ]
    )
    provisional_review = SecResponseReviewV161(
        review_version=REVIEW_VERSION,
        predecessor_contract_content_hash=STAGE8C_V16_CONTRACT_CONTENT_HASH,
        request_contract_content_hash=SEC_REQUEST_CONTRACT_CONTENT_HASH,
        original_failure_code=ORIGINAL_FAILURE_CODE,
        repair_reason=REPAIR_REASON,
        response_body_sha256=_sha256_bytes(response_body),
        total_row_count=len(rows),
        irrelevant_row_count=len(rows) - len(TARGET_TICKERS),
        irrelevant_null_exchange_count=irrelevant_null_exchange_count,
        target_records=tuple(records),
        target_record_set_hash=target_record_set_hash,
        unique_target_count=len(records),
        supported_mapping_count=supported_count,
        accepted=supported_count == len(TARGET_TICKERS),
        claim=SEC_MAPPING_CLAIM,
        diagnostic_only=True,
        segment_claimed=False,
        tier_claimed=False,
        exchange_history_claimed=False,
        listing_figi_claimed=False,
        currency_claimed=False,
        completed_session_claimed=False,
        content_hash="",
    )
    result = SecResponseReviewV161(
        **{
            **asdict(provisional_review),
            "target_records": provisional_review.target_records,
            "content_hash": canonical_hash(
                _review_body(provisional_review, include_hash=False)
            ),
        }
    )
    validate_sec_response_review_v161(result)
    return result


def validate_sec_response_review_v161(value: SecResponseReviewV161) -> None:
    if type(value) is not SecResponseReviewV161:
        raise SecResponseRepairStop("SEC_V161_REVIEW_TYPE_INVALID")
    if type(value.target_records) is not tuple or len(value.target_records) != 3:
        raise SecResponseRepairStop("SEC_V161_REVIEW_TARGET_RECORDS_INVALID")
    supported = 0
    for ordinal, (ticker, record) in enumerate(
        zip(TARGET_TICKERS, value.target_records, strict=True), start=1
    ):
        if type(record) is not SecCorroborationRecordV16:
            raise SecResponseRepairStop("SEC_V161_REVIEW_TARGET_RECORD_TYPE_INVALID")
        name = _require_text(
            record.name, maximum=512, code="SEC_V161_REVIEW_TARGET_NAME_INVALID"
        )
        exchange = _require_text(
            record.provider_exchange,
            maximum=64,
            code="SEC_V161_REVIEW_TARGET_EXCHANGE_INVALID",
        )
        mapping_supported = record.provider_exchange == SEC_EXCHANGE_VALUE
        if (
            type(record.target_ordinal) is not int
            or record.target_ordinal != ordinal
            or record.ticker != ticker
            or type(record.cik) is not str
            or _CIK.fullmatch(record.cik) is None
            or type(record.name) is not str
            or record.name != name
            or type(record.provider_exchange) is not str
            or record.provider_exchange != exchange
            or type(record.mapping_supported) is not bool
            or record.mapping_supported is not mapping_supported
            or record.canonical_operating_mic
            != (CANONICAL_OPERATING_MIC if mapping_supported else None)
            or not _UPPER_SHA256.fullmatch(record.content_hash)
            or record.content_hash
            != canonical_hash(_record_body(record, include_hash=False))
        ):
            raise SecResponseRepairStop("SEC_V161_REVIEW_TARGET_RECORD_DRIFT")
        supported += int(mapping_supported)
    records_by_ticker = {item.ticker: item for item in value.target_records}
    recomputed_target_record_set_hash = canonical_hash(
        [
            _record_body(records_by_ticker[ticker], include_hash=True)
            for ticker in sorted(TARGET_TICKERS)
        ]
    )
    if (
        value.review_version != REVIEW_VERSION
        or value.predecessor_contract_content_hash
        != STAGE8C_V16_CONTRACT_CONTENT_HASH
        or value.request_contract_content_hash != SEC_REQUEST_CONTRACT_CONTENT_HASH
        or value.original_failure_code != ORIGINAL_FAILURE_CODE
        or value.repair_reason != REPAIR_REASON
        or not _UPPER_SHA256.fullmatch(value.response_body_sha256)
        or type(value.total_row_count) is not int
        or value.total_row_count < 3
        or type(value.irrelevant_row_count) is not int
        or value.irrelevant_row_count != value.total_row_count - 3
        or type(value.irrelevant_null_exchange_count) is not int
        or not 0 <= value.irrelevant_null_exchange_count <= value.irrelevant_row_count
        or not _UPPER_SHA256.fullmatch(value.target_record_set_hash)
        or value.target_record_set_hash != recomputed_target_record_set_hash
        or value.unique_target_count != 3
        or value.supported_mapping_count != supported
        or type(value.accepted) is not bool
        or value.accepted is not (supported == 3)
        or value.claim != SEC_MAPPING_CLAIM
        or value.diagnostic_only is not True
        or value.segment_claimed is not False
        or value.tier_claimed is not False
        or value.exchange_history_claimed is not False
        or value.listing_figi_claimed is not False
        or value.currency_claimed is not False
        or value.completed_session_claimed is not False
        or not _UPPER_SHA256.fullmatch(value.content_hash)
        or value.content_hash != canonical_hash(_review_body(value, include_hash=False))
    ):
        raise SecResponseRepairStop("SEC_V161_REVIEW_DRIFT")


def _storage_binding_body(value: SecRepairStorageBindingV161) -> dict[str, object]:
    return {
        "runId": value.run_id,
        "authorizationContentHash": value.authorization_content_hash,
        "sendExecutionResultContentHash": value.send_execution_result_content_hash,
        "replayExecutionResultContentHash": value.replay_execution_result_content_hash,
        "manifestFileSha256": value.manifest_file_sha256,
        "manifestContentHash": value.manifest_content_hash,
        "requestIdentity": value.request_identity,
        "intentFileSha256": value.intent_file_sha256,
        "intentEventHash": value.intent_event_hash,
        "completedFileSha256": value.completed_file_sha256,
        "terminalEventHash": value.terminal_event_hash,
        "responseBodySha256": value.response_body_sha256,
        "responseHeadersHash": value.response_headers_hash,
        "responseBodyByteCount": value.response_body_byte_count,
    }


def _execution_result_content_hash(
    binding: SecRepairStorageBindingV161,
    *,
    new_physical_request_count: int,
    replayed_physical_request_count: int,
) -> str:
    """Rebuild the Git-safe executor summary hash without the private contact."""

    return canonical_hash(
        {
            "summaryVersion": EXECUTION_SUMMARY_VERSION,
            "runId": binding.run_id,
            "stage8cContractContentHash": STAGE8C_V16_CONTRACT_CONTENT_HASH,
            "requestContractContentHash": SEC_REQUEST_CONTRACT_CONTENT_HASH,
            "authorizationContentHash": binding.authorization_content_hash,
            "physicalRequestCount": 1,
            "newPhysicalRequestCount": new_physical_request_count,
            "replayedPhysicalRequestCount": replayed_physical_request_count,
            "retryLimit": 0,
            "responseBodySha256": binding.response_body_sha256,
            "responseHeadersHash": binding.response_headers_hash,
            "terminalEventHash": binding.terminal_event_hash,
            "runtimeUserAgentValuePersisted": False,
            "runtimeUserAgentValueHashed": False,
            "rawResponseContentIncluded": False,
        }
    )


def validate_sec_repair_storage_binding_v161(
    value: SecRepairStorageBindingV161,
) -> None:
    if type(value) is not SecRepairStorageBindingV161:
        raise SecResponseRepairStop("SEC_V161_STORAGE_BINDING_TYPE_INVALID")
    if (
        type(value.run_id) is not str
        or not value.run_id
        or value.run_id != value.run_id.strip()
        or any(character in value.run_id for character in "\x00\r\n/\\")
        or any(
            not _UPPER_SHA256.fullmatch(item)
            for item in (
                value.authorization_content_hash,
                value.send_execution_result_content_hash,
                value.replay_execution_result_content_hash,
                value.manifest_file_sha256,
                value.manifest_content_hash,
                value.request_identity,
                value.intent_file_sha256,
                value.intent_event_hash,
                value.completed_file_sha256,
                value.terminal_event_hash,
                value.response_body_sha256,
                value.response_headers_hash,
            )
        )
        or type(value.response_body_byte_count) is not int
        or not 0 < value.response_body_byte_count <= 4 * 1024 * 1024
    ):
        raise SecResponseRepairStop("SEC_V161_STORAGE_BINDING_INVALID")
    if (
        value.send_execution_result_content_hash
        != _execution_result_content_hash(
            value,
            new_physical_request_count=1,
            replayed_physical_request_count=0,
        )
        or value.replay_execution_result_content_hash
        != _execution_result_content_hash(
            value,
            new_physical_request_count=0,
            replayed_physical_request_count=1,
        )
    ):
        raise SecResponseRepairStop("SEC_V161_EXECUTION_RESULT_HASH_RECONSTRUCTION_DRIFT")


def _read_exact_json(path: Path, *, file_hash: str, code: str) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise SecResponseRepairStop(f"{code}_MISSING")
    raw = path.read_bytes()
    if _sha256_bytes(raw) != file_hash:
        raise SecResponseRepairStop(f"{code}_FILE_HASH_DRIFT")
    value = _strict_json_loads(raw, code=code)
    if type(value) is not dict:
        raise SecResponseRepairStop(f"{code}_SCHEMA_INVALID")
    return value


def _validate_event_hash(value: dict[str, Any], expected: str, code: str) -> None:
    if value.get("eventHash") != expected:
        raise SecResponseRepairStop(f"{code}_EVENT_HASH_DRIFT")
    body = {key: item for key, item in value.items() if key != "eventHash"}
    if canonical_hash(body) != expected:
        raise SecResponseRepairStop(f"{code}_CANONICAL_HASH_DRIFT")


def replay_sec_response_repair_storage_v161(
    storage_root: Path,
    binding: SecRepairStorageBindingV161,
    *,
    test_only: bool,
) -> tuple[SecResponseReviewV161, SecResponseRepairAcceptanceV161]:
    """Rebuild v1.6.1 only from an exact already-completed private run."""

    validate_sec_repair_storage_binding_v161(binding)
    try:
        root = validate_private_storage_root(storage_root, test_only=test_only)
    except AcquisitionStop as error:
        raise SecResponseRepairStop(error.code) from error
    run_root = root / EXECUTION_CONTRACT_VERSION / binding.run_id
    if not run_root.is_dir() or run_root.is_symlink():
        raise SecResponseRepairStop("SEC_V161_COMPLETED_RUN_MISSING")
    allowed_top = {".lock", "plan-authorization.json", "journal", "_private"}
    if any(item.name not in allowed_top or item.is_symlink() for item in run_root.iterdir()):
        raise SecResponseRepairStop("SEC_V161_RUN_ORPHAN_OR_SYMLINK_DRIFT")

    manifest = _read_exact_json(
        run_root / "plan-authorization.json",
        file_hash=binding.manifest_file_sha256,
        code="SEC_V161_MANIFEST",
    )
    manifest_body = {key: item for key, item in manifest.items() if key != "contentHash"}
    if (
        manifest.get("contentHash") != binding.manifest_content_hash
        or canonical_hash(manifest_body) != binding.manifest_content_hash
        or manifest.get("executionContractVersion") != EXECUTION_CONTRACT_VERSION
        or manifest.get("runId") != binding.run_id
        or manifest.get("stage8cContractContentHash")
        != STAGE8C_V16_CONTRACT_CONTENT_HASH
        or manifest.get("requestContractContentHash")
        != SEC_REQUEST_CONTRACT_CONTENT_HASH
        or manifest.get("authorizationContentHash")
        != binding.authorization_content_hash
        or manifest.get("controllerAuthorityContentHash")
        != CONTROLLER_AUTHORITY_CONTENT_HASH
        or manifest.get("authorityBasis") != AUTHORITY_BASIS
        or manifest.get("physicalRequestCount") != 1
        or manifest.get("retryLimit") != 0
        or manifest.get("automaticRetryAllowed") is not False
        or manifest.get("runtimeUserAgentValuePersisted") is not False
        or manifest.get("runtimeUserAgentValueHashed") is not False
        or not isinstance(manifest.get("request"), dict)
        or manifest["request"].get("requestIdentity") != binding.request_identity
        or manifest["request"].get("provider") != "SEC"
        or manifest["request"].get("method") != "GET"
        or manifest["request"].get("endpointPath")
        != "/files/company_tickers_exchange.json"
    ):
        raise SecResponseRepairStop("SEC_V161_MANIFEST_BINDING_DRIFT")

    journal_root = run_root / "journal"
    if (
        not journal_root.is_dir()
        or journal_root.is_symlink()
        or {item.name for item in journal_root.iterdir()} != {binding.request_identity}
    ):
        raise SecResponseRepairStop("SEC_V161_JOURNAL_ROOT_DRIFT")
    request_root = journal_root / binding.request_identity
    if request_root.is_symlink() or {item.name for item in request_root.iterdir()} != {
        "001-INTENT.json",
        "002-COMPLETED.json",
    }:
        raise SecResponseRepairStop("SEC_V161_JOURNAL_EVENT_SET_DRIFT")
    intent = _read_exact_json(
        request_root / "001-INTENT.json",
        file_hash=binding.intent_file_sha256,
        code="SEC_V161_INTENT",
    )
    completed = _read_exact_json(
        request_root / "002-COMPLETED.json",
        file_hash=binding.completed_file_sha256,
        code="SEC_V161_COMPLETED",
    )
    _validate_event_hash(intent, binding.intent_event_hash, "SEC_V161_INTENT")
    _validate_event_hash(completed, binding.terminal_event_hash, "SEC_V161_COMPLETED")
    if (
        intent.get("runId") != binding.run_id
        or intent.get("authorizationContentHash") != binding.authorization_content_hash
        or intent.get("requestIdentity") != binding.request_identity
        or intent.get("sequence") != 1
        or intent.get("previousEventHash") is not None
        or intent.get("state") != "INTENT"
        or completed.get("runId") != binding.run_id
        or completed.get("authorizationContentHash")
        != binding.authorization_content_hash
        or completed.get("requestIdentity") != binding.request_identity
        or completed.get("sequence") != 2
        or completed.get("previousEventHash") != binding.intent_event_hash
        or completed.get("state") != "COMPLETED"
        or not isinstance(completed.get("detail"), dict)
    ):
        raise SecResponseRepairStop("SEC_V161_JOURNAL_CHAIN_DRIFT")
    detail = completed["detail"]
    expected_checkpoint = f"_private/checkpoints/{binding.request_identity}.bin"
    if (
        detail.get("checkpointPath") != expected_checkpoint
        or detail.get("statusCode") != 200
        or detail.get("bodySha256") != binding.response_body_sha256
        or detail.get("bodyByteCount") != binding.response_body_byte_count
        or detail.get("responseHeadersHash") != binding.response_headers_hash
        or detail.get("retryLimit") != 0
        or detail.get("automaticRetryAllowed") is not False
    ):
        raise SecResponseRepairStop("SEC_V161_COMPLETED_DETAIL_DRIFT")
    raw_headers = detail.get("responseHeaders")
    if type(raw_headers) is not list or any(
        type(item) is not list
        or len(item) != 2
        or not all(type(part) is str for part in item)
        for item in raw_headers
    ):
        raise SecResponseRepairStop("SEC_V161_RESPONSE_HEADERS_INVALID")
    if canonical_hash(raw_headers) != binding.response_headers_hash:
        raise SecResponseRepairStop("SEC_V161_RESPONSE_HEADERS_HASH_DRIFT")
    content_type = dict((item[0], item[1]) for item in raw_headers).get("content-type")
    if (
        type(content_type) is not str
        or content_type.split(";", 1)[0].strip().lower() != "application/json"
    ):
        raise SecResponseRepairStop("SEC_V161_RESPONSE_CONTENT_TYPE_INVALID")

    relative = PurePosixPath(expected_checkpoint)
    checkpoint = (run_root / relative).resolve()
    try:
        checkpoint.relative_to(run_root.resolve())
    except ValueError as error:
        raise SecResponseRepairStop("SEC_V161_CHECKPOINT_PATH_ESCAPE") from error
    private_root = run_root / "_private"
    checkpoint_root = private_root / "checkpoints"
    if (
        not private_root.is_dir()
        or private_root.is_symlink()
        or {item.name for item in private_root.iterdir()} != {"checkpoints"}
        or not checkpoint_root.is_dir()
        or checkpoint_root.is_symlink()
        or {item.name for item in checkpoint_root.iterdir()}
        != {f"{binding.request_identity}.bin"}
        or not checkpoint.is_file()
        or checkpoint.is_symlink()
    ):
        raise SecResponseRepairStop("SEC_V161_CHECKPOINT_SET_DRIFT")
    response_body = checkpoint.read_bytes()
    if (
        len(response_body) != binding.response_body_byte_count
        or _sha256_bytes(response_body) != binding.response_body_sha256
    ):
        raise SecResponseRepairStop("SEC_V161_CHECKPOINT_HASH_DRIFT")
    review = build_sec_response_review_v161(response_body)
    if review.response_body_sha256 != binding.response_body_sha256:
        raise SecResponseRepairStop("SEC_V161_REVIEW_RESPONSE_BINDING_DRIFT")
    acceptance = _seal_acceptance(binding, review)
    return review, acceptance


def replay_live_sec_response_repair_v161(
    storage_root: Path,
) -> tuple[SecResponseReviewV161, SecResponseRepairAcceptanceV161]:
    """Replay the exact live completed run with zero network access."""

    review, acceptance = replay_sec_response_repair_storage_v161(
        storage_root,
        LIVE_STORAGE_BINDING,
        test_only=False,
    )
    if (
        review.total_row_count != LIVE_TOTAL_ROW_COUNT
        or review.irrelevant_null_exchange_count
        != LIVE_IRRELEVANT_NULL_EXCHANGE_COUNT
        or review.target_record_set_hash != LIVE_TARGET_RECORD_SET_HASH
    ):
        raise SecResponseRepairStop("SEC_V161_LIVE_RESULT_DRIFT")
    return review, acceptance


def _acceptance_body(
    value: SecResponseRepairAcceptanceV161, *, include_hash: bool
) -> dict[str, object]:
    body: dict[str, object] = {
        "repairContractVersion": value.repair_contract_version,
        "runId": value.run_id,
        "predecessorContractContentHash": value.predecessor_contract_content_hash,
        "requestContractContentHash": value.request_contract_content_hash,
        "controllerAuthorityContentHash": value.controller_authority_content_hash,
        "authorityBasis": value.authority_basis,
        "originalFailureCode": value.original_failure_code,
        "repairReason": value.repair_reason,
        "storageBindingContentHash": value.storage_binding_content_hash,
        "authorizationContentHash": value.authorization_content_hash,
        "sendExecutionResultContentHash": value.send_execution_result_content_hash,
        "replayExecutionResultContentHash": value.replay_execution_result_content_hash,
        "executionResultHashProvenance": value.execution_result_hash_provenance,
        "manifestContentHash": value.manifest_content_hash,
        "requestIdentity": value.request_identity,
        "terminalEventHash": value.terminal_event_hash,
        "responseBodySha256": value.response_body_sha256,
        "responseHeadersHash": value.response_headers_hash,
        "reviewContentHash": value.review_content_hash,
        "totalRowCount": value.total_row_count,
        "irrelevantRowCount": value.irrelevant_row_count,
        "irrelevantNullExchangeCount": value.irrelevant_null_exchange_count,
        "targetRecordSetHash": value.target_record_set_hash,
        "uniqueTargetCount": value.unique_target_count,
        "supportedMappingCount": value.supported_mapping_count,
        "accepted": value.accepted,
        "decisionCode": value.decision_code,
        "canonicalOperatingMic": value.canonical_operating_mic,
        "claim": value.claim,
        "appendOnlySuccessor": value.append_only_successor,
        "postOriginalFailureObservation": value.post_original_failure_observation,
        "holdoutClaimed": value.holdout_claimed,
        "diagnosticOnly": value.diagnostic_only,
        "networkRequestsSentDuringRepair": value.network_requests_sent_during_repair,
        "retryLimit": value.retry_limit,
        "databaseReadAuthorized": value.database_read_authorized,
        "databaseWriteAuthorized": value.database_write_authorized,
        "v22WriteAuthorized": value.v22_write_authorized,
        "v24WriteAuthorized": value.v24_write_authorized,
        "projectionAuthorized": value.projection_authorized,
        "evidenceLabelUpgradeAuthorized": value.evidence_label_upgrade_authorized,
        "segmentClaimed": value.segment_claimed,
        "tierClaimed": value.tier_claimed,
        "exchangeHistoryClaimed": value.exchange_history_claimed,
        "listingFigiClaimed": value.listing_figi_claimed,
        "currencyClaimed": value.currency_claimed,
        "completedSessionClaimed": value.completed_session_claimed,
        "rawResponseContentIncluded": False,
    }
    if include_hash:
        body["contentHash"] = value.content_hash
    return body


def _seal_acceptance(
    binding: SecRepairStorageBindingV161,
    review: SecResponseReviewV161,
) -> SecResponseRepairAcceptanceV161:
    validate_sec_repair_storage_binding_v161(binding)
    validate_sec_response_review_v161(review)
    accepted = review.accepted
    provisional = SecResponseRepairAcceptanceV161(
        repair_contract_version=REPAIR_CONTRACT_VERSION,
        run_id=binding.run_id,
        predecessor_contract_content_hash=STAGE8C_V16_CONTRACT_CONTENT_HASH,
        request_contract_content_hash=SEC_REQUEST_CONTRACT_CONTENT_HASH,
        controller_authority_content_hash=CONTROLLER_AUTHORITY_CONTENT_HASH,
        authority_basis=AUTHORITY_BASIS,
        original_failure_code=ORIGINAL_FAILURE_CODE,
        repair_reason=REPAIR_REASON,
        storage_binding_content_hash=canonical_hash(_storage_binding_body(binding)),
        authorization_content_hash=binding.authorization_content_hash,
        send_execution_result_content_hash=binding.send_execution_result_content_hash,
        replay_execution_result_content_hash=(
            binding.replay_execution_result_content_hash
        ),
        execution_result_hash_provenance=EXECUTION_RESULT_HASH_PROVENANCE,
        manifest_content_hash=binding.manifest_content_hash,
        request_identity=binding.request_identity,
        terminal_event_hash=binding.terminal_event_hash,
        response_body_sha256=binding.response_body_sha256,
        response_headers_hash=binding.response_headers_hash,
        review_content_hash=review.content_hash,
        total_row_count=review.total_row_count,
        irrelevant_row_count=review.irrelevant_row_count,
        irrelevant_null_exchange_count=review.irrelevant_null_exchange_count,
        target_record_set_hash=review.target_record_set_hash,
        unique_target_count=review.unique_target_count,
        supported_mapping_count=review.supported_mapping_count,
        accepted=accepted,
        decision_code=ACCEPTED_DECISION_CODE if accepted else REJECTED_DECISION_CODE,
        canonical_operating_mic=CANONICAL_OPERATING_MIC if accepted else None,
        claim=SEC_MAPPING_CLAIM,
        append_only_successor=True,
        post_original_failure_observation=True,
        holdout_claimed=False,
        diagnostic_only=True,
        network_requests_sent_during_repair=0,
        retry_limit=0,
        database_read_authorized=False,
        database_write_authorized=False,
        v22_write_authorized=False,
        v24_write_authorized=False,
        projection_authorized=False,
        evidence_label_upgrade_authorized=False,
        segment_claimed=False,
        tier_claimed=False,
        exchange_history_claimed=False,
        listing_figi_claimed=False,
        currency_claimed=False,
        completed_session_claimed=False,
        content_hash="",
    )
    result = SecResponseRepairAcceptanceV161(
        **{
            **asdict(provisional),
            "content_hash": canonical_hash(
                _acceptance_body(provisional, include_hash=False)
            ),
        }
    )
    validate_sec_response_repair_acceptance_v161(binding, review, result)
    return result


def validate_sec_response_repair_acceptance_v161(
    binding: SecRepairStorageBindingV161,
    review: SecResponseReviewV161,
    value: SecResponseRepairAcceptanceV161,
) -> None:
    validate_sec_repair_storage_binding_v161(binding)
    validate_sec_response_review_v161(review)
    accepted = review.accepted
    if type(value) is not SecResponseRepairAcceptanceV161 or (
        value.repair_contract_version != REPAIR_CONTRACT_VERSION
        or value.run_id != binding.run_id
        or value.predecessor_contract_content_hash
        != STAGE8C_V16_CONTRACT_CONTENT_HASH
        or value.request_contract_content_hash != SEC_REQUEST_CONTRACT_CONTENT_HASH
        or value.controller_authority_content_hash
        != CONTROLLER_AUTHORITY_CONTENT_HASH
        or value.authority_basis != AUTHORITY_BASIS
        or value.original_failure_code != ORIGINAL_FAILURE_CODE
        or value.repair_reason != REPAIR_REASON
        or value.storage_binding_content_hash
        != canonical_hash(_storage_binding_body(binding))
        or value.authorization_content_hash != binding.authorization_content_hash
        or value.send_execution_result_content_hash
        != binding.send_execution_result_content_hash
        or value.replay_execution_result_content_hash
        != binding.replay_execution_result_content_hash
        or value.execution_result_hash_provenance
        != EXECUTION_RESULT_HASH_PROVENANCE
        or value.manifest_content_hash != binding.manifest_content_hash
        or value.request_identity != binding.request_identity
        or value.terminal_event_hash != binding.terminal_event_hash
        or value.response_body_sha256 != binding.response_body_sha256
        or value.response_headers_hash != binding.response_headers_hash
        or value.review_content_hash != review.content_hash
        or value.total_row_count != review.total_row_count
        or value.irrelevant_row_count != review.irrelevant_row_count
        or value.irrelevant_null_exchange_count
        != review.irrelevant_null_exchange_count
        or value.target_record_set_hash != review.target_record_set_hash
        or value.unique_target_count != review.unique_target_count
        or value.supported_mapping_count != review.supported_mapping_count
        or type(value.accepted) is not bool
        or value.accepted is not accepted
        or value.decision_code
        != (ACCEPTED_DECISION_CODE if accepted else REJECTED_DECISION_CODE)
        or value.canonical_operating_mic
        != (CANONICAL_OPERATING_MIC if accepted else None)
        or value.claim != SEC_MAPPING_CLAIM
        or value.append_only_successor is not True
        or value.post_original_failure_observation is not True
        or value.holdout_claimed is not False
        or value.diagnostic_only is not True
        or value.network_requests_sent_during_repair != 0
        or value.retry_limit != 0
        or value.database_read_authorized is not False
        or value.database_write_authorized is not False
        or value.v22_write_authorized is not False
        or value.v24_write_authorized is not False
        or value.projection_authorized is not False
        or value.evidence_label_upgrade_authorized is not False
        or value.segment_claimed is not False
        or value.tier_claimed is not False
        or value.exchange_history_claimed is not False
        or value.listing_figi_claimed is not False
        or value.currency_claimed is not False
        or value.completed_session_claimed is not False
        or not _UPPER_SHA256.fullmatch(value.content_hash)
        or value.content_hash
        != canonical_hash(_acceptance_body(value, include_hash=False))
    ):
        raise SecResponseRepairStop("SEC_V161_ACCEPTANCE_DRIFT")


def git_safe_result_artifact_v161(
    value: SecResponseRepairAcceptanceV161,
) -> dict[str, object]:
    """Emit counts/hashes and claim boundaries without raw SEC target values."""

    body: dict[str, object] = {
        "resultArtifactVersion": RESULT_ARTIFACT_VERSION,
        "recordedDate": "2026-08-02",
        "state": (
            "ACCEPTED_ENGINEERING_DIAGNOSTIC_ONLY"
            if value.accepted
            else "REJECTED_TARGET_MAPPING_INCOMPLETE"
        ),
        "interpretationAcceptance": _acceptance_body(value, include_hash=True),
    }
    body["contentHash"] = canonical_hash(body)
    return body


__all__ = [
    "ACCEPTED_DECISION_CODE",
    "LIVE_STORAGE_BINDING",
    "ORIGINAL_FAILURE_CODE",
    "REJECTED_DECISION_CODE",
    "REPAIR_CONTRACT_VERSION",
    "SecRepairStorageBindingV161",
    "SecResponseRepairAcceptanceV161",
    "SecResponseRepairStop",
    "SecResponseReviewV161",
    "build_sec_response_review_v161",
    "git_safe_result_artifact_v161",
    "replay_live_sec_response_repair_v161",
    "replay_sec_response_repair_storage_v161",
    "validate_sec_repair_storage_binding_v161",
    "validate_sec_response_repair_acceptance_v161",
    "validate_sec_response_review_v161",
]
