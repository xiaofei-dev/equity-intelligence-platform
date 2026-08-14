# Fundamental Value Stage 7C-1 Company-Quality Producer Pilot

Date: 2026-08-01

## Boundary and result

This was a zero-network, outcome-blind validation-only producer pilot. It did
not read return, benchmark-return, drawdown, rank, or performance fields. It
did not modify the production producer registry or any Stage 1-6 formula.

The pilot stopped before the 216-timeline expansion because the controlled
100 cohort produced zero complete company-quality components on every frozen
date. This is a producer-coverage result, not a model-quality verdict.

## Identity and evidence binding

The existing controlled cohort intersects SEC v4 at exactly 100 of 100 names,
and all 100 have a built hash-verified SEC timeline. Each row binds the stable
controlled security ID, SEC entity ID from the verified payload, a frozen
Stage-7 listing ID, sector, controlled-payload hash, SEC-payload hash, storage
reference, and identity-binding hash. Tickers are labels and are not the sole
identity key.

Every produced operand uses a sealed envelope containing the availability
stratum, producer contract/version/hash, ordered parent IDs and hashes,
security/issuer/listing identity, decision cutoff, period and effective time,
available/ingested chronology, unit, currency, state/reason, numeric value only
for `VALID`, and a canonical output hash. `STRICT_PIT` and
`CURRENT_REVISION_APPROXIMATION` are distinct hash-bound strata.

## Frozen company-quality producers

- Tax rate is TTM income tax divided by positive TTM pretax income, constrained
  to 0 through 0.50.
- NOPAT is TTM operating income multiplied by one minus the tax rate.
- Invested capital is the average of beginning and ending stockholders' equity
  plus total debt minus cash and equivalents. Both balance observations must
  be on or before their respective TTM boundary and no more than 120 days old;
  a post-boundary observation is never eligible.
- ROIC is NOPAT divided by positive average invested capital.
- Operating margin is TTM operating income divided by positive TTM revenue.
- FCF margin is TTM operating cash flow less nonnegative capital expenditure,
  divided by positive TTM revenue.
- Earnings and operating-cash-flow stability require eight aligned discrete
  quarters and use the frozen clipped population coefficient-of-variation
  transformation.

The producer selects the latest unambiguous revision available by the decision
cutoff for each exact period. TTM requires four aligned discrete quarters;
stability requires eight. Quarter-end spacing must be 60-120 days and adjacent
period boundaries must be within seven days. Parents must be USD, periods must
end by the cutoff, and non-finite values, duplicate/tied revisions, invalid
signs, denominators, units, currency, or chronology fail closed.

## Frozen decision dates

The calendar contains 3,160 completed SPY sessions and is hashed as
`518B444025C390B336F689220F77DFCCA81ED687E211EC175324E5F2CD214D22`.
Only the `tradingDate` field was read from the controlled price payload.

The SHA-256-selected Q2 sessions are 2015-05-07, 2016-05-19, 2017-06-30,
2018-04-09, 2019-06-21, 2020-04-20, 2021-06-02, 2022-05-18, and 2023-05-18.

## Coverage

The deterministic cross-sector pilot selected 25 security IDs with set hash
`53CA90469EC1E95BAE569911F1BDD8AC02BEDCE51804536ABB2E419845EAB200`.
All five operand counts and the company-quality count were zero on all nine
dates, primarily because no qualifying aligned period set existed.

The controlled-100 strict-PIT results are:

| Date | ROIC | Operating margin | FCF margin | Earnings stability | Cash-flow stability | Complete company quality |
|---|---:|---:|---:|---:|---:|---:|
| 2015-05-07 | 0 | 0 | 0 | 0 | 0 | 0 |
| 2016-05-19 | 0 | 0 | 0 | 0 | 0 | 0 |
| 2017-06-30 | 0 | 0 | 0 | 0 | 0 | 0 |
| 2018-04-09 | 0 | 0 | 0 | 0 | 0 | 0 |
| 2019-06-21 | 0 | 1 | 0 | 0 | 0 | 0 |
| 2020-04-20 | 0 | 1 | 0 | 0 | 0 | 0 |
| 2021-06-02 | 0 | 2 | 0 | 0 | 0 | 0 |
| 2022-05-18 | 0 | 2 | 0 | 0 | 0 | 0 |
| 2023-05-18 | 0 | 2 | 0 | 0 | 0 | 0 |

The dominant terminal reason is `MISSING_ALIGNED_PERIODS`; bounded secondary
reasons are `REVISION_AMBIGUITY` and `TAX_RATE_OUTLIER`.
Current-revision approximation was not run and remains separate.

The 216-timeline replay was not authorized by the frozen phase gate because
the controlled-100 minimum was 0, below the required 100 usable names per
date. No new data acquisition is justified.

## Explicit blocks

Valuation-policy assumptions were not invented, so `margin_of_safety.low` and
`expected_return.central` remain blocked. Cyclicality, concentration, and
event risk were not imputed, so downside risk remains blocked. A separate
hash-bound parent-coverage audit records D&A, cash dividends, and repurchases
as `PARENT_COVERAGE_UNPROVEN`; none enters this company-quality producer chain.

This artifact is capped at `DEVELOPMENT_OBSERVED_TARGET_COMPONENT_ONLY`. A
company-quality component is not a complete assessment, investable condition,
rating, backtest result, PIT-support label, or forward-support label.
