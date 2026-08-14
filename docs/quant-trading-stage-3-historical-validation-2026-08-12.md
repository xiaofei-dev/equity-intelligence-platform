# Quantitative Trading v1 Stage 3 Historical Validation

Date: 2026-08-12

## Disposition

`QUANT_TRADING` Stage 3 is `NOT_VALIDATED`. The exact frozen Momentum
Continuation strategy produced a positive full-population return with lower
drawdown than SPY, but materially underperformed SPY and produced a low win
rate. No threshold, feature, entry, exit, sizing, or cost rule was changed
after outcome access.

The governed production track remains
`BLOCKED_INPUT_AUTHORITY_INCOMPLETE`. The completed run is only the explicitly
weaker `YAHOO_ADJUSTED_OHLCV_CURRENT_SURVIVOR_APPROXIMATION` track, with claim
ceiling `DEVELOPMENT_OBSERVED_CURRENT_REVISION_CURRENT_SURVIVOR`.

## Pre-outcome seals

- protocol: `84B5DEEDF5ABE572C135E3E1CF3D4FF7ED391F93A20A82D4F3B6C1BF48F070BC`;
- structural cache preflight: `FC63F5EBBDBDEC357B5F0ED6AFB3A5F9E6E2720B1760FE3B4B59192F26981F34`;
- exact Stage 1 differential parity over 25 deterministic real windows:
  `DE82D8CFB94087A5486FC6D80DBE8E11AE782A6ABCA027DAD73CCD3AB2E04501`.

The first implementation attempt was terminated without producing an outcome
because it rebuilt millions of strict contract objects. The optimized path was
accepted only after exact feature, ordered-reason, unrounded score, and plan
parity against the Stage 1 core. The first schema-only inspection disclosed in
the protocol opened one ADM row only and did not calculate a return or strategy
metric.

## Batches

| Batch | Final NAV | CAGR | SPY CAGR | MDD | Sharpe | Trades | Win rate | Costs |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 25 | $95,948.78 | -0.36% | 13.68% | -8.39% | -0.198 | 172 | 28.49% | $370.99 |
| 100 | $116,220.02 | 1.31% | 13.68% | -7.94% | 0.267 | 795 | 32.20% | $1,810.33 |
| 191 | $113,808.46 | 1.13% | 13.68% | -12.02% | 0.187 | 1,243 | 31.38% | $2,867.34 |

The full run's total return was 13.81%, versus SPY's 338.69% over the same
observed-session interval. Its severe-loss rate, defined as closed-trade net
return at or below -20%, was 0.0805%. SPY's maximum drawdown was -33.69%, so
the strategy did reduce drawdown, but it did so while holding substantial cash
and sacrificing most of the market return. This is not adequate evidence of
an attractive trading strategy.

The immutable controlled result hashes are:

- batch 25: `4E72F6FA64F13935E9C32C1434092B5C830366B694D913E4B2BF5AB722E30B74`;
- batch 100: `26B692C7156D15D5F9B8E61402BF00E2F9E6F4B5A6290DEA2E3B281FCCA62AF8`;
- batch 191: `F87E4AF65E9E2AAF73BC6ADA7142FB5C78E21D0E2D8E95771D83963C1533AB8D`.

## Limitations

The population contains 191 current survivors rather than historical members
and excludes delisted names. The Yahoo history is current revision. It lacks
strict V22 identity, halt, suspension, corporate-action, and terminal-event
authority. Adjusted OHLCV is used without separate dividend or split cash
flows. Fifteen equity payloads with invalid adjusted-OHLC geometry were
excluded explicitly, and missing, gapped, or nonpositive-volume windows did
not become neutral signals. SPY and zero-return cash are the only observed
benchmarks; equal weight and sector benchmarks remain `NOT_OBSERVED`.

Passing engineering replay and data-integrity checks does not imply future
performance. This evidence supports rejecting the current v1 strategy for
production, not tuning it against the same outcomes.
