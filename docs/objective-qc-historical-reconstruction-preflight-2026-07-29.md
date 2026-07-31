# Objective QC Historical Reconstruction Preflight

## Decision

The first read-only PostgreSQL preflight for
`OBJECTIVE-QC-HISTORICAL-RECONSTRUCTION-v1.0.0` is **blocked before
scoring**.

No Objective score, cohort rank, historical signal, or Forward
Decision-Quality Validation event was produced. No provider request, database
write, migration, commit, push, or deployment occurred.

The stop is required by the frozen Objective Rating QC contract. Existing
local evidence cannot yet reconstruct a historical decision-time cohort
without inventing period semantics or relaxing the cohort minimum.

## Frozen execution design

- Random seed: `20260729`.
- Candidate dates: last stored benchmark session in each month.
- Sampling: deterministic and stratified.
- Recent stratum: 3 to 9 months before the anchor.
- Medium stratum: 1 to 3 years before the anchor.
- Older stratum: 4 to 10 years before the anchor.
- Planned outcome horizons: 126 and 252 completed benchmark sessions.
- Objective formula and weights: unchanged `QC-v1.0.0`.
- General-company normalization minimum: unchanged at 100.
- Initial universe mode: current-universe retrospective only.
- Availability mode: conservative lag only where semantics are already
  proven. A lag may delay an observation; it cannot create a missing period
  start, convert YTD to a discrete quarter, or create historical membership.

## Local PostgreSQL evidence

The preflight used aggregate metadata only and did not export licensed
provider values.

| Evidence | Local coverage |
|---|---:|
| SPY benchmark sessions | 260 |
| SPY stored date range | 2025-07-16 to 2026-07-28 |
| Securities with accepted stored price history | 59 |
| Securities with stored fundamental facts | 56 |
| Stored fundamental facts through the anchor | 157,641 |
| Fundamental facts with `period_start` | 0 |
| Facts with proven Q1/Q2/Q3/Q4 discrete-quarter semantics | 0 |
| Securities with market value at or before the recent decision boundary | 0 |

The stored fundamental values are not discarded. They remain useful for
current-snapshot work. They cannot be used as historical QC duration operands
until period starts and discrete-quarter semantics are proven.

## Deterministic date plan

| Stratum | Available months | Required random samples | Sealed samples |
|---|---:|---:|---:|
| Recent | 7 | 6 | 0 |
| Medium | 1 | 6 | 0 |
| Older | 0 | 6 | 0 |

The generic historical sampler is the single source of truth for execution
dates. It requires the complete fixed-seed stratified plan to be sealed before
any outcome is inspected. Because the medium and older bands cannot satisfy
the sample request, the Objective preflight does not create a competing
partial sample. The local price range could support a small ad hoc 126-session
diagnostic, but that is not the approved stratified Objective plan and was not
run.

## Exact blockers

1. `DISCRETE_QUARTER_SEMANTICS_UNAVAILABLE`
2. `FROZEN_QC_COHORT_TOO_SMALL`
3. `FUNDAMENTAL_PERIOD_START_UNAVAILABLE`
4. `HISTORICAL_MARKET_VALUE_UNAVAILABLE`
5. `HISTORICAL_MEMBERSHIP_UNPROVEN`
6. `MEDIUM_DECISION_DATES_UNAVAILABLE`
7. `OLDER_DECISION_DATES_UNAVAILABLE`
8. `OUTCOME_126_SESSION_UNAVAILABLE`
9. `OUTCOME_252_SESSION_UNAVAILABLE`

The frozen general-company normalization minimum is 100, while the local
intersection can contain at most 56 securities before per-factor missing-data
checks. That minimum was not changed to fit the available sample.

## Implementation

The read-only preflight is implemented in:

`analysis-python/src/equity_analysis/historical_validation/objective_qc_reconstruction_v1.py`

It provides:

- an Objective-specific adapter over the shared fixed-seed historical sampler;
- explicit 126/252-session support metadata without reading outcome values
  during date selection;
- aggregate PostgreSQL evidence inventory with no numeric provider values;
- fail-closed blocker classification;
- guards that prevent lowering the frozen QC cohort minimum.

`historical_validation/sampling_v1.py` remains the only execution sampler.
The Objective module only audits whether enough local evidence exists to use
that sealed plan. This is an input-reconstruction preflight, not a substitute
scoring engine.
When evidence becomes sufficient, the next builder must call the existing
Objective normalization and QC formula implementation rather than duplicate
or modify it.

## Minimum honest next step

Before historical QC scoring can run, the repository needs a versioned,
offline historical evidence set that provides:

- at least 100 comparable mature-company securities per scoring slice, or a
  previously frozen valid sector cohort of at least 30;
- period starts and proven discrete-quarter semantics for every required
  duration operand;
- historical market value or another frozen valuation denominator available
  at the simulated decision time;
- enough price history for the requested outcomes;
- explicit current-universe retrospective labeling until dated membership and
  delisted outcomes are available.

An approximate-data run may use conservative publication lags and current
universe membership, but it must remain labeled
`CONSERVATIVE_LAG`/`CURRENT_UNIVERSE_RETROSPECTIVE`. It still may not invent
missing financial-period semantics or lower the frozen normalization
threshold.
