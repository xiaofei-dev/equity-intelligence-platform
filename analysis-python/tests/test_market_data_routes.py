from datetime import date

from fastapi.testclient import TestClient

from equity_analysis.main import app
from equity_analysis.market_data.routes import get_ingestion_service
from equity_analysis.market_data.service import SymbolIngestionResult

client = TestClient(app)


class FakeIngestionService:
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
            {"symbol": "AAPL", "rows_upserted": 16},
            {"symbol": "MSFT", "rows_upserted": 16},
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
