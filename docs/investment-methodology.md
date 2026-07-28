# Investment Methodology

## Objective

Improve the user's existing investment process through systematic screening, evidence-based research, explicit risk controls, and honest performance measurement.

The methodology optimizes risk-adjusted and benchmark-relative outcomes. It must not optimize annual return in isolation.

## Baseline Before Optimization

Before evaluating a new strategy, the platform should reconstruct the user's historical baseline where data is available:

- Compound annual growth rate
- Annualized volatility
- Maximum drawdown
- Drawdown recovery time
- Benchmark-relative return
- Beta
- Turnover
- Estimated transaction costs
- Cash exposure
- Position and sector concentration

Historical performance must use the complete account where possible, not selected successful trades.

## Investment Intent and Horizon

Investment intent and expected holding period are separate concepts. A
long-held security can remain speculative, while a researched investment can
have a shorter review horizon.

The platform should distinguish:

- Defensive investing
- Enterprising investing
- Explicitly limited speculation

It should separately record short, medium, or long expected horizons when the
associated strategy defines a testable use case. A generic medium-term score is
not part of the first methodology.

### Long-Term Investment Assessment

Typical inputs:

- Revenue and earnings quality
- Free cash flow
- Balance-sheet strength
- Durable competitive position
- Valuation
- Management execution
- Long-term price trend

Expected behavior:

- Lower turnover
- Longer holding periods
- Thesis-driven review
- Rebalancing based on fundamentals and risk

### Near-Term Market Condition

Typical inputs:

- Price momentum
- Relative strength
- Volume behavior
- Volatility
- Event catalysts
- Trend confirmation

Expected behavior:

- Explicit entry and exit conditions
- Smaller or volatility-adjusted positions
- Higher sensitivity to costs and slippage
- Independent performance reporting

The daily tactical model must not collapse rebound potential, entry timing,
and risk into one recommendation. It reports:

- the stronger setup thesis: momentum or mean reversion;
- independent one-week, one-month, and three-month opportunity outlooks;
- a setup-specific current entry-value score;
- a separate momentum-extension or chase-risk score;
- an entry stage: none, early candidate, probe eligible, confirmed, or
  invalidated;
- actionability and a deterministic risk-unit cap;
- the completed-session cutoff, earliest next-session execution, and
  one-session expiry.

An early candidate is not an entry. A probe is intentionally earlier and less
certain than a confirmed reversal, so it is limited to a fraction of one
separately configured risk unit. A high rebound-potential score may coexist
with low timing confidence or a risk block.

A favorable opportunity does not automatically mean that the current price is
an attractive entry. A gradual breakout may remain actionable even near a
52-week high, while an unusually accelerated and extended breakout may return
`WAIT_FOR_PULLBACK` with a zero risk-unit cap. The extension rule must use
completed-session price structure rather than penalizing a security merely for
making a new high.

Near-term market condition and long-term investment assessment must remain
separate. Strong momentum must not conceal weak business quality or an
insufficient margin of safety, and weak momentum must not automatically
invalidate a long-term thesis.

## Screening Pipeline

An illustrative pipeline is:

```text
Investable universe
      |
      v
Eligibility and data-quality filters
      |
      v
Sector, size, and company-type cohorts
      |
      v
Strategy-specific quantitative rankings
      |
      v
Small candidate set
      |
      v
AI evidence and risk review
      |
      v
Portfolio construction
```

Exact candidate counts are configuration values and should be justified by data and cost rather than hard-coded assumptions.

## Factor Categories

Potential quantitative categories include:

- Trend and momentum
- Relative strength
- Valuation
- Profitability and quality
- Growth
- Balance-sheet risk
- Volatility and drawdown
- Liquidity
- Sector strength

Every factor requires:

- A precise definition
- Data source
- Availability timestamp
- Normalization method
- Missing-value policy
- Direction of preference
- Version identifier

## Strategy-Specific Assessment

The platform must not create one universal score for mature companies,
early-stage growth companies, banks, insurers, REITs, and special situations.
The first implementation supports:

- `Quality Compounder`
- `Undervalued Quality`

Each path must preserve business quality, financial strength, earnings
stability, growth quality, valuation, margin of safety, data confidence, and
risk flags as separate components. Weights are research hypotheses and must be
tested out of sample.

AI must not produce unrestricted scores or portfolio weights. It supplies
source-backed evidence that may support a result, reduce confidence, add a
warning, or trigger a documented eligibility block.

## Portfolio Constraints

Initial constraints may include:

- Maximum number of positions
- Maximum position weight
- Maximum sector exposure
- Maximum strategy-sleeve allocation
- Minimum liquidity
- Volatility-aware sizing
- Correlation awareness
- Minimum cash reserve
- Maximum leverage
- Allowed rebalancing scope

Initial values are configuration proposals and must not be treated as universally optimal.

Portfolio analysis should compare:

1. New-money-only allocation
2. Constrained rebalancing of selected existing positions
3. A target-portfolio simulation

The system analyzes the complete portfolio even when the user permits changes
only to new cash.

## Performance Objective

The primary objective is sustained positive excess return without unacceptable deterioration in drawdown or volatility.

The platform should report:

- Absolute return
- Appropriate benchmark return
- Excess return
- Risk-adjusted return
- Maximum drawdown
- Turnover and costs

An aspirational compound annual return of 20% to 30% may guide research, but it must not drive overfitting, leverage, or misleading product claims.
