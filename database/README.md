# Database Assets

PostgreSQL migrations live in `migrations/` and are packaged into the Spring
Boot application. Flyway applies them during backend startup.

## Forward Validation

`V11__create_forward_validation.sql` adds the prospective decision-quality
experiment boundary. It references sealed screening runs and stores
immutable provider acceptances, enrollments, signals, policy events, shadow
orders and fills, cash flows, valuations, observations, metrics, and report
snapshots. Signal and result tables are append-only; corrections create
superseding versions.

Formal experiments require a provider acceptance identifier. This schema does
not authorize real trading or make a return claim.

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

`V12__create_user_and_portfolio_context.sql` adds future-safe application
users and external identities, immutable account and liability snapshots,
aggregate portfolios, versioned constraints, portfolio scenarios, immutable
human decisions, and append-only audit events. Closed-test identity records are
provisioned outside the migration so that private identity data never enters
source control.

For a trusted local environment, provision the two test identities by supplying
opaque subjects at execution time:

```powershell
psql `
  --set=first_subject='tester-one' `
  --set=second_subject='tester-two' `
  --set=issuer='equity-local' `
  --file=database/dev/provision_closed_test_users.sql
```

The provisioning script is intentionally not a Flyway migration and must not
contain real credentials or authentication tokens.

New price ingestion writes an immutable `daily_price_observation` with
provider, batch, source hash, availability, ingestion, and normalization
lineage. The legacy `daily_price` projection remains temporarily populated for
the Phase 1 market-data endpoint, but screening reads only immutable
observations and snapshot-linked sources.

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
- `V10`: make fundamental-fact idempotency treat a null period start as part
  of the same source observation
- `V11`: add immutable forward decision-quality validation records
- `V12`: add user, identity, portfolio-context, constraint, and decision records
- `V13`: seal the selected market-data provider and normalized adjustment mode
  into every data snapshot

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
psql -v ON_ERROR_STOP=1 -f database/tests/app_schema_acceptance.sql
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
