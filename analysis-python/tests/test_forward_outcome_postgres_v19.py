from __future__ import annotations

import os
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from psycopg.conninfo import conninfo_to_dict
from psycopg.types.json import Jsonb
from test_forward_outcome_postgres_v18 import _bootstrap
from test_forward_outcomes_v21 import (
    _seal,
)
from test_forward_outcomes_v21 import (
    enrollment as legacy_enrollment,
)
from test_forward_outcomes_v21 import (
    outcome_batch as legacy_outcome_batch,
)

from equity_analysis.analytics_interface.contracts import canonical_hash
from equity_analysis.forward_validation.maturity_outcome_engine_v22 import EvidenceState
from equity_analysis.forward_validation.maturity_path_loader_v22 import (
    CompletedSessionCalendarReadV22,
    FrozenSecurityV22,
    PostgresMaturityEvidenceReadRepositoryV22,
)
from equity_analysis.forward_validation.outcome_persistence_v211 import (
    ForwardDqvOutcomeRepositoryV211,
)
from equity_analysis.forward_validation.outcomes_v21 import (
    ForwardOutcomeBatchV21,
    sealed_model_payload,
)
from equity_analysis.forward_validation.outcomes_v211 import (
    FORWARD_DQV_ENROLLMENT_V211,
    ForwardDqvEnrollmentV211,
)

DATABASE_URL = os.getenv("FORWARD_DQV_V19_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="FORWARD_DQV_V19_TEST_DATABASE_URL is not configured",
)


def _assert_isolated_database() -> None:
    assert DATABASE_URL is not None
    database_name = conninfo_to_dict(DATABASE_URL).get("dbname", "")
    if "test" not in database_name.lower():
        raise RuntimeError("FORWARD_DQV_V19_TEST_DATABASE_URL must name an isolated test database")


def _enrollment(*, seal_delta_minutes: int = -1) -> ForwardDqvEnrollmentV211:
    legacy = legacy_enrollment()
    body = legacy.model_dump(mode="python", by_alias=True)
    body["schemaVersion"] = FORWARD_DQV_ENROLLMENT_V211
    body["sealedAt"] = legacy.effective_at_completed_session_open + timedelta(
        minutes=seal_delta_minutes
    )
    body["enrollmentContentHash"] = "sha256:" + "0" * 64
    draft = ForwardDqvEnrollmentV211.model_validate(body)
    return ForwardDqvEnrollmentV211.model_validate(
        sealed_model_payload(draft, "enrollmentContentHash")
    )


@pytest.fixture
def repository() -> ForwardDqvOutcomeRepositoryV211:
    _assert_isolated_database()
    assert DATABASE_URL is not None
    with psycopg.connect(DATABASE_URL) as connection:
        _bootstrap(connection)
    return ForwardDqvOutcomeRepositoryV211(DATABASE_URL)


def test_v19_repository_exact_replay_and_readback(
    repository: ForwardDqvOutcomeRepositoryV211,
) -> None:
    enrollment = _enrollment()

    assert repository.persist_enrollment(enrollment) == enrollment.enrollment_id
    assert repository.persist_enrollment(enrollment) == enrollment.enrollment_id
    assert repository.read_enrollment(enrollment.enrollment_id) == enrollment


def test_v19_repository_discovers_only_hash_verified_due_maturity(
    repository: ForwardDqvOutcomeRepositoryV211,
) -> None:
    enrollment = _enrollment()
    repository.persist_enrollment(enrollment)
    first = enrollment.maturity_schedule[0]

    before = repository.list_due_maturities(
        observed_at=first.matures_at_completed_session - timedelta(seconds=1)
    )
    due = repository.list_due_maturities(observed_at=first.matures_at_completed_session)

    assert before == ()
    assert len(due) == 1
    assert due[0].enrollment == enrollment
    assert due[0].completed_sessions == 5
    assert due[0].matures_at_completed_session == first.matures_at_completed_session
    assert due[0].latest_outcome_batch_id is None

    original = legacy_outcome_batch()
    original_payload = original.model_dump(mode="python", by_alias=True)
    original_payload["observedAt"] = first.matures_at_completed_session
    batch = _seal(
        ForwardOutcomeBatchV21,
        original_payload,
        "outcomeBatchContentHash",
    )
    assert repository.persist_outcome_batch(batch) == batch.outcome_batch_id
    assert repository.persist_outcome_batch(batch) == batch.outcome_batch_id
    assert repository.list_due_maturities(observed_at=first.matures_at_completed_session) == ()

    materialized = repository.list_due_maturities(
        observed_at=first.matures_at_completed_session,
        include_materialized=True,
    )
    assert len(materialized) == 1
    assert materialized[0].latest_outcome_batch_id == batch.outcome_batch_id
    assert materialized[0].latest_result_version == 1
    assert materialized[0].latest_outcome_batch_content_hash == batch.outcome_batch_content_hash

    successor_payload = batch.model_dump(mode="python", by_alias=True)
    successor_payload.update(
        {
            "outcomeBatchId": "7e0cd9cf-87a4-5e0f-bca9-e83d6e6e63b9",
            "resultVersion": 2,
            "supersedesBatchId": batch.outcome_batch_id,
            "observedAt": batch.observed_at + timedelta(minutes=5),
        }
    )
    successor = _seal(
        ForwardOutcomeBatchV21,
        successor_payload,
        "outcomeBatchContentHash",
    )
    repository.persist_outcome_batch(successor)
    latest = repository.list_due_maturities(
        observed_at=successor.observed_at,
        include_materialized=True,
    )
    assert latest[0].latest_outcome_batch_id == successor.outcome_batch_id
    assert latest[0].latest_result_version == 2


def test_v19_database_rejects_legacy_contract_and_post_entry_seal(
    repository: ForwardDqvOutcomeRepositoryV211,
) -> None:
    assert DATABASE_URL is not None
    valid = _enrollment()
    values = valid.model_dump(mode="python", by_alias=True)
    values["modelFreezeHashes"] = Jsonb(values["modelFreezeHashes"])
    values["terminalCounts"] = Jsonb(values["terminalCounts"])
    insert = """
        INSERT INTO analytics.forward_dqv_enrollment_v2 (
            id, idempotency_key, canonical_request_hash, contract_version,
            preregistration_content_hash, decision_manifest_content_hash,
            decision_controlled_artifact_hash,
            decision_controlled_artifact_reference,
            decision_data_snapshot_id, decision_as_of,
            effective_at_completed_session_open, universe_version,
            frozen_population_hash, model_freeze_hashes,
            benchmark_contract_version, benchmark_contract_hash,
            cost_policy_version, cost_policy_hash, security_count,
            terminal_counts, enrollment_content_hash, sealed_at
        ) VALUES (
            %(enrollmentId)s, %(idempotencyKey)s, %(canonicalRequestHash)s,
            %(schemaVersion)s, %(preregistrationContentHash)s,
            %(decisionManifestContentHash)s,
            %(decisionControlledArtifactHash)s,
            %(decisionControlledArtifactReference)s,
            %(decisionDataSnapshotId)s, %(decisionAsOf)s,
            %(effectiveAtCompletedSessionOpen)s, %(universeVersion)s,
            %(frozenPopulationHash)s, %(modelFreezeHashes)s,
            %(benchmarkContractVersion)s, %(benchmarkContractHash)s,
            %(costPolicyVersion)s, %(costPolicyHash)s, %(securityCount)s,
            %(terminalCounts)s, %(enrollmentContentHash)s, %(sealedAt)s
        )
    """
    with psycopg.connect(DATABASE_URL) as connection:
        legacy = dict(values)
        legacy["schemaVersion"] = "FORWARD-DQV-ENROLLMENT-v2.1.0"
        with pytest.raises(psycopg.errors.CheckViolation):
            with connection.transaction():
                connection.execute(insert, legacy)

        after_entry = dict(values)
        after_entry["sealedAt"] = valid.effective_at_completed_session_open + timedelta(seconds=1)
        with pytest.raises(psycopg.errors.CheckViolation):
            with connection.transaction():
                connection.execute(insert, after_entry)


def test_v19_stored_path_sql_reads_exact_price_action_and_adtv_evidence(
    repository: ForwardDqvOutcomeRepositoryV211,
) -> None:
    assert DATABASE_URL is not None
    enrollment = _enrollment()
    fixture_nonce = str(uuid4())
    session_closes = tuple(
        enrollment.effective_at_completed_session_open + timedelta(days=index, hours=6, minutes=30)
        for index in range(5)
    )
    observed_at = session_closes[-1] + timedelta(hours=1)
    with psycopg.connect(DATABASE_URL) as connection:
        security = connection.execute(
            """
            SELECT id, public_id, symbol
            FROM analytics.security
            WHERE symbol = 'V18TEST'
            """
        ).fetchone()
        assert security is not None
        provider_id = connection.execute(
            """
            INSERT INTO analytics.data_provider (
                code, name, provider_schema_version
            ) VALUES (
                'maturity_path_v22_fixture',
                'Maturity Path V22 Fixture',
                'fixture-v1'
            )
            ON CONFLICT (code) DO UPDATE
            SET provider_schema_version = EXCLUDED.provider_schema_version
            RETURNING id
            """
        ).fetchone()[0]
        batch_id = connection.execute(
            """
            INSERT INTO analytics.ingestion_batch (
                provider_id, request_key, status, parser_version,
                normalization_version, started_at, completed_at
            ) VALUES (
                %s, %s, 'SUCCEEDED',
                'fixture-v1', 'fixture-v1', %s, %s
            )
            RETURNING id
            """,
            (
                provider_id,
                f"maturity-path-v22-fixture-{fixture_nonce}",
                enrollment.decision_as_of,
                enrollment.decision_as_of,
            ),
        ).fetchone()[0]
        source_id = connection.execute(
            """
            INSERT INTO analytics.source_record (
                ingestion_batch_id, provider_id, source_reference,
                available_at, ingested_at, schema_version,
                revision_status, quality_status, content_hash
            ) VALUES (
                %s, %s, %s,
                %s, %s, 'fixture-v1', 'AS_REPORTED', 'VALIDATED',
                %s
            )
            RETURNING id
            """,
            (
                batch_id,
                provider_id,
                f"fixture://maturity-path-v22/{fixture_nonce}",
                enrollment.decision_as_of,
                enrollment.decision_as_of,
                canonical_hash({"fixtureNonce": fixture_nonce}),
            ),
        ).fetchone()[0]
        for index, session_close in enumerate(session_closes):
            price = Decimal("100") + Decimal(index)
            connection.execute(
                """
                INSERT INTO analytics.daily_price_observation (
                    security_id, trading_date, open_price, high_price,
                    low_price, close_price, adjusted_close, volume,
                    provider_id, adjustment_mode, source_timezone,
                    revision_number, source_record_id, available_at,
                    ingested_at, normalization_version, quality_status
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, 1000000,
                    %s, 'TOTAL_RETURN_ADJUSTED', 'America/New_York',
                    1, %s, %s, %s, 'fixture-v1', 'VALIDATED'
                )
                """,
                (
                    security[0],
                    session_close.date(),
                    price,
                    price + 2,
                    price - 1,
                    price + 1,
                    price + 1,
                    provider_id,
                    source_id,
                    session_close + timedelta(minutes=1),
                    session_close + timedelta(minutes=2),
                ),
            )
        connection.execute(
            """
            INSERT INTO analytics.metric_definition (
                metric_code, metric_version, value_type, unit_policy,
                description, definition_hash
            ) VALUES (
                'average_daily_dollar_volume',
                'ADTV-20-COMPLETED-SESSIONS-v1.0.0',
                'NUMERIC', 'USD',
                'Decision-time ADTV fixture',
                'sha256:maturity-path-v22-adtv-definition'
            )
            ON CONFLICT (metric_code, metric_version) DO NOTHING
            """
        )
        connection.execute(
            """
            INSERT INTO analytics.metric_observation (
                security_id, metric_code, metric_version, observation_date,
                status, numeric_value, unit, currency, source_record_id,
                effective_at, available_at, ingested_at, revision_number
            ) VALUES (
                %s, 'average_daily_dollar_volume',
                'ADTV-20-COMPLETED-SESSIONS-v1.0.0',
                %s, 'VALID', 1000000, 'USD', 'USD', %s, %s, %s, %s, 1
            )
            """,
            (
                security[0],
                enrollment.decision_as_of.date(),
                source_id,
                enrollment.decision_as_of,
                enrollment.decision_as_of,
                enrollment.decision_as_of,
            ),
        )
        action_detail = {
            "evidence": {
                "reconciliationState": "RECONCILED",
                "adjustedPriceRevisionManifestHash": ("sha256:" + "b" * 64),
            }
        }
        action_hash = canonical_hash(action_detail)
        connection.execute(
            """
            INSERT INTO analytics.analytics_audit_event (
                event_type, entity_type, entity_id, actor_service,
                occurred_at, event_hash, detail
            ) VALUES (
                'ACTION_ADJUSTMENT_RECONCILIATION',
                'SECURITY_PATH', %s, 'PYTHON_ANALYTICS', %s, %s, %s
            )
            ON CONFLICT (event_hash) DO NOTHING
            """,
            (
                f"{security[1]}:{session_closes[-1].date().isoformat()}",
                observed_at - timedelta(minutes=1),
                action_hash,
                Jsonb(action_detail),
            ),
        )

    loader = PostgresMaturityEvidenceReadRepositoryV22(
        DATABASE_URL,
        repository_root=Path.cwd(),
    )
    subject = FrozenSecurityV22(
        database_security_id=security[0],
        public_security_id=security[1],
        symbol=security[2],
        role="PRIMARY",
        exclusion_reason=None,
    )
    calendar = CompletedSessionCalendarReadV22(
        state=EvidenceState.READY,
        session_closes=session_closes,
        evidence_hash=canonical_hash([item.isoformat() for item in session_closes]),
    )
    ready = loader.load_security_path(
        enrollment=enrollment,
        subject=subject,
        calendar=calendar,
        observed_at=observed_at,
    )
    assert ready.state == EvidenceState.READY
    assert len(ready.bars) == 5
    assert ready.entry_open == Decimal("100")
    assert ready.average_daily_dollar_volume == Decimal("1000000")

    missing_calendar = CompletedSessionCalendarReadV22(
        state=EvidenceState.READY,
        session_closes=(*session_closes, session_closes[-1] + timedelta(days=1)),
        evidence_hash=canonical_hash(
            [
                item.isoformat()
                for item in (
                    *session_closes,
                    session_closes[-1] + timedelta(days=1),
                )
            ]
        ),
    )
    missing = loader.load_security_path(
        enrollment=enrollment,
        subject=subject,
        calendar=missing_calendar,
        observed_at=observed_at + timedelta(days=1),
    )
    assert missing.state == EvidenceState.MISSING
    assert missing.reason_codes == ("EXACT_COMPLETED_SESSION_PRICE_PATH_MISSING",)
