# Long Horizon v1.1 Historical Validation Readiness

Date: 2026-07-29

## Result

Long Horizon v1.1 historical validation is `BLOCKED_BY_DATA`. The readiness
runner did not compute a v1.1 score, reuse the v1.0 single score, substitute a
proxy formula, call a provider, write to PostgreSQL, run Forward Validation, or
change the model.

The complete frozen 66-security population has an explicit terminal state:

- 55 primary or reserve model candidates are `MISSING`;
- 2 benchmark securities are `NOT_APPLICABLE` to the company model;
- 9 frozen exclusions remain `EXCLUDED`.

This is an honest readiness result, not an adverse model-performance result.

## Evidence inspected

The runner verifies:

- the accepted Long Horizon v1.1 model freeze and all source hashes it binds;
- the 66-security closed-test universe;
- all 56 hash-verified Yahoo historical payloads in the completed manifest;
- stable public security identifiers and non-numeric inventory metadata from
  the current PostgreSQL database;
- current database counts and date ranges for fundamental facts, READY
  membership snapshots, and classification observations;
- the existing Long Horizon v1.0 report as `DEVELOPMENT_OBSERVED`.

The Git-safe readiness artifact contains no database financial values or raw
licensed provider payloads.

## Why scoring is prohibited

Long Horizon v1.1 requires decision-time evidence for business quality,
financial strength, capital allocation, valuation and entry, expected return,
downside risk, sector-relative evidence, and evidence confidence. The current
repository does not contain hash-verified historical v1.1 decision-input
snapshots that preserve all required fields and their as-of availability.

Current READY universe membership and sector observations do not prove
historical membership, sector assignment, or a peer cohort at each historical
decision date. The formal benchmark set is also incomplete:

- SPY prices are available only as diagnostic, ex-post adjusted evidence;
- dated sector benchmarks are missing;
- equal-weight and pure-momentum comparisons require historical membership;
- pure-value and pure-quality comparisons require the missing PIT v1.1 inputs.

The 55 model candidates have enough hash-verified price history to inspect a
252-session outcome series. Outcome availability cannot repair missing
decision-time evidence. Computing a score first and checking the future price
afterward would introduce an unsupported reconstruction and an invalid
validation claim.

## Missing-field matrix

The machine-readable artifact records every required v1.1 field for every
candidate. All remain `MISSING` as historical decision inputs, even when the
database contains potentially related raw facts. Raw fact presence does not
prove the accepted v1.1 derivation, period alignment, availability, revision
lineage, peer cohort, or classification contract.

## Historical boundary

The 2014-2026 Long Horizon v1.0 result was already observed during development.
It remains:

```text
evaluationRole = DEVELOPMENT_OBSERVED
untouchedHoldout = false
```

It cannot validate v1.1 and cannot be converted into an untouched holdout.

## Required next evidence

Before a Long Horizon v1.1 historical diagnostic can run, a separate bounded
data-construction task must produce complete, hash-verified, PIT decision
snapshots with:

1. all v1.1 fields or explicit missing states;
2. historical security membership and stable identity;
3. dated sector classification and sufficient peer cohorts;
4. all six benchmark contracts;
5. as-of corporate-action evidence suitable for the governance claim;
6. complete 252-session outcomes after the decision cutoff.

If those inputs cannot be constructed without inference or look-ahead, the
correct terminal result remains `BLOCKED_BY_DATA` or
`INSUFFICIENT_EVIDENCE`.

## Artifact

`docs/generated/long-horizon-v1-1-historical-readiness-2026-07-29.json`

The artifact is Git-safe and immutable. It contains hashes, counts, dates,
statuses, and reason codes, but no scores or provider financial values.
