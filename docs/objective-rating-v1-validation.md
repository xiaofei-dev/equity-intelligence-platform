# Objective Rating v1 Validation Report

## Result

The executable validation slice passes its deterministic calculation,
explainability, missing-data, cohort-fairness, specialized-model, horizon
separation, and Python-to-Java contract tests.

The result is a **calculation and contract acceptance**, not approval for a
full-market historical backtest. Production data acceptance remains
`NOT_VERIFIED`.

## Implemented Evidence

- Immutable Pydantic contract and domain models for observations, factor
  results, contributions, horizons, strategy ratings, coverage, risk, lineage,
  run status and result pages.
- Explicit Decimal factor calculations and fixed strategy configurations for
  `QC-v1.0.0`, `UQ-v1.0.0`, and `NEAR_TERM-v1.0.0`.
- Deterministic 5th/95th percentile winsorization, directional percentile
  ranks, market-cap cohorts, and documented cohort fallback.
- A 100-observation deterministic cohort fixture with 25 observations in each
  v1 market-cap band.
- A 20-security provider-acceptance fixture covering corporate actions,
  symbol changes, delisting, size, benchmarks and specialized company types.
- A six-security derived Twelve Data price fixture as of 2026-07-24 with
  request policy and SHA-256 row hashes.
- A shared Python/Java JSON contract fixture that preserves decimal precision.
- A hashed AAPL SEC fixture deriving five 2024-03-30 TTM duration metrics with
  the versioned annual-plus-YTD bridge.
- A bounded AAPL PIT factor reconstruction for ROIC, operating margin,
  net-debt/EBITDA, earnings yield and FCF yield, with incomplete strategies
  remaining unscored.

## Reasonableness Checks

The tests establish economic direction rather than a desired stock ordering:

- Improving any positive factor cannot reduce its normalized score.
- Lower leverage, volatility, drawdown, dilution, or instability cannot receive
  a worse directional score than a higher value in the same cohort.
- Equal economic positions in small, mid, large and mega cohorts receive equal
  quality and valuation dimension scores.
- A missing ROIC produces `INSUFFICIENT_DATA`, not a zero or neutral score.
- Banks, insurers, REITs, resource companies, biotechnology, emerging growth
  and special situations cannot enter the general-company ranking.
- Medium term has no score, and the near-term result does not modify long-term
  quality or valuation.
- In the derived price fixture, AAPL's 60-day return exceeded SPY while META's
  did not, and SPY had lower 60-day volatility than META. These observations
  validate formula direction only and are not investment conclusions.

## Known Limits

- The 100-observation cohort is deterministic test data, not a historical
  investable universe.
- Twenty provider cases, ten mature-company SEC lineages, and six historical
  SEC filing cutoffs were sampled; this remains a bounded validation set.
- Long-term historical factor values have not been backfilled across the
  20-security validation universe.
- Delisting proceeds, complete historical ticker continuity, empirical
  restatement coverage and provider licensing have not passed acceptance.
- No CAGR, alpha, benchmark outperformance or profitability claim is made.

## Next Gate

Before full ranking or backtesting, populate the 20-security acceptance
worksheet from an approved provider trial, cross-check at least 30 facts
against SEC filings, verify at least 20 price/action events, and run the
adversarial PIT tests defined in the v1 specification.
