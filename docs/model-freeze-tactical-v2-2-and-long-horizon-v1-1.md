# Tactical v2.2 and Long Horizon v1.1 Model Freeze

Date: 2026-07-29

## Purpose

This freeze separates model development from validation. It binds the exact
Tactical v2.2 and Long Horizon v1.1 source files to a common, versioned
historical-validation contract before any new historical scoring or
prospective Forward Decision-Quality Validation.

The two machine-readable freeze artifacts include SHA-256 references for the
model implementation, governance code, walk-forward protocol, methodology
documents, prior diagnostic artifacts, and the historical Yahoo manifest.
They also bind formula, weight, input-schema, applicability, missing-data,
benchmark, cost, universe, sampling, and acceptance contracts.

## Freeze chronology

The observed-evidence cutoff remains `2026-07-29T23:59:59Z`. During initial
generation, the latest modification time among every bound source was
`2026-07-30T00:40:54.609680Z`. The fixed administrative freeze time is the
next five-minute UTC boundary, `2026-07-30T00:45:00Z`.

Initial generation fails if a bound source modification time is later than the
recorded source-finalization time. Stable verification after checkout does not
depend on filesystem modification times, because checkout tools may rewrite
them. It instead reconstructs the artifact from the fixed chronology and
current source-content SHA-256 values.

## Historical evidence boundary

All historical evidence inspected before the freeze cutoff is labeled
`DEVELOPMENT_OBSERVED`. The existing 2014-2026 Tactical v2.1 and Long Horizon
v1.0 reports have already influenced problem diagnosis. They are not an
untouched holdout and cannot be relabeled as one.

The freezes therefore state:

```text
evaluationRole = DEVELOPMENT_OBSERVED
untouchedHoldoutAvailable = false
```

Historical replay after this freeze may provide leakage-resistant development
and sealed walk-forward evidence, subject to the governance claim ceiling.
Final confirmation still requires naturally matured, prospective decision
snapshots under a separately preregistered Forward protocol.

## Shared validation contract

Both tracks use:

- chronological nested walk-forward evaluation;
- complete frozen-population decision snapshots;
- stable public security identifiers and explicit terminal states;
- a purge and embargo at least as long as the maximum evaluated horizon;
- block bootstrap for dependent formal observations;
- no ordinary IID bootstrap in a formal gate;
- SPY, dated sector, equal-weight, pure-momentum, pure-value, and pure-quality
  comparisons under one execution and cost policy;
- explicit fixed and liquidity-sensitive costs;
- explicit missing, stale, invalid, not-applicable, specialized, and excluded
  states.

Tactical v2.2 freezes a 60-completed-session maximum horizon with 60-session
purge and embargo. Long Horizon v1.1 freezes a 252-completed-session maximum
horizon with 252-session purge and embargo. Both use random seed `20260729`.

## Model-specific acceptance boundary

Tactical validation evaluates thesis and actionability quality after costs. It
does not interpret a large decline as an entry and does not treat a tactical
score as a return forecast.

Long Horizon v1.1 does not authorize a default ranking score. Validation keeps
business-quality durability, security attractiveness, and downside protection
as separate targets. A result for one target cannot validate the others or be
promoted to a single aggregate return claim.

## Execution status

Creating these freezes does not:

- run historical scoring;
- call Yahoo, EODHD, SEC, or another provider;
- start Forward Decision-Quality Validation;
- modify a database migration;
- commit, push, deploy, or enable automatic trading.

The artifacts are Git-safe contract metadata. They contain hashes, versions,
policies, and paths, but no licensed provider values or historical score
results.

## Generated artifacts

- `docs/generated/tactical-v2-2-model-freeze.json`
- `docs/generated/long-horizon-v1-1-model-freeze.json`

`model_freeze_v1.py` reconstructs and verifies each artifact from current
source bytes. Existing artifacts are treated as immutable: the generator
accepts an identical file and refuses to overwrite a changed one.
