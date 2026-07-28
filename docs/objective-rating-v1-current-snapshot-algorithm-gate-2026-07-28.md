# Objective Rating v1 Current-Snapshot Algorithm Gate

Date: 2026-07-28

## Outcome

The current-snapshot QC Algorithm Gate passed offline for 136 mature US
operating companies. The gate used only previously cached, hash-verified EODHD
and SEC evidence. It made no provider request and did not start Forward
Decision-Quality Validation.

This result is a current research snapshot. It is not a historical PIT
backtest, a return forecast, a portfolio instruction, or authorization for
automatic trading.

## Current-only evidence contract

The input adapter applies the following bounded policy:

- EODHD quarterly financial-statement values are treated as non-cumulative
  discrete quarters based on the written support response received on
  2026-07-28.
- Each EODHD observation retains the cached response hash, provider path,
  retrieval time, filing date when supplied, and the current-only policy
  version.
- Quarter starts are inferred from adjacent quarter boundaries and explicitly
  labeled as inferred.
- Capex is normalized to an absolute cash outflow.
- Diluted weighted-average shares use positive explicit SEC discrete-quarter
  facts. Fiscal fourth-quarter shares are derived using the day-weighted
  difference between the annual and nine-month averages.
- EODHD normalized current total debt, current TTM EBITDA, market
  capitalization, and enterprise value remain limited to current-snapshot
  decisions.
- No current observation is relabeled as historical PIT evidence.

## Gate counts

- Formula-ready provider scope: 223
- Securities with all required cached source routes: 216
- Complete QC factor inputs: 190
- QC algorithm-eligible after formula validity checks: 136
- Frozen minimum general-company cohort: 100
- Scored securities: 136

The difference between 190 input-ready and 136 algorithm-eligible securities
is intentional. Positive-endpoint and denominator rules are applied at formula
execution; invalid economic inputs remain insufficient rather than being
coerced.

## Scoring

The gate preserves `QC-v1.0.0` formulas and weights. Each raw factor is
winsorized at the fifth and ninety-fifth cohort percentiles and normalized by
the frozen sector-size, sector, and general-company fallback rules.

The valuation guardrail uses the mean of the current earnings-yield and
FCF-yield cohort percentiles. Its score is zero when both yield percentiles are
at or below the tenth percentile. The gate stores normalized scores,
contributions, cohort levels, cohort sizes, input hashes, and deterministic
ranks; Git-safe artifacts contain no licensed provider observations.

## Artifacts

- Current input manifest:
  `docs/generated/objective-rating-v1-current-decision-input-manifest-v1.json`
- Current Algorithm Gate:
  `docs/generated/objective-rating-v1-current-snapshot-algorithm-gate-v1.json`
- Controlled current factor inputs:
  `storage/provider-validation/current-decision-inputs-v1` (Git-ignored)

## Next boundary

The next phase is Forward Decision-Quality Validation. It must begin only after
explicit approval and must freeze the score snapshot, benchmark, observation
horizons, transaction-cost assumptions, and evaluation rules before observing
future outcomes. The current gate does not authorize historical performance
claims.
