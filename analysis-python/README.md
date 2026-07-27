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

Design and validate the first quantitative data contract before broad
implementation. The authoritative methodology handoff is
[`docs/quantitative-screening.md`](../docs/quantitative-screening.md).

The next slice should:

- Define a 20-security provider-validation universe
- Add replaceable reference, price, corporate-action, and fundamental provider
  contracts
- Validate point-in-time fields and data lineage
- Ingest sufficient history for general non-financial companies
- Produce versioned `Quality Compounder` and `Undervalued Quality` rankings
- Keep quantitative-only and AI-reviewed states separate

Do not force banks, insurers, REITs, resource companies, biotechnology, or
special situations through the initial general-company model.

## Objective Rating v1 Validation Slice

The `equity_analysis.screening` package now provides:

- Immutable Pydantic domain and internal-contract models
- Explicit Decimal factor calculations
- Versioned `QC-v1.0.0`, `UQ-v1.0.0`, and near-term configurations
- Deterministic cohort winsorization and percentile normalization
- Separate near-term, undefined medium-term, and long-term assessments
- Exact factor contributions, missing reasons, risk flags, and lineage

This is an executable calculation and contract fixture, not a full-market
ingestion job or persisted screening-run API. See the
[v1 validation report](../docs/objective-rating-v1-validation.md).

## Provider Acceptance CLI

Run the representative read-only provider checks from the repository root:

```powershell
.\analysis-python\.venv\Scripts\python.exe -m `
  equity_analysis.provider_validation.cli `
  --representative `
  --start-date 2020-01-01 `
  --end-date 2026-07-25
```

`TWELVE_DATA_API_KEY` and `SEC_USER_AGENT` may come from the process environment
or local `.env`. SEC requires a descriptive application name and a real contact
address. If either provider is not configured, its checks return
`NOT_VERIFIED`; the CLI never substitutes a pass.

The command prints a derived JSON report. It does not persist raw provider
responses or credentials.

The CLI spaces Twelve Data calls by eight seconds by default to respect the
current eight-credit-per-minute plan. The interval can be changed explicitly
with `--twelve-data-request-interval-seconds`, but it must not be reduced below
the active provider entitlement.

For an SEC-only acceptance run that does not consume Twelve Data credits:

```powershell
.\analysis-python\.venv\Scripts\python.exe -m `
  equity_analysis.provider_validation.cli `
  --providers sec_edgar
```
