# Model Validation Governance v1.1

Date: 2026-07-30

## Purpose

`MODEL-VALIDATION-GOVERNANCE-v1.1.0` is a bounded successor to v1.0. It does
not modify or reinterpret the immutable v1 policy, Tactical v2.2, Long Horizon
v1.1, an existing historical result, or a Forward enrollment.

The successor aligns validation language with practical decision value while
preserving the v1 evidence envelope, claim ceilings, leakage controls,
complete-population rule, explicit missing states, and AI boundary.

## Two independent status axes

Operational execution and model evidence are never represented by one field.

`runStatus` describes whether a planned evaluation ran:

- `NOT_STARTED`
- `RUNNING`
- `COMPLETED`
- `BLOCKED_BY_DATA`
- `INSUFFICIENT_EVIDENCE`
- `FAILED`

`modelEvidenceLabel` describes the supported claim:

- `BACKTEST_SUPPORTED`
- `PIT_SUPPORTED`
- `FORWARD_SUPPORTED`
- `PARTIALLY_SUPPORTED`
- `NOT_VALIDATED`
- `INVALIDATED`

A blocked, insufficient, or failed run remains `NOT_VALIDATED`; it is not an
adverse model result. `INVALIDATED` requires completed, predeclared adverse
evidence and cannot be assigned from already observed development evidence.

## Evidence ceilings

v1.1 reuses the v1 evidence envelope and claim-ceiling calculation.

- A current-universe, current-revision, ex-post-adjusted diagnostic may support
  a disclosed `BACKTEST_SUPPORTED` or `PARTIALLY_SUPPORTED` claim.
- It can never become `PIT_SUPPORTED` or `FORWARD_SUPPORTED`.
- `PIT_SUPPORTED` requires verified decision-time availability, historical
  membership, an as-of corporate-action ledger, non-overlapping or purged
  outcomes, and sealed or untouched historical evaluation.
- `FORWARD_SUPPORTED` requires prospective sealed availability, a prospective
  frozen universe, immutable as-of action evidence, naturally matured
  outcomes, and a prospective evaluation role.

Every label is stored per model version, target, and completed-session horizon.
No aggregate label may hide a failed or missing target.

## Tactical v2.2 boundary

Tactical v2.2 produces deterministic ordinal scores. It is not an empirically
calibrated probability model. A calibrated probability claim requires a future
successor version and its own frozen calibration evidence.

Tactical evidence is recorded separately for:

- ranking evidence; and
- entry-decision evidence.

Ranking discrimination cannot validate `ENTRY` or `LIMITED_ENTRY`. Entry
support requires separately observed actionable episodes under the frozen
event, liquidity, cost, and execution contracts. Labels are independent at 5,
20, and 60 completed sessions.

## Long Horizon v1.1 boundary

Long Horizon labels remain separate for:

- company quality;
- security attractiveness;
- expected return; and
- downside risk.

Evidence for one target cannot validate another. A quality result is not an
expected-return rank, an attractive valuation is not a quality claim, and a
return result does not prove downside protection. There is no default aggregate
Long Horizon validation label or ranking.

The first model-aligned horizon is 252 completed sessions. Longer horizons must
be labeled independently and cannot inherit the 252-session conclusion.

## Finite evaluation rule

One frozen model version and freeze hash may have exactly one planned
retrospective. An exact idempotent replay is allowed; a changed plan, sample,
threshold, or run identity is rejected.

Observed outcomes cannot choose the frozen contract. A successor version is
authorized only for:

- an implementation defect;
- a methodology defect;
- a justified missing factor; or
- a systematically harmful assumption.

The successor requires a new model version, new freeze, documented evidence,
and evaluation on a later window or prospective decisions. Repeated successor
creation solely to improve observed results is prohibited.

## Practical-value thresholds

No numeric economic threshold is added retrospectively to the observed
Tactical Tier-1 results. Their threshold applicability is
`OBSERVED_TIER1_NOT_APPLICABLE`.

Future economic-materiality thresholds may be created only as
`FORWARD_ONLY`. They must be versioned and frozen before outcomes mature.
Their later values may cover net value, costs, turnover, drawdown, downside
capture, abstention opportunity cost, or another preregistered decision target.

## Missing, AI, and human boundaries

Missing, stale, invalid, not-applicable, excluded, abstain, and watch-only
states remain explicit. None becomes zero, neutral evidence, or an inferred
success.

AI may explain an immutable result but
`aiMayAffectDeterministicFields=false`. Human judgment is a separate,
append-only decision record. It cannot mutate the model snapshot, evidence
label, score, target result, benchmark outcome, or historical input.

## Execution boundary

This governance successor:

- does not change a model formula, threshold, benchmark, or runner;
- does not rerun a historical evaluation;
- does not enroll or mature Forward evidence;
- does not write a database;
- makes no provider request; and
- does not modify the immutable v1 governance artifact.

The Git-safe machine policy is:

`docs/generated/model-validation-governance-v1-1.json`
