# Quant Trading v2 Controlled Development Result

Date: 2026-08-13

## Ruling

The single preregistered Quant v2 retrospective execution completed. The
result is `NOT_DIRECTIONALLY_SUPPORTIVE_NO_RETUNING_ON_SAME_OUTCOME`; the model
evidence label remains `NOT_VALIDATED`.

This is a useful negative result. The regime-filtered mean-reversion hypothesis
produced positive nominal return, positive average net trade P&L, and materially
lower drawdown than SPY, but it did not produce sufficient return or
risk-adjusted performance to justify product decision use.

## Observed result

The current-survivor development population contains 191 securities. The
decision calendar runs from 2015-01-02 through 2026-07-28 and contains 2,908
sessions after the required history window.

| Metric | Quant v2 | SPY buy-and-hold |
| --- | ---: | ---: |
| Initial NAV | USD 100,000.00 | USD 100,000.00 |
| Final NAV | USD 107,516.24 | USD 434,189.17 |
| CAGR | 0.63% | 13.53% |
| Maximum drawdown | -5.62% | -33.70% |
| Sharpe, zero risk-free rate | 0.254 | 0.812 |
| Calmar | 0.112 | 0.402 |

The primary cost model produced 101 completed trades, 47 wins, 54 losses,
average net P&L of USD 74.42 per completed trade, and USD 237.34 in modeled
costs. The fixed-five-basis-point sensitivity remained profitable at 0.57%
CAGR.

Four of eight gates passed: positive CAGR, positive net expectancy, maximum
drawdown no worse than SPY, and positive fixed-cost-sensitivity CAGR. CAGR
relative to SPY, Sharpe, Calmar, and the positive-calendar-year requirement
failed. Six gates were required.

## Governance disposition

- Do not tune thresholds, formulas, ranking, exits, sizing, or costs against
  this same outcome history.
- Do not replace the accepted v1.1 product strategy with v2.
- Keep v2 available as reproducible research code and a negative historical
  artifact, not as a user-facing buy/sell recommendation.
- Any future successor requires a new economic hypothesis and version plus a
  genuinely new validation boundary. It is not part of this implementation.

The complete value-free aggregate summary is in
[the controlled result fixture](../contracts/quant-trading-v2/controlled-result-summary.example.json).
