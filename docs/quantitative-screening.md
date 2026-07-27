# Quantitative Screening Design

The executable v1 methodology and provider acceptance gate are defined in
[Quantitative Screening v1 Specification and Data Acceptance Plan](quantitative-screening-v1-specification.md).
This design document remains the product-level rationale and scope boundary.

## Purpose

The quantitative workstream must discover research candidates across a broad
United States equity universe without treating one score as a universal
definition of a good stock. It must distinguish company quality, price
attractiveness, market condition, evidence coverage, and portfolio fit.

The first objective is not to predict a guaranteed return. It is to produce a
repeatable candidate-selection process that can be tested against simple
benchmarks and inspected when it fails.

## Analysis Layers

```text
Point-in-time market and fundamental data
                    |
                    v
Eligibility and data-quality filters
                    |
                    v
Base company factors
                    |
                    v
Sector, size, and company-type cohorts
                    |
                    v
Strategy-specific quantitative rankings
                    |
                    v
Evidence-review queue
                    |
                    v
AI-reviewed candidate set
                    |
                    v
User portfolio fit and decision support
```

The layers must remain separately observable. A stock with quantitative data
but no completed evidence review must not appear as though it has received a
final research assessment.

## Initial Strategy Paths

### Quality Compounder

This path looks for mature companies that have:

- Durable profitability
- Consistent returns on invested capital
- Strong cash conversion
- Stable or improving margins
- Manageable debt
- Limited shareholder dilution
- Sustainable per-share growth
- A valuation that is not disconnected from fundamentals

### Undervalued Quality

This path looks for companies that have:

- Acceptable business quality and financial survival characteristics
- A valuation discount relative to conservative value ranges, history, or
  appropriate peers
- No obvious evidence that low valuation is solely explained by structural
  deterioration
- Sufficient liquidity and data quality
- A documented margin-of-safety hypothesis

`Emerging Growth`, banks, insurers, REITs, resource companies, biotechnology,
and special situations require separate eligibility rules or specialized
models. The first general-company model must mark these cases explicitly
rather than force them through unsuitable formulas.

## Separate Assessments

The platform must preserve separate dimensions:

- Business quality
- Financial strength
- Earnings and cash-flow stability
- Growth quality
- Valuation
- Margin of safety
- Shareholder dilution and capital allocation
- Near-term market condition
- Data confidence
- Risk flags

Near-term market condition and long-term investment assessment must not be
collapsed into an unexplained average. `Medium-term` scoring is deferred until
a distinct decision problem and testable methodology are defined.

## Cohort Comparison

Companies should first be compared within meaningful cohorts:

```text
sector x size cohort x company type x strategy path
```

The cohort design should:

- Use versioned size thresholds or market-cap percentiles
- Prefer robust statistics such as medians and winsorized distributions
- Preserve raw values alongside normalized values
- Avoid filling missing observations with zero
- Report cohort size and data coverage
- Avoid guaranteeing a fixed candidate count when too few companies qualify

Sector membership must come from a versioned classification mapping. The
provider's raw classification and the platform's normalized classification
must both be retained.

## Sector Analysis

### Sector Market Condition

The first stage may use `SPY` and the major United States sector ETFs to
calculate:

- 20-, 60-, and 120-trading-day return
- Relative strength versus `SPY`
- Volatility
- Maximum drawdown
- Trend stability

This is a market-condition assessment, not a long-term fundamental rating.

### Sector Fundamental Attractiveness

The later stage aggregates point-in-time constituent information:

- Median and distribution of profitability
- Earnings and free-cash-flow growth
- Financial strength
- Valuation
- Percentage of profitable companies
- Percentage of companies meeting quality and margin-of-safety requirements
- Equal-weight, market-cap-weighted, and market-breadth perspectives
- Data coverage and effective constituent date

Current constituent membership must not be used retroactively in a historical
backtest.

## Quantitative and AI Responsibilities

Deterministic code owns:

- Eligibility
- Financial ratios
- Normalization
- Strategy formulas
- Ranking
- Risk constraints
- Backtest execution

AI owns constrained evidence work:

- Extracting structured facts from filings and trusted documents
- Identifying supporting and contradictory evidence
- Detecting qualitative risks not represented in structured factors
- Producing cited, source-grounded explanations

AI must not invent a free-form numeric score. It may produce a structured
evidence classification that triggers a documented confidence change, warning,
limited ranking adjustment, or candidate block.

## Coverage States

Every security must expose a coverage state:

- `PRICE_ONLY`
- `QUANT_ELIGIBLE`
- `QUANT_INELIGIBLE`
- `AI_QUEUED`
- `AI_REVIEWING`
- `AI_REVIEWED`
- `STALE`
- `INSUFFICIENT_DATA`
- `ANALYSIS_FAILED`
- `SPECIALIZED_MODEL_REQUIRED`

The platform should report universe size, price coverage, fundamental coverage,
quantitatively scored count, evidence-reviewed count, and exclusions by reason.

## Evidence-Review Queue

AI review should be prioritized for:

1. Current user holdings
2. Explicit user requests
3. Watchlist securities
4. New high-ranking quantitative candidates
5. Material ranking changes
6. New filings or material company events
7. Expired research snapshots

Public company research may be cached by source snapshot, strategy version,
prompt version, and model version. Portfolio-specific analysis remains
user-scoped.

## Required Data Contract

The provider evaluation must confirm:

- Security master and stable identifiers
- Listing, delisting, and symbol-change history
- Adjusted and unadjusted daily OHLCV
- Splits and dividends
- Quarterly and annual income statements
- Balance sheets and cash-flow statements
- Diluted and basic shares outstanding
- Historical market capitalization or enough data to reconstruct it
- Filing period, filing date, and availability timestamp
- Restatements and revisions where available
- Sector and industry classification
- Benchmarks and sector ETFs
- Provider, effective, ingestion, and quality timestamps
- Personal and future commercial licensing constraints

Provider-derived ratios may be retained for validation, but the platform should
calculate strategy-critical ratios from normalized source fields.

## Provider Evaluation Plan

Twelve Data remains the development provider for the existing small price
slice. SEC EDGAR is the preferred primary-source filing and XBRL evidence
provider.

Before a recurring paid-data commitment:

1. Define a 20-security validation set spanning size, sector, company type,
   corporate actions, symbol changes, and delisted cases.
2. Compare candidate-provider fields with SEC filings and known price events.
3. Verify point-in-time dates, null handling, units, currencies, adjustments,
   and identifier stability.
4. Record coverage gaps and endpoint costs.
5. Approve one provider for a one-month validation and backfill period.

EODHD is the current leading paid candidate for personal research because its
available packages combine historical prices, fundamentals, corporate actions,
and delisted data. This is not a final vendor selection. Commercial use
requires a separate licensing review.

## First Implementation Slice

The next analytics implementation should:

1. Define the validation universe and provider acceptance tests.
2. Add replaceable provider contracts for reference, price, corporate-action,
   and fundamental data.
3. Ingest sufficient history for the validation universe.
4. Calculate explicit base factors for general non-financial companies.
5. Produce versioned `Quality Compounder` and `Undervalued Quality` rankings.
6. Store raw factors, normalized contributions, exclusions, as-of dates, and
   strategy versions.
7. Compare results with `SPY`, equal-weight, simple value, simple quality, and
   simple momentum baselines.
8. Defer AI review until deterministic rankings and data lineage pass
   validation.

## Acceptance Criteria

- Identical inputs and strategy versions reproduce identical results.
- Every included and excluded security has an explicit reason.
- Missing data never silently becomes zero or a neutral factor.
- Historical calculations use only information available at the decision time.
- Delisted securities and corporate actions are represented in evaluation.
- Results remain separated by strategy path and cohort.
- Quantitative-only and evidence-reviewed rankings are visibly distinct.
- Backtests include realistic execution timing, costs, and turnover.
- No score is presented as a probability of profit or a guaranteed outcome.
