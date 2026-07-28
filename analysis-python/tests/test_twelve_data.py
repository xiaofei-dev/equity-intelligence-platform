import json
from datetime import date
from io import BytesIO
from urllib.request import Request

import pytest

from equity_analysis.market_data.provider import MarketDataProviderError
from equity_analysis.market_data.twelve_data import TwelveDataClient


class Response(BytesIO):
    pass


def test_fetch_daily_prices_normalizes_provider_response() -> None:
    captured_request: Request | None = None

    def opener(request: Request, timeout: float) -> Response:
        nonlocal captured_request
        captured_request = request
        assert timeout == 15.0
        return Response(
            json.dumps(
                {
                    "meta": {
                        "symbol": "AAPL",
                        "currency": "USD",
                        "exchange": "NASDAQ",
                        "mic_code": "XNAS",
                        "exchange_timezone": "America/New_York",
                        "type": "Common Stock",
                    },
                    "values": [
                        {
                            "datetime": "2026-07-23",
                            "open": "210.000000",
                            "high": "214.500000",
                            "low": "209.250000",
                            "close": "213.750000",
                            "volume": "50000000",
                        }
                    ],
                    "status": "ok",
                }
            ).encode()
        )

    series = TwelveDataClient(api_key="test-key", opener=opener).fetch_daily_prices(
        symbol="aapl",
        start_date=date(2026, 7, 23),
        end_date=date(2026, 7, 23),
    )

    assert captured_request is not None
    assert captured_request.get_header("Authorization") == "apikey test-key"
    assert "apikey=" not in captured_request.full_url
    assert series.security.symbol == "AAPL"
    assert series.security.name == "AAPL"
    assert series.security.instrument_type == "COMMON_STOCK"
    assert series.provider == "twelve_data"
    assert series.adjustment_mode == "SPLIT_ADJUSTED"
    assert len(series.bars) == 1
    assert series.bars[0].trading_date == date(2026, 7, 23)
    assert str(series.bars[0].close_price) == "213.750000"
    assert series.bars[0].volume == 50_000_000


def test_fetch_daily_prices_rejects_provider_errors() -> None:
    def opener(request: Request, timeout: float) -> Response:
        return Response(
            json.dumps(
                {
                    "status": "error",
                    "code": 429,
                    "message": "API credits are exhausted",
                }
            ).encode()
        )

    client = TwelveDataClient(api_key="test-key", opener=opener)

    with pytest.raises(MarketDataProviderError, match="API credits are exhausted"):
        client.fetch_daily_prices(
            symbol="AAPL",
            start_date=date(2026, 7, 23),
            end_date=date(2026, 7, 23),
        )
