# Historical Decision-Quality Validation v1

## Purpose

Historical Decision-Quality Validation tests whether frozen deterministic
model outputs have useful relationships with later completed-session outcomes.
It is designed to expose weak models and data limitations rather than to
produce favorable backtest claims.

## Required controls

Every historical run must freeze and record:

- universe and applicability policy;
- model, factor, threshold, cost, and benchmark versions;
- decision cutoff and completed-session calendar identity;
- point-in-time availability assumptions;
- transaction costs, slippage, turnover, and liquidity constraints;
- missing, stale, invalid, and not-applicable states;
- train, development, and untouched-holdout roles;
- survivorship, revision, and classification limitations.

Features must use only evidence available by the decision cutoff. Outcomes
begin after the decision session. Overlapping windows must not be treated as
independent observations.

## Benchmarks and metrics

The contract supports SPY, dated sector, equal-weight, momentum, value, and
quality comparisons when their evidence is available. It measures coverage,
abstention, turnover, costs, rank association, benchmark-relative outcomes,
drawdown, downside, and stability. Missing benchmark evidence remains missing.

Exact formulas and synthetic contract fixtures are public. Numeric results
derived from licensed or personal-use market data remain in Git-ignored
controlled storage and are not published in the repository.

## Evidence labels

Retrospective results observed during development are
`DEVELOPMENT_OBSERVED`. They may show engineering consistency or motivate a
prospective hypothesis, but they are not an untouched holdout and do not prove
future returns.

Stronger claims require separately sealed PIT or forward evidence. Operational
run success is not a model-evidence label.

## Clean-clone behavior

Pure contract, formula, chronology, and leakage tests run in every clean clone.
Tests requiring controlled historical inputs skip explicitly when those local
files are absent. Missing controlled data are never replaced with synthetic
pass results, zero, or neutral values.

See [Licensed Market Data Publication Policy](licensed-market-data-publication-policy.md)
and [Model Validation Master Plan v2](model-validation-master-plan-v2.md).
