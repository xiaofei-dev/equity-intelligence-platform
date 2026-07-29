# Analytics Service

The FastAPI service owns market-data ingestion, deterministic quantitative
analysis, screening, backtesting, and later AI evidence preparation.

## Implemented Contracts

- `GET /health`: service health
- `POST /internal/v1/market-data/daily-prices/ingest`: bounded, idempotent,
  provider-neutral daily-price ingestion with explicit per-symbol outcomes
- `POST /internal/v1/tactical/evaluate`: deterministic
  `TACTICAL-SIGNAL-v2.1.0` evaluation over caller-supplied adjusted completed
  daily bars; it performs no provider request or trade execution
- `POST /internal/v1/analytics/models/long-horizon/evaluate`: stable,
  versioned `LONG-HORIZON-RESEARCH-v1.0.0` model boundary
- `POST /internal/v1/analytics/models/tactical/evaluate`: stable, versioned
  `TACTICAL-SIGNAL-v2.1.0` model boundary
- `POST /internal/v1/market-intelligence/profiles/build`: assemble a
  non-durable versioned research profile
- `POST /internal/v1/market-intelligence/profiles/build-durable`: assemble and
  persist an immutable V17 research profile
- `GET /internal/v1/market-intelligence/profiles/{profileId}`: reconstruct one
  durable research profile
- `POST /internal/v1/market-intelligence/screen`: run an in-memory sector,
  industry, or security screen
- `POST /internal/v1/market-intelligence/screen-durable`: persist an immutable
  V17 screening run and results
- `GET /internal/v1/market-intelligence/screening-runs/{runId}`: read one
  durable screening result set

The market-data ingestion service selects `twelve_data`, `yfinance`, or `eodhd` with
`MARKET_DATA_PROVIDER`. Twelve Data reads `TWELVE_DATA_API_KEY`, EODHD reads
`EODHD_API_KEY`, and yfinance requires no key. All providers also require
`ANALYTICS_DATABASE_URL` for ingestion. Credentials must not be logged,
returned, persisted, or placed in source references.

The analytics model interface is provider-neutral. Daily-price providers
implement the normalized `DailyPriceProvider` boundary. Long-horizon evidence
must first pass the factor, point-in-time, and missing-data assembly boundary.
Changing a provider changes its adapter and evidence provenance, not either
model's request or scoring contract.

New observations use `UNADJUSTED`, `SPLIT_ADJUSTED`, or
`TOTAL_RETURN_ADJUSTED`. Historical `splits` and `all` values remain readable
through the compatibility mapping. yfinance is development/fallback only.
EODHD has passed the bounded current-use provider gates. That acceptance is
capability-specific and does not by itself establish historical point-in-time
readiness or make every security eligible for a score.

## Development

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m uvicorn equity_analysis.main:app --reload
```

## Daily Refresh Operator CLI

Daily Refresh is operator-triggered and is never started by FastAPI startup.
Bootstrap and preflight access PostgreSQL only; they do not construct a
provider client or make a provider request.

Bootstrap the versioned closed-test universe once:

```powershell
.\.venv\Scripts\python.exe -m equity_analysis.daily_refresh.cli bootstrap
```

Print one aggregate, no-network preflight for the bounded 66-security workflow:

```powershell
.\.venv\Scripts\python.exe -m equity_analysis.daily_refresh.cli `
  workflow-preflight `
  --scheduled-for 2026-07-28T23:00:00Z `
  --eodhd-dashboard-used 26647 `
  --runner-max-attempts 1 `
  --allow-initial-backfill
```

The preflight freezes the exact prices, actions, and fundamentals plans,
configuration hashes, completed session, symbols, physical-request ceilings,
and the shared EODHD weighted-call ceiling. Execute that same workflow with the
printed aggregate token:

```powershell
.\.venv\Scripts\python.exe -m equity_analysis.daily_refresh.cli `
  workflow-run `
  --scheduled-for 2026-07-28T23:00:00Z `
  --eodhd-dashboard-used 26647 `
  --runner-max-attempts 1 `
  --allow-initial-backfill `
  --confirm "I_CONFIRM_66_UNIVERSE_DAILY_REFRESH:<SHA256>"
```

`workflow-run` executes prices, actions, then fundamentals. It continues only
after a `SUCCEEDED` result. A partial, failed, locked, budget-skipped, unknown,
or terminal result stops the workflow before the next provider is constructed.
Provider adapters retain zero internal retries; `--runner-max-attempts 2` is
the absolute operator-approved cumulative ceiling.

The existing per-plan `preflight --plan ...` and `run --plan ...` commands
remain available for canaries and isolated recovery.

## Validation

```powershell
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m pytest
```

## Tactical Signal v2.1

`equity_analysis.tactical.signal_v2` evaluates completed daily sessions for
short-term speculation without changing the long-horizon investment models.
It separates rebound potential, entry timing, risk, entry stage, and
one-week/one-month/three-month outlooks. V2.1 additionally separates tactical
opportunity from current entry value and momentum extension risk, so a valid
momentum thesis can explicitly return `WAIT_FOR_PULLBACK`.

Replay all currently sealed tactical payloads without provider requests:

```powershell
.\analysis-python\.venv\Scripts\python.exe `
  analysis-python\scripts\run_tactical_signal_validation.py `
  --all `
  --replay-latest
```

Replay mode does not require `.env` or an API key and records zero physical
requests. Live validation is blocked unless `--execute-live` is supplied
explicitly. Signals are formed after the close, become effective no earlier
than the next session open, and expire after the next completed daily refresh.
See the
[Tactical Signal v2.1 methodology](../docs/tactical-signal-v2-1-methodology-2026-07-28.md).

## Current Analytical Boundary

The two deterministic models now share a stable invocation and evidence
envelope. The AI research layer remains a separately versioned, validated
overlay and cannot replace missing deterministic inputs.

The Forward Decision-Quality framework has passed offline contract acceptance.
Its performance status remains `PENDING_FUTURE_OUTCOMES`: no prospective
signal has yet matured through the 5-, 20-, or 60-trading-day horizon, and no
statistical edge is claimed.

The V16 refresh and V17 Market Intelligence boundaries now create synchronized
durable profiles and sealed screening handoffs that Spring Boot publishes.
After a completed session passes identity, corporate-action, benchmark, and
ranking-eligibility gates, Forward Validation may append prospective outcomes
without changing the frozen model contracts. A partial/no-eligible screen
remains valid evidence but is not enrolled as a ranked decision.

`equity_analysis.daily_refresh` is implemented as a provider-neutral planner,
runner, scheduler boundary, and PostgreSQL persistence adapter. It is not
automatically started by the FastAPI process. Production scheduling remains a
deployment responsibility with explicit quota and full-refresh safety limits.

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

This calculation package is the frozen formula boundary used by the persisted
screening and Market Intelligence composition layers. It is not a claim that
every security has sufficient data or that a full-market historical backtest
has passed. See the
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

After `EODHD_API_KEY` is configured locally, run the bounded EODHD acceptance
and yfinance price cross-check with:

```powershell
.\analysis-python\.venv\Scripts\python.exe -m `
  equity_analysis.provider_validation.cli `
  --providers eodhd sec_edgar yfinance `
  --fixture analysis-python/tests/fixtures/provider_acceptance_universe_v1.json `
  --start-date 2020-01-01 `
  --end-date 2026-07-25
```

Without the EODHD key, EODHD checks return `NOT_VERIFIED`; mock tests never
substitute for live acceptance.

### 100-security mature-company data gate

The bounded mature-company gate uses
`tests/fixtures/provider_acceptance_universe_v3.json`. It contains exactly 100
primary general-company candidates and 20 sector-matched reserves across eight
non-financial sectors. It does not use exchange-wide or bulk-US downloads.

EODHD supplies normalized fundamentals and historical market value. SEC EDGAR
filing acceptance timestamps remain authoritative for point-in-time
availability. An EODHD financial period without a matching SEC availability
timestamp remains `PARTIAL` and cannot enter an Objective Rating snapshot.

The live run has hard limits of 1,122 HTTP attempts and 3,500 weighted EODHD
calls. The live step requires separate authorization. Offline tests never read
`EODHD_API_KEY`.

Validate the manifest without network requests:

```powershell
.\analysis-python\.venv\Scripts\python.exe -m `
  equity_analysis.provider_validation.mature_gate_cli
```

Every invocation first prints a no-network preflight showing the selected
symbols, endpoints, locally projected HTTP requests, and locally configured
weighted-call accounting. The current local weights are not treated as
provider-dashboard proof while the July 27 usage discrepancy remains open.

Live execution requires both `--execute-live` and the exact confirmation
`--confirm-live I_CONFIRM_BOUNDED_LIVE_REQUESTS`. Use `--maximum-symbols` for a
bounded canary.

Only one live gate may hold the cross-process lock. Each accepted live start
receives a unique run ID and writes to a new
`mature-company-data-gate-{run-id}.json` path using exclusive creation.
Existing reports are never overwritten. The lock is preventive; it does not
prove that earlier visible Windows processes represented independent runs.

The command does not print the API key or persist licensed raw responses.

Only `PASS` companies are scoreable. Missing values remain absent, and the gate
does not change Objective Rating v1 formulas, thresholds, or public contracts.
