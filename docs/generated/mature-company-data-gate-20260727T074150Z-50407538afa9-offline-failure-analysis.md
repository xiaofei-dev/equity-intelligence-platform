# Mature Company Data Gate Offline Failure Analysis

## Scope and evidence

- Run ID: `20260727T074150Z-50407538afa9`
- Immutable gate report SHA-256: `47DD2B16254E7E3C02C6543B0B5662B0DAF053313EA57DDF5971921CE9BDFCF9`
- Analysis inputs: the immutable report, repository implementation, offline tests, fixtures, and mocks.
- No EODHD or SEC request was made.
- The immutable report was not modified.

The companion CSV is the exact per-security matrix at the evidence resolution retained by the gate report. The report retained a Boolean `requiredRatingFields` result, not the identity of each absent normalized field. Therefore, a retrospective 13-column raw-field matrix cannot be reconstructed without inventing evidence. For each of the 36 affected securities, the specific missing member or members of `revenue`, `operating_income`, `net_income`, `income_tax`, `pretax_income`, `total_assets`, `total_liabilities`, `stockholders_equity`, `cash_and_equivalents`, `total_debt`, `operating_cash_flow`, `capital_expenditure`, and `shares_outstanding` are `NOT_CAPTURED`.

## Failure frequency

| Failure field or reason | Securities |
|---|---:|
| Missing required rating field set | 36 |
| Missing PIT availability | 13 |
| SEC CIK not found | 1 |
| SEC request failed | 1 |
| Both required-field and PIT failures | 2 |
| Unique non-PASS securities | 49 |

Required-field symbols: NVDA, AVGO, QCOM, AMAT, ADI, PLAB, OLED, CMCSA, TMUS, EA, SBUX, ROST, ORLY, CROX, PEP, MDLZ, CALM, ISRG, ADP, HON, ETN, FAST, EXPO, SAIA, AEP, EXC, XEL, UFPI, WDFC, HWKN, LRCX, KLAC, INTU, MCHP, HSIC, and PCAR.

PIT symbols: VZ, AZO, COST, PEP, KR, ABT, MDT, TMO, EW, EXPO, NEE, PKG, and CAH.

Special SEC failures: LANC (`SEC_EDGAR_CIK_NOT_FOUND`) and TXN (`SEC_EDGAR_REQUEST_FAILED`).

## Defect classification

### Financial-field parsing and mapping

The implementation maps a bounded set of exact EODHD keys and the offline fixture exercises only those mapped spellings. The gate evaluates required-field coverage as a union across every retained financial observation, then persists only a Boolean result. These are confirmed evidence-capture and mapping-boundary limitations.

No retained native payload or per-field missing list proves which keys were absent for the 36 securities. Consequently:

- Parser or mapping defect: `SUSPECTED_NOT_PROVEN` for all 36.
- Genuine provider omission: `NOT_PROVEN` for all 36.
- Per-field frequency among the 13 normalized inputs: `NOT_DETERMINABLE_FROM_RETAINED_EVIDENCE`.

The next focused run must retain sanitized normalized field-presence evidence by security, statement type, period type, and period. It must not retain licensed native responses.

### PIT matching

The implementation has two confirmed limitations:

1. The bulk path uses only the SEC submissions `recent` collection and does not load referenced historical submission files.
2. EODHD fiscal period ends are matched to SEC fact periods exactly or within seven days.

The supported filing-form set is limited to 10-K, 10-Q, 10-K/A, and 10-Q/A. These limitations can produce false missing-PIT results, but the immutable report does not retain the unmatched fiscal periods, candidate SEC periods, form, or accession evidence needed to assign any of the 13 cases conclusively.

- PIT matching defect: `SUSPECTED_NOT_PROVEN` for the 13 symbols.
- Genuinely unavailable filing: `NOT_PROVEN` for the 13 symbols.
- LANC mapping failure: `UNRESOLVED`; the report does not retain the SEC ticker-map evidence.
- TXN request failure: `UNRESOLVED`; the report retains no sanitized endpoint-level failure detail.

## Recoverability estimate

The exact recoverable count is not evidence-determinable. A planning estimate is **15 companies**: the 13 PIT cases plus LANC and TXN are candidates for recovery through SEC history/matching, identity mapping, or a bounded retry. Confidence is low because none can be conclusively classified from retained evidence. The defensible range is **0 to 49**; the 36 required-field cases cannot be added to the estimate until field-presence evidence exists.

This estimate is not a gate result and does not change any Objective Rating v1 requirement.

## Focused retest proposal and exact ceiling

Use exactly five representatives, one network pass each:

| Symbol | Purpose |
|---|---|
| NVDA | Required-field presence capture |
| EXPO | Combined required-field and PIT matching |
| VZ | PIT-only matching |
| LANC | SEC ticker-to-CIK mapping |
| TXN | Sanitized SEC request failure classification |

Maximum EODHD physical attempts: **25** (five endpoints times five symbols).

Configured local EODHD weight: **70** (14 per one-pass symbol).

Provisional provider billing: **125** (25 observed calls per one-pass symbol).

Exact provider-billed safety ceiling: **188** (ceiling of 125 times the 1.5 safety multiplier).

Maximum SEC physical attempts: **15** (ticker mapping, submissions, and company facts for five symbols). No second network pass is authorized by this proposal; persistence idempotency must use immutable normalized payload replay.

## Conclusion

**NEEDS_DESIGN_DECISION**

Before a focused retest can yield a conclusive defect split, the gate artifact schema must be approved to retain:

- exact missing normalized fields by statement and period;
- unmatched EODHD and SEC period identifiers and day offsets;
- SEC filing form and accession matching state;
- sanitized endpoint-specific SEC failure codes.

This is an acceptance-evidence schema decision only. It does not alter Objective Rating v1 formulas, required fields, thresholds, or public contracts.
