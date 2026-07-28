import json
from datetime import date, datetime
from io import BytesIO
from urllib.error import HTTPError
from urllib.request import Request

import pytest

from equity_analysis.config import Settings
from equity_analysis.market_data.eodhd import EodhdProvider
from equity_analysis.market_data.factory import (
    ProviderConfigurationError,
    create_market_data_provider,
)
from equity_analysis.market_data.models import AdjustmentMode
from equity_analysis.market_data.provider import MarketDataProviderError
from equity_analysis.market_data.yfinance_provider import YFinanceProvider


class Response(BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


class FakeFrame:
    def __init__(self, columns, rows):
        self.columns = columns
        self._rows = rows
        self.empty = not rows

    def iterrows(self):
        return iter(self._rows)


class FakeTicker:
    fast_info = {"currency": "USD", "exchange": "NASDAQ"}
    info = {
        "longName": "Apple Inc.",
        "exchange": "NASDAQ",
        "quoteType": "EQUITY",
        "currency": "USD",
        "exchangeTimezoneName": "America/New_York",
    }
    actions = FakeFrame(
        ("Dividends", "Stock Splits"),
        (
            (
                datetime(2026, 5, 11),
                {"Dividends": 0.26, "Stock Splits": 0.0},
            ),
            (
                datetime(2020, 8, 31),
                {"Dividends": 0.0, "Stock Splits": 4.0},
            ),
        ),
    )


def _settings(provider: str, twelve_key: str = "", eodhd_key: str = "") -> Settings:
    return Settings(
        market_data_provider=provider,
        twelve_data_api_key=twelve_key,
        eodhd_api_key=eodhd_key,
        analytics_database_url="postgresql://test",
    )


def test_adjustment_mode_maps_legacy_storage_values() -> None:
    assert AdjustmentMode.from_storage("none") == AdjustmentMode.UNADJUSTED
    assert AdjustmentMode.from_storage("splits") == AdjustmentMode.SPLIT_ADJUSTED
    assert AdjustmentMode.from_storage("all") == AdjustmentMode.TOTAL_RETURN_ADJUSTED


def test_provider_factory_requires_keys_and_rejects_unknown_provider() -> None:
    with pytest.raises(ProviderConfigurationError) as missing:
        create_market_data_provider(_settings("eodhd"))
    assert missing.value.code == "MARKET_DATA_NOT_CONFIGURED"

    with pytest.raises(ProviderConfigurationError) as unsupported:
        create_market_data_provider(_settings("unknown"))
    assert unsupported.value.code == "MARKET_DATA_PROVIDER_UNSUPPORTED"


def test_yfinance_normalizes_unadjusted_and_adjusted_prices_and_actions() -> None:
    frame = FakeFrame(
        ("Open", "High", "Low", "Close", "Adj Close", "Volume"),
        (
            (
                datetime(2026, 7, 23),
                {
                    "Open": 210.0,
                    "High": 214.5,
                    "Low": 209.25,
                    "Close": 213.75,
                    "Adj Close": 212.5,
                    "Volume": 50_000_000,
                },
            ),
        ),
    )
    calls = []

    def downloader(*args, **kwargs):
        calls.append((args, kwargs))
        return frame

    provider = YFinanceProvider(
        downloader=downloader,
        ticker_factory=lambda _symbol: FakeTicker(),
    )
    series = provider.fetch_daily_prices(
        "aapl", date(2026, 7, 23), date(2026, 7, 23)
    )
    actions = provider.fetch_corporate_actions(
        "AAPL", date(2020, 1, 1), date(2026, 7, 25)
    )

    assert calls[0][1]["auto_adjust"] is False
    assert series.adjustment_mode == AdjustmentMode.TOTAL_RETURN_ADJUSTED
    assert str(series.bars[0].close_price) == "213.75"
    assert str(series.bars[0].adjusted_close) == "212.5"
    assert {action.action_type for action in actions.actions} == {"DIVIDEND", "SPLIT"}
    assert series.provider_descriptor.use_classification == "DEVELOPMENT_FALLBACK"


def test_yfinance_rejects_missing_rows_without_converting_them_to_zero() -> None:
    frame = FakeFrame(
        ("Open", "High", "Low", "Close", "Adj Close", "Volume"),
        (
            (
                datetime(2026, 7, 23),
                {
                    "Open": 210.0,
                    "High": 214.5,
                    "Low": 209.25,
                    "Close": float("nan"),
                    "Adj Close": 212.5,
                    "Volume": 50_000_000,
                },
            ),
        ),
    )
    provider = YFinanceProvider(
        downloader=lambda *args, **kwargs: frame,
        ticker_factory=lambda _symbol: FakeTicker(),
    )
    with pytest.raises(MarketDataProviderError) as error:
        provider.fetch_daily_prices("AAPL", date(2026, 7, 23), date(2026, 7, 23))
    assert error.value.code == "EMPTY_RESULT"


def test_yfinance_preserves_valid_rows_and_counts_rejected_rows() -> None:
    columns = ("Open", "High", "Low", "Close", "Adj Close", "Volume")
    frame = FakeFrame(
        columns,
        (
            (
                datetime(2026, 7, 22),
                {
                    "Open": 210.0,
                    "High": 214.5,
                    "Low": 209.25,
                    "Close": 213.75,
                    "Adj Close": 212.5,
                    "Volume": 50_000_000,
                },
            ),
            (
                datetime(2026, 7, 23),
                {
                    "Open": 211.0,
                    "High": 215.0,
                    "Low": 210.0,
                    "Close": float("nan"),
                    "Adj Close": float("nan"),
                    "Volume": 40_000_000,
                },
            ),
        ),
    )
    provider = YFinanceProvider(
        downloader=lambda *args, **kwargs: frame,
        ticker_factory=lambda _symbol: FakeTicker(),
    )

    series = provider.fetch_daily_prices(
        "AAPL", date(2026, 7, 22), date(2026, 7, 23)
    )

    assert len(series.bars) == 1
    assert series.rejected_bar_count == 1


def test_eodhd_maps_symbol_and_redacts_key_from_lineage() -> None:
    captured: list[Request] = []

    def opener(request: Request, timeout: float):
        captured.append(request)
        assert timeout == 20.0
        endpoint = request.full_url.split("/api/", 1)[1].split("?", 1)[0]
        payload = (
            [
                {
                    "date": "2026-07-23",
                    "open": 210,
                    "high": 214.5,
                    "low": 209.25,
                    "close": 213.75,
                    "adjusted_close": 212.5,
                    "volume": 50_000_000,
                }
            ]
            if endpoint.startswith("eod/")
            else {
                "General": {
                    "Name": "Apple Inc.",
                    "Exchange": "NASDAQ",
                    "Type": "Common Stock",
                    "CurrencyCode": "USD",
                }
            }
        )
        return Response(json.dumps(payload).encode())

    provider = EodhdProvider(api_key="test-key", opener=opener)
    series = provider.fetch_daily_prices(
        "AAPL", date(2026, 7, 23), date(2026, 7, 23)
    )

    assert series.provider_symbol == "AAPL.US"
    assert series.source_reference == "eodhd:eod:AAPL.US"
    assert "test-key" not in series.source_reference
    assert "test-key" in captured[0].full_url


def test_eodhd_retries_rate_limit_without_leaking_key() -> None:
    attempts = 0
    sleeps = []

    def opener(request: Request, timeout: float):
        nonlocal attempts
        del request, timeout
        attempts += 1
        raise HTTPError("redacted", 429, "rate limited", {}, None)

    provider = EodhdProvider(
        api_key="test-key",
        opener=opener,
        max_retries=1,
        sleeper=sleeps.append,
    )
    with pytest.raises(MarketDataProviderError) as error:
        provider.fetch_security_metadata("AAPL")

    assert attempts == 2
    assert sleeps == [1.0]
    assert error.value.code == "RATE_LIMITED"
    assert "test-key" not in str(error.value)
    assert error.value.__cause__ is None


def test_eodhd_normalizes_dividends_and_split_ratios() -> None:
    def opener(request: Request, timeout: float):
        del timeout
        endpoint = request.full_url.split("/api/", 1)[1].split("?", 1)[0]
        payload = (
            [{"date": "2026-05-11", "value": 0.26, "currency": "USD"}]
            if endpoint.startswith("div/")
            else [{"date": "2020-08-31", "split": "4/1"}]
        )
        return Response(json.dumps(payload).encode())

    provider = EodhdProvider(api_key="test-key", opener=opener)
    actions = provider.fetch_corporate_actions(
        "AAPL", date(2020, 1, 1), date(2026, 7, 25)
    )

    dividend = next(item for item in actions.actions if item.action_type == "DIVIDEND")
    split = next(item for item in actions.actions if item.action_type == "SPLIT")
    assert str(dividend.amount) == "0.26"
    assert str(split.split_from) == "1"
    assert str(split.split_to) == "4"
