# Model Validation Master Plan v2

Date: 2026-07-29

## Objective

Redesign and honestly evaluate two independent deterministic research models:

- `TACTICAL-SIGNAL-v2.2.0` for one-week, one-month, and three-month
  speculation and entry timing;
- `LONG-HORIZON-RESEARCH-v1.1.0` for twelve-month-plus company quality,
  financial strength, capital allocation, valuation, expected-return range,
  and permanent-loss risk.

The work is successful if it produces reproducible evidence and an honest
terminal status. A favorable backtest is not a required outcome.

## Practical value and finite evaluation

The validation objective is measurable decision usefulness, not perfect
prediction accuracy. Short-horizon speculation is especially noisy, so a
model may still be useful when individual calls are wrong if it consistently
improves ranking, entry timing, expected payoff, downside control, abstention,
or decision consistency relative to simple alternatives.

Each frozen model version receives one planned retrospective evaluation. The
result is recorded without changing formulas, weights, thresholds, universe,
costs, benchmarks, or missing-data behavior in response to that result. A new
model version is permitted only for a demonstrated implementation defect,
documented methodology defect, justified missing factor, or evidence that a
specific design assumption is systematically harmful. The successor must use
walk-forward, later historical, or prospective evidence and must not relabel
previously observed outcomes as an untouched holdout.

Practical-value reporting combines absolute and benchmark-relative returns,
rank information coefficient, top-minus-bottom spread, directional hit rate,
upside and downside capture, maximum adverse and favorable excursion,
drawdown, volatility, risk adjustment, turnover, transaction costs, coverage,
abstention, and stability across time, sector, size, and market regime. No
single accuracy statistic determines acceptance.

## Non-negotiable boundaries

- Previously observed 2014-2026 results are development evidence. They are not
  an untouched holdout.
- Missing, stale, invalid, excluded, and not-applicable inputs remain explicit.
- Provider presence or ingestion success does not imply scoring eligibility.
- No AI output may alter a deterministic score, classification, risk gate, or
  rank.
- No model output is an automatic order, portfolio weight, or promise of
  return.
- No historical result may be described as proof of future performance.
- Objective Rating v1 remains an independent model and is not silently
  reinterpreted.

## Main-controller ownership

The main controller owns:

- repository and contract reconciliation;
- workstream boundaries and conflict resolution;
- model-freeze acceptance;
- validation claim ceilings;
- provider and migration approval gates;
- cross-workstream test acceptance;
- final documentation and release readiness.

Subtasks may implement isolated modules, but a subtask report is not phase
acceptance. The main controller independently verifies source, tests, hashes,
and evidence before advancing the plan.

When work can be separated safely, the main controller must use independent
project tasks for Historical Tactical Validation, Long Horizon Historical
Validation, Benchmark/Persistence/Forward DQV Contracts, and
Acceptance/PostgreSQL/CI/Security. Each task receives bounded file ownership,
frozen shared contracts, tests, artifacts, and stop conditions. Every task
must report modified files, exact test results, artifact hashes, limitations,
blockers, and a recommended next action back to the main controller. A
delegated task may not change shared formulas, approve its own methodology,
make unapproved provider requests, commit, push, deploy, or claim validation.

## Workstream A: validation governance

Deliver:

1. A versioned governance contract that distinguishes:
   - availability evidence;
   - universe evidence;
   - outcome dependence;
   - evaluation role;
   - price and corporate-action evidence.
2. A claim ceiling derived from the weakest evidence dimension.
3. Model-freeze records that bind:
   - formulas and weights;
   - input schema and applicability;
   - missing-data policy;
   - benchmark and cost contracts;
   - universe and sampling;
   - acceptance thresholds;
   - source-artifact hashes;
   - seed, maximum horizon, purge, and embargo.
4. Terminal states that allow `MIXED`, `NOT_VALIDATED`,
   `INSUFFICIENT_EVIDENCE`, and `BLOCKED_BY_DATA`.

## Workstream B: Tactical v2.2

The model must:

- evaluate continuation and mean reversion independently for every horizon;
- allow `NONE` and `CONFLICT`, rather than forcing a thesis;
- separate opportunity, entry value, and actionability;
- use market and sector regime plus relative strength;
- make falling-knife, chase, volatility, liquidity, and event risks explicit;
- apply non-compensating gates to dangerous setups;
- use completed sessions only;
- bind all inputs through a deterministic hash;
- expire after one additional completed session;
- exclude AI from the deterministic contract.

Historical diagnostics must report one-week, one-month, and three-month
outcomes separately. Overlapping observations are diagnostic only.

## Workstream C: Long Horizon v1.1

The model must separately report:

- business quality;
- financial strength;
- capital allocation;
- valuation and entry;
- a low, base, and high expected-return range;
- permanent-loss and downside risk;
- sector-relative evidence;
- evidence confidence.

It must distinguish a good company from an attractively priced security.
Evidence confidence must never improve economic scores. The model must not
publish a default cross-sectional ranking until a target-specific ranking
contract is frozen and validated.

Banks, insurers, REITs, resource companies, biotechnology companies, and
recent IPOs must not be coerced into the general-company model.

## Workstream D: unified historical evaluation

Use chronological nested walk-forward evaluation with:

- expanding development windows;
- sealed inner and outer windows;
- purge and embargo of at least 60 sessions for Tactical and 252 sessions for
  Long Horizon;
- non-overlapping formal decisions;
- separately labeled overlapping diagnostics;
- block bootstrap for dependent observations;
- no ordinary IID bootstrap in a formal gate.

Required benchmarks are:

- SPY;
- sector benchmark;
- equal-weight universe;
- pure momentum;
- pure value;
- pure quality.

Unavailable benchmark evidence remains `MISSING`; it is never replaced by
zero return or SPY without disclosure.

Required metrics include:

- information coefficient;
- top-minus-bottom spread;
- top-minus-benchmark return;
- maximum drawdown;
- downside capture;
- turnover;
- coverage;
- missing, invalid, excluded, and abstention counts;
- transaction-cost and liquidity-sensitive cost effects.

Current-universe and current-revision history can support development
diagnostics only. It cannot establish a validation-eligible claim.

## Workstream E: immutable decision snapshots

Each prospective decision snapshot must bind:

- security public ID and universe version;
- decision cutoff and completed-session as-of time;
- model, feature, input-schema, and freeze versions;
- source and evidence hashes;
- every deterministic dimension and terminal state;
- missing and excluded reasons;
- benchmark, cost, and sector-mapping versions;
- AI status separately with
  `may_affect_deterministic_fields=false`;
- a canonical snapshot hash and idempotency key.

The complete frozen population must receive a terminal state, including
abstentions and insufficient-data outcomes.

## Workstream F: Forward Decision-Quality Validation v2

Forward v2 begins only after both model freezes exist.

It must:

- enroll sealed daily decisions prospectively;
- prevent outcome data from changing a prior snapshot;
- observe one-week, one-month, three-month, and twelve-month-plus horizons;
- preserve no-setup and missing-data decisions;
- apply the frozen benchmark and cost policies;
- generate append-only outcomes and superseding reports;
- report operational completeness separately from model quality;
- require naturally matured samples before a validation claim.

Existing Forward v1 records and contracts remain immutable.

## Database decision gate

PostgreSQL V17 can store the existing Market Intelligence profile and four
horizon labels, but it requires a numeric score for an assessed horizon.
Long Horizon v1.1 intentionally provides no default ranking score. PostgreSQL
V11 Forward Validation also supports only 5, 20, and 60-session ranked
top/bottom candidate signals.

Before implementing durable Long Horizon v1.1 snapshots or 252-session Forward
v2 outcomes, the main controller must determine whether an append-only V18 is
required. No migration is added implicitly.

## Phases and gates

### Phase 1: contract correction

- Implement governance, Tactical v2.2, Long Horizon v1.1, and the unified
  walk-forward protocol.
- Run focused and backward-compatibility tests.

Gate: deterministic contracts pass and no historical outcome has influenced
the frozen version.

### Phase 2: model freeze

- Generate and verify Tactical and Long Horizon freeze artifacts.
- Record the observed-evidence cutoff and absence of an untouched holdout.

Gate: every referenced source and policy hash is valid.

### Phase 3: historical development diagnostics

- Replay only from existing verified caches and database evidence.
- Make zero provider requests unless separately approved.
- Produce explicit missing-benchmark and blocked-data states.

Gate: complete population accounting, no leakage claim, and reproducible
results.

### Phase 4: persistence and interface integration

- Decide the V18 boundary.
- Add versioned internal Python and public Java contracts.
- Display deterministic assessment, evidence state, and AI narrative
  separately in Next.js.

Gate: cross-language contract tests and append-only persistence tests pass.

### Phase 5: prospective validation

- Seal daily decisions.
- Observe naturally matured outcomes.
- Publish interim reports without declaring an edge prematurely.

Gate: the preregistered minimum sample, evidence ceiling, and acceptance
thresholds are satisfied.

### Phase 6: release acceptance

Run:

- complete Python tests and Ruff;
- Java contract, client, and controller tests;
- frontend unit, lint, build, and route tests;
- PostgreSQL clean and upgrade-path tests if a migration is approved;
- duplicate enrollment and resume tests;
- clean-clone analytics tests;
- full-history Gitleaks and focused secret scans.

No commit, push, deployment, or live provider request is implied by this plan.

## Stop conditions

Stop and return to the main controller when:

- a formula, threshold, or universe would change after outcome inspection;
- a required benchmark or PIT field is unavailable;
- a frozen hash or population identity changes;
- a request budget or provider journal cannot be reconciled;
- an existing migration cannot express the new immutable contract;
- a result would require treating missing evidence as neutral;
- a proposed positive claim exceeds the evidence claim ceiling.

## Completion criteria

This objective is complete only when:

1. both deterministic model versions are frozen and reproducible;
2. historical evidence is labeled according to its real limitations;
3. benchmark, cost, risk, coverage, and abstention metrics are complete;
4. immutable prospective decision snapshots can be created idempotently;
5. Forward v2 can mature all four horizons without changing past decisions;
6. AI remains explanatory only;
7. all applicable tests and security checks pass;
8. each model receives an evidence-supported terminal validation status.
