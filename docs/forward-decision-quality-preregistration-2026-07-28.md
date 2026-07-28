# Forward Decision-Quality Validation v1 Preregistration

Date: 2026-07-28

## Status

`FORWARD-VALIDATION-v1.0.0` is preregistered in `DRY_RUN` mode under experiment
ID `forward-dry-run-131fd6c59a596056`.

The experiment has not enrolled signals or observed future outcomes. It is
waiting for the first verified weekly-close enrollment and its operational
data gates.

## Frozen configuration

- Strategy path: `QC-v1.0.0`
- Shadow notional: USD 10,000 per signal and arm
- Score buckets: top and bottom 20%, retaining all boundary ties
- Observation horizons: 5, 20, and 60 trading days
- Entry policy: `ENTRY-POLICY-v1.0.0`
- Cost model: `COST-MODEL-v1.0.0`
- Cash return: `CASH-RETURN-3M-TREASURY-v1.0.0`
- Sector benchmarks: `SECTOR-BENCHMARK-MAP-v1.0.0`
- Trading calendar contract: `XNYS-CALENDAR-v1.0.0`
- Buy cost: 10 basis points transaction cost plus 10 basis points slippage
- Hypothetical exit cost: 10 basis points transaction cost plus 10 basis
  points slippage

The six shadow arms are lump sum, fixed four-tranche, state-gated
four-tranche, cash only, sector ETF, and SPY.

## Baseline calculation check

The sealed current Algorithm Gate contains 136 scores. Its deterministic
bucket preview contains 28 top-bucket and 28 bottom-bucket securities. This is
only a calculation preview; those securities are not enrolled signals because
the protocol requires a fresh screening run after the verified final trading
session of the week.

The first calendar-day candidate is 2026-07-31. That date must be confirmed by
the versioned US trading calendar before enrollment.

The published [NYSE holidays and trading-hours
calendar](https://www.nyse.com/markets/hours-calendars) was reviewed on
2026-07-28 and identifies 2026-07-31 as a scheduled regular-session weekday.
The system must still confirm that the session actually completed before
enrollment because an unscheduled closure cannot be proven in advance.

## Pending enrollment gates

- Verify the US trading session calendar.
- Verify dated prices and corporate actions for each security, SPY, and the
  applicable sector ETFs.
- Provide a PIT-available three-month US Treasury cash rate.
- Verify identity, delisting, and unresolved corporate-action coverage.
- Produce a fresh sealed QC screening result after the weekly close.

Until these pass, `signalsEnrolled` remains zero and the conclusion remains
`INSUFFICIENT_SAMPLE`.

## Formal-mode boundary

Formal mode remains blocked because the existing current-snapshot route is not
the 300-to-500-security historical PIT provider acceptance required by the
original protocol. Dry-run prospective evidence may be collected without
weakening or relabeling that requirement.

No real order, automatic trading, recommendation, historical backtest claim,
or guaranteed-return claim is authorized.

## Artifact

The immutable Git-safe preregistration is:

`docs/generated/forward-decision-quality-preregistration-v1.json`

The operational preflight is:

`docs/generated/forward-enrollment-operational-preflight-v1.json`
