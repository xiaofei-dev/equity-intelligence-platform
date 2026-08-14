# Fundamental Value Investment System v1 Stage 2 Acceptance

Date: 2026-07-31

## Decision

Stage 2 is `REPAIRED_PENDING_INDEPENDENT_REACCEPTANCE` for the pure
deterministic Python core. The master audit rejected the initial candidate for
growth-domain crashes and an omitted capital-allocation-quality dimension.
Both findings are repaired below, but Stage 3 remains closed until the master
controller independently accepts this gate. The model evidence label remains
`NOT_VALIDATED`.

## Implemented

- strict typed inputs, states, ranges, valuations, thesis conditions, and caps;
- company quality, financial resilience, earnings/cash-flow quality, and a
  separate price-independent capital-allocation-quality dimension;
- FCFF DCF with a one-time enterprise-to-equity bridge and terminal-share cap;
- normalized Owner Earnings without a duplicate cash/debt bridge;
- zero-growth Earnings Power;
- optional non-controlling comparable cross-check;
- exact method cardinality and all-three-primary aggregation gate;
- weighted-median central value and ordered weighted-quantile range;
- reference-price margin of safety;
- shareholder-cash-flow expected-return IRR;
- separately computed downside risk;
- structured thesis, counter-thesis, and invalidation conditions;
- deterministic refinancing-evidence materiality;
- 0/1/2/3/5 percent risk-cap ceilings; and
- canonical input and result hashes with complete core version bindings.

The repaired formula and assumption-policy versions are both `v1.1.0`.
Growth in every explicit FCFF, Owner Earnings, and expected-return scenario,
and terminal growth in every FCFF scenario, must exceed negative one before
arithmetic. Decimal and domain failures return explicit `INVALID` components.
Gross cash, debt, depreciation and amortization, and capital expenditures use
nonnegative sign conventions; change in working capital remains signed.

## Verification

The focused acceptance suite covers known answers, method bridges, state
precedence, missing-data monotonicity, crossed ranges, duplicate methods,
optional comparable evidence, distribution bounds, applicability refusal,
expected-return/downside isolation, evidence-label ceilings, content hashes,
and price/quality independence.

Initial candidate results, superseded by the P1 repair:

```text
Stage 2 focused tests: 199 passed in 0.58s
Ruff: All checks passed
git diff --check: PASS
```

The repaired candidate adds exact regressions for growth at `-1.00` and
`-1.01`, terminal growth at `-1.10`, extreme finite reference-price Decimal
domains, sign conventions, capital-allocation state propagation, price
independence, cap monotonicity, and version/hash binding. Final pytest and Ruff
results with the approved offline development toolchain are:

```text
Repaired Stage 2 focused tests plus normative version parity: 216 passed in 0.67s
Ruff --no-cache: All checks passed
AST, JSON, and relative-link checks: PASS
git diff --check: PASS
Independent repair audit: PASS
```

The 216 cases comprise the original 199-test matrix, 16 formula and dimension
repair regressions, and one normative-fixture/core version-parity regression.
The decision fixture binds formula and assumption-policy v1.1.0 and is resealed
as `sha256:042286da1c14af568c53fd05c4002a78763393a4ddb5e3235a8eacfb6da34a17`.
These results support a `PASS` recommendation but do not replace the master
controller's independent gate decision.

## Boundaries not crossed

Stage 2 has no V22 repository or persistence dependency. It creates no
migration, database table, HTTP route, FastAPI handler, Spring contract,
frontend component, provider adapter, AI narrative, Quantitative Trading
dependency, portfolio weight, order, trade, brokerage authority, or
guaranteed-return claim.

No provider request, database operation, cloud resource, deployment, license
change, generated-evidence rewrite, commit, push, or merge was performed.

## Residual risks and next gate

- Synthetic known-answer acceptance does not validate investment usefulness.
- Assumption policies and factor thresholds remain frozen engineering choices,
  not empirically supported return claims.
- Stage 3 must bind exact V22 evidence IDs, hashes, timestamps, selection
  outcomes, and specialized applicability without weakening this pure core.
- NBN remains an explicit Stage 3 identity/classification regression case.

Stage 3 must not begin until the controller accepts this Stage 2 gate.
