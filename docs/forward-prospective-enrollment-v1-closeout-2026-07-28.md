# Forward Prospective Enrollment v1 Closeout

Date: 2026-07-28

## Outcome

The first Market Intelligence-to-Forward prospective bridge is implemented
and verified locally. It converts a sealed PostgreSQL V17 Market Intelligence
screen into an idempotent prospective-enrollment attempt for the existing V11
Forward ledger without inventing eligible signals.

The current 66-security decision snapshot contains:

- 0 eligible deterministic results;
- 55 `INSUFFICIENT_DATA` Objective outcomes; and
- 11 `SPECIALIZED_MODEL_REQUIRED` outcomes.

The bridge therefore records one append-only
`FORWARD_PROSPECTIVE_ENROLLMENT_ATTEMPT_SEALED` audit event with
`NO_ELIGIBLE_SIGNALS`. It creates no V11 `forward_enrollment`,
`forward_candidate_signal`, or `forward_observation_result` row. Repeating the
same idempotency key returns the same attempt and does not duplicate business
state.

The verified local attempt is:

- attempt ID `6ee0e7cc-d269-45e1-b4bc-0e27c2a551a1`;
- attempt hash
  `sha256:8cb5594eabcef82c4c221a4da12f7a54bc8e4ab996954683611efc186bc6c6b3`;
- data snapshot `beaa9952-9852-4088-9dc3-92047824414b`;
- sealed Market Intelligence run
  `f6f36a73-53c2-4762-b76c-deac6712bede`; and
- decision cutoff `2026-07-29T02:57:08.988871Z`.

This is a successful no-eligible engineering result, not a return,
performance, or statistical-edge result.

## Boundary between V17 and V11

V17 remains the durable source of immutable Market Intelligence profiles,
horizon views, exclusions, and sealed screening results. V11 remains the
prospective outcome ledger for genuinely eligible signals.

The bridge:

1. verifies the decision-snapshot audit-event hash;
2. verifies every referenced sealed V17 screening run;
3. reads immutable profile decisions and explicit exclusion reasons;
4. records one append-only prospective-attempt audit event;
5. writes V11 enrollment and signal rows only when an eligible deterministic
   result exists; and
6. returns the same attempt for an identical idempotency key.

It does not copy an AI narrative into ranking state, create a trade, replace a
missing factor, or promote a provider fetch to scoring eligibility.

## Frozen maturity contract

Eligible prospective signals retain the exact frozen Forward maturity
schedule:

| Label | Trading sessions | Prospective use |
| --- | ---: | --- |
| `ONE_WEEK` | 5 | Tactical outcome checkpoint |
| `ONE_MONTH` | 20 | Tactical outcome checkpoint |
| `THREE_MONTHS` | 60 | Tactical outcome checkpoint |

The 12-month-plus model remains research context only. It is preserved in the
decision record but is not represented as a prospective outcome horizon by
this bridge.

Because the current attempt has no eligible signals, all three maturity
entries are `NOT_APPLICABLE`. No future price or outcome observation has been
created.

## Public contract and research workspace

Spring Boot provides typed public create, latest, and attempt-detail routes
under `/api/v1/forward-validation/prospective-enrollments`. It translates the
versioned Python internal contract and does not reimplement Forward logic.

The Next.js research workspace uses a strict typed decoder for the public
latest route. Its prospective panel distinguishes:

- no attempt;
- blocked or no-eligible attempt;
- pending future checkpoints; and
- checkpoints that are not applicable because no signal episode started.

The panel displays the 5-, 20-, and 60-session schedule and labels
12-month-plus content as model context. The browser does not call Python,
PostgreSQL, or a market-data provider directly.

## Fundamental evidence boundary

This phase also closes the raw-fundamental-to-factor wiring defect without
changing Objective Rating v1:

- a provider-neutral fundamentals envelope retains provider identity, source
  reference, SHA-256 content hash, availability and retrieval times, current
  company classification, current market capitalization, and normalized
  financial observations;
- the persisted-fact adapter accepts an operand only when its period
  semantics, duration, unit, currency, availability, ingestion cutoff,
  revision, freshness, continuity, quality status, and lineage are proven;
- `Q_UNPROVEN`, `NOT_VERIFIED`, stale, future, or incomplete inputs remain
  explicit `MISSING` or invalid states;
- historical FCF-yield percentile remains missing without an eligible
  historical PIT series; and
- the valuation guardrail remains missing when the required cohort
  percentiles are unavailable.

The current EODHD daily-refresh facts do not yet prove the required discrete
quarter and quality semantics. Provider retrieval completion is therefore not
Objective eligibility. The adapter can assemble supported frozen factors from
future evidence that satisfies the same provider-neutral contract, but it
does not lower the cohort threshold or infer missing operands.

## Verification evidence

The implementation was verified with:

- exact Python contract and idempotency tests;
- typed Spring client, controller, and contract tests;
- strict Next.js contract and transport tests;
- an isolated PostgreSQL 17 `V1 -> V17` run;
- a V17-to-V11 no-eligible bridge test proving one append-only attempt event
  and zero V11 enrollment, candidate-signal, and outcome rows; and
- an actual PostgreSQL Objective screening re-run proving one supported
  factor can be assembled with lineage while missing factors remain missing.

The verified Objective re-run completed with 0 scored, 55 insufficient-data,
and 11 specialized-model results. No false eligibility was introduced.

The full local acceptance also passed:

- Python Ruff plus 527 tests, with 6 environment-gated tests skipped;
- 47 Spring Boot tests;
- 15 frontend contract tests, TypeScript, ESLint, and production build;
- an npm production-dependency audit with zero known vulnerabilities;
- PostgreSQL 17 clean `V1 -> V17` and populated `V3 -> V17`, `V12 -> V17`,
  and `V16 -> V17` migration paths;
- clean-environment Analytics with 518 tests passed and 15 deliberate skips;
- full-history and current-tree Gitleaks scans with no leaks; and
- a rebuilt local four-service check in which `/research` rendered the sealed
  no-eligible attempt, all three `NOT_APPLICABLE` checkpoints, and the
  no-outcome/no-trade safety wording.

## Non-claims and inactive operations

This phase made:

- no live Yahoo, EODHD, SEC, or other provider request;
- no change to scoring formulas, weights, cohort thresholds, PIT rules, or
  missing-data behavior;
- no outcome, benchmark, excess-return, or performance claim;
- no brokerage or automatic-trading integration; and
- no commit, push, cloud-resource creation, scheduler activation, or
  deployment.

The next Forward step is to enroll a future sealed decision snapshot only when
it contains genuinely eligible deterministic signals, then wait for its
predeclared 5-, 20-, and 60-session maturity dates.
