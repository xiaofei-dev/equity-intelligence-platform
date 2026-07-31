import json
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from equity_analysis.historical_validation.yahoo_price_cache_v1 import (
    ADJUSTMENT_POLICY_VERSION,
    CANARY_SYMBOLS,
    EXPECTED_SECURITY_COUNT,
    HISTORICAL_START_DATE,
    HistoricalYahooPriceCacheError,
    build_historical_yahoo_price_cache_plan,
    build_historical_yahoo_price_preflight,
    execute_historical_yahoo_price_cache,
    normalize_historical_yahoo_series,
)
from equity_analysis.market_data.models import (
    AdjustmentMode,
    DailyPriceBar,
    DailyPriceSeries,
    SecurityMetadata,
)
from equity_analysis.market_data.provider import MarketDataProviderError
from equity_analysis.market_data.yfinance_provider import YFINANCE_DESCRIPTOR
from equity_analysis.provider_validation.execution_safety import (
    ExecutionLease,
    SymbolExecutionJournal,
)

END_DATE = date(2026, 7, 28)
AS_OF = datetime(2026, 7, 29, 12, tzinfo=UTC)


def _plan(run_id: str = "20260729T120000Z-test"):
    return build_historical_yahoo_price_cache_plan(
        end_date=END_DATE,
        as_of=AS_OF,
        run_id=run_id,
    )


def _series(
    symbol: str,
    *,
    adjusted_close: Decimal | None = Decimal("5"),
) -> DailyPriceSeries:
    return DailyPriceSeries(
        security=SecurityMetadata(
            symbol=symbol,
            name=symbol,
            exchange="NASDAQ",
            instrument_type="COMMON_STOCK",
            currency="USD",
            exchange_timezone="America/New_York",
        ),
        provider_descriptor=YFINANCE_DESCRIPTOR,
        requested_symbol=symbol,
        provider_symbol=symbol,
        adjustment_mode=AdjustmentMode.TOTAL_RETURN_ADJUSTED,
        bars=(
            DailyPriceBar(
                trading_date=date(2014, 1, 2),
                open_price=Decimal("10"),
                high_price=Decimal("12"),
                low_price=Decimal("9"),
                close_price=Decimal("10"),
                adjusted_close=adjusted_close,
                volume=100,
            ),
            DailyPriceBar(
                trading_date=END_DATE,
                open_price=Decimal("20"),
                high_price=Decimal("24"),
                low_price=Decimal("18"),
                close_price=Decimal("20"),
                adjusted_close=Decimal("10"),
                volume=200,
            ),
        ),
        source_reference=f"yfinance:download:{symbol}",
        available_at=AS_OF,
        retrieved_at=AS_OF,
    )


def _all_keys(value):
    if isinstance(value, dict):
        return set(value) | {
            key
            for item in value.values()
            for key in _all_keys(item)
        }
    if isinstance(value, list):
        return {key for item in value for key in _all_keys(item)}
    return set()


def test_plan_freezes_55_companies_plus_spy_and_completed_range() -> None:
    first = _plan()
    second = _plan()

    assert first == second
    assert len(first.symbols) == EXPECTED_SECURITY_COUNT
    assert len(set(first.symbols)) == EXPECTED_SECURITY_COUNT
    assert first.symbols[-1] == "SPY"
    assert "XLK" not in first.symbols
    assert first.start_date == HISTORICAL_START_DATE
    assert first.end_date == END_DATE
    assert len(first.universe_file_sha256) == 64
    assert len(first.ordered_symbol_set_hash) == 64
    assert len(first.plan_hash) == 64


@pytest.mark.parametrize(
    ("end_date", "match"),
    (
        (date(2013, 12, 31), "precedes"),
        (date(2026, 7, 26), "market session"),
        (date(2026, 7, 29), "not a completed"),
    ),
)
def test_plan_rejects_unapproved_end_boundaries(end_date, match) -> None:
    with pytest.raises(ValueError, match=match):
        build_historical_yahoo_price_cache_plan(
            end_date=end_date,
            as_of=AS_OF,
            run_id="invalid",
        )


def test_preflight_is_git_safe_and_contains_only_bounded_metadata() -> None:
    preflight = build_historical_yahoo_price_preflight(_plan())

    assert preflight["securityCount"] == EXPECTED_SECURITY_COUNT
    assert preflight["expectedWrapperCalls"] == EXPECTED_SECURITY_COUNT
    assert preflight["wrapperCallHardCeiling"] == EXPECTED_SECURITY_COUNT
    assert preflight["providerRetryLimit"] == 0
    assert preflight["canarySymbols"] == list(CANARY_SYMBOLS)
    assert preflight["canarySymbolCount"] == 6
    assert preflight["networkRequestsExecuted"] is False
    assert preflight["pricesIncluded"] is False
    assert len(preflight["artifactContentHash"]) == 64
    assert not {
        "bars",
        "open",
        "high",
        "low",
        "close",
        "adjustedClose",
        "volume",
        "adjustmentFactor",
    } & _all_keys(preflight)


def test_normalization_scales_ohlc_by_adjusted_close_ratio() -> None:
    payload = normalize_historical_yahoo_series(
        _series("AAPL"),
        expected_symbol="AAPL",
        start_date=HISTORICAL_START_DATE,
        end_date=END_DATE,
    )

    first = payload["bars"][0]
    assert first["raw"] == {
        "open": "10",
        "high": "12",
        "low": "9",
        "close": "10",
        "adjustedClose": "5",
    }
    assert first["tactical"] == {
        "open": "5.0",
        "high": "6.0",
        "low": "4.5",
        "close": "5",
        "sessionComplete": True,
    }
    assert first["adjustmentFactor"] == "0.5"
    assert payload["adjustment"]["policyVersion"] == ADJUSTMENT_POLICY_VERSION
    assert payload["adjustment"]["sourceAutoAdjust"] is False
    assert payload["adjustment"]["factorFormula"] == "AdjClose/Close"
    assert payload["adjustment"]["volumeAdjustment"] == "UNCHANGED"
    assert len(payload["contentHash"]) == 64


def test_normalization_requires_adjusted_close_for_every_bar() -> None:
    with pytest.raises(HistoricalYahooPriceCacheError, match="ADJUSTED_CLOSE_REQUIRED"):
        normalize_historical_yahoo_series(
            _series("AAPL", adjusted_close=None),
            expected_symbol="AAPL",
            start_date=HISTORICAL_START_DATE,
            end_date=END_DATE,
        )


def test_full_bounded_run_fetches_each_symbol_once_and_writes_safe_manifest(
    tmp_path: Path,
) -> None:
    plan = _plan()
    calls = []

    def fetcher(symbol, start_date, end_date):
        calls.append((symbol, start_date, end_date))
        return _series(symbol)

    result = execute_historical_yahoo_price_cache(
        plan,
        fetcher=fetcher,
        storage_root=tmp_path / "storage",
        output_directory=tmp_path / "output",
    )

    assert result.status == "COMPLETE"
    assert result.physical_wrapper_calls == EXPECTED_SECURITY_COUNT
    assert [item[0] for item in calls] == list(plan.symbols)
    assert all(
        start == HISTORICAL_START_DATE and end == END_DATE
        for _, start, end in calls
    )
    assert result.manifest["completedSecurityCount"] == EXPECTED_SECURITY_COUNT
    assert result.manifest["physicalWrapperCalls"] == EXPECTED_SECURITY_COUNT
    assert result.manifest["newPhysicalWrapperCalls"] == EXPECTED_SECURITY_COUNT
    assert result.manifest["failedSecurityCount"] == 0
    assert result.manifest["pricesIncluded"] is False
    assert not {
        "bars",
        "open",
        "high",
        "low",
        "close",
        "adjustedClose",
        "volume",
        "adjustmentFactor",
    } & _all_keys(result.manifest)

    receipt = next(
        item for item in result.manifest["records"] if item["symbol"] == "AAPL"
    )
    controlled = json.loads(
        (
            tmp_path / "storage" / receipt["payloadStorageReference"]
        ).read_text(encoding="utf-8")
    )
    assert controlled["bars"][0]["tactical"]["close"] == "5"
    assert controlled["bars"][0]["raw"]["close"] == "10"
    assert not (tmp_path / "storage" / ".historical-yahoo-price-cache.lock").exists()


def test_canary_then_same_run_resume_fetches_exactly_6_then_remaining_50(
    tmp_path: Path,
) -> None:
    plan = _plan()
    canary_calls = []

    canary = execute_historical_yahoo_price_cache(
        plan,
        fetcher=lambda symbol, _start, _end: (
            canary_calls.append(symbol) or _series(symbol)
        ),
        storage_root=tmp_path / "storage",
        output_directory=tmp_path / "output",
        canary=True,
    )

    assert canary.status == "PARTIAL_AWAITING_RESUME"
    assert canary_calls == list(CANARY_SYMBOLS)
    assert canary.physical_wrapper_calls == 6
    assert canary.manifest["completedSecurityCount"] == 6
    assert canary.manifest["failedSecurityCount"] == 0
    assert canary.manifest["unrunSecurityCount"] == 50
    assert canary.manifest["executionNewSymbolCeiling"] == 6
    assert "progress-006-" in canary.manifest_path.name
    assert not (
        tmp_path
        / "output"
        / f"historical-yahoo-price-cache-{plan.run_id}-manifest.json"
    ).exists()

    remaining_calls = []
    resumed = execute_historical_yahoo_price_cache(
        plan,
        fetcher=lambda symbol, _start, _end: (
            remaining_calls.append(symbol) or _series(symbol)
        ),
        storage_root=tmp_path / "storage",
        output_directory=tmp_path / "output",
        maximum_new_symbols=50,
    )

    assert resumed.status == "COMPLETE"
    assert remaining_calls == [
        symbol for symbol in plan.symbols if symbol not in CANARY_SYMBOLS
    ]
    assert resumed.physical_wrapper_calls == 50
    assert resumed.manifest["completedSecurityCount"] == EXPECTED_SECURITY_COUNT
    assert resumed.manifest["replayedSecurityCount"] == 6
    assert resumed.manifest["newPhysicalWrapperCalls"] == 50
    assert resumed.manifest["physicalWrapperCalls"] == EXPECTED_SECURITY_COUNT
    assert resumed.manifest["unrunSecurityCount"] == 0
    assert resumed.manifest["executionNewSymbolCeiling"] == 50


def test_resume_revalidates_completed_payloads_without_fetching_again(
    tmp_path: Path,
) -> None:
    plan = _plan()
    first = execute_historical_yahoo_price_cache(
        plan,
        fetcher=lambda symbol, _start, _end: _series(symbol),
        storage_root=tmp_path / "storage",
        output_directory=tmp_path / "output",
    )
    first.manifest_path.unlink()
    calls = []

    resumed = execute_historical_yahoo_price_cache(
        plan,
        fetcher=lambda *_args: calls.append("unexpected"),
        storage_root=tmp_path / "storage",
        output_directory=tmp_path / "output",
    )

    assert resumed.status == "COMPLETE"
    assert resumed.physical_wrapper_calls == 0
    assert resumed.manifest["physicalWrapperCalls"] == EXPECTED_SECURITY_COUNT
    assert resumed.manifest["newPhysicalWrapperCalls"] == 0
    assert resumed.manifest["replayedSecurityCount"] == EXPECTED_SECURITY_COUNT
    assert calls == []


def test_unknown_intent_stops_before_any_fetch(tmp_path: Path) -> None:
    plan = _plan()
    storage = tmp_path / "storage"
    journal = SymbolExecutionJournal(storage / "journals", plan.run_id)
    journal.append(
        plan.symbols[-1],
        "INTENT",
        {
            "requestIdentity": "dangling",
            "startDate": plan.start_date.isoformat(),
            "endDate": plan.end_date.isoformat(),
        },
    )
    calls = []

    with pytest.raises(HistoricalYahooPriceCacheError, match="UNKNOWN_JOURNAL_STATE"):
        execute_historical_yahoo_price_cache(
            plan,
            fetcher=lambda *_args: calls.append("unexpected"),
            storage_root=storage,
            output_directory=tmp_path / "output",
        )

    assert calls == []
    assert not (storage / ".historical-yahoo-price-cache.lock").exists()


def test_provider_failure_is_journaled_once_and_never_retried(tmp_path: Path) -> None:
    plan = _plan()
    calls = []

    def failing(symbol, _start, _end):
        calls.append(symbol)
        raise MarketDataProviderError("sanitized", "EMPTY_RESULT")

    result = execute_historical_yahoo_price_cache(
        plan,
        fetcher=failing,
        storage_root=tmp_path / "storage",
        output_directory=tmp_path / "output",
    )

    assert result.status == "FAILED"
    assert calls == [plan.symbols[0]]
    assert result.manifest["physicalWrapperCalls"] == 1
    assert result.manifest["newPhysicalWrapperCalls"] == 1
    assert result.manifest["providerRetryLimit"] == 0
    assert result.manifest["failures"] == [
        {"symbol": plan.symbols[0], "reasonCode": "EMPTY_RESULT"}
    ]
    events = sorted(
        (
            tmp_path
            / "storage"
            / "journals"
            / plan.run_id
            / plan.symbols[0]
        ).glob("[0-9]*-*.json")
    )
    assert [
        json.loads(path.read_text(encoding="utf-8"))["state"] for path in events
    ] == ["INTENT", "FAILED"]

    resumed_calls = []
    resumed = execute_historical_yahoo_price_cache(
        plan,
        fetcher=lambda *_args: resumed_calls.append("unexpected"),
        storage_root=tmp_path / "storage",
        output_directory=tmp_path / "output",
    )
    assert resumed.status == "FAILED"
    assert resumed.physical_wrapper_calls == 0
    assert resumed_calls == []


def test_active_execution_lease_blocks_before_fetch(tmp_path: Path) -> None:
    plan = _plan()
    storage = tmp_path / "storage"
    calls = []

    with ExecutionLease(
        storage / ".historical-yahoo-price-cache.lock",
        "other-run",
    ):
        with pytest.raises(RuntimeError, match="EXECUTION_LOCK_ACTIVE"):
            execute_historical_yahoo_price_cache(
                plan,
                fetcher=lambda *_args: calls.append("unexpected"),
                storage_root=storage,
                output_directory=tmp_path / "output",
            )

    assert calls == []
