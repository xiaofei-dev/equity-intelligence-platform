# Fundamental Value Stage 7C-2 Company-Quality Producer Pilot Repair

Date: 2026-08-01

## Boundary and result

This was a zero-network, outcome-blind validation-only producer pilot. It did
not read return, benchmark-return, drawdown, rank, or performance fields. It
did not modify the production producer registry or any Stage 1-6 formula.

The repaired gate ran the deterministic 25-security integrity pilot, the
controlled 100-security integrity replay, and then the existing offline 216
timelines. The 216 replay produced zero complete company-quality components on
every frozen date and therefore stopped below the frozen minimum of 100. This
is a producer-coverage result, not a model-quality verdict.

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

The producer contract is
`FV-STAGE7-COMPANY-QUALITY-PRODUCERS-v1.1.0`. It searches exact common parent
period keys and constructs chains over distinct period ends. TTM requires four
distinct quarters; stability requires eight. Quarter-end spacing must be
60-120 days and adjacent boundaries must be within seven days. For multiple
inclusive/exclusive start variants ending on the same date, the selector first
chooses the latest ending chain and then the minimum total deviation from a
91-day quarter. These ranks depend only on period metadata, never values. If
equally ranked variants have incompatible evidence hashes, the affected
producer fails with `EQUALLY_RANKED_PERIOD_VARIANT_AMBIGUITY`. A quarter end is
never counted twice.

Revision selection is local to the exact operand and period used by a selected
chain. An ambiguity elsewhere in the payload cannot invalidate unrelated
producers, while incompatible top-ranked revisions of a required selected
parent fail with `SELECTED_PARENT_REVISION_AMBIGUITY`. Exact cross-parent
alignment, USD units, period end by cutoff, and strict availability by cutoff
remain mandatory; no nearest-date or current-value fallback exists.

The 0-0.50 tax-rate bound was retained outcome-blind. It rejects tax benefits,
negative pretax-income ratios, and extreme one-off effective rates instead of
turning them into ordinary operating economics. The 120-day balance rule was
also retained: it is a prior-only one-quarter staleness ceiling around each TTM
boundary and never admits a post-boundary balance. Both rules are conservative
coverage choices already frozen in the pilot; neither was changed after seeing
coverage.

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
| 2019-06-21 | 0 | 1 | 0 | 2 | 0 | 0 |
| 2020-04-20 | 0 | 2 | 1 | 3 | 1 | 0 |
| 2021-06-02 | 0 | 3 | 1 | 4 | 1 | 0 |
| 2022-05-18 | 0 | 3 | 1 | 4 | 1 | 0 |
| 2023-05-18 | 0 | 3 | 1 | 4 | 1 | 0 |

The offline-216 strict-PIT operand VALID counts by date are:

| Date | ROIC | Operating margin | FCF margin | Earnings stability | Cash-flow stability | Complete company quality |
|---|---:|---:|---:|---:|---:|---:|
| 2015-05-07 | 0 | 0 | 0 | 0 | 0 | 0 |
| 2016-05-19 | 0 | 0 | 0 | 0 | 0 | 0 |
| 2017-06-30 | 0 | 0 | 0 | 0 | 0 | 0 |
| 2018-04-09 | 0 | 0 | 0 | 0 | 0 | 0 |
| 2019-06-21 | 0 | 2 | 0 | 2 | 0 | 0 |
| 2020-04-20 | 0 | 3 | 1 | 3 | 1 | 0 |
| 2021-06-02 | 0 | 4 | 1 | 4 | 1 | 0 |
| 2022-05-18 | 0 | 4 | 1 | 4 | 1 | 0 |
| 2023-05-18 | 0 | 4 | 1 | 4 | 1 | 0 |

For every date, the remainder of each 25, 100, or 216 denominator is explicit
`MISSING`; no operand in this replay ended `INVALID`. Across all nine
offline-216 dates the reason counts are: `MISSING_ALIGNED_PERIODS` 9,669,
`BALANCE_PARENT_ALIGNMENT_MISSING` 4, `TAX_RATE_OUTLIER` 5, and `VALID` 42.
Target-propagated reasons are separately counted in the checked summary. The
phase matrix hashes are `8E8CE1EA170972622D01D5F54F12B3D0B2F20B0D924BC56A442EA6391325A520`,
`A64AD4B41E8FFAD294887FC6429C107D3F50FF8D7BBB11FA78EF6DF0F9911B65`,
and `AF58780978C267E57D4AB2B56C4864DCC85416275EC67F891F6942C1EB2A20E2`
for 25, 100, and 216 respectively. Current-revision approximation was not run
and remains separate.

Integrity and semantic success, not 100% coverage, authorizes the next offline
phase. The frozen coverage threshold is evaluated only after 216. Its minimum
complete count is 0, below 100, so the acquisition/returns gate remains closed.

## Explicit blocks

Valuation-policy assumptions were not invented, so `margin_of_safety.low` and
`expected_return.central` remain blocked. Cyclicality, concentration, and
event risk were not imputed, so downside risk remains blocked. A separate
hash-bound parent-coverage audit records D&A, cash dividends, and repurchases
as `PARENT_COVERAGE_UNPROVEN`; none enters this company-quality producer chain.

This artifact is capped at `DEVELOPMENT_OBSERVED_TARGET_COMPONENT_ONLY`. A
company-quality component is not a complete assessment, investable condition,
rating, backtest result, PIT-support label, or forward-support label.
