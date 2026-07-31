# Forward Decision-Quality Validation v2

Date: 2026-07-29

## Purpose

Forward Decision-Quality Validation v2 is the prospective evidence protocol
for:

- `TACTICAL-SIGNAL-v2.2.0`; and
- `LONG-HORIZON-RESEARCH-v1.1.0`.

It does not reinterpret previously observed historical results as an untouched
holdout. It begins with decisions made after the accepted model freezes and
waits for their outcomes to mature naturally. The protocol may conclude
`NOT_VALIDATED`, `MIXED`, `INSUFFICIENT_EVIDENCE`, or `BLOCKED_BY_DATA`.
Producing a favorable result is not an implementation objective.

This implementation is deliberately limited to contracts, immutable artifact
builders, and V16 audit-event payload builders. It performs no database write,
provider request, route exposure, model execution, outcome collection, commit,
push, deployment, or automatic trade.

## Preregistration

`FORWARD-DQV-PREREGISTRATION-v2.0.0` binds:

- the accepted Tactical v2.2 and Long Horizon v1.1 freeze-record, canonical
  artifact, physical file, and complete freeze-binding hashes;
- `MODEL-VALIDATION-GOVERNANCE-v1.0.0`, including both its canonical artifact
  hash and physical file SHA-256;
- the frozen historical validation protocol and walk-forward source hashes;
- the common `LIQUIDITY-SENSITIVE-COST-v1.0.0` contract;
- the complete formal benchmark set;
- complete-population accounting;
- natural outcome maturity;
- the prohibition on ordinary IID bootstrap for dependent outcomes;
- immutable prior decisions; and
- `aiMayAffectDeterministicFields=false`.

The builder verifies the accepted files from the repository. A self-consistent
but different model freeze, governance artifact, protocol source, or
walk-forward source is rejected. A changed contract requires a new explicit
version and preregistration.

No production preregistration or enrollment was executed by this workstream.
The builders are ready for the main controller to create the first artifact
only after it accepts the complete implementation.

## Benchmark evidence gate v2.1

`FORWARD-BENCHMARK-PREREGISTRATION-v2.1.0` closes the legacy gap where a
decision manifest could rely on a general ready flag without independently
proving all six benchmark constructions. The v2.1 path requires exactly one
terminal family for SPY, dated sector ETFs, equal weight, pure momentum, pure
value, and pure quality. Every family must be `AVAILABLE` before enrollment.

The controlled construction artifact, controlled evidence bundle, and
Git-safe manifest independently bind:

- the decision cutoff, universe, and frozen population;
- source, constituent, weight, selection, and per-holding cost evidence;
- the real-sector-to-ETF assignment for the sector family;
- the parent frozen liquidity-cost policy version and hash; and
- the separate benchmark-construction cost hash for the fixed notional,
  next-session-open entry, horizon-close exit, and no-rebalance convention.

The two cost hashes have different meanings and are not interchangeable.
Drift in either contract blocks enrollment. `PROVISIONAL` prices, missing
sector assignments, fewer than 20 Objective-score observations, less than 80%
Objective coverage, a benchmark preregistration later than the decision
cutoff, or direct promotion of a v2.0 manifest also blocks enrollment.

The first sealed v2.0 decision predates this v2.1 benchmark
preregistration. It therefore remains immutable diagnostic evidence and
cannot be retrospectively promoted.

## Frozen horizons

| Completed sessions | Model role | Formal gate |
| ---: | --- | --- |
| 5 | Tactical formal | Yes |
| 20 | Tactical formal | Yes |
| 60 | Tactical formal | Yes |
| 126 | Long Horizon interim diagnostic | No |
| 252 | Long Horizon formal | Yes |

The 126-session observation cannot be presented as validation of a model whose
minimum stated horizon is 12 months. It is retained as an explicitly
diagnostic intermediate observation. The 252-session result is the formal
Long Horizon observation.

Every horizon uses a purge, embargo, and minimum bootstrap block length at
least as long as its own outcome horizon. Formal evidence uses
`PURGED_BLOCK + BLOCK_BOOTSTRAP`. Rolling, overlapping daily decisions are
never evaluated with ordinary IID confidence intervals.

## Enrollment

The legacy `FORWARD-DQV-ENROLLMENT-v2.0.0` contract remains immutable.
Prospective model-quality evidence now uses
`FORWARD-DQV-ENROLLMENT-v2.1.0`, which accepts only a hash-valid
`FORWARD-DECISION-MANIFEST-v2.1.0` backed by the controlled v2.1 benchmark
chain. The source v2.0 decision is retained as evidence but is not itself
eligible for direct v2.1 enrollment. The accepted v2.1 manifest:

1. independently derives `prospectiveReady=true`;
2. has no readiness blocker;
3. binds exactly the preregistered model freezes;
4. contains one row per stable public security ID;
5. has terminal counts covering the full population for both model tracks;
6. proves all six benchmark families through the controlled construction,
   bundle, and Git-safe manifest hashes;
7. binds both the parent liquidity-cost policy and the separate benchmark
   construction cost policy;
8. records no AI influence over deterministic decisions; and
9. retains the immutable controlled decision artifact hash.

The controller supplies the exchange-calendar-derived completed-session
maturity timestamp for each of the five horizons. Every timestamp must follow
the decision and the schedule must be strictly chronological.

Enrollment uses an idempotency key and a content hash. An exact replay is
accepted. Reusing the same idempotency key with different evidence is rejected.
The enrollment artifact records model quality as `NOT_MATURED`; enrollment
success is not evidence that either model works.

## Outcome boundary

An outcome batch can be built only at or after the preregistered completed
session. It binds, without changing:

- the enrollment hash;
- the decision manifest hash;
- the controlled decision artifact hash;
- the frozen population hash; and
- the selected horizon and maturity timestamp.

Every enrolled security must have exactly one terminal outcome row. Valid
states are `ASSESSED`, `MISSING`, `STALE`, `INVALID`, `NOT_APPLICABLE`, and
`EXCLUDED`. Missing data cannot carry a return or a neutral value.

Each batch also requires one terminal row for all six frozen benchmarks:

- SPY;
- sector;
- equal weight;
- pure momentum;
- pure value; and
- pure quality.

Unavailable benchmark evidence is retained as missing, stale, or invalid and
blocks formal evidence. It is never silently replaced with SPY or zero.

For assessed observations, the controlled artifact retains gross return,
average daily dollar volume, order notional, price/action evidence hash, cost,
net return, and net excess returns. The exact frozen liquidity-sensitive cost
formula is applied to both securities and benchmarks before comparison.

The Git-safe manifest retains IDs, terminal states, reasons, source hashes, and
controlled record hashes only. It explicitly excludes raw provider values and
deterministic numeric results.

## Operational completeness and model quality

The protocol reports two independent axes:

### Operational completeness

`COMPLETE`, `INCOMPLETE`, or `BLOCKED` answers whether the system produced the
required immutable population and evidence records. A complete run may still
contain explicit missing-data evidence. An operational failure is not called a
model failure.

### Model quality

The allowed terminal states are:

- `NOT_MATURED`;
- `DIAGNOSTIC_ONLY`;
- `VALIDATED`;
- `MIXED`;
- `NOT_VALIDATED`;
- `INSUFFICIENT_EVIDENCE`; and
- `BLOCKED_BY_DATA`.

Formal target evidence requires:

- at least 100 naturally matured eligible security decisions;
- at least 80% population coverage;
- at least two outcome-horizon lengths of distinct completed decision
  sessions;
- a bootstrap block at least as long as the horizon;
- the complete available benchmark set;
- positive lower confidence bounds for the required discrimination and net
  benchmark comparisons; and
- frozen drawdown and downside-capture controls where applicable.

Tactical has one formal target, `TACTICAL_DECISION_QUALITY`. Long Horizon keeps
three separate targets:

- `BUSINESS_QUALITY`;
- `SECURITY_ATTRACTIVENESS`; and
- `DOWNSIDE_RISK`.

Long Horizon v1.1 cannot receive one aggregate rank-validation claim. If its
targets disagree, the overall result is `MIXED`. Missing metrics produce
`INSUFFICIENT_EVIDENCE`; unavailable required benchmark data produces
`BLOCKED_BY_DATA`; adverse complete evidence produces `NOT_VALIDATED`.

## Immutable artifacts and V16 handoff

Controlled enrollment and outcome artifacts are content-addressed under:

- `storage/forward-validation/enrollments-v2`; and
- `storage/forward-validation/outcomes-v2`.

Writers verify exact replay byte-for-byte and reject overwrite conflicts.

The V16 audit-event builders create append-only payloads for:

- `FORWARD_V2_PREREGISTRATION_SEALED`;
- `FORWARD_V2_DECISION_SNAPSHOT_ENROLLED`;
- `FORWARD_V2_OUTCOME_BATCH_SEALED`; and
- `FORWARD_V2_MODEL_QUALITY_ASSESSED`.

Every payload records:

- stable IDs and canonical hashes;
- operational and model-quality states;
- `aiStatus=NOT_EXECUTED`;
- `databaseWriteExecuted=false`; and
- `providerNetworkRequests=0`.

They do not write `analytics.analytics_audit_event`. A controller-owned
integration must provide transactional persistence and database-level
idempotency. A normalized multi-horizon PostgreSQL ledger may still require a
separately approved append-only migration; this module does not introduce one.

## Stop conditions

The protocol stops rather than claiming validation when:

- a freeze, governance, protocol, or decision hash differs;
- the decision snapshot is not prospective-ready;
- the complete population or terminal counts do not reconcile;
- AI affected a deterministic field;
- the requested horizon has not matured naturally;
- a required benchmark is unavailable;
- ordinary IID bootstrap is proposed for dependent outcomes;
- sample size, coverage, or distinct decision sessions are insufficient;
- a prior decision would need to be changed; or
- the evidence cannot distinguish operational failure from model quality.
