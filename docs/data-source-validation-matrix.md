# Data Source Validation Matrix

## Purpose

This matrix records whether a provider can support Objective Rating v1. A
marketing or documentation claim is not production acceptance. No paid service
was purchased during this validation.

Status meanings:

- `VALIDATED_LIMITED`: an existing entitlement returned a tested subset.
- `VALIDATED_PRIMARY_SOURCE`: live primary-source fields were verified.
- `DOCUMENTED_CANDIDATE`: official documentation describes the capability, but
  entitlement, historical depth, point-in-time semantics, and licensing remain
  unverified.
- `NOT_VERIFIED`: the required behavior was not established.

## Required Field Matrix

| Domain | Minimum required fields | PIT requirement |
| --- | --- | --- |
| Security identity | Durable provider ID, CIK, ticker history, name, exchange/MIC, instrument type, active status, listing and delisting dates | Effective dates for identifier and classification changes |
| Classification | Raw sector, industry, SIC, normalized company type and mapping version | Classification effective at the decision time |
| Daily price | Unadjusted OHLCV, split-adjusted close, total-return-adjusted close or reconstructable actions, exchange timezone | Trading date and documented adjustment policy |
| Corporate actions | Split date and ratio; dividend declaration, ex, record, pay dates, amount and currency; delisting proceeds | Action must not affect dates before it became effective |
| Income statement | Revenue, gross profit, operating income, pretax income, tax, net income, EPS, basic and diluted weighted-average shares, interest and D&A | Period end, filing/acceptance time, form, accession and revision |
| Balance sheet | Cash, current assets/liabilities, total assets, short/long debt, equity and minority interest | Period end, filing/acceptance time, form, accession and revision |
| Cash flow | CFO, capex, issuance, repurchase and dividends | Period end, filing/acceptance time, form, accession and revision |
| Historical valuation | Historical market cap or PIT shares and price sufficient to reconstruct it | Value and share count available on the simulated date |
| Lineage | Provider, source reference, period, `filedAt`, `availableAt`, `ingestedAt`, currency, unit, revision, quality and content hash | Mandatory for every factor input used in a backtest |

## Provider Comparison

| Source | Security and ticker history | Prices and actions | Statements and shares | PIT/revisions | Delisted coverage | v1 status and recommendation |
| --- | --- | --- | --- | --- | --- | --- |
| Twelve Data | Profile, exchange/MIC, type and optional FIGI/ISIN/CUSIP are documented; durable symbol-event history is not yet proven | Daily OHLCV supports `none`, `splits`, `dividends`, and `all`; splits and dividends are documented | Quarterly/annual income, balance sheet and cash flow endpoints include basic/diluted shares; historical market cap is documented on higher tiers | Fundamental `last_change` is documented, but filing acceptance and restatement history were not proven | Not proven | `VALIDATED_LIMITED` for adjusted daily prices. Keep the existing integration; do not approve it alone for PIT fundamentals. |
| SEC EDGAR | CIK, tickers, exchanges, submissions and accession references | No market prices, total returns or complete corporate-action feed | Primary filed XBRL facts and statements, including many historical share facts | Live responses expose form, filed date, period, accession and submission acceptance time; issuer extensions still require mapping | Filing history remains available, but complete delisted price history does not | `VALIDATED_PRIMARY_SOURCE`. Use as the fundamental lineage authority and provider cross-check, not as the sole dataset. |
| EODHD | Product catalogue documents instruments, identifier mapping and delisted-company data | EOD, splits and dividends are documented | Fundamentals and historical market cap are documented | Historical availability and revision semantics require a paid-key test | Documented, not tested | `DOCUMENTED_CANDIDATE`; leading one-month acceptance candidate if free sources cannot close the PIT and delisting gaps. |
| Financial Modeling Prep | Company profiles and delisted-company endpoints are documented | Non-split-adjusted and dividend-adjusted EOD, splits and dividends are documented | Annual/quarterly statements and as-reported filings are documented | Filing dates exist in documented outputs, but historical revision/availability semantics require testing | Documented, not tested | `DOCUMENTED_CANDIDATE`; retain as the main alternative to EODHD. |
| Massive / Polygon | Dated ticker reference, CIK/FIGI, inactive tickers and experimental ticker events are documented | Adjusted/unadjusted aggregates, splits and dividends are documented | Annual, quarterly and TTM statements are documented through the financials expansion | EDGAR index and financial endpoints are documented; revision and historical availability behavior require testing | Inactive tickers are documented, final-return completeness is not tested | `DOCUMENTED_CANDIDATE`; strongest reference/price alternative, but not approved for PIT fundamentals. |

## Live Validation Performed on 2026-07-26

The existing Twelve Data entitlement returned 162 adjusted daily observations
from 2025-12-01 through 2026-07-24 for each of `AAPL`, `MSFT`, `TGT`, `GE`,
`META`, and `SPY`. Only derived returns, volatility, drawdown, request policy,
and row hashes are retained in the repository. Raw licensed responses and the
API key are not stored.

SEC EDGAR live responses for Apple CIK `0000320193` connected the 2026-05-01
10-Q submission acceptance timestamp and accession
`0000320193-26-000013` to an XBRL revenue fact with period end 2026-03-28,
form, filed date, accession, USD unit, and value. This proves the minimum
lineage fields for the tested fact, not universal issuer/tag coverage.

The automated acceptance harness then completed the 20-security fixture.
Nineteen current securities returned usable adjusted history; delisted `TWTR`
did not resolve through its former current-symbol route. AAPL returned five
split and 82 dividend events. The current entitlement did not establish
general corporate-action coverage, META's dated ticker change, or TWTR's
delisting return. See the
[derived acceptance report](provider-acceptance-report-2026-07-26.md).

SEC validation completed all 20 identities/model gates and all ten
mature-company filing lineages. Historical PIT fixtures cover AAPL, MSFT and
META filing selection. AAPL now has bounded TTM, 12-quarter stability, three-
year growth and 12-month valuation fixtures. The cross-issuer TTM bridge passed
for MSFT and TGT. TGT did not expose a compatible standard gross-profit fact,
and AAPL's tested quarterly filing did not expose compatible interest expense.

Automated SEC requests require an explicitly configured `SEC_USER_AGENT`
containing an application name and real contact address. The tool does not read
or transmit Git identity automatically; without this setting, SEC checks safely
return `NOT_VERIFIED`.

## Acceptance Conclusion

The rating calculation, PIT filing selection, core SEC TTM bridge and limited
price reconstruction are feasible without a new purchase. A survivorship-safe
historical production backtest is `NOT_VERIFIED` because symbol history, final
delisting returns, issuer-specific statement gaps, complete revision history,
and commercial licensing remain incomplete.

Free-source acceptance is therefore:

- `ACCEPTED` for the deterministic v1 calculation and contract prototype.
- `ACCEPTED_LIMITED` for SEC primary-source lineage and issuer sampling.
- `ACCEPTED_LIMITED` for current-security adjusted daily prices.
- `NOT_ACCEPTED` for a production full-market PIT backtest dataset.

The next paid trial, if separately authorized, must focus on dated ticker
events, delisting proceeds, historical revisions, general corporate actions,
AAPL interest expense and TGT gross profit. Broad endpoint availability alone
is not a reason to subscribe.

No provider may move from `DOCUMENTED_CANDIDATE` to approved until the
20-security fixture passes field coverage, units, action dates, null behavior,
identifier continuity, PIT revisions, rate limits, cost, and personal and
commercial license review.

## Official Documentation Reviewed

- [Twelve Data time series](https://twelvedata.com/docs/llms/market-data/time-series.md)
  and [fundamental endpoints](https://twelvedata.com/docs)
- [SEC EDGAR APIs](https://www.sec.gov/search-filings/edgar-application-programming-interfaces)
- [EODHD financial APIs](https://eodhd.com/financial-apis)
- [Financial Modeling Prep stable API](https://site.financialmodelingprep.com/developer/docs/stable)
- [Massive Stocks REST API](https://massive.com/docs/rest/stocks)

## Expanded Development Universe

`provider-acceptance-us-v2.0.0` contains 66 unique symbols. The paced
2026-07-27 Twelve Data run returned adjusted daily history for 65 and left
only delisted `TWTR` as `NOT_VERIFIED`; no daily-price check failed. This is a
broader development-price validation, not production PIT acceptance or proof
that the observations have been persisted to PostgreSQL.
