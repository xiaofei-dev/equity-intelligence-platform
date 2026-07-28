# Objective Rating v1 Cross-Provider Current Interest Acceptance

Date: 2026-07-28
Policy version: `current-interest-cross-provider-evidence-v1.0.0`
Provider artifact:
`provider-current-interest-cross-validation-20260728T075513Z-483a7026d70b.json`
Evidence-gate status: `ACCEPTED_CURRENT_SNAPSHOT_INPUT_ONLY`

## Acceptance conclusion

The Yahoo-EODHD cross-provider evidence gate is accepted for seven of the ten
frozen securities:

- AMAT, COO, CSCO, DHR, FAST, and TSN:
  `CURRENT_TTM_CONFIRMED`;
- CIEN: `CURRENT_TTM_CONFIRMED_WITH_QUARTER_CONFLICT`.

FIX, PLAB, and WDFC remain `PROVIDER_CONFLICT` and their
`interest_expense_ttm` operand remains `MISSING`.

This accepts only evidence for a provider-normalized current TTM operand.
It does not prove complete gross-interest economic scope, historical PIT
availability, revision history, or quarter-level history. It does not create
a score, rank, strategy result, or Forward Decision-Quality signal.

## Source verification

The immutable provider artifact has:

- ten unique frozen symbols and 100% terminal coverage;
- six `CROSS_PROVIDER_TTM_CONFIRMED` records;
- one `YAHOO_INTERNAL_REVISION_INCONSISTENCY` record;
- three `PROVIDER_VALUE_CONFLICT` records;
- nine Yahoo physical requests and one hash-verified replay;
- zero EODHD and zero SEC physical requests;
- no retries;
- no raw provider values in the Git-safe artifact.

The artifact canonical content hash, its ten controlled comparison hashes,
and its ten raw-envelope file hashes were independently recomputed. All
matched their recorded references.

The controlled local evidence also proved:

- every accepted EODHD four-record sum exactly equals the Yahoo explicit TTM
  value using Decimal equality;
- all three provider-conflict cases are exact mismatches;
- CIEN's EODHD sum exactly equals Yahoo TTM while Yahoo's displayed four
  `3M` values do not sum to that TTM.

The provider implementation permits a small comparison tolerance, but no
accepted result relies on it. Every accepted cross-provider comparison is
exact.

## CIEN ruling

CIEN is accepted at TTM level with the mandatory risk flag
`YAHOO_QUARTER_SERIES_CONFLICT`.

The Yahoo trailing observation explicitly represents TTM and exactly
corroborates the EODHD aggregate. The Yahoo quarterly display is internally
inconsistent with that trailing observation, so:

- `interest_expense_ttm` may be used for the sealed current snapshot;
- Yahoo quarterly values may not be used to construct the operand;
- neither provider's quarterly interest series is authorized for historical
  reconstruction or quarter-level analytics;
- `upstreamIndependenceProven` remains false.

## Conflict ruling

FIX, PLAB, and WDFC remain missing. Their EODHD aggregates differ from Yahoo
TTM, and the existing local SEC evidence does not explain the discrepancy or
prove a complete current denominator.

No zero, neutral value, weight redistribution, or forced rank is allowed.

## Scope and next state

This evidence acceptance unblocks a possible controlled current-input
supplement for seven securities. Provider Integration did not generate such
supplements, so scoring-input integration remains
`NOT_IMPLEMENTED`.

Before any Algorithm Gate rerun, a separate authorized offline step must:

1. write content-addressed current-only supplements for the seven accepted
   operands;
2. retain both providers' source hashes and the policy version;
3. mark CIEN's quarter conflict;
4. leave FIX, PLAB, and WDFC missing;
5. rebuild factor-ready snapshots without changing formulas or cohorts.

Algorithm Gate and Forward Decision-Quality Validation remain stopped.
