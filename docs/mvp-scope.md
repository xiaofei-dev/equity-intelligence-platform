# MVP Scope

## MVP Goal

Deliver a usable daily equity research workflow that can be demonstrated, evaluated, and extended without connecting to a brokerage account.

## Primary User Journey

1. The system updates daily market and fundamental data.
2. Eligibility rules remove unsuitable or insufficiently liquid securities.
3. Sector and stock factors rank the remaining universe.
4. The system presents a small candidate list with score explanations.
5. AI reviews source documents and identifies qualitative strengths, risks, and unresolved questions.
6. The portfolio module proposes a simulated allocation under explicit constraints.
7. The user reviews the evidence and records a decision.
8. The platform tracks subsequent performance against a benchmark.

## In Scope

### Market Coverage

- One equity market
- Daily or end-of-day data
- A clearly defined investable universe

The initial market is United States listed equities. Twelve Data is the
development provider for the bounded Phase 1 slice; the provider interface
must remain replaceable because broader coverage and commercial use require a
separate data and licensing decision.

### Quantitative Screening

- Liquidity and market-cap eligibility
- Trend and momentum indicators
- Fundamental quality indicators
- Valuation indicators
- Volatility and drawdown indicators
- Sector-relative strength
- Transparent factor contributions

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

- Separate short-term and long-term strategy sleeves
- Maximum position limits
- Maximum sector exposure
- Volatility-aware position sizing
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
- Kafka and Kubernetes
- Full multi-tenant enterprise administration

## MVP Acceptance Criteria

- All services start locally through a documented process.
- A stock can move through the full data-to-display workflow.
- Quantitative scores are reproducible and versioned.
- AI output includes sources and can fail safely.
- The two strategy sleeves are measured separately.
- A recommendation snapshot cannot be silently altered after creation.
- Backtests use point-in-time rules and include estimated trading costs.
- The application contains no real-money execution path.
