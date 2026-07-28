# EODHD `interestExpense` Documentation and Cache Audit

Date: 2026-07-28

## Scope

This audit evaluated the last provider-normalized current-interest evidence
route without calling an EODHD or SEC financial-data endpoint. It used:

- five official EODHD public documentation resources;
- the hash-verified local EODHD Fundamentals response cache;
- the immutable 223-security formula-ready aggregate; and
- the controlled provider-neutral scoring-input payloads.

No numeric provider value is included in the Git-safe artifact. No Objective
Rating formula, weight, cohort, missing-data rule, or PIT threshold changed.

## Official Documentation Findings

The official common-stock glossary defines `interestExpense` as the cost
incurred for borrowed funds. The Academy interest-coverage example uses
`ebit / interestExpense` for a specified period. These sources prove the
field's broad identity, but do not prove the complete frozen-v1 economic
scope.

The following remain undocumented:

- whether capitalized interest, financing fees, lease interest, operating
  interest, or related-party interest are included;
- whether interest income can be netted against the expense;
- whether `quarterly` means a discrete quarter, fiscal YTD, or TTM;
- whether `yearly` is guaranteed to represent one complete fiscal-year
  duration with a defined start date;
- a separate TTM interest-expense field; and
- an immutable field-level revision and publication timeline.

The glossary does document the report currency, period-end `date`, and
`filing_date`. It does not supply an SEC acceptance timestamp. Official
recalculation guidance means historical values can change without an
immutable revision stream, so revision semantics remain contradicted for PIT
history.

## Cache Structure

The frozen aggregate contains 223 `FORMULA_READY` source securities:

- 216 have a hash-verified raw EODHD Fundamentals response cache;
- 7 do not: A, AAPL, ACN, ADBE, ADI, CAT, and JNJ;
- none of the 216 cached responses exposes an explicitly named TTM
  interest-expense path in Highlights, Valuation, or Technicals.

Across the 216 cached responses, the audit found 22,309 non-null quarterly and
7,281 non-null yearly `interestExpense` field occurrences. These are
structure/coverage counts only; values are not persisted in the artifact.
Field presence does not establish duration semantics.

## Ten-Security Result

| Symbol | Raw quarterly non-null | Raw yearly non-null | Controlled records | Period start | SEC accession/hash lineage | Route |
|---|---:|---:|---:|---:|---|---|
| AMAT | 123 | 41 | 11 | 0 | Present | BLOCKED |
| CIEN | 117 | 29 | 11 | 0 | Present | BLOCKED |
| COO | 138 | 41 | 11 | 0 | Present | BLOCKED |
| CSCO | 106 | 38 | 11 | 0 | Present | BLOCKED |
| DHR | 121 | 41 | 11 | 0 | Present | BLOCKED |
| FAST | 106 | 39 | 11 | 0 | Present | BLOCKED |
| FIX | 110 | 29 | 11 | 0 | Present | BLOCKED |
| PLAB | 119 | 41 | 11 | 0 | Present | BLOCKED |
| TSN | 127 | 32 | 11 | 0 | Present | BLOCKED |
| WDFC | 106 | 41 | 11 | 0 | Present | BLOCKED |

Each controlled payload has eight quarterly and three annual EODHD-normalized
interest records with period end, `availableAt`, SEC accession, record hash,
source hash, and immutable controlled-payload hash coverage. None carries a
provider `periodStart`. The SEC accession match proves filing/date lineage; it
does not prove that the provider's quarterly value is a discrete quarter or
that its economic scope equals frozen-v1 gross interest expense.

## Decision

Current-snapshot-only interest coverage remains `BLOCKED` for all ten
securities. The route has:

- no officially documented TTM interest-expense field;
- no officially documented discrete-quarter contract;
- no complete economic-scope definition; and
- no cached period-start evidence capable of closing the duration contract.

No interest supplement or corrected factor snapshot was generated.
Clarification from EODHD Support is required before this provider-normalized
route can be accepted. The support inquiry remains a draft and was not sent.

Machine-readable artifact:

`docs/generated/eodhd-interest-expense-documentation-cache-audit-v1-2.json`
