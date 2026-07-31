# Historical Walk-Forward Validation v2

## Purpose

`HISTORICAL-VALIDATION-PROTOCOL-v2.0.0` supplies shared validation
infrastructure for Tactical v2.2 and Long Horizon v1.1. It does not define or
change either model's formulas.

The protocol consumes `MODEL-VALIDATION-GOVERNANCE-v1.0.0`. The already
observed 2014-2026 Tactical v2.1 and Long Horizon v1.0 results remain
development evidence. A v2 walk-forward run over that period may diagnose a
redesigned model, but it is not an untouched historical holdout.

## Nested chronological folds

Each outer fold has three ordered windows:

1. expanding `DEVELOPMENT_OBSERVED`;
2. `SEALED_VALIDATION`, after a purge; and
3. `WALK_FORWARD_OUTER_FOLD`, after an embargo.

Tactical folds require at least 60 completed-session purge and embargo
windows. Long-horizon folds require at least 252 sessions. A formal
non-overlapping schedule also spaces decisions by at least the maximum
evaluated horizon and prevents a later outer fold from beginning before the
prior fold's outcome window has matured.

An overlapping schedule is allowed only when explicitly labeled
`OVERLAPPING_DIAGNOSTIC`. It cannot enter a formal acceptance gate.
Prospective decisions use the separate `PROSPECTIVE_FORWARD` role.

## Benchmarks

The formal contract records availability independently for:

- SPY;
- the dated sector benchmark;
- equal-weight universe;
- pure momentum;
- pure value; and
- pure quality.

Each available benchmark retains a versioned identifier and evidence hash.
Missing, stale, invalid, and not-applicable benchmark states remain explicit.
A formal gate stops if any required benchmark is unavailable.

## Costs

The cost contract combines:

- fixed round-trip costs;
- one-way base slippage; and
- a bounded square-root participation impact based on order notional divided
  by average daily dollar volume.

The cost policy and its parameters are versioned and included in the protocol
hash. A validation run cannot replace missing liquidity with zero impact.

## Frozen population

Every decision snapshot contains every security in the frozen universe.
Each security has exactly one terminal state:

- `ASSESSED`;
- `MISSING`;
- `INVALID`;
- `STALE`;
- `NOT_APPLICABLE`;
- `SPECIALIZED_MODEL_REQUIRED`; or
- `EXCLUDED`.

Silent removal of a security invalidates the snapshot.

## Metrics

Every formal run retains:

- rank information coefficient;
- top-minus-bottom return;
- top-versus-benchmark return;
- maximum drawdown;
- downside capture;
- turnover;
- coverage;
- missing count; and
- excluded count.

The contract does not allow a favorable subset of metrics to replace this
complete report.

## Dependence and resampling

Ordinary IID bootstrap is not accepted by a formal gate. Purged dependent
slices require a deterministic block bootstrap. The supplied circular-block
implementation records observation count, block length, iterations, seed,
and the diagnostic 90 percent interval.

Block-bootstrap output does not by itself establish a statistical edge.
Claim strength remains capped by the governance evidence envelope.

## Immutability and boundaries

Protocol and fold plans have deterministic canonical hashes. A later formula,
weight, threshold, applicability, benchmark, cost, sampling, or evidence
change requires a new model freeze and validation version.

This infrastructure performs no provider request, model scoring, automatic
trade, or AI adjustment. Existing historical v1 artifacts and Forward v1
preregistration remain immutable.
