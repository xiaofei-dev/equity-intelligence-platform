import os
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal

import psycopg
import pytest
from psycopg.conninfo import conninfo_to_dict

from equity_analysis.daily_refresh.persistence import (
    DatasetCodes,
    PostgresRefreshPersistence,
)
from equity_analysis.market_data.fundamentals import (
    FundamentalsEnvelope,
    normalize_current_company_profile,
    normalize_current_market_capitalization,
)
from equity_analysis.market_data.models import (
    ProviderCapability,
    ProviderDescriptor,
    ProviderUseClassification,
)
from equity_analysis.provider_validation.models import (
    NormalizedFinancialObservation,
)

DATABASE_URL = os.getenv("DAILY_REFRESH_V16_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="DAILY_REFRESH_V16_TEST_DATABASE_URL is not configured",
)
NOW = datetime(2026, 7, 28, 23, tzinfo=UTC)
SOURCE_HASH = f"sha256:{'9' * 64}"
SOURCE_REFERENCE = "fixture:fundamentals:AAPL.US:current-envelope-v1"
DESCRIPTOR = ProviderDescriptor(
    code="current_fundamentals_fixture",
    name="Current Fundamentals Fixture",
    provider_schema_version="fixture-fundamentals-v1",
    parser_version="fixture-fundamentals-parser-v1",
    capabilities=frozenset({ProviderCapability.FUNDAMENTALS}),
    use_classification=ProviderUseClassification.DEVELOPMENT,
)
CODES = DatasetCodes(
    refresh_plan="daily_market_refresh_v1",
    unadjusted_price="daily_price_unadjusted_v1",
    total_return_adjusted_price="daily_price_total_return_adjusted_v1",
    corporate_action="corporate_action_v1",
)


def _envelope() -> FundamentalsEnvelope:
    financial = NormalizedFinancialObservation(
        symbol="AAPL",
        provider_symbol="AAPL.US",
        statement_type="INCOME_STATEMENT",
        period_type="ANNUAL",
        fiscal_period_end=date(2025, 9, 27),
        currency="USD",
        values={"revenue": Decimal("416161000000")},
        source_reference="fixture:fundamentals:AAPL.US:yearly",
        content_hash="8" * 64,
        provider_schema_version=DESCRIPTOR.provider_schema_version,
        parser_version=DESCRIPTOR.parser_version,
        effective_at=datetime(2025, 9, 27, tzinfo=UTC),
        available_at=NOW,
        ingested_at=NOW,
    )
    return FundamentalsEnvelope(
        provider_descriptor=DESCRIPTOR,
        requested_symbol="AAPL",
        provider_symbol="AAPL.US",
        source_reference=SOURCE_REFERENCE,
        content_hash=SOURCE_HASH,
        available_at=NOW,
        retrieved_at=NOW,
        financial_observations=(financial,),
        company_profile=normalize_current_company_profile(
            legal_name="Apple Inc.",
            sector="Technology",
            industry="Consumer Electronics",
            effective_at=NOW,
        ),
        market_capitalization=normalize_current_market_capitalization(
            value="3210000000000",
            currency="USD",
            effective_at=NOW,
        ),
    )


def test_current_fundamentals_share_exact_source_lineage_and_are_idempotent() -> None:
    assert DATABASE_URL is not None
    database_name = conninfo_to_dict(DATABASE_URL).get("dbname", "").lower()
    if "test" not in database_name:
        pytest.skip("Configured database is not explicitly named as a test database")

    with psycopg.connect(DATABASE_URL) as connection:
        security = connection.execute(
            "SELECT public_id FROM analytics.security WHERE symbol = 'AAPL'"
        ).fetchone()
    if security is None:
        pytest.skip("The isolated PostgreSQL fixture has no AAPL security")

    persistence = PostgresRefreshPersistence(
        DATABASE_URL,
        refresh_plan_key="plan",
        refresh_plan_version=1,
        dataset_codes=CODES,
        now=lambda: NOW,
    )
    envelope = _envelope()
    first = persistence.write_fundamentals(str(security[0]), envelope)
    second = persistence.write_fundamentals(str(security[0]), envelope)

    assert first.content_hash == SOURCE_HASH
    assert first.source_reference == SOURCE_REFERENCE
    assert first.available_at == NOW
    assert first.ingested_at == NOW
    assert second.rows_written == 0

    with psycopg.connect(DATABASE_URL) as connection:
        lineage = connection.execute(
            """
            SELECT sr.id, sr.content_hash, sr.available_at, sr.ingested_at
            FROM analytics.source_record sr
            JOIN analytics.data_provider dp ON dp.id = sr.provider_id
            WHERE dp.code = %s AND sr.source_reference = %s
              AND sr.content_hash = %s
            """,
            (DESCRIPTOR.code, SOURCE_REFERENCE, SOURCE_HASH),
        ).fetchall()
        profile = connection.execute(
            """
            SELECT cp.source_record_id, cp.legal_name, cp.taxonomy_code,
                   cp.sector_code, cp.industry_code,
                   cp.available_at, cp.ingested_at
            FROM analytics.company_profile_observation cp
            JOIN analytics.security s ON s.id = cp.security_id
            JOIN analytics.source_record sr ON sr.id = cp.source_record_id
            WHERE s.symbol = 'AAPL' AND sr.source_reference = %s
              AND sr.content_hash = %s
            """,
            (SOURCE_REFERENCE, SOURCE_HASH),
        ).fetchall()
        market_cap = connection.execute(
            """
            SELECT mv.source_record_id, mv.numeric_value, mv.currency,
                   mv.available_at, mv.ingested_at
            FROM analytics.market_value_observation mv
            JOIN analytics.security s ON s.id = mv.security_id
            JOIN analytics.source_record sr ON sr.id = mv.source_record_id
            WHERE s.symbol = 'AAPL' AND mv.metric_code = 'MARKET_CAP'
              AND sr.source_reference = %s AND sr.content_hash = %s
            """,
            (SOURCE_REFERENCE, SOURCE_HASH),
        ).fetchall()
        financial = connection.execute(
            """
            SELECT ff.source_record_id, ff.numeric_value,
                   ff.available_at, ff.ingested_at
            FROM analytics.fundamental_fact ff
            JOIN analytics.security s ON s.id = ff.security_id
            JOIN analytics.source_record sr ON sr.id = ff.source_record_id
            WHERE s.symbol = 'AAPL' AND ff.metric_code = 'revenue'
              AND sr.source_reference = %s AND sr.content_hash = %s
            """,
            (SOURCE_REFERENCE, SOURCE_HASH),
        ).fetchall()

    assert len(lineage) == 1
    assert len(profile) == 1
    assert len(market_cap) == 1
    assert len(financial) == 1
    source_id = lineage[0][0]
    assert profile[0][0] == market_cap[0][0] == financial[0][0] == source_id
    assert lineage[0][1:] == (SOURCE_HASH, NOW, NOW)
    assert profile[0][1] == "Apple Inc."
    assert profile[0][2] == "PROVIDER_CURRENT"
    assert profile[0][3] is not None
    assert profile[0][4] is not None
    assert profile[0][5:] == (NOW, NOW)
    assert market_cap[0][1:] == (Decimal("3210000000000"), "USD", NOW, NOW)
    assert financial[0][1:] == (Decimal("416161000000"), NOW, NOW)


def test_cached_projection_is_idempotent_and_does_not_duplicate_financial_facts() -> None:
    assert DATABASE_URL is not None
    database_name = conninfo_to_dict(DATABASE_URL).get("dbname", "").lower()
    if "test" not in database_name:
        pytest.skip("Configured database is not explicitly named as a test database")
    with psycopg.connect(DATABASE_URL) as connection:
        security = connection.execute(
            "SELECT public_id FROM analytics.security WHERE symbol = 'AAPL'"
        ).fetchone()
        if security is not None:
            connection.execute(
                """
                INSERT INTO analytics.security_classification (
                    security_id, classification_version, normalized_sector,
                    normalized_industry, company_type, effective_from
                )
                SELECT id, 'fixture-company-type-v1', 'FIXTURE', 'FIXTURE',
                       'MATURE_OPERATING_COMPANY', DATE '1970-01-01'
                FROM analytics.security WHERE symbol = 'AAPL'
                ON CONFLICT ON CONSTRAINT uq_security_classification_version
                DO NOTHING
                """
            )
        before_financial = connection.execute(
            """
            SELECT COUNT(*) FROM analytics.fundamental_fact fact
            JOIN analytics.security security ON security.id = fact.security_id
            WHERE security.symbol = 'AAPL'
            """
        ).fetchone()[0]
    if security is None:
        pytest.skip("The isolated PostgreSQL fixture has no AAPL security")

    persistence = PostgresRefreshPersistence(
        DATABASE_URL,
        refresh_plan_key="plan",
        refresh_plan_version=1,
        dataset_codes=CODES,
        now=lambda: NOW,
    )
    envelope = replace(
        _envelope(),
        source_reference="fixture:captured:AAPL:current-projection-v1",
        content_hash=f"sha256:{'7' * 64}",
    )
    storage_reference = "storage/provider-validation/fixture/AAPL.bin"
    first = persistence.write_current_fundamentals_projection(
        str(security[0]),
        envelope,
        storage_reference=storage_reference,
    )
    second = persistence.write_current_fundamentals_projection(
        str(security[0]),
        envelope,
        storage_reference=storage_reference,
    )

    assert first.rows_written == 3
    assert second.rows_written == 0
    with psycopg.connect(DATABASE_URL) as connection:
        source = connection.execute(
            """
            SELECT storage_reference
            FROM analytics.source_record
            WHERE source_reference = %s AND content_hash = %s
            """,
            (envelope.source_reference, envelope.content_hash),
        ).fetchone()
        classification = connection.execute(
            """
            SELECT normalized_sector, normalized_industry, company_type,
                   source_record_id
            FROM analytics.security_classification classification
            JOIN analytics.security security
              ON security.id = classification.security_id
            WHERE security.symbol = 'AAPL'
              AND classification.classification_version =
                  'provider-current-replay-v1.0.0'
              AND classification.effective_from = %s
            """,
            (NOW.date(),),
        ).fetchone()
        after_financial = connection.execute(
            """
            SELECT COUNT(*) FROM analytics.fundamental_fact fact
            JOIN analytics.security security ON security.id = fact.security_id
            WHERE security.symbol = 'AAPL'
            """
        ).fetchone()[0]
        audit_count = connection.execute(
            """
            SELECT COUNT(*) FROM analytics.analytics_audit_event
            WHERE event_type = 'PROVIDER_CACHE_REPLAY'
              AND entity_id = %s
            """,
            (str(security[0]),),
        ).fetchone()[0]

    assert source == (storage_reference,)
    assert classification is not None
    assert classification[:3] == (
        "Technology",
        "Consumer Electronics",
        "MATURE_OPERATING_COMPANY",
    )
    assert after_financial == before_financial
    assert audit_count == 1
