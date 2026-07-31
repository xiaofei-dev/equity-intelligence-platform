# Forward DQV Maturity and Outcome Engine v2.2

## Purpose

The engine deterministically evaluates an accepted prospective enrollment at
5, 20, 60, 126, and 252 completed sessions. The 126-session result is an
interim diagnostic; 252 sessions is the formal long-horizon result.

## Evidence boundary

An evaluation requires the exact completed-session calendar, next-session-open
entry price, every adjusted OHLC bar through the maturity close, corporate
action hashes, source-manifest hashes, and the frozen cost-policy hash. Natural
calendar fallback, partial paths, future observations, and missing-to-zero
coercion are prohibited.

`observedAt` must be explicitly timezone-aware. Every completed-session bar
must occur after the enrolled entry open, the final bar must equal the
registered maturity session exactly, and every `availableAt` must be no later
than `observedAt`.

The batch-level source-manifest, calendar, corporate-action, and price hashes
are deterministic canonical roots over the ready path inputs. Roots bind and
sort paths by typed stable identity: `SECURITY:<public-security-uuid>` or
`BENCHMARK:<benchmark-kind>`. Calling order, ticker-like display names, and
colliding `subjectId` values cannot change or obscure a root. Duplicate typed
identities are rejected. The roots are not expected to equal any individual
row or bar hash; their purpose is to bind the complete set of row-level hashes
into the sealed batch.

Each security preserves `MISSING`, `STALE`, `INVALID`, `NOT_APPLICABLE`, or
`EXCLUDED` when it cannot be assessed. Every batch contains all six frozen
benchmark identities. Human judgment and AI narrative may be attached only as
typed provenance and cannot alter deterministic outcomes.

The security population must contain only public-security identities, must
contain no duplicate public security UUID, and must equal the enrollment's
frozen `securityCount` exactly. A benchmark path cannot be substituted into
that population even when the tuple length still matches.

## Calculations

- gross return: maturity adjusted close divided by entry adjusted open minus one
- net return: gross return minus the frozen liquidity-sensitive round-trip cost
- path metrics: maximum adverse excursion, maximum favorable excursion, and
  maximum drawdown
- aggregate metric: downside capture relative to SPY down sessions
- per-ready-path downside capture relative to the same SPY negative-session
  path, preserved in supplemental analytics for the statistics adapter
- supplemental diagnostics: downside deviation, realized volatility, and
  negative-session count
- supplemental liquidity evidence: per-path order notional, average daily
  dollar volume, and their participation ratio; these inputs and the resulting
  cost are bound by the canonical bundle hash

Portfolio turnover is not inferred from per-path order notional. Gate H does
not receive a complete portfolio-value denominator, so supplemental analytics
preserve `portfolioTurnover=null` with
`NOT_COMPUTABLE_MISSING_PORTFOLIO_DENOMINATOR`. Missing turnover is never
coerced to zero.

Downside capture is also never coerced to zero when SPY has no negative
sessions in the evaluation window. In that case both aggregate and per-path
evidence carry explicit not-applicable states. A numeric zero is valid only
when SPY did decline and the evaluated path had no loss on those same sessions.
All ready paths must share the exact SPY completed-session calendar.

Tactical entry-thesis and timing-category references, and long-horizon expected
return range and calibration references, are preserved as frozen payload
fields. The engine does not create or reinterpret those model results.

## Persistence and corrections

The output is a canonical `ForwardOutcomeBatchV21`, so the existing V18 ledger
and v2.1.1 repository provide exact replay, append-only result versions, and a
single predecessor for corrections. Supplemental diagnostics are controlled
payload data and are not silently written into unsupported V18 metric codes.

## Current repository status

The checked-in preflight is honestly blocked by `BLOCKED_NO_ENROLLMENT` and
`NO_MATURED_OUTCOMES`. It performs zero network requests, zero database writes,
and computes no real outcomes.

Quality-report resampling, Holm correction, repeated-cohort scheduling, and
final model-quality conclusions remain separate Gate Z responsibilities. This
engine produces the deterministic maturity evidence they consume.
