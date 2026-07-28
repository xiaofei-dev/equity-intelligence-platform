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
