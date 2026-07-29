import os
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid5

import psycopg
import pytest
from psycopg.conninfo import conninfo_to_dict

from equity_analysis.market_intelligence.models import (
    EvidenceLineage,
    RankMetric,
    ScreeningRequest,
)
from equity_analysis.market_intelligence.persistence import (
    MarketIntelligenceRepository,
    canonical_hash,
)
from equity_analysis.market_intelligence.pipeline import MarketIntelligenceAssembler
from equity_analysis.market_intelligence.service import screen_profiles

DATABASE_URL = os.getenv("MARKET_INTELLIGENCE_V17_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="MARKET_INTELLIGENCE_V17_TEST_DATABASE_URL is not configured",
)

AS_OF = datetime(2026, 7, 28, 22, tzinfo=UTC)
AVAILABLE_AT = AS_OF - timedelta(hours=1)
UNIVERSE_VERSION = "market-intelligence-postgres-v17-fixture"
PROVIDER_CODE = "market_intelligence_v17_fixture"
SCREENING_IDEMPOTENCY_LABEL = "market-intelligence-v17-fixture"
NAMESPACE = UUID("70f19133-3a42-4789-ae40-bef4a7c5e264")


def _assert_isolated_database() -> None:
    assert DATABASE_URL is not None
    database_name = conninfo_to_dict(DATABASE_URL).get("dbname", "")
    if "test" not in database_name.lower():
        raise RuntimeError(
            "MARKET_INTELLIGENCE_V17_TEST_DATABASE_URL must name an isolated test database"
        )


def _reset_fixture_database(connection) -> None:
    connection.execute(
        """
        TRUNCATE TABLE
            analytics.analytics_audit_event,
            analytics.data_snapshot,
            analytics.security,
            analytics.data_provider,
            analytics.universe_definition,
            analytics.classification_node,
            analytics.exchange
        RESTART IDENTITY CASCADE
        """
    )


def _bootstrap_fixture(connection) -> tuple[UUID, tuple[UUID, ...]]:
    schema_version = connection.execute(
        "SELECT MAX(installed_rank) FROM flyway_schema_history WHERE success = TRUE"
    ).fetchone()
    assert schema_version is not None and schema_version[0] >= 17
    connection.execute(
        """
        INSERT INTO analytics.exchange (
            mic, acronym, name, country_code, timezone, currency
        ) VALUES ('XNAS', 'NASDAQ', 'Nasdaq Test Fixture', 'US',
                  'America/New_York', 'USD')
        """
    )
    connection.execute(
        """
        INSERT INTO analytics.classification_node (
            taxonomy_code, taxonomy_version, node_code, parent_node_code,
            level, name, effective_from
        ) VALUES
            ('GICS', 'GICS-TEST-v1', '45', NULL,
             'SECTOR', 'Information Technology', DATE '2020-01-01'),
            ('GICS', 'GICS-TEST-v1', '4510', '45',
             'INDUSTRY', 'Software and Services', DATE '2020-01-01')
        """
    )
    provider_id = connection.execute(
        """
        INSERT INTO analytics.data_provider (
            code, name, provider_schema_version
        ) VALUES (%s, 'Market Intelligence V17 Fixture', 'fixture-v1')
        RETURNING id
        """,
        (PROVIDER_CODE,),
    ).fetchone()[0]
    batch_id = connection.execute(
        """
        INSERT INTO analytics.ingestion_batch (
            provider_id, request_key, status, parser_version,
            normalization_version, started_at, completed_at
        ) VALUES (
            %s, 'market-intelligence-v17-fixture', 'SUCCEEDED',
            'fixture-parser-v1', 'fixture-normalization-v1', %s, %s
        ) RETURNING id
        """,
        (provider_id, AVAILABLE_AT, AVAILABLE_AT),
    ).fetchone()[0]
    source_id = connection.execute(
        """
        INSERT INTO analytics.source_record (
            ingestion_batch_id, provider_id, source_reference, available_at,
            ingested_at, schema_version, revision_status, quality_status,
            content_hash
        ) VALUES (
            %s, %s, 'fixture://market-intelligence-v17', %s, %s,
            'fixture-v1', 'AS_REPORTED', 'VALIDATED',
            'sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'
        ) RETURNING id
        """,
        (batch_id, provider_id, AVAILABLE_AT, AVAILABLE_AT),
    ).fetchone()[0]
    connection.execute(
        """
        INSERT INTO analytics.universe_definition (
            version, effective_at, configuration, configuration_hash
        ) VALUES (
            %s, %s, '{"market":"US","securityCount":66}'::jsonb,
            'sha256:market-intelligence-postgres-v17-fixture'
        )
        """,
        (UNIVERSE_VERSION, AS_OF - timedelta(days=1)),
    )
    snapshot_id = connection.execute(
        """
        INSERT INTO analytics.data_snapshot (
            snapshot_key, status, as_of_time, ingestion_cutoff,
            market_normalization_version, fundamental_normalization_version,
            action_normalization_version, manifest_hash,
            market_data_provider, market_adjustment_mode
        ) VALUES (
            'market-intelligence-v17-fixture', 'BUILDING', %s, %s,
            'market-fixture-v1', 'fundamental-fixture-v1', 'action-fixture-v1',
            'sha256:market-intelligence-postgres-v17-snapshot',
            %s, 'TOTAL_RETURN_ADJUSTED'
        ) RETURNING id
        """,
        (AS_OF, AS_OF, PROVIDER_CODE),
    ).fetchone()[0]
    connection.execute(
        """
        INSERT INTO analytics.data_snapshot_source (
            snapshot_id, ingestion_batch_id
        ) VALUES (%s, %s)
        """,
        (snapshot_id, batch_id),
    )

    public_ids: list[UUID] = []
    start = date(2026, 4, 1)
    for ordinal in range(66):
        symbol = (
            "SPY"
            if ordinal == 0
            else "AAPL"
            if ordinal == 1
            else "MSFT"
            if ordinal == 2
            else f"MI{ordinal:03d}"
        )
        public_id = uuid5(NAMESPACE, symbol)
        public_ids.append(public_id)
        security_id = connection.execute(
            """
            INSERT INTO analytics.security (
                public_id, symbol, exchange, name, instrument_type,
                currency, active
            ) VALUES (%s, %s, 'NASDAQ', %s, %s, 'USD', TRUE)
            RETURNING id
            """,
            (
                public_id,
                symbol,
                f"{symbol} Fixture Company",
                "ETF" if symbol == "SPY" else "COMMON_STOCK",
            ),
        ).fetchone()[0]
        connection.execute(
            """
            INSERT INTO analytics.security_listing (
                security_id, symbol, exchange, mic, currency, valid_from,
                source_record_id
            ) VALUES (%s, %s, 'NASDAQ', 'XNAS', 'USD',
                      DATE '2020-01-01', %s)
            """,
            (security_id, symbol, source_id),
        )
        connection.execute(
            """
            INSERT INTO analytics.company_profile_observation (
                security_id, legal_name, primary_mic, taxonomy_code,
                taxonomy_version, sector_code, industry_code,
                effective_from, revision_number, source_record_id,
                available_at, ingested_at, quality_status
            ) VALUES (
                %s, %s, 'XNAS', 'GICS', 'GICS-TEST-v1', '45', '4510',
                DATE '2020-01-01', 1, %s, %s, %s, 'VALIDATED'
            )
            """,
            (
                security_id,
                f"{symbol} Fixture Company",
                source_id,
                AVAILABLE_AT,
                AVAILABLE_AT,
            ),
        )
        if ordinal < 55:
            membership_status = "INCLUDED"
            membership_reason = "PRIMARY" if ordinal < 48 else "RESERVE"
            company_type = "MATURE_OPERATING_COMPANY"
        elif ordinal < 57:
            membership_status = "REFERENCE_ONLY"
            membership_reason = "BENCHMARK"
            company_type = "BENCHMARK"
        else:
            membership_status = "EXCLUDED"
            membership_reason = "SPECIALIZED_MODEL_REQUIRED"
            company_type = "FINANCIAL"
        connection.execute(
            """
            INSERT INTO analytics.snapshot_universe_member (
                snapshot_id, universe_version, security_id, membership_status,
                membership_reason, symbol_at_snapshot,
                company_type_at_snapshot, normalized_sector_at_snapshot
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, 'Information Technology')
            """,
            (
                snapshot_id,
                UNIVERSE_VERSION,
                security_id,
                membership_status,
                membership_reason,
                symbol,
                company_type,
            ),
        )
        for session in range(65):
            trading_date = start + timedelta(days=session)
            close = Decimal(100 + ordinal) + Decimal(session) / Decimal(10)
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
                    1, %s, %s, %s, 'fixture-normalization-v1', 'VALIDATED'
                )
                """,
                (
                    security_id,
                    trading_date,
                    close - 1,
                    close + 1,
                    close - 2,
                    close,
                    close,
                    provider_id,
                    source_id,
                    AVAILABLE_AT,
                    AVAILABLE_AT,
                ),
            )
        connection.execute(
            """
            INSERT INTO analytics.market_value_observation (
                security_id, metric_code, observation_date, numeric_value,
                unit, currency, provider_id, revision_number,
                source_record_id, available_at, ingested_at,
                normalization_version
            ) VALUES (
                %s, 'MARKET_CAP', DATE '2026-06-04', %s,
                'USD', 'USD', %s, 1, %s, %s, %s,
                'fixture-normalization-v1'
            )
            """,
            (
                security_id,
                Decimal("10000000000") + Decimal(ordinal),
                provider_id,
                source_id,
                AVAILABLE_AT,
                AVAILABLE_AT,
            ),
        )
    connection.execute(
        """
        UPDATE analytics.data_snapshot
        SET status = 'READY', source_count = 1, security_count = 66,
            sealed_at = %s
        WHERE id = %s
        """,
        (AS_OF, snapshot_id),
    )
    return snapshot_id, tuple(public_ids)


def test_v17_market_intelligence_snapshot_to_forward_handoff_is_idempotent() -> None:
    _assert_isolated_database()
    assert DATABASE_URL is not None
    with psycopg.connect(DATABASE_URL) as connection:
        _reset_fixture_database(connection)
        snapshot_id, public_ids = _bootstrap_fixture(connection)

    assembler = MarketIntelligenceAssembler(DATABASE_URL)
    first = assembler.assemble_snapshot(
        data_snapshot_id=snapshot_id,
        universe_version=UNIVERSE_VERSION,
    )
    second = assembler.assemble_snapshot(
        data_snapshot_id=snapshot_id,
        universe_version=UNIVERSE_VERSION,
    )

    assert first.profile_ids == second.profile_ids
    assert len(first.profile_ids) == 66
    assert set(first.profiles_by_security) == {str(item) for item in public_ids}
    assert first.objective_screening_run_id is None

    repository = MarketIntelligenceRepository(DATABASE_URL)
    profiles = tuple(
        repository.load_profile(profile_id) for profile_id in first.profile_ids
    )
    assert all(profile.ai_narrative.status == "NOT_EXECUTED" for profile in profiles)
    assert all(profile.ranking_state.value == "NOT_ELIGIBLE" for profile in profiles)
    assert {profile.security.symbol for profile in profiles} >= {"SPY", "AAPL", "MSFT"}

    request = ScreeningRequest(as_of=AS_OF, rank_by=RankMetric.OBJECTIVE_QUALITY)
    result = screen_profiles(profiles, request)
    assert result.items == ()
    assert result.acceptance["gateStatus"] == "NO_ELIGIBLE_RESULTS"
    profile_ids = {
        profile.security.security_id: profile_id
        for profile_id, profile in zip(first.profile_ids, profiles, strict=True)
    }
    run_id = repository.persist_screening_run(
        request,
        result,
        profile_ids,
        idempotency_key=SCREENING_IDEMPOTENCY_LABEL,
        data_snapshot_id=snapshot_id,
        universe_version=UNIVERSE_VERSION,
    )
    duplicate_run_id = repository.persist_screening_run(
        request,
        result,
        profile_ids,
        idempotency_key=SCREENING_IDEMPOTENCY_LABEL,
        data_snapshot_id=snapshot_id,
        universe_version=UNIVERSE_VERSION,
    )
    assert duplicate_run_id == run_id

    event_hash = repository.persist_decision_snapshot_event(
        data_snapshot_id=snapshot_id,
        universe_version=UNIVERSE_VERSION,
        objective_screening_run_id=None,
        profile_ids=first.profile_ids,
        screening_run_ids=(run_id,),
        as_of=AS_OF,
    )
    duplicate_event_hash = repository.persist_decision_snapshot_event(
        data_snapshot_id=snapshot_id,
        universe_version=UNIVERSE_VERSION,
        objective_screening_run_id=None,
        profile_ids=first.profile_ids,
        screening_run_ids=(run_id,),
        as_of=AS_OF,
    )
    assert duplicate_event_hash == event_hash

    metadata = repository.load_run_metadata(run_id)
    page = repository.load_screening_page(run_id, cursor=None, limit=20)
    envelope = repository.load_profile_envelope(first.profile_ids[0])
    assert metadata.gate_status == "NO_ELIGIBLE_RESULTS"
    assert metadata.profile_set_hash == first.profile_set_hash
    assert page.items == ()
    assert envelope.current_market_data.state == "VALID"
    assert envelope.current_market_data.price is not None
    assert envelope.current_market_data.provider_code == PROVIDER_CODE

    with psycopg.connect(DATABASE_URL) as connection:
        counts = connection.execute(
            """
            SELECT
              (SELECT COUNT(*) FROM analytics.security_profile_snapshot),
              (SELECT COUNT(*) FROM analytics.metric_observation),
              (SELECT COUNT(*) FROM analytics.market_intelligence_screening_run),
              (SELECT COUNT(*) FROM analytics.market_intelligence_screening_result),
              (SELECT COUNT(*) FROM analytics.market_intelligence_ai_narrative),
              (SELECT COUNT(*) FROM analytics.analytics_audit_event
               WHERE event_type = 'MARKET_INTELLIGENCE_DECISION_SNAPSHOT_SEALED')
            """
        ).fetchone()
        audit = connection.execute(
            """
            SELECT detail->>'dataSnapshotId', detail->>'universeVersion',
                   detail->>'profileSetHash', detail->>'screeningRunSetHash',
                   detail->>'aiStatus'
            FROM analytics.analytics_audit_event
            WHERE event_hash = %s
            """,
            (event_hash,),
        ).fetchone()
    assert counts == (66, 198, 1, 0, 0, 1)
    assert audit == (
        str(snapshot_id),
        UNIVERSE_VERSION,
        first.profile_set_hash,
        canonical_hash((str(run_id),)),
        "NOT_EXECUTED",
    )


def test_metric_materialization_appends_revision_when_missing_becomes_valid() -> None:
    _assert_isolated_database()
    assert DATABASE_URL is not None
    with psycopg.connect(DATABASE_URL) as connection:
        _reset_fixture_database(connection)
        _, public_ids = _bootstrap_fixture(connection)
        security_id = connection.execute(
            "SELECT id FROM analytics.security WHERE public_id = %s",
            (public_ids[1],),
        ).fetchone()[0]
        source = connection.execute(
            """
            SELECT source.id, provider.code, provider.provider_schema_version,
                   batch.parser_version, source.source_reference,
                   source.content_hash, source.available_at, source.ingested_at
            FROM analytics.source_record source
            JOIN analytics.data_provider provider ON provider.id = source.provider_id
            JOIN analytics.ingestion_batch batch
              ON batch.id = source.ingestion_batch_id
            WHERE provider.code = %s
            """,
            (PROVIDER_CODE,),
        ).fetchone()
        observation_date = date(2026, 6, 4)
        lineage = (
            EvidenceLineage(
                provider_code=source[1],
                provider_schema_version=source[2],
                parser_version=source[3],
                source_reference=source[4],
                content_hash=source[5],
                effective_at=datetime.combine(
                    observation_date,
                    datetime.min.time(),
                    UTC,
                ),
                available_at=source[6],
                retrieved_at=source[7],
            ),
        )

        for _ in range(2):
            MarketIntelligenceAssembler._materialize_metric(
                connection,
                security_id=security_id,
                name="latest_price",
                observation_date=observation_date,
                value=None,
                unit="PRICE",
                currency=None,
                reason="PRICE_OBSERVATION_MISSING",
                source_id=None,
                lineage=(),
            )
        for _ in range(2):
            MarketIntelligenceAssembler._materialize_metric(
                connection,
                security_id=security_id,
                name="latest_price",
                observation_date=observation_date,
                value=Decimal("123.45"),
                unit="PRICE",
                currency=None,
                reason=None,
                source_id=source[0],
                lineage=lineage,
            )

        observations = connection.execute(
            """
            SELECT revision_number, status, numeric_value, reason_code
            FROM analytics.metric_observation
            WHERE security_id = %s
              AND metric_code = 'latest_price'
              AND observation_date = %s
            ORDER BY revision_number
            """,
            (security_id, observation_date),
        ).fetchall()

    assert observations == [
        (1, "MISSING", None, "PRICE_OBSERVATION_MISSING"),
        (2, "VALID", Decimal("123.450000000000"), None),
    ]
