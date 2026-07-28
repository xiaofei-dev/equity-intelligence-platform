# Objective Rating v1 Evidence Methodology and Scoring Input v4

Version note: `objective-rating-evidence-policy-v4.2.0` supersedes only the
source-semantic decisions identified in
`objective-rating-v1-source-semantics-audit-2026-07-28.md`. Frozen rating
formulas remain unchanged. Existing v4.0 payloads remain immutable.

## Decision

Objective Rating formulas, weights, cohort rules, PIT rules, specialized-model
exclusions, and missing-data behavior remain unchanged.

The next integration route is an SEC-authoritative financial timeline plus a
separately evidenced market-observation timeline. Existing EODHD fundamentals
may remain lineage evidence, but their quarterly bucket and period end do not
prove duration semantics. Repeating the same endpoint cannot repair that gap.

The original v3 cache audit was not suitable for scoring:

- current ranking eligible: 0;
- historical PIT eligible: 0;
- `DURATION_SEMANTIC_UNPROVEN`: 223;
- `PERIOD_START_NOT_RETAINED`: 223;
- `HISTORICAL_VALUATION_PIT_UNPROVEN`: 223.

No Algorithm Gate or Forward Decision-Quality Validation is authorized by this
decision.

The subsequent v4 implementation hash-verified that evidence and built 216
SEC-authoritative, content-addressed timelines. Seven securities have no cached
SEC transport. The v4 evidence layer is real and independently replayable.
The current-only EODHD supplement route now accepts documented provider total
debt and `Highlights.EBITDA` TTM. Full current QC eligibility remains zero
until the exact factor windows are assembled and validated. Current UQ and
historical PIT also retain their independent historical-valuation blockers. See
`objective-rating-v1-evidence-source-decision-2026-07-27.md`.

## Factor and operand audit

`INSTANT` facts have one economic date. `DURATION` facts require start and end.
`MARKET_OBSERVATION` records require a trading date and proven observation
availability. `DERIVED` values retain every operand and derivation version.

| Factor | Required operands | Types | Current window | Historical valuation/backtest window |
|---|---|---|---|---|
| ROIC | operating income, income tax, pretax income, current/prior equity, debt and cash | DURATION + INSTANT + DERIVED | Current PIT TTM; current and prior invested capital | Rebuild at every historical cutoff |
| FCF margin | CFO, capex, revenue | DURATION + DERIVED | PIT TTM | PIT TTM at each observation |
| Cash conversion | CFO, capex, net income | DURATION + DERIVED | PIT TTM | PIT TTM at each observation |
| Margin quality | gross profit, revenue, operating income; current and three-year comparison | DURATION + DERIVED | Current PIT TTM plus three-year comparator | Same relative to each historical cutoff |
| Stability | quarterly operating income, CFO, capex and revenue | DURATION + DERIVED | At least eight aligned discrete quarters | Eight quarters known at each cutoff |
| EPS growth | net income attributable for the formula and diluted weighted-average shares | DURATION + DERIVED | Positive endpoints separated by three years | Endpoint facts known at each cutoff |
| FCF/share growth | CFO, capex, diluted weighted-average shares | DURATION + DERIVED | Positive endpoints separated by three years | Endpoint facts known at each cutoff |
| Net debt/EBITDA | debt, cash, EBITDA | INSTANT + DURATION + DERIVED | Current PIT TTM and instant balance sheet | Rebuild at each cutoff |
| Interest coverage | EBIT and interest expense | DURATION + DERIVED | Current PIT TTM | Rebuild at each cutoff |
| Dilution | diluted weighted-average shares | DURATION + DERIVED | Three-year CAGR | Three-year endpoints known at cutoff |
| Earnings yield | EBIT, market cap, debt, cash, minority interest | DURATION + INSTANT + MARKET_OBSERVATION + DERIVED | Last completed trading day and PIT TTM | Rebuild at each month-end |
| FCF yield | CFO, capex, market cap | DURATION + MARKET_OBSERVATION + DERIVED | Last completed trading day and PIT TTM | Rebuild at each month-end |
| Historical FCF-yield percentile | monthly FCF yields | DERIVED | Target 60, minimum 12 PIT monthly observations | Rebuild without later facts or revisions |
| Operating margin | operating income and revenue | DURATION + DERIVED | Current PIT TTM | Rebuild at each cutoff |
| Valuation guardrail | earnings-yield and FCF-yield cohort percentiles | DERIVED | Current cross-section | Historical cross-section at cutoff |

Every primitive observation requires entity, taxonomy/concept where relevant,
unit, currency, economic period, `availableAt`, source reference, content hash,
revision identity, and accession. A missing or invalid denominator stays
missing.

## SEC-authoritative financial timeline

### Permitted source

Use only official SEC submissions and official standard-taxonomy facts from
Company Facts, Company Concept, filing Inline XBRL, or SEC bulk files. SEC APIs
aggregate non-custom facts applying to the filing entity; custom concepts are
not silently promoted to standard concepts.

Each retained fact includes:

- CIK and durable security/entity mapping version;
- taxonomy and exact concept;
- value and SEC unit;
- start and end for duration facts, or end for instant facts;
- filed date and accepted timestamp;
- form, fiscal year/period and frame;
- accession number;
- source response hash, retrieval time and parser version;
- amendment/restatement status.

`availableAt` is the SEC acceptance timestamp when available. A filed date is
not silently upgraded to an intraday acceptance time. If only a date is known,
availability is conservatively the next complete trading day.

### Concept mapping

Create `sec-us-gaap-objective-rating-map-v1.0.0`. Each normalized operand has an
ordered allow-list of exact standard concepts, expected balance/duration type,
allowed units, and issuer-specific selection evidence. Examples for coverage
testing include:

- `RevenueFromContractWithCustomerExcludingAssessedTax`;
- `Revenues`;
- `OperatingIncomeLoss`;
- `GrossProfit`;
- `NetIncomeLoss`;
- `IncomeTaxExpenseBenefit`;
- `NetCashProvidedByUsedInOperatingActivities`;
- `PaymentsToAcquirePropertyPlantAndEquipment`;
- `WeightedAverageNumberOfDilutedSharesOutstanding`;
- `InterestExpense`;
- `StockholdersEquity`;
- `CashAndCashEquivalentsAtCarryingValue`;
- `EntityCommonStockSharesOutstanding` from `dei`.

Names in this list are candidates, not interchangeable synonyms. Selection is
valid only after dimensional, statement-role, unit, period and issuer evidence
passes. An extension concept or a broader/narrower concept requires a new
mapping version and explicit review. Unknown concepts remain missing.

There is no single standard US-GAAP EBITDA concept. Frozen v1 accepts a
normalized reported EBITDA input; it did not freeze the later
pretax-plus-interest-plus-D&A derivation. Integration therefore needs either:

1. a provider-reported EBITDA with documented TTM or bridgeable duration
   semantics; or
2. a separately approved future formula/source-normalization change.

Until one route is accepted, net debt/EBITDA remains missing.

Frozen v1 interest coverage uses gross reported interest expense. Consolidated
`InterestExpense` is the primary standard concept. `InterestExpenseDebt` and
`InterestExpenseNonoperating` require an issuer-consistency policy proving
complete scope. `InterestAndDebtExpense`, net interest, capitalized interest,
and component-only facts remain invalid.

### Fact selection and revisions

At cutoff, select only facts whose accepted `availableAt` is at or before the
cutoff. Prefer the latest accepted accession available at that time for the
same entity, concept, unit, dimensions and economic period. Preserve earlier
facts; never overwrite them.

Amended filings create new revisions. A later amendment affects only snapshots
whose cutoff follows its acceptance. Conflicting same-priority facts are
`INVALID` unless a deterministic filing/context rule selects one.

### Discrete quarters and YTD

An SEC duration fact retains its actual start and end. A fact is `ANNUAL`,
`YTD`, or `DISCRETE_QUARTER` only from its dates, form, fiscal context and
versioned duration classifier.

YTD subtraction is allowed only when both facts have:

- the same entity, taxonomy, concept, unit and dimensions;
- the same fiscal-year start;
- ordered period ends within the same fiscal year;
- both accessions accepted no later than the target cutoff.

`discrete = later YTD - earlier YTD` uses
`SEC-YTD-DIFFERENCE-v1.0.0` and retains both facts, accessions, values and
availability timestamps. Otherwise the quarter is missing. Weighted diluted
shares use duration-day weighting and the existing weighted YTD bridge, not
instant shares.

## Historical valuation PIT reconstruction

At historical month-end:

1. Select the last completed US trading session on or before the observation
   date.
2. Use the EOD close observable after that market close. The contract records
   exchange calendar, market-close timestamp and a conservative availability
   rule/version.
3. Use unadjusted close for contemporaneous market capitalization. Corporate
   actions affect security identity and share comparability; adjusted close is
   separately retained for total-return/near-term calculations.
4. Select only SEC financial facts accepted by that month-end cutoff.
5. Use PIT instant common shares appropriate to market capitalization, not
   diluted weighted-average shares.

EODHD documents that raw OHLC is unadjusted, `adjusted_close` includes splits
and dividends, and volume is split-adjusted. The API response exposes trading
date but not historical publication metadata. Therefore v4 must record the
explicit market-close availability policy and evidence; 2026 ingestion time
cannot be substituted for a historical public timestamp.

`dei:EntityCommonStockSharesOutstanding` can be a candidate instant share fact,
but it is sufficient only when it matches the traded share class/security and
is PIT available. It may be stale between filing dates and cannot replace
diluted weighted-average shares. If strict monthly shares cannot be proven,
historical market cap is missing.

The frozen UQ factor directly blocked by this issue is
`historical_fcf_yield_percentile`. Current UQ is also incomplete until at least
12 valid PIT monthly observations exist. The factor must not be deleted,
down-weighted or neutralized.

Current-only QC may become feasible before historical UQ/backtesting if all QC
financial operands, current EOD availability, classifications and cohorts pass.
Such a result is labeled `CURRENT_ONLY`; it is not historical, backtest, or
forward-validation ready.

## Scoring Input v4 contract

### Snapshot envelope

- `snapshotId`, `snapshotVersion`, `sealed`, `sealedAt`;
- `asOfTime`, `marketCutoffTime`, exchange calendar/version;
- `universeVersion` and universe content hash;
- QC/UQ, factor, derivation, concept-map and normalization versions;
- classification version and per-security classification hash;
- parser versions and source-artifact manifest hash;
- license/redistribution policy;
- canonical snapshot hash.

### Observation

- immutable observation ID and type:
  `INSTANT`, `DURATION`, or `MARKET_OBSERVATION`;
- entity/security IDs, symbol effective range and share class;
- taxonomy, concept, dimensions and statement role;
- Decimal value, unit and currency;
- `periodStart`, `periodEnd`, fiscal year/period, form and frame;
- filed and accepted timestamps, `availableAt`, ingested time and accession;
- market session/date, close timestamp and adjustment mode where applicable;
- revision status, quality status, source reference and content hash;
- parser, mapping and normalization versions.

### Derivation

- derivation ID/version and output observation ID;
- ordered operand observation IDs and hashes;
- formula parameters, Decimal rounding and unit checks;
- derived `availableAt = max(operand availableAt)`;
- explicit validity or missing reason.

### Eligibility

- `CURRENT_ONLY_ELIGIBLE`;
- `HISTORICAL_PIT_ELIGIBLE`;
- `INSUFFICIENT_DATA`;
- `SPECIALIZED_MODEL_REQUIRED`;
- `INVALID`.

Historical eligibility implies current eligibility, but not conversely. A
sealed snapshot is append-only; corrections supersede it with a new snapshot.

## Offline implementation result

For the 223 formula-ready provider entities, the implementation:

1. Hash-verify cached submissions, Company Facts and stored filing evidence.
2. Inventory standard concepts, units, dimensions, start/end, form, frame,
   filed date and accession without requesting data.
3. Join acceptance timestamps from cached submissions by accession.
4. Run each candidate through the versioned mapping; record accepted concept,
   rejected candidates and reason.
5. Measure annual, YTD, discrete-quarter, instant, eight-quarter, three-year
   endpoint and historical-cutoff coverage.
6. Produce per-operand and per-factor current/historical eligibility counts.
7. Write accepted observations and derivations only to Git-ignored,
   content-addressed scoring-input-v4 storage.

The final result built timelines for 216 securities and left seven as
`OFFICIAL_SEC_TIMELINE_NOT_CACHED`. It produced 59,583 deterministic YTD
differences. Exact operand coverage and all controlled-payload hashes are in
`docs/generated/scoring-input-v4-sec-offline-manifest-v2.json`.

The v4.0 `InterestExpenseNonOperating` mapping was later found to be both
narrower than frozen v1 and incorrectly capitalized for the current taxonomy.
The v4.1 offline semantic audit accepts consolidated `InterestExpense`
primitives for 171 cached securities. Debt components remain unsummed on the
SEC reconstruction route, but frozen v1 also permits a documented vendor total
debt. The v4.2 correction accepts EODHD `shortLongTermDebtTotal` and
`Highlights.EBITDA` TTM only for a sealed current snapshot. The offline
adapter found 216 complete supplements and 55 securities satisfying all
primitive QC source contracts. Those 55 are candidates, not algorithm-eligible
ratings: current QC remains zero until current TTM, three-year, aligned
eight-quarter, and required-factor statuses are assembled. Current UQ remains
blocked by its monthly PIT FCF-yield factor, and historical PIT remains blocked
by historical availability and revision lineage.

The seven securities without cached SEC evidence require, at minimum, CIK/share
class resolution plus official submissions and Company Facts or filing Inline
XBRL covering the required current, eight-quarter and three-year windows. This
is a future bounded evidence request, not authorized here.

## Evidence basis

SEC documentation states that Company Facts returns all company concepts,
Company Concept separates facts by unit, standard XBRL facts carry consistent
contexts, and the APIs update as filings are disseminated. SEC submissions
provide filing history and metadata. EODHD documents the distinction between
raw close and split/dividend-adjusted close, but does not document historical
publication timestamps in the EOD response.

Official references:

- <https://www.sec.gov/search-filings/edgar-application-programming-interfaces>
- <https://www.sec.gov/data-research/sec-markets-data/financial-statement-data-sets>
- <https://eodhd.com/financial-apis/api-for-historical-data-and-volumes>
- <https://eodhd.com/financial-apis/stock-etfs-fundamental-data-feeds>
