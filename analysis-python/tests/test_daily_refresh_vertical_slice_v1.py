import json
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest

from equity_analysis.daily_refresh.calendar import UnitedStatesMarketCalendar
from equity_analysis.daily_refresh.cli import _preflight
from equity_analysis.daily_refresh.models import (
    Dataset,
    DatasetCursor,
    RefreshPolicy,
    SecurityTarget,
)
from equity_analysis.daily_refresh.persistence import (
    WriteResult,
    _refresh_run_idempotency_key,
)
from equity_analysis.daily_refresh.planner import DailyRefreshPlanner, RefreshPlanningError
from equity_analysis.daily_refresh.runner import DailyRefreshRunner
from equity_analysis.daily_refresh.universe import load_closed_test_universe
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

ANALYSIS_ROOT = Path(__file__).resolve().parents[1]
UNIVERSE_PATH = (
    ANALYSIS_ROOT
    / "resources"
    / "universes"
    / "market-intelligence-closed-test-us-v1.json"
)
TARGET = SecurityTarget("00000000-0000-0000-0000-000000000001", "AAPL")
NOW = datetime(2026, 7, 28, 23, tzinfo=UTC)
DESCRIPTOR = ProviderDescriptor(
    code="yfinance",
    name="Fixture",
    provider_schema_version="fixture-v1",
    parser_version="fixture-v1",
    capabilities=frozenset({ProviderCapability.DAILY_PRICES}),
    use_classification=ProviderUseClassification.DEVELOPMENT_FALLBACK,
)


def test_closed_test_universe_freezes_all_66_roles() -> None:
    universe = load_closed_test_universe(UNIVERSE_PATH)
    assert universe.version == "market-intelligence-closed-test-us-v1.0.0"
    assert {role: len(items) for role, items in universe.members_by_role.items()} == {
        "PRIMARY": 48,
        "RESERVE": 7,
        "REFERENCE_ONLY": 2,
        "EXCLUDED": 9,
    }
    assert universe.members_by_role["REFERENCE_ONLY"] == ("SPY", "XLK")
    assert universe.excluded_reasons["NBN"] == "FINANCIAL"
    assert len(universe.refreshable_symbols) == 57
    assert set(("AAPL", "MSFT", "AMZN", "GE", "NBN", "SPY")) <= set(
        universe.symbols
    )
    raw = json.loads(UNIVERSE_PATH.read_text(encoding="utf-8"))
    assert raw["sourceFixtureSha256"] == (
        "1C53948F5CD0D1E74F870DEF6B34A619DE1845B9DA2B3170B4712427DE43A033"
    )


def test_completed_session_respects_regular_and_early_close_grace() -> None:
    calendar = UnitedStatesMarketCalendar()
    assert calendar.session_close(date(2026, 7, 2)).hour == 17
    assert calendar.latest_completed_session(
        datetime(2026, 7, 2, 18, 29, tzinfo=UTC)
    ) == date(2026, 7, 1)
    assert calendar.latest_completed_session(
        datetime(2026, 7, 2, 18, 30, tzinfo=UTC)
    ) == date(2026, 7, 2)
    assert calendar.session_close(date(2026, 11, 27)).hour == 18
    assert calendar.session_close(date(2026, 12, 24)).hour == 18
    assert calendar.latest_completed_session(
        datetime(2026, 7, 28, 21, 29, tzinfo=UTC)
    ) == date(2026, 7, 27)
    assert calendar.latest_completed_session(
        datetime(2026, 7, 28, 21, 30, tzinfo=UTC)
    ) == date(2026, 7, 28)


def test_initial_price_plan_is_260_sessions_and_one_physical_fetch() -> None:
    plan = DailyRefreshPlanner(UnitedStatesMarketCalendar()).plan(
        universe=(TARGET,),
        cursors={},
        provider_code="yfinance",
        universe_version="fixture-v1",
        as_of=NOW,
        datasets=(Dataset.DAILY_PRICE,),
    )
    assert len(plan.items) == 2
    assert plan.items[0].start_date == UnitedStatesMarketCalendar().shift_sessions(
        date(2026, 7, 28), -259
    )
    assert [item.estimated_weighted_calls for item in plan.items] == [2, 0]
    assert plan.items[0].request_key == plan.items[1].request_key


def test_refresh_run_identity_is_bound_to_exact_plan_configuration() -> None:
    plan = DailyRefreshPlanner(UnitedStatesMarketCalendar()).plan(
        universe=(TARGET,),
        cursors={},
        provider_code="yfinance",
        universe_version="fixture-v1",
        as_of=NOW,
        datasets=(Dataset.DAILY_PRICE,),
    )
    same = replace(plan)
    expanded_scope = replace(plan, configuration_hash="f" * 64)

    assert _refresh_run_idempotency_key(plan) == _refresh_run_idempotency_key(same)
    assert _refresh_run_idempotency_key(plan) != _refresh_run_idempotency_key(
        expanded_scope
    )


def test_price_preflight_counts_unique_shared_requests() -> None:
    canary_symbols = ("AAPL", "MSFT", "AMZN", "GE", "NBN", "SPY")
    canary = DailyRefreshPlanner(
        UnitedStatesMarketCalendar(),
        RefreshPolicy(max_attempts=1),
    ).plan(
        universe=tuple(
            SecurityTarget(
                f"00000000-0000-0000-0000-{index:012d}",
                symbol,
            )
            for index, symbol in enumerate(canary_symbols, start=1)
        ),
        cursors={},
        provider_code="yfinance",
        universe_version="fixture-v1",
        as_of=NOW,
        datasets=(Dataset.DAILY_PRICE,),
    )
    assert _preflight(canary, "prices")["physicalRequestHardCeiling"] == 6
    full = DailyRefreshPlanner(
        UnitedStatesMarketCalendar(),
        RefreshPolicy(max_attempts=2),
    ).plan(
        universe=tuple(
            SecurityTarget(
                f"00000000-0000-0000-0000-{index:012d}",
                f"S{index}",
            )
            for index in range(57)
        ),
        cursors={},
        provider_code="yfinance",
        universe_version="fixture-v1",
        as_of=NOW,
        datasets=(Dataset.DAILY_PRICE,),
    )
    assert _preflight(full, "prices")["physicalRequestHardCeiling"] == 114


def test_eodhd_plans_have_exact_hard_weights_and_freshness_filter() -> None:
    planner = DailyRefreshPlanner(UnitedStatesMarketCalendar())
    action_plan = planner.plan(
        universe=(TARGET,),
        cursors={},
        provider_code="eodhd",
        universe_version="fixture-v1",
        as_of=NOW,
        datasets=(Dataset.CORPORATE_ACTION,),
    )
    assert action_plan.estimated_weighted_calls == 4
    recent = DatasetCursor(
        security_id=TARGET.security_id,
        dataset=Dataset.FUNDAMENTALS,
        provider_code="eodhd",
        adjustment_mode=None,
        last_successful_update=datetime(2026, 7, 1, tzinfo=UTC),
    )
    current_plan = planner.plan(
        universe=(TARGET,),
        cursors={(TARGET.security_id, Dataset.FUNDAMENTALS, None): recent},
        provider_code="eodhd",
        universe_version="fixture-v1",
        as_of=NOW,
        datasets=(Dataset.FUNDAMENTALS,),
    )
    assert current_plan.items == ()
    stale = DatasetCursor(
        security_id=TARGET.security_id,
        dataset=Dataset.FUNDAMENTALS,
        provider_code="eodhd",
        adjustment_mode=None,
        last_successful_update=datetime(2026, 4, 1, tzinfo=UTC),
    )
    stale_plan = planner.plan(
        universe=(TARGET,),
        cursors={(TARGET.security_id, Dataset.FUNDAMENTALS, None): stale},
        provider_code="eodhd",
        universe_version="fixture-v1",
        as_of=NOW,
        datasets=(Dataset.FUNDAMENTALS,),
    )
    assert stale_plan.estimated_weighted_calls == 20


def test_planner_rejects_unapproved_provider_dataset_pair() -> None:
    planner = DailyRefreshPlanner(UnitedStatesMarketCalendar())
    with pytest.raises(RefreshPlanningError) as raised:
        planner.plan(
            universe=(TARGET,),
            cursors={},
            provider_code="yfinance",
            universe_version="fixture-v1",
            as_of=NOW,
            datasets=(Dataset.FUNDAMENTALS,),
        )
    assert raised.value.code == "DATASET_PROVIDER_NOT_APPROVED"


class _OneFetchProvider:
    descriptor = DESCRIPTOR

    def __init__(self) -> None:
        self.calls = 0

    def fetch_daily_prices(self, symbol: str, start_date: date, end_date: date):
        self.calls += 1
        return DailyPriceSeries(
            security=SecurityMetadata(
                symbol, symbol, "NASDAQ", "COMMON_STOCK", "USD", "America/New_York"
            ),
            provider_descriptor=self.descriptor,
            requested_symbol=symbol,
            provider_symbol=symbol,
            adjustment_mode=AdjustmentMode.TOTAL_RETURN_ADJUSTED,
            bars=(
                DailyPriceBar(
                    end_date,
                    Decimal("10"),
                    Decimal("11"),
                    Decimal("9"),
                    Decimal("10"),
                    100,
                    Decimal("9.5"),
                ),
            ),
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
            source_reference=f"fixture:{symbol}:actions",
            available_at=NOW,
        )


class _Store:
    def __init__(self) -> None:
        self.events = []

    @contextmanager
    def single_run_lock(self):
        yield True

    def start_run(self, plan):
        return "run"

    def pending_items(self, run_id, plan):
        return plan.items

    def start_item(self, run_id, item):
        return None

    def record_result(self, run_id, result):
        return None

    def fail_attempt(self, run_id, item, error_code, retry_at):
        return None

    def complete_run(self, result):
        return None

    def request_intent(self, run_id, item, attempt, **detail):
        self.events.append(("INTENT", item.request_key, attempt, detail))

    def request_completed(self, run_id, item, attempt, **detail):
        self.events.append(("COMPLETED", item.request_key, attempt, detail))

    def request_failed(self, run_id, item, attempt, **detail):
        self.events.append(("FAILED", item.request_key, attempt, detail))


class _Writer:
    def write_prices(self, series, mode):
        return WriteResult(
            rows_written=1,
            rows_rejected=0,
            ingestion_batch_id=UUID("00000000-0000-0000-0000-000000000010"),
            effective_at=NOW,
            available_at=NOW,
            ingested_at=NOW,
            source_reference=series.source_reference,
            content_hash=series.content_hash,
            provider_schema_version="fixture-v1",
            parser_version="fixture-v1",
        )

    def write_actions(self, series):
        raise AssertionError("not used")

    def write_fundamentals(self, security_id, observations):
        raise AssertionError("not used")


def test_price_runner_fetches_once_and_journals_only_physical_request() -> None:
    provider = _OneFetchProvider()
    store = _Store()
    plan = DailyRefreshPlanner(UnitedStatesMarketCalendar()).plan(
        universe=(TARGET,),
        cursors={},
        provider_code="yfinance",
        universe_version="fixture-v1",
        as_of=NOW,
        datasets=(Dataset.DAILY_PRICE,),
    )
    result = DailyRefreshRunner(
        price_provider=provider,
        action_provider=provider,
        writer=_Writer(),
        store=store,
        calendar=UnitedStatesMarketCalendar(),
        policy=RefreshPolicy(),
        now=lambda: NOW,
    ).run(plan)
    assert provider.calls == 1
    assert result.weighted_calls_used == 1
    assert sum(item.physical_requests for item in result.results) == 1
    assert [event[0] for event in store.events] == ["INTENT", "COMPLETED"]


def test_price_runner_shares_terminal_failure_across_adjustment_modes() -> None:
    class FailingProvider(_OneFetchProvider):
        def fetch_daily_prices(self, symbol: str, start_date: date, end_date: date):
            self.calls += 1
            raise MarketDataProviderError("fixture failure", "YFINANCE_REQUEST_FAILED")

    provider = FailingProvider()
    store = _Store()
    plan = DailyRefreshPlanner(UnitedStatesMarketCalendar()).plan(
        universe=(TARGET,),
        cursors={},
        provider_code="yfinance",
        universe_version="fixture-v1",
        as_of=NOW,
        datasets=(Dataset.DAILY_PRICE,),
    )

    result = DailyRefreshRunner(
        price_provider=provider,
        action_provider=provider,
        writer=_Writer(),
        store=store,
        calendar=UnitedStatesMarketCalendar(),
        policy=RefreshPolicy(max_attempts=1),
        now=lambda: NOW,
    ).run(plan)

    assert provider.calls == 1
    assert result.failed_items == 2
    assert sum(item.physical_requests for item in result.results) == 1
    assert sum(item.weighted_calls_used for item in result.results) == 1
    assert [event[0] for event in store.events] == ["INTENT", "FAILED"]
