# Quantitative Trading v1 Stage 0 Acceptance

Date: 2026-08-12

## Candidate Scope

Stage 0 freezes the strict Python contract, canonical Git-safe fixture, and
normative methodology for one independent long-only momentum-continuation
strategy. It preserves Tactical v2.2, Fundamental Value, V21, V22, and V26
semantics and adds no migration or executable model.

The repaired freeze removes daily-bar ambiguity by fixing entry/exit fill
precedence, conservative same-bar handling, delayed trailing/invalidation
effects, whole-share/cash/cost sizing, candidate priority, adjusted-price and
terminal-event handling, and benchmark/cost parity.

## Acceptance Boundary

Acceptance requires the focused contract tests, Ruff, JSON/hash verification,
and `git diff --check` to pass. It proves deterministic contract enforcement,
not signal quality, backtested returns, point-in-time validity, or trading
authority.

No provider request, network call, database write, signal calculation,
backtest, Spring/Next.js implementation, commit, push, deploy, cloud action,
portfolio order, or brokerage action is part of Stage 0.

## Verification

- Focused strict-contract suite: `62 passed`.
- Ruff over the new Python package and focused tests: passed.
- Canonical fixture JSON parse and SHA-256 recomputation: passed.
- Scoped `git diff --check`: passed.

Recommendation: Stage 0 engineering candidate `PASS`; independent re-audit
remains the final acceptance gate. Stop before Stage 1.
