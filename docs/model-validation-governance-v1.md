# Model Validation Governance v1

## Purpose

`MODEL-VALIDATION-GOVERNANCE-v1.0.0` defines the evidence and model-freeze
boundary for Tactical v2.2, Long Horizon v1.1, and their prospective
Decision-Quality Validation.

It does not make a model favorable. A valid implementation may conclude that
a model is mixed, not validated, insufficiently evidenced, or blocked by
data.

## Observed historical evidence

The 2014-2026 Tactical v2.1 and Long Horizon v1.0 results have already been
reviewed. They are `DEVELOPMENT_OBSERVED` evidence and are not an untouched
holdout for a redesigned model.

They may support failure diagnosis, architecture design, and labeled
walk-forward diagnostics. They may not be used both to choose a formula or
threshold and to claim that the same formula or threshold passed an
independent test.

## Independent evidence dimensions

Every validation run records five dimensions:

1. availability evidence;
2. universe evidence;
3. outcome dependence;
4. evaluation role; and
5. price and corporate-action evidence.

The strongest allowed positive conclusion is capped by the weakest dimension.
An unknown dimension is never replaced by an optimistic default.

Current-revision facts, current-universe retrospective membership,
ex-post-adjusted prices, observed development periods, and overlapping
outcomes cannot produce `VALIDATED`.

## Model freeze

Before an outer-fold or prospective outcome is evaluated, an immutable freeze
record binds:

- the model and validation protocol versions;
- formulas and weights;
- input, applicability, and missing-data contracts;
- benchmarks and costs;
- universe and sampling definitions;
- acceptance thresholds and random seed;
- source artifacts and observed-evidence cutoff; and
- purge and embargo lengths.

Tactical freezes cover at least 60 sessions. Long-horizon freezes cover at
least 252 sessions. A formula, weight, applicability, benchmark, cost, lag, or
threshold change creates a new model version and a new freeze record.

## Complete population

A sealed snapshot contains every frozen-universe security with an explicit
terminal state. Assessed, missing, invalid, stale, not applicable, specialized,
and excluded outcomes remain visible. Silent population attrition is invalid.

## Outcome dependence

Formal gates use non-overlapping observations or a documented purged-block
method. Overlapping monthly outcomes and ordinary IID bootstrap intervals are
diagnostic only and cannot enter a formal acceptance decision.

## Acceptance layers

1. **Structural validity**: deterministic replay, cutoffs, complete terminal
   states, hashes, and no AI influence on deterministic values.
2. **Evidence validity**: availability, membership, revisions, adjustments,
   and benchmark evidence.
3. **Directional validity**: rank discrimination, top-minus-bottom direction,
   and fold, sector, and regime consistency.
4. **Practical value**: net benchmark-relative value, drawdown, downside
   capture, turnover, liquidity, and costs.
5. **Prospective confirmation**: immutable future decisions and naturally
   matured outcomes.

Allowed terminal statuses are `VALIDATED`, `PROVISIONALLY_VALIDATED`, `MIXED`,
`NOT_VALIDATED`, `INSUFFICIENT_EVIDENCE`, and `BLOCKED_BY_DATA`.

## Forward boundary

The existing Forward v1 preregistration remains immutable and QC-specific.
Tactical v2.2 and Long Horizon v1.1 require a separate Forward v2
preregistration after their contracts and freeze records are accepted.

AI may explain deterministic evidence but must retain
`may_affect_deterministic_fields=false`. No validation contract authorizes
automatic brokerage execution or guaranteed-return language.
