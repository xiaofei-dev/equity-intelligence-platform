from datetime import date

from fastapi.testclient import TestClient

from equity_analysis.main import app
from equity_analysis.market_data.routes import get_ingestion_service
from equity_analysis.market_data.service import SymbolIngestionResult

client = TestClient(app)


class FakeIngestionService:
    provider_code = "twelve_data"

    def ingest(
        self,
        symbols: tuple[str, ...],
        start_date: date,
        end_date: date,
    ) -> tuple[SymbolIngestionResult, ...]:
        assert symbols == ("AAPL", "MSFT")
        assert start_date == date(2026, 7, 1)
        assert end_date == date(2026, 7, 23)
        return (
            SymbolIngestionResult(symbol="AAPL", rows_upserted=16),
            SymbolIngestionResult(symbol="MSFT", rows_upserted=16),
        )


def test_ingest_daily_prices_returns_normalized_result() -> None:
    app.dependency_overrides[get_ingestion_service] = lambda: FakeIngestionService()
    try:
        response = client.post(
            "/internal/v1/market-data/daily-prices/ingest",
            json={
                "symbols": ["aapl", "MSFT"],
                "start_date": "2026-07-01",
                "end_date": "2026-07-23",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {
        "provider": "twelve_data",
        "results": [
            {
                "symbol": "AAPL",
                "rows_upserted": 16,
                "status": "SUCCEEDED",
                "error_code": None,
                "message": None,
            },
            {
                "symbol": "MSFT",
                "rows_upserted": 16,
                "status": "SUCCEEDED",
                "error_code": None,
                "message": None,
            },
        ],
        "total_rows_upserted": 32,
    }


def test_ingest_daily_prices_rejects_reversed_date_range() -> None:
    app.dependency_overrides[get_ingestion_service] = lambda: FakeIngestionService()
    try:
        response = client.post(
            "/internal/v1/market-data/daily-prices/ingest",
            json={
                "symbols": ["AAPL"],
                "start_date": "2026-07-24",
                "end_date": "2026-07-23",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 422


class PartialFailureIngestionService:
    provider_code = "eodhd"

    def ingest(self, symbols, start_date, end_date):
        del symbols, start_date, end_date
        return (
            SymbolIngestionResult(symbol="AAPL", rows_upserted=1),
            SymbolIngestionResult(
                symbol="TWTR",
                rows_upserted=0,
                status="FAILED",
                error_code="EMPTY_RESULT",
                message="EODHD returned no daily prices for TWTR",
            ),
        )


def test_ingest_daily_prices_reports_partial_failure_without_failing_batch() -> None:
    app.dependency_overrides[get_ingestion_service] = lambda: PartialFailureIngestionService()
    try:
        response = client.post(
            "/internal/v1/market-data/daily-prices/ingest",
            json={
                "symbols": ["AAPL", "TWTR"],
                "start_date": "2026-07-01",
                "end_date": "2026-07-23",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["provider"] == "eodhd"
    assert response.json()["results"][1]["status"] == "FAILED"
    assert response.json()["total_rows_upserted"] == 1


class CompleteFailureIngestionService(PartialFailureIngestionService):
    def ingest(self, symbols, start_date, end_date):
        del symbols, start_date, end_date
        return (
            SymbolIngestionResult(
                symbol="TWTR",
                rows_upserted=0,
                status="FAILED",
                error_code="EMPTY_RESULT",
                message="EODHD returned no daily prices for TWTR",
            ),
        )


def test_ingest_daily_prices_returns_502_when_every_symbol_fails() -> None:
    app.dependency_overrides[get_ingestion_service] = lambda: CompleteFailureIngestionService()
    try:
        response = client.post(
            "/internal/v1/market-data/daily-prices/ingest",
            json={
                "symbols": ["TWTR"],
                "start_date": "2026-07-01",
                "end_date": "2026-07-23",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 502
    assert response.json()["detail"]["code"] == "MARKET_DATA_PROVIDER_ERROR"
