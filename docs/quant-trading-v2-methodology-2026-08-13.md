# Quant Trading v2 Methodology

Date: 2026-08-13

## Purpose

Quant v2 is an independent `REGIME_FILTERED_MEAN_REVERSION` research strategy.
It does not alter or combine the observed v1 momentum-continuation or v1.1
dual-momentum strategies. Its purpose is to test whether short-lived pullbacks
inside established security and broad-market uptrends provide useful entry and
exit timing evidence.

The historical cache was previously observed. The single v2 replay is therefore
development evidence, not an untouched holdout or proof of future returns.

## Frozen signal

Every completed SPY session is a decision boundary. A security requires 253
aligned daily observations, a price of at least USD 5, median 20-session dollar
volume of at least USD 5 million, SPY and security closes above their 200-session
simple moving averages, security SMA50 above SMA200, close below SMA20, simple
two-change RSI2 at or below 10, 20-session z-score at or below -1.25, and ATR14
at no more than 10% of price.

Eligible securities are ranked by 60% pullback-depth percentile and 40% RSI
oversold percentile, with durable security ID as the final tie break. At most
five candidates may enter at the next observed open.

## Frozen trade and portfolio rules

The maximum entry price is signal close plus 0.25 ATR. The initial stop is the
signal close minus the smaller of 8% and the larger of 2.5 ATR or 3%. The frozen
signal-session SMA20 is the profit target. Maximum-entry reward/risk must be at
least 1.25. Stop wins same-bar ambiguity. The maximum holding period is ten
sessions, with a session-ten close exit. A broken market or security 200-session
trend exits at the next open.

The simulator starts with USD 100,000, uses whole shares, risks at most 0.5% of
prior-close NAV per position, caps notional at 20% per position, and holds at
most five positions. Entry and exit use the frozen C9 nonlinear cost function;
a fixed five-basis-point-per-side sensitivity is required. There is no final
portfolio-weight, brokerage, or LLM authority.

## One-pass historical ruling

The immutable protocol permits one outcome access and zero retries after either
completion or failure. It evaluates eight gates: positive CAGR, positive net
trade expectancy, Sharpe above SPY, Calmar above SPY, drawdown no worse than
SPY, CAGR no more than two percentage points below SPY, at least six positive
calendar years among 2016-2024, and positive CAGR under fixed five-basis-point
costs.

At least six gates plus positive expectancy is directionally supportive for
development only. It cannot upgrade the production evidence label. An
unsupportive result is sealed as `NOT_VALIDATED`; parameters must not be changed
and rerun against the same outcome history.

Normative fixtures:

- [Decision contract](../contracts/quant-trading-v2/decision-contract.example.json)
- [Historical validation protocol](../contracts/quant-trading-v2/historical-validation-protocol.example.json)
