# Objective Rating v1: 300-Security Expansion Algorithm Gate

## Decision

The expansion Algorithm Scoring Gate is **NOT_ACCEPTED**.

The provider universe contains 300 unique securities: 243 `PASS`, 27
`PARTIAL`, and 30 `EXCLUDED`. All 243 live-confirmed controlled payloads were
loaded and hash-verified. None contains the complete operands required by
`QC-v1.0.0` and `UQ-v1.0.0`, so no numeric score or rank is emitted.

This decision does not reverse the provider acceptance. It preserves the
separate meanings of provider coverage and algorithm eligibility.

## Authoritative evidence

- Final aggregate SHA-256:
  `5AA19700E6DDD0F874A97C4A8A1F3D16346BFFB0BBD82EADE67E1CB6FE1428B7`
- Final billing reconciliation SHA-256:
  `D7AE336CEB0165A15B06DE76EC0DC050DAB7CD3E404DCB2B4E55322F71272D5F`
- Controlled payloads loaded: 243
- Additional network requests: 0
- Licensed values written to Git artifacts: 0

The gate verified the aggregate, reconciliation, 17 source scoring-input
manifests, 243 canonical payload hashes, and every record content hash. The
record adapter reconstructs the producer's original `+00:00` timestamp form
before verifying record hashes because the persisted Pydantic JSON form uses
`Z`. No financial value is changed by this representation-only adapter.

## Contract validation

The controlled records pass the following checks:

- decimal parsing;
- unit presence;
- effective, available, and ingestion timestamps;
- `availableAt` no later than the frozen aggregate cutoff;
- provider and source reference;
- accession where supplied;
- source and record content hashes;
- payload canonical hashes.

The payload contract contains only these financial fields:

- capital expenditure;
- cash and equivalents;
- income tax;
- long-term debt where reported;
- net income;
- operating cash flow;
- operating income;
- pretax income;
- revenue;
- shares outstanding;
- stockholders' equity;
- total assets;
- total debt where reported;
- total liabilities.

## Formula gaps

All 243 provider `PASS` securities lack:

- diluted weighted-average shares;
- EBITDA;
- gross profit;
- interest expense;
- historical market capitalization or equivalent PIT price inputs.

`CALM` additionally lacks total debt. Point-in-time shares outstanding cannot
replace diluted weighted-average duration shares.

Consequently the payloads cannot reproduce:

- gross-margin quality;
- diluted EPS growth;
- FCF per diluted share growth;
- dilution;
- net debt / EBITDA;
- interest coverage;
- earnings yield;
- FCF yield;
- historical FCF-yield percentile;
- the QC valuation guardrail.

Some individual factors could be derived from the available fields, but both
strategies require every configured factor. Partial factor calculation cannot
produce a strategy score, contribution total, cohort rank, or valuation rank.

## Results

| Population | Count | Algorithm result |
|---|---:|---|
| Provider `PASS` payloads loaded | 243 | `INSUFFICIENT_DATA` |
| Provider `PARTIAL` | 27 | `INSUFFICIENT_DATA` |
| Provider `EXCLUDED` | 30 | `NOT_APPLICABLE` |
| Formula-ready | 0 | — |
| QC scored/ranked | 0 | Not evaluable |
| UQ scored/ranked | 0 | Not evaluable |

The deterministic gate-decision hash is reproducible for the same aggregate,
reconciliation, manifests, payloads, and algorithm versions. Ranking stability,
sector comparisons, size comparisons, extreme-value analysis, and contribution
reconciliation remain `NOT_EVALUABLE` because no valid strategy score exists.

## Required offline integration work

Integration must extend the controlled scoring snapshot with the missing
formula operands and histories, using the frozen scoring-ready snapshot
contract. Each new observation must retain its value, unit, currency,
period/effective time, `availableAt`, ingestion time, source/accession, content
hash, parser/normalization version, and classification version.

No field may be inferred as zero. No later observation may enter an earlier
snapshot. Any new live data requirement must be separately approved before
another Algorithm Gate run.

Forward Decision-Quality Validation remains out of scope and must not start.
