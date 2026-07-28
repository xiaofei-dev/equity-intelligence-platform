# Provider Current-Interest Cross-Validation v1

Date: 2026-07-28

## Scope

This bounded validation compared Yahoo Finance public
`fundamentals-timeseries` interest observations with existing hash-verified
EODHD Fundamentals caches for exactly:

`AMAT`, `CIEN`, `COO`, `CSCO`, `DHR`, `FAST`, `FIX`, `PLAB`, `TSN`, and
`WDFC`.

No EODHD or SEC request was made. Yahoo raw responses and numeric comparisons
are stored only in Git-ignored, content-addressed controlled storage. The
Git-safe artifact contains dates, statuses, source hashes, comparison hashes,
and lineage, but no provider values.

This validation does not authorize an Objective Rating input, create an
interest supplement, run a score, or change a formula. Methodology acceptance
belongs to Main Algorithm.

## Contracts

- Transport schema:
  `yahoo-fundamentals-timeseries-transport-v1.0.0`
- Normalization contract:
  `yahoo-interest-normalization-v1.0.0`
- Comparison policy:
  `provider-current-interest-comparison-v1.0.0`
- Git-safe artifact schema:
  `provider-current-interest-cross-validation-v1.0.0`

The normalizer requires:

- `quarterlyInterestExpense` records to declare `periodType=3M`;
- `annualInterestExpense` records to declare `periodType=12M`;
- `trailingInterestExpense` records to declare `periodType=TTM`;
- a non-null finite value, currency, and valid `asOfDate`;
- four distinct latest quarterly dates with gaps from 70 through 120 days;
- consistent Yahoo currency and matching EODHD currency; and
- four EODHD cached observations on the exact Yahoo quarterly dates.

Numeric equality allows only the greater of one currency unit or one
millionth of the reference value. Absolute and relative differences are
preserved in controlled storage and represented in the Git-safe artifact by
comparison status and evidence hash.

## Classifications

- `CROSS_PROVIDER_TTM_CONFIRMED`: Yahoo's displayed four-quarter sum matches
  Yahoo TTM and the EODHD same-date four-quarter sum also matches Yahoo TTM.
- `PROVIDER_VALUE_CONFLICT`: Yahoo is internally consistent, but the EODHD
  same-date four-quarter sum does not match Yahoo TTM.
- `YAHOO_INTERNAL_REVISION_INCONSISTENCY`: Yahoo's displayed quarters do not
  reconcile to Yahoo TTM. A matching EODHD sum is recorded separately and
  does not resolve the Yahoo revision question.
- `INSUFFICIENT_DATA`: a required series, period type, currency, date,
  continuity rule, or same-date provider observation is missing or invalid.

## Terminal Result

Run ID: `20260728T075513Z-483a7026d70b`

| Symbol | Classification | Yahoo 4Q vs TTM | EODHD 4Q vs Yahoo TTM |
|---|---|---|---|
| AMAT | `CROSS_PROVIDER_TTM_CONFIRMED` | Match | Match |
| CIEN | `YAHOO_INTERNAL_REVISION_INCONSISTENCY` | Conflict | Match |
| COO | `CROSS_PROVIDER_TTM_CONFIRMED` | Match | Match |
| CSCO | `CROSS_PROVIDER_TTM_CONFIRMED` | Match | Match |
| DHR | `CROSS_PROVIDER_TTM_CONFIRMED` | Match | Match |
| FAST | `CROSS_PROVIDER_TTM_CONFIRMED` | Match | Match |
| FIX | `PROVIDER_VALUE_CONFLICT` | Match | Conflict |
| PLAB | `PROVIDER_VALUE_CONFLICT` | Match | Conflict |
| TSN | `CROSS_PROVIDER_TTM_CONFIRMED` | Match | Match |
| WDFC | `PROVIDER_VALUE_CONFLICT` | Match | Conflict |

CIEN is intentionally not resolved here. Its EODHD same-date four-quarter sum
matches Yahoo TTM, while Yahoo's currently displayed four quarters do not
reconcile to that TTM. Main Algorithm must decide whether this cross-provider
evidence is methodologically acceptable.

The existing offline SEC evidence for CIEN, FIX, PLAB, and WDFC does not
explain the differences. It either lacks current acceptable gross-interest
facts or does not prove provider revision timing and complete economic-scope
equivalence.

## Execution and Lineage

- Terminal-run Yahoo physical attempts: 9
- Hash-verified Yahoo response replays: 1 (AMAT)
- EODHD physical attempts: 0
- SEC physical attempts: 0
- Retries: 0
- Earlier response-structure probe: 1 Yahoo request
- Earlier incomplete AMAT transport attempt reused by the terminal run: 1
- Total Yahoo physical requests across implementation and terminal execution:
  11

The initial AMAT transport completed and was stored before a parser rejected
Yahoo's single-item `meta.type` array. The parser was corrected and covered by
a regression test. The terminal run replayed that immutable AMAT response
instead of requesting it again.

Git-safe artifact:

`docs/generated/provider-current-interest-cross-validation-20260728T075513Z-483a7026d70b.json`

- Artifact content hash:
  `D40DE58FF9AE058507FCAA0DD8CF9152B5A2D4D4616862A02B385BFAD9A1E1B4`
- File SHA-256:
  `4867C85B8975CA0A4B6600A83903D637EFA792DFEE0899560890C472B1E576B3`

No interest supplement was generated.
