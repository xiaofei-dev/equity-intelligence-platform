# Data and Backtesting

## Data Principles

Investment results are only as reliable as the historical data and availability assumptions behind them.

Every stored dataset should identify:

- Provider
- Original timestamp
- Ingestion timestamp
- Effective date
- Revision or restatement status
- Schema version
- Quality status

## Required Data Categories

The MVP may require:

- Security master and symbol history
- Daily adjusted and unadjusted prices
- Trading volume
- Corporate actions
- Fundamental statements
- Filing publication timestamps
- Sector and industry classification
- Benchmark data
- Risk-free rate data when needed
- Source documents for AI research

The first providers remain open decisions.

## Point-in-Time Correctness

The backtest must use only information that would have been available at the simulated decision time.

It must prevent:

- Look-ahead bias
- Survivorship bias
- Restatement leakage
- Delisting exclusion
- Future constituent leakage
- Train-test contamination

## Backtest Assumptions

Every run must record:

- Strategy version
- Parameter set
- Universe definition
- Data snapshot
- Rebalancing schedule
- Execution timing
- Transaction-cost model
- Slippage model
- Tax treatment or explicit exclusion
- Benchmark
- Start and end dates

## Evaluation Design

Recommended stages:

1. Exploratory analysis
2. In-sample development
3. Out-of-sample evaluation
4. Walk-forward testing
5. Paper trading
6. Limited-capital observation

The same holdout data must not be repeatedly used to tune the strategy.

## Metrics

At minimum, report:

- Compound annual growth rate
- Total return
- Benchmark return
- Excess return
- Annualized volatility
- Maximum drawdown
- Drawdown recovery time
- Sharpe ratio
- Sortino ratio
- Beta
- Win rate
- Profit factor
- Turnover
- Estimated costs
- Exposure by sector and position

## Recommendation Snapshots

Every recommendation should preserve:

- Recommendation timestamp
- Prices available at that time
- Candidate scores
- Factor values
- Strategy version
- AI report version
- Source references
- Proposed allocation
- Human decision

Snapshots should be immutable. Corrections should create a new version or an audit entry.

## Live Evaluation

Paper-trading results should be compared with:

- The selected benchmark
- The user's historical baseline
- Simple passive alternatives
- The same strategy before AI adjustments, when applicable

This allows the system to determine whether each added component produces incremental value.

