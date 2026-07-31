# Forward Daily Incremental Protocol

## Decision

Forward Decision-Quality Validation uses a daily, post-close enrollment cycle.
The earlier weekly preregistration remains immutable evidence but is
operationally superseded by `FORWARD-VALIDATION-v1.1.0`.

Daily API quota is a safety capacity, not a consumption target. The scheduler
refreshes only datasets whose recorded last-update state is stale or missing.
It must not issue requests merely to consume unused quota.

## Dataset refresh policy

- Daily prices and historical market capitalization are refreshed after each
  completed regular US trading session.
- Fundamentals and identity metadata use a seven-calendar-day maximum age,
  unless a filing, provider update, missing value, or validation warning
  triggers an earlier refresh.
- Dividends and splits are prioritized for active preview securities and
  benchmarks. The wider universe uses a seven-calendar-day check.
- Missing or stale data remains missing. It is never replaced with zero or a
  neutral score.

Each security keeps separate last-update evidence for daily prices, historical
market capitalization, fundamentals, corporate actions, and identity. A
successful request must update only the applicable dataset timestamp and
retain its response hash.

## Initial bounded plan

The first authoritative plan contains 223 formula-ready source securities and
the required benchmark set. The deterministic last-update scheduler plans 589
EODHD physical requests:

- 231 daily-price requests for securities and benchmarks;
- 223 historical-market-capitalization requests;
- 128 dividend and split requests for the preview and benchmarks; and
- seven fundamentals requests for `A`, `AAPL`, `ACN`, `ADBE`, `ADI`, `CAT`,
  and `JNJ`, whose reusable EODHD fundamentals cache is missing.

This corrects the preliminary static estimate of 582 requests recorded by the
protocol artifact. The immutable per-session plan is authoritative because it
evaluates each dataset's actual last-update state.

The plan is approximately 0.589% of a 100,000-call daily quota. The configured
execution ceiling is 1,000 calls, the hard ceiling is 1,500 calls, and retries
are disabled.

## Enrollment boundary

The refresh plan may be prepared before market close, but it cannot be marked
ready for live execution until the target regular session has completed and
the provider is expected to contain complete end-of-day observations.
Scoring and signal enrollment occur only after the refresh, validation, and
immutable sealing steps succeed.

Daily cohorts may overlap. Primary evaluation therefore uses unique
first-entry episodes, records overlap explicitly, and prevents the same
security, strategy, and bucket from re-entering for 60 trading days.

This protocol is research-only. It does not authorize automatic trading or
claim that prospective observations prove future excess returns.

## Implemented vertical-slice bridge

The local Market Intelligence vertical slice now provides an idempotent bridge
from sealed V17 screening decisions to the V11 prospective ledger. Every
attempt is recorded as an append-only audit event. V11 enrollment, candidate
signal, and observation rows are created only when the sealed decision
contains an eligible deterministic signal.

The verified 66-security snapshot has 0 eligible results, 55
`INSUFFICIENT_DATA` results, and 11 `SPECIALIZED_MODEL_REQUIRED` results. Its
bridge attempt is therefore `NO_ELIGIBLE_SIGNALS`, with no V11 signal or
outcome rows. The 5-, 20-, and 60-session schedules are retained as
`NOT_APPLICABLE`; the 12-month-plus model remains context only.

Spring Boot exposes typed create, latest, and attempt-detail endpoints. The
Next.js research workspace displays the typed latest state and clearly
separates pending or matured prospective outcomes from long-horizon model
context.

This bridge phase made no provider request. It did not change a formula,
cohort threshold, PIT rule, missing-data rule, or previously frozen Forward
schedule. The bounded 57-price/57-action/55-fundamental refresh was completed
in the preceding vertical-slice phase: ACN's malformed current row was
rejected, while 259 prior valid sessions were retained.
