# Fundamental Value Historical Validation v1

Date: 2026-07-31

## Gate status

Stage 7A is frozen as a read-only audit and Stage 7B is limited to offline,
migration-free infrastructure. No provider request is authorized. The current
production V22 evidence and empty production producer registry cannot assemble
all 34 operands for a mature company, so real assessments remain `MISSING` and
the model remains `NOT_VALIDATED`.

## Frozen protocol

- Fundamental Value remains separate from Quant Trading.
- The model, assumptions, applicability routes, missing-state rules, and risk
  ceilings are unchanged.
- The frozen population contains 200 explicit curated/control securities and
  110 additional securities, ten per GICS sector. The additional selection is
  three large, four mid, and three small capitalization names per sector from
  a hash-bound source snapshot, excluding the curated stable security IDs.
- SPY and eleven sector ETFs are benchmarks outside the 310 count.
- Every security has one explicit role: `PRIMARY`, `RESERVE`,
  `REFERENCE_ONLY`, `SPECIALIZED_MODEL_REQUIRED`, `EXCLUDED`, or
  `INSUFFICIENT_DATA`. The denominator does not shrink when an observation is
  ineligible.
- Nine primary dates contain one SHA-256-ranked completed US session from Q2 of
  each year 2015 through 2023. The calendar hash and outcome cutoff are bound,
  and the 2023 node must mature through 756 completed sessions. Three
  adverse-entry stress diagnostics are 2018-09-20, 2020-02-19, and 2022-01-03.
  Stress results never enter the primary estimate.
- Three-year total return is primary, two-year is supporting, and one-year is
  diagnostic. Outcomes use total-return corporate-action treatment and
  security-matched sector benchmarks.
- Equal-weight high, middle, and low portfolios are formed within each decision
  date before aggregation. Stock-date observations are not independent.
- Current-revision fundamentals are labelled
  `CURRENT_REVISION_APPROXIMATION`; they cannot establish strict PIT or Forward
  support. Historical validation can never establish `FORWARD_SUPPORTED`.

The validation-only predictor interface keeps company quality, security
attractiveness/margin of safety, expected return, and downside risk separate.
It forms deterministic 20/60/20 quintile groups per target and date among at
least 100 eligible generic assessments, with durable security ID tie-breaking.
Existing binary investable conditions are evaluated separately. Risk cap is
forbidden as a predictor, no composite score is introduced, and outcome
execution stops until the master accepts each economically defensible mapping.

## Batching and preflight

Benchmarks are acquired separately. Batch 0 contains one equity canary per
GICS sector and binds the twelve benchmark checkpoints. It permits at most 91
EODHD physical attempts and configured weight 190, with retry zero. The eleven
canaries remain members of the 310 universe, but reuse proof is
`BLOCKED_EXECUTION_CONTRACT_INCOMPLETE` until completed Batch 0 receipts exist.
Remaining physical equity acquisition uses
eleven batches of 25 and one batch of 24. No batch executes more than 25 new
equities.

Baseline acquisition uses 322 Yahoo price wrapper calls for 310 equities and
12 benchmarks, plus EODHD fundamentals, dividends, and splits for equities:
930 physical requests and weight 3,720. One universe-snapshot request remains
separately optional. EODHD EOD cross-checking and historical market cap are
separate optional phases of 310 requests/weight each. The combined maximum may
reach 1,587/4,377, but no baseline plan may execute an optional endpoint.
Retry is zero and the unused allowance reserve is at least 20,000.

## Mandatory stops

Execution stops on authentication, rate limit, transport ambiguity, schema or
semantic drift, content/hash mismatch, lease or journal conflict, PIT breach,
universe drift, unexplained quota delta, or an `UNKNOWN` physical request.
Unknown requests are never automatically rerun. It also stops before outcomes
if the exact curated 200 list, frozen source snapshot, stable identities,
capitalization policy, rating mapping, benchmark/action policy, outcome cutoff,
or protocol hashes are absent.

## Statistical report contract

Entry is the first completed session after the decision cutoff. Exits are the
252nd, 504th, and 756th completed sessions after entry; entry itself is not
counted as an elapsed session.

For each decision date and horizon the report preserves coverage denominators,
portfolio total and annualized return, SPY and matched-sector excess, hit rate,
high-minus-low spread, monotonicity, drawdown/downside, turnover, and explicit
cost assumptions. The nine overlapping annual decision clusters support
descriptive date-level summaries; ordinary IID stock-row tests and IID
bootstrap are prohibited. Reports include the median across nine dates,
positive-date count, leave-one-date-out summaries, and up to three
non-overlapping 756-session anchors. The frozen v1 protocol is descriptive; a
future circular block bootstrap would require block length three and a sealed
seed before outcomes.

## Frozen market-first thresholds

Three-year outcomes alone may support a label. The freeze requires at least
seven complete random dates, 100 usable generic assessments per date, 20 names
in each extreme quintile, and at least 90 percent SPY/outcome coverage. For
attractiveness and expected return it requires median rank IC above 0.05 with
at least six positive dates, median top-minus-bottom annualized spread above
two percentage points, median top-minus-SPY annualized excess above one point
with at least six wins, nonnegative leave-one-date-out median SPY excess, and
top maximum-drawdown deterioration no worse than five points. Expected-return
interval coverage must be at least 40 percent and median absolute annualized
error below ten points. Sector-relative evidence is secondary and separately
labelled when only current classification is available. Missing sector mapping
does not replace or invalidate a complete SPY result.

Company-quality and downside conclusions require their own future target
evidence; otherwise they are `INSUFFICIENT_EVIDENCE`. A stress veto applies if
at least two of three stress nodes show at least ten-point annualized SPY
underperformance or ten-point worse drawdown. Directional incomplete evidence
is `DEVELOPMENT_OBSERVED`; operational data failure is
`INSUFFICIENT_EVIDENCE`/`BLOCKED_BY_DATA`, not a model label. No Stage 7 file
updates V23, and `PIT_SUPPORTED`/`FORWARD_SUPPORTED` are impossible here.
Portfolio MDD, downside capture, and the stress veto remain
`BLOCKED_DAILY_PATH_REQUIRED`; constituent MDD is never averaged or described
as portfolio MDD. Threshold evaluation remains pending Stage 7D.
