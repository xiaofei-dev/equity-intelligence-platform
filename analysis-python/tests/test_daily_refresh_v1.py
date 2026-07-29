from contextlib import contextmanager
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

import pytest

from equity_analysis.daily_refresh.calendar import UnitedStatesMarketCalendar
from equity_analysis.daily_refresh.models import (
    Dataset,
    DatasetCursor,
    FreshnessState,
    RefreshOutcome,
    RefreshPolicy,
    SecurityTarget,
)
from equity_analysis.daily_refresh.persistence import WriteResult
from equity_analysis.daily_refresh.planner import DailyRefreshPlanner, RefreshPlanningError
from equity_analysis.daily_refresh.runner import DailyRefreshRunner
from equity_analysis.daily_refresh.scheduler import DailyRefreshScheduler
from equity_analysis.market_data.models import (
    AdjustmentMode,
    CorporateActionSeries,
    DailyPriceBar,
    DailyPriceSeries,
    ProviderCapability,
    ProviderDescriptor,
    ProviderUseClassification,
    SecurityMetadata,
)
from equity_analysis.market_data.provider import MarketDataProviderError

NOW = datetime(2026, 7, 28, 23, tzinfo=UTC)
DESCRIPTOR = ProviderDescriptor(
    code="yfinance",
    name="Fixture",
    provider_schema_version="fixture-v1",
    parser_version="fixture-v1",
    capabilities=frozenset(
        {ProviderCapability.DAILY_PRICES, ProviderCapability.CORPORATE_ACTIONS}
    ),
    use_classification=ProviderUseClassification.DEVELOPMENT_FALLBACK,
)
TARGET = SecurityTarget("00000000-0000-0000-0000-000000000001", "AAPL")


def test_calendar_handles_weekends_and_us_holidays() -> None:
    calendar = UnitedStatesMarketCalendar()
    assert not calendar.is_session(date(2026, 7, 3))
    assert not calendar.is_session(date(2026, 7, 4))
    assert calendar.previous_session(date(2026, 7, 6)) == date(2026, 7, 2)
    assert not calendar.is_session(date(2026, 4, 3))


def test_planner_uses_overlap_and_separates_price_adjustment_modes() -> None:
    calendar = UnitedStatesMarketCalendar()
    planner = DailyRefreshPlanner(calendar)
    cursor = DatasetCursor(
        security_id=TARGET.security_id,
        dataset=Dataset.DAILY_PRICE,
        provider_code="yfinance",
        adjustment_mode=AdjustmentMode.UNADJUSTED,
        last_market_session_date=date(2026, 7, 27),
    )
    plan = planner.plan(
        universe=[TARGET],
        cursors={(TARGET.security_id, Dataset.DAILY_PRICE, AdjustmentMode.UNADJUSTED): cursor},
        provider_code="yfinance",
        universe_version="fixture-v1",
        as_of=NOW,
    )
    assert len(plan.items) == 2
    unadjusted = next(
        item for item in plan.items if item.adjustment_mode == AdjustmentMode.UNADJUSTED
    )
    assert unadjusted.start_date == date(2026, 7, 20)
    assert {item.adjustment_mode for item in plan.items} == {
        AdjustmentMode.UNADJUSTED,
        AdjustmentMode.TOTAL_RETURN_ADJUSTED,
    }
    assert plan.estimated_weighted_calls == 2


def test_planner_fails_closed_before_eodhd_budget_can_be_exceeded() -> None:
    policy = RefreshPolicy(
        max_attempts=3,
        eodhd_daily_budget=100,
        eodhd_reserve=10,
    )
    planner = DailyRefreshPlanner(UnitedStatesMarketCalendar(), policy)
    with pytest.raises(RefreshPlanningError, match="only 90") as raised:
        planner.plan(
            universe=[
                SecurityTarget(f"00000000-0000-0000-0000-{index:012d}", f"S{index}")
                for index in range(11)
            ],
            cursors={},
            provider_code="eodhd",
            universe_version="fixture-v1",
            as_of=NOW,
        )
    assert raised.value.code == "EODHD_BUDGET_EXCEEDED"


class FixtureProvider:
    descriptor = DESCRIPTOR

    def __init__(self, latest: date = date(2026, 7, 28), failures: int = 0) -> None:
        self.latest = latest
        self.failures = failures
        self.calls = 0

    def fetch_daily_prices(self, symbol: str, start_date: date, end_date: date):
        self.calls += 1
        if self.calls <= self.failures:
            raise MarketDataProviderError("temporary", "RATE_LIMITED")
        bar = DailyPriceBar(
            self.latest,
            Decimal("10"),
            Decimal("11"),
            Decimal("9"),
            Decimal("10.5"),
            100,
            Decimal("10.25"),
        )
        return DailyPriceSeries(
            security=SecurityMetadata(
                symbol, symbol, "NASDAQ", "COMMON_STOCK", "USD", "America/New_York"
            ),
            provider_descriptor=self.descriptor,
            requested_symbol=symbol,
            provider_symbol=symbol,
            adjustment_mode=AdjustmentMode.TOTAL_RETURN_ADJUSTED,
            bars=(bar,),
            source_reference=f"fixture:{symbol}",
            available_at=NOW,
            retrieved_at=NOW,
        )

    def fetch_corporate_actions(self, symbol: str, start_date: date, end_date: date):
        return CorporateActionSeries(
            provider_descriptor=self.descriptor,
            requested_symbol=symbol,
            provider_symbol=symbol,
            actions=(),
            source_reference=f"fixture:actions:{symbol}",
            available_at=NOW,
        )


class MemoryStore:
    def __init__(self, locked: bool = True) -> None:
        self.locked = locked
        self.results = []
        self.final = None

    @contextmanager
    def single_run_lock(self):
        yield self.locked

    def start_run(self, plan):
        return "run-1"

    def pending_items(self, run_id, plan):
        return plan.items

    def start_item(self, run_id, item):
        pass

    def record_result(self, run_id, result):
        self.results.append(result)

    def fail_attempt(self, run_id, item, error_code, retry_at):
        pass

    def complete_run(self, result):
        self.final = result

    def load_cursors(self, provider_code):
        return {}

    def weighted_calls_used(self, provider_code, on_date):
        return 0


class MemoryWriter:
    def write_prices(self, series, mode):
        return WriteResult(
            len(series.bars),
            series.rejected_bar_count,
            UUID("00000000-0000-0000-0000-000000000010"),
            datetime(2026, 7, 28, tzinfo=UTC),
            series.available_at,
            series.retrieved_at,
            series.source_reference,
            series.content_hash,
            series.provider_descriptor.provider_schema_version,
            series.provider_descriptor.parser_version,
        )

    def write_actions(self, series):
        return WriteResult(
            len(series.actions),
            0,
            UUID("00000000-0000-0000-0000-000000000011"),
            datetime(2026, 7, 28, tzinfo=UTC),
            series.available_at,
            series.available_at,
            series.source_reference,
            "sha256:fixture-actions",
            series.provider_descriptor.provider_schema_version,
            series.provider_descriptor.parser_version,
        )


def _plan(provider_code: str = "yfinance"):
    return DailyRefreshPlanner(UnitedStatesMarketCalendar()).plan(
        universe=[TARGET],
        cursors={},
        provider_code=provider_code,
        universe_version="fixture-v1",
        as_of=NOW,
    )


def test_runner_retries_and_records_explicit_current_outcome() -> None:
    provider = FixtureProvider(failures=1)
    store = MemoryStore()
    runner = DailyRefreshRunner(
        price_provider=provider,
        action_provider=provider,
        writer=MemoryWriter(),
        store=store,
        calendar=UnitedStatesMarketCalendar(),
        sleeper=lambda _: None,
        now=lambda: NOW,
    )
    result = runner.run(_plan())
    assert result.outcome == RefreshOutcome.SUCCEEDED
    assert provider.calls == 2
    assert all(item.freshness_state == FreshnessState.CURRENT for item in result.results)
    assert store.final == result


def test_runner_reports_partial_for_late_prices() -> None:
    provider = FixtureProvider(latest=date(2026, 7, 27))
    runner = DailyRefreshRunner(
        price_provider=provider,
        action_provider=provider,
        writer=MemoryWriter(),
        store=MemoryStore(),
        calendar=UnitedStatesMarketCalendar(),
        sleeper=lambda _: None,
        now=lambda: NOW,
    )
    result = runner.run(_plan())
    assert result.outcome == RefreshOutcome.PARTIAL
    assert sum(item.freshness_state == FreshnessState.LATE for item in result.results) == 2


def test_runner_skips_when_cross_process_lock_is_held() -> None:
    provider = FixtureProvider()
    runner = DailyRefreshRunner(
        price_provider=provider,
        action_provider=provider,
        writer=MemoryWriter(),
        store=MemoryStore(locked=False),
        calendar=UnitedStatesMarketCalendar(),
        now=lambda: NOW,
    )
    result = runner.run(_plan())
    assert result.outcome == RefreshOutcome.SKIPPED_LOCKED
    assert provider.calls == 0


def test_scheduler_loads_durable_state_before_planning() -> None:
    provider = FixtureProvider()
    store = MemoryStore()
    runner = DailyRefreshRunner(
        price_provider=provider,
        action_provider=provider,
        writer=MemoryWriter(),
        store=store,
        calendar=UnitedStatesMarketCalendar(),
        now=lambda: NOW,
    )
    scheduler = DailyRefreshScheduler(
        provider_code="yfinance",
        universe_version="fixture-v1",
        universe_loader=lambda: [TARGET],
        planner=DailyRefreshPlanner(UnitedStatesMarketCalendar()),
        runner=runner,
        store=store,
        now=lambda: NOW,
    )
    result = scheduler.invoke()
    assert result.outcome == RefreshOutcome.SUCCEEDED
    assert result.planned_items == 2
