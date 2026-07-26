# Provider Acceptance Report: 2026-07-26

## Scope

This derived report covers the complete 20-security acceptance universe. The
read-only checks were executed in paced batches because the existing Twelve
Data plan permits eight API credits per minute. The price window was
2020-01-01 through 2026-07-26.

No raw provider response, API key, private contact information, or licensed
bulk dataset is stored.

## Result

| Result | Count |
| --- | ---: |
| Securities | 20 |
| `PASS` checks | 47 |
| `FAIL` checks | 0 |
| `NOT_VERIFIED` checks | 56 |
| `NOT_APPLICABLE` checks | 4 |
| Production backtest status | `NOT_VERIFIED` |

`FAIL` remains zero because an unavailable entitlement, missing historical
identifier endpoint, unconfigured SEC identity, or unsupported delisted ticker
is an unverified capability rather than proof that an observed financial value
is wrong.

## Daily Price Evidence

| Coverage | Securities | Result |
| --- | --- | --- |
| 1,648 observations, 2020-01-02 through 2026-07-24 | AAPL, MSFT, META, WMT, MCD, CAT, ADP, NKE, TGT, PLAB, GE, JPM, PGR, O, XOM, MRNA, SPY, XLK | `PASS` |
| 1,255 observations, 2021-07-26 through 2026-07-24 | LCID | `PASS`; shorter public history is expected |
| Current ticker rejected | TWTR | `NOT_VERIFIED`; a delisted-symbol dataset is required |

Twelve Data identified `O` as `REIT`, `SPY` and `XLK` as `ETF`, and the
remaining current equities as `COMMON_STOCK`. Provider instrument type is
evidence but does not replace the versioned company-type gate.

## Corporate Actions and Identity Evidence

| Check | Result |
| --- | --- |
| AAPL split history | `PASS`; five events from 1987-06-16 through 2020-08-31 |
| AAPL dividend history | `PASS`; 82 events from 1988-11-21 through 2026-05-11 |
| WMT and TGT dividend history | `NOT_VERIFIED`; endpoint is outside the current plan |
| GE split history | `NOT_VERIFIED`; endpoint is outside the current plan |
| META `FB` to `META` dated identifier event | `NOT_VERIFIED`; tested contract exposes no dated event |
| TWTR delisting proceeds and final return | `NOT_VERIFIED` |

The separate SEC feasibility check already connected Apple's 2026-05-01 10-Q
acceptance timestamp and accession `0000320193-26-000013` to XBRL facts.
Recurring automated SEC access is intentionally not attempted unless
`SEC_USER_AGENT` is explicitly set to an application name plus a real contact
address. Repository Git identity is never read or transmitted automatically.

## Decision

The existing Twelve Data plan is sufficient for adjusted daily-price
validation of current securities and AAPL action examples. The 20-security run
also demonstrated that client-side pacing is required: the acceptance CLI now
defaults to an eight-second minimum request interval. It is not sufficient to
establish symbol-change history, delisting returns, or general
corporate-action coverage.

Do not purchase a service yet. The next useful validation is:

1. Configure a deliberate SEC contact identity locally and rerun the 20
   securities.
2. Complete SEC tag mapping for the mature-company cases.
3. Evaluate a bounded paid trial only for the remaining identifier, delisting,
   revision, and corporate-action gaps.
