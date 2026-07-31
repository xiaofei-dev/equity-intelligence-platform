# Practical Tactical v2.2 Backtest v1

## Scope

This route evaluates the frozen Tactical v2.2 ordinal score over one-week,
one-month, and three-month completed-session horizons. It compares model
portfolios with SPY, an assessable-universe equal-weight baseline, and
available diagnostic benchmarks after the frozen transaction-cost policy.

The run is retrospective development evidence. It is not an untouched
holdout, strict point-in-time validation, a calibrated forecast, or proof of
future returns.

## Publication boundary

Numeric returns, price paths, drawdowns, excursions, hit rates, rank
statistics, and benchmark comparisons are derived from personal-use or
licensed market data. They remain in a content-addressed controlled result
under Git-ignored `storage/` and are not published in this repository.

The public manifest records only:

- model and policy versions;
- source and controlled-result hashes;
- horizon and population counts;
- benchmark availability;
- execution and claim-boundary states;
- explicit limitations.

Git-safe manifest:

`docs/generated/practical-tactical-v2-2-backtest-manifest-v1.json`

## Reproduction

The run requires the local controlled retrospective and historical price
cache. In a clean clone, the data-dependent test skips explicitly while pure
formula and benchmark-contract tests continue to run.

```powershell
$env:PYTHONPATH = "analysis-python/src"
.\analysis-python\.venv\Scripts\python.exe -m `
  equity_analysis.historical_validation.practical_tactical_v22_cli
```

See [Licensed Market Data Publication Policy](licensed-market-data-publication-policy.md).
