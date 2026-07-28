# Objective Rating v1 Source Semantics Audit

## Decision

This audit restores the source meanings frozen in
`quantitative-screening-v1-specification.md`. It changes no formula, weight,
required-factor rule, missing-data rule, cohort rule, or PIT rule.

The corrected policy versions are:

- `objective-rating-evidence-policy-v4.2.0`;
- `sec-us-gaap-objective-rating-map-v1.1.0`;
- `sec-interest-expense-policy-v1.1.0`;
- `objective-rating-current-snapshot-policy-v1.0.0`.

Earlier artifacts remain immutable. The v2 audit supersedes their source
eligibility decisions rather than rewriting them.

## Frozen contract versus later evidence restrictions

| Input | Frozen v1 meaning | Correct source decision |
|---|---|---|
| Interest expense | Gross reported interest expense used in `EBIT / abs(interest expense)` | Accept consolidated, unsegmented SEC `InterestExpense`; narrower concepts remain conditional |
| Total debt | Normalized total debt, including a vendor total-debt field where supplied | Accept EODHD `shortLongTermDebtTotal` for a sealed current snapshot |
| EBITDA | Normalized reported/provider EBITDA input | Accept EODHD `Highlights.EBITDA`, officially defined as TTM |
| Current market cap | Positive provider market cap, or price times PIT instant shares | Accept a current provider observation ingested by the cutoff |
| Historical FCF-yield percentile | At least 12 monthly PIT FCF yields using then-available TTM FCF and shares | Remains blocked without the monthly PIT series |

The factor code accepts direct normalized `total_debt`, `ebitda`, and
`market_capitalization` inputs. It does not require SEC reconstruction.

## Interest-expense ruling

`InterestExpense` is the compatible standard concept for total operating and
nonoperating gross interest. The cache contains accepted duration primitives
for 171 securities and 14,828 facts.

`InterestExpenseDebt` and `InterestExpenseNonoperating` remain conditional on
issuer-specific evidence that the concept is the complete denominator.
`InterestAndDebtExpense`, net interest, capitalized interest, segment facts,
and component-only facts remain rejected.

This hierarchy never adds concepts together and never converts missing
interest to zero.

## EODHD current-snapshot route

The official EODHD documentation:

- calls `shortLongTermDebtTotal` total debt;
- explains that its component construction can vary by issuer;
- defines `Highlights.EBITDA` as EBITDA on a TTM basis;
- defines financial-statement `ebitda` as
  `ebit + depreciationAndAmortization`;
- provides `General.UpdatedAt`, `General.CurrencyCode`, financial-statement
  dates, filing dates, and statement currency.

Frozen v1 permits a provider-normalized total-debt value. Issuer composition
variation is therefore a disclosed normalization limitation, not an automatic
rejection. The implementation does not infer component-level comparability.

The accepted EBITDA route is `Highlights.EBITDA`. The financial-statement
quarterly `ebitda` route is not used because its discrete-versus-YTD semantics
remain unspecified. No quarterly TTM series is manufactured.

The later factor-window audit also accepts current
`Valuation.EnterpriseValue` because EODHD documents the same formula frozen in
v1. When this direct denominator is used, minority interest is not defaulted
to zero; the separate component is `NOT_APPLICABLE` because component
reconstruction is not the selected source route. This does not authorize
historical enterprise-value reconstruction.

Each accepted controlled supplement retains:

- symbol, sealed `asOfTime`, provider update date, retrieval time, and
  conservative ingestion-by-cutoff evidence;
- provider field path, Decimal string, unit, currency, period type, and
  effective time;
- balance-sheet period end and filing date for total debt;
- raw response content hash, policy version, and controlled payload hash;
- explicit current-only and revision-history limitations.

Exact licensed values remain in Git-ignored, content-addressed storage.

## Purpose separation

### Current snapshot rating

A sealed current snapshot may use the accepted provider total debt, TTM
EBITDA, and market cap if the completed response was present by the cutoff.
It makes no claim about when a historical value was originally published.

### Forward Decision-Quality Validation

A future observation may enroll a valid sealed current rating. That does not
create historical backtest evidence. Forward Validation remains outside this
task and was not started.

### Historical reconstruction

An old-cutoff rating still requires the data, revision, identifier, universe,
price, shares, and corporate actions known at that old cutoff. Current
ingestion and `General.UpdatedAt` cannot prove historical availability.

## Offline coverage and eligibility

The hash-verified current-snapshot adapter found:

- 223 provider-formula-ready target securities;
- 216 complete cached EODHD fundamentals responses with
  `Highlights.EBITDA`, `Highlights.MarketCapitalization`,
  `shortLongTermDebtTotal`, update metadata, and currency;
- seven securities without a cached EODHD fundamentals response:
  A, AAPL, ACN, ADBE, ADI, CAT, and JNJ;
- 171 securities with accepted SEC `InterestExpense` primitives;
- 55 securities satisfying the complete primitive source-contract
  intersection required by QC.

The 55 count is not a score-eligibility count. Current QC algorithm eligibility
remains zero until a separate offline assembler verifies the exact current
TTM, three-year, and aligned eight-quarter windows and evaluates every required
factor status. No factor value, score, cohort, or rank was computed.

Current UQ remains zero because
`historical_fcf_yield_percentile` still lacks its required monthly PIT
observations. Historical reconstruction remains zero because historical
availability and revision lineage are unproven.

Machine-readable evidence:

- `docs/generated/eodhd-fundamentals-documentation-semantic-audit-v2.json`;
- `docs/generated/objective-rating-v1-current-snapshot-supplements-v1.json`;
- `docs/generated/objective-rating-v1-source-semantics-audit-v2.json`.

## Next offline step

Do not request more SEC filings or repeat existing EODHD endpoints for this
decision. The next permitted implementation is an offline factor-window
assembler that:

1. selects only evidence available by the sealed current cutoff;
2. constructs the frozen current TTM, three-year, and aligned eight-quarter
   windows;
3. returns `VALID`, `MISSING`, `INVALID`, or `NOT_APPLICABLE` per factor;
4. leaves any required missing factor as `INSUFFICIENT_DATA`;
5. does not score, normalize, or rank until the complete input contract passes.

## Official references

- [EODHD Fundamentals glossary](https://eodhd.com/financial-academy/financial-faq/fundamentals-glossary-common-stock)
- [EODHD debt fields explained](https://eodhd.com/financial-academy/financial-faq/debt-fields-explained)
- [EODHD Fundamentals API documentation](https://eodhd.com/financial-apis/stock-etfs-fundamental-data-feeds)
- [SEC operating-company taxonomies](https://www.sec.gov/data-research/structured-data/taxonomies-schemas/standard-taxonomies/operating-companies)
