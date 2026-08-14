"""Read-only execution boundary for the frozen Stage 8C v1.6 DB inventory.

The runtime database URL is caller supplied and never persisted or hashed.  The
only SQL issued by an accepted attempt is the exact frozen runtime preflight
followed by the exact frozen inventory query on one connection and transaction.
libpq session options establish a read-only transaction default and a bounded
statement timeout before either query can execute.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Protocol

import psycopg
from psycopg.rows import dict_row

from equity_analysis.fundamental_value.prospective_company_quality_acquisition_v1 import (
    AcquisitionStop,
    validate_private_storage_root,
)
from equity_analysis.fundamental_value.stage8c_sec_inventory_v16 import (
    ACCEPTED_LEGACY_SECURITY_EXCHANGES,
    CANONICAL_OPERATING_MIC,
    CURRENT_TICKER_RULE,
    INVENTORY_ADOPTION_POLICY_VERSION,
    INVENTORY_AS_OF_DATE,
    INVENTORY_RESULT_SCHEMA_FIELDS,
    REQUIRED_LISTING_CURRENCY,
    REQUIRED_SECURITY_CURRENCY,
    REQUIRED_SECURITY_INSTRUMENT_TYPE,
    TARGET_DATABASE_INVENTORY_QUERY_V16,
    TARGET_TICKERS,
    InventoryReviewV16,
    Stage8CV16Stop,
    build_database_inventory_contract_v16,
    build_inventory_review_v16,
    build_stage8c_v16_contract,
    canonical_hash,
    validate_database_inventory_contract_v16,
    validate_inventory_review_v16,
    validate_stage8c_v16_contract,
)
from equity_analysis.provider_validation.execution_safety import ExecutionLease

EXECUTION_CONTRACT_VERSION = "FV-STAGE8C-TARGET-DB-INVENTORY-EXECUTION-v1.0.0"
AUTHORIZATION_VERSION = "FV-STAGE8C-TARGET-DB-INVENTORY-AUTHORIZATION-v1.0.0"
CHECKPOINT_VERSION = "FV-STAGE8C-TARGET-DB-INVENTORY-CHECKPOINT-v1.0.0"
RECEIPT_VERSION = "FV-STAGE8C-TARGET-DB-INVENTORY-RECEIPT-v1.0.0"
RUNTIME_READ_GRANT_VERSION = (
    "FV-STAGE8C-TARGET-DB-INVENTORY-RUNTIME-READ-GRANT-v1.0.0"
)
MANIFEST_VERSION = "FV-STAGE8C-TARGET-DB-INVENTORY-MANIFEST-v1.0.0"
JOURNAL_VERSION = "FV-STAGE8C-TARGET-DB-INVENTORY-JOURNAL-v1.0.0"
RUNTIME_PREFLIGHT_VERSION = (
    "FV-STAGE8C-TARGET-DB-INVENTORY-RUNTIME-PREFLIGHT-v1.0.0"
)
CONTROLLER_AUTHORITY_VERSION = (
    "FV-STAGE8C-TARGET-DB-INVENTORY-CONTROLLER-AUTHORITY-v1.0.0"
)
AUTHORITY_BASIS = "USER_EXPLICIT_BROAD_FUTURE_DATABASE_AUTHORIZATION_2026_08_02"
EXECUTION_SCOPE = "TARGET_POSTGRESQL_INVENTORY_READ_ONLY_NO_MIGRATION_NO_WRITES"
STAGE8C_V16_CONTRACT_CONTENT_HASH = (
    "9045FCFA5CC3BD63EB100522CC96D25DAFB53AB212C83047DFFC42B5215121BC"
)
DATABASE_INVENTORY_CONTRACT_CONTENT_HASH = (
    "D4B70A85BF53BBD13813AFF3DE7F1DB75E850947C456F252E38036570FC4B410"
)
DATABASE_INVENTORY_QUERY_CONTENT_HASH = (
    "EF830E6A74D07FA91897FE0684457DEAEEA349D8AE97F2736E2A920BBAFDEF7A"
)
STATEMENT_TIMEOUT_MILLISECONDS = 5_000
CONNECT_TIMEOUT_SECONDS = 5
LIBPQ_READ_ONLY_OPTIONS = (
    "-c default_transaction_read_only=on -c statement_timeout=5000"
)
REQUIRED_TARGET_SCHEMA_HEAD = "24"
RUNTIME_STATE_REVIEW_POLICY = (
    "SAME_CONNECTION_INTERNAL_PREFLIGHT_REQUIRED_NO_EXTERNAL_RECEIPT_AUTHORITY"
)
RUNTIME_PREFLIGHT_QUERY_V16 = """SELECT
    current_setting('server_version_num')::integer AS "serverVersionNum",
    (
        SELECT version
        FROM public.flyway_schema_history
        WHERE success = TRUE
        ORDER BY installed_rank DESC
        LIMIT 1
    ) AS "flywayHeadVersion",
    to_regclass('analytics.evidence_company_identity_v1')::text AS "companyIdentityTable",
    to_regclass('analytics.evidence_instrument_identity_v1')::text AS "instrumentIdentityTable",
    to_regclass('analytics.evidence_share_class_identity_v1')::text AS "shareClassIdentityTable",
    to_regclass('analytics.evidence_listing_identity_v1')::text AS "listingIdentityTable",
    to_regclass('analytics.evidence_ticker_assignment_v1')::text AS "tickerAssignmentTable",
    to_regclass('analytics.fv_cq_forward_enrollment_v1')::text AS "v24EnrollmentTable"
"""
RUNTIME_PREFLIGHT_QUERY_CONTENT_HASH = (
    "CD0719332FE7EEC9E15B4286181E36D911CF8A514A5B0F8814D90478D6B18D7F"
)
CONTROLLER_AUTHORITY_CONTENT_HASH = (
    "50E2B883DD2A25D5B48F7933AEC76F814A458242A9FF35031E37B50CAB5468EC"
)

_RUN_ID = re.compile(r"[A-Z0-9][A-Z0-9._-]{7,127}\Z")
_UPPER_SHA256 = re.compile(r"[0-9A-F]{64}\Z")
_RUN_FOLDER = "FV-STAGE8C-TARGET-DB-INVENTORY-EXECUTION-v1.0.0"
_MANIFEST_RELATIVE_PATH = "execution-manifest.json"
_EVENTS_RELATIVE_PATH = "events"
_CHECKPOINT_RELATIVE_PATH = "_private/inventory-checkpoint.json"
_PREFLIGHT_RECEIPT_RELATIVE_PATH = "_private/runtime-preflight-receipt.json"
_RUNTIME_READ_GRANT_RELATIVE_PATH = "_private/runtime-read-grant.json"
_RECEIPT_RELATIVE_PATH = "inventory-receipt.json"
_EVENT_NAME = re.compile(
    r"(?P<sequence>\d{3})-"
    r"(?P<state>INTENT|REJECTED_RUNTIME_STATE|COMPLETED)\.json\Z"
)


class TargetInventoryExecutionStop(RuntimeError):
    """Fail-closed inventory execution stop with a stable, secret-free code."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class CursorV16(Protocol):
    def __enter__(self) -> CursorV16: ...

    def __exit__(self, *args: object) -> None: ...

    def execute(self, query: str) -> object: ...

    def fetchall(self) -> list[Mapping[str, Any]]: ...


class ConnectionV16(Protocol):
    def __enter__(self) -> ConnectionV16: ...

    def __exit__(self, *args: object) -> None: ...

    def cursor(self) -> CursorV16: ...


@dataclass(frozen=True)
class TargetInventoryRuntimePreflightReceiptV16:
    receipt_version: str
    run_id: str
    controller_authority_content_hash: str
    query_content_hash: str
    server_version_num: int
    flyway_head_version: str | None
    company_identity_table: str | None
    instrument_identity_table: str | None
    share_class_identity_table: str | None
    listing_identity_table: str | None
    ticker_assignment_table: str | None
    v24_enrollment_table: str | None
    accepted: bool
    reason_codes: tuple[str, ...]
    query_execution_count: int
    test_only: bool
    database_url_persisted: bool
    database_url_hashed: bool
    inventory_authorized: bool
    content_hash: str = ""


@dataclass(frozen=True)
class TargetInventoryPhaseAuthorizationV16:
    authorization_version: str
    run_id: str
    stage8c_contract_content_hash: str
    database_inventory_contract_content_hash: str
    query_content_hash: str
    authority_basis: str
    controller_authority_content_hash: str
    execution_scope: str
    inventory_as_of_date: str
    adoption_policy_version: str
    statement_timeout_milliseconds: int
    test_only: bool
    runtime_database_state_reviewed: bool
    required_target_schema_head: str
    observed_target_schema_head: str | None
    runtime_state_review_policy: str
    runtime_preflight_receipt_content_hash: str | None
    database_read_authorized: bool
    database_write_authorized: bool
    migration_authorized: bool
    identifier_generation_authorized: bool
    content_hash: str = ""


@dataclass(frozen=True)
class TargetInventoryRuntimeReadGrantV16:
    grant_version: str
    run_id: str
    phase_authorization_content_hash: str
    runtime_preflight_receipt_content_hash: str
    same_connection_and_transaction: bool
    runtime_query_execution_count: int
    inventory_query_authorized: bool
    database_write_authorized: bool
    migration_authorized: bool
    identifier_generation_authorized: bool
    content_hash: str = ""


@dataclass(frozen=True)
class TargetInventoryExecutionReceiptV16:
    receipt_version: str
    run_id: str
    stage8c_contract_content_hash: str
    database_inventory_contract_content_hash: str
    query_content_hash: str
    authorization_content_hash: str
    inventory_as_of_date: str
    adoption_policy_version: str
    manifest_content_hash: str
    intent_event_hash: str
    runtime_preflight_receipt_content_hash: str
    runtime_preflight_receipt_file_sha256: str
    runtime_read_grant_content_hash: str
    runtime_read_grant_file_sha256: str
    checkpoint_relative_path: str
    checkpoint_content_hash: str
    checkpoint_file_sha256: str
    row_count: int
    review_content_hash: str
    runtime_query_execution_count: int
    inventory_query_execution_count: int
    write_statement_count: int
    generated_identifier_count: int
    database_url_persisted: bool
    database_url_hashed: bool
    raw_rows_in_receipt: bool
    content_hash: str = ""


def _is_upper_sha256(value: object) -> bool:
    return type(value) is str and _UPPER_SHA256.fullmatch(value) is not None


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest().upper()


def _controller_authority_body() -> dict[str, object]:
    return {
        "authorityRecordVersion": CONTROLLER_AUTHORITY_VERSION,
        "authorityBasis": AUTHORITY_BASIS,
        "executionScope": EXECUTION_SCOPE,
        "stage8cContractContentHash": STAGE8C_V16_CONTRACT_CONTENT_HASH,
        "databaseInventoryContractContentHash": (
            DATABASE_INVENTORY_CONTRACT_CONTENT_HASH
        ),
        "queryContentHash": DATABASE_INVENTORY_QUERY_CONTENT_HASH,
        "targetTickers": list(TARGET_TICKERS),
        "inventoryAsOfDate": INVENTORY_AS_OF_DATE,
        "adoptionPolicy": {
            "version": INVENTORY_ADOPTION_POLICY_VERSION,
            "acceptedLegacySecurityExchanges": list(
                ACCEPTED_LEGACY_SECURITY_EXCHANGES
            ),
            "requiredSecurityActive": True,
            "requiredSecurityInstrumentType": REQUIRED_SECURITY_INSTRUMENT_TYPE,
            "requiredSecurityCurrency": REQUIRED_SECURITY_CURRENCY,
            "requiredListingMic": CANONICAL_OPERATING_MIC,
            "requiredListingCurrency": REQUIRED_LISTING_CURRENCY,
            "registryEvidenceRequired": True,
            "currentTickerRule": CURRENT_TICKER_RULE,
        },
        "resultSchemaFields": list(INVENTORY_RESULT_SCHEMA_FIELDS),
        "transactionPolicy": {
            "defaultTransactionReadOnly": True,
            "statementTimeoutMilliseconds": STATEMENT_TIMEOUT_MILLISECONDS,
            "connectTimeoutSeconds": CONNECT_TIMEOUT_SECONDS,
            "exactStaticQueryOnly": True,
        },
        "runtimeStateReview": {
            "policy": RUNTIME_STATE_REVIEW_POLICY,
            "requiredTargetSchemaHead": REQUIRED_TARGET_SCHEMA_HEAD,
            "runtimePreflightQueryContentHash": (
                RUNTIME_PREFLIGHT_QUERY_CONTENT_HASH
            ),
            "externalPreflightReadOnly": True,
            "preflightAloneAuthorizesInventory": False,
            "sameConnectionAndTransactionRequired": True,
            "attemptAuthorizationNeverClaimsRuntimeReviewed": True,
            "externalPreflightReceiptForbiddenForInventory": True,
        },
        "databaseUrlRuntimeOnly": True,
        "databaseUrlPersisted": False,
        "databaseUrlHashed": False,
        "databaseWriteAuthorized": False,
        "migrationAuthorized": False,
        "identifierGenerationAuthorized": False,
    }


def _authorization_body(
    value: TargetInventoryPhaseAuthorizationV16, *, include_hash: bool
) -> dict[str, object]:
    body: dict[str, object] = {
        "authorizationVersion": value.authorization_version,
        "runId": value.run_id,
        "stage8cContractContentHash": value.stage8c_contract_content_hash,
        "databaseInventoryContractContentHash": (
            value.database_inventory_contract_content_hash
        ),
        "queryContentHash": value.query_content_hash,
        "authorityBasis": value.authority_basis,
        "controllerAuthorityContentHash": value.controller_authority_content_hash,
        "executionScope": value.execution_scope,
        "inventoryAsOfDate": value.inventory_as_of_date,
        "adoptionPolicyVersion": value.adoption_policy_version,
        "statementTimeoutMilliseconds": value.statement_timeout_milliseconds,
        "testOnly": value.test_only,
        "runtimeDatabaseStateReviewed": value.runtime_database_state_reviewed,
        "requiredTargetSchemaHead": value.required_target_schema_head,
        "observedTargetSchemaHead": value.observed_target_schema_head,
        "runtimeStateReviewPolicy": value.runtime_state_review_policy,
        "runtimePreflightReceiptContentHash": (
            value.runtime_preflight_receipt_content_hash
        ),
        "databaseReadAuthorized": value.database_read_authorized,
        "databaseWriteAuthorized": value.database_write_authorized,
        "migrationAuthorized": value.migration_authorized,
        "identifierGenerationAuthorized": value.identifier_generation_authorized,
    }
    if include_hash:
        body["contentHash"] = value.content_hash
    return body


def _receipt_body(
    value: TargetInventoryExecutionReceiptV16, *, include_hash: bool
) -> dict[str, object]:
    body: dict[str, object] = {
        "receiptVersion": value.receipt_version,
        "runId": value.run_id,
        "stage8cContractContentHash": value.stage8c_contract_content_hash,
        "databaseInventoryContractContentHash": (
            value.database_inventory_contract_content_hash
        ),
        "queryContentHash": value.query_content_hash,
        "authorizationContentHash": value.authorization_content_hash,
        "inventoryAsOfDate": value.inventory_as_of_date,
        "adoptionPolicyVersion": value.adoption_policy_version,
        "manifestContentHash": value.manifest_content_hash,
        "intentEventHash": value.intent_event_hash,
        "runtimePreflightReceiptContentHash": (
            value.runtime_preflight_receipt_content_hash
        ),
        "runtimePreflightReceiptFileSha256": (
            value.runtime_preflight_receipt_file_sha256
        ),
        "runtimeReadGrantContentHash": value.runtime_read_grant_content_hash,
        "runtimeReadGrantFileSha256": value.runtime_read_grant_file_sha256,
        "checkpointRelativePath": value.checkpoint_relative_path,
        "checkpointContentHash": value.checkpoint_content_hash,
        "checkpointFileSha256": value.checkpoint_file_sha256,
        "rowCount": value.row_count,
        "reviewContentHash": value.review_content_hash,
        "runtimeQueryExecutionCount": value.runtime_query_execution_count,
        "inventoryQueryExecutionCount": value.inventory_query_execution_count,
        "writeStatementCount": value.write_statement_count,
        "generatedIdentifierCount": value.generated_identifier_count,
        "databaseUrlPersisted": value.database_url_persisted,
        "databaseUrlHashed": value.database_url_hashed,
        "rawRowsInReceipt": value.raw_rows_in_receipt,
    }
    if include_hash:
        body["contentHash"] = value.content_hash
    return body


def _runtime_read_grant_body(
    value: TargetInventoryRuntimeReadGrantV16, *, include_hash: bool
) -> dict[str, object]:
    body: dict[str, object] = {
        "grantVersion": value.grant_version,
        "runId": value.run_id,
        "phaseAuthorizationContentHash": (
            value.phase_authorization_content_hash
        ),
        "runtimePreflightReceiptContentHash": (
            value.runtime_preflight_receipt_content_hash
        ),
        "sameConnectionAndTransaction": value.same_connection_and_transaction,
        "runtimeQueryExecutionCount": value.runtime_query_execution_count,
        "inventoryQueryAuthorized": value.inventory_query_authorized,
        "databaseWriteAuthorized": value.database_write_authorized,
        "migrationAuthorized": value.migration_authorized,
        "identifierGenerationAuthorized": value.identifier_generation_authorized,
    }
    if include_hash:
        body["contentHash"] = value.content_hash
    return body


def _runtime_preflight_receipt_body(
    value: TargetInventoryRuntimePreflightReceiptV16, *, include_hash: bool
) -> dict[str, object]:
    body: dict[str, object] = {
        "receiptVersion": value.receipt_version,
        "runId": value.run_id,
        "controllerAuthorityContentHash": (
            value.controller_authority_content_hash
        ),
        "queryContentHash": value.query_content_hash,
        "serverVersionNum": value.server_version_num,
        "flywayHeadVersion": value.flyway_head_version,
        "companyIdentityTable": value.company_identity_table,
        "instrumentIdentityTable": value.instrument_identity_table,
        "shareClassIdentityTable": value.share_class_identity_table,
        "listingIdentityTable": value.listing_identity_table,
        "tickerAssignmentTable": value.ticker_assignment_table,
        "v24EnrollmentTable": value.v24_enrollment_table,
        "accepted": value.accepted,
        "reasonCodes": list(value.reason_codes),
        "queryExecutionCount": value.query_execution_count,
        "testOnly": value.test_only,
        "databaseUrlPersisted": value.database_url_persisted,
        "databaseUrlHashed": value.database_url_hashed,
        "inventoryAuthorized": value.inventory_authorized,
    }
    if include_hash:
        body["contentHash"] = value.content_hash
    return body


def _runtime_preflight_reasons(
    *,
    server_version_num: object,
    flyway_head_version: object,
    actual_tables: tuple[object, ...],
) -> tuple[str, ...]:
    expected_tables = (
        "analytics.evidence_company_identity_v1",
        "analytics.evidence_instrument_identity_v1",
        "analytics.evidence_share_class_identity_v1",
        "analytics.evidence_listing_identity_v1",
        "analytics.evidence_ticker_assignment_v1",
        "analytics.fv_cq_forward_enrollment_v1",
    )
    reasons: list[str] = []
    if type(server_version_num) is not int or not 170_000 <= server_version_num < 180_000:
        reasons.append("POSTGRESQL_17_REQUIRED")
    if flyway_head_version != "24":
        reasons.append("FLYWAY_HEAD_V24_REQUIRED")
    if actual_tables[:5] != expected_tables[:5]:
        reasons.append("V22_IDENTITY_TABLES_REQUIRED")
    if actual_tables[5:] != expected_tables[5:]:
        reasons.append("V24_ENROLLMENT_MARKER_REQUIRED")
    return tuple(reasons)


def validate_target_inventory_runtime_preflight_receipt_v16(
    value: TargetInventoryRuntimePreflightReceiptV16,
) -> None:
    if type(value) is not TargetInventoryRuntimePreflightReceiptV16:
        raise TargetInventoryExecutionStop(
            "TARGET_DB_INVENTORY_RUNTIME_PREFLIGHT_RECEIPT_TYPE_INVALID"
        )
    actual_tables = (
        value.company_identity_table,
        value.instrument_identity_table,
        value.share_class_identity_table,
        value.listing_identity_table,
        value.ticker_assignment_table,
        value.v24_enrollment_table,
    )
    expected_reasons = _runtime_preflight_reasons(
        server_version_num=value.server_version_num,
        flyway_head_version=value.flyway_head_version,
        actual_tables=actual_tables,
    )
    if (
        type(value.run_id) is not str
        or _RUN_ID.fullmatch(value.run_id) is None
        or value.receipt_version != RUNTIME_PREFLIGHT_VERSION
        or value.controller_authority_content_hash
        != CONTROLLER_AUTHORITY_CONTENT_HASH
        or value.query_content_hash != RUNTIME_PREFLIGHT_QUERY_CONTENT_HASH
        or type(value.server_version_num) is not int
        or (
            value.flyway_head_version is not None
            and type(value.flyway_head_version) is not str
        )
        or any(item is not None and type(item) is not str for item in actual_tables)
        or type(value.reason_codes) is not tuple
        or value.reason_codes != expected_reasons
        or type(value.accepted) is not bool
        or value.accepted is not (not expected_reasons)
        or value.query_execution_count != 1
        or type(value.test_only) is not bool
        or value.database_url_persisted is not False
        or value.database_url_hashed is not False
        or value.inventory_authorized is not False
        or not _is_upper_sha256(value.content_hash)
        or value.content_hash
        != canonical_hash(
            _runtime_preflight_receipt_body(value, include_hash=False)
        )
    ):
        raise TargetInventoryExecutionStop(
            "TARGET_DB_INVENTORY_RUNTIME_PREFLIGHT_RECEIPT_DRIFT"
        )


def _validate_frozen_contracts() -> None:
    stage8c = build_stage8c_v16_contract()
    inventory = build_database_inventory_contract_v16()
    try:
        validate_stage8c_v16_contract(stage8c)
        validate_database_inventory_contract_v16(inventory)
    except (Stage8CV16Stop, TypeError, ValueError) as error:
        raise TargetInventoryExecutionStop(
            "TARGET_DB_INVENTORY_FROZEN_CONTRACT_INVALID"
        ) from error
    query_hash = _sha256_bytes(TARGET_DATABASE_INVENTORY_QUERY_V16.encode("utf-8"))
    preflight_query_hash = _sha256_bytes(RUNTIME_PREFLIGHT_QUERY_V16.encode("utf-8"))
    if (
        stage8c.content_hash != STAGE8C_V16_CONTRACT_CONTENT_HASH
        or inventory.content_hash != DATABASE_INVENTORY_CONTRACT_CONTENT_HASH
        or inventory.query_content_hash != DATABASE_INVENTORY_QUERY_CONTENT_HASH
        or query_hash != DATABASE_INVENTORY_QUERY_CONTENT_HASH
        or preflight_query_hash != RUNTIME_PREFLIGHT_QUERY_CONTENT_HASH
        or inventory.target_tickers != TARGET_TICKERS
        or inventory.inventory_as_of_date != INVENTORY_AS_OF_DATE
        or inventory.adoption_policy_version != INVENTORY_ADOPTION_POLICY_VERSION
        or inventory.database_read_authorized is not False
        or inventory.database_write_authorized is not False
    ):
        raise TargetInventoryExecutionStop(
            "TARGET_DB_INVENTORY_FROZEN_CONTRACT_DRIFT"
        )
    if canonical_hash(_controller_authority_body()) != CONTROLLER_AUTHORITY_CONTENT_HASH:
        raise TargetInventoryExecutionStop(
            "TARGET_DB_INVENTORY_CONTROLLER_AUTHORITY_HASH_DRIFT"
        )


def seal_target_inventory_phase_authorization_v16(
    *,
    run_id: str,
    accepted_controller_authority_content_hash: str | None = None,
    test_only: bool = False,
    runtime_preflight_receipt: object | None = None,
    database_read_authorized: bool = False,
) -> TargetInventoryPhaseAuthorizationV16:
    """Authorize one attempt, never a runtime state or inventory result."""

    _validate_frozen_contracts()
    if accepted_controller_authority_content_hash != CONTROLLER_AUTHORITY_CONTENT_HASH:
        raise TargetInventoryExecutionStop(
            "TARGET_DB_INVENTORY_CONTROLLER_AUTHORITY_HASH_REQUIRED"
        )
    if runtime_preflight_receipt is not None:
        raise TargetInventoryExecutionStop(
            "TARGET_DB_INVENTORY_EXTERNAL_PREFLIGHT_RECEIPT_FORBIDDEN"
        )
    provisional = TargetInventoryPhaseAuthorizationV16(
        authorization_version=AUTHORIZATION_VERSION,
        run_id=run_id,
        stage8c_contract_content_hash=STAGE8C_V16_CONTRACT_CONTENT_HASH,
        database_inventory_contract_content_hash=(
            DATABASE_INVENTORY_CONTRACT_CONTENT_HASH
        ),
        query_content_hash=DATABASE_INVENTORY_QUERY_CONTENT_HASH,
        authority_basis=AUTHORITY_BASIS,
        controller_authority_content_hash=CONTROLLER_AUTHORITY_CONTENT_HASH,
        execution_scope=EXECUTION_SCOPE,
        inventory_as_of_date=INVENTORY_AS_OF_DATE,
        adoption_policy_version=INVENTORY_ADOPTION_POLICY_VERSION,
        statement_timeout_milliseconds=STATEMENT_TIMEOUT_MILLISECONDS,
        test_only=test_only,
        runtime_database_state_reviewed=False,
        required_target_schema_head=REQUIRED_TARGET_SCHEMA_HEAD,
        observed_target_schema_head=None,
        runtime_state_review_policy=RUNTIME_STATE_REVIEW_POLICY,
        runtime_preflight_receipt_content_hash=None,
        database_read_authorized=database_read_authorized,
        database_write_authorized=False,
        migration_authorized=False,
        identifier_generation_authorized=False,
    )
    result = TargetInventoryPhaseAuthorizationV16(
        **{
            **asdict(provisional),
            "content_hash": canonical_hash(
                _authorization_body(provisional, include_hash=False)
            ),
        }
    )
    validate_target_inventory_phase_authorization_v16(result)
    return result


def validate_target_inventory_phase_authorization_v16(
    value: TargetInventoryPhaseAuthorizationV16,
) -> None:
    _validate_frozen_contracts()
    if type(value) is not TargetInventoryPhaseAuthorizationV16:
        raise TargetInventoryExecutionStop(
            "TARGET_DB_INVENTORY_AUTHORIZATION_TYPE_INVALID"
        )
    if (
        type(value.run_id) is not str
        or _RUN_ID.fullmatch(value.run_id) is None
        or type(value.test_only) is not bool
        or type(value.runtime_database_state_reviewed) is not bool
        or type(value.database_read_authorized) is not bool
        or value.authorization_version != AUTHORIZATION_VERSION
        or value.stage8c_contract_content_hash != STAGE8C_V16_CONTRACT_CONTENT_HASH
        or value.database_inventory_contract_content_hash
        != DATABASE_INVENTORY_CONTRACT_CONTENT_HASH
        or value.query_content_hash != DATABASE_INVENTORY_QUERY_CONTENT_HASH
        or value.authority_basis != AUTHORITY_BASIS
        or value.controller_authority_content_hash
        != CONTROLLER_AUTHORITY_CONTENT_HASH
        or value.execution_scope != EXECUTION_SCOPE
        or value.inventory_as_of_date != INVENTORY_AS_OF_DATE
        or value.adoption_policy_version != INVENTORY_ADOPTION_POLICY_VERSION
        or value.required_target_schema_head != REQUIRED_TARGET_SCHEMA_HEAD
        or value.runtime_state_review_policy != RUNTIME_STATE_REVIEW_POLICY
        or value.runtime_database_state_reviewed is not False
        or value.observed_target_schema_head is not None
        or value.runtime_preflight_receipt_content_hash is not None
        or type(value.statement_timeout_milliseconds) is not int
        or value.statement_timeout_milliseconds != STATEMENT_TIMEOUT_MILLISECONDS
        or value.database_write_authorized is not False
        or value.migration_authorized is not False
        or value.identifier_generation_authorized is not False
        or not _is_upper_sha256(value.content_hash)
        or value.content_hash
        != canonical_hash(_authorization_body(value, include_hash=False))
    ):
        raise TargetInventoryExecutionStop(
            "TARGET_DB_INVENTORY_AUTHORIZATION_BINDING_DRIFT"
        )


def _validate_receipt(
    authorization: TargetInventoryPhaseAuthorizationV16,
    receipt: TargetInventoryExecutionReceiptV16,
) -> None:
    if type(receipt) is not TargetInventoryExecutionReceiptV16:
        raise TargetInventoryExecutionStop("TARGET_DB_INVENTORY_RECEIPT_TYPE_INVALID")
    if (
        receipt.receipt_version != RECEIPT_VERSION
        or receipt.run_id != authorization.run_id
        or receipt.stage8c_contract_content_hash
        != STAGE8C_V16_CONTRACT_CONTENT_HASH
        or receipt.database_inventory_contract_content_hash
        != DATABASE_INVENTORY_CONTRACT_CONTENT_HASH
        or receipt.query_content_hash != DATABASE_INVENTORY_QUERY_CONTENT_HASH
        or receipt.authorization_content_hash != authorization.content_hash
        or receipt.inventory_as_of_date != INVENTORY_AS_OF_DATE
        or receipt.adoption_policy_version != INVENTORY_ADOPTION_POLICY_VERSION
        or not _is_upper_sha256(receipt.manifest_content_hash)
        or not _is_upper_sha256(receipt.intent_event_hash)
        or not _is_upper_sha256(
            receipt.runtime_preflight_receipt_content_hash
        )
        or not _is_upper_sha256(
            receipt.runtime_preflight_receipt_file_sha256
        )
        or not _is_upper_sha256(receipt.runtime_read_grant_content_hash)
        or not _is_upper_sha256(receipt.runtime_read_grant_file_sha256)
        or receipt.checkpoint_relative_path != _CHECKPOINT_RELATIVE_PATH
        or not _is_upper_sha256(receipt.checkpoint_content_hash)
        or not _is_upper_sha256(receipt.checkpoint_file_sha256)
        or type(receipt.row_count) is not int
        or receipt.row_count < len(TARGET_TICKERS)
        or not _is_upper_sha256(receipt.review_content_hash)
        or receipt.runtime_query_execution_count != 1
        or receipt.inventory_query_execution_count != 1
        or receipt.write_statement_count != 0
        or receipt.generated_identifier_count != 0
        or receipt.database_url_persisted is not False
        or receipt.database_url_hashed is not False
        or receipt.raw_rows_in_receipt is not False
        or not _is_upper_sha256(receipt.content_hash)
        or receipt.content_hash != canonical_hash(_receipt_body(receipt, include_hash=False))
    ):
        raise TargetInventoryExecutionStop("TARGET_DB_INVENTORY_RECEIPT_DRIFT")


def _derive_runtime_read_grant(
    authorization: TargetInventoryPhaseAuthorizationV16,
    runtime_preflight_receipt: TargetInventoryRuntimePreflightReceiptV16,
) -> TargetInventoryRuntimeReadGrantV16:
    if (
        runtime_preflight_receipt.run_id != authorization.run_id
        or runtime_preflight_receipt.test_only is not authorization.test_only
        or runtime_preflight_receipt.accepted is not True
    ):
        raise TargetInventoryExecutionStop(
            "TARGET_DB_INVENTORY_RUNTIME_PREFLIGHT_BINDING_DRIFT"
        )
    provisional = TargetInventoryRuntimeReadGrantV16(
        grant_version=RUNTIME_READ_GRANT_VERSION,
        run_id=authorization.run_id,
        phase_authorization_content_hash=authorization.content_hash,
        runtime_preflight_receipt_content_hash=(
            runtime_preflight_receipt.content_hash
        ),
        same_connection_and_transaction=True,
        runtime_query_execution_count=1,
        inventory_query_authorized=True,
        database_write_authorized=False,
        migration_authorized=False,
        identifier_generation_authorized=False,
    )
    result = TargetInventoryRuntimeReadGrantV16(
        **{
            **asdict(provisional),
            "content_hash": canonical_hash(
                _runtime_read_grant_body(provisional, include_hash=False)
            ),
        }
    )
    _validate_runtime_read_grant(
        authorization, runtime_preflight_receipt, result
    )
    return result


def _validate_runtime_read_grant(
    authorization: TargetInventoryPhaseAuthorizationV16,
    runtime_preflight_receipt: TargetInventoryRuntimePreflightReceiptV16,
    value: TargetInventoryRuntimeReadGrantV16,
) -> None:
    if (
        type(value) is not TargetInventoryRuntimeReadGrantV16
        or value.grant_version != RUNTIME_READ_GRANT_VERSION
        or value.run_id != authorization.run_id
        or value.phase_authorization_content_hash != authorization.content_hash
        or value.runtime_preflight_receipt_content_hash
        != runtime_preflight_receipt.content_hash
        or value.same_connection_and_transaction is not True
        or value.runtime_query_execution_count != 1
        or value.inventory_query_authorized is not True
        or value.database_write_authorized is not False
        or value.migration_authorized is not False
        or value.identifier_generation_authorized is not False
        or not _is_upper_sha256(value.content_hash)
        or value.content_hash
        != canonical_hash(_runtime_read_grant_body(value, include_hash=False))
    ):
        raise TargetInventoryExecutionStop(
            "TARGET_DB_INVENTORY_RUNTIME_READ_GRANT_DRIFT"
        )


def _validated_database_url(value: object) -> str:
    if (
        type(value) is not str
        or not value
        or value != value.strip(" \t\n\r\f\v")
        or "\x00" in value
    ):
        raise TargetInventoryExecutionStop("TARGET_DB_INVENTORY_DATABASE_URL_INVALID")
    return value


def _validated_storage_root(storage_root: Path, *, test_only: bool) -> Path:
    if not isinstance(storage_root, Path):
        raise TargetInventoryExecutionStop("TARGET_DB_INVENTORY_STORAGE_ROOT_INVALID")
    try:
        return validate_private_storage_root(storage_root, test_only=test_only)
    except AcquisitionStop as error:
        raise TargetInventoryExecutionStop(error.code) from error


def _assert_no_symlink(path: Path, *, stop: Path) -> None:
    current = path
    while True:
        if current.exists() and current.is_symlink():
            raise TargetInventoryExecutionStop(
                "TARGET_DB_INVENTORY_STORAGE_SYMLINK_STOP"
            )
        if current == stop or current.parent == current:
            break
        current = current.parent


def target_inventory_run_root_v16(
    storage_root: Path,
    authorization: TargetInventoryPhaseAuthorizationV16,
) -> Path:
    validate_target_inventory_phase_authorization_v16(authorization)
    return (
        storage_root.resolve()
        / "fundamental-value-forward-enrollment-v1"
        / "stage8c"
        / _RUN_FOLDER
        / authorization.run_id
    )


def _atomic_json_create(path: Path, value: dict[str, object]) -> bytes:
    encoded = _canonical_json_bytes(value) + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(encoded)
        stream.flush()
        os.fsync(stream.fileno())
    return encoded


def _strict_json_file(path: Path) -> tuple[dict[str, object], bytes]:
    def object_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, item in pairs:
            if key in result:
                raise TargetInventoryExecutionStop(
                    "TARGET_DB_INVENTORY_PRIVATE_ARTIFACT_INVALID"
                )
            result[key] = item
        return result

    try:
        if not path.is_file() or path.is_symlink():
            raise TargetInventoryExecutionStop(
                "TARGET_DB_INVENTORY_PRIVATE_ARTIFACT_INVALID"
            )
        raw = path.read_bytes()
        payload = json.loads(raw.decode("utf-8"), object_pairs_hook=object_pairs)
    except TargetInventoryExecutionStop:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise TargetInventoryExecutionStop(
            "TARGET_DB_INVENTORY_PRIVATE_ARTIFACT_INVALID"
        ) from error
    if type(payload) is not dict:
        raise TargetInventoryExecutionStop(
            "TARGET_DB_INVENTORY_PRIVATE_ARTIFACT_INVALID"
        )
    return payload, raw


def _manifest_body(
    authorization: TargetInventoryPhaseAuthorizationV16,
) -> dict[str, object]:
    return {
        "manifestVersion": MANIFEST_VERSION,
        "runId": authorization.run_id,
        "stage8cContractContentHash": STAGE8C_V16_CONTRACT_CONTENT_HASH,
        "databaseInventoryContractContentHash": (
            DATABASE_INVENTORY_CONTRACT_CONTENT_HASH
        ),
        "queryContentHash": DATABASE_INVENTORY_QUERY_CONTENT_HASH,
        "authorizationContentHash": authorization.content_hash,
        "targetTickers": list(TARGET_TICKERS),
        "inventoryAsOfDate": INVENTORY_AS_OF_DATE,
        "adoptionPolicyVersion": INVENTORY_ADOPTION_POLICY_VERSION,
        "requiredTargetSchemaHead": REQUIRED_TARGET_SCHEMA_HEAD,
        "runtimeStateReviewPolicy": RUNTIME_STATE_REVIEW_POLICY,
        "attemptAuthorizationClaimsRuntimeReviewed": False,
        "sameConnectionAndTransactionRequired": True,
        "runtimeQueryExecutionCount": 1,
        "maximumInventoryQueryExecutionCount": 1,
        "defaultTransactionReadOnly": True,
        "statementTimeoutMilliseconds": STATEMENT_TIMEOUT_MILLISECONDS,
        "connectTimeoutSeconds": CONNECT_TIMEOUT_SECONDS,
        "exactStaticQueryOnly": True,
        "databaseUrlPersisted": False,
        "databaseUrlHashed": False,
        "databaseWriteAuthorized": False,
        "migrationAuthorized": False,
        "identifierGenerationAuthorized": False,
    }


def _write_or_verify_manifest(
    authorization: TargetInventoryPhaseAuthorizationV16,
    manifest_path: Path,
) -> str:
    body = _manifest_body(authorization)
    content_hash = canonical_hash(body)
    expected = {**body, "contentHash": content_hash}
    if manifest_path.exists():
        actual, _ = _strict_json_file(manifest_path)
        if actual != expected:
            raise TargetInventoryExecutionStop(
                "TARGET_DB_INVENTORY_IMMUTABLE_MANIFEST_DRIFT"
            )
    else:
        _atomic_json_create(manifest_path, expected)
    return content_hash


def _event_body(
    authorization: TargetInventoryPhaseAuthorizationV16,
    *,
    sequence: int,
    state: str,
    previous_event_hash: str | None,
    detail: dict[str, object],
) -> dict[str, object]:
    return {
        "journalVersion": JOURNAL_VERSION,
        "runId": authorization.run_id,
        "authorizationContentHash": authorization.content_hash,
        "queryContentHash": DATABASE_INVENTORY_QUERY_CONTENT_HASH,
        "sequence": sequence,
        "state": state,
        "previousEventHash": previous_event_hash,
        "detail": detail,
    }


def _append_event(
    authorization: TargetInventoryPhaseAuthorizationV16,
    events_path: Path,
    *,
    sequence: int,
    state: str,
    previous_event_hash: str | None,
    detail: dict[str, object],
) -> dict[str, object]:
    body = _event_body(
        authorization,
        sequence=sequence,
        state=state,
        previous_event_hash=previous_event_hash,
        detail=detail,
    )
    event = {**body, "eventHash": canonical_hash(body)}
    events_path.mkdir(parents=True, exist_ok=True)
    _atomic_json_create(events_path / f"{sequence:03d}-{state}.json", event)
    return event


def _load_events(
    authorization: TargetInventoryPhaseAuthorizationV16,
    events_path: Path,
) -> tuple[dict[str, object], ...]:
    if not events_path.exists():
        return ()
    if not events_path.is_dir() or events_path.is_symlink():
        raise TargetInventoryExecutionStop("TARGET_DB_INVENTORY_JOURNAL_DRIFT")
    paths = tuple(sorted(events_path.iterdir(), key=lambda item: item.name))
    events: list[dict[str, object]] = []
    previous: str | None = None
    for expected_sequence, path in enumerate(paths, start=1):
        match = _EVENT_NAME.fullmatch(path.name)
        if match is None or not path.is_file() or path.is_symlink():
            raise TargetInventoryExecutionStop("TARGET_DB_INVENTORY_JOURNAL_DRIFT")
        event, _ = _strict_json_file(path)
        expected_keys = {
            "journalVersion",
            "runId",
            "authorizationContentHash",
            "queryContentHash",
            "sequence",
            "state",
            "previousEventHash",
            "detail",
            "eventHash",
        }
        state = match.group("state")
        body = dict(event)
        event_hash = body.pop("eventHash", None)
        if (
            set(event) != expected_keys
            or event["journalVersion"] != JOURNAL_VERSION
            or event["runId"] != authorization.run_id
            or event["authorizationContentHash"] != authorization.content_hash
            or event["queryContentHash"] != DATABASE_INVENTORY_QUERY_CONTENT_HASH
            or type(event["sequence"]) is not int
            or event["sequence"] != expected_sequence
            or int(match.group("sequence")) != expected_sequence
            or event["state"] != state
            or event["previousEventHash"] != previous
            or type(event["detail"]) is not dict
            or not _is_upper_sha256(event_hash)
            or event_hash != canonical_hash(body)
        ):
            raise TargetInventoryExecutionStop("TARGET_DB_INVENTORY_JOURNAL_DRIFT")
        previous = str(event_hash)
        events.append(event)
    if len(events) > 2:
        raise TargetInventoryExecutionStop("TARGET_DB_INVENTORY_JOURNAL_DRIFT")
    return tuple(events)


def _intent_detail(manifest_content_hash: str) -> dict[str, object]:
    return {
        "manifestContentHash": manifest_content_hash,
        "runtimePreflightQueryContentHash": RUNTIME_PREFLIGHT_QUERY_CONTENT_HASH,
        "queryContentHash": DATABASE_INVENTORY_QUERY_CONTENT_HASH,
        "requiredTargetSchemaHead": REQUIRED_TARGET_SCHEMA_HEAD,
        "intendedRuntimeQueryExecutionCount": 1,
        "maximumInventoryQueryExecutionCount": 1,
        "sameConnectionAndTransactionRequired": True,
        "writeStatementCount": 0,
        "generatedIdentifierCount": 0,
        "databaseUrlPersisted": False,
        "databaseUrlHashed": False,
    }


def _completed_detail(
    *,
    manifest_content_hash: str,
    intent_event_hash: str,
    runtime_preflight_receipt_content_hash: str,
    runtime_preflight_receipt_file_sha256: str,
    runtime_read_grant_content_hash: str,
    runtime_read_grant_file_sha256: str,
    checkpoint_content_hash: str,
    checkpoint_file_sha256: str,
    receipt_content_hash: str,
    review_content_hash: str,
    row_count: int,
) -> dict[str, object]:
    return {
        "manifestContentHash": manifest_content_hash,
        "intentEventHash": intent_event_hash,
        "runtimePreflightReceiptContentHash": (
            runtime_preflight_receipt_content_hash
        ),
        "runtimePreflightReceiptFileSha256": (
            runtime_preflight_receipt_file_sha256
        ),
        "runtimeReadGrantContentHash": runtime_read_grant_content_hash,
        "runtimeReadGrantFileSha256": runtime_read_grant_file_sha256,
        "checkpointContentHash": checkpoint_content_hash,
        "checkpointFileSha256": checkpoint_file_sha256,
        "receiptContentHash": receipt_content_hash,
        "reviewContentHash": review_content_hash,
        "rowCount": row_count,
        "runtimeQueryExecutionCount": 1,
        "inventoryQueryExecutionCount": 1,
        "writeStatementCount": 0,
        "generatedIdentifierCount": 0,
    }


def _rejected_runtime_state_detail(
    *,
    manifest_content_hash: str,
    intent_event_hash: str,
    runtime_preflight_receipt: TargetInventoryRuntimePreflightReceiptV16,
    runtime_preflight_receipt_file_sha256: str,
) -> dict[str, object]:
    return {
        "manifestContentHash": manifest_content_hash,
        "intentEventHash": intent_event_hash,
        "runtimePreflightReceiptContentHash": (
            runtime_preflight_receipt.content_hash
        ),
        "runtimePreflightReceiptFileSha256": (
            runtime_preflight_receipt_file_sha256
        ),
        "reasonCodes": list(runtime_preflight_receipt.reason_codes),
        "runtimeQueryExecutionCount": 1,
        "inventoryQueryExecutionCount": 0,
        "writeStatementCount": 0,
        "generatedIdentifierCount": 0,
    }


def _checkpoint_body(
    authorization: TargetInventoryPhaseAuthorizationV16,
    rows: tuple[dict[str, object], ...],
    *,
    runtime_preflight_receipt_content_hash: str,
    runtime_read_grant_content_hash: str,
) -> dict[str, object]:
    return {
        "checkpointVersion": CHECKPOINT_VERSION,
        "runId": authorization.run_id,
        "stage8cContractContentHash": STAGE8C_V16_CONTRACT_CONTENT_HASH,
        "databaseInventoryContractContentHash": (
            DATABASE_INVENTORY_CONTRACT_CONTENT_HASH
        ),
        "queryContentHash": DATABASE_INVENTORY_QUERY_CONTENT_HASH,
        "authorizationContentHash": authorization.content_hash,
        "runtimePreflightReceiptContentHash": (
            runtime_preflight_receipt_content_hash
        ),
        "runtimeReadGrantContentHash": runtime_read_grant_content_hash,
        "inventoryAsOfDate": INVENTORY_AS_OF_DATE,
        "adoptionPolicyVersion": INVENTORY_ADOPTION_POLICY_VERSION,
        "rowCount": len(rows),
        "rows": list(rows),
    }


def _load_checkpoint(
    authorization: TargetInventoryPhaseAuthorizationV16,
    checkpoint_path: Path,
    *,
    runtime_preflight_receipt_content_hash: str,
    runtime_read_grant_content_hash: str,
) -> tuple[tuple[dict[str, object], ...], str, str]:
    payload, raw = _strict_json_file(checkpoint_path)
    expected_keys = {
        "checkpointVersion",
        "runId",
        "stage8cContractContentHash",
        "databaseInventoryContractContentHash",
        "queryContentHash",
        "authorizationContentHash",
        "runtimePreflightReceiptContentHash",
        "runtimeReadGrantContentHash",
        "inventoryAsOfDate",
        "adoptionPolicyVersion",
        "rowCount",
        "rows",
        "contentHash",
    }
    if set(payload) != expected_keys or type(payload["rows"]) is not list:
        raise TargetInventoryExecutionStop("TARGET_DB_INVENTORY_CHECKPOINT_DRIFT")
    rows = tuple(payload["rows"])
    if any(type(row) is not dict for row in rows):
        raise TargetInventoryExecutionStop("TARGET_DB_INVENTORY_CHECKPOINT_DRIFT")
    body = dict(payload)
    content_hash = body.pop("contentHash")
    if (
        payload["checkpointVersion"] != CHECKPOINT_VERSION
        or payload["runId"] != authorization.run_id
        or payload["stage8cContractContentHash"]
        != STAGE8C_V16_CONTRACT_CONTENT_HASH
        or payload["databaseInventoryContractContentHash"]
        != DATABASE_INVENTORY_CONTRACT_CONTENT_HASH
        or payload["queryContentHash"] != DATABASE_INVENTORY_QUERY_CONTENT_HASH
        or payload["authorizationContentHash"] != authorization.content_hash
        or payload["runtimePreflightReceiptContentHash"]
        != runtime_preflight_receipt_content_hash
        or payload["runtimeReadGrantContentHash"]
        != runtime_read_grant_content_hash
        or payload["inventoryAsOfDate"] != INVENTORY_AS_OF_DATE
        or payload["adoptionPolicyVersion"] != INVENTORY_ADOPTION_POLICY_VERSION
        or type(payload["rowCount"]) is not int
        or payload["rowCount"] != len(rows)
        or not _is_upper_sha256(content_hash)
        or content_hash != canonical_hash(body)
    ):
        raise TargetInventoryExecutionStop("TARGET_DB_INVENTORY_CHECKPOINT_DRIFT")
    return rows, str(content_hash), _sha256_bytes(raw)


def _load_runtime_preflight_receipt(
    path: Path,
) -> tuple[TargetInventoryRuntimePreflightReceiptV16, str]:
    payload, raw = _strict_json_file(path)
    expected_keys = {
        "receiptVersion",
        "runId",
        "controllerAuthorityContentHash",
        "queryContentHash",
        "serverVersionNum",
        "flywayHeadVersion",
        "companyIdentityTable",
        "instrumentIdentityTable",
        "shareClassIdentityTable",
        "listingIdentityTable",
        "tickerAssignmentTable",
        "v24EnrollmentTable",
        "accepted",
        "reasonCodes",
        "queryExecutionCount",
        "testOnly",
        "databaseUrlPersisted",
        "databaseUrlHashed",
        "inventoryAuthorized",
        "contentHash",
    }
    if set(payload) != expected_keys or type(payload["reasonCodes"]) is not list:
        raise TargetInventoryExecutionStop(
            "TARGET_DB_INVENTORY_RUNTIME_PREFLIGHT_RECEIPT_DRIFT"
        )
    try:
        receipt = TargetInventoryRuntimePreflightReceiptV16(
            receipt_version=payload["receiptVersion"],
            run_id=payload["runId"],
            controller_authority_content_hash=payload[
                "controllerAuthorityContentHash"
            ],
            query_content_hash=payload["queryContentHash"],
            server_version_num=payload["serverVersionNum"],
            flyway_head_version=payload["flywayHeadVersion"],
            company_identity_table=payload["companyIdentityTable"],
            instrument_identity_table=payload["instrumentIdentityTable"],
            share_class_identity_table=payload["shareClassIdentityTable"],
            listing_identity_table=payload["listingIdentityTable"],
            ticker_assignment_table=payload["tickerAssignmentTable"],
            v24_enrollment_table=payload["v24EnrollmentTable"],
            accepted=payload["accepted"],
            reason_codes=tuple(payload["reasonCodes"]),
            query_execution_count=payload["queryExecutionCount"],
            test_only=payload["testOnly"],
            database_url_persisted=payload["databaseUrlPersisted"],
            database_url_hashed=payload["databaseUrlHashed"],
            inventory_authorized=payload["inventoryAuthorized"],
            content_hash=payload["contentHash"],
        )
    except (KeyError, TypeError) as error:
        raise TargetInventoryExecutionStop(
            "TARGET_DB_INVENTORY_RUNTIME_PREFLIGHT_RECEIPT_DRIFT"
        ) from error
    validate_target_inventory_runtime_preflight_receipt_v16(receipt)
    return receipt, _sha256_bytes(raw)


def _load_runtime_read_grant(
    authorization: TargetInventoryPhaseAuthorizationV16,
    runtime_preflight_receipt: TargetInventoryRuntimePreflightReceiptV16,
    path: Path,
) -> tuple[TargetInventoryRuntimeReadGrantV16, str]:
    payload, raw = _strict_json_file(path)
    expected_keys = {
        "grantVersion",
        "runId",
        "phaseAuthorizationContentHash",
        "runtimePreflightReceiptContentHash",
        "sameConnectionAndTransaction",
        "runtimeQueryExecutionCount",
        "inventoryQueryAuthorized",
        "databaseWriteAuthorized",
        "migrationAuthorized",
        "identifierGenerationAuthorized",
        "contentHash",
    }
    if set(payload) != expected_keys:
        raise TargetInventoryExecutionStop(
            "TARGET_DB_INVENTORY_RUNTIME_READ_GRANT_DRIFT"
        )
    try:
        grant = TargetInventoryRuntimeReadGrantV16(
            grant_version=payload["grantVersion"],
            run_id=payload["runId"],
            phase_authorization_content_hash=payload[
                "phaseAuthorizationContentHash"
            ],
            runtime_preflight_receipt_content_hash=payload[
                "runtimePreflightReceiptContentHash"
            ],
            same_connection_and_transaction=payload[
                "sameConnectionAndTransaction"
            ],
            runtime_query_execution_count=payload[
                "runtimeQueryExecutionCount"
            ],
            inventory_query_authorized=payload["inventoryQueryAuthorized"],
            database_write_authorized=payload["databaseWriteAuthorized"],
            migration_authorized=payload["migrationAuthorized"],
            identifier_generation_authorized=payload[
                "identifierGenerationAuthorized"
            ],
            content_hash=payload["contentHash"],
        )
    except (KeyError, TypeError) as error:
        raise TargetInventoryExecutionStop(
            "TARGET_DB_INVENTORY_RUNTIME_READ_GRANT_DRIFT"
        ) from error
    _validate_runtime_read_grant(
        authorization, runtime_preflight_receipt, grant
    )
    return grant, _sha256_bytes(raw)


def _load_receipt(
    authorization: TargetInventoryPhaseAuthorizationV16,
    receipt_path: Path,
) -> TargetInventoryExecutionReceiptV16:
    payload, _ = _strict_json_file(receipt_path)
    expected_keys = set(
        _receipt_body(
            TargetInventoryExecutionReceiptV16(
                receipt_version="",
                run_id="",
                stage8c_contract_content_hash="",
                database_inventory_contract_content_hash="",
                query_content_hash="",
                authorization_content_hash="",
                inventory_as_of_date="",
                adoption_policy_version="",
                manifest_content_hash="",
                intent_event_hash="",
                runtime_preflight_receipt_content_hash="",
                runtime_preflight_receipt_file_sha256="",
                runtime_read_grant_content_hash="",
                runtime_read_grant_file_sha256="",
                checkpoint_relative_path="",
                checkpoint_content_hash="",
                checkpoint_file_sha256="",
                row_count=0,
                review_content_hash="",
                runtime_query_execution_count=0,
                inventory_query_execution_count=0,
                write_statement_count=0,
                generated_identifier_count=0,
                database_url_persisted=False,
                database_url_hashed=False,
                raw_rows_in_receipt=False,
            ),
            include_hash=True,
        )
    )
    if set(payload) != expected_keys:
        raise TargetInventoryExecutionStop("TARGET_DB_INVENTORY_RECEIPT_DRIFT")
    try:
        receipt = TargetInventoryExecutionReceiptV16(
            receipt_version=payload["receiptVersion"],
            run_id=payload["runId"],
            stage8c_contract_content_hash=payload["stage8cContractContentHash"],
            database_inventory_contract_content_hash=payload[
                "databaseInventoryContractContentHash"
            ],
            query_content_hash=payload["queryContentHash"],
            authorization_content_hash=payload["authorizationContentHash"],
            inventory_as_of_date=payload["inventoryAsOfDate"],
            adoption_policy_version=payload["adoptionPolicyVersion"],
            manifest_content_hash=payload["manifestContentHash"],
            intent_event_hash=payload["intentEventHash"],
            runtime_preflight_receipt_content_hash=payload[
                "runtimePreflightReceiptContentHash"
            ],
            runtime_preflight_receipt_file_sha256=payload[
                "runtimePreflightReceiptFileSha256"
            ],
            runtime_read_grant_content_hash=payload[
                "runtimeReadGrantContentHash"
            ],
            runtime_read_grant_file_sha256=payload[
                "runtimeReadGrantFileSha256"
            ],
            checkpoint_relative_path=payload["checkpointRelativePath"],
            checkpoint_content_hash=payload["checkpointContentHash"],
            checkpoint_file_sha256=payload["checkpointFileSha256"],
            row_count=payload["rowCount"],
            review_content_hash=payload["reviewContentHash"],
            runtime_query_execution_count=payload[
                "runtimeQueryExecutionCount"
            ],
            inventory_query_execution_count=payload[
                "inventoryQueryExecutionCount"
            ],
            write_statement_count=payload["writeStatementCount"],
            generated_identifier_count=payload["generatedIdentifierCount"],
            database_url_persisted=payload["databaseUrlPersisted"],
            database_url_hashed=payload["databaseUrlHashed"],
            raw_rows_in_receipt=payload["rawRowsInReceipt"],
            content_hash=payload["contentHash"],
        )
    except (KeyError, TypeError) as error:
        raise TargetInventoryExecutionStop(
            "TARGET_DB_INVENTORY_RECEIPT_DRIFT"
        ) from error
    _validate_receipt(authorization, receipt)
    return receipt


def _build_runtime_preflight_receipt(
    *,
    run_id: str,
    test_only: bool,
    fetched: object,
) -> TargetInventoryRuntimePreflightReceiptV16:
    expected_fields = {
        "serverVersionNum",
        "flywayHeadVersion",
        "companyIdentityTable",
        "instrumentIdentityTable",
        "shareClassIdentityTable",
        "listingIdentityTable",
        "tickerAssignmentTable",
        "v24EnrollmentTable",
    }
    if (
        type(fetched) is not list
        or len(fetched) != 1
        or not isinstance(fetched[0], Mapping)
    ):
        raise TargetInventoryExecutionStop(
            "TARGET_DB_INVENTORY_RUNTIME_PREFLIGHT_RESULT_INVALID"
        )
    row = dict(fetched[0])
    if set(row) != expected_fields:
        raise TargetInventoryExecutionStop(
            "TARGET_DB_INVENTORY_RUNTIME_PREFLIGHT_RESULT_INVALID"
        )
    actual_tables = (
        row["companyIdentityTable"],
        row["instrumentIdentityTable"],
        row["shareClassIdentityTable"],
        row["listingIdentityTable"],
        row["tickerAssignmentTable"],
        row["v24EnrollmentTable"],
    )
    reasons = _runtime_preflight_reasons(
        server_version_num=row["serverVersionNum"],
        flyway_head_version=row["flywayHeadVersion"],
        actual_tables=actual_tables,
    )
    provisional = TargetInventoryRuntimePreflightReceiptV16(
        receipt_version=RUNTIME_PREFLIGHT_VERSION,
        run_id=run_id,
        controller_authority_content_hash=CONTROLLER_AUTHORITY_CONTENT_HASH,
        query_content_hash=RUNTIME_PREFLIGHT_QUERY_CONTENT_HASH,
        server_version_num=row["serverVersionNum"],
        flyway_head_version=row["flywayHeadVersion"],
        company_identity_table=row["companyIdentityTable"],
        instrument_identity_table=row["instrumentIdentityTable"],
        share_class_identity_table=row["shareClassIdentityTable"],
        listing_identity_table=row["listingIdentityTable"],
        ticker_assignment_table=row["tickerAssignmentTable"],
        v24_enrollment_table=row["v24EnrollmentTable"],
        accepted=not reasons,
        reason_codes=reasons,
        query_execution_count=1,
        test_only=test_only,
        database_url_persisted=False,
        database_url_hashed=False,
        inventory_authorized=False,
    )
    receipt = TargetInventoryRuntimePreflightReceiptV16(
        **{
            **asdict(provisional),
            "reason_codes": provisional.reason_codes,
            "content_hash": canonical_hash(
                _runtime_preflight_receipt_body(
                    provisional, include_hash=False
                )
            ),
        }
    )
    validate_target_inventory_runtime_preflight_receipt_v16(receipt)
    return receipt


def run_target_inventory_runtime_preflight_v16(
    *,
    run_id: str,
    accepted_controller_authority_content_hash: str | None,
    database_url: object,
    test_only: bool = False,
    connect_factory: Callable[..., ConnectionV16] = psycopg.connect,
) -> TargetInventoryRuntimePreflightReceiptV16:
    """Run one read-only schema/runtime query; this does not authorize inventory."""

    _validate_frozen_contracts()
    if accepted_controller_authority_content_hash != CONTROLLER_AUTHORITY_CONTENT_HASH:
        raise TargetInventoryExecutionStop(
            "TARGET_DB_INVENTORY_CONTROLLER_AUTHORITY_HASH_REQUIRED"
        )
    if type(run_id) is not str or _RUN_ID.fullmatch(run_id) is None:
        raise TargetInventoryExecutionStop(
            "TARGET_DB_INVENTORY_RUNTIME_PREFLIGHT_RUN_ID_INVALID"
        )
    if type(test_only) is not bool:
        raise TargetInventoryExecutionStop(
            "TARGET_DB_INVENTORY_RUNTIME_PREFLIGHT_TEST_FLAG_INVALID"
        )
    if not test_only and connect_factory is not psycopg.connect:
        raise TargetInventoryExecutionStop(
            "TARGET_DB_INVENTORY_PRODUCTION_CONNECT_INJECTION_BLOCKED"
        )
    validated_url = _validated_database_url(database_url)
    try:
        with connect_factory(
            validated_url,
            autocommit=False,
            row_factory=dict_row,
            connect_timeout=CONNECT_TIMEOUT_SECONDS,
            options=LIBPQ_READ_ONLY_OPTIONS,
        ) as connection:
            with connection.cursor() as cursor:
                cursor.execute(RUNTIME_PREFLIGHT_QUERY_V16)
                fetched = cursor.fetchall()
    except Exception:
        raise TargetInventoryExecutionStop(
            "TARGET_DB_INVENTORY_RUNTIME_PREFLIGHT_QUERY_FAILED"
        ) from None
    return _build_runtime_preflight_receipt(
        run_id=run_id,
        test_only=test_only,
        fetched=fetched,
    )


def _inventory_rows_from_fetched(
    fetched: object,
) -> tuple[dict[str, object], ...]:
    if type(fetched) is not list:
        raise TargetInventoryExecutionStop("TARGET_DB_INVENTORY_ROWS_INVALID")
    rows: list[dict[str, object]] = []
    for row in fetched:
        if not isinstance(row, Mapping):
            raise TargetInventoryExecutionStop("TARGET_DB_INVENTORY_ROWS_INVALID")
        rows.append(dict(row))
    return tuple(rows)


def _build_review(
    rows: tuple[dict[str, object], ...],
) -> InventoryReviewV16:
    try:
        review = build_inventory_review_v16(rows)
        validate_inventory_review_v16(review)
    except (Stage8CV16Stop, TypeError, ValueError) as error:
        code = error.code if isinstance(error, Stage8CV16Stop) else (
            "TARGET_DB_INVENTORY_REVIEW_BUILD_FAILED"
        )
        raise TargetInventoryExecutionStop(code) from error
    return review


def _replay_private_result(
    authorization: TargetInventoryPhaseAuthorizationV16,
    *,
    manifest_content_hash: str,
    events: tuple[dict[str, object], ...],
    runtime_preflight_receipt_path: Path,
    runtime_read_grant_path: Path,
    checkpoint_path: Path,
    receipt_path: Path,
) -> tuple[InventoryReviewV16, TargetInventoryExecutionReceiptV16]:
    if (
        len(events) != 2
        or events[0]["state"] != "INTENT"
        or events[1]["state"] != "COMPLETED"
        or events[0]["detail"] != _intent_detail(manifest_content_hash)
    ):
        raise TargetInventoryExecutionStop("TARGET_DB_INVENTORY_JOURNAL_DRIFT")
    runtime_preflight_receipt, preflight_file_hash = (
        _load_runtime_preflight_receipt(runtime_preflight_receipt_path)
    )
    if (
        runtime_preflight_receipt.run_id != authorization.run_id
        or runtime_preflight_receipt.test_only is not authorization.test_only
        or runtime_preflight_receipt.accepted is not True
    ):
        raise TargetInventoryExecutionStop(
            "TARGET_DB_INVENTORY_RUNTIME_PREFLIGHT_BINDING_DRIFT"
        )
    runtime_read_grant, grant_file_hash = _load_runtime_read_grant(
        authorization,
        runtime_preflight_receipt,
        runtime_read_grant_path,
    )
    rows, checkpoint_hash, checkpoint_file_hash = _load_checkpoint(
        authorization,
        checkpoint_path,
        runtime_preflight_receipt_content_hash=(
            runtime_preflight_receipt.content_hash
        ),
        runtime_read_grant_content_hash=runtime_read_grant.content_hash,
    )
    receipt = _load_receipt(authorization, receipt_path)
    review = _build_review(rows)
    expected_completed = _completed_detail(
        manifest_content_hash=manifest_content_hash,
        intent_event_hash=str(events[0]["eventHash"]),
        runtime_preflight_receipt_content_hash=(
            runtime_preflight_receipt.content_hash
        ),
        runtime_preflight_receipt_file_sha256=preflight_file_hash,
        runtime_read_grant_content_hash=runtime_read_grant.content_hash,
        runtime_read_grant_file_sha256=grant_file_hash,
        checkpoint_content_hash=checkpoint_hash,
        checkpoint_file_sha256=checkpoint_file_hash,
        receipt_content_hash=receipt.content_hash,
        review_content_hash=review.content_hash,
        row_count=len(rows),
    )
    if (
        receipt.manifest_content_hash != manifest_content_hash
        or receipt.intent_event_hash != events[0]["eventHash"]
        or receipt.runtime_preflight_receipt_content_hash
        != runtime_preflight_receipt.content_hash
        or receipt.runtime_preflight_receipt_file_sha256
        != preflight_file_hash
        or receipt.runtime_read_grant_content_hash
        != runtime_read_grant.content_hash
        or receipt.runtime_read_grant_file_sha256 != grant_file_hash
        or receipt.checkpoint_content_hash != checkpoint_hash
        or receipt.checkpoint_file_sha256 != checkpoint_file_hash
        or receipt.row_count != len(rows)
        or receipt.review_content_hash != review.content_hash
        or events[1]["previousEventHash"] != events[0]["eventHash"]
        or events[1]["detail"] != expected_completed
    ):
        raise TargetInventoryExecutionStop(
            "TARGET_DB_INVENTORY_STORAGE_REPLAY_DRIFT"
        )
    return review, receipt


def _validate_rejected_runtime_state_terminal(
    authorization: TargetInventoryPhaseAuthorizationV16,
    *,
    manifest_content_hash: str,
    events: tuple[dict[str, object], ...],
    runtime_preflight_receipt_path: Path,
) -> None:
    if (
        len(events) != 2
        or events[0]["state"] != "INTENT"
        or events[1]["state"] != "REJECTED_RUNTIME_STATE"
        or events[0]["detail"] != _intent_detail(manifest_content_hash)
        or events[1]["previousEventHash"] != events[0]["eventHash"]
    ):
        raise TargetInventoryExecutionStop("TARGET_DB_INVENTORY_JOURNAL_DRIFT")
    runtime_preflight_receipt, preflight_file_hash = (
        _load_runtime_preflight_receipt(runtime_preflight_receipt_path)
    )
    if (
        runtime_preflight_receipt.run_id != authorization.run_id
        or runtime_preflight_receipt.test_only is not authorization.test_only
        or runtime_preflight_receipt.accepted is not False
        or not runtime_preflight_receipt.reason_codes
        or events[1]["detail"]
        != _rejected_runtime_state_detail(
            manifest_content_hash=manifest_content_hash,
            intent_event_hash=str(events[0]["eventHash"]),
            runtime_preflight_receipt=runtime_preflight_receipt,
            runtime_preflight_receipt_file_sha256=preflight_file_hash,
        )
    ):
        raise TargetInventoryExecutionStop(
            "TARGET_DB_INVENTORY_REJECTED_RUNTIME_STATE_DRIFT"
        )


def execute_target_inventory_read_v16(
    authorization: TargetInventoryPhaseAuthorizationV16,
    *,
    runtime_preflight_receipt: object | None = None,
    database_url: object,
    storage_root: Path,
    connect_factory: Callable[..., ConnectionV16] = psycopg.connect,
) -> tuple[InventoryReviewV16, TargetInventoryExecutionReceiptV16]:
    """Internally preflight and query one database connection, or replay."""

    validate_target_inventory_phase_authorization_v16(authorization)
    if authorization.database_read_authorized is not True:
        raise TargetInventoryExecutionStop(
            "TARGET_DB_INVENTORY_DATABASE_READ_NOT_AUTHORIZED"
        )
    if runtime_preflight_receipt is not None:
        raise TargetInventoryExecutionStop(
            "TARGET_DB_INVENTORY_EXTERNAL_PREFLIGHT_RECEIPT_FORBIDDEN"
        )
    if not authorization.test_only and connect_factory is not psycopg.connect:
        raise TargetInventoryExecutionStop(
            "TARGET_DB_INVENTORY_PRODUCTION_CONNECT_INJECTION_BLOCKED"
        )
    validated_url = _validated_database_url(database_url)
    approved_root = _validated_storage_root(
        storage_root, test_only=authorization.test_only
    )
    run_root = target_inventory_run_root_v16(storage_root, authorization)
    _assert_no_symlink(run_root, stop=approved_root)
    run_root.mkdir(parents=True, exist_ok=True)
    if run_root.is_symlink() or run_root.resolve() != run_root:
        raise TargetInventoryExecutionStop(
            "TARGET_DB_INVENTORY_STORAGE_SYMLINK_STOP"
        )
    checkpoint_path = run_root / Path(_CHECKPOINT_RELATIVE_PATH)
    runtime_preflight_receipt_path = run_root / Path(
        _PREFLIGHT_RECEIPT_RELATIVE_PATH
    )
    runtime_read_grant_path = run_root / Path(
        _RUNTIME_READ_GRANT_RELATIVE_PATH
    )
    receipt_path = run_root / _RECEIPT_RELATIVE_PATH
    manifest_path = run_root / _MANIFEST_RELATIVE_PATH
    events_path = run_root / _EVENTS_RELATIVE_PATH
    try:
        with ExecutionLease(
            run_root / ".lock",
            f"{authorization.run_id}:{authorization.content_hash}",
            heartbeat_interval_seconds=3_600.0,
        ) as lease:
            manifest_content_hash = _write_or_verify_manifest(
                authorization, manifest_path
            )
            events = _load_events(authorization, events_path)
            preflight_exists = runtime_preflight_receipt_path.exists()
            grant_exists = runtime_read_grant_path.exists()
            checkpoint_exists = checkpoint_path.exists()
            receipt_exists = receipt_path.exists()
            if len(events) == 1:
                if (
                    events[0]["state"] != "INTENT"
                    or events[0]["detail"]
                    != _intent_detail(manifest_content_hash)
                ):
                    raise TargetInventoryExecutionStop(
                        "TARGET_DB_INVENTORY_JOURNAL_DRIFT"
                    )
                raise TargetInventoryExecutionStop(
                    "TARGET_DB_INVENTORY_UNMATCHED_INTENT_STOP"
                )
            if len(events) == 2:
                if events[1]["state"] == "REJECTED_RUNTIME_STATE":
                    if (
                        not preflight_exists
                        or grant_exists
                        or checkpoint_exists
                        or receipt_exists
                    ):
                        raise TargetInventoryExecutionStop(
                            "TARGET_DB_INVENTORY_INCOMPLETE_PRIVATE_RESULT"
                        )
                    _validate_rejected_runtime_state_terminal(
                        authorization,
                        manifest_content_hash=manifest_content_hash,
                        events=events,
                        runtime_preflight_receipt_path=(
                            runtime_preflight_receipt_path
                        ),
                    )
                    raise TargetInventoryExecutionStop(
                        "TARGET_DB_INVENTORY_RUNTIME_STATE_REJECTED"
                    )
                if not (
                    preflight_exists
                    and grant_exists
                    and checkpoint_exists
                    and receipt_exists
                ):
                    raise TargetInventoryExecutionStop(
                        "TARGET_DB_INVENTORY_INCOMPLETE_PRIVATE_RESULT"
                    )
                return _replay_private_result(
                    authorization,
                    manifest_content_hash=manifest_content_hash,
                    events=events,
                    runtime_preflight_receipt_path=(
                        runtime_preflight_receipt_path
                    ),
                    runtime_read_grant_path=runtime_read_grant_path,
                    checkpoint_path=checkpoint_path,
                    receipt_path=receipt_path,
                )
            if (
                preflight_exists
                or grant_exists
                or checkpoint_exists
                or receipt_exists
            ):
                raise TargetInventoryExecutionStop(
                    "TARGET_DB_INVENTORY_INCOMPLETE_PRIVATE_RESULT"
                )
            intent = _append_event(
                authorization,
                events_path,
                sequence=1,
                state="INTENT",
                previous_event_hash=None,
                detail=_intent_detail(manifest_content_hash),
            )
            lease.heartbeat()
            database_phase = "RUNTIME_PREFLIGHT"
            try:
                with connect_factory(
                    validated_url,
                    autocommit=False,
                    row_factory=dict_row,
                    connect_timeout=CONNECT_TIMEOUT_SECONDS,
                    options=LIBPQ_READ_ONLY_OPTIONS,
                ) as connection:
                    with connection.cursor() as cursor:
                        cursor.execute(RUNTIME_PREFLIGHT_QUERY_V16)
                        runtime_preflight_receipt = (
                            _build_runtime_preflight_receipt(
                                run_id=authorization.run_id,
                                test_only=authorization.test_only,
                                fetched=cursor.fetchall(),
                            )
                        )
                        preflight_bytes = _atomic_json_create(
                            runtime_preflight_receipt_path,
                            _runtime_preflight_receipt_body(
                                runtime_preflight_receipt,
                                include_hash=True,
                            ),
                        )
                        preflight_file_hash = _sha256_bytes(preflight_bytes)
                        if runtime_preflight_receipt.accepted is not True:
                            _append_event(
                                authorization,
                                events_path,
                                sequence=2,
                                state="REJECTED_RUNTIME_STATE",
                                previous_event_hash=str(intent["eventHash"]),
                                detail=_rejected_runtime_state_detail(
                                    manifest_content_hash=(
                                        manifest_content_hash
                                    ),
                                    intent_event_hash=str(intent["eventHash"]),
                                    runtime_preflight_receipt=(
                                        runtime_preflight_receipt
                                    ),
                                    runtime_preflight_receipt_file_sha256=(
                                        preflight_file_hash
                                    ),
                                ),
                            )
                            raise TargetInventoryExecutionStop(
                                "TARGET_DB_INVENTORY_RUNTIME_STATE_REJECTED"
                            )
                        runtime_read_grant = _derive_runtime_read_grant(
                            authorization, runtime_preflight_receipt
                        )
                        grant_bytes = _atomic_json_create(
                            runtime_read_grant_path,
                            _runtime_read_grant_body(
                                runtime_read_grant, include_hash=True
                            ),
                        )
                        grant_file_hash = _sha256_bytes(grant_bytes)
                        lease.heartbeat()
                        database_phase = "INVENTORY"
                        cursor.execute(TARGET_DATABASE_INVENTORY_QUERY_V16)
                        rows = _inventory_rows_from_fetched(cursor.fetchall())
            except TargetInventoryExecutionStop:
                raise
            except Exception:
                code = (
                    "TARGET_DB_INVENTORY_RUNTIME_PREFLIGHT_QUERY_FAILED"
                    if database_phase == "RUNTIME_PREFLIGHT"
                    else "TARGET_DB_INVENTORY_QUERY_FAILED"
                )
                raise TargetInventoryExecutionStop(code) from None
            review = _build_review(rows)
            checkpoint = _checkpoint_body(
                authorization,
                rows,
                runtime_preflight_receipt_content_hash=(
                    runtime_preflight_receipt.content_hash
                ),
                runtime_read_grant_content_hash=runtime_read_grant.content_hash,
            )
            checkpoint_hash = canonical_hash(checkpoint)
            checkpoint_payload = {**checkpoint, "contentHash": checkpoint_hash}
            checkpoint_bytes = _atomic_json_create(
                checkpoint_path, checkpoint_payload
            )
            lease.heartbeat()
            provisional_receipt = TargetInventoryExecutionReceiptV16(
                receipt_version=RECEIPT_VERSION,
                run_id=authorization.run_id,
                stage8c_contract_content_hash=STAGE8C_V16_CONTRACT_CONTENT_HASH,
                database_inventory_contract_content_hash=(
                    DATABASE_INVENTORY_CONTRACT_CONTENT_HASH
                ),
                query_content_hash=DATABASE_INVENTORY_QUERY_CONTENT_HASH,
                authorization_content_hash=authorization.content_hash,
                inventory_as_of_date=INVENTORY_AS_OF_DATE,
                adoption_policy_version=INVENTORY_ADOPTION_POLICY_VERSION,
                manifest_content_hash=manifest_content_hash,
                intent_event_hash=str(intent["eventHash"]),
                runtime_preflight_receipt_content_hash=(
                    runtime_preflight_receipt.content_hash
                ),
                runtime_preflight_receipt_file_sha256=preflight_file_hash,
                runtime_read_grant_content_hash=runtime_read_grant.content_hash,
                runtime_read_grant_file_sha256=grant_file_hash,
                checkpoint_relative_path=_CHECKPOINT_RELATIVE_PATH,
                checkpoint_content_hash=checkpoint_hash,
                checkpoint_file_sha256=_sha256_bytes(checkpoint_bytes),
                row_count=len(rows),
                review_content_hash=review.content_hash,
                runtime_query_execution_count=1,
                inventory_query_execution_count=1,
                write_statement_count=0,
                generated_identifier_count=0,
                database_url_persisted=False,
                database_url_hashed=False,
                raw_rows_in_receipt=False,
            )
            receipt = TargetInventoryExecutionReceiptV16(
                **{
                    **asdict(provisional_receipt),
                    "content_hash": canonical_hash(
                        _receipt_body(provisional_receipt, include_hash=False)
                    ),
                }
            )
            _validate_receipt(authorization, receipt)
            _atomic_json_create(
                receipt_path, _receipt_body(receipt, include_hash=True)
            )
            completed = _append_event(
                authorization,
                events_path,
                sequence=2,
                state="COMPLETED",
                previous_event_hash=str(intent["eventHash"]),
                detail=_completed_detail(
                    manifest_content_hash=manifest_content_hash,
                    intent_event_hash=str(intent["eventHash"]),
                    runtime_preflight_receipt_content_hash=(
                        runtime_preflight_receipt.content_hash
                    ),
                    runtime_preflight_receipt_file_sha256=(
                        preflight_file_hash
                    ),
                    runtime_read_grant_content_hash=(
                        runtime_read_grant.content_hash
                    ),
                    runtime_read_grant_file_sha256=grant_file_hash,
                    checkpoint_content_hash=checkpoint_hash,
                    checkpoint_file_sha256=receipt.checkpoint_file_sha256,
                    receipt_content_hash=receipt.content_hash,
                    review_content_hash=review.content_hash,
                    row_count=len(rows),
                ),
            )
            if completed["previousEventHash"] != intent["eventHash"]:
                raise TargetInventoryExecutionStop(
                    "TARGET_DB_INVENTORY_JOURNAL_DRIFT"
                )
            lease.heartbeat()
            events = _load_events(authorization, events_path)
            replay_review, replay_receipt = _replay_private_result(
                authorization,
                manifest_content_hash=manifest_content_hash,
                events=events,
                runtime_preflight_receipt_path=runtime_preflight_receipt_path,
                runtime_read_grant_path=runtime_read_grant_path,
                checkpoint_path=checkpoint_path,
                receipt_path=receipt_path,
            )
            if replay_review != review or replay_receipt != receipt:
                raise TargetInventoryExecutionStop(
                    "TARGET_DB_INVENTORY_POST_WRITE_REPLAY_DRIFT"
                )
            return replay_review, replay_receipt
    except TargetInventoryExecutionStop:
        raise
    except RuntimeError as error:
        raise TargetInventoryExecutionStop(str(error)) from error


__all__ = [
    "AUTHORITY_BASIS",
    "CONNECT_TIMEOUT_SECONDS",
    "CONTROLLER_AUTHORITY_CONTENT_HASH",
    "DATABASE_INVENTORY_CONTRACT_CONTENT_HASH",
    "DATABASE_INVENTORY_QUERY_CONTENT_HASH",
    "EXECUTION_CONTRACT_VERSION",
    "EXECUTION_SCOPE",
    "LIBPQ_READ_ONLY_OPTIONS",
    "RUNTIME_PREFLIGHT_QUERY_CONTENT_HASH",
    "RUNTIME_PREFLIGHT_QUERY_V16",
    "RUNTIME_READ_GRANT_VERSION",
    "STAGE8C_V16_CONTRACT_CONTENT_HASH",
    "STATEMENT_TIMEOUT_MILLISECONDS",
    "TargetInventoryExecutionReceiptV16",
    "TargetInventoryExecutionStop",
    "TargetInventoryPhaseAuthorizationV16",
    "TargetInventoryRuntimePreflightReceiptV16",
    "TargetInventoryRuntimeReadGrantV16",
    "execute_target_inventory_read_v16",
    "run_target_inventory_runtime_preflight_v16",
    "seal_target_inventory_phase_authorization_v16",
    "target_inventory_run_root_v16",
    "validate_target_inventory_phase_authorization_v16",
    "validate_target_inventory_runtime_preflight_receipt_v16",
]
