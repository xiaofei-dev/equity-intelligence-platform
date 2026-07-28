# Tactical Signal v2.1 Methodology

Date: 2026-07-28

## Decision boundary

`TACTICAL-SIGNAL-v2.1.0` is a deterministic completed-daily-session model for
short-term speculation. It does not change Objective Rating v1,
`LONG-HORIZON-RESEARCH-v1.0.0`, or any portfolio constraint.

The model keeps three questions separate:

1. **Is a short-term setup present?**
2. **How favorable is its one-week, one-month, or three-month opportunity?**
3. **Is the current completed-session price an acceptable entry, or is the
   setup already too extended to chase?**

A favorable opportunity is therefore not an entry instruction. A momentum
thesis may be confirmed while actionability is `WAIT_FOR_PULLBACK`.

## Data and execution contract

The evaluator accepts only corporate-action-adjusted daily OHLC prices,
provider-reported volume, adjustment factors, and completed-session flags.
Security and benchmark rows are aligned on shared completed sessions with
positive volume.

The output:

- is formed after a completed daily close;
- is effective no earlier than the next session open;
- expires after one additional completed session;
- does not identify an intraday low;
- does not authorize same-session or automatic brokerage execution.

An intraday model requires a separate contract and independently validated
intraday data.

## Compatibility with v2.0

The v2.0 setup types, entry stages, horizon outlooks, risk-unit caps, and legacy
state fields remain available. V2.1 adds:

- `momentum_extension_risk_score`;
- `entry_value_score`;
- `WAIT_FOR_PULLBACK` actionability.

When a momentum setup is confirmed but requires a pullback, its legacy state is
`WATCH_FOR_CONFIRMATION`, not `MOMENTUM_ENTRY`. This conservative mapping keeps
older consumers from treating a confirmed thesis as an immediately acceptable
entry.

## Opportunity versus entry value

Horizon opportunity indices retain their v2.0 meaning. They describe the
selected setup's prospective tactical attractiveness at 5, 20, and 60 trading
sessions. They do not include a direct chase veto.

Entry value is setup-specific:

- **Momentum entry value** combines trend confirmation, momentum strength,
  benchmark regime, liquidity, the inverse of momentum-extension risk, and the
  existing tactical risk penalty.
- **Mean-reversion entry value** remains the existing payoff-asymmetry score
  between recovery toward the 20-/60-session means and the deterministic
  recent-low-plus-half-ATR invalidation boundary.

The mean-reversion payoff-asymmetry formula and all v2.0 mean-reversion entry
gates are unchanged.

## Momentum extension and chase risk

Momentum-extension risk is independent from proximity to a 52-week high. A
security is not penalized merely for making a new high.

The score uses only completed adjusted daily observations:

- extension above the 20-session mean in ATR units, 25%;
- extension above the 5-session mean in ATR units, 20%;
- the latest close above a prior-20-session log-trend projection in ATR units,
  30%;
- acceleration of the latest five daily returns versus the preceding
  15-session return distribution, 20%;
- the latest positive opening gap in ATR units, 5%.

Each component has a no-penalty region. A gradual, internally consistent
breakout can remain an entry. A sudden burst far above its recent trend can
retain a favorable opportunity while receiving high extension risk.

## Momentum actionability

The frozen v2.0 confirmation requirements remain:

- momentum score at least 65;
- trend confirmation at least 60;
- one-week opportunity at least 55;
- tactical risk below 72.

After those requirements are met:

- extension risk below 70 and entry value at least 60 produces
  `CONFIRMED / ENTRY`;
- extension risk at least 70 or entry value below 60 produces
  `CONFIRMED / WAIT_FOR_PULLBACK`.

`WAIT_FOR_PULLBACK` has a maximum risk-unit multiplier of zero. It means the
continuation thesis is present but the current price is not accepted for
entry. It is not a short recommendation and does not predict that a pullback
must occur.

## Mean-reversion actionability

V2.1 retains the v2.0 distinction among:

- `EARLY_REVERSAL_CANDIDATE`;
- `PROBE_ELIGIBLE`;
- `CONFIRMED`;
- `INVALIDATED`.

A large decline may raise rebound potential and payoff asymmetry while entry
timing remains weak. V2.1 does not promote a falling knife, lower a reversal
threshold, or tune a threshold to any named security.

## AI and safety boundary

All setup, opportunity, extension-risk, entry-value, entry-stage,
actionability, invalidation, and risk-unit fields are deterministic model
outputs. An AI research layer may explain them or attach a separately visible,
expiring evidence overlay. It cannot overwrite, upgrade, or recompute these
fields.

The model provides research states only. It does not choose portfolio weights,
place orders, guarantee returns, or claim a statistically proven edge.

## Verification requirements

Contract tests must demonstrate that:

- a gradual 52-week breakout is not penalized solely for reaching a high;
- an overextended confirmed breakout becomes `WAIT_FOR_PULLBACK`;
- a healthy confirmed breakout remains `ENTRY`;
- mean-reversion payoff asymmetry and gates remain unchanged;
- canonical assessment serialization is deterministic;
- adjusted completed-session and no-look-ahead boundaries remain enforced.

Walk-forward output continues to retain
`statisticalEdgeProven=NOT_ESTABLISHED`.
