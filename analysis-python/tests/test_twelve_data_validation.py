import json
from io import BytesIO

import pytest

from equity_analysis.provider_validation.twelve_data import (
    TwelveDataValidationClient,
    TwelveDataValidationError,
)


class Response(BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


def opener_for(payloads):
    def open_request(request, timeout):
        del timeout
        endpoint = request.full_url.split("/")[-1].split("?")[0]
        return Response(json.dumps(payloads[endpoint]).encode())

    return open_request


def test_twelve_data_validation_summarizes_prices_and_actions() -> None:
    client = TwelveDataValidationClient(
        api_key="test-key",
        opener=opener_for(
            {
                "time_series": {
                    "meta": {
                        "symbol": "AAPL",
                        "exchange": "NASDAQ",
                        "type": "Common Stock",
                        "currency": "USD",
                    },
                    "values": [
                        {"datetime": "2020-01-02"},
                        {"datetime": "2026-07-24"},
                    ],
                },
                "splits": {
                    "splits": [
                        {"date": "2020-08-31"},
                        {"date": "2014-06-09"},
                    ]
                },
                "dividends": {
                    "dividends": [
                        {"ex_date": "2026-05-11"},
                        {"ex_date": "2026-02-09"},
                    ]
                },
            }
        ),
    )

    prices = client.fetch_price_summary(
        "aapl",
        start_date=__import__("datetime").date(2020, 1, 1),
        end_date=__import__("datetime").date(2026, 7, 25),
    )
    splits = client.fetch_splits_summary("AAPL")
    dividends = client.fetch_dividends_summary("AAPL")

    assert prices.adjustment_mode == "all"
    assert prices.observation_count == 2
    assert splits.observation_count == 2
    assert dividends.observation_count == 2


def test_twelve_data_validation_preserves_provider_rejection_as_error() -> None:
    client = TwelveDataValidationClient(
        api_key="test-key",
        opener=opener_for(
            {
                "splits": {
                    "status": "error",
                    "code": 403,
                    "message": "Endpoint is not included in this plan",
                }
            }
        ),
    )

    with pytest.raises(TwelveDataValidationError, match="not included"):
        client.fetch_splits_summary("AAPL")


def test_twelve_data_validation_enforces_configured_request_interval() -> None:
    times = iter((100.0, 102.0, 108.0))
    sleeps = []
    client = TwelveDataValidationClient(
        api_key="test-key",
        opener=opener_for(
            {
                "splits": {"splits": [{"date": "2020-08-31"}]},
                "dividends": {"dividends": [{"ex_date": "2026-05-11"}]},
            }
        ),
        minimum_request_interval_seconds=8.0,
        monotonic=lambda: next(times),
        sleeper=sleeps.append,
    )

    client.fetch_splits_summary("AAPL")
    client.fetch_dividends_summary("AAPL")

    assert sleeps == [6.0]
