# Quantitative Screening v1 Specification and Data Acceptance Plan

## Status and Scope

This document defines the design and data-validation gate for the first
deterministic United States equity screen. It covers only the `Quality
Compounder` (`QC`) and `Undervalued Quality` (`UQ`) strategy paths for mature,
non-financial operating companies. It is a research-candidate ranking, not a
buy recommendation, return forecast, portfolio allocation, or trading system.

No AI score, user workflow, portfolio construction, brokerage connection, or
production-universe import is in scope for this gate. A provider must pass the
acceptance tests below before the corresponding production implementation is
approved.

## Horizon Separation

The system does not produce a universal stock score.

| Horizon | v1 conclusion | Interpretation |
| --- | --- | --- |
| `LONG_TERM` | Separate quality, valuation, `QC-v1.0.0`, and `UQ-v1.0.0` results | A deterministic assessment of a mature operating company and the price paid for it. |
| `NEAR_TERM` | `NEAR_TERM-v1.0.0` market-condition score and `FAVORABLE`, `NEUTRAL`, or `UNFAVORABLE` label | A one-to-three-month description of price behavior. It is not a trade instruction and does not modify long-term scores. |
| `MEDIUM_TERM` | `NOT_DEFINED` with no score | No testable medium-term decision problem has been approved. |

The near-term score uses 20-, 60-, and 120-trading-day total return, 60-day
relative strength versus `SPY`, 60-day annualized volatility, 120-day maximum
drawdown, and 120-day trend stability. The weights are 10%, 20%, 20%, 20%,
10%, 10%, and 10%, respectively.

## Universe and Eligibility

An observation is eligible only when all rules below are true at the rebalance
timestamp. Rules are versioned as `universe-us-general-company-v1.0.0`.

| Area | v1 rule |
| --- | --- |
| Market and instrument | A primary, USD-denominated common share listed on NYSE, Nasdaq, or NYSE American; no ETF, fund, closed-end fund, preferred share, warrant, right, unit, SPAC, partnership, or depositary receipt. |
| Reporting basis | A United States SEC reporting issuer with usable 10-K and 10-Q history. The primary CIK and a durable vendor identifier are required. |
| Trading history | At least five completed fiscal years, twelve completed fiscal quarters, and 252 prior trading days of price history. |
| Size and liquidity | Point-in-time market capitalization of at least USD 500 million and 60-trading-day median dollar volume of at least USD 2 million. Dollar volume is unadjusted close multiplied by reported volume. |
| Financial coverage | The trailing twelve months (TTM), prior TTM, and three annual observations needed by the requested factor must be available and internally valid. |
| Filing freshness | The newest required quarterly or annual filing must be no more than 150 calendar days old; annual-only factors may not use an annual filing older than 450 days. |
| General-company model | The normalized company type must be `MATURE_OPERATING_COMPANY`. An explicit manual override is allowed only with a reason, effective dates, and reviewer identity. |

The following types receive `SPECIALIZED_MODEL_REQUIRED`, never a v1 score:

- Banks, insurers, brokers, asset managers, and other financial businesses.
- REITs, mortgage REITs, and real-estate operating companies whose economics
  require an FFO/AFFO model.
- Oil, gas, coal, metals, mining, and other extractive/resource businesses.
- Biotechnology, pre-revenue drug development, and clinical-stage issuers.
- Emerging-growth issuers that do not meet the history rule, loss-making
  turnaround cases, recent IPOs, SPACs, funds, and special situations.

Classification uses a dated, versioned mapping from provider sector/industry,
SEC SIC, instrument type, and a reviewed exception table. Raw provider values
and the normalized result are both retained. A classification uncertainty is
an exclusion, not a guess.

## Required Raw Data and Lineage

Every stored value must carry `provider`, `provider_record_id` when available,
`source_url_or_accession`, `period_end`, `filed_at`, `available_at`,
`ingested_at`, `currency`, `unit`, `revision_status`, and `quality_status`.
`available_at` is mandatory for backtests.

| Domain | Required fields |
| --- | --- |
| Security master | CIK, ticker history, vendor durable identifier, issuer name, exchange/MIC, instrument type, listing and delisting dates, sector, industry, SIC, currency, and classification effective dates. |
| Prices and actions | Daily unadjusted OHLCV; split-adjusted and total-return-adjusted close when supplied; dividend ex-date, pay date, amount, currency; split effective date and ratio; delisting date and final return when available. |
| Income statement | Revenue, cost of revenue, gross profit, operating income, pretax income, income tax, net income, basic EPS, diluted EPS, basic weighted-average shares, diluted weighted-average shares, interest expense, and D&A when reported. |
| Balance sheet | Cash and equivalents, current assets, current liabilities, total assets, short- and long-term debt, total debt where supplied, total equity, and minority interest. |
| Cash flow | Cash flow from operations, capital expenditures, free cash flow only as a provider cross-check, share issuance, repurchases, and common dividends. |
| Market and benchmark | Historical market capitalization or reconstructable point-in-time shares and price; `SPY`; sector ETFs used only for the separate market-condition view. |

Strategy-critical ratios are calculated from normalized fields. Vendor ratios
are comparison-only fields and must never be silently substituted.

## Point-in-Time Rules

1. A fundamental observation becomes usable at the SEC acceptance timestamp
   plus one full United States trading session. When that timestamp is absent,
   it is not PIT-eligible.
2. The applicable statement is the most recent filing available by the
   rebalance cutoff, not the most recent fiscal period visible today. Each fact
   retains form, accession, fiscal period, filing date, and revision lineage.
3. A restatement replaces an earlier value only from the later filing's
   availability time. It must not rewrite a historical ranking before then.
4. Security membership, ticker mappings, classifications, delistings, prices,
   and corporate actions use records effective on the simulated date. Current
   constituents and current tickers must not be projected backward.
5. Rankings are calculated after the last regular-session close on the last
   trading day of each calendar month. Orders are assumed to execute at the
   next trading day's close, with the same convention applied to benchmarks.
6. Raw vendor responses or a content hash, parser version, and normalization
   version are preserved so a run can be reproduced after a provider revision.

## Cohorts and Normalization

The production comparison key is:

```text
normalized sector x market-cap band x MATURE_OPERATING_COMPANY x strategy path
```

Market-cap bands are fixed for v1 at the rebalance date: `SMALL` (USD 0.5–2B),
`MID` (USD 2–10B), `LARGE` (USD 10–200B), and `MEGA` (USD 200B or more). A
cell with fewer than 20 eligible observations does not produce a rank. It may
fall back, in order, to `sector x company type` (minimum 30) and then all
general companies (minimum 100); the fallback level is stored with every
factor. No fixed candidate count is promised.

For a factor that passes its validity rule, values are winsorized at the 5th
and 95th percentile of its active cohort, then transformed to an ascending or
descending percentile score from 0 to 100. Raw values, winsorized values,
cohort count, direction, and normalized score are all retained.

Each factor has exactly one status: `VALID`, `MISSING`, `INVALID`, or
`NOT_APPLICABLE`. v1 does not redistribute a missing factor's weight. If any
factor required by a strategy is not `VALID`, that strategy returns
`INSUFFICIENT_DATA` with no numeric score.

## Base Factors

All calculations use the latest PIT-eligible TTM and the prior available TTM
unless stated otherwise. `Capex` is the absolute cash-flow value. Values with
an invalid denominator are missing, not zero.

For duration metrics reported as cumulative year-to-date values, v1 derives TTM
with version `TTM-YTD-BRIDGE-v1.0.0`:

`TTM = prior fiscal-year annual + current YTD - prior-year comparable YTD`

The three inputs must have the same metric and unit, comparable YTD durations,
chronologically compatible periods, and `availableAt <= asOfTime`. Every
accession remains in lineage. Four reported 10-Q values must not be summed
unless they are independently verified discrete quarters.

Weighted-average duration metrics such as diluted shares use
`TTM-WEIGHTED-YTD-BRIDGE-v1.0.0`. Each reported average is multiplied by its
inclusive period days before applying the annual-plus-YTD bridge, then divided
by the derived TTM day count. Per-share growth and dilution use these weighted
TTM shares, not point-in-time shares outstanding.

| Dimension | Formula and validity |
| --- | --- |
| Return on invested capital | `NOPAT / average(invested capital)` where `NOPAT = operating income x (1 - clamped effective tax rate)` and the tax rate is clamped to 0–35%; `invested capital = total equity + total debt - cash and equivalents`. Both current and prior invested capital must be positive. |
| Free-cash-flow margin | `(CFO - Capex) / revenue`; revenue must be positive. |
| Cash conversion | `(CFO - Capex) / net income`; valid only when net income is positive. |
| Margin quality | Arithmetic mean of current TTM gross margin, current TTM operating margin, three-year gross-margin change, and three-year operating-margin change. All four components remain visible in lineage. |
| Per-share growth | Three-year CAGR of diluted EPS and FCF per diluted share; valid only when both endpoint values are positive. |
| Stability | Arithmetic mean of the population coefficient of variation for quarterly operating margin and quarterly FCF margin. Each coefficient is population standard deviation divided by absolute mean. Lower is better; histories must be aligned and contain at least eight valid quarters. |
| Debt service | `net debt / EBITDA` (lower is better) and `EBIT / absolute interest expense` (higher is better). Each requires a positive denominator. Net cash is retained as a value, not clipped to zero. |
| Dilution | Three-year CAGR of diluted weighted-average shares. Lower or negative growth is better. Split-adjusted comparable shares are required. |
| Earnings yield | `TTM EBIT / enterprise value`; enterprise value is market cap plus total debt plus minority interest minus cash and equivalents. Both numerator and EV must be positive. |
| Free-cash-flow yield | `TTM FCF / market capitalization`; market capitalization must be positive. |
| Valuation discount | The mean of available inverse valuation percentile scores: earnings yield, FCF yield, and the security's own five-year FCF-yield percentile. A historical comparator needs 12 PIT-eligible monthly observations. |

## Strategy Formulas

Factor scores are cohort percentiles. A missing required factor makes the
security ineligible for that strategy; there is no implicit neutral score.

`QC-v1.0.0` requires positive TTM operating income and FCF, positive median
three-year ROIC, and no hard risk flag. Its exact factor weights are:

| Factor | Weight |
| --- | ---: |
| ROIC | 25% |
| FCF margin | 10% |
| Cash conversion | 10% |
| Margin quality | 7.5% |
| Stability | 7.5% |
| Diluted EPS growth | 7.5% |
| FCF-per-diluted-share growth | 7.5% |
| Net debt / EBITDA | 5% |
| Interest coverage | 5% |
| Dilution | 10% |
| Valuation guardrail | 5% |

The valuation guardrail contributes zero when the security is in the most
expensive decile on both earnings yield and FCF yield. It does not convert a
quality score into a price target.

`UQ-v1.0.0` requires positive TTM operating income, positive TTM FCF, positive
equity, and no hard risk flag. Its exact factor weights are:

| Factor | Weight |
| --- | ---: |
| Earnings yield | 15% |
| FCF yield | 20% |
| Own-history FCF-yield percentile | 10% |
| ROIC | 15% |
| Operating margin | 10% |
| Net debt / EBITDA | 7.5% |
| Interest coverage | 7.5% |
| Cash conversion | 5% |
| Stability | 5% |
| Dilution | 5% |

The `margin-of-safety` field is the valuation-discount component and its input
coverage, not an assertion that a loss cannot occur.

`qualityScore` is the QC contribution excluding its 5% valuation guardrail,
divided by 0.95. `valuationScore` is the sum of the three UQ valuation
contributions divided by 0.45. These dimension scores explain the distinction
between a good company and an attractively priced security; neither is a
probability of profit.

## Risk Exclusions and Flags

Hard exclusions are: restricted company type; stale or missing required data;
negative equity; negative TTM operating income or FCF where the strategy
requires positivity; market-cap or liquidity failure; unresolvable identifier
history; invalid accounting units/currency; and any failed PIT lineage check.

Soft flags do not change v1 scores but are stored and shown separately:
three-year revenue decline, margin deterioration, net-debt/EBITDA above 3,
interest coverage below 3, dilution CAGR above 3%, an audit going-concern
warning, a qualified filing parser result, or a provider/SEC material mismatch.

## Backtest Design and Acceptance

The first backtest is monthly equal-weight top-decile selection within each
strategy path, capped at 25 names, with no portfolio optimizer. It is an
evaluation harness, not an implementation commitment. It records the complete
universe, exclusions, scores, execution prices, 10 bps one-way transaction
cost, 10 bps one-way slippage, turnover, and delisting proceeds. Cash is held
when fewer names qualify.

Baselines are `SPY` total return, eligible-universe equal weight, a simple
quality composite, a simple value composite, and a simple 12-month momentum
composite. All use the same eligible PIT universe and execution convention.

Acceptance is methodological, not a return target:

- Two identical runs against the same snapshot produce identical rankings,
  exclusions, and trades.
- The 20-security checks pass, including at least one delisted and one
  renamed security; no date or action is silently discarded.
- A sampled set of 30 filing facts across the validation universe matches the
  cited SEC filing's value, unit, period, and availability timestamp.
- A sampled set of 20 price/action observations matches the approved price
  provider and the documented adjustment policy.
- PIT adversarial tests show that a later filing, later restatement, current
  constituent list, or post-event corporate action cannot change an earlier
  decision.
- At least ten years of data, or the maximum verified provider history when
  shorter, is partitioned before tuning into a development period, a sealed
  holdout, and walk-forward folds. Parameters are frozen before the holdout.
- Reports include return, excess return, annualized volatility, maximum
  drawdown, recovery time, Sharpe, Sortino, beta, turnover, estimated costs,
  sector exposure, and coverage. No minimum CAGR or alpha is an acceptance
  condition.

## Twenty-Security Provider Acceptance Universe

This is a data test set, not a recommendation list. `Expected v1 outcome` is
the expected classification after provider and SEC validation.

| Symbol or history | Test purpose | Expected v1 outcome |
| --- | --- | --- |
| AAPL | Mega-cap, multiple splits, dividends | Eligible candidate if fields pass |
| MSFT | Mega-cap software, recurring cash flow | Eligible candidate if fields pass |
| META / FB | Ticker change and mature platform company | Eligible under one durable identity |
| WMT | Defensive consumer staples and dividends | Eligible candidate if fields pass |
| MCD | Franchise model and debt-service fields | Eligible candidate if fields pass |
| CAT | Cyclical industrial and capex | Eligible candidate if fields pass |
| ADP | Asset-light services and share data | Eligible candidate if fields pass |
| NKE | Consumer discretionary and margin cycle | Eligible candidate if fields pass |
| TGT | Retail margin stress and dividend history | Eligible candidate if fields pass |
| PLAB | Smaller general operating company | Eligible candidate if fields pass |
| GE | Major restructuring, spin-off, and reverse split | Manual review; not a clean acceptance candidate |
| JPM | Bank | Specialized model required |
| PGR | Insurer | Specialized model required |
| O | REIT | Specialized model required |
| XOM | Extractive resource company | Specialized model required |
| MRNA | Biotechnology | Specialized model required |
| LCID | Recent loss-making growth issuer | Specialized model required or ineligible |
| TWTR (delisted) | Delisting and final-return history | Historical-only; must remain discoverable |
| SPY | Benchmark total-return and corporate-action behavior | Benchmark only |
| XLK | Sector ETF reference history | Market-condition reference only |

For each row, the acceptance worksheet records the exact endpoint, request
date, plan, identifier, response hash, field coverage, units, nulls, observed
action dates, SEC cross-check accession, and pass/fail reason.

## Provider Feasibility Conclusion

| Source | Documented capability relevant to v1 | Gate conclusion |
| --- | --- | --- |
| Twelve Data | Daily OHLCV with `all`, `splits`, `dividends`, or `none` adjustment modes; profile classification; splits; dividends; quarterly and annual income statement, balance sheet, cash flow; diluted/basic shares; historical market cap; and fundamental last-change endpoints. Full statement history and historical market cap require higher paid plan tiers. | Suitable for development price ingestion and potentially a paid all-in-one validation. Not approved for PIT backtesting until a paid-key test proves historical availability timestamps, revisions/restatements, delisted coverage, and durable ticker history. |
| SEC EDGAR | Primary issuer submissions and XBRL company facts supply CIK, forms, filing and acceptance metadata, period ends, units, accession references, statements, and many share facts. | Required primary-source validator and fundamental lineage source. It is not a price, corporate-action, sector-taxonomy, or complete delisted-price provider; XBRL tags require a versioned mapping and issuer extensions need fallback handling. |
| EODHD paid validation candidate | Its current public product catalogue lists EOD history, fundamentals, splits/dividends, delisted-company data, historical market capitalization, instrument/exchange data, and identifier mapping. | Leading one-month paid validation candidate because its stated coverage aligns with the complete contract. Approval is conditional: a paid-key, 20-security extract must prove actual endpoint access, revision and availability semantics, delisted records, adjustment policy, rate limits, cost, and personal/commercial license terms. |

The v1 data gate is therefore **conditionally feasible but not yet certified**.
Twelve Data plus SEC EDGAR can validate much of the contract, but the current
repository has only a bounded Twelve Data price integration and no stored PIT
fundamentals or security-history model. EODHD should be tested before any
recurring commitment; if it cannot expose PIT revisions and historical
availability adequately, it must be rejected for backtesting even if its
current-data coverage is broad.

### Documentation Checked

The interface findings above were checked on 2026-07-26 against the providers'
published documentation and live SEC data responses:

- [Twelve Data time series](https://twelvedata.com/docs/llms/market-data/time-series.md),
  [income statement](https://twelvedata.com/docs/llms/fundamentals/income-statement.md),
  [balance sheet](https://twelvedata.com/docs/llms/fundamentals/balance-sheet.md),
  [cash flow](https://twelvedata.com/docs/llms/fundamentals/cash-flow.md),
  [splits](https://twelvedata.com/docs/llms/fundamentals/splits.md),
  [dividends](https://twelvedata.com/docs/llms/fundamentals/dividends.md),
  [market capitalization](https://twelvedata.com/docs/llms/fundamentals/market-cap.md),
  and [last changes](https://twelvedata.com/docs/llms/fundamentals/last-changes.md).
- [SEC EDGAR application programming interfaces](https://www.sec.gov/search-filings/edgar-application-programming-interfaces),
  including the live `submissions`, `companyfacts`, and XBRL `frames` response
  formats for Apple CIK `0000320193`.
- [EODHD financial APIs product catalogue](https://eodhd.com/financial-apis).

## Deferred Implementation Decision

After the 20-security worksheet and PIT tests pass, implement only the
replaceable provider contracts, normalized storage, deterministic eligibility,
and the two versioned ranking snapshots. Do not add AI review, user accounts,
portfolio allocation, or specialized-industry scores in that slice.
