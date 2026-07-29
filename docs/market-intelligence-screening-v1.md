# Market Intelligence and Screening v1

Date: 2026-07-28

## Decision and Scope

`MARKET-INTELLIGENCE-SCREENING-v1.0.0` is the versioned research-profile and
screening layer for United States equities. It assembles durable security facts,
classification, comparable cohorts, valuation evidence, and already-versioned
deterministic model outputs into one explainable profile.

It does not introduce a universal stock score or change Objective Rating v1,
`TACTICAL-SIGNAL-v2.1.0`, or `LONG-HORIZON-RESEARCH-v1.0.0`. It does not fetch
provider data, write analytics tables, choose portfolio weights, or execute trades.

## Information Boundaries

| Category | Contract treatment |
| --- | --- |
| Security master | Durable ID, symbol, issuer, exchange MIC, currency, instrument type, CIK, and provider durable ID. |
| Classification | Dated taxonomy, sector, industry, normalized company type, and source lineage. |
| Observed facts | Typed `VALID`, `MISSING`, `INVALID`, or `NOT_APPLICABLE` values with lineage. |
| Comparable cohorts | Explicit identity, taxonomy, company type, optional size band, member count, and minimum count. |
| Objective Rating v1 | Existing status and separate quality and valuation scores; provider acceptance alone is never sufficient. |
| Tactical views | Separate one-week, one-month, and three-month `TACTICAL-SIGNAL-v2.1.0` views. |
| Long-horizon view | Separate 12-month-plus `LONG-HORIZON-RESEARCH-v1.0.0` view. |
| Valuation evidence | Objective valuation, long-horizon valuation, and own-history percentile remain visible. |
| AI narrative | Optional cited narrative that cannot alter facts, scores, eligibility, ranks, weights, or trades. |

Non-valid facts cannot carry a value. This prevents missing data from becoming
zero or a neutral score.

## Internal API and Ranking

Python exposes versioned internal durable endpoints for:

- snapshot profile assembly;
- sealed screening-run creation and result pagination;
- immutable and latest profile reads;
- security search; and
- facets.

Spring Boot owns user-facing workflows and publishes these under
`/api/v1/market-intelligence`. The browser never calls the Python service
directly. These endpoints accept stored normalized evidence and model results
and perform no provider calls. Filters cover sector, industry, company type,
symbol, and horizon. Ranking metrics are Objective quality, Objective
valuation, the three tactical horizons, 12-month-plus long horizon, and buying
opportunity.

Buying opportunity v1 is the unweighted arithmetic mean of three explicitly
available components: Objective Rating valuation, long-horizon valuation, and
own-history valuation percentile. All three must be valid. It is research
evidence, not a price target or assurance against loss.

## Ranking Eligibility

A durable partial profile can be useful while excluded from ranking. Ranking
requires:

1. effective sector and industry classification;
2. valid market capitalization, latest price, and average daily dollar volume;
3. all four horizon records present, available by the cutoff, and not expired;
4. Objective Rating status `SCORED` with both dimension scores;
5. valid valuation evidence; and
6. at least one comparable cohort meeting its declared minimum count.

Every exclusion is retained as a reason code. Provider `PASS` is not an input.

## Acceptance Gates

| Gate | Required evidence | Honest v1 decision |
| --- | --- | --- |
| Sector coverage | Count and percentage of the intended universe with effective sector and industry, grouped by taxonomy. | `PASS` only when every ranked security is classified and the predeclared target is met. |
| Security coverage | Intended universe, durable-profile, partial-profile, and exclusion counts. | A fixture or provider-acceptance set is not production coverage. |
| Freshness | Cutoff, fact `availableAt`, model `asOf` and `effectiveAt`, and tactical `expiresAt`. | Unavailable or expired evidence is excluded; report maximum age by domain. |
| Ranking eligibility | Eligible count by metric plus formula, cohort, classification, and freshness exclusions. | Algorithm correctness can pass with zero eligible securities, but the result must say `NO_ELIGIBLE_RESULTS`. |
| Explainability | Metric, source model/version, hashes, fact states, lineage, and exclusion rules. | 100% of ranked records must pass. |

The response reports observed counts. Production target percentages belong to
the run configuration so this code cannot silently change them.

## Provider Boundary

Provider-native payloads remain behind normalization adapters. EODHD is the
current bounded licensed source. Yahoo/yfinance is allowed only for development
or bounded cross-checking. Twelve Data remains supported by the existing
provider-neutral boundary, and Intrinio can later implement the same capability
and lineage contracts. The committed fixture contains synthetic values only.

## Persistence

V17 and the Python persistence adapter implement immutable, append-oriented
storage with the following fields. See
`market-intelligence-screening-persistence-v1.md` for the reconciled mapping
to existing V1-V16 evidence and durable internal endpoints.

### `analytics.security_profile_snapshot`

`profile_id uuid`, `contract_version text`, `security_id uuid`,
`snapshot_as_of timestamptz`, `symbol text`, `issuer_name text`,
`exchange_mic text`, `currency char(3)`, `instrument_type text`, `cik text`,
`durable_provider_id text`, `profile_state text`, `ranking_state text`,
`objective_rating_status text`, `objective_rating_version text`,
`objective_quality_score numeric(7,4) null`,
`objective_valuation_score numeric(7,4) null`, `input_payload_hash text`,
`created_at timestamptz`. Unique:
`(security_id, snapshot_as_of, contract_version, input_payload_hash)`.

### `analytics.security_classification_observation`

`classification_id uuid`, `security_id uuid`, `taxonomy_version text`,
`sector_code text`, `sector_name text`, `industry_code text`,
`industry_name text`, `company_type text`, `effective_at timestamptz`,
`available_at timestamptz`, `provider_code text`,
`provider_schema_version text`, `parser_version text`,
`source_reference text`, `source_content_hash text`, `retrieved_at timestamptz`.

### `analytics.security_profile_fact`

`profile_id uuid`, `fact_name text`, `fact_state text`,
`value_decimal numeric null`, `value_text text null`,
`value_integer bigint null`, `value_boolean boolean null`, `reason text null`,
`unit text null`, `currency char(3) null`. Enforce exactly one typed value for
`VALID` and no value otherwise.

### `analytics.security_profile_fact_lineage`

`profile_id uuid`, `fact_name text`, `lineage_ordinal integer`,
`provider_code text`, `provider_schema_version text`, `parser_version text`,
`source_reference text`, `source_content_hash text`,
`effective_at timestamptz null`, `available_at timestamptz`,
`retrieved_at timestamptz`.

### `analytics.comparable_cohort_snapshot`

`cohort_snapshot_id uuid`, `profile_id uuid`, `cohort_id text`,
`taxonomy_version text`, `sector_code text`, `industry_code text null`,
`company_type text`, `size_band text null`, `eligible_member_count integer`,
`minimum_member_count integer`, `is_sufficient boolean`.

### `analytics.market_intelligence_horizon_view`

`profile_id uuid`, `horizon text`, `model_id text`, `model_version text`,
`view_state text`, `model_as_of timestamptz`, `effective_at timestamptz`,
`expires_at timestamptz null`, `score numeric(7,4) null`, `label text`,
`input_hash text`, `evidence_hash text`, `missing_inputs jsonb`,
`explanation jsonb`. Enforce a score only for `ASSESSED`.

### `analytics.market_intelligence_valuation_evidence`

`profile_id uuid`, `evidence_state text`, `evidence_as_of timestamptz`,
`objective_valuation_score numeric(7,4) null`,
`long_horizon_valuation_score numeric(7,4) null`,
`own_history_percentile numeric(7,4) null`, `limitations jsonb`.

### `analytics.market_intelligence_ranking_exclusion`

`profile_id uuid`, `reason_ordinal integer`, `reason_code text`.

### `analytics.market_intelligence_screening_run`

`run_id uuid`, `contract_version text`, `as_of timestamptz`,
`filter_payload jsonb`, `rank_metric text`, `sort_direction text`,
`result_limit integer`, `input_snapshot_hash text`, `eligible_count integer`,
`excluded_count integer`, `sector_coverage_count integer`,
`security_coverage_count integer`, `fresh_profile_count integer`,
`explainable_count integer`, `gate_status text`, `created_at timestamptz`.

### `analytics.market_intelligence_screening_result`

`run_id uuid`, `profile_id uuid`, `rank integer`, `metric_value numeric`,
`sector_code text`, `industry_code text`. Unique `(run_id, rank)` and
`(run_id, profile_id)`.

### `analytics.market_intelligence_ai_narrative`

`profile_id uuid`, `status text`, `narrative text null`,
`source_references jsonb`, `generated_at timestamptz null`,
`prompt_version text null`, `model_version text null`, `confidence text null`,
`may_affect_deterministic_fields boolean`. Enforce
`may_affect_deterministic_fields = false`; this table must never participate in
deterministic ranking calculations.

## Deferred Work

- Production authentication replacing closed-test identity.
- Deployed scheduled snapshot orchestration.
- Completion of the stopped bounded provider refresh.
- Any new industry-specific scoring methodology.
