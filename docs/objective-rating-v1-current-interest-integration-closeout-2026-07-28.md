# Objective Rating v1 Current Interest Integration Closeout

Date: 2026-07-28
Integration version: `current-interest-input-integration-v1.0.0`
Status: `STOPPED_COHORT_TOO_SMALL`

## Outcome

The accepted Yahoo-EODHD current-interest evidence was integrated into a new
immutable current factor-input snapshot at cutoff
`2026-07-28T07:55:16.812055Z`.

Seven content-addressed `CURRENT_SNAPSHOT_ONLY` interest supplements were
created in Git-ignored controlled storage:

- AMAT;
- CIEN;
- COO;
- CSCO;
- DHR;
- FAST;
- TSN.

CIEN retains `YAHOO_QUARTER_SERIES_CONFLICT`. Its Yahoo quarterly values are
not used in the operand and are not authorized for quarter-level history.

FIX, PLAB, and WDFC retain:

```text
interest_expense_ttm.status = MISSING
interest_expense_ttm.reasonCode = PROVIDER_CONFLICT
```

## Reassembled factor inputs

All 55 source-contract candidate snapshots were superseded by version
`objective-rating-current-factor-input-v1.5.0`. The new manifest and all 55
payload hashes were verified.

Results:

| Gate | Count | Status |
|---|---:|---|
| Current QC input-ready | 7 | Valid inputs, but insufficient cohort |
| Current UQ input-ready | 0 | Historical FCF-yield percentile remains missing |
| Provider conflict | 3 | Missing, no numeric substitute |
| Interest supplements | 7 | Current-only |

No licensed values are copied into the Git-safe manifest.

## Cohort gate

Frozen Objective Rating v1 thresholds remain:

- sector × market-cap × company-type: 20;
- sector × company-type: 30;
- general company: 100.

Only seven securities are fully QC input-ready. Seven is below the smallest
allowed threshold of 20, so no factor normalization, score, contribution,
rank, or result hash may be generated.

The bounded Algorithm Gate was not executed. The terminal state is:

```text
COHORT_TOO_SMALL
```

## Unchanged boundaries

- Objective Rating v1 formulas and weights are unchanged.
- Cohort and missing-data rules are unchanged.
- Current evidence is not historical PIT evidence.
- EODHD quarterly interest records are not reclassified as a reusable
  quarter-level history.
- No gross-interest completeness claim is made.
- Forward Decision-Quality Validation remains stopped.
- No network request was made by the integration or methodology acceptance.
