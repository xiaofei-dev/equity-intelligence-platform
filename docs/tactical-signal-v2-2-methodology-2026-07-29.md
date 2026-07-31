# Tactical Signal v2.2 Methodology

Date: 2026-07-29

## Status and decision boundary

`TACTICAL-SIGNAL-v2.2.0` is a deterministic, completed-daily-session research
model for short-term speculation. It evaluates one-week, one-month, and
three-month views without changing Objective Rating v1, the long-horizon model,
portfolio constraints, or any historical v2.1 artifact.

Version 2.2 is implemented beside v2.1. It is not yet the default analytics or
Market Intelligence model. Route, registry, persistence, walk-forward, and
prospective-enrollment integration require separate controller acceptance.

The existing 2014-2026 tactical results are development evidence. They have
already been observed and cannot serve as an untouched holdout for v2.2.
Version 2.2 must be frozen before prospective Forward Decision-Quality
Validation begins.

## Evidence contract

The model accepts a `TacticalContextV22` with:

- a stable security identifier;
- a timezone-aware decision cutoff;
- an as-of completed trading date;
- corporate-action-adjusted security OHLCV;
- a versioned market benchmark, normally SPY;
- a separately versioned sector benchmark;
- explicit deterministic event-risk evidence;
- provider, availability, ingestion, source SHA-256, sector-mapping version,
  and sector-mapping SHA-256 metadata.

Price evidence uses `VALID`, `MISSING`, `STALE`, `INVALID`, or
`NOT_APPLICABLE`. Required market or sector evidence that is not `VALID`
produces `INSUFFICIENT_DATA`; it is never replaced with a neutral score.

Valid evidence must:

- have timezone-aware availability and ingestion timestamps no later than the
  decision cutoff;
- contain chronological, unique, positive-volume completed sessions;
- contain no session after the as-of date;
- include the shared as-of session for the security, market, and sector;
- retain valid source and sector-mapping hashes.

The signal is formed after the completed as-of close, is effective from the
next completed session open, and expires after one additional completed
session. It cannot identify or execute at an intraday bottom.

## Independent tactical theses

Version 2.2 does not select the larger of two raw scores and force that thesis
onto every horizon. Continuation and mean reversion are evaluated independently
for each horizon. The terminal thesis is:

- `NONE`: neither thesis passes its gates;
- `CONTINUATION`: continuation alone passes;
- `MEAN_REVERSION`: mean reversion alone passes;
- `CONFLICT`: both pass and the unresolved conflict prevents an entry.

The one-week, one-month, and three-month views may select different theses.
Their scores are not averaged into a long-term investment conclusion.

## Feature families

### Continuation

Continuation combines horizon-specific security trend, market-relative
strength, sector-relative strength, market regime, and sector regime.

- One week uses 5- and 20-session returns.
- One month uses 20- and 60-session returns.
- Three months uses 60- and 120-session returns.

Relative strength is computed separately against market and sector. A weak
sector can therefore coexist with positive stock-relative strength; both pieces
of evidence remain visible.

### Mean-reversion potential

Mean-reversion potential combines:

- distance below the 20-session average;
- 5-, 10-, and 20-session selloff severity;
- recent maximum drawdown;
- proximity to the 20-session low in ATR units;
- market- and sector-relative exhaustion.

Potential is not timing. A large decline cannot authorize an entry.

### Rebound readiness

Rebound readiness uses only completed-session evidence:

- closing location within the latest range;
- close versus open;
- one-session return;
- one-session market- and sector-relative return;
- downside deceleration;
- reclaim of the prior five-session low;
- direction-aware volume.

A structural reversal requires a reclaimed prior low, a bullish low rejection,
or both a higher low and higher close.

### Non-compensating risks

The model keeps separate:

- falling-knife risk from negative acceleration, lower closes, weak closing
  location, and fresh lows;
- chase risk from ATR-normalized moving-average extension, return burst, and
  positive gaps;
- volatility risk from ATR, drawdown, gaps, and trend damage;
- liquidity capacity from comparable 20-session adjusted-dollar volume;
- deterministic event risk.

These are gates, not merely negative weights. Strong trend or oversold evidence
cannot compensate for a failed risk gate.

## Horizon eligibility

Continuation thresholds are 58, 60, and 62 for one week, one month, and three
months. Continuation is not eligible when both market and sector regimes are
below 35.

Mean-reversion thresholds are 60, 58, and 56. It also requires:

- mean-reversion potential of at least 60;
- rebound readiness of at least 55, 52, or 48 by horizon;
- falling-knife risk below 70;
- a completed-session reversal structure.

These thresholds are structural v2.2 development parameters. They were not
selected to improve the already-observed historical v2.1 aggregate.

## Entry and abstention rules

Opportunity and entry value remain separate.

- `NONE` produces `NO_SETUP`.
- `CONFLICT` produces `WATCH_ONLY`.
- Invalid liquidity, liquidity below 35, volatility risk at least 80, or
  `HIGH` event risk produces `RISK_BLOCKED`.
- Continuation chase risk at least 60 or continuation entry value below 60
  produces `WAIT_FOR_PULLBACK`.
- Mean-reversion entry value below 55 produces `WATCH_ONLY`.
- Liquidity below 50 or `ELEVATED` event risk limits an otherwise eligible
  entry to `LIMITED_ENTRY`.
- Mean reversion is capped at `LIMITED_ENTRY`.
- Only an eligible, liquid, event-verified continuation with acceptable entry
  value can produce `ENTRY`.

`LIMITED_ENTRY` exposes a maximum of 0.25 independently configured risk units;
`ENTRY` exposes at most 1.0 risk unit. All other states expose zero. These are
not portfolio weights, dollar recommendations, or brokerage instructions.

Missing, stale, invalid, or not-applicable event evidence is not assigned a
neutral value. Scores may still describe price structure, but event uncertainty
is listed in `missing_inputs`, confidence is `LOW`, and actionability cannot
exceed `WATCH_ONLY`.

## Corporate actions and liquidity

Provider-reported volume is not silently combined with a recent incompatible
adjustment regime. If the latest 21 adjustment factors vary by more than five
percent, liquidity becomes `INVALID` and entry is blocked. Directional volume
also cannot confirm a setup across that transition.

## Determinism and AI boundary

The canonical input hash binds the full context, bars, timestamps, provider
references, event evidence, and mapping hashes. Canonical assessment
serialization is deterministic.

There is no AI field in the v2.2 input or output contract. AI may later explain
an immutable deterministic assessment through a separately stored cited
narrative with `may_affect_deterministic_fields=false`. It cannot change
scores, eligibility, thesis, actionability, risk gates, or risk-unit caps.

## Validation boundary

The core implementation is accepted only for formula and contract behavior.
It does not establish a return edge.

Before historical diagnostic replay:

1. freeze the v2.2 model and configuration hash;
2. retain all prior results as `DEVELOPMENT_REPLAY`;
3. use horizon-specific purge and embargo rules;
4. report overlapping and non-overlapping results separately;
5. compare SPY, sector ETF, equal-weight, pure-momentum, and simple
   mean-reversion baselines under the same execution and cost policy;
6. report abstentions, coverage, calibration, turnover, adverse and favorable
   excursion, invalidation, drawdown, and regime/sector stability;
7. do not tune to named securities or the authoritative v2.1 aggregate.

The final validation status must come from frozen prospective decision
snapshots and naturally matured future outcomes. A valid outcome may be
`MIXED`, `NOT_VALIDATED`, `INSUFFICIENT_EVIDENCE`, or `BLOCKED_BY_DATA`.
No favorable result is required.
