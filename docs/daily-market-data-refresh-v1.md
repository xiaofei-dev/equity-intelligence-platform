# Daily Market Data Refresh v1

## Scope and safety boundary

Daily Market Data Refresh v1 is a provider-neutral Python analytics-worker
workflow for an explicitly configured United States equity universe. It
refreshes daily prices and corporate actions. It does not refresh fundamentals,
make a security scoreable, run a model, or authorize a trade.

Yahoo Finance through `yfinance` is the default no-key adapter for development
and internal evaluation where its terms and data quality permit. It is not a
contracted market-data feed. Yahoo terms, upstream availability, unofficial API
behavior, exchange rights, display/redistribution rights, and commercial use
must be reviewed before deployment. EODHD remains the bounded licensed
alternative. Intrinio or another provider must implement the normalized
price/action protocols rather than changing refresh or scoring contracts.

No production provider request is authorized by this implementation. Every
live run requires a separately bounded preflight and explicit approval.

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
  total-return-adjusted-price, and corporate-action dataset codes.
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
6. Provider retries terminally fail the current task attempt and create a
   higher attempt. Restart recovery resumes partitions whose latest task is
   pending, leased/running, or failed.
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

Price freshness is scoped only to price datasets. It cannot update a
fundamental timestamp or imply that SEC/provider fundamental evidence is
current or scoring-ready.

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
is `MISSING`. Retryable transport, rate-limit, server, and temporarily empty
responses use bounded exponential backoff. Malformed data and entitlement
errors fail without unbounded retries.

Inactive securities and listings ending before the expected session are
excluded and counted. Delisting evidence closes a listing through the
security-master workflow; a missing price never silently deactivates a
security.

## EODHD quota math

The planner reserves 10,000 of the 100,000 daily allowance. It conservatively
charges one logical request for each price mode and one for actions, and
reserves all three allowed attempts.

| Universe | Logical requests | Worst case: 3 attempts | Allowance used | Capacity after 10k reserve |
|---:|---:|---:|---:|---:|
| 300 | 900 | 2,700 | 2.7% | 87,300 |
| 500 | 1,500 | 4,500 | 4.5% | 85,500 |
| Full-US example: 8,000 | 24,000 | 72,000 | 72.0% | 18,000 |

The 8,000-security example is quota math, not a current listing count. Every
plan uses the exact manifest size. An initial refresh above 1,000 active
securities requires `allow_large_full_refresh`. If prior V16 usage plus the
worst-case plan exceeds 90,000, planning fails before a provider call.

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
- four existing `dataset_definition.dataset_code` values
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
