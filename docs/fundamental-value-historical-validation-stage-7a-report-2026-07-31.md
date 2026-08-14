# Fundamental Value Historical Validation Stage 7A Report

Date: 2026-07-31

## Decision

Stage 7A read-only audit is complete. The migration-free offline portion of
Stage 7B is implemented as an isolated candidate. Live acquisition, snapshot
assembly, outcome evaluation, and any evidence-label change remain closed
pending master acceptance.

No formula, assumption, applicability route, missing-state behavior, risk-cap
ceiling, V22/V23 migration, Java API, frontend contract, or Quant Trading
artifact was changed. No provider or network request was made.

## Current implementation audit

Stages 1-6 provide the strict Python contract and deterministic core, exact
34-operand V22 assembly, empty-by-default governed producer registry, V23
immutable persistence and replay, internal FastAPI route, validating Spring
projection, and read-only Next.js workspace. Production V22 maps seven direct
operands. It does not supply all tax, D&A, working-capital, EBITDA,
distribution, multi-period stability, assumption, downside, debt-maturity, or
capital-allocation evidence. The production producer registry is empty.

Therefore mature generic assemblies remain `MISSING`, no real assessment is
usable, and `modelEvidenceLabel` remains `NOT_VALIDATED`. The existing V23
validator correctly refuses another label. Stage 7 results must remain a
separate validation artifact until an independent Stage 7E decision approves a
versioned successor.

Existing generic historical modules are design references only. Their older
contracts do not contain the Stage 7 revision/availability boundary, and their
IID bootstrap cannot be used for overlapping annual three-year observations.

## Offline Stage 7B ownership

Added files:

- `analysis-python/src/equity_analysis/fundamental_value/historical_validation_v1.py`
- `analysis-python/src/equity_analysis/fundamental_value/historical_provider_v1.py`
- `analysis-python/src/equity_analysis/fundamental_value/historical_execution_v1.py`
- `analysis-python/tests/test_fundamental_value_historical_validation_v1.py`
- `analysis-python/tests/test_fundamental_value_historical_provider_v1.py`
- `analysis-python/tests/test_fundamental_value_historical_execution_v1.py`
- `docs/fundamental-value-historical-validation-v1.md`
- this report

No accepted Stage 1-6 implementation file was edited by Stage 7.

## Universe and date freeze

The universe mechanism requires exactly 200 explicit curated rows, then uses a
domain-separated sealed seed to select exactly three large, four mid, and three
small names in each of eleven GICS sectors from a hash-bound non-curated pool.
Stable security IDs, source ordinal, source snapshot ID/hash, role, sector, and
capitalization bucket are bound into the manifest. Cross-sector or cross-size
backfill is forbidden. The result must contain 310 unique IDs. The benchmark
manifest is separate and contains SPY plus eleven sector ETFs.

The date mechanism requires a completed-session calendar and selects one
SHA-256-ranked Q2 session per year from 2015 through 2023. It adds separately
labelled adverse-entry diagnostics on 2018-09-20, 2020-02-19, and 2022-01-03.
The primary and stress sets must be unique and cannot be combined. The bound
outcome cutoff must prove that the 2023 node matures through 756 completed
sessions after the first post-cutoff entry session.

## Batch schedule and preflight

- Batch 0: SPY, eleven sector ETFs, and one equity canary from each of eleven
  sectors. Maximum 91 EODHD physical attempts, weight 190, retry zero. Optional
  Yahoo corroboration has a maximum 23 wrapper calls.
- Remaining acquisition: eleven isolated batches of 25 and one batch of 24.

Canary reuse remains `BLOCKED_EXECUTION_CONTRACT_INCOMPLETE`; no receipt or
idempotency claim exists before completed Batch 0 evidence. A batch may never
exceed 25 equities.

The provisional exact EODHD plan is:

- one `/api/exchange-symbol-list/US?delisted=1&fmt=json` snapshot request,
  provisional weight one;
- per equity: fundamentals weight 10; EOD, dividends, splits, and historical
  market capitalization weight one each, totaling five attempts and weight 14;
- per benchmark: EOD, dividends, and splits, totaling three attempts and weight
  three;
- full ceiling including the source snapshot: 1,587 physical attempts and
  configured weight 4,377;
- retry zero and minimum unused daily allowance reserve 20,000.

The master must verify current entitlement, endpoint semantics, and weights
before approval. The current EODHD fundamentals adapter has no historical
`availableAt`; its values can only be labelled
`CURRENT_REVISION_APPROXIMATION`, never strict PIT. `fetch_daily_prices()` also
performs a hidden fundamentals call, so Stage 7 must use exact journaled request
identities or explicit deduplication.

## Test matrix

The reachable offline regressions cover deterministic 310 universe selection,
source/hash and identity refusal, Q2/stress date freezing, calendar maturity,
phase-specific provider budgets, master-frozen preflight authenticity,
timezone and evidence-lineage refusal, intentionally blocked runner/Yahoo/
canary execution, four-target predictor and quintile replay, exact 310 terminal
coverage, missing-population refusal, matched sector strata, observed-only
metric denominators, annualization domains, and descriptive date statistics.
They do not claim receipt replay or request idempotency while the provider
runner is intentionally `BLOCKED_EXECUTION_CONTRACT_INCOMPLETE`.

The master-provided offline toolchain runs against the worktree source with
pytest cache and bytecode disabled and a bounded temporary base directory.
The final terminal-coverage matrix reports 45 passing tests and Ruff reports no
findings. `git diff --check` also passes. No dependency download occurred.

## Stop conditions and unresolved decisions

Live execution is blocked until the master accepts all of the following:

1. The exact curated 200 rows and a frozen, licensed source snapshot with
   stable IDs, GICS lineage, capitalization inputs, lifecycle status, and
   delisted/acquired/failed coverage. No such 310-security source is currently
   present in the repository.
2. Master acceptance of each target-specific predictor mapping. The interface
   freezes deterministic 20/60/20 quintiles and durable-ID tie-breaking for
   company quality, security attractiveness, expected return, and downside,
   while forbidding risk cap and any invented composite score.
3. Calendar snapshot/hash, decision cutoff and entry convention, 252/504/756
   exit convention, outcome cutoff, delisting/acquisition return policy,
   share-class policy, sector ETF mapping, currency policy, and action/adjustment
   reconciliation.
4. Turnover and transaction-cost policy, including explicit behavior when
   liquidity is missing. Missing liquidity cannot mean zero cost.
5. Whether the nine dependent date portfolios remain descriptive evidence or
   use a separately preregistered block/randomization method. IID stock-row
   inference and IID bootstrap are prohibited.
6. Current EODHD entitlements, endpoint weights, billed-call reconciliation,
   and the exact hard billed-call multiplier/ceiling.

Execution must stop on authentication, rate limiting, transport ambiguity,
schema/semantic/hash drift, lease/journal conflict, PIT breach, universe drift,
quota anomaly, incomplete benchmark/action evidence, silent population
attrition, specialized-company generic routing, or an unknown physical
request. An unknown request is never automatically rerun.

Stage 7C is not authorized by this report.
