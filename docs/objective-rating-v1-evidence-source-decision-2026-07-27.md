# Objective Rating v1 Evidence Source Implementation Decision

> Superseded in part by
> `objective-rating-v1-source-semantics-audit-2026-07-28.md`. The v4.0 SEC
> timeline and hashes remain immutable evidence, but its
> `InterestExpenseNonOperating`-only policy was not part of frozen v1 and used
> the wrong current-taxonomy spelling. The later audit also establishes a
> separate current-only provider route for EODHD
> `shortLongTermDebtTotal` and `Highlights.EBITDA` TTM. Do not use this
> document's strict interest, SEC-only total-debt, or SEC-derived EBITDA
> conclusions for new current-snapshot eligibility decisions. Historical PIT
> conclusions remain unchanged.

## Outcome

The offline SEC timeline implementation is accepted as a real
`provider-neutral-scoring-input-v4.0.0` evidence layer. It does not make the
Objective Rating algorithms eligible to run.

The implementation:

- verified the frozen 223-security formula-ready aggregate and cached response
  hashes;
- built content-addressed v4 timelines for 216 securities in Git-ignored
  controlled storage;
- retained exact SEC concept, unit, start, end, form, frame, accession, filed
  date, acceptance timestamp, revision, and source hashes;
- created 59,583 deterministic discrete-quarter derivations under
  `SEC-YTD-DIFFERENCE-v1.0.0`;
- left A, AAPL, ACN, ADBE, ADI, CAT, and JNJ as
  `OFFICIAL_SEC_TIMELINE_NOT_CACHED`;
- executed no network request, rating, Algorithm Gate, or Forward Validation.

The final Git-safe manifest is
`docs/generated/scoring-input-v4-sec-offline-manifest-v2.json`. It contains
only counts, reason codes, storage references, and hashes. SEC and provider
values remain outside Git.

## Frozen formula-to-evidence mapping

The mapping below describes source eligibility. It does not change any factor,
weight, required-factor rule, cohort rule, or missing-data behavior.

| Objective Rating operand | Authorized SEC evidence | Current cache result | Decision |
|---|---|---:|---|
| Revenue | `RevenueFromContractWithCustomerExcludingAssessedTax`, then issuer-reviewed `Revenues`, then issuer-reviewed `SalesRevenueNet` | 210 securities | Retain exact concept and mapping priority; do not merge overlapping facts |
| Operating income / EBIT input | `OperatingIncomeLoss` | 193 | Authorized when period, unit, context, and revision selection pass |
| Gross profit | `GrossProfit` | 115 | Authorized; otherwise missing |
| Net income | `NetIncomeLoss` | 205 | Authorized; otherwise missing |
| Income tax | `IncomeTaxExpenseBenefit` | 216 | Authorized; invalid denominators remain invalid |
| Pretax income | `IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest` | 196 | Authorized only for the frozen tax and EBITDA derivation semantics |
| Operating cash flow | `NetCashProvidedByUsedInOperatingActivities` | 216 | Authorized |
| Capital expenditure | `PaymentsToAcquirePropertyPlantAndEquipment` | 183 | Authorized; broader PP&E concepts are not automatic synonyms |
| Diluted weighted-average shares | `WeightedAverageNumberOfDilutedSharesOutstanding`, then the combined basic-and-diluted concept | 216 | Authorized only as duration shares; never substituted for instant shares |
| Cash | `CashAndCashEquivalentsAtCarryingValue` | 212 | Authorized; restricted-cash combinations require another mapping version |
| Stockholders' equity | `StockholdersEquity` | 210 | Authorized; NCI-inclusive equity is not an automatic synonym |
| Interest expense | `InterestExpenseNonOperating` | 0 | Missing. `InterestExpense` and `InterestAndDebtExpense` are not silently accepted |
| Debt | Exact current/noncurrent long-term debt and short-term borrowing components | 150 / 158 / 100 | Retained as components; total debt is missing until non-overlap and completeness are proven |
| D&A | `DepreciationDepletionAndAmortization` | 162 | Authorized only as an EBITDA derivation operand |
| Instant common shares | `dei:EntityCommonStockSharesOutstanding` | 196 | Candidate evidence; market-cap use additionally requires traded-class identity |

The cache contains useful direct evidence for many factors. The manifest's
`factorEvidenceCandidateCounts` only means that at least one accepted primitive
exists for every listed direct operand. It is not TTM, eight-quarter,
three-year, factor, or ranking eligibility.

## EBITDA, interest, debt, and shares ruling

There is no authorized direct standard US-GAAP EBITDA concept.

`SEC-EBITDA-DERIVATION-v1.0.0` may calculate:

`pretax income + non-operating interest expense + depreciation, depletion and amortization`

only when all operands have the same issuer, currency, compatible consolidated
context, economic period, cutoff-valid revision, and duration semantics. The
current cache has zero securities with the strict interest concept, so no
EBITDA is derived.

Interest coverage remains missing for the same reason. Broad interest tags can
include debt interest, capitalized interest, total interest, or another
economically different scope. Provider-normalized values do not repair the
missing SEC concept and statement-role proof.

Debt components are not summed automatically because concepts can overlap and
issuers report different debt structures. A future issuer-aware mapping must
prove a complete, non-overlapping total-debt family.

`dei:EntityCommonStockSharesOutstanding` is an instant fact, not a duration
average. It may support market capitalization only after a durable listing and
share-class mapping proves that the SEC fact represents the traded security.
The diluted weighted-average share count is not a substitute.

## Historical market observation policy

Official EODHD documentation defines raw OHLC as unadjusted and
`adjusted_close` as split-and-dividend adjusted, but the EOD response
documentation does not define a historical publication timestamp.

`US-EOD-NEXT-SESSION-OPEN-v1.0.0` is accepted as a conservative internal PIT
policy:

- raw close for trading session T becomes available only at the open of the
  next session in a versioned US exchange calendar;
- a session-open timestamp must be supplied explicitly;
- adjusted close is retained only for total-return uses;
- the policy is not represented as provider publication metadata;
- provider corrections and restatements remain unproven.

This policy can establish conservative price availability. It cannot by itself
establish historical market capitalization. The frozen UQ
`historical_fcf_yield_percentile` remains blocked until at least 12 monthly PIT
market-cap observations can be reconstructed without later revisions or
diluted-share substitution.

## Recalculated eligibility

| Scope | Eligible | Result |
|---|---:|---|
| SEC timeline built | 216 / 223 | Evidence layer accepted |
| Current-only QC | 0 / 223 | `INSUFFICIENT_DATA` |
| Current-only UQ | 0 / 223 | `INSUFFICIENT_DATA` |
| Historical PIT | 0 / 223 | `INSUFFICIENT_DATA` |
| Forward Validation | 0 / 223 | Not authorized and not ready |

Current-only ratings are assessed separately from historical readiness. They
are not rejected merely because a backtest is unavailable. In this cache,
however, current QC and UQ still fail their own required operands: strict
interest, proven total debt, EBITDA, current market capitalization, and
valuation-derived factors. UQ additionally requires the historical FCF-yield
percentile.

## Remaining source decision

No repeat of the existing EODHD or SEC Company Facts endpoints is justified.
Those responses do not add the missing semantics.

The next decision is a source-route choice:

1. **SEC filing-evidence route:** authorize a bounded acquisition and parser
   extension for official filing Inline XBRL presentation/context evidence,
   plus submissions and Company Facts for the seven uncached securities.
   Acceptance must prove interest scope, debt-family completeness, dimensions,
   statement role, and traded-share-class mapping. Missing concepts remain
   missing even after this work.
2. **Licensed PIT fundamentals route:** evaluate a source that supplies total
   debt, EBITDA, gross interest expense, class-specific instant shares or
   historical market capitalization, period start/end, publication
   availability, revision identity, and durable source lineage. A provider
   field without these semantics does not pass.

This work can be handed back to Provider Integration to consume the v4 adapter
and manifest. Provider Integration cannot truthfully declare scoring
eligibility until one source route above passes. Algorithm Gate remains
blocked; Forward Validation remains prohibited.

## Official evidence

- SEC EDGAR API documentation:
  <https://www.sec.gov/search-filings/edgar-application-programming-interfaces>
- SEC Financial Statement Data Sets:
  <https://www.sec.gov/data-research/sec-markets-data/financial-statement-data-sets>
- EODHD historical EOD documentation:
  <https://eodhd.com/financial-apis/api-for-historical-data-and-volumes>
- EODHD fundamentals documentation:
  <https://eodhd.com/financial-apis/stock-etfs-fundamental-data-feeds>
