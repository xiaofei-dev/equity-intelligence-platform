# MVP Scope

## MVP Goal

Deliver a usable daily equity research workflow that can be demonstrated, evaluated, and extended without connecting to a brokerage account.

## Primary User Journey

1. The system updates daily market and fundamental data.
2. Eligibility rules remove unsuitable or insufficiently liquid securities.
3. Strategy-specific factors rank companies within appropriate sector, size,
   and company-type cohorts.
4. The system presents a small quantitative candidate list with eligibility
   and factor explanations.
5. AI reviews source documents and identifies qualitative strengths, risks, and unresolved questions.
6. The portfolio module evaluates candidate fit and compares new-money-only,
   constrained-rebalancing, and target-portfolio simulations.
7. The user reviews the evidence and records a decision.
8. The platform tracks subsequent performance against a benchmark.

## In Scope

### Market Coverage

- One equity market
- Daily or end-of-day data
- A clearly defined investable universe

The initial market is United States listed equities. EODHD is the current
bounded licensed source for accepted fundamental capabilities. yfinance may
support no-key daily price development and bounded closed-test refreshes,
subject to licensing review before public or commercial use. Twelve Data
remains supported through the same provider-neutral boundary. No provider is
allowed to change the model contract or convert missing evidence into a value.

### Quantitative Screening

- Liquidity and market-cap eligibility
- Trend and momentum indicators
- Fundamental quality indicators
- Valuation indicators
- Volatility and drawdown indicators
- Sector-relative strength
- Transparent factor contributions
- Separate `Quality Compounder` and `Undervalued Quality` paths
- Explicit coverage, exclusion, and specialized-model states

### Candidate Research

- Candidate ranking
- Company overview
- Price and volume chart
- Key fundamental metrics
- Score breakdown
- Data freshness indicators

### AI-Assisted Analysis

- Source-backed company and management review
- Earnings and guidance change summaries
- Competitive and industry risk analysis
- Regulatory, litigation, and governance risk flags
- Counterarguments to the quantitative thesis
- Structured output with citations and uncertainty

### Portfolio Support

- Investment approach, horizon, risk profile, and sector preferences
- Cash, liabilities, leverage limits, and current holdings
- Defensive, enterprising, and explicitly limited speculative allocations
- Maximum position limits
- Maximum sector exposure
- New-money-only and constrained-rebalancing comparisons
- Cash allocation
- Simulated transactions only

### Evaluation

- Daily recommendation snapshots
- Simulated portfolio history
- Benchmark comparison
- Compound return
- Maximum drawdown
- Volatility
- Sharpe and Sortino ratios
- Turnover and estimated costs

### User Interface

- Dashboard
- Candidate list
- Stock detail and research report
- Simulated portfolio
- Performance and review page

## Out of Scope

- Brokerage connectivity
- Automatic order execution
- High-frequency or intraday trading
- Guaranteed-return claims
- Multiple equity markets
- Social or community features
- Billing and subscription management
- Native mobile applications
- Complex machine-learning prediction models
- Specialized models for banks, insurers, REITs, resource companies,
  biotechnology, and special situations
- Kafka and Kubernetes
- Full multi-tenant enterprise administration

## MVP Acceptance Criteria

- All services start locally through a documented process.
- A stock can move through the full data-to-display workflow.
- Quantitative scores are reproducible and versioned.
- AI output includes sources and can fail safely.
- Quantitative-only and AI-reviewed states are visibly distinct.
- Near-term market condition and long-term investment assessment remain
  separate.
- A recommendation snapshot cannot be silently altered after creation.
- Backtests use point-in-time rules and include estimated trading costs.
- The application contains no real-money execution path.
