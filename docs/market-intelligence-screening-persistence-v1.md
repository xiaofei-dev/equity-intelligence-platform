# Market Intelligence Screening v1 Persistence Mapping

## Contract Source

This mapping reconciles commit
`950d41c1a1ce2ba5eba8326883685456d0eac5a6` and its
`docs/market-intelligence-screening-v1.md` handoff with database migrations
V1-V17. It distinguishes reusable evidence from immutable assembled profiles
and avoids creating parallel security, observation, snapshot, or sector-group
models.

All listed records are Python-owned `analytics.*`. No `app.*` ownership or
Spring Boot database access changes are introduced.

## Existing V1-V16 Mappings

| Screening contract field | Durable mapping | Notes |
| --- | --- | --- |
| `securityId` | `security.public_id` | The V17 profile stores the internal `security.id` foreign key; the wire UUID is joined from `public_id`. |
| Symbol history | `security_listing` | The profile freezes the selected `symbol` for reproducibility. |
| Issuer, currency, instrument type | `security` and `company_profile_observation` | The selected values are frozen in the profile. |
| Exchange MIC | `security_listing.mic`, `exchange.mic` | The selected MIC is frozen in the profile. |
| CIK and durable provider ID | `security_identifier` | The selected identifiers are frozen in the profile. |
| Classification observation | `company_profile_observation`, `security_classification`, and `classification_node` | Existing dated evidence remains authoritative; V17 freezes the selected taxonomy, names, company type, and effective timestamp rather than adding another observation table. |
| Provider code/schema | `source_record.provider_id -> data_provider` | `data_provider.provider_schema_version` supplies the provider schema version. |
| Parser version | `source_record.ingestion_batch_id -> ingestion_batch.parser_version` | No duplicate parser field is stored in V17 lineage. |
| Source reference/hash | `source_record.source_reference` and `content_hash` | V17 lineage references the source UUID. |
| `availableAt`/`retrievedAt` | `source_record.available_at` and `ingested_at` | Profile lineage also freezes the contract timestamps used by assembly. |
| Typed fact version/state/value/reason/unit/currency | `metric_observation` | The adapter resolves `metric_code` plus `metric_version`; the table enforces exactly one typed value for `VALID`, no value for other states, and an explicit reason code for non-valid states. Integer contract values use exact scale-zero numeric observations. |
| Fact definition/version | `metric_definition` | Keeps formula and unit policy versioned. |
| Fact source lineage | `metric_observation.source_record_id` plus `source_record` | V17 adds only an ordinal junction for facts derived from multiple existing source records. |
| Objective Rating status and dimensions | `coverage_result`, `strategy_rating`, and frozen profile columns | V17 does not alter Objective Rating formulas or equate provider acceptance with eligibility. |
| Strategy/factor methodology | `strategy_definition`, `factor_definition`, `strategy_factor_weight` | Existing hashes and versions remain authoritative. |
| Security screening factors/contributions/ranks | `factor_result`, `factor_result_lineage`, `factor_contribution`, and `strategy_rating` | These remain the Objective Rating calculation record. |
| Data snapshot/cutoffs | `data_snapshot`, `data_snapshot_source`, and `snapshot_universe_member` | V17 profiles and screening runs may reference the sealed source snapshot. |
| Sector/industry aggregate screening | `screening_scope` and `screening_group_result` | V17 does not duplicate group results. |
| Per-security freshness | `security_dataset_freshness` | Stale profile exclusions are frozen separately so historical ranking decisions remain reproducible. |

## V17 Profile-Layer Additions

### `security_profile_snapshot`

Persists the assembled contract identity, frozen security projection,
classification projection, `profileState`, `rankingState`, Objective Rating
status/version/dimensions, explainability statements, and input payload hash.
Its uniqueness matches the handoff:
security, as-of timestamp, contract version, and input hash.

Classification columns are all-null or all-present. Authoritative evidence
continues to live in V1-V16 tables. Classification lineage is an ordered set of
existing `source_record` references, and a classified profile must identify
its primary classification source.

### `security_profile_fact` and `security_profile_fact_lineage`

Select existing `metric_observation` records into the profile. No fact value or
status is copied. The optional ordered lineage junction supports multi-source
derived facts while retaining source timestamps and hashes through
`source_record`.

### `comparable_cohort_snapshot`

Freezes cohort identity, taxonomy, company type, optional industry and size
band, eligible/minimum counts, and generated sufficiency. It does not add a
second universe-membership model.

### `market_intelligence_horizon_view`

Persists exactly one view per profile for `ONE_WEEK`, `ONE_MONTH`,
`THREE_MONTHS`, and `TWELVE_MONTHS_PLUS`. Each record preserves model ID and
version, assessed/insufficient/not-applicable state, model/as-of/effective/
expiry timestamps, input and evidence hashes, missing inputs, explanation,
label, and optional score. Only `ASSESSED` views may carry a score.

This table is separate from V8 `horizon_assessment`: V8 is an Objective Rating
run projection with near/medium/long labels, while the screening contract
requires four differently named, independently versioned and expiring model
views.

### `market_intelligence_valuation_evidence`

Freezes the three components used by Buying Opportunity v1: Objective
valuation, long-horizon valuation, and own-history percentile. A `VALID`
record requires all three; any other state carries none. Limitations and an
evidence hash are retained. The arithmetic remains application-owned and is
not encoded as a universal score.

### `market_intelligence_ranking_exclusion`

Stores ordered classification, fact, stale, cohort, formula, model, filter, or
ranking exclusions. This is separate from V8 `coverage_reason` because profile
assembly and profile filtering occur after, and can combine, multiple
deterministic model outputs.

### `market_intelligence_screening_run` and result

The run freezes the contract version, idempotency and canonical-request hashes,
as-of time, optional source snapshot, filter JSON, ranking metric/direction/
limit, methodology reference, input snapshot hash, observed gate counts,
status, result hash, and seal time.

This is not a duplicate of `screening_run`. The existing table is the
Objective Rating calculation task that creates factors and strategy ratings.
The V17 run filters and ranks already assembled durable profiles across
Objective, tactical, long-horizon, and Buying Opportunity metrics. Results
uniquely constrain both rank and profile within a run.

### `market_intelligence_ai_narrative`

Persists optional cited narrative, generation time, prompt/model versions,
confidence, and narrative hash. `may_affect_deterministic_fields` is constrained
to `false`. This table has no foreign-key path into deterministic fact,
horizon, valuation, eligibility, contribution, or rank values.

## Immutability and Corrections

All V17 tables reject update and delete. A correction creates:

- a new source/metric revision when evidence changes;
- a new profile with a new input hash;
- a new screening run with a new canonical request/input snapshot hash; or
- a new profile-bound AI narrative rather than altering deterministic fields.

This preserves the historical service response and its selection rationale.

## Implemented Application Adapter

The Python analytics service now provides an idempotent transactional adapter
in `equity_analysis.market_intelligence.persistence`. It:

1. resolves wire `securityId` through `security.public_id`;
2. resolves selected `metric_observation` and ordered `source_record` lineage
   by exact provider, schema, parser, reference, hash, and timestamps;
3. atomically inserts a profile and every V17 child;
4. calculates canonical profile, request, input-snapshot, valuation, narrative,
   and result hashes;
5. inserts sealed screening runs and ordered results idempotently; and
6. reconstructs internal API responses from sealed profile/run records.

Internal durable endpoints are:

- `POST /internal/v1/market-intelligence/profiles/build-durable`
- `GET /internal/v1/market-intelligence/profiles/{profileId}`
- `POST /internal/v1/market-intelligence/screen-durable`
- `GET /internal/v1/market-intelligence/screening-runs/{runId}`

The adapter writes only `analytics.*`, does not rerun formulas during reads,
and never allows AI narrative fields to participate in ranking.
