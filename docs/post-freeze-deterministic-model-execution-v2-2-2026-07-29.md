# Post-Freeze Deterministic Model Execution v2.2

## Purpose

This execution layer connects the frozen post-preregistration population to the
existing deterministic Tactical v2.2 and Long Horizon v1.1 models. It produces
the 66 terminal security rows required by
`POST-FREEZE-DECISION-SNAPSHOT-v2.2.0`.

This work does not change either model's formulas, weights, applicability,
missing-data behavior, or point-in-time rules.

## Frozen inputs

The orchestrator verifies and binds:

- `docs/generated/forward-preregistration-seal-v2-2.json`;
- `docs/generated/forward-dqv-preregistration-v2.json`;
- `docs/generated/tactical-v2-2-model-freeze.json`;
- `docs/generated/long-horizon-v1-1-model-freeze.json`;
- one post-seal completed-session price evidence artifact;
- one versioned model-input evidence artifact;
- the exact 66 stable public security identities and frozen roles.

The population remains:

- 48 `PRIMARY`;
- 7 `RESERVE`;
- 2 `REFERENCE_ONLY`;
- 9 `EXCLUDED`.

Legacy decisions and results cannot be upgraded into this execution.

## Execution behavior

`PRIMARY` and `RESERVE` members are evaluated by the existing frozen functions:

- `evaluate_tactical_signal_v22`;
- `evaluate_long_horizon_v11`.

The tactical result is separated into independent 1-week, 1-month, and
3-month terminals. Each terminal has its own input hash and result hash. The
12-month-plus long-horizon terminal is independently hashed and retains a
separate evidence hash.

`REFERENCE_ONLY` members are always `NOT_APPLICABLE`. `EXCLUDED` members remain
`EXCLUDED` and retain the frozen exclusion reason. They are never passed to the
models.

Missing, stale, invalid, not-applicable, specialized-model, and excluded states
remain explicit. They do not receive a zero or neutral score and cannot carry a
result hash.

## AI boundary

AI is disabled for deterministic execution. It cannot change any input,
terminal state, model result, rank, or hash. This layer does not produce
narrative research.

## Current repository preflight

The current repository preflight is:

`docs/generated/post-freeze-model-execution-v2-2-preflight.json`

Its status is `BLOCKED` for exactly:

- `COMPLETED_SESSION_PRICE_EVIDENCE_MISSING`;
- `MODEL_INPUT_EVIDENCE_MISSING`.

The preflight generates no decision rows, real manifest, score, rank,
enrollment, network request, database read, or database write.

The existing future-price preflight is not completed-session evidence. Existing
pre-freeze, historical, fixture, or legacy decision artifacts cannot satisfy
either blocker.

## Fixture acceptance

The controlled fixture:

- executes both frozen models for all 55 `PRIMARY` and `RESERVE` members;
- produces exactly 66 terminal rows;
- proves independent 1-week, 1-month, 3-month, and 12-month-plus bindings;
- proves deterministic replay and source/result hash stability;
- preserves the 2 reference-only and 9 excluded roles;
- proves missing tactical evidence remains missing while an independent
  long-horizon assessment can remain assessed;
- rejects pre-seal execution and immutable artifact conflicts.

Fixture success proves executable contracts only. It is not a real
post-freeze decision, does not enroll Forward Decision-Quality Validation, and
does not establish future performance.

## Next safe step

After a completed trading session, the controller may provide:

1. hash-verified completed-session price and action-adjustment evidence;
2. cutoff-valid Tactical v2.2 contexts;
3. cutoff-valid Long Horizon v1.1 inputs and evidence hashes;
4. exact sector and source bindings for all 66 frozen members.

Only then may this execution layer produce the 66 controlled terminal rows for
the snapshot assembler. Snapshot sealing, six-benchmark readiness, V18
acceptance, and enrollment remain separate gates.
