# Market Intelligence Data Model v1

## Purpose

Market Intelligence Data Model v1 extends the existing analytics schema for
daily United States equity research. It supports a 300-security validation
universe, a 500-security expansion universe, and a future full-US daily
workload without changing the existing user/portfolio or screening contracts.

The model is provider-neutral, point-in-time aware, and append-only wherever
records represent evidence, versions, checkpoints, freshness assessments,
usage telemetry, or audit history.

## Ownership

All objects introduced by V14-V16 are in `analytics.*` and are owned by the
Python analytics service. Flyway owns their DDL. Spring Boot continues to own
`app.*`, the public API, user workflows, portfolios, and human decisions.
Java must consume screening and refresh information through documented HTTP
contracts rather than querying analytics result or operations tables.

This phase does not authorize Python to read or write `app.*`.

## Existing Structures Reused

The phase deliberately reuses:

- `analytics.security`, `security_identifier`, and `security_listing` for
  canonical identity and symbol history;
- `security_classification` for the existing normalized classification
  history;
- `data_provider`, `ingestion_batch`, and `source_record` for provider and
  source lineage;
- `daily_price_observation`, `corporate_action`, `fundamental_fact`, and
  `market_value_observation` for observed numeric evidence;
- `data_snapshot` and `snapshot_universe_member` for sealed point-in-time
  inputs; and
- `screening_run`, factor results, strategy ratings, contributions, and ranks
  for deterministic security-level results.

The legacy `security.active` and `daily_price` tables remain projections for
existing application compatibility. New analytics must use immutable
observations.

## Migration Map

### V14: Reference and Dataset Metadata

- `exchange`: normalized MIC reference data.
- `classification_node`: versioned sector and industry taxonomy nodes.
- `company_profile_observation`: dated profiles and taxonomy assignments with
  source, availability, and ingestion lineage.
- `security_status_observation`: active, inactive, delisted, acquired, and
  bankrupt lifecycle evidence.
- `dataset_definition` and `dataset_release`: provider-neutral dataset,
  schema, normalization, availability-lag, ownership, and retention metadata.

### V15: Evidence and Screening

- `metric_definition`: versioned reusable fundamental or factor definitions.
- `metric_observation`: numeric, text, or Boolean evidence with `VALID`,
  `MISSING`, `INVALID`, and `NOT_APPLICABLE` states.
- `screening_scope`: universe, sector, or industry scope plus a methodology
  reference.
- `screening_group_result`: sector/industry counts, median scores, and ranks
  attached to an immutable screening run and strategy version.

`metric_observation` does not duplicate numeric facts already represented by
`fundamental_fact`. It is the reusable normalized or derived metric boundary
and the explicit non-value boundary. A valid observation has exactly one
typed value and source lineage. A non-valid observation has no value and must
have a reason code. Zero remains a valid numeric value only when actually
observed or deterministically derived.

### V16: Daily Refresh Operations

- `refresh_plan`: immutable versioned cadence and target definitions.
- `refresh_run`: idempotent execution with a canonical request hash.
- `refresh_task`: retryable provider/dataset/security partitions with leases.
- `refresh_checkpoint`: append-only resumability state.
- `security_dataset_freshness`: append-only per-security last-success and
  freshness assessments.
- `provider_usage_event`: append-only request, quota, unit, and estimated-cost
  telemetry without account credentials.
- `analytics_audit_event`: append-only operational audit evidence.

Runs and tasks may change only while operational. Terminal records are
immutable. Retries create a higher task attempt number; freshness changes
create a new assessment.

## Point-in-Time Rules

Economic applicability, provider availability, and platform ingestion are
separate:

1. `effective_at` or the domain date records when the fact applies.
2. `available_at` records when the source made it usable.
3. `ingested_at` records when the platform obtained it.
4. `recorded_at` is database audit time.

A historical selection must satisfy both `available_at <= as_of_time` and
`ingested_at <= ingestion_cutoff`. It must select a compatible dataset,
normalization version, provider, and adjustment mode sealed by the snapshot.
Later corrections append revisions and cannot replace evidence visible to an
earlier snapshot.

## Retention and Licensed Data

Dataset definitions declare one of `PERMANENT`, `AUDIT_7_YEARS`, or
`OPERATIONAL_2_YEARS`. Evidence needed to reproduce sealed snapshots,
completed ratings, or audit decisions must be retained for the applicable
audit period. Operational records may be archived only when they are not
referenced by retained evidence.

The database stores normalized observations, hashes, and durable source
references. It does not store raw licensed provider payloads or secrets.
Deletion or archival automation is intentionally outside this migration.

## Workload and Index Strategy

Indexes prioritize:

- one security's history and latest PIT observation;
- one day's provider/adjustment-mode price batch across a full universe;
- metric cohorts for deterministic normalization;
- sector and industry screening groups;
- pending/stale task claims and per-security retry history; and
- current/stale freshness scans.

The tables use ordinary PostgreSQL 17 indexes rather than premature
partitioning. Daily OHLCV volume for 300, 500, and a full-US universe remains
practical with these access paths. Partitioning should be introduced only
after measured table size, vacuum, backup, or query latency requires it.

## Integration Assumptions

The algorithm task may read `metric_observation` only after it verifies metric
and dataset versions and PIT cutoffs. Provider acceptance, formula readiness,
scoring eligibility, and ranking remain separate states.

The daily-refresh task owns population of refresh plans, runs, tasks,
checkpoints, freshness assessments, and usage events. It must use stable
idempotency keys and canonical hashes, and must never place credentials in
telemetry or checkpoint JSON.

Neither task may assume unmerged application changes. Any new Java-visible
refresh or sector-screening response requires a separately versioned HTTP
contract.

V17 reconciles the separately committed
`MARKET-INTELLIGENCE-SCREENING-v1.0.0` service contract with this foundation.
See
[Market Intelligence Screening v1 Persistence Mapping](market-intelligence-screening-persistence-v1.md)
for the field-level mapping and remaining Python adapter work.
