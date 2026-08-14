from __future__ import annotations

import copy
import os
import sys
import threading
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import psycopg
import pytest
from psycopg.rows import dict_row

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from current_assessment_fixture_v1 import (  # noqa: E402
    eodhd_price_fixture_v1,
    fundamentals_fixture_v1,
    seed_synthetic_current_identity_authority_v25,
    write_source_receipt_v1,
)

from equity_analysis.fundamental_value import current_assessment_persistence_v1
from equity_analysis.fundamental_value.current_assessment_persistence_v1 import (
    AUTHORIZATION_CONTENT_HASH,
    AUTHORIZATION_REFERENCE,
    CurrentAssessmentPersistenceConflict,
    CurrentAssessmentRepositoryV1,
    provision_current_assessment_authority_v1,
)
from equity_analysis.fundamental_value.current_assessment_v1 import (
    build_current_fundamental_assessment_v1,
    create_current_completed_session_seal_v1,
)
from equity_analysis.fundamental_value.current_evidence_registration_v1 import (
    CurrentEvidenceRegistrationRepositoryV1,
    provision_current_evidence_authorities_v1,
)

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"),
    reason="TEST_DATABASE_URL is required for PostgreSQL integration acceptance",
)


def _database_url() -> str:
    value = os.getenv("TEST_DATABASE_URL")
    if not value:
        pytest.skip("TEST_DATABASE_URL is required")
    if "test" not in value.rsplit("/", 1)[-1].lower():
        pytest.fail("V26 integration requires a disposable test database")
    return value


def _build_registered_assessment(
    url: str,
    root: Path,
    *,
    projection_years: int = 5,
    provision_assessment_authority: bool = True,
    ticker: str = "GOOG",
    cutoff_second_offset: int = 0,
):
    identity, projection_content_hash = seed_synthetic_current_identity_authority_v25(
        url, ticker=ticker
    )
    if provision_assessment_authority:
        provision_current_assessment_authority_v1(
            url,
            identity_projection_content_hash=projection_content_hash,
            authorization_reference=AUTHORIZATION_REFERENCE,
            authorization_content_hash=AUTHORIZATION_CONTENT_HASH,
            authority_write_authorized=True,
        )
    fundamentals = copy.deepcopy(fundamentals_fixture_v1())
    fundamentals["General"]["Code"] = identity.ticker
    fundamentals["General"]["UpdatedAt"] = "2026-08-02"
    fundamentals_raw, fundamentals_source = write_source_receipt_v1(
        root,
        fundamentals,
        "EODHD",
        datetime(2026, 8, 12, 17, 17, 14, tzinfo=UTC),
        symbol=identity.ticker, identity=identity,
        projection_content_hash=projection_content_hash,
    )
    price_available_at = datetime(2026, 8, 12, 17, 22, 26, tzinfo=UTC)
    price = eodhd_price_fixture_v1(
        identity,
        trading_date="2026-08-11",
        available_at=price_available_at,
    )
    price_raw, price_source = write_source_receipt_v1(
        root, price, "EODHD", price_available_at,
        symbol=identity.ticker, identity=identity,
        projection_content_hash=projection_content_hash,
        source_kind="PRICE",
    )
    session = create_current_completed_session_seal_v1(
        session_date=date(2026, 8, 11),
        completed_at=price_available_at,
        mic="XNAS",
    )
    provision_current_evidence_authorities_v1(
        url,
        completed_session=session,
        authority_write_authorized=True,
    )
    cutoff = datetime(2026, 8, 12, 17, 23, tzinfo=UTC) + timedelta(
        seconds=cutoff_second_offset
    )
    applicability, price_selection = CurrentEvidenceRegistrationRepositoryV1(
        url, receipt_storage_root=root
    ).register(
        identity=identity, completed_session=session,
        fundamentals_raw=fundamentals_raw, fundamentals_payload=fundamentals,
        fundamentals_source=fundamentals_source, price_raw=price_raw,
        price_payload=price, price_source=price_source, decision_cutoff=cutoff,
    )
    return build_current_fundamental_assessment_v1(
        identity=identity, completed_session=session,
        applicability_seal=applicability, price_selection_seal=price_selection,
        fundamentals_raw=fundamentals_raw, fundamentals_payload=fundamentals,
        fundamentals_source=fundamentals_source, price_raw=price_raw,
        price_payload=price, price_source=price_source, decision_cutoff=cutoff,
        projection_years=projection_years,
    )


def test_v26_current_assessment_round_trip_formula_replay_and_idempotency(
    tmp_path: Path,
) -> None:
    url = _database_url()
    assessment = _build_registered_assessment(
        url, tmp_path, provision_assessment_authority=False
    )
    repository = CurrentAssessmentRepositoryV1(url)
    with psycopg.connect(url, row_factory=dict_row) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """SELECT identity.projection_content_hash,
                          authority.authority_id IS NOT NULL AS authority_exists
                   FROM analytics.fv_identity_authority_v2 identity
                   LEFT JOIN analytics.fv_current_assessment_authority_v1 authority
                     ON authority.identity_authority_id=identity.authority_id"""
            )
            identity_row = cursor.fetchone()
            projection_hash = identity_row["projection_content_hash"]
    if not identity_row["authority_exists"]:
        with pytest.raises(CurrentAssessmentPersistenceConflict):
            repository.persist(assessment)
    authority_id = provision_current_assessment_authority_v1(
        url,
        identity_projection_content_hash=projection_hash,
        authorization_reference=AUTHORIZATION_REFERENCE,
        authorization_content_hash=AUTHORIZATION_CONTENT_HASH,
        authority_write_authorized=True,
    )
    assert (
        provision_current_assessment_authority_v1(
            url,
            identity_projection_content_hash=projection_hash,
            authorization_reference=AUTHORIZATION_REFERENCE,
            authorization_content_hash=AUTHORIZATION_CONTENT_HASH,
            authority_write_authorized=True,
        )
        == authority_id
    )
    with psycopg.connect(url, row_factory=dict_row) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT recorded_at FROM analytics.fv_current_assessment_authority_v1 "
                "WHERE authority_id=%s",
                (authority_id,),
            )
            authority_recorded_at = cursor.fetchone()["recorded_at"]
            assert authority_recorded_at.year == 2026
            assert authority_recorded_at.microsecond == 0
            with pytest.raises(psycopg.Error, match="immutable"):
                cursor.execute(
                    "UPDATE analytics.fv_current_assessment_authority_v1 "
                    "SET recorded_at=TIMESTAMPTZ '2001-01-01 00:00:00+00' "
                    "WHERE authority_id=%s",
                    (authority_id,),
                )
            connection.rollback()
            with pytest.raises(psycopg.Error, match="immutable"):
                cursor.execute(
                    "DELETE FROM analytics.fv_current_assessment_authority_v1 "
                    "WHERE authority_id=%s",
                    (authority_id,),
                )
            connection.rollback()

    relocated_payload = copy.deepcopy(
        current_assessment_persistence_v1.current_fundamental_assessment_to_wire_v1(
            assessment
        )
    )
    terminal_growth = next(
        item
        for item in relocated_payload["input_evidence"]
        if item["operand_code"] == "terminal_growth_rate"
    )
    debt_maturity = next(
        item
        for item in relocated_payload["input_evidence"]
        if item["operand_code"] == "debt_maturity_schedule"
    )
    terminal_value = terminal_growth["value"]
    terminal_growth.update(
        state="MISSING",
        value=None,
        reason_codes=["DEBT_MATURITY_SCHEDULE_NOT_AVAILABLE"],
    )
    debt_maturity.update(state="VALID", value=terminal_value, reason_codes=[])
    relocated_body = dict(relocated_payload)
    relocated_body.pop("content_hash")
    relocated_payload["content_hash"] = current_assessment_persistence_v1._sha256(
        current_assessment_persistence_v1._payload_text(relocated_body).encode()
    )
    relocated_expected = current_assessment_persistence_v1._expected_record(
        relocated_payload
    )
    relocated_values = {
        item["operand_code"]: (
            None if item["value"] is None else Decimal(item["value"])
        )
        for item in relocated_payload["input_evidence"]
    }
    with psycopg.connect(url, row_factory=dict_row) as connection:
        with pytest.raises(psycopg.Error, match="frozen operand state drift"):
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SET LOCAL ROLE analytics_fv_current_assessment_writer_v1"
                    )
                    current_assessment_persistence_v1.CurrentAssessmentRepositoryV1._verify_producer_registry(
                        cursor
                    )
                    current_assessment_persistence_v1.CurrentAssessmentRepositoryV1._insert(
                        cursor,
                        relocated_payload,
                        relocated_expected,
                        durable_operand_values=relocated_values,
                    )
    first = repository.persist(assessment)
    replay = repository.persist(assessment)
    assert replay == first
    assert repository.load(first.assessment_id) == first
    assert repository.load_latest_for_security(assessment.security_id) == first
    assert repository.load_latest_for_symbol("GOOG") == first

    with psycopg.connect(url, row_factory=dict_row) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """SELECT
                      (SELECT count(*) FROM analytics.fv_current_assessment_v1
                       WHERE assessment_id=%s) AS roots,
                      (SELECT count(*) FROM analytics.fv_current_assessment_source_v1
                       WHERE assessment_id=%s) AS sources,
                      (SELECT count(*) FROM analytics.fv_current_assessment_operand_v1
                       WHERE assessment_id=%s) AS operands,
                      (SELECT count(*)
                       FROM analytics.fv_current_assessment_operand_parent_v1
                       WHERE assessment_id=%s) AS parents,
                      (SELECT count(*)
                       FROM analytics.fv_current_assessment_operand_reason_v1
                       WHERE assessment_id=%s) AS reasons,
                      (SELECT count(*) FROM analytics.fv_current_assessment_seal_v1
                       WHERE assessment_id=%s) AS seals,
                  (SELECT count(*) FROM analytics.fv_current_assessment_authority_v1)
                    AS authorities,
                  (SELECT creator_xid8 IS NOT NULL
                       FROM analytics.fv_current_assessment_seal_v1
                       WHERE assessment_id=%s) AS creator_bound""",
                    (first.assessment_id,) * 7,
                )
            assert cursor.fetchone() == {
                "roots": 1, "sources": 2, "operands": 34, "parents": 32,
                "reasons": 1, "seals": 1, "authorities": 1,
                "creator_bound": True,
            }


def test_v26_current_assessment_is_append_only_and_late_children_fail(
    tmp_path: Path,
) -> None:
    url = _database_url()
    assessment = _build_registered_assessment(url, tmp_path)
    record = CurrentAssessmentRepositoryV1(url).persist(assessment)
    with psycopg.connect(url) as connection:
        with connection.cursor() as cursor:
            with pytest.raises(psycopg.Error, match="immutable"):
                cursor.execute(
                    "UPDATE analytics.fv_current_assessment_v1 SET symbol='ALTERED' "
                    "WHERE assessment_id=%s", (record.assessment_id,),
                )
            connection.rollback()
            with pytest.raises(psycopg.Error, match="is sealed"):
                cursor.execute(
                    """INSERT INTO analytics.fv_current_assessment_operand_reason_v1
                       (assessment_id,operand_ordinal,reason_ordinal,reason_code)
                       VALUES (%s,34,2,'LATE_REASON')""",
                    (record.assessment_id,),
                )
            connection.rollback()
            with pytest.raises(psycopg.Error, match="immutable"):
                cursor.execute(
                    "UPDATE analytics.fv_current_producer_contract_v1 "
                    "SET governance='ALTERED' WHERE operand_ordinal=1"
                )


def test_v26_rejects_a_distinct_assessment_at_the_same_decision_cutoff(
    tmp_path: Path,
) -> None:
    url = _database_url()
    assessment = _build_registered_assessment(url, tmp_path)
    repository = CurrentAssessmentRepositoryV1(url)
    repository.persist(assessment)
    changed = _build_registered_assessment(
        url, tmp_path / "changed", projection_years=6
    )
    with pytest.raises(CurrentAssessmentPersistenceConflict):
        repository.persist(changed)


def test_v26_two_connection_late_child_cannot_race_the_seal(
    tmp_path: Path,
) -> None:
    url = _database_url()
    with psycopg.connect(url, row_factory=dict_row) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT count(*) AS value FROM analytics.fv_current_assessment_v1 "
                "WHERE symbol='FOX'"
            )
            cutoff_offset = cursor.fetchone()["value"] + 1
    assessment = _build_registered_assessment(
        url,
        tmp_path,
        ticker="FOX",
        cutoff_second_offset=cutoff_offset,
    )
    payload = current_assessment_persistence_v1.current_fundamental_assessment_to_wire_v1(
        assessment
    )
    expected = current_assessment_persistence_v1._expected_record(payload)
    late_started = threading.Event()
    allow_late_insert = threading.Event()
    late_errors: list[str] = []

    sealing = psycopg.connect(url, row_factory=dict_row)
    try:
        with sealing.cursor() as cursor:
            cursor.execute("BEGIN")
            cursor.execute("SET LOCAL ROLE analytics_fv_current_assessment_writer_v1")
            current_assessment_persistence_v1.CurrentAssessmentRepositoryV1._verify_producer_registry(
                cursor
            )
            current_assessment_persistence_v1.CurrentAssessmentRepositoryV1._insert(
                cursor,
                payload,
                expected,
                durable_operand_values={
                    item.operand_code: item.value
                    for item in assessment.input_evidence
                },
            )

        def insert_late_reason() -> None:
            try:
                with psycopg.connect(url) as late:
                    with late.cursor() as cursor:
                        cursor.execute(
                            "SELECT set_config("
                            "'app.fv_current_assessment_creator_xid8','1',false)"
                        )
                        late_started.set()
                        assert allow_late_insert.wait(timeout=10)
                        cursor.execute(
                            """INSERT INTO
                               analytics.fv_current_assessment_operand_reason_v1
                               (assessment_id,operand_ordinal,reason_ordinal,reason_code)
                               VALUES (%s,34,2,'RACING_LATE_REASON')""",
                            (expected.assessment_id,),
                        )
                    late.commit()
            except psycopg.Error as error:
                late_errors.append(str(error))

        late_thread = threading.Thread(target=insert_late_reason, daemon=True)
        late_thread.start()
        assert late_started.wait(timeout=5)
        sealing.commit()
        allow_late_insert.set()
        late_thread.join(timeout=10)
        assert not late_thread.is_alive()
        assert len(late_errors) == 1
        assert "is sealed" in late_errors[0]
    finally:
        sealing.close()

    persisted = CurrentAssessmentRepositoryV1(url).load(expected.assessment_id)
    assert persisted.assessment_content_hash == assessment.content_hash
    with psycopg.connect(url, row_factory=dict_row) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """SELECT
                     (SELECT count(*) FROM
                       analytics.fv_current_assessment_operand_reason_v1
                       WHERE assessment_id=%s) AS reason_count,
                     creator_xid8::text<>'1' AS server_creator,
                     date_trunc('second',sealed_at)=sealed_at AS sealed_whole_second
                   FROM analytics.fv_current_assessment_seal_v1
                   WHERE assessment_id=%s""",
                (expected.assessment_id, expected.assessment_id),
            )
            assert cursor.fetchone() == {
                "reason_count": 1,
                "server_creator": True,
                "sealed_whole_second": True,
            }
