# Objective Rating v1 Current Factor-Window Methodology Audit

Date: 2026-07-28

## Decision

This audit changes no Objective Rating v1 formula, weight, missing-data rule,
PIT rule, company-type exclusion, cohort rule, or ranking rule. It authorizes
one new source derivation and one current-only source alternative:

- `SEC-FY-MINUS-9M-v1.0.0` for a strictly proven fiscal fourth quarter; and
- a direct EODHD `Valuation.EnterpriseValue` input when its documented formula
  matches frozen v1.

No score, percentile, cohort, or rank was calculated.

## Fiscal fourth-quarter derivation

`FY annual - same-fiscal-year nine-month YTD = Q4 discrete` is not an
unchanged instance of `SEC-YTD-DIFFERENCE-v1.0.0`. The existing rule requires
the later operand to be YTD and covers adjacent cumulative differences such as
`6M - 3M` and `9M - 6M`. An annual operand has distinct form, duration, revision,
and fiscal-calendar semantics. Q4 therefore uses the separately versioned
`SEC-FY-MINUS-9M-v1.0.0`.

The derivation requires:

- identical entity, taxonomy, concept, unit, currency, dimensions, fiscal
  year, fiscal start, and sign convention;
- a `10-K` `ANNUAL` `FY` fact and a `10-Q` `YTD` `Q3` fact;
- both facts available no later than the sealed cutoff;
- preserved revisions and no amended operand requiring reconciliation;
- an annual duration of 350 through 385 days;
- a nine-month duration of 230 through 310 days;
- a resulting fourth-quarter duration of 60 through 120 days;
- continuous boundaries, with Q4 starting the day after the nine-month end.

The result retains both ordered observation IDs, content hashes, accessions,
availability timestamps, period boundaries, and the derivation version.
Numeric plausibility alone never authorizes the derivation.

Across the 55 candidates, the corrected offline run generated:

- 18,267 adjacent YTD differences under
  `SEC-YTD-DIFFERENCE-v1.0.0`; and
- 9,018 fiscal Q4 differences under `SEC-FY-MINUS-9M-v1.0.0`.

It rejected 78 amended-operand combinations and two fiscal-calendar
alignments. Rejected facts remained missing.

## Three-year and stability windows

Only these frozen factors require a three-year endpoint:

| Factor | Three-year operands |
|---|---|
| Margin quality | Gross profit, operating income, and revenue |
| Diluted EPS growth | Net income and diluted weighted-average shares |
| FCF per diluted share growth | Operating cash flow, capex, and diluted weighted-average shares |
| Dilution | Diluted weighted-average shares |

ROIC, FCF margin, cash conversion, debt service, operating margin, and current
valuation inputs do not acquire a new three-year endpoint merely for data
governance. QC's separate positive median three-year ROIC eligibility condition
belongs to the later strategy eligibility gate; it is not silently added to a
factor formula.

Stability still requires eight consecutive period-aligned discrete quarters
for operating income, revenue, operating cash flow, and capex. The corrected
run made stability input-ready for 43 of 55 securities.

The 200-day current-window freshness check is a versioned implementation of
the frozen stale-data exclusion. It is not a new factor operand. It must remain
visible in the snapshot and can be revised only through a separately approved
freshness-policy version.

## Minority interest and enterprise value

Minority interest is not an input to quality, leverage, cash conversion,
growth, dilution, or stability formulas. It is a component only of frozen
enterprise value:

`market cap + total debt + minority interest - cash`.

Missing minority interest is never converted to zero. The EODHD cache did not
contain a current numeric
`noncontrollingInterestInConsolidatedEntity` value for any of the 216 complete
supplements.

EODHD officially defines `Valuation.EnterpriseValue` with the same frozen
formula. A positive, hash-verified current provider enterprise value therefore
provides an alternative input route for the earnings-yield denominator.
Under that route, the separate minority-interest component is
`NOT_APPLICABLE` because no component reconstruction is performed. This is
source routing, not a formula change, and it is current-snapshot only.

The direct route does not permit:

- treating a missing component as zero;
- reconstructing historical enterprise value;
- claiming field-level revision history; or
- bypassing a missing or nonpositive EBIT numerator.

## Corrected offline result

The final immutable Git-safe manifest is:

`docs/generated/objective-rating-v1-current-factor-input-manifest-v1-4.json`

The controlled snapshots use:

- snapshot contract `objective-rating-current-factor-input-v1.3.0`;
- window policy `objective-rating-current-factor-window-v1.3.0`;
- Git-ignored storage
  `storage/provider-validation/current-factor-input-snapshots-v1-3`.

Results:

- current QC input-ready: 0 of 55;
- current UQ input-ready: 0 of 55;
- net debt / EBITDA input-ready: 55 of 55;
- stability input-ready: 43 of 55;
- QC valuation-guardrail raw inputs ready: 13 of 55;
- 10 securities have every QC factor input except current interest coverage:
  AMAT, CIEN, COO, CSCO, DHR, FAST, FIX, PLAB, TSN, and WDFC.

The universal current QC blocker is now `interest_expense_ttm`: accepted total
SEC `InterestExpense` history exists, but no candidate has a current,
non-stale four-quarter window under that strict concept. Later issuer concept
transitions to narrower interest concepts cannot be accepted without the
already-required issuer consistency and completeness evidence.

UQ remains independently blocked for all 55 by
`historical_fcf_yield_percentile`. The Q4 correction does not relax that
factor.

## Handoff decision

The corrected snapshots may be returned to Provider Integration for
hash-chain and coverage verification. Repeating the same assembly is expected
to produce **zero** fully QC-input-ready securities under the current accepted
interest policy.

The ten interest-only candidates are the maximum immediate QC opportunity, not
an eligibility forecast. They can become input-ready only if a separately
versioned issuer/concept consistency policy proves a current gross-interest
TTM series without mixing net interest, capitalized interest, debt fees, or
incomplete components. No new live request is authorized by this audit.

Algorithm Scoring Gate and Forward Decision-Quality Validation remain
prohibited.

## Official source

- [EODHD Fundamentals glossary](https://eodhd.com/financial-academy/financial-faq/fundamentals-glossary-common-stock)
