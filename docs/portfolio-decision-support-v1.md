# Portfolio Decision Support and Evaluation v1

## Purpose

Task 5 turns the immutable V28 portfolio context into a human-controlled
decision workflow. It supports onboarding, current evidence assembly, four
deterministic scenario types, an immutable human decision, and later simulated
evaluation. It is not an allocation optimizer, brokerage system, or promise of
future returns.

## V32 product projection

V32 adds an immutable exact-four comparison cohort before recommendation or
human acceptance. The cohort contains exactly one sealed `HOLD_CURRENT`,
`NEW_MONEY_ONLY`, `CONSTRAINED_REBALANCE`, and `TARGET_PORTFOLIO` scenario for
the same owner, portfolio, and V28 context. Spring exposes the cohort to the
browser while recommendation binding can still be unavailable.

The V32 longitudinal projection is read-only decision support. Gross return,
net return, HOLD_CURRENT return, SPY return, true daily-path maximum drawdown,
coverage, turnover, and cost are shown only for a complete server-replayed
maturity. Awaiting or terminal-missing horizons retain explicit unavailable
values. Human thesis reviews use only `CONFIRMED`, `WEAKENED`, `INVALIDATED`,
or `INSUFFICIENT_EVIDENCE`; they do not create orders, change portfolio
weights, or upgrade research evidence labels.

## Version ownership

- V12 remains authoritative for users, accounts, sealed account snapshots,
  liabilities, portfolios, memberships, investment profiles, and constraint
  policies.
- V21 and the V12 scenario/result/decision tables remain legacy and are not
  reinterpreted.
- V28 remains the immutable current portfolio and risk context.
- V29 owns the new Portfolio Decision Scenario v1 graph, its evidence bindings,
  deterministic candidate, recommendation-for-review, and human decision.
- V30 owns later simulated observations and maturity evaluation. Separating V30
  prevents future price chronology from being mixed into the current decision
  transaction.
- V31 owns controlled longitudinal total-return observations and natural
  maturities. V32 owns the exact-four cohort and longitudinal projection. V33
  hardens time and longitudinal seals. V34 aligns ratio replay at scale 20 with
  `ROUND_HALF_EVEN`. V35 requires V22 `CLOSE_PRICE` and `UNADJUSTED` evidence
  for current portfolio valuation without changing V31 total-return semantics.

Manual and bounded CSV onboarding use V12. CSV raw bytes are not persisted;
the sealed snapshot records the file hash, parser version, and normalized
content hash.

## Frozen scenario contract

The exact scenarios are `HOLD_CURRENT`, `NEW_MONEY_ONLY`,
`CONSTRAINED_REBALANCE`, and `TARGET_PORTFOLIO`.

The deterministic objective is lexicographic:

1. prove identity, ownership, chronology, and evidence integrity;
2. preserve hard constraints and locked positions;
3. enforce exact scenario semantics;
4. minimize gross traded notional;
5. minimize estimated cost;
6. minimize deviation from explicit human targets; and
7. use durable security ID ascending only as a final tie-break.

Expected return, Fundamental Value scores, and Quant scores are never optimizer
coefficients. `LONG_TERM_CORE` and `QUANT_TRADING` remain independent. Sleeve
budgets and cross-sleeve cash transfers require explicit human input.

`HOLD_CURRENT` has no trades. `NEW_MONEY_ONLY` cannot sell and uses only an
explicit human-approved candidate set. `CONSTRAINED_REBALANCE` obeys exact
per-security permissions. `TARGET_PORTFOLIO` evaluates the exact human target
without repairing or clamping it.

## Evidence and authority

Every nonzero trade requires an accepted, current, hash-bound price. Missing,
stale, invalid, and not-applicable evidence is never substituted with zero or a
neutral score. Existing holdings with unavailable prices may appear in a
partial hold view, but cannot receive a numeric trade delta.

Fundamental Value and Quant references retain their original evidence labels.
`NOT_VALIDATED` cannot be upgraded. Fundamental Value risk caps are ceilings,
not target weights. Quant v2 and any evidence with research use disabled cannot
authorize an increase. An exit review is advisory and never forces a sale.

The engine can emit only `CANDIDATE_FOR_HUMAN_REVIEW` or
`NO_FEASIBLE_CANDIDATE`. Final weights, orders, brokerage execution, and LLM
security-selection or weight authority are prohibited.

## Economics

Transaction-cost and slippage rates are nonnegative one-way basis-point inputs
bound to `portfolio-decision-cost-policy-v1.0.0`. Cost is the sum of absolute
trade notional multiplied by the combined rate. Market impact is unavailable
unless a sealed liquidity observation and versioned formula are present.

Tax is an optional non-advisory estimate. It is unavailable without complete
lot basis, acquisition dates, rates, and a frozen lot-selection policy. Missing
impact or tax is never represented as zero.

The scenario reports gross buys, gross sells, gross traded notional, one-way
weight turnover, and gross-traded-notional rate separately. Final constraints
are evaluated after contribution, trades, cost, and any explicitly applied tax
estimate.

## Simulated evaluation

V30 enrolls the evaluation and V31 starts on the first eligible completed
session after every immutable decision/context cutoff. V31 compares the
accepted scenario with both the exact `HOLD_CURRENT` counterfactual and an SPY
buy-and-hold comparator funded from the same pre-trade capital base at 20, 60,
252, 504, and 756 completed-session horizons. Each available horizon therefore
requires the entry observation plus the horizon sessions. The MVP records net
return, accepted-minus-HOLD and accepted-minus-SPY return, complete coverage,
and the frozen entry implementation cost. Gross return and true daily-path
maximum drawdown remain explicitly not observed; nonzero external cash flow is
refused until a separately frozen time-weighted-return policy exists.

Evaluation cannot alter a decision or upgrade a model evidence label. Missing
paths remain explicit, and no same-history threshold tuning is permitted.

## Product sequence

1. Create or select an owner-isolated portfolio and accounts.
2. Enter holdings, cash, and liabilities manually or import a bounded CSV.
3. Seal complete V12 snapshots and a versioned V12 constraint policy.
4. Assemble accepted price and V26/V27 evidence into V28 without accepting
   browser-supplied market values.
5. Compare all four V29 scenarios and record an immutable human decision.
6. Observe V30 simulated performance without creating brokerage orders.

The acceptance demonstration uses a clearly labelled synthetic USD 100,000
portfolio. It is engineering evidence, not a claim about a real user portfolio
or future investment performance.
