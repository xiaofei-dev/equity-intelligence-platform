from __future__ import annotations

import os
from datetime import timedelta
from uuid import UUID

import psycopg
import pytest
from psycopg.conninfo import conninfo_to_dict
from test_forward_outcomes_v21 import (
    NOW,
    SECURITY_ID,
    _seal,
    enrollment,
    outcome_batch,
    quality_report,
)

from equity_analysis.forward_validation.outcome_persistence_v21 import (
    ForwardDqvOutcomeRepositoryV21,
    ForwardDqvPersistenceConflict,
)
from equity_analysis.forward_validation.outcomes_v21 import (
    ForwardDqvEnrollmentV21,
    ForwardOutcomeBatchV21,
)

DATABASE_URL = os.getenv("FORWARD_DQV_V18_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="FORWARD_DQV_V18_TEST_DATABASE_URL is not configured",
)


def _assert_isolated_database() -> None:
    assert DATABASE_URL is not None
    database_name = conninfo_to_dict(DATABASE_URL).get("dbname", "")
    if "test" not in database_name.lower():
        raise RuntimeError(
            "FORWARD_DQV_V18_TEST_DATABASE_URL must name an isolated test database"
        )


def _bootstrap(connection: psycopg.Connection) -> None:
    contract = connection.execute(
        "SELECT to_regclass('analytics.forward_dqv_quality_report_v2')"
    ).fetchone()
    assert contract is not None and contract[0] is not None
    connection.execute(
        """
        TRUNCATE TABLE
            analytics.forward_dqv_quality_report_v2,
            analytics.forward_dqv_path_metric_v2,
            analytics.forward_dqv_benchmark_outcome_v2,
            analytics.forward_dqv_security_outcome_v2,
            analytics.forward_dqv_outcome_batch_v2,
            analytics.forward_dqv_maturity_schedule_v2,
            analytics.forward_dqv_enrollment_v2,
            analytics.data_snapshot,
            analytics.universe_definition,
            analytics.security
        RESTART IDENTITY CASCADE
        """
    )
    connection.execute(
        """
        INSERT INTO analytics.universe_definition (
            version, effective_at, configuration, configuration_hash
        ) VALUES (
            'test-universe-v1', %s, '{"securityCount":1}'::jsonb,
            'sha256:v18-postgres-test-universe'
        )
        """,
        (NOW,),
    )
    connection.execute(
        """
        INSERT INTO analytics.data_snapshot (
            id, snapshot_key, status, as_of_time, ingestion_cutoff,
            market_normalization_version, fundamental_normalization_version,
            action_normalization_version, manifest_hash, source_count,
            security_count, sealed_at, market_data_provider,
            market_adjustment_mode
        ) VALUES (
            'b51a0367-973c-593f-a626-96b83c58f8f9',
            'forward-dqv-v18-postgres-test', 'READY', %s, %s,
            'test-market-v1', 'test-fundamental-v1', 'test-action-v1',
            'sha256:v18-postgres-test-snapshot', 0, 1, %s,
            'fixture', 'TOTAL_RETURN_ADJUSTED'
        )
        """,
        (NOW, NOW, NOW),
    )
    connection.execute(
        """
        INSERT INTO analytics.security (
            public_id, symbol, exchange, name, instrument_type, currency, active
        ) VALUES (%s, 'V18TEST', 'NASDAQ', 'V18 Test Security',
                  'COMMON_STOCK', 'USD', TRUE)
        """,
        (SECURITY_ID,),
    )


@pytest.fixture
def repository() -> ForwardDqvOutcomeRepositoryV21:
    _assert_isolated_database()
    assert DATABASE_URL is not None
    with psycopg.connect(DATABASE_URL) as connection:
        _bootstrap(connection)
    return ForwardDqvOutcomeRepositoryV21(DATABASE_URL)


def test_v18_repository_exact_replay_and_readback(
    repository: ForwardDqvOutcomeRepositoryV21,
) -> None:
    enrolled = enrollment()
    batch = outcome_batch()

    assert repository.persist_enrollment(enrolled) == enrolled.enrollment_id
    assert repository.persist_enrollment(enrolled) == enrolled.enrollment_id
    assert repository.read_enrollment(enrolled.enrollment_id) == enrolled

    assert repository.persist_outcome_batch(batch) == batch.outcome_batch_id
    assert repository.persist_outcome_batch(batch) == batch.outcome_batch_id
    assert repository.read_outcome_batch(batch.outcome_batch_id) == batch

    report = quality_report()
    assert repository.persist_quality_report(report) == report.report_id
    assert repository.persist_quality_report(report) == report.report_id
    assert repository.read_quality_report(report.report_id) == report


def test_v18_repository_rejects_idempotency_conflict(
    repository: ForwardDqvOutcomeRepositoryV21,
) -> None:
    enrolled = enrollment()
    repository.persist_enrollment(enrolled)
    payload = enrolled.model_dump(mode="python", by_alias=True)
    payload["canonicalRequestHash"] = "sha256:" + "b" * 64
    conflict = _seal(
        ForwardDqvEnrollmentV21,
        payload,
        "enrollmentContentHash",
    )

    with pytest.raises(ForwardDqvPersistenceConflict):
        repository.persist_enrollment(conflict)


def test_v18_accepts_one_successor_and_rejects_a_branch(
    repository: ForwardDqvOutcomeRepositoryV21,
) -> None:
    enrolled = enrollment()
    first = outcome_batch()
    repository.persist_enrollment(enrolled)
    repository.persist_outcome_batch(first)

    successor_payload = first.model_dump(mode="python", by_alias=True)
    successor_payload.update(
        {
            "outcomeBatchId": UUID("7e0cd9cf-87a4-5e0f-bca9-e83d6e6e63b9"),
            "resultVersion": 2,
            "supersedesBatchId": first.outcome_batch_id,
            "observedAt": first.observed_at + timedelta(hours=1),
        }
    )
    successor = _seal(
        ForwardOutcomeBatchV21,
        successor_payload,
        "outcomeBatchContentHash",
    )
    assert repository.persist_outcome_batch(successor) == successor.outcome_batch_id

    branch_payload = successor.model_dump(mode="python", by_alias=True)
    branch_payload.update(
        {
            "outcomeBatchId": UUID("21c60245-29a9-5379-82e8-80307292191c"),
            "observedAt": successor.observed_at + timedelta(hours=1),
        }
    )
    branch = _seal(
        ForwardOutcomeBatchV21,
        branch_payload,
        "outcomeBatchContentHash",
    )

    with pytest.raises(ForwardDqvPersistenceConflict):
        repository.persist_outcome_batch(branch)
