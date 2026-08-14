# Quant Trading v1.1 Research Product Slice Acceptance

Date: 2026-08-13

## Outcome

The Quant v1.1 research product slice is accepted for engineering use. This
does not change the model evidence label. The controlled historical result
remains `NOT_DIRECTIONALLY_SUPPORTIVE_NO_RETUNING_ON_SAME_OUTCOME`, and the
model remains `NOT_VALIDATED`.

## Implemented Boundary

- Provider-neutral V22 assembly of exact 253-session security and SPY inputs.
- Immutable V27 public-safe research-decision persistence.
- FastAPI internal ID-based creation and readback.
- Spring Boot public GET-only projection and independent contract validation.
- Next.js `/research/quant-trading` workspace.
- Explicit `ENTRY_CANDIDATE`, `HOLD_REVIEW`, `EXIT_REVIEW`, `NO_SIGNAL`,
  `NOT_APPLICABLE`, and `INSUFFICIENT_EVIDENCE` states.
- Entry-candidate signal price, maximum entry price, initial stop, ATR, and
  maximum-holding context.

The slice prohibits final portfolio weights, order quantities, brokerage
instructions, automatic brokerage execution, LLM signal or weight authority,
and guaranteed-return claims. It does not implement Quant v2.

## Verification

- Full PostgreSQL 17 migration, upgrade, preservation, refusal, and V27 SQL
  acceptance matrix: passed.
- Typed Python V27 PostgreSQL write/read/exact replay: 1 passed.
- Complete focused Quant Python matrix, including V22 assembly, decision,
  persistence, FastAPI routes, historical contracts, and simulation: 216
  passed.
- Complete offline Spring suite: 150 passed across 26 test reports.
- Frontend Node contract tests: 66 passed.
- Frontend ESLint: passed.
- Next.js production build: passed, including dynamic
  `/research/quant-trading`.

No provider request, model-formula change, production label upgrade, final
portfolio weighting, brokerage integration, commit, push, or deployment was
performed for this acceptance.
