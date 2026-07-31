# Market Intelligence Eligibility Recovery v1

## Purpose

Eligibility Recovery v1 explains why a sealed Market Intelligence snapshot
cannot enter the frozen Objective Rating cohort and determines whether an
approved, bounded provider request plan can improve that result. It does not
change formulas, point-in-time rules, cohort thresholds, or missing-data
semantics.

The read-only internal contract is:

```text
GET /internal/v1/market-intelligence/eligibility-recovery/status/latest
```

It requires the exact `data_snapshot_id`, `universe_version`, and `as_of`
boundary. The requested timestamp must equal the sealed READY snapshot.

Spring Boot exposes the same typed, read-only status to the closed-test
workspace:

```text
GET /api/v1/market-intelligence/eligibility-recovery/status/latest
```

Spring validates the closed-test identity, translates the public camel-case
query contract to the internal snake-case contract, and sanitizes upstream
errors. It does not read Python-owned tables or reimplement eligibility logic.
The Next.js research workspace calls only this public Spring endpoint.

## Evidence Boundary

The status is recomputed from PostgreSQL V1-V17 evidence:

- the sealed `analytics.data_snapshot`;
- its immutable universe membership;
- V17 security profiles and the latest sealed screening coverage;
- snapshot-bound fundamental and market-value observations;
- snapshot-time dataset freshness events.

Historical `docs/generated` artifacts are not runtime inputs. The response is
Git-safe and contains statuses, reason codes, source-route decisions, hashes,
and timestamps, but no licensed provider values.

## Recovery Decision

Each included general company receives exact factor and operand diagnostics.
Reference-only, excluded, and specialized-model securities remain explicitly
not applicable.

Provider requests are planned only when they can increase the maximum eligible
count under the frozen contract. Repeating EODHD fundamentals whose quarterly
records remain `Q_UNPROVEN`, have no `periodStart`, or are `NOT_VERIFIED` does
not prove discrete-quarter or TTM semantics. Yahoo daily prices cannot supply
Objective fundamental evidence. Neither route supplies the required historical
point-in-time FCF-yield series.

For the current 66-security sealed snapshot, the bounded approved routes cannot
raise the current Objective cohort to its frozen minimum of 20. The status is
therefore `BLOCKED_COHORT_UNREACHABLE`, the request plan is empty, confirmation
is not requested, and no provider request is executed.

## Local Acceptance

The rebuilt four-service stack returned the same canonical response through
Python and Spring:

- profile count: 66;
- sealed result count: 66;
- current eligible count: 0;
- frozen minimum eligible count: 20;
- maximum eligible after the approved plan: 0;
- due included securities: 55;
- provider request-plan items: 0;
- network requests executed: false;
- scores or ranks generated: false; and
- artifact content hash:
  `sha256:2d593662aff10164600f03ecd00c0ad2a2ba092c30dfd0d0f18f0fe91544720e`.

The `/research` page rendered the blocked cohort, exact coverage counts,
freshness and blocker evidence, and the empty provider plan. It exposes no
provider-execution, scoring, ranking, or trade action.

Verification passed with Python Ruff and 530 tests plus 7 environment-gated
skips, 51 Spring tests, 19 frontend tests, TypeScript, ESLint, production
build, and a real isolated PostgreSQL 17 `V1 -> V17` route test.

## Safety Properties

- The preflight ID and artifact content hash are deterministic for identical
  sealed evidence; generation time is excluded from their canonical input.
- Missing, stale, invalid, and not-applicable states remain distinct.
- A provider-complete response is never treated as scoring eligibility.
- No execution endpoint is exposed for a blocked or empty request plan.
- Any future executable plan must preserve the existing V16 refresh journal,
  lease, checkpoint, idempotency, retry, and budget boundaries.
