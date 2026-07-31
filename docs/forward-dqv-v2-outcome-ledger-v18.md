# Forward DQV v2 Outcome Ledger (V18)

Date: 2026-07-29

## Status

`IMPLEMENTED_AND_POSTGRESQL_17_ACCEPTED`

V18 is the bounded append-only successor required by the Prospective Outcome
Persistence Readiness Audit v1. It does not reinterpret or mutate any V1-V17
record. It does not authorize an outcome for the current benchmark v2.2
`DATA_PENDING` preregistration.

## Machine-verifiable acceptance

The implementation acceptance is sealed in
`docs/generated/forward-dqv-v18-acceptance-v1.json`.

The offline verifier
`equity_analysis.forward_validation.v18_acceptance_v1` recomputes the V18
migration, Python contract, and repository file hashes. It also verifies the
exact seven-table schema, five completed-session horizons, six benchmark kinds,
PostgreSQL 17 clean and upgrade-path evidence, repository test evidence, and
the recorded full-suite, Ruff, and diff-check states.

The acceptance status is intentionally split:

- `implementationStatus = READY`;
- `enrollmentStatus = NOT_EXECUTED`.

The artifact therefore allows the v2.2 readiness controller to accept the V18
implementation boundary without claiming that a prospective population was
enrolled or that any outcome, score, or rank was produced.

## Ownership and scope

All seven new tables are Python-owned `analytics.*` objects:

1. `forward_dqv_enrollment_v2`
2. `forward_dqv_maturity_schedule_v2`
3. `forward_dqv_outcome_batch_v2`
4. `forward_dqv_security_outcome_v2`
5. `forward_dqv_benchmark_outcome_v2`
6. `forward_dqv_path_metric_v2`
7. `forward_dqv_quality_report_v2`

V18 creates no `app.*` object. Spring Boot remains the owner of user-facing
business state. V16 refresh, transport, calendar, and source evidence remains
separate from the terminal outcome ledger.

## Frozen persistence rules

- An enrollment binds the idempotency request hash, preregistration, decision
  manifest, controlled decision artifact, READY data snapshot, universe,
  complete frozen-population hash, both model freezes, benchmark contract, cost
  policy, and explicit terminal counts.
- Every enrollment has exactly five deferred-validated maturity rows:
  5, 20, 60, 126, and 252 completed sessions.
- The 5/20/60 horizons are `TACTICAL_FORMAL`; 126 is
  `LONG_HORIZON_INTERIM_DIAGNOSTIC` and is not formal-gate eligible; 252 is
  `LONG_HORIZON_FORMAL`.
- A complete outcome batch has exactly one terminal row for every stable public
  security identity in the frozen population and exactly one row for each of
  SPY, sector, equal-weight, pure momentum, pure value, and pure quality.
- Assessed or available rows require gross return, round-trip cost, net return,
  price evidence, and source-manifest evidence. Net return must equal gross
  return minus the stored cost within `1e-12`.
- Missing, stale, invalid, not-applicable, and excluded states retain null
  numeric values and explicit reason codes. They are never changed to zero.
- Typed path metrics persist maximum adverse excursion, maximum favorable
  excursion, maximum drawdown, benchmark maximum drawdown, and downside
  capture. Complete assessed security rows require MAE, MFE, and drawdown.
- Every table rejects `UPDATE` and `DELETE`.
- A correction is a new result version that names the immediately preceding
  result for the same enrollment, horizon, and model track where applicable.
  Unique predecessor constraints prohibit branching.
- Deferred constraint triggers validate the five-row maturity schedule and the
  complete batch population at transaction commit.
- Raw provider prices and licensed values are not stored in Git-safe artifacts.
  No AI field may alter deterministic outcomes, and no brokerage execution path
  is introduced.

## Python v2.1 contract and repository

`outcomes_v21.py` adds a versioned extension rather than changing immutable
v2.0 artifacts. It validates five-horizon roles, six benchmark identities,
explicit terminal states, cost/gross/net arithmetic, path evidence,
complete-population accounting, correction shape, and canonical SHA-256
chains.

`outcome_persistence_v21.py` writes enrollment plus maturity schedule, outcome
batch plus all terminal/path rows, and quality reports in atomic PostgreSQL
transactions. Exact replay returns the existing immutable row. Reusing an
identity or version with different evidence raises
`FORWARD_DQV_V2_IDEMPOTENCY_CONFLICT`. Readback reconstructs and validates the
same v2.1 object.

## Acceptance

PostgreSQL 17 accepted:

- clean `V1 -> V18`;
- populated `V3 -> V18`;
- `V12 -> V18`;
- `V16 -> V18`; and
- `V17 -> V18`.

The real PostgreSQL repository test accepted atomic enrollment, outcome, and
quality-report persistence; exact replay; conflicting replay rejection; exact
typed readback; and one correction successor with a rejected branch.

Python contract tests additionally reject incorrect net-return arithmetic,
missing MFE for an assessed security, and formal classification of the
126-session interim horizon.

## Explicit non-actions

This implementation made no provider request, score, model-formula change,
Forward quality claim, commit, push, cloud-resource change, or deployment.
Actual Forward v2 outcomes remain prohibited until a post-preregistration
decision and all benchmark evidence naturally mature.
