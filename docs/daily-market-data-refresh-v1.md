# Daily Market Data Refresh v1

## Scope and safety boundary

Daily Market Data Refresh v1 is a provider-neutral Python analytics-worker
workflow for an explicitly configured United States equity universe. It
refreshes daily prices, corporate actions, and bounded fundamental snapshots.
It does not make a security scoreable, run a model, or authorize a trade.

Yahoo Finance through `yfinance` is the default no-key adapter for development
and internal evaluation where its terms and data quality permit. It is not a
contracted market-data feed. Yahoo terms, upstream availability, unofficial API
behavior, exchange rights, display/redistribution rights, and commercial use
must be reviewed before deployment. EODHD remains the bounded licensed
alternative. Intrinio or another provider must implement the normalized
price/action protocols rather than changing refresh or scoring contracts.

Every live run requires an exact bounded preflight and confirmation token.
Provider execution is never started by importing the package or starting the
FastAPI web service.

## Implemented persistence contract

The runtime implements the schema introduced by database migrations V14-V16
and reuses the immutable observation structures from V1-V13. It does not
create compatibility tables or require another migration.

V16 tables used:

- `analytics.refresh_plan`: the active, immutable plan selected by configured
  `plan_key`, `plan_version`, provider, and plan dataset code.
- `analytics.refresh_run`: one idempotent scheduled execution, keyed by plan,
  provider, universe version, and expected session.
- `analytics.refresh_task`: one security/dataset/adjustment partition per
  attempt. Provider retries create a higher `attempt_number`; terminal tasks
  are never changed.
- `analytics.refresh_checkpoint`: append-only completion checkpoints with
  canonical hashes.
- `analytics.security_dataset_freshness`: append-only per-security dataset
  assessments. The latest event is the current view.
- `analytics.provider_usage_event`: append-only physical request and weighted
  unit telemetry. Local weights remain `NOT_RECONCILED` with provider billing.

Existing tables used:

- `analytics.security.public_id` resolves the configured UUID to the existing
  bigint `security.id`.
- `analytics.data_provider` supplies the existing provider identifier.
- `analytics.dataset_definition` supplies configured plan, unadjusted-price,
  total-return-adjusted-price, corporate-action, and fundamental dataset codes.
- `analytics.ingestion_batch` and `analytics.source_record` retain provider
  schema/parser/normalization versions, source reference, content hash, and
  availability/ingestion lineage.
- `analytics.daily_price_observation` stores append-only normalized OHLCV
  revisions by security, session, provider, adjustment mode, and source.
- `analytics.corporate_action` stores append-only dividend/split revisions by
  stable provider action identity and source.

Dataset codes are deployment reference data injected through `DatasetCodes`;
the application does not invent or silently insert them. The configured V16
refresh plan and all four dataset definitions must exist before the scheduler
starts.

## Runtime flow

1. A deployed scheduled job loads an immutable, versioned universe manifest.
2. The planner reads the latest V16 freshness event for each
   `(security, dataset, provider, adjustment mode)` and today's provider usage.
3. It identifies the latest expected US market session, applies a five-session
   overlap, and reserves worst-case retry cost.
4. PostgreSQL `pg_try_advisory_lock` permits only one refresh process.
5. The runtime creates or resumes an idempotent V16 run and its deterministic
   task partitions.
6. Provider-internal retries remain disabled. A separately approved second
   runner attempt creates a higher task attempt. Restart recovery never
   replays an `UNKNOWN` request and requires matching immutable journal
   evidence before terminal recovery.
7. The writer creates an idempotent ingestion batch and source record, then
   appends only unseen immutable observations. A changed source content hash
   creates a higher observation/action revision. Replaying the same source
   inserts nothing.
8. The task is terminally completed, and freshness plus checkpoint records are
   appended. The run ends as `SUCCEEDED`, `PARTIAL`, or `FAILED`.

Price datasets remain distinct:

- Unadjusted prices persist provider-native OHLCV and a null adjusted close.
- Total-return-adjusted prices require an adjusted close and preserve the
  normalized adjustment-mode identifier.
- Corporate actions preserve dividends and splits independently of prices.

Price, corporate-action, and fundamental freshness are independent. A price
refresh cannot update a fundamental timestamp or imply that provider
fundamental evidence is current or scoring-ready.

## Time and lineage semantics

For every persisted source:

- the trading/effective date records economic applicability;
- `available_at` records provider availability;
- `ingested_at` records platform receipt and cannot precede availability;
- `recorded_at` remains the database audit time;
- provider schema, parser, and normalization versions remain explicit; and
- content hash plus source reference determines source idempotency.

The writer never issues `UPDATE` or `DELETE` against
`daily_price_observation` or `corporate_action`. Corrections append revisions.
Legacy `analytics.daily_price` is not the refresh writer's source of truth.

V16 freshness supports `CURRENT`, `STALE`, `MISSING`, `INVALID`, and
`NOT_APPLICABLE`. Runtime `LATE` maps to V16 `STALE` with reason
`LATE_DATA`; provider/persistence failure maps to `INVALID`; inactive or
delisted scope maps to `NOT_APPLICABLE`. Explicit states are never replaced
with numeric zero.

## Calendar and lifecycle behavior

The deterministic calendar handles weekends, standard US market holidays, Good
Friday, and explicit exceptional-closure overrides. Early closes are sessions.
Operations must configure unexpected exchange closures.

One missing expected session is `LATE`; a wider gap is `STALE`; an empty result
is `MISSING`. Provider rate limiting, authentication failure, malformed data,
entitlement failure, an unknown request state, or a journal/lease mismatch is
a hard stop. Provider-internal retries are disabled.

Inactive securities and listings ending before the expected session are
excluded and counted. Delisting evidence closes a listing through the
security-master workflow; a missing price never silently deactivates a
security.

## Closed-test operator workflow

Bootstrap the immutable universe once:

```powershell
.\analysis-python\.venv\Scripts\python.exe -m `
  equity_analysis.daily_refresh.cli bootstrap
```

Generate one no-network preflight for prices, actions, and fundamentals:

```powershell
.\analysis-python\.venv\Scripts\python.exe -m `
  equity_analysis.daily_refresh.cli workflow-preflight `
  --scheduled-for 2026-07-28T23:00:00Z `
  --eodhd-dashboard-used 26647 `
  --runner-max-attempts 1 `
  --allow-initial-backfill
```

Execute the exact frozen workflow with the printed token:

```powershell
.\analysis-python\.venv\Scripts\python.exe -m `
  equity_analysis.daily_refresh.cli workflow-run `
  --scheduled-for 2026-07-28T23:00:00Z `
  --eodhd-dashboard-used 26647 `
  --runner-max-attempts 1 `
  --allow-initial-backfill `
  --confirm "I_CONFIRM_66_UNIVERSE_DAILY_REFRESH:<SHA256>"
```

The v1 universe contains 57 price/action targets and 55 fundamental targets.
The accepted offline aggregate preflight contains 226 task partitions and a
226-physical-request ceiling at one runner attempt. EODHD hard weight is 664,
including shared action and fundamental budget reservation.

## EODHD quota math

The planner reserves 10,000 of the 100,000 daily allowance. It conservatively
charges the selected datasets and reserves the configured one- or two-attempt
hard ceiling before constructing the provider.

| Universe | Logical requests | Worst case: 2 attempts | Allowance used | Capacity after 10k reserve |
|---:|---:|---:|---:|---:|
| 300 | 900 | 1,800 | 1.8% | 88,200 |
| 500 | 1,500 | 3,000 | 3.0% | 87,000 |
| Full-US example: 8,000 | 24,000 | 48,000 | 48.0% | 42,000 |

The 8,000-security example is quota math, not a current listing count. Every
plan uses the exact manifest size. If prior V16 usage plus the worst-case plan
exceeds 90,000, planning fails before a provider call.

## 2026-07-28 bounded live result

The six-symbol Yahoo canary passed. The first 57-security price attempt stopped
safely after ACN supplied one internally inconsistent 2026-07-28 OHLC bar.
Offline remediation made invalid rows non-fatal to otherwise valid history,
made the yfinance cache location explicitly writable, prevented adjusted and
unadjusted partitions from double-counting one failed transport, and corrected
`STALE` freshness persistence.

The approved bounded recovery then completed:

- ACN plus ABT canary: two Yahoo requests; ABT `CURRENT`; ACN retained 259 valid
  sessions and is `STALE/LATE_DATA` through 2026-07-27;
- remaining price scope: 41 Yahoo requests and 82 successful partitions;
- corporate actions: 57 securities, 114 EODHD requests/weight units; and
- fundamentals: 55 securities, 55 EODHD requests and 550 weight units.

All terminal journals, usage events, and task states are persisted; no active
refresh run, task lease, or `UNKNOWN` request remains. The invalid ACN bar was
not coerced, repaired, or labeled as a completed daily observation.

## Deployment requirements

Run an ephemeral worker near managed PostgreSQL, not on the user's PC. A sample
schedule is `30 2 * * 2-6` UTC after the normal US close. A separately bounded
late-data reconciliation may run at `30 12 * * 2-6` UTC.

Required runtime configuration:

- `ANALYTICS_DATABASE_URL`
- `MARKET_DATA_PROVIDER=yfinance|eodhd|twelve_data`
- selected provider credential when applicable
- versioned universe source
- V16 refresh `plan_key` and `plan_version`
- the configured plan and observation `dataset_definition.dataset_code` values
- provider timeout/retry and EODHD budget/reserve settings

Render can invoke the analytics image as a Cron Job. AWS can use EventBridge
Scheduler with an ECS Fargate task. Alert on `FAILED`, `PARTIAL`, prolonged
lock contention, cursor lag beyond two sessions, budget rejection, stale
leases, or excessive duration. Logs include run ID, provider, universe
version, counts, estimated/actual units, and stable error codes; credentials
and raw responses are prohibited.

## Verification

Offline tests inject providers, clock, sleep, writer, and store. Static
schema-drift checks require every V16 table/column used by persistence and ban
the removed draft table names. A PostgreSQL integration test, enabled with
`DAILY_REFRESH_V16_TEST_DATABASE_URL`, runs the complete writer/runner path
against PostgreSQL 17 after V1-V16, then proves a repeated run adds no duplicate
prices, actions, freshness events, or checkpoints.
