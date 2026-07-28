# Tactical Signal v2 Methodology

Date: 2026-07-28

## Decision boundary

`TACTICAL-SIGNAL-v2.0.0` is a completed-daily-session model for short-term
speculation. It does not change Objective Rating v1 or
`LONG-HORIZON-RESEARCH-v1.0.0`.

The two decision layers must remain visible and must never be averaged:

- long-term investment research evaluates business quality, financial
  resilience, valuation, evidence quality, and a 12-month-plus thesis;
- short-term speculation evaluates current price behavior, rebound or
  continuation potential, entry timing, and tactical risk.

A security may therefore be favorable for long-term research while having no
current tactical entry. It may also have high rebound potential while its
entry timing remains weak.

## Data contract

The model accepts corporate-action-adjusted daily OHLC prices, provider-reported
volume, an adjustment factor, and a completed-session flag. Before evaluation,
the security and benchmark are aligned on shared completed sessions with
positive volume. Zero-volume pseudo sessions and unmatched calendar rows do not
count as trading sessions.

The EODHD validation adapter derives adjusted OHLC by multiplying raw OHLC by
`adjusted_close / close`. It retains provider-reported volume. When the price
adjustment factor changes by more than 5% within the latest 21 shared sessions,
directional volume confirmation is suppressed instead of mixing incompatible
volume regimes.

The daily signal:

- is formed only after a completed close;
- is effective no earlier than the next session open;
- expires after one additional completed session;
- cannot identify an intraday low or authorize same-session execution.

An eventual intraday model requires a separate version and data contract.

The analytics service exposes the deterministic evaluator at
`POST /internal/v1/tactical/evaluate`. The endpoint accepts caller-supplied
security and benchmark bars and makes no provider request. Spring Boot remains
the owner of any future user-facing workflow; the frontend must not call the
Python endpoint directly.

## Independent output axes

### Setup type

- `MOMENTUM`: continuation is stronger than mean reversion.
- `MEAN_REVERSION`: rebound potential is stronger than continuation.

### Entry stage

- `NONE`: no actionable stage is present.
- `EARLY_REVERSAL_CANDIDATE`: rebound potential exists, but the evidence does
  not authorize an entry.
- `PROBE_ELIGIBLE`: early reversal structure and risk-adjusted asymmetry permit
  only a limited probe.
- `CONFIRMED`: completed-session evidence confirms the selected setup.
- `INVALIDATED`: a prior probe or confirmed reversal crossed its supplied
  deterministic invalidation level.
- `INSUFFICIENT_DATA`: required shared completed-session history is absent.

### Actionability

- `WATCH_ONLY`
- `LIMITED_ENTRY`
- `ENTRY`
- `RISK_BLOCKED`
- `NO_SETUP`
- `INSUFFICIENT_DATA`

`LIMITED_ENTRY` caps the model output at `0.25` of one independently configured
risk unit. `ENTRY` caps it at `1.0` risk unit. These are not portfolio weights
or dollar recommendations. The portfolio service must apply cash, leverage,
concentration, volatility, and sleeve constraints separately. AI cannot change
the cap or upgrade an entry stage.

### Horizon outlook

One-week, one-month, and three-month opportunity indices are reported
independently as `FAVORABLE`, `NEUTRAL`, `UNFAVORABLE`, or
`INSUFFICIENT_DATA`. They are outlooks, not entry states. The entry state is a
separate next-session timing decision.

## Deterministic features

Momentum uses 5-, 10-, 20-, and, when available, 60-session security returns
and benchmark-relative returns.

Rebound potential is kept separate from entry timing. It combines:

- adjusted distance below the 20-session moving average, 30%;
- 5-, 10-, and 20-session selloff severity, 25%;
- 60-session drawdown, 15%;
- proximity to the 20-session low in ATR units, 15%;
- five-session benchmark-relative exhaustion, 15%.

Early reversal timing combines:

- closing location within the latest daily range, 20%;
- close versus open, 15%;
- one-session return, 15%;
- one-session benchmark-relative return, 10%;
- decline deceleration, 15%;
- recovery of the prior five-session low, 15%;
- direction-aware volume, 10%.

Volume cannot confirm a weak high-volume close. A structural early reversal
requires at least one of:

- a lower intraday low followed by a close back above the prior five-session
  low;
- a close in the upper 40% of the daily range at or above the open;
- both a higher low and a higher close than the preceding session.

Trend confirmation separately tests price versus the 5- and 10-session moving
averages, positive 3- and 5-session returns, positive five-session relative
return, a higher low, and a higher close.

Risk is independent from potential. The model retains:

- ATR, drawdown, overnight-gap, and trend-damage risk;
- a separate falling-knife score using negative acceleration, five-session
  decline, weak closing location, repeated lower closes, and a weak fresh low;
- payoff asymmetry between a recovery toward the 20-/60-session means and a
  recent-low-plus-half-ATR invalidation boundary.

An optional evidence-backed event score is bounded to 0-100. The default
neutral value is 50. AI event overlays remain separately visible, expire, and
cannot overwrite raw scores or states.

## Entry gates

The gates are frozen before inspecting named-security results.

Momentum is confirmed only when:

- momentum is at least 65;
- trend confirmation is at least 60;
- one-week opportunity is at least 55;
- risk is below 72.

A mean-reversion probe requires:

- rebound potential at least 68;
- reversal timing at least 50;
- payoff asymmetry at least 55;
- one-week opportunity at least 40;
- risk below 88;
- falling-knife risk below 85;
- a structural early-reversal condition.

A confirmed mean-reversion entry requires:

- rebound potential at least 60;
- reversal timing at least 65;
- trend confirmation at least 50;
- one-week opportunity at least 50;
- risk below 82.

Risk at or above 92 or falling-knife risk at or above 94 blocks mean-reversion
entry. Securities with fewer than 60 shared sessions cannot become actionable;
they may only be early candidates. A large price decline by itself never
creates an entry.

The output also reports entry-stage confidence from the minimum distance to all
applicable thresholds. A result barely crossing a gate remains `LOW`
stage-confidence and may change at the next daily refresh.

## Walk-forward diagnostics

`TACTICAL-WALK-FORWARD-v2.0.0`:

- recreates every signal from the available prefix only;
- enters no earlier than the next session open;
- separates setup type and entry stage;
- applies a 20-session same-setup cooldown;
- includes a 40-basis-point round-trip cost;
- applies the deterministic invalidation boundary, including adverse gap
  execution;
- reports excess return, hit rate, maximum adverse excursion, maximum
  favorable excursion, and invalidation rate.

All diagnostics retain `statisticalEdgeProven=NOT_ESTABLISHED`. Descriptive
walk-forward results are not proof of future performance.

## Validation and claim boundary

The accepted V2 validation is an offline replay of the sealed EODHD payloads.
It makes zero provider requests and keeps raw licensed payloads under
Git-ignored storage. The Git-safe artifact records hashes and derived scores,
not raw provider values.

- artifact:
  `docs/generated/tactical-signal-validation-20260728T113936Z-all-requested.json`;
- file SHA-256:
  `1A75EB70DA9CDAD83CEB463E061709596346A43370C65D73D11780CD020E8C0E`;
- input cutoff: 2026-07-27 completed close;
- physical provider requests: 0.

The model is designed to distinguish:

- high rebound potential with poor timing;
- an early probe from a confirmed reversal;
- a good company from a good short-term entry;
- a missed first rebound leg from an invalid decision process.

It does not predict an exact bottom, guarantee a rebound, make a portfolio
allocation, or enable automatic brokerage execution.
