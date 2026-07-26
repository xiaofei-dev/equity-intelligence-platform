# Analytics Service

The FastAPI service owns market-data ingestion, deterministic quantitative
analysis, screening, backtesting, and later AI evidence preparation.

## Implemented Contracts

- `GET /health`: service health
- `POST /internal/v1/market-data/daily-prices/ingest`: bounded and idempotent
  Twelve Data daily-price ingestion

The service reads `TWELVE_DATA_API_KEY` and `ANALYTICS_DATABASE_URL` from the
runtime environment. It must not log or return credentials.

## Development

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m uvicorn equity_analysis.main:app --reload
```

## Validation

```powershell
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m pytest
```

## Next Responsibility

Implement a minimal, versioned quantitative screen over the existing daily
prices. The result must expose explicit factor values, an as-of date, a
strategy version, and deterministic candidate ranking. Do not add fundamentals,
machine learning, or a larger universe in that slice.
