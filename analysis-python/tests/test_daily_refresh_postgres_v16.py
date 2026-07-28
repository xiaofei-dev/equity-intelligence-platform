import os
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal

import psycopg
import pytest

from equity_analysis.daily_refresh.calendar import UnitedStatesMarketCalendar
from equity_analysis.daily_refresh.models import SecurityTarget
from equity_analysis.daily_refresh.persistence import (
    DatasetCodes,
    PostgresRefreshPersistence,
    require_v16_contract,
)
from equity_analysis.daily_refresh.planner import DailyRefreshPlanner
from equity_analysis.daily_refresh.runner import DailyRefreshRunner
from equity_analysis.market_data.models import (
    AdjustmentMode,
    CorporateAction,
    CorporateActionSeries,
    DailyPriceBar,
    DailyPriceSeries,
    ProviderCapability,
    ProviderDescriptor,
    ProviderUseClassification,
    SecurityMetadata,
)

DATABASE_URL = os.getenv("DAILY_REFRESH_V16_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="DAILY_REFRESH_V16_TEST_DATABASE_URL is not configured",
)
NOW = datetime(2026, 7, 28, 23, tzinfo=UTC)
CODES = DatasetCodes(
    refresh_plan="daily_market_refresh_v1",
    unadjusted_price="daily_price_unadjusted_v1",
    total_return_adjusted_price="daily_price_total_return_adjusted_v1",
    corporate_action="corporate_action_v1",
)
DESCRIPTOR = ProviderDescriptor(
    code="integration_fixture",
    name="Integration Fixture",
    provider_schema_version="fixture-v1",
    parser_version="fixture-parser-v1",
    capabilities=frozenset(
        {ProviderCapability.DAILY_PRICES, ProviderCapability.CORPORATE_ACTIONS}
    ),
    use_classification=ProviderUseClassification.DEVELOPMENT,
)


class FixtureProvider:
    descriptor = DESCRIPTOR

    def fetch_daily_prices(self, symbol: str, start_date: date, end_date: date):
        bar = DailyPriceBar(
            trading_date=end_date,
            open_price=Decimal("100"),
            high_price=Decimal("105"),
            low_price=Decimal("99"),
            close_price=Decimal("104"),
            adjusted_close=Decimal("103.5"),
            volume=1_000_000,
        )
        return DailyPriceSeries(
            security=SecurityMetadata(
                symbol=symbol,
                name=symbol,
                exchange="NASDAQ",
                instrument_type="COMMON_STOCK",
                currency="USD",
                exchange_timezone="America/New_York",
            ),
            provider_descriptor=self.descriptor,
            requested_symbol=symbol,
            provider_symbol=symbol,
            adjustment_mode=AdjustmentMode.TOTAL_RETURN_ADJUSTED,
            bars=(bar,),
            source_reference=f"fixture:prices:{symbol}:{end_date}",
            available_at=NOW,
            retrieved_at=NOW,
        )

    def fetch_corporate_actions(self, symbol: str, start_date: date, end_date: date):
        return CorporateActionSeries(
            provider_descriptor=self.descriptor,
            requested_symbol=symbol,
            provider_symbol=symbol,
            actions=(
                CorporateAction(
                    action_type="DIVIDEND",
                    effective_date=end_date,
                    amount=Decimal("0.25"),
                    currency="USD",
                ),
            ),
            source_reference=f"fixture:actions:{symbol}:{end_date}",
            available_at=NOW,
        )


def test_v16_refresh_and_immutable_writer_are_idempotent() -> None:
    assert DATABASE_URL is not None
    with psycopg.connect(DATABASE_URL) as connection:
        require_v16_contract(connection)
        provider_id = connection.execute(
            """
            INSERT INTO analytics.data_provider (code, name, provider_schema_version)
            VALUES (%s, %s, %s)
            ON CONFLICT (code) DO UPDATE SET name = EXCLUDED.name
            RETURNING id
            """,
            (DESCRIPTOR.code, DESCRIPTOR.name, DESCRIPTOR.provider_schema_version),
        ).fetchone()[0]
        for code in (
            CODES.refresh_plan,
            CODES.unadjusted_price,
            CODES.total_return_adjusted_price,
            CODES.corporate_action,
        ):
            connection.execute(
                """
                INSERT INTO analytics.dataset_definition (
                    dataset_code, owner_service, description, retention_class
                ) VALUES (%s, 'PYTHON_ANALYTICS', %s, 'PERMANENT')
                ON CONFLICT (dataset_code) DO NOTHING
                """,
                (code, f"Offline integration fixture for {code}"),
            )
        connection.execute(
            """
            INSERT INTO analytics.refresh_plan (
                plan_key, plan_version, dataset_code, provider_id, cadence,
                target_scope, freshness_target, task_timeout, maximum_attempts,
                active_from, definition_hash
            ) VALUES (
                'plan', 1, %s, %s, 'DAILY', '{"fixture":true}',
                INTERVAL '2 days', INTERVAL '15 minutes', 3,
                '2026-01-01T00:00:00Z', 'fixture-refresh-plan-v1'
            ) ON CONFLICT (plan_key, plan_version) DO NOTHING
            """,
            (CODES.refresh_plan, provider_id),
        )
        security = connection.execute(
            "SELECT public_id FROM analytics.security WHERE symbol = 'AAPL'"
        ).fetchone()
    target = SecurityTarget(str(security[0]), "AAPL")
    persistence = PostgresRefreshPersistence(
        DATABASE_URL,
        refresh_plan_key="plan",
        refresh_plan_version=1,
        dataset_codes=CODES,
        now=lambda: NOW,
    )
    plan = DailyRefreshPlanner(UnitedStatesMarketCalendar()).plan(
        universe=[target],
        cursors={},
        provider_code=DESCRIPTOR.code,
        universe_version="fixture-universe-v1",
        as_of=NOW,
    )
    provider = FixtureProvider()
    runner = DailyRefreshRunner(
        price_provider=provider,
        action_provider=provider,
        writer=persistence,
        store=persistence,
        calendar=UnitedStatesMarketCalendar(),
        sleeper=lambda _: None,
        now=lambda: NOW,
    )
    first = runner.run(plan)
    second = runner.run(plan)
    assert first.outcome.value == "SUCCEEDED"
    assert second.outcome.value == "SUCCEEDED"
    original_prices = provider.fetch_daily_prices("AAPL", date(2026, 7, 28), date(2026, 7, 28))
    corrected_bar = replace(
        original_prices.bars[0],
        close_price=Decimal("103"),
        adjusted_close=Decimal("102.5"),
    )
    corrected_prices = replace(original_prices, bars=(corrected_bar,))
    persistence.write_prices(corrected_prices, AdjustmentMode.UNADJUSTED.value)
    persistence.write_prices(corrected_prices, AdjustmentMode.UNADJUSTED.value)
    original_actions = provider.fetch_corporate_actions(
        "AAPL", date(2026, 7, 28), date(2026, 7, 28)
    )
    corrected_action = replace(original_actions.actions[0], amount=Decimal("0.30"))
    corrected_actions = replace(original_actions, actions=(corrected_action,))
    persistence.write_actions(corrected_actions)
    persistence.write_actions(corrected_actions)
    with psycopg.connect(DATABASE_URL) as connection:
        assert connection.execute(
            """
            SELECT COUNT(*) FROM analytics.daily_price_observation observation
            JOIN analytics.data_provider provider ON provider.id = observation.provider_id
            WHERE provider.code = %s
            """,
            (DESCRIPTOR.code,),
        ).fetchone()[0] == 3
        assert connection.execute(
            """
            SELECT MAX(revision_number)
            FROM analytics.daily_price_observation observation
            JOIN analytics.data_provider provider ON provider.id = observation.provider_id
            WHERE provider.code = %s
              AND observation.adjustment_mode = 'UNADJUSTED'
            """,
            (DESCRIPTOR.code,),
        ).fetchone()[0] == 2
        assert connection.execute(
            """
            SELECT COUNT(*) FROM analytics.corporate_action action
            JOIN analytics.data_provider provider ON provider.id = action.provider_id
            WHERE provider.code = %s
            """,
            (DESCRIPTOR.code,),
        ).fetchone()[0] == 2
        assert connection.execute(
            """
            SELECT MAX(revision_number)
            FROM analytics.corporate_action action
            JOIN analytics.data_provider provider ON provider.id = action.provider_id
            WHERE provider.code = %s
            """,
            (DESCRIPTOR.code,),
        ).fetchone()[0] == 2
        assert connection.execute(
            """
            SELECT COUNT(*) FROM analytics.security_dataset_freshness freshness
            JOIN analytics.data_provider provider ON provider.id = freshness.provider_id
            WHERE provider.code = %s
            """,
            (DESCRIPTOR.code,),
        ).fetchone()[0] == 3
        assert connection.execute(
            """
            SELECT COUNT(*) FROM analytics.refresh_checkpoint checkpoint
            JOIN analytics.refresh_run run ON run.id = checkpoint.refresh_run_id
            JOIN analytics.refresh_plan plan ON plan.id = run.refresh_plan_id
            WHERE plan.plan_key = 'plan'
            """,
        ).fetchone()[0] == 3
