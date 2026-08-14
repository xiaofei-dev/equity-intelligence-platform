# Portfolio Decision Support and Evaluation v1 Acceptance

Date: 2026-08-13

## Decision

Task 5 passes its final fresh mutation-driven four-service engineering
acceptance gate through V35. It does not authorize brokerage execution, LLM-selected
securities or weights, guaranteed returns, deployment, or an investment-label
upgrade.

## Delivered workflow

- Spring-owned manual and CSV onboarding creates owner-isolated V12 snapshots,
  liabilities, balances, constraints, and the mandatory V29 companion seal.
- Public context creation is ID-only. Spring binds the governed V12 graph and
  Python replays persisted V22 prices plus V26 Fundamental Value and V27 Quant
  state. Browsers cannot submit prices, market values, evidence hashes, model
  labels, entry sessions, quantities, or returns.
- The deterministic engine implements `HOLD_CURRENT`, `NEW_MONEY_ONLY`,
  `CONSTRAINED_REBALANCE`, and `TARGET_PORTFOLIO`, with explicit human sleeve
  budgets and separate Fundamental Value and Quant authority.
- V29 stores immutable evidence manifests, scenarios, recommendations, and a
  single-current-chain human decision.
- V30 owns evaluation enrollment. V31 freezes distinct accepted and
  `HOLD_CURRENT` opening ledgers and restricts the MVP to buy-and-hold
  observations derived from completed sessions and sealed selector IDs.
- V31 derives zero trade notional, turnover, and cost when quantities do not
  change; nonzero external cash flow is fail-closed. Controlled maturation
  requires contiguous same-calendar observations through exactly 20, 60, 252,
  504, or 756 sessions and seals accepted, HOLD, SPY, and excess returns.
- Spring exposes the public workflow and a service-authenticated internal
  observation/maturation surface. Next.js communicates only with Spring.
- V32 requires one sealed exact-four scenario cohort before recommendation or
  human acceptance, then derives gross and net return, HOLD/SPY comparisons,
  true daily-path maximum drawdown, coverage, turnover, cost, and immutable
  thesis-review state from the controlled observation path.

## Runtime acceptance

### PostgreSQL 17

- The final current-byte migration and upgrade/refusal matrix through V35
  passed. The runner preserves historical V29/V31 fixture execution before the
  V35 current-price successor is applied, then verifies the exact V35 contract
  and upgrade preservation.
- V34 migration SHA-256:
  `C49D861B4769CBE41F825481866585F2D1547CEEBE87092A4F883CD6DD2A5FDF`.
- V35 migration SHA-256:
  `6940FFBE939E44026C4D2D15F233BF9CF064C379587B490BBCAACB61A37C0BC3`.
- Final runner SHA-256:
  `603992EAA55384966F2397F4C5AFB4B9E0B4EF60C943DBDBB68D207E3DCE23E7`.

- The final full migration and upgrade matrix through V33 exited `0` in 118.5 seconds and ended
  with `Database migration acceptance passed.`, including clean V1-to-V33,
  preservation paths, and the unchanged
  V18-to-V19 refusal.
- V31 migration SHA-256:
  `319D0C07EC096B84CD4D665CEA93A62468F0FBBE2E930D543D597AB882E7C059`.
- V31 acceptance SHA-256:
  `DB49FED9D29A3BB32457901C52BEE9A37B8DF93889FA3AD3D42AECB149FFA8AD`.
- V32 migration SHA-256:
  `84E4E96128A0F99CFC8C3BFF391691330635DC39CCF3EB9929FE874AC286A236`.
- V32 acceptance SHA-256:
  `4715F304A635DAA8E89ED2E517A17B3B0E93E2C7EEE64FE9C2ADEB9FE4B3DA82`.
- V33 migration SHA-256:
  `F61CFBA1068387BB6F7AB84E281CFD283771D5ACD38722AA1FC91EF6F9DA4D8F`.
- V33 acceptance SHA-256:
  `A7F0A3286CDA11DFC8305619D17358F0DACD01764DAF06146B0C33C89272777B`.
- Historical end-to-end fixture SHA-256:
  `EE4FF7D6EB16E6721EDDEAC5EFF78C8383C799A47D4610007D2E058EF33AE2A3`.
- Runner SHA-256:
  `EFB9298DDF8AC3EE414EEBB516CA5F3F84E66D4FF95A480EB144F24961EF590E`.
- Acceptance covers companion consumption, contract/cardinality immutability,
  cross-owner selector refusal, controlled-output refusal, terminal-missing
  derivation, and post-terminal observation refusal. The shared evaluation lock
  and non-deferrable controlled-output relationship close the audited race and
  same-transaction future-command bypass by construction.

### Python, Spring, and frontend

- Current Task 5 Python context/decision regression: 81 passed; Ruff passed.
- Focused Spring projection/controller/client regression: 14 passed.
- Complete frontend Node suite: 97 passed; ESLint and the Next.js 16.2.12
  production build passed.
- The final fresh V1-to-V35 database seeded one offline GOOG assessment and
  executed the public Spring workflow with zero provider and brokerage calls.
  It created the V28 context, all four scenarios, a selected
  `TARGET_PORTFOLIO` candidate, and one immutable human `ACCEPTED` conclusion.
  Exact replays succeeded; changed same-key comparison, selection, and decision
  commands returned HTTP 409.
- A live Next.js readback returned HTTP 200 and displayed `Exact 4 / 4`, all
  four scenario types, `ACCEPTED`, `NOT_VALIDATED`, and the no-final-weight,
  no-order, no-brokerage, no-autonomous-AI boundary. The Git-safe
  [fresh E2E artifact](generated/portfolio-decision-task5-fresh-e2e-v1.json)
  has SHA-256
  `94F88A425DE1566BC295C8388EEBADE968E535C31B4367B7B2124F79BD0379FC`.

- Focused Python context/decision tests: 77 passed; Ruff passed.
- Full offline Spring suite: 179 tests, zero failures or errors, with three
  environment-gated tests skipped.
- Final fresh PostgreSQL typed Spring run: 3 passed in 2.588 seconds. It read
  the accepted fixture and natural-maturity projection, then created a superseding
  human decision and evaluation, froze opening ledgers, wrote 21 ID-only
  observations with 42 accepted/HOLD selector rows, matured the 20-session
  horizon, verified exact replay and conflicting replay refusal, and read the
  public V31 projection.
- The controlled result contained 21 observations from 2025-01-03 through
  2025-01-31: gross return `0.158`, accepted net return `0.157995`, HOLD return `0.16`,
  accepted-minus-HOLD `-0.002005`, SPY return `0.10`, and
  accepted-minus-SPY `0.057995`. Turnover was zero and frozen entry cost was
  `0.5`; true daily-path maximum drawdown was `0` on the synthetic path.
- Focused frontend decision/onboarding suite: 25 passed; ESLint and the Next.js 16.2.12 production
  build passed. The decoder validates real dates, whole-second UTC timestamps,
  coverage arithmetic, excess arithmetic, return domains, and nullable
  not-observed metrics.
- The prior four-service fixture gate returned HTTP 200 from FastAPI, Spring, and
  Next.js. A local Chrome DOM inspection verified the fixture `TARGET_PORTFOLIO`
  evaluation, HOLD and SPY comparators, 20-session `AVAILABLE` state, later
  awaiting maturities, 21/21 coverage, returns, and `$0.50` cost. All
  assertions are preserved in the Git-safe
  [V32 browser acceptance artifact](generated/portfolio-decision-task5-v32-browser-assertion-v1.json).
  The page displayed the exact four-scenario cohort, gross/net/HOLD/SPY values,
  true daily-path drawdown, coverage, turnover, cost, and the explicit
  `INSUFFICIENT_EVIDENCE` thesis review. The artifact SHA-256 is
  `7B3AB602D6B5D653B5BC57B0F8ADC4E21D6069976E5EFFA5F2190055E5C7127B`.
  That artifact is retained as fixture readback evidence only. It does not prove
  the required fresh mutation-driven comparison flow on the final V33 bytes.

## Honest limitations

- The USD 100,000 examples and matured path are controlled synthetic evidence
  proving workflow mechanics, not investment performance.
- Natural production maturity, provider execution, deployment, and investment
  validation remain future gates.
- The production model evidence labels remain unchanged, including
  `NOT_VALIDATED` where applicable.
- The final E2E uses controlled offline evidence and proves contract,
  persistence, service, and presentation behavior only. It is not a real
  portfolio recommendation or an investment-performance result.
- No provider request, business-database deployment, brokerage action, commit,
  push, or cloud deployment occurred.

The prior [V33 blocked gate artifact](generated/portfolio-decision-task5-v33-final-gate-v1.json)
is retained as immutable historical evidence and is superseded for engineering
acceptance by the fresh V35 E2E artifact above.
