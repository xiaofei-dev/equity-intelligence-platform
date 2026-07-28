# Objective Rating v1 Current Factor-Input Assembly

> Superseded in part by
> `objective-rating-v1-current-factor-window-methodology-audit-2026-07-28.md`.
> The original v1.1 snapshots remain immutable. The later policy adds strict
> fiscal Q4 derivation and a documented direct enterprise-value source route,
> then writes new content-addressed snapshots without modifying this evidence.

Date: 2026-07-27

## Outcome

The offline assembler built immutable, content-addressed factor-input snapshots
for all 55 securities in the frozen source-contract candidate set. The set
content hash is
`86CCFB3BDFDAAD46AC6DCC3D606E66CA16AF94C4A39439ACE404CC7AED7ED3A2`.

This stage produced no scores, percentiles, cohorts, or ranks. It made no
network requests and did not change QC-v1.0.0 or UQ-v1.0.0 formulas, weights,
missing-data rules, or cohort requirements.

The result is:

- full current QC input-ready: 0 of 55;
- full current UQ input-ready: 0 of 55;
- net-debt-to-EBITDA raw input-ready: 55 of 55;
- every other complete QC or UQ factor input remained missing;
- historical FCF-yield percentile remained blocked for 55 of 55.

The zero full-readiness result is an evidence result, not a parser or execution
failure. The 55 securities were source-contract candidates, not previously
proven factor-window candidates.

## Frozen Window Rules

The assembler consumed the frozen v4.1 factor requirements and applied these
rules:

- TTM duration inputs require four consecutive observations classified as
  `DISCRETE_QUARTER`.
- Raw YTD observations are never summed as quarters. Deterministically derived
  discrete quarters retain their SEC operand lineage.
- TTM diluted weighted-average shares use inclusive-duration-day weighting.
- Three-year endpoints require four-quarter windows whose fiscal period ends
  are 1,000 through 1,200 days apart.
- Stability requires eight consecutive, period-aligned discrete quarters for
  operating income, revenue, operating cash flow, and capital expenditure.
- Date continuity, rather than calendar-quarter labels, permits 53/54-week
  fiscal calendars.
- Every source observation must have `availableAt` at or before the sealed
  cutoff of `2026-07-27T23:59:59Z`.
- A current financial window ending more than 200 days before the cutoff is
  stale.
- Missing inputs remain missing. They are not converted to zero or a neutral
  factor.

`Highlights.EBITDA` is accepted only as the documented current-snapshot TTM
provider input. Current total debt and market capitalization use the accepted
current-snapshot supplement contract. Historical FCF-yield history remains
blocked under the frozen PIT policy.

## Coverage Interpretation

The dominant blocker is the absence of a complete, recent sequence of four
independently proven discrete quarters for the required duration operands.
SEC Company Facts often provides Q1 and cumulative YTD records, while the
current strict assembly policy does not treat a raw YTD record as a discrete
quarter and does not infer a fourth quarter from an annual fact.

The assembler also preserves these independent blockers:

- no proven instant minority-interest value or explicit not-applicable
  evidence for enterprise value;
- no minimum 12-month PIT FCF-yield series;
- no complete recent eight-quarter aligned stability window;
- no valid three-year endpoint windows when the current TTM window is absent.

These findings do not authorize a YTD bridge, annual-minus-nine-month
derivation, minority-interest default, or any scoring-rule change. A later
methodology decision must explicitly approve any additional derivation.

## Artifacts

- Git-safe manifest:
  `docs/generated/objective-rating-v1-current-factor-input-manifest-v1-2.json`
- Controlled value store:
  `storage/provider-validation/current-factor-input-snapshots-v1-1`
- Snapshot contract:
  `objective-rating-current-factor-input-v1.1.0`
- Window policy:
  `objective-rating-current-factor-window-v1.1.0`

The manifest contains symbols, statuses, blocker counts, storage references,
and content hashes. It contains no licensed values. Controlled snapshots
contain the operand evidence and remain in gitignored content-addressed
storage.

## Gate Conclusion

`CURRENT_FACTOR_INPUT_GATE = INSUFFICIENT_DATA`

The Algorithm Gate must not calculate Objective Rating v1 for these 55
securities from this artifact. Forward Decision-Quality Validation remains
prohibited.
