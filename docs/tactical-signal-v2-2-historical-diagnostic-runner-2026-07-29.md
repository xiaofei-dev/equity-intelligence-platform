# Tactical Signal v2.2 Historical Diagnostic Runner

Date: 2026-07-29

## Purpose

`TACTICAL-V2.2-HISTORICAL-DIAGNOSTIC-v1.0.0` is an offline, development-only
walk-forward diagnostic for `TACTICAL-SIGNAL-v2.2.0`. It does not change the
signal, tune a parameter, perform a provider request, create an investment
recommendation, or establish a statistical edge.

The runner is implemented in
`analysis-python/src/equity_analysis/historical_validation/tactical_v22_diagnostic.py`.
It directly uses:

- `HISTORICAL-VALIDATION-PROTOCOL-v2.0.0`; and
- `NESTED-WALK-FORWARD-v2.0.0`.

The runner does not use the legacy Tactical v2.1 walk-forward evaluator.

## Freeze binding

Execution requires the accepted Tactical v2.2 freeze:

- artifact:
  `docs/generated/tactical-v2-2-model-freeze.json`;
- artifact content hash:
  `A596080CD7936A6881A38E759C597934DAE1125EC83026DF6DB0434F6FE31910`;
- freeze-record hash:
  `D6E3EDB1160856ADE700C37D42A4C9E2CDDA3B88A4080DBC8ED73354B4C5BF99`;
- file SHA-256:
  `5D541315F62990BC5F44A4E421F404D737F6FFCF039E586B18BA362A113DC49F`;
- frozen at:
  `2026-07-30T00:45:00Z`.

The runner verifies the file hash, canonical artifact content hash,
freeze-record hash, and model version before it may read outcomes. A missing
or changed freeze returns a `BLOCKED` report with no horizon metrics.

## Evidence and claim boundary

All historical intervals currently available to the project have already been
observed. Every result therefore records:

- `evaluationRole=DEVELOPMENT_OBSERVED`;
- `claimCeiling=DIAGNOSTIC_ONLY`;
- `untouchedHoldoutAvailable=false`;
- `availability=CURRENT_REVISION_RETROSPECTIVE`;
- `universe=CURRENT_UNIVERSE_RETROSPECTIVE`; and
- `priceAction=EX_POST_TOTAL_RETURN_ADJUSTED`.

Neither purging nor chronological outer folds can turn observed development
data into an untouched holdout. Only future sealed decisions can supply
prospective validation evidence.

## Source boundary

The loader reads only the immutable local Yahoo cache:

`storage/historical-validation/yahoo-daily-price-cache-v1`

For the manifest and every payload it verifies:

- canonical content hash;
- file SHA-256;
- symbol identity;
- bar count; and
- complete-manifest status.

The loader has no network client. Historical price values stay in controlled
local storage and are not copied into a Git-safe report.

## Walk-forward schedules

The diagnostic constructs two plans from the same shared completed-session
calendar.

### Conservative non-overlapping schedule

- horizons: 5, 20, and 60 completed sessions;
- initial development: 252 sessions;
- inner validation: 60 sessions;
- purge: 60 sessions;
- embargo: 60 sessions;
- outer evaluation: 60 sessions;
- decision spacing: 60 sessions; and
- fold step: 120 sessions.

Using 60-session spacing for all three horizons is deliberately conservative.
It guarantees that the 5-, 20-, and 60-session outcome windows do not overlap
between selected decision dates.

### Overlapping diagnostic schedule

- the same 5-, 20-, and 60-session horizons;
- the same development, purge, embargo, and outer windows;
- one-session decision spacing; and
- 60-session fold step.

These observations are labeled `OVERLAPPING_DIAGNOSTIC`. They are reported
separately and cannot enter a formal acceptance gate.

## Complete frozen population

Every decision date must retain one terminal state for every frozen security:

- `ASSESSED`;
- `MISSING`;
- `INVALID`;
- `STALE`;
- `NOT_APPLICABLE`;
- `SPECIALIZED_MODEL_REQUIRED`; or
- `EXCLUDED`.

The runner validates the terminal population through the shared protocol.
Silent deletion or favorable-subset evaluation is prohibited.

## Benchmark contract

Every preflight and result contains all six benchmark records with one explicit
availability state:

1. SPY;
2. dated sector benchmark;
3. equal-weight frozen universe;
4. pure momentum;
5. pure value; and
6. pure quality.

An available benchmark requires a versioned identifier and SHA-256 evidence
hash. `MISSING`, `STALE`, `INVALID`, and `NOT_APPLICABLE` are retained as
states with reasons. Missing benchmarks never become zero returns.

For a complete diagnostic:

- SPY uses the same next-session-open to terminal-close execution;
- sector uses the dated sector benchmark associated with each selected
  security;
- equal weight uses the complete assessed frozen population;
- pure momentum uses the top quintile of trailing 60-session return;
- pure value uses an externally supplied, hash-bound point-in-time score; and
- pure quality uses an externally supplied, hash-bound point-in-time score.

All portfolio benchmarks use the same execution and liquidity-sensitive cost
policy. The runner does not invent value or quality scores from price.

## Cost and turnover

The implementation binds the frozen cost contract:

- fixed round trip: 2 basis points;
- base one-way slippage: 1 basis point;
- square-root participation impact: 25 basis points at full participation;
- maximum one-way impact: 50 basis points; and
- positive average daily dollar volume is mandatory.

The report retains total and average round-trip cost rates. Average turnover is
the decision-to-decision one-way selection replacement ratio. A transition
between cash and a non-empty selection is full turnover. Repeated episode
costing is intentionally conservative and is not presented as optimized
execution.

## Metrics

The runner reports each schedule and horizon separately:

- decision count;
- assessed security count;
- actionable episode count;
- complete terminal-population counts;
- coverage;
- mean cross-sectional rank information coefficient;
- top-minus-bottom net return;
- average gross and net model returns;
- hit rate;
- turnover;
- total and average costs;
- maximum drawdown;
- downside capture versus SPY;
- return volatility;
- worst period return;
- average maximum adverse excursion;
- average maximum favorable excursion; and
- average net return and model-minus-benchmark return for every available
  benchmark.

Nullable metrics remain null when their mathematical evidence does not exist.
They are not replaced with zero merely to make a report complete.

## Current offline preflight result

The accepted freeze and the existing 2014-2026 Yahoo cache can be
hash-verified, but the outcome diagnostic remains `BLOCKED`.

The current cache contains 55 security series plus SPY. It does not contain:

- dated sector ETF histories and a hash-bound historical sector mapping;
- point-in-time deterministic event-risk evidence for each security and
  decision date;
- point-in-time pure-value benchmark scores; or
- point-in-time pure-quality benchmark scores.

SPY, equal-weight, and pure-momentum capability can be identified as
`AVAILABLE`. Sector, pure value, and pure quality remain `MISSING`. Because
Tactical v2.2 requires sector and deterministic event evidence, the runner
does not execute a partial outcome replay or substitute neutral inputs.

This stop is an evidence result, not a model failure. A future task may provide
the missing hash-bound evidence or explicitly approve a narrower diagnostic
contract under a new version. This implementation does not relax the accepted
v2.2 freeze.

## Immutable blocked terminal artifact

The accepted real-cache preflight is sealed in the Git-safe terminal artifact:

`docs/generated/tactical-v2-2-historical-diagnostic-terminal-2026-07-29.json`

- terminal status: `BLOCKED_BY_DATA`;
- evaluation role: `DEVELOPMENT_OBSERVED`;
- untouched holdout: `false`;
- claim ceiling: `DIAGNOSTIC_ONLY`;
- artifact content hash:
  `E389CB70CEAB19854DB13B22652CC547C4618B12F4E28947DB03297D59632C7A`;
- file SHA-256:
  `43FCFCFB4066BDFCF530308C8B04DDC409B6D6E6CFDB4DA0098424A9A207B7A0`;
- network requests: `0`; and
- parameter tuning: `false`.

The artifact binds the accepted model freeze, protocol hashes, walk-forward
plan hashes, the verified Yahoo manifest and payload count, and the verified
66-security universe. Its terminal population is complete:

- 55 Primary or Reserve candidates are `MISSING`, because the diagnostic
  cannot legally execute without dated sector mapping, event evidence, pure
  value, and pure quality evidence;
- 2 Reference-only securities are `NOT_APPLICABLE`; and
- 9 frozen exclusions are `EXCLUDED` with their original reason.

Every population record retains the deterministic stable public security ID,
symbol, role, historical-price cache state, terminal state, and reason profile.
The repeated reason profiles are defined once at population level so the
artifact remains compact without losing per-security accountability.

The terminal artifact contains no licensed price values, model scores, outcome
returns, horizon metrics, or performance claim. It is a durable proof that the
accepted runner stopped before outcome evaluation rather than silently
discarding unavailable securities or benchmarks.

## Validation completed in this task

Offline tests cover:

- missing freeze blocking before outcomes;
- freeze file, content, record-hash, and version binding;
- all-six-benchmark explicit-state enforcement;
- missing benchmark preservation without zero substitution;
- shared protocol and nested walk-forward plan construction;
- deterministic synthetic execution for both schedules and all horizons;
- complete terminal population, costs, turnover, coverage, risk, and
  benchmark metrics;
- immutable Yahoo manifest and payload hash verification; and
- the real local-cache `BLOCKED/MISSING` preflight;
- deterministic stable-ID accounting for all 66 frozen securities; and
- canonical and file-hash verification of the committed blocked terminal
  artifact.

No network request, provider retry, parameter search, observed-history outcome
artifact, commit, push, or deployment is part of this runner implementation.
