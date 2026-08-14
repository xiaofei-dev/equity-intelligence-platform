from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest
from psycopg.rows import dict_row

import equity_analysis.fundamental_value.stage8c_target_inventory_execution_v16 as execution_module
from equity_analysis.fundamental_value.prospective_company_quality_acquisition_v1 import (
    private_storage_marker_payload,
)
from equity_analysis.fundamental_value.stage8c_sec_inventory_v16 import (
    INVENTORY_RESULT_SCHEMA_FIELDS,
    TARGET_DATABASE_INVENTORY_QUERY_V16,
    InventoryAdoptionState,
    canonical_hash,
)
from equity_analysis.fundamental_value.stage8c_target_inventory_execution_v16 import (
    CONNECT_TIMEOUT_SECONDS,
    CONTROLLER_AUTHORITY_CONTENT_HASH,
    DATABASE_INVENTORY_QUERY_CONTENT_HASH,
    LIBPQ_READ_ONLY_OPTIONS,
    RUNTIME_PREFLIGHT_QUERY_CONTENT_HASH,
    RUNTIME_PREFLIGHT_QUERY_V16,
    TargetInventoryExecutionStop,
    TargetInventoryRuntimePreflightReceiptV16,
    execute_target_inventory_read_v16,
    run_target_inventory_runtime_preflight_v16,
    seal_target_inventory_phase_authorization_v16,
    target_inventory_run_root_v16,
    validate_target_inventory_phase_authorization_v16,
    validate_target_inventory_runtime_preflight_receipt_v16,
)


class _FakeCursor:
    def __init__(
        self,
        responses: list[list[dict[str, object]]],
        *,
        fail_on_execute: dict[int, Exception] | None = None,
    ) -> None:
        self.responses = responses
        self.fail_on_execute = fail_on_execute or {}
        self.statements: list[str] = []

    def __enter__(self) -> _FakeCursor:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def execute(self, query: str) -> None:
        self.statements.append(query)
        error = self.fail_on_execute.get(len(self.statements))
        if error is not None:
            raise error

    def fetchall(self) -> list[dict[str, object]]:
        return self.responses[len(self.statements) - 1]


class _FakeConnection:
    def __init__(self, cursor: _FakeCursor) -> None:
        self._cursor = cursor
        self.entered = False
        self.exited = False

    def __enter__(self) -> _FakeConnection:
        self.entered = True
        return self

    def __exit__(self, *args: object) -> None:
        self.exited = True

    def cursor(self) -> _FakeCursor:
        return self._cursor


class _FakeConnect:
    def __init__(
        self,
        *responses: list[dict[str, object]],
        fail_on_execute: dict[int, Exception] | None = None,
    ) -> None:
        self.cursor = _FakeCursor(
            list(responses), fail_on_execute=fail_on_execute
        )
        self.connection = _FakeConnection(self.cursor)
        self.calls: list[tuple[str, dict[str, object]]] = []

    def __call__(self, database_url: str, **kwargs: object) -> _FakeConnection:
        self.calls.append((database_url, kwargs))
        return self.connection


def _empty_row(ordinal: int, ticker: str) -> dict[str, object]:
    row: dict[str, object] = {field: None for field in INVENTORY_RESULT_SCHEMA_FIELDS}
    row["targetOrdinal"] = ordinal
    row["targetTicker"] = ticker
    return row


def _inventory_rows() -> list[dict[str, object]]:
    return [
        _empty_row(1, "GOOG"),
        _empty_row(2, "FOX"),
        _empty_row(3, "MSFT"),
    ]


def _preflight_rows(
    *,
    server_version_num: int = 170_005,
    flyway_head_version: str = "24",
) -> list[dict[str, object]]:
    return [
        {
            "serverVersionNum": server_version_num,
            "flywayHeadVersion": flyway_head_version,
            "companyIdentityTable": "analytics.evidence_company_identity_v1",
            "instrumentIdentityTable": "analytics.evidence_instrument_identity_v1",
            "shareClassIdentityTable": (
                "analytics.evidence_share_class_identity_v1"
            ),
            "listingIdentityTable": "analytics.evidence_listing_identity_v1",
            "tickerAssignmentTable": (
                "analytics.evidence_ticker_assignment_v1"
            ),
            "v24EnrollmentTable": "analytics.fv_cq_forward_enrollment_v1",
        }
    ]


def _storage_root(tmp_path: Path) -> Path:
    root = tmp_path / "private"
    root.mkdir(parents=True)
    marker = private_storage_marker_payload(root, test_only=True)
    (root / ".fv-stage8c-private-storage.json").write_text(
        json.dumps(marker, sort_keys=True), encoding="utf-8"
    )
    return root


def _attempt(
    run_id: str = "TEST-DB-INVENTORY-001", *, authorized: bool = True
):
    return seal_target_inventory_phase_authorization_v16(
        run_id=run_id,
        accepted_controller_authority_content_hash=(
            CONTROLLER_AUTHORITY_CONTENT_HASH
        ),
        test_only=True,
        database_read_authorized=authorized,
    )


def _stop(code: str):
    return pytest.raises(TargetInventoryExecutionStop, match=f"^{code}$")


def _forged_accepted_preflight(
    run_id: str = "TEST-DB-INVENTORY-001",
) -> TargetInventoryRuntimePreflightReceiptV16:
    row = _preflight_rows()[0]
    provisional = TargetInventoryRuntimePreflightReceiptV16(
        receipt_version=(
            "FV-STAGE8C-TARGET-DB-INVENTORY-RUNTIME-PREFLIGHT-v1.0.0"
        ),
        run_id=run_id,
        controller_authority_content_hash=CONTROLLER_AUTHORITY_CONTENT_HASH,
        query_content_hash=RUNTIME_PREFLIGHT_QUERY_CONTENT_HASH,
        server_version_num=170_005,
        flyway_head_version="24",
        company_identity_table=str(row["companyIdentityTable"]),
        instrument_identity_table=str(row["instrumentIdentityTable"]),
        share_class_identity_table=str(row["shareClassIdentityTable"]),
        listing_identity_table=str(row["listingIdentityTable"]),
        ticker_assignment_table=str(row["tickerAssignmentTable"]),
        v24_enrollment_table=str(row["v24EnrollmentTable"]),
        accepted=True,
        reason_codes=(),
        query_execution_count=1,
        test_only=True,
        database_url_persisted=False,
        database_url_hashed=False,
        inventory_authorized=False,
    )
    return replace(
        provisional,
        content_hash=canonical_hash(
            execution_module._runtime_preflight_receipt_body(
                provisional, include_hash=False
            )
        ),
    )


def test_frozen_queries_and_controller_authority_hashes_are_exact() -> None:
    assert CONTROLLER_AUTHORITY_CONTENT_HASH == (
        "50E2B883DD2A25D5B48F7933AEC76F814A458242A9FF35031E37B50CAB5468EC"
    )
    assert DATABASE_INVENTORY_QUERY_CONTENT_HASH == hashlib.sha256(
        TARGET_DATABASE_INVENTORY_QUERY_V16.encode("utf-8")
    ).hexdigest().upper()
    assert RUNTIME_PREFLIGHT_QUERY_CONTENT_HASH == hashlib.sha256(
        RUNTIME_PREFLIGHT_QUERY_V16.encode("utf-8")
    ).hexdigest().upper()
    assert "default_transaction_read_only=on" in LIBPQ_READ_ONLY_OPTIONS
    assert "statement_timeout=5000" in LIBPQ_READ_ONLY_OPTIONS


def test_phase_authorization_is_attempt_only_and_never_claims_runtime_review() -> None:
    authorization = _attempt()
    validate_target_inventory_phase_authorization_v16(authorization)
    assert authorization.database_read_authorized is True
    assert authorization.runtime_database_state_reviewed is False
    assert authorization.observed_target_schema_head is None
    assert authorization.runtime_preflight_receipt_content_hash is None
    assert authorization.database_write_authorized is False
    assert authorization.migration_authorized is False
    assert authorization.identifier_generation_authorized is False


def test_self_consistent_offline_forged_receipt_cannot_authorize_or_execute(
    tmp_path: Path,
) -> None:
    forged = _forged_accepted_preflight()
    validate_target_inventory_runtime_preflight_receipt_v16(forged)
    with _stop("TARGET_DB_INVENTORY_EXTERNAL_PREFLIGHT_RECEIPT_FORBIDDEN"):
        seal_target_inventory_phase_authorization_v16(
            run_id=forged.run_id,
            accepted_controller_authority_content_hash=(
                CONTROLLER_AUTHORITY_CONTENT_HASH
            ),
            test_only=True,
            runtime_preflight_receipt=forged,
            database_read_authorized=True,
        )

    def fail_connect(*args: object, **kwargs: object):
        raise AssertionError((args, kwargs))

    with _stop("TARGET_DB_INVENTORY_EXTERNAL_PREFLIGHT_RECEIPT_FORBIDDEN"):
        execute_target_inventory_read_v16(
            _attempt(),
            runtime_preflight_receipt=forged,
            database_url="postgresql://db-b.invalid/db",
            storage_root=_storage_root(tmp_path),
            connect_factory=fail_connect,
        )


def test_standalone_db_a_preflight_cannot_authorize_db_b_inventory(
    tmp_path: Path,
) -> None:
    db_a = _FakeConnect(_preflight_rows())
    db_a_receipt = run_target_inventory_runtime_preflight_v16(
        run_id="TEST-DB-INVENTORY-001",
        accepted_controller_authority_content_hash=(
            CONTROLLER_AUTHORITY_CONTENT_HASH
        ),
        database_url="postgresql://db-a.invalid/db",
        test_only=True,
        connect_factory=db_a,
    )
    assert db_a_receipt.accepted is True
    db_b = _FakeConnect(_preflight_rows(), _inventory_rows())
    with _stop("TARGET_DB_INVENTORY_EXTERNAL_PREFLIGHT_RECEIPT_FORBIDDEN"):
        execute_target_inventory_read_v16(
            _attempt(),
            runtime_preflight_receipt=db_a_receipt,
            database_url="postgresql://db-b.invalid/db",
            storage_root=_storage_root(tmp_path),
            connect_factory=db_b,
        )
    assert db_b.calls == []


def test_success_uses_one_connection_one_transaction_and_two_ordered_queries(
    tmp_path: Path,
) -> None:
    root = _storage_root(tmp_path)
    authorization = _attempt()
    fake = _FakeConnect(_preflight_rows(), _inventory_rows())
    database_url = "postgresql://runtime-secret.invalid/inventory"

    review, receipt = execute_target_inventory_read_v16(
        authorization,
        database_url=database_url,
        storage_root=root,
        connect_factory=fake,
    )

    assert len(fake.calls) == 1
    assert fake.calls[0] == (
        database_url,
        {
            "autocommit": False,
            "row_factory": dict_row,
            "connect_timeout": CONNECT_TIMEOUT_SECONDS,
            "options": LIBPQ_READ_ONLY_OPTIONS,
        },
    )
    assert fake.cursor.statements == [
        RUNTIME_PREFLIGHT_QUERY_V16,
        TARGET_DATABASE_INVENTORY_QUERY_V16,
    ]
    assert [item.adoption_state for item in review.decisions] == [
        InventoryAdoptionState.NEW_ID_CANDIDATE,
        InventoryAdoptionState.NEW_ID_CANDIDATE,
        InventoryAdoptionState.CONFLICT,
    ]
    assert receipt.runtime_query_execution_count == 1
    assert receipt.inventory_query_execution_count == 1
    assert receipt.write_statement_count == 0
    run_root = target_inventory_run_root_v16(root, authorization)
    assert (run_root / "execution-manifest.json").is_file()
    assert (run_root / "_private/runtime-preflight-receipt.json").is_file()
    assert (run_root / "_private/runtime-read-grant.json").is_file()
    assert (run_root / "_private/inventory-checkpoint.json").is_file()
    assert [path.name for path in sorted((run_root / "events").iterdir())] == [
        "001-INTENT.json",
        "002-COMPLETED.json",
    ]
    for path in run_root.rglob("*.json"):
        assert database_url.encode("utf-8") not in path.read_bytes()


def test_rejected_db_b_runtime_state_is_terminal_before_inventory_query(
    tmp_path: Path,
) -> None:
    root = _storage_root(tmp_path)
    authorization = _attempt()
    rejected = _preflight_rows(
        server_version_num=160_009, flyway_head_version="23"
    )
    rejected[0]["companyIdentityTable"] = None
    fake = _FakeConnect(rejected)
    with _stop("TARGET_DB_INVENTORY_RUNTIME_STATE_REJECTED"):
        execute_target_inventory_read_v16(
            authorization,
            database_url="postgresql://db-b.invalid/db",
            storage_root=root,
            connect_factory=fake,
        )
    assert fake.cursor.statements == [RUNTIME_PREFLIGHT_QUERY_V16]
    run_root = target_inventory_run_root_v16(root, authorization)
    assert [path.name for path in sorted((run_root / "events").iterdir())] == [
        "001-INTENT.json",
        "002-REJECTED_RUNTIME_STATE.json",
    ]
    assert (run_root / "_private/runtime-preflight-receipt.json").is_file()
    assert not (run_root / "_private/runtime-read-grant.json").exists()
    assert not (run_root / "inventory-receipt.json").exists()

    def fail_connect(*args: object, **kwargs: object):
        raise AssertionError((args, kwargs))

    with _stop("TARGET_DB_INVENTORY_RUNTIME_STATE_REJECTED"):
        execute_target_inventory_read_v16(
            authorization,
            database_url="postgresql://db-b.invalid/db",
            storage_root=root,
            connect_factory=fail_connect,
        )


@pytest.mark.parametrize(
    ("fail_on_execute", "expected_code"),
    [
        (1, "TARGET_DB_INVENTORY_RUNTIME_PREFLIGHT_QUERY_FAILED"),
        (2, "TARGET_DB_INVENTORY_QUERY_FAILED"),
    ],
)
def test_transport_exception_after_intent_is_sanitized_and_blocks_rerun(
    tmp_path: Path,
    fail_on_execute: int,
    expected_code: str,
) -> None:
    root = _storage_root(tmp_path)
    authorization = _attempt(run_id=f"TEST-DB-INVENTORY-00{fail_on_execute}")
    fake = _FakeConnect(
        _preflight_rows(),
        _inventory_rows(),
        fail_on_execute={
            fail_on_execute: RuntimeError(
                "password=do-not-leak host=private.invalid"
            )
        },
    )
    with _stop(expected_code) as captured:
        execute_target_inventory_read_v16(
            authorization,
            database_url="postgresql://runtime-secret.invalid/db",
            storage_root=root,
            connect_factory=fake,
        )
    assert captured.value.__cause__ is None
    assert "password" not in repr(captured.value)
    run_root = target_inventory_run_root_v16(root, authorization)
    assert [path.name for path in (run_root / "events").iterdir()] == [
        "001-INTENT.json"
    ]

    def fail_connect(*args: object, **kwargs: object):
        raise AssertionError((args, kwargs))

    with _stop("TARGET_DB_INVENTORY_UNMATCHED_INTENT_STOP"):
        execute_target_inventory_read_v16(
            authorization,
            database_url="postgresql://runtime-secret.invalid/db",
            storage_root=root,
            connect_factory=fail_connect,
        )


def test_crash_after_inventory_select_leaves_unmatched_intent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _storage_root(tmp_path)
    authorization = _attempt()
    fake = _FakeConnect(_preflight_rows(), _inventory_rows())
    original = execution_module._atomic_json_create

    def crash_checkpoint(path: Path, value: dict[str, object]) -> bytes:
        if path.name == "inventory-checkpoint.json":
            raise RuntimeError("SIMULATED_CHECKPOINT_CRASH")
        return original(path, value)

    monkeypatch.setattr(execution_module, "_atomic_json_create", crash_checkpoint)
    with _stop("SIMULATED_CHECKPOINT_CRASH"):
        execute_target_inventory_read_v16(
            authorization,
            database_url="postgresql://runtime-only.invalid/db",
            storage_root=root,
            connect_factory=fake,
        )
    assert fake.cursor.statements == [
        RUNTIME_PREFLIGHT_QUERY_V16,
        TARGET_DATABASE_INVENTORY_QUERY_V16,
    ]
    run_root = target_inventory_run_root_v16(root, authorization)
    assert [path.name for path in (run_root / "events").iterdir()] == [
        "001-INTENT.json"
    ]


def test_completed_replay_is_exact_and_performs_zero_database_calls(
    tmp_path: Path,
) -> None:
    root = _storage_root(tmp_path)
    authorization = _attempt()
    first_review, first_receipt = execute_target_inventory_read_v16(
        authorization,
        database_url="postgresql://runtime-only.invalid/db",
        storage_root=root,
        connect_factory=_FakeConnect(_preflight_rows(), _inventory_rows()),
    )

    def fail_connect(*args: object, **kwargs: object):
        raise AssertionError((args, kwargs))

    replay_review, replay_receipt = execute_target_inventory_read_v16(
        authorization,
        database_url="postgresql://different.invalid/db",
        storage_root=root,
        connect_factory=fail_connect,
    )
    assert replay_review == first_review
    assert replay_receipt == first_receipt


def test_schema_failure_after_select_is_unmatched_and_not_retried(
    tmp_path: Path,
) -> None:
    root = _storage_root(tmp_path)
    authorization = _attempt()
    bad_rows = _inventory_rows()
    bad_rows[0].pop("securityName")
    with _stop("DB_INVENTORY_ROW_SCHEMA_INVALID"):
        execute_target_inventory_read_v16(
            authorization,
            database_url="postgresql://runtime-only.invalid/db",
            storage_root=root,
            connect_factory=_FakeConnect(_preflight_rows(), bad_rows),
        )
    run_root = target_inventory_run_root_v16(root, authorization)
    assert [path.name for path in (run_root / "events").iterdir()] == [
        "001-INTENT.json"
    ]


def test_production_connect_injection_and_authorization_drift_fail_closed(
    tmp_path: Path,
) -> None:
    fake = _FakeConnect(_preflight_rows(), _inventory_rows())
    production_attempt = replace(_attempt(), test_only=False)
    production_attempt = replace(
        production_attempt,
        content_hash=canonical_hash(
            execution_module._authorization_body(
                production_attempt, include_hash=False
            )
        ),
    )
    validate_target_inventory_phase_authorization_v16(production_attempt)
    with _stop("TARGET_DB_INVENTORY_PRODUCTION_CONNECT_INJECTION_BLOCKED"):
        execute_target_inventory_read_v16(
            production_attempt,
            database_url="postgresql://runtime-only.invalid/db",
            storage_root=tmp_path,
            connect_factory=fake,
        )

    with _stop("TARGET_DB_INVENTORY_AUTHORIZATION_BINDING_DRIFT"):
        validate_target_inventory_phase_authorization_v16(
            replace(_attempt(), migration_authorized=True)
        )
