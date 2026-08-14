# Quantitative Trading v1 Stage 1 Acceptance

Date: 2026-08-12

## Candidate Scope

Stage 1 implements the pure deterministic Python momentum-continuation signal
and trade-plan core. It consumes exactly 253 aligned, completed, cutoff-valid
security and SPY adjusted-OHLCV sessions plus strict V22-style identity,
selector, chronology, event, corporate-action, and lifecycle bindings.

The engine implements the frozen features, weights, readiness gates, entry
range, initial stop, two-risk-unit target, three-ATR trailing stop, invalidation,
and 60-session time-stop rules with precision-50 `Decimal` arithmetic and
half-even rounding. It emits immutable, content-hashed `READY`, `NO_SETUP`,
`INELIGIBLE`, `MISSING`, `STALE`, or `INVALID` results. Non-valid inputs emit no
numeric score or plan.

## Acceptance Boundary

The Git-safe fixture contains synthetic engineering values only. Passing tests
proves formula replay, state propagation, evidence binding, and deterministic
serialization. It does not prove profitable trading, backtested value,
point-in-time provider coverage, or future returns. The evidence label remains
`NOT_VALIDATED`.

Stage 1 consumes a trusted prevalidated adapter seam. It verifies canonical
session-set and benchmark-identity seals but does not itself establish calendar
or identity authority. Stage 2 must load accepted V22 records and reject the
TEST_ONLY synthetic authorities before any production decision is possible.

Stage 1 adds no provider call, network access, database migration, simulator,
historical outcome access, API, Java, frontend, AI, brokerage path, commit,
push, deployment, or cloud resource. Tactical v2.2, Fundamental Value, and
Stage 0 semantics remain unchanged.

## Verification

- Focused Stage 1 engine suite: `25 passed`.
- Stage 0 plus Stage 1 Quant Trading suite: `87 passed`.
- Ruff over the Quant Trading package and focused tests: passed.
- Canonical synthetic fixture parse and exact replay: passed.
- Scoped `git diff --check`: passed.

Independent formula and contract re-audit: `PASS`, with no remaining P1/P2.

Recommendation: Stage 1 engineering `PASS`. Stop before the event-driven
portfolio simulator.
