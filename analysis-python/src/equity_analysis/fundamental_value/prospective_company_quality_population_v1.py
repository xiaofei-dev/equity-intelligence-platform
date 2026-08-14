"""Offline Stage 8C population-metadata seal for the C5 191-member cohort.

This module reads already-controlled artifacts only.  It never performs network
or database I/O and it deliberately excludes financial values from its output.
The result is an acquisition input, not an identity adjudication and not a V24
enrollment authorization.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath
from typing import Any, Final

from equity_analysis.fundamental_value.prospective_company_quality_acquisition_v1 import (
    PopulationInputManifest,
    PopulationMember,
    seal_population_input_manifest,
    validate_population_input_manifest,
)

CONTRACT_VERSION: Final = "FV-STAGE8C-POPULATION-METADATA-v1.0.0"
MANIFEST_STATE: Final = "SEALED_IDENTITY_ACQUISITION_INPUT"
C5_MEMBER_COUNT: Final = 191
C5_RECORD_COUNT: Final = 1_804
C5_IDENTITY_SET_HASH: Final = (
    "B29306CE3B1A047C074B68FDA07149FFF72F7B2ECD2BC0D78AAD7B42692656C7"
)
C5_PRIVATE_SEAL_FILE_SHA256: Final = (
    "F96E6DE65D77D4263B52F46F605AEF9844C0A755EE7CFCD433F7AB1FB4E43B85"
)
C5_PRIVATE_SEAL_CONTENT_HASH: Final = (
    "D9BF09661416214C1FF9788D41AC9E1FD6505FB72E02C091B762DA4F98CCA712"
)
C5_COVERAGE_FILE_SHA256: Final = (
    "6136495A50D4EF99C642D1C30CA9FA3823675CDADF88870ADBD05DEE5C340B66"
)
C5_COVERAGE_CONTENT_HASH: Final = (
    "848ED7DE1A55F3EBE56B6DAB4E5BF8E347C303BF803A0FAC1F096FDA7E09DB4C"
)
CACHED_AUDIT_FILE_SHA256: Final = (
    "2AE865EA4EC446F3FBED8BC5B1BC80F669B6967988BAA74FB01A0E55DED1C027"
)
CACHED_AUDIT_CONTENT_HASH: Final = (
    "6A1739CBE0417746791F68F78D03BD36A206B3D8670DEE4837BB609924D87F1F"
)
FORMULA_AGGREGATE_FILE_SHA256: Final = (
    "2B3EE90401BB635FBB07CA977FD35D7A371CB64BB1735D070FC28268598CA9F8"
)
FORMULA_AGGREGATE_CONTENT_HASH: Final = (
    "CE0EB2F588105DA4E12F8BB763EC65B759714A2C4A6C9435C35A9F2ED9F69859"
)
KNOWN_US_ISIN_CUSIP_CONFLICT_COUNT: Final = 54
FOREIGN_ISIN_NAMESPACE_COUNT: Final = 7
MIC_COUNTS: Final = (("XNAS", 69), ("XNYS", 122))

C5_COVERAGE_PATH: Final = Path(
    "contracts/fundamental-value-historical-validation-v1/"
    "stage7c5-provider-native-company-quality-coverage.json"
)
CACHED_AUDIT_PATH: Final = Path(
    "docs/generated/provider-cached-transport-semantic-audit-v1.2.json"
)
FORMULA_AGGREGATE_PATH: Final = Path(
    "docs/generated/formula-ready-243-final-aggregate-v1.json"
)
JOURNAL_ROOT: Final = Path(
    "storage/provider-validation/scoring-inputs-v2/physical-request-journals"
)
DEFAULT_OUTPUT_PATH: Final = Path(
    "storage/fundamental-value-forward-enrollment-v1/stage8c/"
    "population-metadata-manifest-v1.json"
)

_SHA256 = re.compile(r"[0-9A-F]{64}")
_SYMBOL = re.compile(r"[A-Z0-9][A-Z0-9.-]{0,15}")
_ISIN = re.compile(r"[A-Z]{2}[A-Z0-9]{10}")
_CUSIP = re.compile(r"[A-Z0-9*@#]{9}")
_RUN_ID = re.compile(r"[0-9]{8}T[0-9]{6}Z-[0-9a-f]{12}")
_FORBIDDEN_OUTPUT_KEYS: Final = {
    "value",
    "numericValue",
    "revenue",
    "operatingIncome",
    "netIncome",
    "operatingCashFlow",
    "capitalExpenditure",
    "financials",
}
_LIMITATIONS: Final = (
    "NEW_CURRENT_METADATA_SEAL_NOT_ORIGINAL_C5_EVIDENCE",
    "C5_SOURCE_HASH_MATCH_DOES_NOT_UPGRADE_CURRENT_CHRONOLOGY",
    "FIFTY_FOUR_ISIN_CUSIP_CONFLICTS_UNRESOLVED",
    "OPENFIGI_AND_SEC_IDENTITY_ADJUDICATION_REQUIRED",
    "CURRENT_REVISION_APPROXIMATION_ONLY",
    "NO_FINANCIAL_NUMERIC_VALUES_INCLUDED",
    "NO_DURABLE_V22_UUID_PROJECTION",
    "NETWORK_NOT_AUTHORIZED",
)


class PopulationMetadataViolation(ValueError):
    """Fail-closed population metadata contract violation."""


@dataclass(frozen=True)
class SourceFileSeal:
    source_kind: str
    logical_path: str
    file_sha256: str
    canonical_content_hash: str


@dataclass(frozen=True)
class PopulationMetadataRow:
    member_ordinal: int
    security_id: str
    symbol: str
    mic: str
    isin: str
    cusip: str
    identifier_input_state: str
    reason_codes: tuple[str, ...]
    c5_source_content_hash: str
    source_run_id: str
    source_request_identity: str
    completion_event_hash: str
    completion_event_file_sha256: str
    completion_event_path: str
    fundamentals_response_file_sha256: str
    fundamentals_response_path: str
    row_content_hash: str


@dataclass(frozen=True)
class PopulationMetadataManifest:
    state: str
    test_only: bool
    c5_identity_set_hash: str
    c5_record_count: int
    source_files: tuple[SourceFileSeal, ...]
    rows: tuple[PopulationMetadataRow, ...]
    known_us_isin_cusip_conflict_count: int
    foreign_isin_namespace_count: int
    network_authorized: bool
    database_write_authorized: bool
    v24_enrollment_authorized: bool
    identity_acquisition_input_ready: bool
    limitations: tuple[str, ...]
    content_hash: str


def canonical_hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")
    ).hexdigest().upper()


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def _strict_json_bytes(raw: bytes, *, label: str) -> Any:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise PopulationMetadataViolation(f"{label}_DUPLICATE_JSON_KEY")
            result[key] = value
        return result

    try:
        return json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=reject_duplicates,
            parse_constant=lambda _value: (_ for _ in ()).throw(
                ValueError("non-finite JSON number")
            ),
        )
    except PopulationMetadataViolation:
        raise
    except (UnicodeDecodeError, ValueError) as error:
        raise PopulationMetadataViolation(f"{label}_INVALID_JSON") from error


def _strict_dict(value: object, *, label: str) -> dict[str, Any]:
    if type(value) is not dict:
        raise PopulationMetadataViolation(f"{label}_MUST_BE_OBJECT")
    return value


def _strict_list(value: object, *, label: str) -> list[Any]:
    if type(value) is not list:
        raise PopulationMetadataViolation(f"{label}_MUST_BE_ARRAY")
    return value


def _sha256(value: object, *, label: str) -> str:
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        raise PopulationMetadataViolation(f"{label}_INVALID_SHA256")
    return value


def _artifact_content_hash(payload: dict[str, Any], field: str) -> str:
    claimed = _sha256(payload.get(field), label=field)
    body = dict(payload)
    body.pop(field)
    if canonical_hash(body) != claimed:
        raise PopulationMetadataViolation(f"{field}_DRIFT")
    return claimed


def isin_checksum_valid(value: str) -> bool:
    if _ISIN.fullmatch(value) is None:
        return False
    expanded = "".join(
        str(ord(character) - 55) if character.isalpha() else character
        for character in value
    )
    total = 0
    for index, character in enumerate(reversed(expanded)):
        digit = int(character)
        if index % 2 == 1:
            digit *= 2
        total += digit // 10 + digit % 10
    return total % 10 == 0


def cusip_checksum_valid(value: str) -> bool:
    if _CUSIP.fullmatch(value) is None or not value[8].isdigit():
        return False

    def numeric(character: str) -> int:
        if character.isdigit():
            return int(character)
        if "A" <= character <= "Z":
            return ord(character) - 55
        return {"*": 36, "@": 37, "#": 38}[character]

    total = 0
    for index, character in enumerate(value[:8]):
        number = numeric(character) * (2 if index % 2 == 1 else 1)
        total += number // 10 + number % 10
    return (10 - total % 10) % 10 == int(value[8])


def _source_file_body(value: SourceFileSeal) -> dict[str, object]:
    return {
        "sourceKind": value.source_kind,
        "logicalPath": value.logical_path,
        "fileSha256": value.file_sha256,
        "canonicalContentHash": value.canonical_content_hash,
    }


def _row_body(
    value: PopulationMetadataRow, *, include_hash: bool
) -> dict[str, object]:
    body: dict[str, object] = {
        "memberOrdinal": value.member_ordinal,
        "securityId": value.security_id,
        "symbol": value.symbol,
        "mic": value.mic,
        "isin": value.isin,
        "cusip": value.cusip,
        "identifierInputState": value.identifier_input_state,
        "reasonCodes": list(value.reason_codes),
        "c5SourceContentHash": value.c5_source_content_hash,
        "sourceRunId": value.source_run_id,
        "sourceRequestIdentity": value.source_request_identity,
        "completionEventHash": value.completion_event_hash,
        "completionEventFileSha256": value.completion_event_file_sha256,
        "completionEventPath": value.completion_event_path,
        "fundamentalsResponseFileSha256": value.fundamentals_response_file_sha256,
        "fundamentalsResponsePath": value.fundamentals_response_path,
    }
    if include_hash:
        body["rowContentHash"] = value.row_content_hash
    return body


def manifest_to_dict(
    value: PopulationMetadataManifest, *, include_hash: bool = True
) -> dict[str, object]:
    body: dict[str, object] = {
        "contractVersion": CONTRACT_VERSION,
        "state": value.state,
        "claimScope": "STAGE8C_POPULATION_METADATA_INPUT_ONLY",
        "testOnly": value.test_only,
        "c5IdentitySetHash": value.c5_identity_set_hash,
        "c5RecordCount": value.c5_record_count,
        "memberCount": len(value.rows),
        "micCounts": dict(MIC_COUNTS),
        "sourceFiles": [_source_file_body(item) for item in value.source_files],
        "rows": [_row_body(item, include_hash=True) for item in value.rows],
        "knownUsIsinCusipConflictCount": (
            value.known_us_isin_cusip_conflict_count
        ),
        "foreignIsinNamespaceCount": value.foreign_isin_namespace_count,
        "networkAuthorized": value.network_authorized,
        "databaseWriteAuthorized": value.database_write_authorized,
        "v24EnrollmentAuthorized": value.v24_enrollment_authorized,
        "identityAcquisitionInputReady": value.identity_acquisition_input_ready,
        "financialNumericValuesIncluded": False,
        "limitations": list(value.limitations),
    }
    if include_hash:
        body["contentHash"] = value.content_hash
    return body


def _validate_source_file(value: SourceFileSeal) -> None:
    if type(value) is not SourceFileSeal:
        raise PopulationMetadataViolation("SOURCE_FILE_SEAL_TYPE_INVALID")
    for label, item in (
        ("SOURCE_KIND", value.source_kind),
        ("SOURCE_LOGICAL_PATH", value.logical_path),
    ):
        if type(item) is not str or not item or item != item.strip():
            raise PopulationMetadataViolation(f"{label}_INVALID")
    _sha256(value.file_sha256, label="SOURCE_FILE")
    _sha256(value.canonical_content_hash, label="SOURCE_CONTENT")


def _validate_row(value: PopulationMetadataRow) -> None:
    if type(value) is not PopulationMetadataRow:
        raise PopulationMetadataViolation("POPULATION_ROW_TYPE_INVALID")
    if type(value.member_ordinal) is not int or value.member_ordinal <= 0:
        raise PopulationMetadataViolation("MEMBER_ORDINAL_INVALID")
    if value.security_id != f"EODHD:{value.symbol}":
        raise PopulationMetadataViolation("SECURITY_SYMBOL_BINDING_DRIFT")
    if _SYMBOL.fullmatch(value.symbol) is None:
        raise PopulationMetadataViolation("SYMBOL_INVALID")
    if value.mic not in dict(MIC_COUNTS):
        raise PopulationMetadataViolation("MIC_INVALID")
    if not isin_checksum_valid(value.isin):
        raise PopulationMetadataViolation("ISIN_CHECKSUM_INVALID")
    if not cusip_checksum_valid(value.cusip):
        raise PopulationMetadataViolation("CUSIP_CHECKSUM_INVALID")
    if type(value.reason_codes) is not tuple or not value.reason_codes:
        raise PopulationMetadataViolation("REASON_CODES_INVALID")
    if len(value.reason_codes) != len(set(value.reason_codes)):
        raise PopulationMetadataViolation("REASON_CODES_DUPLICATE")
    for item in value.reason_codes:
        if type(item) is not str or not item or item != item.strip():
            raise PopulationMetadataViolation("REASON_CODE_INVALID")
    if value.isin.startswith("US") and value.isin[2:11] != value.cusip:
        expected_state = "KNOWN_PROVIDER_IDENTIFIER_CONFLICT"
        expected_reasons = (
            "ISIN_NATIONAL_COMPONENT_DIFFERS_FROM_PROVIDER_CUSIP",
            "OPENFIGI_AND_SEC_ADJUDICATION_REQUIRED",
        )
    elif not value.isin.startswith("US"):
        expected_state = "FOREIGN_ISIN_NAMESPACE_UNRESOLVED"
        expected_reasons = (
            "ISIN_NAMESPACE_NOT_US",
            "OPENFIGI_AND_SEC_ADJUDICATION_REQUIRED",
        )
    else:
        expected_state = "CHECKSUM_VALID_UNADJUDICATED"
        expected_reasons = ("OPENFIGI_AND_SEC_ADJUDICATION_REQUIRED",)
    if (
        value.identifier_input_state != expected_state
        or value.reason_codes != expected_reasons
    ):
        raise PopulationMetadataViolation("IDENTIFIER_INPUT_STATE_DRIFT")
    for label, item in (
        ("C5_SOURCE", value.c5_source_content_hash),
        ("COMPLETION_EVENT", value.completion_event_hash),
        ("COMPLETION_EVENT_FILE", value.completion_event_file_sha256),
        ("FUNDAMENTALS_RESPONSE_FILE", value.fundamentals_response_file_sha256),
        ("ROW_CONTENT", value.row_content_hash),
    ):
        _sha256(item, label=label)
    if value.c5_source_content_hash != value.fundamentals_response_file_sha256:
        raise PopulationMetadataViolation("C5_FUNDAMENTALS_SOURCE_HASH_DRIFT")
    for label, item in (("IDENTIFIER_INPUT_STATE", value.identifier_input_state),):
        if type(item) is not str or not item or item != item.strip():
            raise PopulationMetadataViolation(f"{label}_INVALID")
    if type(value.source_run_id) is not str or _RUN_ID.fullmatch(value.source_run_id) is None:
        raise PopulationMetadataViolation("SOURCE_RUN_ID_INVALID")
    _sha256(value.source_request_identity, label="SOURCE_REQUEST_IDENTITY")
    for label, item in (
        ("COMPLETION_EVENT_PATH", value.completion_event_path),
        ("FUNDAMENTALS_RESPONSE_PATH", value.fundamentals_response_path),
    ):
        if type(item) is not str or not item or item != item.strip():
            raise PopulationMetadataViolation(f"{label}_INVALID")
        parsed = PurePosixPath(item)
        if parsed.is_absolute() or ".." in parsed.parts or parsed.as_posix() != item:
            raise PopulationMetadataViolation(f"{label}_INVALID")
    if value.row_content_hash != canonical_hash(
        _row_body(value, include_hash=False)
    ):
        raise PopulationMetadataViolation("ROW_CONTENT_HASH_DRIFT")


def _assert_no_financial_values(payload: object) -> None:
    if isinstance(payload, dict):
        forbidden = _FORBIDDEN_OUTPUT_KEYS.intersection(payload)
        if forbidden:
            raise PopulationMetadataViolation("FINANCIAL_VALUE_KEY_PRESENT")
        for nested in payload.values():
            _assert_no_financial_values(nested)
    elif isinstance(payload, list):
        for nested in payload:
            _assert_no_financial_values(nested)


def seal_population_metadata_row(
    value: PopulationMetadataRow,
) -> PopulationMetadataRow:
    """Seal one already-normalized, value-free population metadata row."""

    if value.row_content_hash:
        raise PopulationMetadataViolation("UNSEALED_ROW_MUST_NOT_HAVE_CONTENT_HASH")
    result = replace(
        value,
        row_content_hash=canonical_hash(_row_body(value, include_hash=False)),
    )
    _validate_row(result)
    return result


def validate_population_metadata_manifest(value: PopulationMetadataManifest) -> None:
    if type(value) is not PopulationMetadataManifest:
        raise PopulationMetadataViolation("POPULATION_MANIFEST_TYPE_INVALID")
    if value.state != MANIFEST_STATE:
        raise PopulationMetadataViolation("POPULATION_MANIFEST_STATE_INVALID")
    if type(value.test_only) is not bool:
        raise PopulationMetadataViolation("TEST_ONLY_MUST_BE_BOOL")
    if type(value.source_files) is not tuple or len(value.source_files) != 4:
        raise PopulationMetadataViolation("SOURCE_FILE_SET_INVALID")
    if type(value.rows) is not tuple or len(value.rows) != C5_MEMBER_COUNT:
        raise PopulationMetadataViolation("MEMBER_SET_INVALID")
    if tuple(item.member_ordinal for item in value.rows) != tuple(
        range(1, C5_MEMBER_COUNT + 1)
    ):
        raise PopulationMetadataViolation("MEMBER_ORDINAL_SEQUENCE_DRIFT")
    for item in value.source_files:
        _validate_source_file(item)
    for item in value.rows:
        _validate_row(item)
    for label, items in (
        ("SECURITY_ID", [item.security_id for item in value.rows]),
        ("SYMBOL", [item.symbol for item in value.rows]),
        ("ISIN", [item.isin for item in value.rows]),
        ("CUSIP", [item.cusip for item in value.rows]),
        ("EVENT_PATH", [item.completion_event_path for item in value.rows]),
        ("RESPONSE_PATH", [item.fundamentals_response_path for item in value.rows]),
    ):
        if len(items) != len(set(items)):
            raise PopulationMetadataViolation(f"DUPLICATE_{label}")
    if tuple(sorted(Counter(item.mic for item in value.rows).items())) != MIC_COUNTS:
        raise PopulationMetadataViolation("MIC_DISTRIBUTION_DRIFT")
    identity_hash = canonical_hash(sorted(item.security_id for item in value.rows))
    if value.c5_identity_set_hash != identity_hash:
        raise PopulationMetadataViolation("C5_IDENTITY_SET_HASH_DRIFT")
    us_conflicts = sum(
        item.isin.startswith("US") and item.isin[2:11] != item.cusip
        for item in value.rows
    )
    foreign = sum(not item.isin.startswith("US") for item in value.rows)
    if value.known_us_isin_cusip_conflict_count != us_conflicts:
        raise PopulationMetadataViolation("ISIN_CUSIP_CONFLICT_COUNT_DRIFT")
    if value.foreign_isin_namespace_count != foreign:
        raise PopulationMetadataViolation("FOREIGN_ISIN_COUNT_DRIFT")
    if (
        type(value.c5_record_count) is not int
        or value.c5_record_count != C5_RECORD_COUNT
        or type(value.known_us_isin_cusip_conflict_count) is not int
        or type(value.foreign_isin_namespace_count) is not int
        or value.network_authorized is not False
        or value.database_write_authorized is not False
        or value.v24_enrollment_authorized is not False
        or value.identity_acquisition_input_ready is not True
        or value.limitations != _LIMITATIONS
    ):
        raise PopulationMetadataViolation("POPULATION_AUTHORITY_BOUNDARY_DRIFT")
    if not value.test_only:
        expected_sources = (
            (
                "C5_PRIVATE_PREDICTOR_SEAL",
                "external-controlled/stage7c5-provider-native/sealed-predictors.json",
                C5_PRIVATE_SEAL_FILE_SHA256,
                C5_PRIVATE_SEAL_CONTENT_HASH,
            ),
            (
                "C5_GIT_SAFE_COVERAGE",
                C5_COVERAGE_PATH.as_posix(),
                C5_COVERAGE_FILE_SHA256,
                C5_COVERAGE_CONTENT_HASH,
            ),
            (
                "CACHED_TRANSPORT_SEMANTIC_AUDIT",
                CACHED_AUDIT_PATH.as_posix(),
                CACHED_AUDIT_FILE_SHA256,
                CACHED_AUDIT_CONTENT_HASH,
            ),
            (
                "FORMULA_READY_AGGREGATE",
                FORMULA_AGGREGATE_PATH.as_posix(),
                FORMULA_AGGREGATE_FILE_SHA256,
                FORMULA_AGGREGATE_CONTENT_HASH,
            ),
        )
        actual_sources = tuple(
            (
                item.source_kind,
                item.logical_path,
                item.file_sha256,
                item.canonical_content_hash,
            )
            for item in value.source_files
        )
        if actual_sources != expected_sources:
            raise PopulationMetadataViolation("FROZEN_SOURCE_SET_DRIFT")
        if (
            value.c5_identity_set_hash != C5_IDENTITY_SET_HASH
            or us_conflicts != KNOWN_US_ISIN_CUSIP_CONFLICT_COUNT
            or foreign != FOREIGN_ISIN_NAMESPACE_COUNT
        ):
            raise PopulationMetadataViolation("FROZEN_POPULATION_DRIFT")
    if value.content_hash != canonical_hash(
        manifest_to_dict(value, include_hash=False)
    ):
        raise PopulationMetadataViolation("POPULATION_CONTENT_HASH_DRIFT")
    _assert_no_financial_values(manifest_to_dict(value))


def seal_population_metadata_manifest(
    *,
    rows: tuple[PopulationMetadataRow, ...],
    source_files: tuple[SourceFileSeal, ...],
    c5_identity_set_hash: str,
    test_only: bool,
) -> PopulationMetadataManifest:
    provisional = PopulationMetadataManifest(
        state=MANIFEST_STATE,
        test_only=test_only,
        c5_identity_set_hash=c5_identity_set_hash,
        c5_record_count=C5_RECORD_COUNT,
        source_files=source_files,
        rows=rows,
        known_us_isin_cusip_conflict_count=sum(
            item.isin.startswith("US") and item.isin[2:11] != item.cusip
            for item in rows
        ),
        foreign_isin_namespace_count=sum(
            not item.isin.startswith("US") for item in rows
        ),
        network_authorized=False,
        database_write_authorized=False,
        v24_enrollment_authorized=False,
        identity_acquisition_input_ready=True,
        limitations=_LIMITATIONS,
        content_hash="",
    )
    result = replace(
        provisional,
        content_hash=canonical_hash(
            manifest_to_dict(provisional, include_hash=False)
        ),
    )
    validate_population_metadata_manifest(result)
    return result


def decode_population_metadata_manifest(payload: object) -> PopulationMetadataManifest:
    """Strictly decode and revalidate a persisted Stage 8C manifest."""

    body = _strict_dict(payload, label="POPULATION_MANIFEST")
    expected_keys = {
        "contractVersion",
        "state",
        "claimScope",
        "testOnly",
        "c5IdentitySetHash",
        "c5RecordCount",
        "memberCount",
        "micCounts",
        "sourceFiles",
        "rows",
        "knownUsIsinCusipConflictCount",
        "foreignIsinNamespaceCount",
        "networkAuthorized",
        "databaseWriteAuthorized",
        "v24EnrollmentAuthorized",
        "identityAcquisitionInputReady",
        "financialNumericValuesIncluded",
        "limitations",
        "contentHash",
    }
    if set(body) != expected_keys:
        raise PopulationMetadataViolation("POPULATION_MANIFEST_SHAPE_DRIFT")
    if (
        body["contractVersion"] != CONTRACT_VERSION
        or body["claimScope"] != "STAGE8C_POPULATION_METADATA_INPUT_ONLY"
        or body["financialNumericValuesIncluded"] is not False
        or body["memberCount"] != C5_MEMBER_COUNT
        or body["micCounts"] != dict(MIC_COUNTS)
    ):
        raise PopulationMetadataViolation("POPULATION_MANIFEST_HEADER_DRIFT")
    source_values: list[SourceFileSeal] = []
    for raw in _strict_list(body["sourceFiles"], label="SOURCE_FILES"):
        source = _strict_dict(raw, label="SOURCE_FILE")
        if set(source) != {
            "sourceKind",
            "logicalPath",
            "fileSha256",
            "canonicalContentHash",
        }:
            raise PopulationMetadataViolation("SOURCE_FILE_SHAPE_DRIFT")
        source_values.append(
            SourceFileSeal(
                source_kind=source["sourceKind"],
                logical_path=source["logicalPath"],
                file_sha256=source["fileSha256"],
                canonical_content_hash=source["canonicalContentHash"],
            )
        )
    row_values: list[PopulationMetadataRow] = []
    row_keys = {
        "memberOrdinal",
        "securityId",
        "symbol",
        "mic",
        "isin",
        "cusip",
        "identifierInputState",
        "reasonCodes",
        "c5SourceContentHash",
        "sourceRunId",
        "sourceRequestIdentity",
        "completionEventHash",
        "completionEventFileSha256",
        "completionEventPath",
        "fundamentalsResponseFileSha256",
        "fundamentalsResponsePath",
        "rowContentHash",
    }
    for raw in _strict_list(body["rows"], label="ROWS"):
        row = _strict_dict(raw, label="ROW")
        if set(row) != row_keys:
            raise PopulationMetadataViolation("ROW_SHAPE_DRIFT")
        reasons = _strict_list(row["reasonCodes"], label="ROW_REASONS")
        row_values.append(
            PopulationMetadataRow(
                member_ordinal=row["memberOrdinal"],
                security_id=row["securityId"],
                symbol=row["symbol"],
                mic=row["mic"],
                isin=row["isin"],
                cusip=row["cusip"],
                identifier_input_state=row["identifierInputState"],
                reason_codes=tuple(reasons),
                c5_source_content_hash=row["c5SourceContentHash"],
                source_run_id=row["sourceRunId"],
                source_request_identity=row["sourceRequestIdentity"],
                completion_event_hash=row["completionEventHash"],
                completion_event_file_sha256=row["completionEventFileSha256"],
                completion_event_path=row["completionEventPath"],
                fundamentals_response_file_sha256=(
                    row["fundamentalsResponseFileSha256"]
                ),
                fundamentals_response_path=row["fundamentalsResponsePath"],
                row_content_hash=row["rowContentHash"],
            )
        )
    limitations = _strict_list(body["limitations"], label="LIMITATIONS")
    result = PopulationMetadataManifest(
        state=body["state"],
        test_only=body["testOnly"],
        c5_identity_set_hash=body["c5IdentitySetHash"],
        c5_record_count=body["c5RecordCount"],
        source_files=tuple(source_values),
        rows=tuple(row_values),
        known_us_isin_cusip_conflict_count=(
            body["knownUsIsinCusipConflictCount"]
        ),
        foreign_isin_namespace_count=body["foreignIsinNamespaceCount"],
        network_authorized=body["networkAuthorized"],
        database_write_authorized=body["databaseWriteAuthorized"],
        v24_enrollment_authorized=body["v24EnrollmentAuthorized"],
        identity_acquisition_input_ready=body["identityAcquisitionInputReady"],
        limitations=tuple(limitations),
        content_hash=body["contentHash"],
    )
    validate_population_metadata_manifest(result)
    return result


def load_population_metadata_manifest(path: Path) -> PopulationMetadataManifest:
    return decode_population_metadata_manifest(
        _strict_json_bytes(path.read_bytes(), label="POPULATION_MANIFEST")
    )


def _relative_source_path(path: Path, repo_root: Path, *, label: str) -> str:
    try:
        return path.resolve(strict=True).relative_to(repo_root).as_posix()
    except ValueError as error:
        raise PopulationMetadataViolation(f"{label}_PATH_ESCAPE") from error


def _source_file_seal(
    *,
    source_kind: str,
    logical_path: str,
    path: Path,
    content_field: str,
    expected_file_hash: str,
    expected_content_hash: str,
) -> tuple[SourceFileSeal, dict[str, Any]]:
    if _file_sha256(path) != expected_file_hash:
        raise PopulationMetadataViolation(f"{source_kind}_FILE_HASH_DRIFT")
    payload = _strict_dict(
        _strict_json_bytes(path.read_bytes(), label=source_kind),
        label=source_kind,
    )
    if _artifact_content_hash(payload, content_field) != expected_content_hash:
        raise PopulationMetadataViolation(f"{source_kind}_CONTENT_HASH_DRIFT")
    return (
        SourceFileSeal(
            source_kind,
            logical_path,
            expected_file_hash,
            expected_content_hash,
        ),
        payload,
    )


def _c5_sources(c5_payload: dict[str, Any]) -> tuple[dict[str, str], tuple[str, ...]]:
    if set(c5_payload) != {
        "schemaVersion",
        "contractHash",
        "validationProtocolHash",
        "minimumEligiblePerDate",
        "outcomesReadBeforeSeal",
        "records",
        "contentHash",
    }:
        raise PopulationMetadataViolation("C5_SEAL_SHAPE_DRIFT")
    if (
        c5_payload["outcomesReadBeforeSeal"] is not False
        or _artifact_content_hash(c5_payload, "contentHash")
        != C5_PRIVATE_SEAL_CONTENT_HASH
    ):
        raise PopulationMetadataViolation("C5_SEAL_CONTRACT_DRIFT")
    records = _strict_list(c5_payload["records"], label="C5_RECORDS")
    if len(records) != C5_RECORD_COUNT:
        raise PopulationMetadataViolation("C5_RECORD_COUNT_DRIFT")
    hashes: defaultdict[str, set[str]] = defaultdict(set)
    identities: set[str] = set()
    record_keys: set[tuple[str, str]] = set()
    for raw in records:
        record = _strict_dict(raw, label="C5_RECORD")
        expected_keys = {
            "securityId",
            "symbol",
            "decisionDate",
            "target",
            "dateType",
            "value",
            "sourceHash",
            "contractHash",
            "validationProtocolHash",
            "track",
            "contentHash",
        }
        if set(record) != expected_keys:
            raise PopulationMetadataViolation("C5_RECORD_SHAPE_DRIFT")
        security_id = record["securityId"]
        symbol = record["symbol"]
        if security_id != f"EODHD:{symbol}" or _SYMBOL.fullmatch(symbol) is None:
            raise PopulationMetadataViolation("C5_RECORD_IDENTITY_DRIFT")
        if record["target"] != "COMPANY_QUALITY":
            raise PopulationMetadataViolation("C5_TARGET_DRIFT")
        content_hash = record["contentHash"]
        body = dict(record)
        body.pop("contentHash")
        if canonical_hash(body) != content_hash:
            raise PopulationMetadataViolation("C5_RECORD_CONTENT_HASH_DRIFT")
        source_hash = _sha256(record["sourceHash"], label="C5_SOURCE")
        key = (security_id, record["decisionDate"])
        if key in record_keys:
            raise PopulationMetadataViolation("C5_DUPLICATE_SECURITY_DATE")
        record_keys.add(key)
        identities.add(security_id)
        hashes[symbol].add(source_hash)
    ordered_identities = tuple(sorted(identities))
    if (
        len(ordered_identities) != C5_MEMBER_COUNT
        or canonical_hash(list(ordered_identities)) != C5_IDENTITY_SET_HASH
    ):
        raise PopulationMetadataViolation("C5_IDENTITY_SET_DRIFT")
    if any(len(hashes[security_id.split(":", 1)[1]]) != 1 for security_id in identities):
        raise PopulationMetadataViolation("C5_SYMBOL_SOURCE_HASH_AMBIGUOUS")
    return (
        {symbol: next(iter(values)) for symbol, values in hashes.items()},
        ordered_identities,
    )


def _completed_event_index(
    journal_root: Path,
) -> dict[tuple[str, str], tuple[Path, dict[str, Any]]]:
    result: dict[tuple[str, str], tuple[Path, dict[str, Any]]] = {}
    for path in journal_root.glob("*/requests/*/*/*-COMPLETED.json"):
        payload = _strict_dict(
            _strict_json_bytes(path.read_bytes(), label="COMPLETION_EVENT"),
            label="COMPLETION_EVENT",
        )
        detail = payload.get("detail")
        if type(detail) is not dict:
            continue
        response_hash = detail.get("responseContentHash")
        symbol = payload.get("symbol")
        endpoint = detail.get("endpointCategory")
        if (
            endpoint != "fundamentals"
            or type(symbol) is not str
            or type(response_hash) is not str
        ):
            continue
        key = (symbol, response_hash)
        if key in result:
            raise PopulationMetadataViolation("DUPLICATE_FUNDAMENTALS_COMPLETION")
        result[key] = (path, payload)
    return result


def build_population_metadata_manifest(
    *, repo_root: Path, c5_private_seal_path: Path
) -> PopulationMetadataManifest:
    """Build the exact no-network Stage 8C 191-row population input seal."""

    repo = repo_root.resolve(strict=True)
    c5_path = c5_private_seal_path.resolve(strict=True)
    c5_file_hash = _file_sha256(c5_path)
    if c5_file_hash != C5_PRIVATE_SEAL_FILE_SHA256:
        raise PopulationMetadataViolation("C5_PRIVATE_SEAL_FILE_HASH_DRIFT")
    c5_payload = _strict_dict(
        _strict_json_bytes(c5_path.read_bytes(), label="C5_PRIVATE_SEAL"),
        label="C5_PRIVATE_SEAL",
    )
    c5_source_hashes, identities = _c5_sources(c5_payload)

    coverage_seal, coverage_payload = _source_file_seal(
        source_kind="C5_GIT_SAFE_COVERAGE",
        logical_path=C5_COVERAGE_PATH.as_posix(),
        path=repo / C5_COVERAGE_PATH,
        content_field="contentHash",
        expected_file_hash=C5_COVERAGE_FILE_SHA256,
        expected_content_hash=C5_COVERAGE_CONTENT_HASH,
    )
    if (
        coverage_payload.get("outcomesRead") is not False
        or coverage_payload.get("providerValuesIncluded") is not False
        or coverage_payload.get("predictorCheckpoint", {}).get("contentHash")
        != C5_PRIVATE_SEAL_CONTENT_HASH
    ):
        raise PopulationMetadataViolation("C5_COVERAGE_BOUNDARY_DRIFT")

    audit_seal, audit_payload = _source_file_seal(
        source_kind="CACHED_TRANSPORT_SEMANTIC_AUDIT",
        logical_path=CACHED_AUDIT_PATH.as_posix(),
        path=repo / CACHED_AUDIT_PATH,
        content_field="artifactContentHash",
        expected_file_hash=CACHED_AUDIT_FILE_SHA256,
        expected_content_hash=CACHED_AUDIT_CONTENT_HASH,
    )
    aggregate_seal, aggregate_payload = _source_file_seal(
        source_kind="FORMULA_READY_AGGREGATE",
        logical_path=FORMULA_AGGREGATE_PATH.as_posix(),
        path=repo / FORMULA_AGGREGATE_PATH,
        content_field="artifactContentHash",
        expected_file_hash=FORMULA_AGGREGATE_FILE_SHA256,
        expected_content_hash=FORMULA_AGGREGATE_CONTENT_HASH,
    )
    if (
        audit_payload.get("sourceAggregatePath")
        != FORMULA_AGGREGATE_PATH.as_posix()
        or audit_payload.get("sourceAggregateSha256")
        != FORMULA_AGGREGATE_FILE_SHA256
        or aggregate_payload.get("rawProviderValuesIncluded") is not False
        or audit_payload.get("rawProviderValuesIncluded") is not False
        or audit_payload.get("licensedResponsesIncluded") is not False
        or audit_payload.get("credentialsIncluded") is not False
    ):
        raise PopulationMetadataViolation("CACHED_SOURCE_BOUNDARY_DRIFT")

    evidence_by_symbol: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for raw in _strict_list(audit_payload.get("responseEvidence"), label="RESPONSE_EVIDENCE"):
        evidence = _strict_dict(raw, label="RESPONSE_EVIDENCE_ROW")
        if evidence.get("endpoint") != "fundamentals":
            continue
        symbols = evidence.get("symbols")
        if type(symbols) is not list or len(symbols) != 1 or type(symbols[0]) is not str:
            raise PopulationMetadataViolation("FUNDAMENTALS_EVIDENCE_SYMBOL_DRIFT")
        evidence_by_symbol[symbols[0]].append(evidence)

    journal_root = (repo / JOURNAL_ROOT).resolve(strict=True)
    event_index = _completed_event_index(journal_root)
    row_values: list[PopulationMetadataRow] = []
    for ordinal, security_id in enumerate(identities, 1):
        symbol = security_id.split(":", 1)[1]
        evidence_rows = evidence_by_symbol[symbol]
        if len(evidence_rows) != 1:
            raise PopulationMetadataViolation("FUNDAMENTALS_EVIDENCE_CARDINALITY_DRIFT")
        evidence = evidence_rows[0]
        response_hash = _sha256(
            evidence.get("responseContentHash"), label="AUDIT_RESPONSE"
        )
        if response_hash != c5_source_hashes[symbol]:
            raise PopulationMetadataViolation("C5_AUDIT_SOURCE_HASH_DRIFT")
        event_tuple = event_index.get((symbol, response_hash))
        if event_tuple is None:
            raise PopulationMetadataViolation("FUNDAMENTALS_COMPLETION_MISSING")
        event_path, event = event_tuple
        event_hash = _sha256(event.get("eventHash"), label="COMPLETION_EVENT")
        event_body = dict(event)
        event_body.pop("eventHash")
        if canonical_hash(event_body) != event_hash or event_hash != evidence.get("eventHash"):
            raise PopulationMetadataViolation("COMPLETION_EVENT_HASH_DRIFT")
        if (
            event.get("state") != "COMPLETED"
            or event.get("symbol") != symbol
            or event.get("runId") != evidence.get("runId")
        ):
            raise PopulationMetadataViolation("COMPLETION_EVENT_IDENTITY_DRIFT")
        detail = _strict_dict(event.get("detail"), label="COMPLETION_DETAIL")
        checkpoint_value = detail.get("responseCheckpointPath")
        if type(checkpoint_value) is not str or not checkpoint_value:
            raise PopulationMetadataViolation("RESPONSE_CHECKPOINT_PATH_INVALID")
        checkpoint_path = Path(checkpoint_value)
        if not checkpoint_path.is_absolute():
            checkpoint_path = repo / checkpoint_path
        checkpoint_path = checkpoint_path.resolve(strict=True)
        try:
            checkpoint_path.relative_to(journal_root)
        except ValueError as error:
            raise PopulationMetadataViolation("RESPONSE_CHECKPOINT_PATH_ESCAPE") from error
        expected_response_directory = (event_path.parent / "responses").resolve()
        if (
            checkpoint_path.parent != expected_response_directory
            or checkpoint_path.name != response_hash + ".bin"
            or event_path.parent.name != event.get("requestIdentity")
            or event_path.parent.parent.name != symbol
            or event_path.parent.parent.parent.name != "requests"
            or event_path.parent.parent.parent.parent.name != event.get("runId")
        ):
            raise PopulationMetadataViolation("COMPLETION_CHECKPOINT_BINDING_DRIFT")
        if _file_sha256(checkpoint_path) != response_hash:
            raise PopulationMetadataViolation("FUNDAMENTALS_RESPONSE_HASH_DRIFT")
        response = _strict_dict(
            _strict_json_bytes(
                checkpoint_path.read_bytes(), label="FUNDAMENTALS_RESPONSE"
            ),
            label="FUNDAMENTALS_RESPONSE",
        )
        general = _strict_dict(response.get("General"), label="GENERAL_METADATA")
        if general.get("Code") != symbol:
            raise PopulationMetadataViolation("GENERAL_SYMBOL_DRIFT")
        mic = {"NYSE": "XNYS", "NASDAQ": "XNAS"}.get(general.get("Exchange"))
        if mic is None:
            raise PopulationMetadataViolation("GENERAL_EXCHANGE_UNSUPPORTED")
        isin = general.get("ISIN")
        cusip = general.get("CUSIP")
        if type(isin) is not str or not isin_checksum_valid(isin):
            raise PopulationMetadataViolation("GENERAL_ISIN_INVALID")
        if type(cusip) is not str or not cusip_checksum_valid(cusip):
            raise PopulationMetadataViolation("GENERAL_CUSIP_INVALID")
        if isin.startswith("US") and isin[2:11] != cusip:
            state = "KNOWN_PROVIDER_IDENTIFIER_CONFLICT"
            reasons = (
                "ISIN_NATIONAL_COMPONENT_DIFFERS_FROM_PROVIDER_CUSIP",
                "OPENFIGI_AND_SEC_ADJUDICATION_REQUIRED",
            )
        elif not isin.startswith("US"):
            state = "FOREIGN_ISIN_NAMESPACE_UNRESOLVED"
            reasons = (
                "ISIN_NAMESPACE_NOT_US",
                "OPENFIGI_AND_SEC_ADJUDICATION_REQUIRED",
            )
        else:
            state = "CHECKSUM_VALID_UNADJUDICATED"
            reasons = ("OPENFIGI_AND_SEC_ADJUDICATION_REQUIRED",)
        provisional = PopulationMetadataRow(
            member_ordinal=ordinal,
            security_id=security_id,
            symbol=symbol,
            mic=mic,
            isin=isin,
            cusip=cusip,
            identifier_input_state=state,
            reason_codes=reasons,
            c5_source_content_hash=response_hash,
            source_run_id=event["runId"],
            source_request_identity=event["requestIdentity"],
            completion_event_hash=event_hash,
            completion_event_file_sha256=_file_sha256(event_path),
            completion_event_path=_relative_source_path(
                event_path, repo, label="COMPLETION_EVENT"
            ),
            fundamentals_response_file_sha256=response_hash,
            fundamentals_response_path=_relative_source_path(
                checkpoint_path, repo, label="FUNDAMENTALS_RESPONSE"
            ),
            row_content_hash="",
        )
        row_values.append(seal_population_metadata_row(provisional))

    source_files = (
        SourceFileSeal(
            "C5_PRIVATE_PREDICTOR_SEAL",
            "external-controlled/stage7c5-provider-native/sealed-predictors.json",
            c5_file_hash,
            C5_PRIVATE_SEAL_CONTENT_HASH,
        ),
        coverage_seal,
        audit_seal,
        aggregate_seal,
    )
    return seal_population_metadata_manifest(
        rows=tuple(row_values),
        source_files=source_files,
        c5_identity_set_hash=C5_IDENTITY_SET_HASH,
        test_only=False,
    )


def to_acquisition_population_input_manifest(
    value: PopulationMetadataManifest,
) -> PopulationInputManifest:
    validate_population_metadata_manifest(value)
    members = tuple(
        PopulationMember(
            member_ordinal=item.member_ordinal,
            security_id=item.security_id,
            symbol=item.symbol,
            mic=item.mic,
            isin=item.isin,
            cusip=item.cusip,
            source_content_hash="sha256:" + item.c5_source_content_hash.lower(),
        )
        for item in value.rows
    )
    result = seal_population_input_manifest(members, test_only=value.test_only)
    validate_population_input_manifest(result)
    return result


def write_population_metadata_manifest(
    value: PopulationMetadataManifest, path: Path
) -> tuple[str, bool]:
    """Write once, or verify an exact byte-for-byte replay."""

    validate_population_metadata_manifest(value)
    payload = (
        json.dumps(manifest_to_dict(value), indent=2, ensure_ascii=True) + "\n"
    ).encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as stream:
            stream.write(payload)
        replayed = False
    except FileExistsError as error:
        if path.read_bytes() != payload:
            raise PopulationMetadataViolation(
                "IMMUTABLE_MANIFEST_REPLAY_CONFLICT"
            ) from error
        replayed = True
    return hashlib.sha256(payload).hexdigest().upper(), replayed
