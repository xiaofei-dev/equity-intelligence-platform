# Tactical Signal v1 Methodology

Date: 2026-07-28

Status: retained for reproducibility and superseded for new evaluations by
`TACTICAL-SIGNAL-v2.0.0`. V1 artifacts and walk-forward results must not be
relabelled as V2 results.

## Purpose

`TACTICAL-SIGNAL-v1.1.0` evaluates daily-data trading setups over one week
(5 trading days), one month (20 trading days), and three months
(60 trading days). It is separate from Objective Rating v1 and must not be
used as a long-term business-quality or intrinsic-value assessment.

The model is intended for research and simulated execution. It does not enable
automatic brokerage execution and does not claim a statistically proven edge.

## Design

The model keeps two incompatible tactical theses separate:

1. **Momentum continuation** uses 5-, 10-, 20-, and 60-day returns, plus
   20- and 60-day relative strength against a sector or market benchmark.
2. **Mean reversion** uses standardized distance from the 20-day moving
   average, the 60-day trend floor, and an explicit falling-knife penalty.

The stronger setup is selected, but it cannot become an entry without a
separate confirmation gate. Confirmation checks the 5- and 20-day moving
averages, positive 5-day return, positive 5-day relative return, and current
volume versus the trailing 20-day average.

Additional components are:

- market regime from benchmark 5-, 20-, and 60-day returns;
- liquidity from 20-day average dollar volume;
- risk penalty from 14-day ATR, 60-day maximum drawdown, and overnight gaps;
- an optional bounded event-drift input from cited research evidence.

The resulting states are `MOMENTUM_ENTRY`, `MEAN_REVERSION_ENTRY`,
`WATCH_FOR_CONFIRMATION`, `AVOID`, and `INSUFFICIENT_DATA`.

Recent IPOs with at least 21 daily bars may receive a low-confidence provisional
signal. The missing 60-day history is not filled or inferred.

## Walk-forward diagnostics

`TACTICAL-WALK-FORWARD-v1.0.0` recreates historical signals using only bars
available at each cutoff. Signals are formed after the cutoff close and the
simulated entry occurs at the next trading session's open. It reports
one-week, one-month, and three-month:

- episode count;
- hit rate versus the selected benchmark;
- average excess return after a 40-basis-point round-trip cost;
- maximum adverse excursion.

These diagnostics are descriptive. Every output retains
`statisticalEdgeProven=NOT_ESTABLISHED`.

## Validation snapshot

The bounded 2026-07-28 validation made 13 EODHD daily-price requests for seven
securities and six benchmarks. Raw licensed payloads are stored under the
Git-ignored `storage/tactical-validation` directory.

The Git-safe result is:

- `docs/generated/tactical-signal-validation-20260728T103435Z.json`
- file SHA-256:
  `B669622151679D011970F3D3A71CDB46F7246D496DC75573A7A1EEB0F4A16F63`

The first sandbox-blocked attempt is retained as failure evidence. It made no
successful provider request and is not an input to the accepted result.

## Claim boundary

The model distinguishes current setup quality from future realized performance.
It does not guarantee profit, does not treat a large decline as an automatic
mean-reversion entry, and does not use backtested performance as proof of future
performance.
