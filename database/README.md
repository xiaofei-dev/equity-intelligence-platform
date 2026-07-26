# Database Assets

PostgreSQL migrations live in `migrations/` and are packaged into the Spring
Boot application. Flyway applies them during backend startup.

## Schema Ownership

- `app.*`: user-facing workflows and system-of-record state
- `analytics.*`: normalized market data and analysis results

Future `app.*` records include user investment profiles, accounts, cash,
liabilities, holdings, constraints, decisions, and portfolio-specific
recommendation snapshots. Future `analytics.*` records include reference data,
corporate actions, normalized fundamentals, factors, strategy rankings,
coverage states, backtests, and reusable company evidence reviews.

Python may write analytics-owned data and results. Java owns all user-facing
account, holding, and decision state.

Cross-schema changes require an explicit contract and migration.

## Applied Migrations

- `V1`: create `app` and `analytics` schemas
- `V2`: create the security master and daily-price tables; seed the
  six-symbol engineering universe
- `V3`: consolidate duplicate United States ticker identities and enforce
  unique normalized symbols
- `V4`: add source lineage, durable public security IDs, identifier history,
  listing history, and versioned classifications
- `V5`: add immutable price, corporate-action, fundamental, and market-value
  observations; backfill legacy prices as `NOT_VERIFIED`
- `V6`: add sealed data snapshots, source manifests, universe definitions,
  and point-in-time universe membership
- `V7`: add versioned factor and strategy metadata plus idempotent screening
  runs
- `V8`: add immutable coverage, factor, strategy-rating, contribution, and
  horizon results
- `V9`: add analytics access roles and versioned screening read projections

Migration files are append-only after they have been applied to a shared
environment. Corrections require a new migration rather than editing deployed
history.

## Analytics Time and Version Semantics

Versioned observations are append-only. `available_at` records when a
historical process could first use an observation, `ingested_at` records when
the platform received it, and the domain date records when it applies
economically. A point-in-time query must apply both the snapshot's
`as_of_time` and `ingestion_cutoff`.

A missing value is not an observation. Missing or invalid strategy inputs are
stored as factor and coverage statuses with reasons, never as numeric zero.
Sealed snapshots and completed screening results reject subsequent changes.

## Access Boundary

Flyway owns DDL. The `analytics_writer` and `analytics_reader` roles are
`NOLOGIN` group roles; deployment credentials receive membership outside the
migrations. The Python service writes analytics-owned observations and
results. Java may read approved market-data projections, but consumes ratings
through the versioned internal HTTP contract rather than rating-table SQL.

## Schema Acceptance

Run all migrations against PostgreSQL 17, then execute:

```bash
psql -v ON_ERROR_STOP=1 -f database/tests/analytics_schema_acceptance.sql
```

The acceptance script verifies required objects, strategy-weight totals,
legacy price backfill, append-only guards, role isolation, missing-value
behavior, and the two-cutoff point-in-time selection rule.

The CI-compatible runner creates isolated empty and upgrade-path databases,
executes the acceptance script against both, verifies a representative legacy
price backfill, and removes the databases afterward:

```bash
sh database/tests/run-migration-tests.sh
```
