# Forward DQV Repeated-Date Cohort Controller v2.2

## Purpose

The repeated-date cohort controller prepares and audits accumulation of
prospective Forward Decision-Quality Validation evidence across multiple
completed decision sessions. It does not create decisions, execute models,
enroll a population, observe outcomes, or run statistics.

The controller consumes only `FORWARD-DQV-ENROLLMENT-v2.1.1` records and the
latest immutable V18/V19 outcome evidence for each enrollment and horizon.
The legacy v2.1.0 chronology is rejected.

## Frozen bindings

Every accepted decision date must match:

- the canonical Forward DQV v2 preregistration;
- its exact 66 stable public security UUIDs;
- the preregistered universe version and identity-binding hash;
- both frozen model artifact hashes;
- the frozen benchmark and cost-policy bindings;
- the V19 chronology contract
  `decisionAsOf <= sealedAt <= effectiveEntryOpen`; and
- the exact 5, 20, 60, 126, and 252 completed-session maturity schedule.

Different decision dates may contain the same securities because they are
different prospective observations. They may not reuse an enrollment ID,
decision-manifest hash, or data-snapshot ID. The same decision date is an exact
idempotent replay only when its complete candidate hash is unchanged.

## Cohort accounting

Decision-time terminal counts are descriptive planning evidence only. They are
never used as matured eligibility.

Matured eligibility is calculated separately for every security and every
horizon from terminal security outcome records:

- `ASSESSED` contributes one eligible decision;
- `MISSING`, `STALE`, `INVALID`, `NOT_APPLICABLE`, and `EXCLUDED` remain
  explicit non-eligible states; and
- absent outcome evidence remains `NOT_MATURED`.

Every decision date must have at least 80% assessed coverage for the relevant
horizon. A formal horizon also requires:

- at least 100 assessed security decisions;
- at least two distinct decision dates;
- a matured calendar span of at least two times the horizon; and
- a horizon-specific purged and embargoed independent-date schedule.

The controller compares a candidate date with the last accepted independent
date for that horizon. A nearby date remains visible but is not counted as an
independent sample. The 126-session horizon remains diagnostic-only even when
its evidence thresholds are reached.

## Persistent read path

The CLI supports three sources:

- `--contract-fixture` for deterministic isolated contract tests;
- `--input` for a versioned offline request; and
- `--persisted-enrollments` for read-only PostgreSQL V19 enrollment and latest
  V18 outcome-batch evidence.

The persistent path may optionally select repeated `--enrollment-id` values.
It reads the database URL from `DATABASE_URL` by default or from the
environment variable named by `--database-url-env`. It never accepts a
credential on the command line.

The controller performs no database write, provider request, model rerun,
outcome calculation, scheduler creation, cloud action, or trading action.

## Current acceptance status

Implementation and isolated controller tests are ready, but the formal
contract-fixture artifact is intentionally not generated.

The immutable V19 acceptance artifact remains canonically valid, while its
recorded source hash for `outcome_persistence_v211.py` predates the additive
due-maturity loader. Strict current-source verification therefore stops with
`V19_SOURCE_HASH_MISMATCH`. A versioned superseding V19 acceptance must bind
the final repository source and PostgreSQL acceptance before the controller
may produce its formal artifact.

The old immutable V19 artifact must not be overwritten, and no verifier bypass
is allowed.
