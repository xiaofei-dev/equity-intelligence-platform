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

## Strategy Separation

Short-term and long-term positions must be treated as separate strategy sleeves.

### Long-Term Core Sleeve

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

### Short-Term Tactical Sleeve

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

Profits in one sleeve must not hide weaknesses in the other.

## Screening Pipeline

An illustrative pipeline is:

```text
Investable universe
      |
      v
Eligibility and data-quality filters
      |
      v
Sector ranking
      |
      v
Quantitative stock ranking
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

## Composite Scoring

The final score must be explicit and versioned. An initial conceptual formula may be:

```text
Final Score =
    Quantitative Score
  + Sector Score
  + Fundamental Quality Score
  + Valuation Score
  + AI Risk Adjustment
```

Weights are research hypotheses, not facts. They must be tested out of sample.

AI should have limited influence and should primarily:

- Apply documented risk adjustments
- Flag missing or contradictory evidence
- Require human review

AI should not produce unrestricted scores or portfolio weights.

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

Initial values are configuration proposals and must not be treated as universally optimal.

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

