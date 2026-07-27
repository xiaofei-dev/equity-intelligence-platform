# Forward Decision-Quality Validation v1

## Purpose and Claim Boundary

`FORWARD-VALIDATION-v1.0.0` is an immutable, prospective shadow experiment.
It observes whether deterministic objective ratings, near-term market
conditions, and a paced entry policy improve decision quality after costs and
cash waiting. It is not a recommendation, an automated trading system, or
evidence of guaranteed returns.

Four conclusions are independent:

1. `CALCULATION_VALIDATED` means formulas, event ordering, and contracts pass.
2. `PROVIDER_ACCEPTED` means a provider passed the experiment's PIT data gate.
3. `DECISION_QUALITY_IMPROVED` is a descriptive prospective result.
4. `STATISTICAL_EDGE_PROVEN` is always `NOT_ESTABLISHED` in the one-to-two
   month v1 observation. A confirmatory claim requires a separately
   preregistered period of at least twelve months and thirty non-overlapping
   weekly time cohorts.

## Launch Gate and Enrollment

The implementation defaults to `DRY_RUN`. `FORMAL` requires a recorded
provider acceptance for a 300-to-500-security universe stratified by sector
and market-cap band. The current twenty-security validation set cannot satisfy
this gate. The acceptance record is immutable, identifies the provider and
stratification version, stores a versioned capability matrix and result hash,
and must have status `ACCEPTED`. Supplying an arbitrary identifier is not
sufficient.

After the regular close on the last trading day of each week, an enrollment
references one sealed, succeeded screening run. `QC-v1.0.0` and `UQ-v1.0.0`
are evaluated separately. The top and bottom twenty percent of scored
securities enter `TOP` and `BOTTOM`; all ties at a boundary are retained and
the actual bucket count is recorded. A security cannot re-enter the same
strategy path and bucket while its sixty-trading-day episode is active.

Every signal freezes the security identity, screening run, score, percentile,
near-term assessment, sector, size cohort, sector benchmark, versions,
lineage, input hash, and a USD 10,000 shadow notional. Bottom-bucket
observations test ranking discrimination and are not recommendations.

## Counterfactual Arms

Each signal creates parallel shadow ledgers:

| Arm | Rule |
| --- | --- |
| `A_LUMP_SUM` | Invest 100% at the next trading day's close. |
| `B_FIXED_FOUR_TRANCHE` | Invest 25% on the next trading day and after 5, 10, and 15 additional trading days. |
| `C_STATE_GATED_FOUR_TRANCHE` | At five-trading-day checkpoints, invest the next 25% only when the prior completed session is `FAVORABLE`. |
| `D_CASH_ONLY` | Remain in cash for the full observation. |
| `E_SECTOR_ETF` | Invest 100% in the versioned sector ETF at the next close. |
| `E_SPY` | Invest 100% in SPY at the next close. |

All arms permit fractional shadow shares. No real order is created.

## Entry Policy v1

`ENTRY-POLICY-v1.0.0` checks the next trading day and then every five trading
days through trading day 60. The decision uses the near-term assessment from
the preceding completed session; a same-close condition cannot authorize a
same-close fill.

- `FAVORABLE` advances exactly one fixed 25% tranche.
- `NEUTRAL`, `UNFAVORABLE`, `MISSING`, or `STALE` produces `PAUSE`.
- A pause neither reallocates nor enlarges a later tranche.
- Four fills produce `FULLY_ALLOCATED`.
- Unallocated cash after day 60 produces `EXPIRED`.
- A delisting, unresolved corporate action, or inability to establish safe
  tradability produces `TERMINATED`.
- A later rating change never cancels an episode or changes a prior decision.

States are `AWAITING_FIRST_TRANCHE`, `FIRST_TRANCHE`, `SECOND_TRANCHE`,
`THIRD_TRANCHE`, `FOURTH_TRANCHE`, `PAUSE`, `FULLY_ALLOCATED`, `EXPIRED`, and
`TERMINATED`. State is an append-only event stream, not an editable field.

## Valuation and Metrics

Shadow fills use unadjusted closes. Splits change shares. Dividends become a
receivable on the ex-date and cash on the payment date; they are not
automatically reinvested. Uninvested cash accrues the latest PIT-available
three-month United States Treasury rate with actual-days/365 compounding.
Missing cash-rate data is `CASH_RATE_UNAVAILABLE`, never zero.

`COST-MODEL-v1.0.0` charges 10 basis points one-way transaction cost and 10
basis points one-way slippage on purchases and hypothetical window-end sales.

All arithmetic uses Decimal and half-even rounding:

```text
netTotalReturn =
  (endingSecurities + cash + dividendReceivable - initialBudget) / initialBudget

averageAcquisitionPrice =
  (grossPurchaseValue + buyCosts + slippage) / acquiredShares

purchasePriceImprovement =
  (comparisonAveragePrice - policyAveragePrice) / comparisonAveragePrice

missedUpside =
  max(0, hypotheticalFullyInvestedEndingValue - actualEndingValue) / initialBudget

cashDrag = fullyInvestedReturn - actualMixedCashReturn
```

Maximum adverse excursion is the lowest marked return after each fill relative
to its cost-inclusive basis. Maximum drawdown is the largest peak-to-trough
loss in total shadow-ledger wealth. Upside and downside capture divide summed
strategy daily returns by summed benchmark daily returns on positive and
negative benchmark days respectively. Fewer than five applicable days returns
`INSUFFICIENT_SAMPLE`.

Results are observed after 5, 20, and 60 trading days. Relative returns are
reported against both the sector ETF and SPY. Top-minus-bottom spread is
calculated within the same enrollment week, strategy path, arm, and horizon.
Overall aggregates require twenty completed episodes; sector and size groups
require ten.

## Immutability and Corrections

Signals, policy events, orders, fills, cash flows, valuations, observations,
metrics, and report snapshots are append-only. A correction creates a new
version with a `supersedes` reference. It cannot rewrite the originally
observed signal or action. Every result retains the price, action, cash-rate,
calendar, provider, normalization, and rule versions needed to reproduce it.

## Operational Decisions

- `CONTINUE`: no PIT breach, provider remains accepted, completeness is at
  least 95%, and no safety stop occurred.
- `MODIFY`: calculation is valid but fill rate is below 10% or above 90%,
  critical missing data exceeds 5%, or costs and missed upside overwhelm the
  intended benefit. A change creates a new version for future signals only.
- `PAUSE`: any confirmed look-ahead leak, unresolved material corporate
  action, two consecutive failed enrollments, or loss of provider acceptance.
- `CLOSE`: the rule cannot remain deterministic, or a later adequately
  sampled confirmatory phase shows persistent cost-adjusted harm.

The v1 report conclusion is limited to `PROMISING`, `MIXED`, `UNFAVORABLE`, or
`INSUFFICIENT_SAMPLE`.

## Remaining Formal-Launch Blockers

The implementation and deterministic fixtures may run in `DRY_RUN`, but a
formal observation clock remains blocked until all of the following exist:

- An accepted 300-to-500-security stratified PIT provider record.
- Dated identity, delisting, split, dividend, and unresolved-action coverage.
- A versioned United States trading calendar.
- PIT daily three-month Treasury observations.
- Sector ETF mappings and verified benchmark price/action coverage.
- A successful PostgreSQL V1-to-V11 migration acceptance run in the target
  runtime.

No scheduler should be enabled before these gates pass.
