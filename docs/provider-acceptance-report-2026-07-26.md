# Provider Acceptance Report: 2026-07-26

## Scope

This derived report covers the complete 20-security acceptance universe. The
read-only checks were executed in paced batches because the existing Twelve
Data plan permits eight API credits per minute. The price window was
2020-01-01 through 2026-07-26.

No raw provider response, API key, private contact information, or licensed
bulk dataset is stored.

## Result

| Result | Count |
| --- | ---: |
| Securities | 20 |
| `PASS` checks | 47 |
| `FAIL` checks | 0 |
| `NOT_VERIFIED` checks | 56 |
| `NOT_APPLICABLE` checks | 4 |
| Production backtest status | `NOT_VERIFIED` |

`FAIL` remains zero because an unavailable entitlement, missing historical
identifier endpoint, unconfigured SEC identity, or unsupported delisted ticker
is an unverified capability rather than proof that an observed financial value
is wrong.

## Daily Price Evidence

| Coverage | Securities | Result |
| --- | --- | --- |
| 1,648 observations, 2020-01-02 through 2026-07-24 | AAPL, MSFT, META, WMT, MCD, CAT, ADP, NKE, TGT, PLAB, GE, JPM, PGR, O, XOM, MRNA, SPY, XLK | `PASS` |
| 1,255 observations, 2021-07-26 through 2026-07-24 | LCID | `PASS`; shorter public history is expected |
| Current ticker rejected | TWTR | `NOT_VERIFIED`; a delisted-symbol dataset is required |

Twelve Data identified `O` as `REIT`, `SPY` and `XLK` as `ETF`, and the
remaining current equities as `COMMON_STOCK`. Provider instrument type is
evidence but does not replace the versioned company-type gate.

## Corporate Actions and Identity Evidence

| Check | Result |
| --- | --- |
| AAPL split history | `PASS`; five events from 1987-06-16 through 2020-08-31 |
| AAPL dividend history | `PASS`; 82 events from 1988-11-21 through 2026-05-11 |
| WMT and TGT dividend history | `NOT_VERIFIED`; endpoint is outside the current plan |
| GE split history | `NOT_VERIFIED`; endpoint is outside the current plan |
| META `FB` to `META` dated identifier event | `NOT_VERIFIED`; tested contract exposes no dated event |
| TWTR delisting proceeds and final return | `NOT_VERIFIED` |

The separate SEC feasibility check already connected Apple's 2026-05-01 10-Q
acceptance timestamp and accession `0000320193-26-000013` to XBRL facts.
Recurring automated SEC access is intentionally not attempted unless
`SEC_USER_AGENT` is explicitly set to an application name plus a real contact
address. Repository Git identity is never read or transmitted automatically.

## SEC EDGAR Acceptance

The configured read-only SEC run completed for all 20 acceptance securities.
The contact identity remained local and was not written to this report or any
test fixture.

| SEC result | Count |
| --- | ---: |
| `PASS` | 40 |
| `NOT_VERIFIED` | 7 |
| `NOT_APPLICABLE` | 6 |
| `FAIL` | 0 |

All ten mature operating-company cases resolved to a durable CIK and linked a
latest 10-K or 10-Q acceptance timestamp and accession to XBRL facts. Eight
passed every required tag group. ADP and NKE require an issuer-specific or
derived mapping for operating income; ADP's capital expenditure maps to
`PaymentsToAcquireOtherPropertyPlantAndEquipment`.

The current-period operating-income derivations are now validated with two
independent same-accession paths:

| Issuer and period | Operating-cost path | Pretax cross-check | Derived result |
| --- | --- | --- | ---: |
| ADP, 2026 Q3 single quarter | Revenue - cost of services - SG&A | Pretax + interest expense - other income | USD 1,785.5M |
| NKE, FY2026 | Revenue - cost of goods - SG&A | Pretax - net interest income - other income | USD 3,797M |

The implementation is restricted to the reviewed ADP and NKE CIKs. Every
component must have the same accession, period and unit, and the two paths must
produce exactly the same Decimal result. A frozen derived fixture retains only
the public facts required to reproduce the calculation; it does not retain the
raw SEC response or local contact identity.

A full companyfacts replay found 59 same-period ADP observations and 63
same-period NKE observations for which all required components coexist. Both
derivation paths agreed in all 122 cases. The frozen regression set includes
the current observations plus two annual periods for each issuer; production
ingestion must still apply the filing-availability cutoff rather than treating
the current companyfacts response as historically available.

The remaining field gaps belong to company types already excluded from the
general-company model: JPM and PGR are financial companies, O is a REIT, XOM
is a resource company, and TWTR is a delisted special situation. They do not
block the v1 mature-company scorer.

Ticker-only SEC lookup initially resolved XOM to an unrelated newer CIK. The
acceptance fixture now pins Exxon Mobil to CIK `0000034088`, and the replay
linked its 2026-05-04 10-Q accession `0000034088-26-000067`. This confirms that
ticker is not a safe durable identity key. ETF benchmark XLK correctly returns
SEC issuer identity and operating-company fundamentals as `NOT_APPLICABLE`.

## Historical Filing PIT Evidence

The SEC adapter now selects only 10-K, 10-Q and amendment filings whose
acceptance timestamp is at or before the requested timezone-aware
`asOfTime`. When the current submissions index does not reach the cutoff, it
loads the applicable SEC supplemental submissions file.

A frozen, derived six-case fixture covers AAPL, MSFT and META from 2021 through
2024. Each row stores CIK, cutoff, form, filing date, acceptance timestamp,
accession, report date and a canonical SHA-256 hash. META demonstrates that:

- the 2022-06-15 cutoff selects accession `0001326801-22-000057`; and
- the 2022-08-01 cutoff selects the later accession
  `0001326801-22-000082`.

Tests also prove that a 10-Q amendment cannot replace the original filing
before the amendment's acceptance timestamp. SEC facts are delayed until a
complete trading session is available and later-accession facts cannot alter
an earlier cutoff.

## Initial Historical Fundamental Observation

An AAPL fixture as of 2024-06-30 validates five real SEC duration metrics:
revenue, operating income, net income, operating cash flow and capital
expenditure. TTM uses the versioned YTD bridge rather than summing cumulative
10-Q values:

`TTM = fiscal 2023 annual + fiscal 2024 Q2 YTD - fiscal 2023 Q2 YTD`

| Metric | TTM value (USD) |
| --- | ---: |
| Revenue | 381,623,000,000 |
| Operating income | 118,240,000,000 |
| Net income | 100,389,000,000 |
| Operating cash flow | 110,563,000,000 |
| Capital expenditure | 8,644,000,000 |
| Derived free cash flow | 101,919,000,000 |

This produces an FCF margin of `0.26706724` and cash conversion of
`1.01524071`. These are deterministic calculation checks, not an investment
conclusion or a complete QC/UQ rating.

The same cutoff now includes PIT balance-sheet values and the 2024-06-28
adjusted close. The following additional raw factor values are reproducible:

| Factor | Raw value |
| --- | ---: |
| ROIC | `0.69507759` |
| Operating margin | `0.30983457` |
| Net debt / EBITDA | `0.53926976` |
| Earnings yield | `0.03613722` |
| FCF yield | `0.03182912` |
| Three-year EPS growth | `0.13102646` |
| Three-year FCF/share growth | `0.07403515` |
| Three-year dilution | `-0.03121614` |
| Margin quality | `0.21484168` |
| Stability | `0.11283395` |
| Historical FCF-yield percentile | `0.00000000` |

ROIC uses stockholders' equity plus total debt minus cash at 2024-03-30 and
2023-04-01. Market capitalization uses 15,337,686,000 reported common shares
and the Twelve Data adjusted close of `208.77123` on 2024-06-28.

Weighted TTM diluted shares are reconstructed using inclusive period-day
weights. The 2021-03-27 baseline is 17,179,630,000 shares and the 2024-03-30
value is 15,620,484,096.15384615 shares.

The stability input contains 12 derived discrete fiscal quarters from
2021-06-26 through 2024-03-30. Cumulative cash-flow values are differenced
within a fiscal year, and Q4 uses annual minus Q3 YTD. The operating-margin
coefficient of variation is `0.06375535`; the FCF-margin coefficient is
`0.16191254`.

No QC/UQ score is emitted. Interest coverage lacks a compatible TTM interest
expense observation, while the valuation guardrail requires an eligible
comparison cohort. Under v1 missing-factor rules, both strategies remain
`INSUFFICIENT_DATA`.

The historical percentile uses 12 monthly observations from July 2023 through
June 2024. Each row combines the last adjusted close, the latest PIT TTM FCF,
reported shares and the governing SEC accession. The target is 60 months, so
the current result passes the v1 minimum but records 12/60 coverage.

Apple's official 2024 Q2 inline XBRL contains no interest-expense fact or
issuer-specific interest-expense tag. Annual 2023 interest expense must not be
silently carried forward as a 2024 TTM value. Interest coverage therefore
remains explicitly missing and becomes a paid-provider acceptance field.

## Cross-Issuer Portability

The same versioned TTM bridge was applied at 2024-06-30 to MSFT and TGT.

| Issuer | Verified TTM fields | Explicit gap |
| --- | --- | --- |
| MSFT | Revenue, gross profit, operating income, net income, CFO, capex and interest expense | None in the bounded bridge |
| TGT | Revenue, operating income, net income, CFO, capex and interest expense | No compatible standard gross-profit fact |

MSFT produced TTM operating income of USD 105.762 billion, FCF of USD 70.576
billion and interest expense of USD 2.716 billion. TGT produced TTM operating
income of USD 5.675 billion, FCF of USD 4.582 billion and interest expense of
USD 461 million. These values prove formula portability, not ranking
eligibility. TGT margin quality remains missing rather than being inferred from
an unapproved cost-of-sales mapping.

## Final Acceptance Decision

Objective Rating v1 method and contract validation is **accepted**. Free-source
production data acceptance is **not accepted**.

The replaceable provider implementation subsequently added offline-tested
yfinance and EODHD adapters. These tests establish normalization, failure
handling, retry, and secret-redaction behavior only. No live EODHD request was
made, so EODHD production acceptance remains `NOT_VERIFIED` and the result
counts in this report are unchanged.

Implementation may proceed only for provider-neutral immutable observations,
pure factors/scoring, bounded adapters and contract fixtures. Full-market
backfill, production ranking and backtesting remain blocked on a separately
authorized vendor trial for dated identity history, delisting returns,
revisions, general corporate actions and issuer-specific statement fields.

## Decision

The existing Twelve Data plan is sufficient for adjusted daily-price
validation of current securities and AAPL action examples. The 20-security run
also demonstrated that client-side pacing is required: the acceptance CLI now
defaults to an eight-second minimum request interval. It is not sufficient to
establish symbol-change history, delisting returns, or general
corporate-action coverage.

Do not purchase a service yet. The next useful validation is:

1. Configure a deliberate SEC contact identity locally and rerun the 20
   securities. **Completed.**
2. Build historical filing selection and frozen PIT fixtures; do not infer
   historical availability from the latest company-facts response.
   **Initial six-case filing fixture completed.**
3. Connect the reviewed ADP and NKE derivations to PIT filing selection and
   normalized `fundamental_fact` persistence.
4. Evaluate a bounded paid trial only for the remaining identifier, delisting,
   revision, and corporate-action gaps.

The first part of item 2 is now implemented as a deterministic SEC fact
selector and frozen restatement fixture. A fact becomes eligible only after
one complete United States trading session following SEC acceptance. The
selector applies an explicit as-of cutoff, preserves accession and period
metadata, and proves that a later amendment cannot change an earlier result.
The production gate remains `NOT_VERIFIED` until real multi-period issuer
fixtures and the remaining provider checks pass.

## Expanded 66-Security Price Validation

A second stratified development universe was validated on 2026-07-27 with the
existing Twelve Data entitlement and the same eight-second request interval.
It contains 66 unique symbols spanning general companies, capitalization
bands, specialized-model exclusions, benchmarks, ticker changes, and a
delisted case.

| Adjusted daily price result | Count |
| --- | ---: |
| `PASS` | 65 |
| `NOT_VERIFIED` | 1 |
| `FAIL` | 0 |

`TWTR` is the only `NOT_VERIFIED` price case because the current contract does
not provide delisted-symbol history. All other symbols returned adjusted daily
history for their available listing periods.

For `NBN`, Twelve Data returned 1,648 observations from 2020-01-02 through
2026-07-24. SEC ticker lookup did not resolve the issuer, so the fixture pins
Northeast Bancorp to CIK `0000811831` from the official filing archive. Filing
lineage then passed, while general-company revenue and operating-income tag
groups remained unavailable. As a financial company, `NBN` remains
`SPECIALIZED_MODEL_REQUIRED`.

This validates broader development-price access. It does not establish
PostgreSQL persistence, delisting returns, full PIT fundamentals, or
production provider acceptance.

## EODHD All-in-One Live Acceptance: 2026-07-26

The configured All-in-One entitlement was tested through the provider-neutral
20-security harness with SEC EDGAR and yfinance cross-checks. The API key
remained local and was not printed, persisted, or included in a source
reference. No raw licensed response was retained.

The corrected run produced 116 `PASS`, zero `FAIL`, 210 `NOT_VERIFIED`, and six
`NOT_APPLICABLE` checks. Production backtest status remains `NOT_VERIFIED`.

EODHD daily-price coverage passed for all 20 securities:

- Eighteen established current securities and both benchmarks returned 1,648
  observations from 2020-01-02 through 2026-07-24.
- LCID returned 1,468 observations from 2020-09-18 through 2026-07-24.
- Delisted TWTR returned 712 observations from 2020-01-02 through 2022-10-27.
- Every EODHD price series had zero rejected normalized observations.
- The three requested dividend checks and two requested split checks passed.

yfinance returned normalized price history for all 19 current securities and
did not resolve TWTR. The adapter explicitly rejected one incomplete Yahoo row
where required values were missing instead of converting the values to zero.

This run validates bounded EODHD EOD price access, current metadata used by the
adapter, sampled dividends, sampled splits, and delisted-symbol price
availability. It does not yet accept:

- Adjusted versus unadjusted economic equivalence across providers.
- TWTR delisting proceeds or final return.
- Dated FB-to-META identifier history.
- Quarterly and annual EODHD fundamental normalization.
- Historical shares or market capitalization.
- Historical `effectiveAt` and `availableAt` semantics or revisions.
- Live missing-data behavior across all required domains.
- Documented entitlement limits and reproducible rerun hashes.

EODHD therefore moves from `DOCUMENTED_CANDIDATE` to `VALIDATED_LIMITED` for
the bounded price/action slice only. It is not accepted as the production
Objective Rating v1 dataset, and no full-market ranking or formal forward
validation is authorized by this result.

## 100-Security Aggregate Provider Gate

The mature-company provider gate is accepted through an offline, hash-verified
merge of immutable live reports. This is a cross-run aggregate acceptance, not
a claim that one 120-security execution produced 100 passing companies.

The merge applies these evidence rules:

- each security is counted once;
- the original 120-security report supplies the baseline result;
- a later result may replace the baseline only when it is an immutable live
  report with a verified SHA-256 hash and the unchanged acceptance criteria;
- offline derived evidence may explain or reclassify diagnostics, but it cannot
  upgrade a security to `PASS`;
- missing source identity, report hash, or immutable live-evidence metadata
  invalidates an attempted override.

The aggregate ledger contains 120 unique evaluated securities. Exactly 100
have live-confirmed `PASS` evidence and 20 remain unresolved as `PARTIAL` or
`FAIL`. No unresolved or offline-only result is included in the passing count.
The aggregate provider-gate status is therefore `PASS`.

This result establishes the bounded 100-security mature-company data gate only.
It does not accept EODHD as an unrestricted production dataset, authorize
Objective Rating execution, authorize the 300-500 security gate, or reconcile
endpoint-level provider billing. Run-level billing is
`PROVISIONALLY_RECONCILED`; endpoint-level billing remains `NOT_RECONCILED`.
