# Objective Rating v1: Final 223-Security Algorithm Gate

## Decision

The final Algorithm Scoring Gate is **NOT_ACCEPTED**. No QC or UQ score or rank
was generated.

The result is a contract-level rejection, not a correction of provider data.
All 223 terminal `FORMULA_READY` controlled payloads were loaded and their
canonical hashes verified. The payloads still do not carry enough semantics to
reproduce Objective Rating v1 without assumptions prohibited by the frozen
specification.

## Verified evidence

- Formula-ready aggregate file SHA-256:
  `2B3EE90401BB635FBB07CA977FD35D7A371CB64BB1735D070FC28268598CA9F8`
- Aggregate canonical hash:
  `CE0EB2F588105DA4E12F8BB763EC65B759714A2C4A6C9435C35A9F2ED9F69859`
- Billing sidecar SHA-256:
  `074C8D62F046DA78931B91559A5C5748ACDC045C122056F440D20AADCED1CCD9`
- Terminal population: 243
- Controlled payloads loaded: 223
- Input-level insufficient securities: 20
- Additional network requests: 0

The source manifest, terminal evidence, component reports, per-security source
reports, controlled payloads, and referenced checkpoints were hash-verified.
Licensed raw values remain in Git-ignored controlled storage.

## Blocking contract findings

### Financial duration semantics

Financial observations have `fiscalPeriodEnd` and `periodType`, but no
`periodStart` or explicit `durationSemantics`.

Objective Rating v1 prohibits summing four reported 10-Q values unless they are
independently verified as discrete quarters. It also requires duration-aware
annual-plus-YTD bridges for cumulative data and weighted-duration treatment for
diluted shares. The v2 payload cannot distinguish those cases.

Treating every `QUARTERLY` record as a discrete quarter would silently change
the PIT and TTM rules, so the gate does not do so.

### Historical valuation PIT

Historical daily prices and historical market capitalizations use their 2026
ingestion timestamp as `availableAt`. Their effective dates are earlier.

Objective Rating v1's historical FCF-yield percentile requires the price,
shares, and TTM fundamentals that were available at each historical month-end.
Under the frozen `availableAt <= asOfTime` rule, these records were not
available at those earlier month-ends. Replacing `availableAt` with the
effective trading date would rewrite the source contract and is not allowed.

### Classification snapshot

The final aggregate and controlled payloads do not seal:

- sector;
- market-cap cohort;
- company type;
- classification version;
- universe version;
- a single algorithm `asOfTime` and cutoff.

Without those fields, the gate cannot apply specialized-model exclusions or
choose the sector × size × company-type, sector × company-type, or general
company cohort.

## Result

| State | Count |
|---|---:|
| Input `FORMULA_READY` | 223 |
| Input `SECURITY_INSUFFICIENT_DATA` | 20 |
| Algorithm eligible | 0 |
| QC eligible/scored/ranked | 0 |
| UQ eligible/scored/ranked | 0 |
| Algorithm `INSUFFICIENT_DATA` | 243 |
| Algorithm `NOT_APPLICABLE` | 0 |

The 20 input-level insufficient securities retain their original reason codes.
The 223 controlled inputs receive these algorithm-level reasons:

- `FINANCIAL_DURATION_SEMANTICS_MISSING`;
- `HISTORICAL_VALUATION_PIT_UNAVAILABLE`;
- `COMPANY_CLASSIFICATION_SNAPSHOT_MISSING`.

No missing input is converted to zero or neutral, and no weight is
redistributed.

## Determinism

Two independent offline executions over the same authoritative inputs produced
the same artifact file SHA-256:

`21C8BC79348F63002D007918792203D2D0A540CD63441DC8290F3C6A6ECE15BE`

The canonical gate-result hash is:

`81D41686E94D48CF241D45E432B7A0079674D2BDAFBF3B69B3BFE7187491BCE5`

This proves deterministic rejection for the frozen inputs. It does not prove
deterministic factor values, scores, or ranks because none were admissible.

## Required next input

A new immutable, offline snapshot must add:

1. period start and verified duration semantics for every duration fact;
2. a defensible historical availability timestamp for price and market-value
   observations without overwriting the existing evidence;
3. versioned sector, size, company-type, universe, as-of, and cutoff fields.

If producing those fields requires new provider or SEC requests, separate
authorization is required. The current gate must not infer them.

Forward Decision-Quality Validation remains prohibited.
