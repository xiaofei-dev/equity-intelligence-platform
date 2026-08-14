# Database Assets

PostgreSQL migrations live in `migrations/` and are packaged into the Spring
Boot application. Flyway applies them during backend startup.

The repository migration source head is V28. The last shared operational
application baseline remains V17 until a separately controlled release. The
managed-database topology, credential
separation, migration release procedure, backups, and recovery targets are
defined in [Database Deployment v1](../docs/database-deployment-v1.md).

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

`V27__create_quant_research_decision_v1.sql` adds the append-only public-safe
Quant v1.1 research projection. It stores no provider payloads and explicitly
denies final portfolio weights, order quantities, brokerage instructions, LLM
signal authority, and guaranteed-return claims.

`V28__create_unified_portfolio_risk_context_v1.sql` adds the append-only
user-owned portfolio context, exact V12 account-snapshot and constraint-policy
bindings, position and sleeve projections, deterministic risk reasons, and
immutable human reviews. It preserves V21 as a legacy lane and never grants
weight, order, brokerage, or LLM authority.

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
- `V14`: add exchange/taxonomy references, point-in-time company profiles and
  security lifecycle evidence, and provider-neutral dataset releases
- `V15`: add explicit-status metric observations plus sector/industry
  screening scopes and aggregate ranks
- `V16`: add idempotent daily refresh orchestration, checkpoints, per-security
  freshness, provider usage telemetry, analytics audit records, and
  full-universe workload indexes
- `V17`: persist immutable assembled market-intelligence profiles, selected
  fact lineage, cohorts, four horizon views, valuation evidence, ranking
  exclusions, profile-screening runs/results, and isolated AI narratives
- `V18`: add the legacy Forward DQV v2 outcome ledger
- `V19`: repair Forward DQV enrollment chronology while refusing preexisting
  v2.1.0 enrollments
- `V20`: add the legacy Forward DQV benchmark outcome v3 lineage
- `V21`: add legacy, unwired Core/Tactical portfolio-decision lanes
- `V22`: add the append-only Unified Market Data and Evidence Foundation v1
  identity, calendar, lineage, canonical evidence, selector, and
  applicability contracts
- `V23`: add append-only Fundamental Value v1 assembly, ordered operand
  evidence-parent seals, deterministic assessment components, and relational
  completeness seals.
  V23 does not own raw retention, deletion, legal holds, portfolio weights,
  orders, or brokerage actions.
- `V24`: add an isolated, development-only company-quality Forward enrollment
  contract with V22 evidence links, a complete terminal cohort and immutable
  seal, and empty 252/504/756-session maturity rows. It seeds no enrollment and
  preserves `NOT_VALIDATED`.
- `V25`: add the exact three-security Fundamental Value identity authority
  used by the current-evidence registration boundary. It does not authorize an
  investment assessment or a portfolio action.
- `V26`: add append-only current Fundamental Value assessment persistence,
  an explicitly provisioned narrow persistence/publication authority, complete
  source/operand provenance, server-owned chronology, and immutable seals.
  It preserves `NOT_VALIDATED` and all action, ranking, final-weight, brokerage,
  and evidence-upgrade prohibitions.

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

V23 is narrower: ordinary `analytics_writer` members have no Fundamental Value
table DML. A deployment credential for the trusted Python persistence
repository must receive the dedicated `analytics_fundamental_value_writer_v1`
role. PostgreSQL enforces relational seals, cardinality, identity, finite
numeric domains, and append-only behavior; the Python repository is the
semantic boundary that replays the complete Stage 2 formula before write and
on readback.

## Schema Acceptance

Run all migrations against PostgreSQL 17, then execute:

```bash
psql -v ON_ERROR_STOP=1 -f database/tests/analytics_schema_acceptance.sql
psql -v ON_ERROR_STOP=1 -f database/tests/app_schema_acceptance.sql
```

The acceptance script verifies required objects, strategy-weight totals,
legacy price backfill, append-only guards, role isolation, missing-value
behavior, and the two-cutoff point-in-time selection rule.

The CI-compatible runner creates isolated clean and populated upgrade-path
databases through V26, preserves the V19 refusal behavior, verifies V18-V25
row/hash preservation, executes the base and advanced V22 relational safety
matrices plus the V23 Fundamental Value, V24 narrow Forward-enrollment,
V25 identity-authority, and V26 current-assessment
schema matrices, and removes every test
database afterward:

```bash
sh database/tests/run-migration-tests.sh
```

The Python-owned typed persistence and internal-query boundary has a real
PostgreSQL integration test. Run it against a disposable database migrated
through V22. Its
module-scoped fixture creates a unique synthetic identity, calendar, provider,
canonical-evidence, and selector namespace, so it does not depend on either
V22 SQL acceptance script having seeded rows:

```bash
TEST_DATABASE_URL=postgresql://... \
  python -m pytest \
  analysis-python/tests/integration/test_evidence_persistence_postgres_v1.py -q
```

The integration test stores only synthetic private-storage references. No
licensed raw payload is committed to Git.
