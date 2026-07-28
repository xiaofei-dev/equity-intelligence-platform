# Decision Log

This file records product and architecture decisions. New entries should be appended rather than rewriting historical decisions.

## 2026-07-25: Product Positioning

Decision:

Position the product as an equity intelligence and decision-support platform, not an automatic stock-picking or guaranteed-return system.

Reason:

The product's differentiator is the combination of quantitative consistency, source-backed AI research, explicit portfolio discipline, and reproducible evaluation.

## 2026-07-25: Human-Controlled MVP

Decision:

Do not connect to brokerage execution in the MVP.

Reason:

The strategy must first be evaluated through historical testing, paper trading, and human review. Automatic execution adds security, operational, and compliance risk without validating the core research workflow.

## 2026-07-25: Hybrid Technology Stack

Decision:

Use Next.js and TypeScript for the frontend, Java 21 and Spring Boot for the main backend, Python and FastAPI for analytics, and PostgreSQL for persistence.

Reason:

Spring Boot demonstrates enterprise backend practices and owns business workflows. Python provides the strongest ecosystem for quantitative analysis, data processing, backtesting, and AI integration.

## 2026-07-25: Initial Service Boundaries

Decision:

The frontend calls Spring Boot, and Spring Boot calls FastAPI through a versioned internal API.

Reason:

This keeps the public API and business system centralized while isolating Python analytics concerns.

## 2026-07-25: Deferred Kafka and Kubernetes

Decision:

Use HTTP and Docker Compose initially. Do not introduce Kafka or Kubernetes in the MVP.

Reason:

The initial system does not yet require durable multi-consumer event streaming or multi-node container orchestration. The architecture will preserve clear contracts and portable containers so these technologies can be introduced when justified.

## 2026-07-25: Deployment Path

Decision:

Use Render for the initial public deployment and plan a later learning-oriented migration to Amazon ECS Fargate and Amazon RDS.

Reason:

Render supports rapid delivery of the multi-service MVP. AWS provides a credible later path for deeper cloud, security, networking, and operations experience.

## 2026-07-25: Repository Language

Decision:

All repository artifacts must be written in English. Chinese may be used in conversation with the user.

Reason:

English repository content improves professional presentation, consistency, and collaboration.

## 2026-07-25: Initial Market and Data Provider

Decision:

Use United States listed equities, daily data, and Twelve Data for the first
end-to-end vertical slice. Isolate provider-specific behavior behind an
analytics-service interface.

Reason:

United States equities provide a deep, well-documented initial market and align
with the project's daily research scope. Twelve Data provides daily OHLCV,
reference metadata, split adjustment controls, and a development quota suitable
for the small initial universe. Its individual plans do not grant public or
commercial redistribution rights, so a business license review is mandatory
before public deployment. The provider boundary preserves the option to migrate
if licensing, coverage, cost, or data quality requirements change.

## 2026-07-25: United States Security Ingestion Identity

Decision:

Use the normalized ticker symbol as the unique ingestion identity within the
single-market MVP. Treat exchange labels as mutable provider metadata.

Reason:

Provider exchange labels can differ from seeded reference labels and can change
after a listing transfer. Using `(symbol, exchange)` created duplicate security
records for the same United States ticker. The single-market scope makes symbol
identity sufficient for the MVP; a future multi-market expansion must introduce
a durable global identifier before relaxing this constraint.

## 2026-07-26: Two-Stage Research Funnel

Decision:

Run deterministic broad-universe screening before AI evidence review. Keep
quantitative-only and evidence-reviewed candidate states distinct.

Reason:

Broad screening must be reproducible, testable, and affordable across thousands
of securities. AI is better used to inspect source documents, identify
contradictions, and explain a prioritized set of candidates and current
holdings.

## 2026-07-26: Initial Long-Term Strategy Paths

Decision:

Implement `Quality Compounder` and `Undervalued Quality` as the first
quantitative strategy paths. Do not create one universal score for every
company type.

Reason:

Mature companies, early-stage growth companies, banks, insurers, REITs,
resource companies, biotechnology, and special situations require materially
different inputs and risk rules. The first two paths align with the initial
Graham-inspired long-term investment discipline and can be defined with
general-company financial statements.

## 2026-07-26: Separate Intent, Horizon, and Portfolio Fit

Decision:

Keep investment approach, expected horizon, asset assessment, and user
portfolio fit as separate concepts. Distinguish defensive investing,
enterprising investing, and explicitly limited speculation. Do not implement a
generic medium-term score until a distinct methodology is justified.

Reason:

Holding period alone does not determine whether a position is an investment or
speculation. A stock can be attractive as a company yet unsuitable at its
current price or for a user's existing concentration and risk limits.

## 2026-07-26: Portfolio Scenario Model

Decision:

Analyze the user's complete portfolio while separately comparing
new-money-only allocation, constrained rebalancing, and a target-portfolio
simulation.

Reason:

New cash cannot be allocated responsibly without considering existing
positions, cash, liabilities, leverage, and concentration. The user controls
which existing positions may change, and no scenario authorizes automatic
execution.

## 2026-07-26: Data Provider Validation Before Commitment

Decision:

Retain Twelve Data for the current engineering slice, use SEC EDGAR as the
preferred primary-source filing and XBRL evidence provider, and evaluate EODHD
as the leading paid personal-research candidate through a 20-security
acceptance exercise before a recurring commitment.

Reason:

The production methodology requires adjusted and unadjusted prices, corporate
actions, listing and delisting history, historical shares, point-in-time
fundamentals, classifications, and licensing clarity. Marketing coverage alone
does not prove that a provider supports unbiased historical evaluation.

## 2026-07-26: General-Company Quantitative Screening v1 Data Gate

Decision:

Define `QC-v1.0.0` and `UQ-v1.0.0` only for mature, liquid United States
non-financial operating companies, with versioned point-in-time eligibility,
cohorts, formulas, exclusions, and a 20-security provider acceptance exercise.
Use SEC EDGAR as the primary filing/XBRL validator; retain Twelve Data for the
existing development price slice; validate EODHD with a paid one-month extract
before approving it for a historical backtest.

Reason:

The current price-only slice cannot prove fundamental availability, revisions,
delisted history, or point-in-time correctness. A reproducible data and
methodology gate is required before building ranking, AI, user, or portfolio
features. Banks, insurers, REITs, resource companies, biotechnology,
early-stage growth, and special situations remain outside the general-company
model.

## 2026-07-26: Separate Horizon Assessments

Decision:

Return a long-term company/valuation assessment and an independent near-term
market-condition assessment. Return `NOT_DEFINED` with no score for medium term
until a distinct, testable methodology is approved. Do not combine horizon
scores.

Reason:

Price behavior over one to three months answers a different question from
long-term business quality and valuation. A generic medium-term score would add
an unsupported conclusion and increase overfitting risk.

## 2026-07-26: Required Factors Do Not Reweight

Decision:

Give every factor an explicit validity state. If a strategy-required factor is
not valid, return `INSUFFICIENT_DATA` with no strategy score. Do not convert the
missing value to zero and do not redistribute its weight.

Reason:

Zero implies an observed poor result, while reweighting silently changes the
strategy formula. Explicit failure preserves comparability, explainability and
version reproducibility.

## 2026-07-26: Screening Task and Wire Contract

Decision:

Define screening as an idempotent asynchronous Python-owned task using a data
snapshot, universe version and strategy versions. Java consumes immutable
ratings through a versioned contract and never duplicates factor calculations.
Use a shared JSON fixture to verify Python and Java compatibility.

Reason:

Full-universe screening is a long-running analytics responsibility. Stable
task identity and immutable inputs support retries and auditability, while one
calculation owner prevents language implementations from drifting.

## 2026-07-26: Paid Providers Remain Documented Candidates

Decision:

Classify EODHD, Financial Modeling Prep and Massive / Polygon as
`DOCUMENTED_CANDIDATE` until a bounded 20-security trial verifies field
coverage, point-in-time behavior, delisting, revisions, costs and licensing.
Do not purchase a service as part of Objective Rating v1 validation.

Reason:

Published endpoint coverage does not prove historical availability semantics or
commercial suitability. The existing Twelve Data entitlement and SEC EDGAR are
sufficient for the limited calculation and lineage validation performed in
this slice.

## 2026-07-26: Read-Only Provider Acceptance Harness

Decision:

Validate providers through a read-only Python CLI that emits explicit
`PASS`, `FAIL`, `NOT_VERIFIED`, and `NOT_APPLICABLE` checks for the versioned
20-security fixture. Persist only reviewed derived evidence, never credentials
or raw licensed responses. Require `SEC_USER_AGENT` to be configured explicitly
and never infer it from Git identity.

Reason:

Provider documentation and isolated successful calls are insufficient for a
repeatable data gate. Explicit states prevent an entitlement or identity
configuration gap from becoming a false data failure, while deliberate contact
configuration avoids disclosing local account metadata without authorization.

## 2026-07-26: Point-in-Time Analytics Persistence

Decision:

Store provider lineage, security history, market and fundamental observations,
data snapshots, factor results, coverage, and strategy ratings in
`analytics.*` as append-only, versioned records. A sealed snapshot applies
both an information-availability cutoff and an ingestion cutoff. Python owns
analytics writes; Java consumes ratings only through the versioned internal
HTTP contract.

Reason:

Economic dates alone cannot prevent restatement, late-ingestion, current-ticker,
or current-universe leakage. Immutable source revisions and exact strategy,
universe, normalization, and source versions make calculations reproducible.
Keeping rating formulas and persistence Python-owned also prevents a second
Java scoring implementation from drifting.

## 2026-07-26: Historical Filing Availability and Durable Identity

Decision:

Select SEC filings by timezone-aware acceptance timestamp, not report period or
filing date alone. Load SEC supplemental submission indexes for older cutoffs,
apply amendments only after their own acceptance time, and delay facts until a
complete trading session is available. Use an internal immutable security
identifier with dated ticker mappings; never use ticker as the durable key.

Reason:

A period-end date predates public availability, a later amendment must not
rewrite an earlier snapshot, and the current submissions index does not contain
all older filings. The XOM acceptance test also demonstrated that ticker-only
lookup can resolve to an unrelated CIK.

## 2026-07-26: Versioned YTD-to-TTM Bridge

Decision:

For cumulative duration metrics, derive TTM as prior annual plus current YTD
minus prior-year comparable YTD under `TTM-YTD-BRIDGE-v1.0.0`. Require matching
metric and unit, comparable durations, valid chronology, PIT availability and
preserved accession lineage. Do not blindly sum four 10-Q observations.

Reason:

SEC 10-Q company facts frequently contain cumulative year-to-date values.
Summing them double-counts earlier quarters, while the explicit bridge produces
a reproducible TTM value and makes restated comparative inputs auditable.

## 2026-07-26: PIT Market Value Reconstruction

Decision:

For the validation slice, reconstruct market capitalization from the latest
PIT-eligible reported common shares and the last available adjusted daily close
at or before the cutoff. Preserve both lineages and report the share-period
staleness. Do not emit a strategy score when any required history or factor is
missing.

Reason:

A provider's current market-cap field can leak future shares into a historical
cutoff. Explicit price-times-shares reconstruction is auditable, while keeping
incomplete QC/UQ results unscored prevents partial data from appearing as a
valid ranking.

## 2026-07-26: Weighted-Average TTM Shares

Decision:

Reconstruct TTM diluted weighted-average shares with inclusive period-day
weights under `TTM-WEIGHTED-YTD-BRIDGE-v1.0.0`. Use the result for per-share
metrics and dilution; do not apply the additive monetary-value bridge directly
to weighted averages.

Reason:

Weighted-average shares represent exposure over a duration, not an additive
flow. Period weighting preserves the economic meaning when annual and
cumulative YTD observations are bridged.

## 2026-07-26: Discrete Quarters and Margin Stability

Decision:

Derive discrete quarters from cumulative SEC duration facts under
`DISCRETE-FROM-CUMULATIVE-v1.0.0`. Subtract adjacent YTD observations sharing a
fiscal-year start and derive Q4 as annual minus Q3 YTD. Define stability as the
mean population coefficient of variation of aligned operating and FCF margins.
Define margin quality as the mean of current gross margin, current operating
margin, and their respective three-year changes.

Reason:

Cash-flow 10-Q facts are usually cumulative and cannot be treated as standalone
quarters. Explicit differencing prevents double counting, while fixed composite
formulas remove ambiguity from the single versioned factor values.

## 2026-07-26: Historical FCF-Yield Percentile

Decision:

Calculate a security's historical FCF-yield percentile from PIT month-end
observations using an ascending midrank. Target 60 months and require at least
12. Reconstruct each market cap from that month's adjusted close and the latest
reported shares available at the cutoff; pair it with only the TTM FCF then
available.

Reason:

Using today's shares or latest TTM FCF across old prices creates look-ahead
bias. A fixed midrank and explicit 12/60 coverage make the preliminary
historical valuation signal deterministic without overstating its depth.

## 2026-07-26: PostgreSQL-Backed Screening Pipeline

Decision:

Use PostgreSQL screening runs as the durable task queue for the first vertical
slice. FastAPI creates idempotent runs, recovers pending or stale-running work,
acquires advisory locks, builds observations from sealed snapshots, and writes
coverage, factor, strategy, contribution, horizon, and lineage results before
sealing the run. Spring Boot forwards only the versioned HTTP task and rating
contract.

Twenty-security acceptance is layered. Every security must appear in snapshot
membership and coverage, while only mature operating companies with sufficient
v1 data receive numeric ratings. Specialized companies, benchmarks, historical
securities, and incomplete records retain explicit non-scored states.

Reason:

This preserves one owner for deterministic formulas and analytics persistence,
supports safe request retries and process restarts without introducing an
external queue, and prevents incomplete provider coverage from being presented
as a neutral or fabricated score.

## 2026-07-26: Objective Rating v1 Validation Closure

Decision:

Accept the deterministic Objective Rating v1 method, data contracts, PIT
selection rules and bounded validation fixtures. Do not accept the free-source
combination as a production full-market backtest dataset. Limit the next
implementation slice to provider-neutral observations, pure calculations,
bounded adapters and shared contracts until a separately authorized vendor
trial closes the named data gaps.

Reason:

AAPL, MSFT and TGT prove that the formulas and core SEC bridge are executable,
while AAPL interest expense and TGT gross profit prove that issuer-specific
coverage cannot be assumed. Ticker history, delisting proceeds and revision
semantics also remain insufficient for survivorship-safe production research.

## 2026-07-26: Immutable Forward Decision-Quality Validation

Decision:

Evaluate objective ratings and paced entry rules through parallel, immutable
shadow ledgers under `FORWARD-VALIDATION-v1.0.0`. Keep the near-term score a
market condition rather than a recommendation. Only `FAVORABLE` permits the
next fixed 25% state-gated tranche. Preserve paused, unfilled, expired, cash,
cost, and missed-upside outcomes. Default to `DRY_RUN` until a 300-to-500
security stratified PIT provider acceptance is recorded.

Reason:

Retrospective selection of successful waits would create outcome bias.
Freezing each signal and all counterfactual arms before outcomes exist makes
purchase-price, return, drawdown, and opportunity-cost comparisons auditable.
One to two months can validate operations and provide preliminary direction,
but cannot establish persistent excess return.

## 2026-07-26: User and Portfolio System of Record

Decision:

Separate application users from authentication identities and resolve the
initial closed-test identities to stable internal user identifiers. Model
accounts, cash, positions, liabilities, aggregate portfolios, constraint
policies, portfolio scenarios, and human decisions in `app.*`. Represent
account history with immutable point-in-time snapshots. Use explicit account
sets for aggregate portfolios and compare new-money-only, constrained
rebalancing, and target-portfolio scenarios against the same complete context.

User, portfolio, and account constraints form a tightening hierarchy. Scenario
inputs, completed results, and human decisions preserve their resolved
versions. Java owns and authorizes all user state. Python receives only a
versioned calculation contract and cannot write `app.*`.

Reason:

Two closed-test identities still require real ownership boundaries if the
model is to evolve safely toward multiple users. Immutable inputs and decisions
make later evaluation reproducible, while explicit scenario permissions keep
portfolio analysis separate from trade authority. The schema boundary prevents
reusable analytics from becoming an accidental store of private account data.

## 2026-07-26: Replaceable Market Data Provider Boundary

Decision:

Normalize Twelve Data, yfinance, and EODHD behind provider-neutral price,
corporate-action, security-metadata, and lineage contracts. Select ingestion
through `MARKET_DATA_PROVIDER`, use normalized adjustment modes for new
records, preserve legacy modes through a read mapping, and seal one market
provider and adjustment mode into every data snapshot.

yfinance is development and fallback data only. EODHD remains a documented
candidate until the live 20-security acceptance gate proves entitlement,
point-in-time behavior, identifier continuity, delisted coverage, historical
market values, rate limits, and licensing. SEC EDGAR remains the filing and
revision-lineage authority.

Reason:

Provider-native fields, defaults, and availability claims must not change
Objective Rating v1. A normalized boundary and sealed source selection prevent
mixed-provider observations from changing deterministic calculations. Missing
market capitalization remains missing and forces insufficient coverage rather
than becoming zero or a neutral score.

## 2026-07-26: Bound the Mature-Company Data Gate

Decision:

Use a named universe of 100 primary mature non-financial U.S. issuers and 20
sector-matched reserves across eight sectors. EODHD supplies normalized
structured data, while SEC EDGAR remains authoritative for filing acceptance,
amendments, and point-in-time availability.

Limit the run to 3,500 weighted EODHD calls and 1,122 HTTP attempts. Do not use
bulk-US or exchange-wide endpoints.

A company is scoreable only when every required gate domain passes. Partial
data is not converted to zero, a neutral score, or relaxed eligibility.
Objective Rating v1 formulas, factor inputs, cohort thresholds, and public
contracts remain frozen.

Reason:

A bounded, stratified gate measures provider fitness without turning an
acceptance exercise into uncontrolled full-market ingestion.

## 2026-07-27: Make Live Provider Gates Single-Run and Immutable

Decision:

Require a cross-process lock, a unique run ID, exclusive report creation, a
maximum-symbol option, a no-network preflight, and an explicit live
confirmation phrase for every mature-company live gate.

Treat the lock as preventive protection. Two visible Windows `python.exe`
processes are not evidence by themselves that two independent gate commands
were running because a virtual-environment launcher and child interpreter can
both be visible.

The surviving local report records 1,680 weighted EODHD calls, while the EODHD
dashboard reached approximately 12,000 calls during the day. This discrepancy
is unresolved. Local endpoint weights, interrupted commands, retries, earlier
commands, and overwritten reports remain possible contributors and must not be
presented as confirmed causes.

Reason:

Provider usage needs immutable per-run evidence and enforceable concurrency
control before another live acceptance attempt. Local projections are not a
substitute for provider billing evidence.

## 2026-07-27: Bound Reproducibility Network Reruns

Decision:

Run a second provider download for no more than five securities in a mature
gate. For every other security, replay the already-normalized immutable payload
through persistence to verify idempotency without a second EODHD request.

Record physical HTTP attempts, configured local endpoint weights, and observed
provider-dashboard deltas as separate measures. Keep provider billing status
`NOT_RECONCILED` until endpoint-level evidence explains the difference.

Use 25 observed provider calls as the provisional one-pass planning cost and 50
as the provisional complete two-pass cost. Apply a 1.5 billing safety
multiplier. These values are budget controls, not claims about EODHD endpoint
prices.

Reason:

The AAPL canary produced 10 EODHD attempts and 28 configured local weighted
calls, while the dashboard increased by 50. Re-downloading every security would
spend provider quota without adding proportional reproducibility evidence.

## 2026-07-27: Scoring Input v3 Duration, Availability, and Classification Contract

Decision:

Preserve scoring-input v2 as immutable evidence and create content-addressed v3
payloads for contract remediation. Every v3 observation records `periodStart`,
`periodEnd`, duration semantic evidence, derivation lineage, and separate
observed, provider-publication, public-availability, and ingestion timestamps.

The permitted proven duration semantics are `DISCRETE_QUARTER`, `YTD`, `ANNUAL`,
and `INSTANT`. A provider `QUARTERLY` bucket alone does not prove whether a
duration value is discrete or cumulative. Unproven semantics and missing period
starts remain explicit blockers.

Derive a discrete quarter only under
`discrete-quarter-subtraction-v1.0.0`, using YTD components with the same
taxonomy, unit, entity, fiscal-year start, valid period chronology, and valid
accession/availability chronology. Do not perform implicit YTD conversion.

Historical prices and market values without proven provider-publication times
may support a current ranking after ingestion, but cannot support historical
PIT valuation. Seal sector, market-cap band, company type, applicability,
classification version, universe version, as-of cutoff, and verified source
hash in each v3 classification snapshot.

Reason:

The 223 formula-complete v2 payloads lack sufficient duration and historical
publication semantics for Objective Rating v1. Adding explicit versioned
evidence without rewriting v2 keeps missing states honest and prevents
look-ahead assumptions.

## 2026-07-27: Route Objective Rating Evidence Through SEC Timelines

Decision:

Keep Objective Rating v1 formulas unchanged and route financial duration
evidence through a versioned SEC standard-taxonomy timeline. Retain exact
concept, unit, dimensions, start, end, form, frame, accession, filed and
accepted timestamps. Unknown, custom or economically non-equivalent concepts
remain missing.

Permit YTD subtraction only for facts with identical entity, taxonomy, concept,
unit, dimensions and fiscal-year start when both accessions were public by the
target cutoff. Preserve both operands and use
`SEC-YTD-DIFFERENCE-v1.0.0`.

Create `provider-neutral-scoring-input-v4.0.0` with separate instant, duration,
market-observation and derived records. Historical valuation requires
contemporaneously available financials, unadjusted EOD close and PIT instant
common shares. Ingestion timestamps do not establish historical availability,
and diluted weighted-average shares do not replace instant shares.

Reason:

The v3 audit confirms that all 223 cached securities lack proven duration and
historical valuation availability semantics. SEC structured facts can provide
authoritative financial periods and filing lineage, while historical market
observations require an explicit, independently accepted availability policy.
This route preserves missing-data and look-ahead protections without changing
factor weights or formulas.

## 2026-07-27: Accept the Offline SEC v4 Timeline but Keep Scoring Blocked

Decision:

Accept `provider-neutral-scoring-input-v4.0.0` as the evidence contract and
`sec-us-gaap-objective-rating-map-v1.0.0` as its strict standard-concept map.
The offline implementation may retain exact SEC Company Facts and use cached
submissions acceptance timestamps. It may derive discrete quarters only under
`SEC-YTD-DIFFERENCE-v1.0.0`.

Accept `US-EOD-NEXT-SESSION-OPEN-v1.0.0` as a conservative internal
availability policy for unadjusted EOD close. Do not describe it as provider
publication metadata, and do not infer historical market capitalization from
it without PIT class-specific shares.

Keep `InterestExpense`, `InterestAndDebtExpense`, overlapping debt components,
non-GAAP EBITDA, and diluted weighted-average shares as invalid automatic
substitutes for strict interest, total debt, EBITDA, and instant shares.
Current-only eligibility is evaluated separately from historical eligibility,
but every frozen required factor must still be valid.

Reason:

The hash-verified offline run built 216 SEC timelines and 59,583 deterministic
quarter derivations without a network request. Seven securities lacked cached
SEC transport. Strict interest coverage was zero, debt completeness and EBITDA
could not be proven, and instant shares lacked traded-class proof. Current QC,
current UQ, and historical PIT eligibility therefore remain zero. Repeating
the existing endpoints would not resolve these semantics; the next decision is
between bounded official filing-context evidence and a licensed PIT source.

## 2026-07-28: Restore Frozen v1 Source Semantics

Decision:

Supersede the v4.0 source-semantic restriction that accepted only
`InterestExpenseNonOperating`. Frozen v1 requires gross reported interest
expense for `EBIT / abs(interest expense)` and did not restrict it to
nonoperating interest.

Under `sec-interest-expense-policy-v1.1.0`, accept unsegmented consolidated
`InterestExpense`. Treat `InterestExpenseDebt` and
`InterestExpenseNonoperating` as issuer-policy-dependent alternatives.
Continue to reject `InterestAndDebtExpense`, net interest, capitalized
interest, and component-only facts.

Permit a documented standardized vendor `totalDebt` because the frozen
specification explicitly permits total debt where supplied. Do not require an
SEC component sum on that source route. Keep total debt missing until the
provider documents the exact inclusion semantics.

Treat frozen EBITDA as a normalized reported input. Do not feed the later
pretax-plus-interest-plus-D&A derivation into QC-v1.0.0 or UQ-v1.0.0 without a
separate approved formula/source-normalization decision.

Separate current snapshot, forward observation, and historical reconstruction
requirements. A current provider market-cap value ingested by the sealed
cutoff does not require historical publication metadata. UQ's own-history
FCF-yield factor still requires its frozen monthly PIT inputs. A full historical
backtest still requires historical availability and revision lineage for every
input.

Reason:

The official taxonomy labels `InterestExpense` as operating and nonoperating
total interest, while the current concept spelling is
`InterestExpenseNonoperating`. Cached evidence contains accepted
`InterestExpense` duration facts for 171 securities. The five-security canary
therefore used a later, narrower policy rather than the frozen formula meaning.

Reclassification removes strict nonoperating interest as a universal blocker
but does not create scores. EODHD total debt and EBITDA exist for all 223
provider-formula-ready securities, yet public documentation does not establish
the total-debt inclusion policy or bridgeable TTM EBITDA duration. Current QC,
current UQ, and historical PIT eligibility remain zero for those independent
reasons.

## 2026-07-28: Keep EODHD Debt and EBITDA Semantics Unaccepted

Decision:

Do not promote `shortLongTermDebtTotal` or financial-statement `ebitda` into
the frozen Objective Rating v1 provider semantic contract based only on the
current public EODHD documentation.

Accept as documented facts that EODHD calls `shortLongTermDebtTotal` total debt,
that Financials records carry statement currency and filing date, and that
EODHD defines `ebitda` as `ebit + depreciationAndAmortization`.

Keep total-debt equivalence `NOT_DOCUMENTED`: EODHD says composition may vary
by company and does not publish exhaustive inclusion/exclusion, consolidation,
instant-period, or immutable revision semantics. Keep TTM EBITDA construction
`NOT_DOCUMENTED`: quarterly values are not defined as discrete quarter, YTD,
or TTM. Mark immutable historical revision semantics `CONTRADICTED` because
EODHD has publicly announced recalculating historical fundamentals without a
documented immutable field-revision stream.

Reason:

The official glossary, debt explainer, Fundamentals documentation, and
official OpenAPI path were inspected and hash-recorded without requesting
financial data. The OpenAPI schema confirms the endpoint and broad Financials
collections but supplies no field-level statement schema. Existing 223/223
field presence proves availability, not meaning. Current QC therefore remains
blocked. Current UQ additionally remains blocked by monthly PIT FCF-yield
history. A support inquiry is required before these fields can be promoted.

## 2026-07-28: Accept the EODHD Current-Snapshot Debt and TTM EBITDA Route

Decision:

Supersede the preceding current-snapshot conclusion, while retaining its
historical PIT limitations.

For `objective-rating-current-snapshot-policy-v1.0.0`, accept:

- `Financials.Balance_Sheet.*.*.shortLongTermDebtTotal` as
  provider-normalized `total_debt`; and
- `Highlights.EBITDA` as provider-normalized TTM `ebitda`.

The frozen v1 formula accepts total debt where supplied and a normalized
reported/provider EBITDA input. It does not require a complete SEC component
sum or a quarterly EBITDA reconstruction. Issuer-specific debt composition is
recorded as a provider-normalization limitation rather than treated as an
automatic missing value.

This route is limited to a hash-verified response completed before a sealed
current cutoff. It records provider update date, retrieval/ingestion evidence,
unit, currency, source hash, parser/policy version, and limitations. It cannot
support an old-cutoff reconstruction or prove immutable revisions.

Reason:

The official EODHD glossary calls `shortLongTermDebtTotal` total debt and
defines `Highlights.EBITDA` as TTM. The offline adapter found complete
current-only supplements for 216 of 223 target securities. Fifty-five
securities satisfy the complete primitive QC source-contract intersection, but
that is not algorithm eligibility. Current QC eligibility remains zero until
the exact factor windows and required-factor statuses are assembled. Current
UQ retains the monthly PIT FCF-yield blocker, and historical PIT remains
unproven.

## 2026-07-28: Version Fiscal Q4 Derivation and Direct Enterprise Value

Decision:

Add `SEC-FY-MINUS-9M-v1.0.0` rather than expanding
`SEC-YTD-DIFFERENCE-v1.0.0` silently. The new rule derives a discrete fiscal
fourth quarter only from an aligned annual 10-K fact and nine-month Q3 10-Q YTD
fact with identical entity, concept, unit, currency, dimensions, fiscal year,
and fiscal start. Both operands must be available by cutoff. Amendment,
revision, period-boundary, sign-convention, and 53/54-week alignment conflicts
remain missing.

Keep `6M - 3M` and `9M - 6M` under the existing adjacent-YTD rule.

Accept positive current EODHD `Valuation.EnterpriseValue` as an alternative
earnings-yield denominator because the official provider formula matches
frozen v1. Under this direct route, a separate minority-interest component is
`NOT_APPLICABLE`; a missing component is never converted to zero. Historical
enterprise-value reconstruction remains unproven.

Limit three-year factor endpoints to margin quality, diluted EPS growth, FCF
per diluted share growth, and dilution. Stability retains its separate
eight-quarter aligned history.

Reason:

An annual-minus-nine-month derivation has different form, duration, revision,
and fiscal-calendar semantics from adjacent YTD differences and therefore
requires its own version. The offline correction produced 9,018 accepted Q4
derivations, rejected 78 amended combinations and two calendar mismatches, and
raised stability readiness to 43 of 55.

Full current QC input readiness remains zero because no candidate has a
current accepted gross-interest TTM window. Ten candidates have every other QC
factor input. Current UQ remains independently blocked by its historical
FCF-yield percentile.

## 2026-07-27: Keep Source-Contract Coverage Separate from Factor-Window Readiness

Decision:

Treat the 55-security current source-contract intersection as an input to a
separate deterministic factor-window gate. Do not interpret field presence or
source-contract acceptance as proof that the frozen QC-v1.0.0 or UQ-v1.0.0
windows are complete.

The factor-window gate requires recent consecutive `DISCRETE_QUARTER`
observations, duration-weighted diluted shares, aligned eight-quarter histories,
three-year endpoints, cutoff-safe lineage, and explicit missing states. It may
use documented `Highlights.EBITDA` as current TTM EBITDA, but it may not sum raw
YTD facts, infer missing fourth quarters, default minority interest to zero, or
manufacture PIT valuation history.

Reason:

The offline 55-security assembly produced complete net-debt-to-EBITDA inputs
but zero complete QC or UQ input sets under the frozen evidence rules. This
outcome is `INSUFFICIENT_DATA`, not permission to relax formulas, derivations,
cohort rules, or missing-data behavior.

## 2026-07-28: Require Issuer Evidence for Interest Concept Transitions

Decision:

Adopt `sec-issuer-interest-consistency-v1.0.0` as a diagnostic policy. Continue
to prefer consolidated `us-gaap:InterestExpense`. A transition to
`InterestExpenseDebt` or `InterestExpenseNonoperating` is not authorized unless
issuer evidence proves equal economic scope, statement role, unit, sign
convention, complete period coverage, and disclosure continuity before the
cutoff.

Overlapping comparative periods with equal values are supporting evidence but
are not sufficient by themselves. `InterestAndDebtExpense`, net-interest
concepts, capitalized interest, old annual substitutions, and cross-cutoff
facts remain rejected.

Reason:

The bounded offline audit found nine issuers with current conditional interest
facts and historical overlap, but no cached filing presentation/context
evidence proving complete gross-interest scope. PLAB had no current acceptable
gross-interest concept. Therefore none of the ten interest-only QC candidates
became QC input-ready.
# 2026-07-28: Keep EODHD provider-normalized current interest blocked pending a documented duration contract

- Official EODHD documentation identifies `interestExpense` as borrowed-funds
  cost and documents report currency, period-end date, and filing date.
- Public documentation does not define quarterly records as discrete, YTD, or
  TTM; does not explicitly define full-year duration; and does not establish
  complete treatment of capitalized interest, financing fees, netting, or
  operating-interest components.
- Existing controlled records preserve period-end, SEC accession, source hash,
  and immutable payload lineage, but they do not contain a provider period
  start. An SEC period/accession match does not prove provider duration or
  economic-scope equivalence.
- Therefore EODHD `interestExpense` is not authorized as a current TTM input
  until the provider supplies a versioned semantic contract or equivalent
  official documentation. Missing interest remains missing.
- No Objective Rating v1 formula, weight, cohort, PIT, or PASS rule changes.

# 2026-07-28: Treat Yahoo-EODHD current-interest comparison as evidence, not automatic authorization

Adopt `provider-current-interest-comparison-v1.0.0` as a bounded diagnostic
policy for the ten frozen interest-only candidates. Require explicit Yahoo
`3M`, `12M`, and `TTM` period types, exact quarterly date alignment, currency
consistency, four non-overlapping recent quarters, and tightly bounded numeric
agreement.

Cross-provider agreement is recorded as evidence for Main Algorithm. It does
not by itself authorize provider-normalized interest expense or generate an
interest supplement. Provider conflicts, Yahoo internal revision
inconsistency, and insufficient evidence remain separate terminal states.
Raw Yahoo responses and numeric differences remain in Git-ignored controlled
storage; Git-safe artifacts retain only statuses, dates, hashes, and lineage.

# 2026-07-28: Keep the current QC cohort gate closed after offline completion audit

The v1.5 current factor manifest has seven QC input-ready securities against
the frozen minimum of 20. All 48 not-ready securities retain an
interest-coverage blocker, and 42 also lack several other current or historical
factor inputs.

Do not treat EODHD current-field presence as semantic authorization, do not
reinterpret provider conflicts, and do not use UQ historical PIT gaps to
change the current-QC threshold. Existing accepted offline evidence produces
zero immediately completable additional securities. Potential current-field
and bounded cross-provider routes require separate Algorithm acceptance before
they can change factor readiness.

# 2026-07-28: Authorize frozen-v1 raw current TTM fields and restore 150-day freshness

The frozen Objective Rating v1 contract names diluted EPS, revenue, and gross
profit as raw inputs. Authorize EODHD `Highlights.DilutedEpsTTM`,
`Highlights.RevenueTTM`, and `Highlights.GrossProfitTTM` for sealed current
snapshots when TTM identity, period end, cutoff-safe acquisition, unit,
currency, normalization version, and source hashes are retained. This does not
authorize historical PIT use or create a missing three-year endpoint.

Do not authorize `Highlights.OperatingMarginTTM` as a formula operand. Frozen
v1 makes vendor ratios comparison-only; operating margin remains operating
income divided by revenue.

Restore the frozen 150-calendar-day current-filing freshness limit in place of
the factor-window implementation's 200-day limit before reassembly. This
removes CSCO from the seven previously ready cases and leaves six. Reaching the
minimum cohort of 20 therefore requires fourteen additional fully valid
securities, not thirteen. The Algorithm Gate remains closed pending that
evidence.

# 2026-07-28: Request a machine-verifiable EODHD duration and history contract

Accept the v1.7 current-factor reassembly as method-conformant, but keep the
Algorithm Gate closed at six QC input-ready securities. Do not execute the
single-symbol Yahoo preflight because even its best case reaches only seven,
below the frozen minimum of 20.

EODHD already exposes most required income-statement and cash-flow values. Ask
support only for unresolved machine-verifiable semantics and coverage:
period-start and explicit 3M/YTD/12M/TTM identity, historical TTM diluted EPS
and raw factor endpoints, current interest-expense TTM construction,
per-record publication availability, revision/vintage behavior, and plan
entitlement. Do not reopen the resolved current total-debt, EBITDA, revenue,
gross-profit, or diluted-EPS TTM decisions.

If support cannot provide exact endpoints, JSON paths, period semantics, and
versioned documentation, evaluate provider capabilities—not a preselected
brand—for explicit duration metadata, eight-quarter raw histories, comparable
historical TTM endpoints, split/unit/currency metadata, availability and
revision lineage, durable identifiers, and licensed snapshot retention.
## 2026-07-28 — Preserve accepted v1.5 evidence when applying the QC current-input policy

- Reassemble current QC factor inputs from immutable v1.5 controlled snapshots
  so accepted interest evidence and its hashes remain intact.
- Enforce the frozen 150-day current financial freshness limit and remove
  `CSCO` from the ready set.
- Permit cached EODHD `DilutedEpsTTM`, `RevenueTTM`, and `GrossProfitTTM` only
  for the sealed current snapshot with complete lineage.
- Continue to reject `OperatingMarginTTM` as a substitute for raw formula
  inputs and annual diluted EPS as a historical TTM endpoint.
- Do not execute the bounded Yahoo preflight because its best case produces
  only 7 ready securities, below the frozen cohort minimum of 20.

# 2026-07-28: Accept an isolated EODHD current-snapshot QC route

Accept the written EODHD support statement that quarterly financial values are
not cumulative for a separately versioned `CURRENT_DECISION_ONLY` adapter.
This decision does not revise the historical PIT contract and does not
authorize historical backtesting from today's downloaded history.

Use cached EODHD quarterly financial statements for current QC duration
operands, with adjacent period starts explicitly marked as inferred. Retain
cached response hashes, provider paths, retrieval times, filing dates, and
policy versions. Use only explicit positive SEC discrete-quarter diluted-share
facts and a separately versioned day-weighted annual-minus-nine-month
derivation for fiscal Q4 shares. Never use point-in-time shares as a diluted
weighted-average substitute.

The resulting offline gate contains 190 complete QC input sets and 136
formula-valid securities, exceeding the frozen general-company minimum of
100. Authorize deterministic `QC-v1.0.0` scoring for this sealed snapshot only.
Keep UQ, historical performance claims, automatic execution, and Forward
Decision-Quality Validation closed pending separate approval.

# 2026-07-28: Preregister Forward Validation as a prospective dry run

After explicit approval, preregister `FORWARD-VALIDATION-v1.0.0` in `DRY_RUN`
mode against the sealed 136-security current QC Algorithm Gate. Freeze the
strategy path, top/bottom bucket construction, 5/20/60-trading-day horizons,
entry policy, six counterfactual arms, USD 10,000 shadow notional, transaction
costs, slippage, cash-rate contract, sector benchmarks, and claim boundaries
before observing outcomes.

Do not enroll the current bucket preview as live signals. The protocol requires
a fresh sealed screening run after the verified final US trading session of
the week. Keep enrollment closed until the trading calendar, benchmark prices
and actions, PIT three-month Treasury rate, identity and corporate-action
coverage, and fresh weekly score pass their gates.

Do not relabel the current provider route as the 300-to-500-security historical
PIT acceptance required for `FORMAL` mode. Prospective dry-run evidence,
formal provider acceptance, and statistical edge confirmation remain separate
claims.

# 2026-07-28: Freeze the first Forward enrollment operational preflight

Use 2026-07-31 as the first scheduled weekly-close candidate after reviewing
the published NYSE calendar. Treat this only as a scheduled session; require
confirmation that the regular session completed before signal enrollment.

Freeze the required current-preview benchmark set as SPY, XLB, XLC, XLI, XLK,
XLP, XLV, and XLY. At the weekly close, require a fresh sealed QC run, dated
candidate and benchmark prices and actions, cutoff-safe three-month Treasury
cash rate, identity and tradability review, and immutable hashes before
creating any signal. A missing or conflicting input stops enrollment rather
than receiving a default value.

# 2026-07-28: Operate Forward validation as a daily incremental cycle

Supersede the weekly operating cadence with
`FORWARD-VALIDATION-v1.1.0`. Retain the weekly preregistration as immutable
historical evidence; do not overwrite or relabel it.

After each completed regular US trading session, refresh daily prices and
historical market capitalization for the active source universe and required
benchmarks. Refresh fundamentals, identity, dividends, and splits only when
their per-dataset last-update state is stale, missing, or a priority trigger
requires it. The 100,000-call provider quota is a safety capacity, not a
consumption objective.

Require a completed-session check, bounded request plan, zero retries,
cross-process lock, immutable request evidence, refreshed scoring, and sealed
signals before enrollment. Missing or stale data must remain explicit and
must not receive a default value. Daily cohort overlap must be reported, and
primary inference must use unique first-entry episodes with a 60-trading-day
same-security, same-strategy, same-bucket re-entry cooldown.

# 2026-07-28: Separate tactical trading signals from long-horizon research

Retain Objective Rating v1 unchanged. Add `TACTICAL-SIGNAL-v1.1.0` for
daily-data one-week, one-month, and three-month research. Keep momentum continuation
and mean reversion as separate theses and require an independent entry
confirmation gate. A decline alone must never authorize a mean-reversion
entry.

Add `LONG-HORIZON-RESEARCH-v1.0.0` as an absolute 12-month-plus research
rubric, with a separate bank model and an explicit no-score rule for recent
IPOs lacking adequate public history. Permit only a cited, bounded
`RESEARCH-EVIDENCE-OVERLAY-v1.0.0`; it cannot replace missing data or
independently determine a trade.

Keep intraday trading, automatic execution, portfolio weights, and claims of
statistical edge out of scope. Walk-forward tactical diagnostics must form the
signal after a completed close, enter no earlier than the next session, include
costs, and retain `statisticalEdgeProven=NOT_ESTABLISHED`.

# 2026-07-28: Freeze AI Equity Research Rubric v1

Adopt `AI-EQUITY-RESEARCH-v1.0.0` as the versioned qualitative evidence layer
after deterministic screening. Require fixed dimension caps for management
execution, governance, strategy and competition, capital allocation, operating
resilience, regulatory and legal exposure, and accounting and disclosure
quality. The total long-horizon overlay is bounded to plus or minus 10 points;
separate expiring tactical event overlays are bounded to plus or minus five
points and cannot overwrite the raw opportunity indices.

Require CEO career and execution evidence, company-strategy dependencies, a
counter-thesis, evidence grades, citations, source timestamps, content hashes,
missing states, conflicts, model and prompt versions, and token/tool/cost
telemetry. AI cannot fill a missing deterministic score, infer management
quality from reputation, set portfolio weights or authorize a trade.

Use `gpt-5.6-terra` with medium reasoning as the default production review
configuration. Limit each security to 12,000 input tokens, 2,000 output tokens,
three web-search calls, a USD 0.15 cost target and a USD 0.20 hard application
budget. Reserve `gpt-5.6-sol` for material-risk or source-conflict escalation
under a USD 0.35 hard budget. Model aliases and prices remain runtime
configuration rather than investment-methodology semantics.

# 2026-07-28: Replace new tactical decisions with Tactical Signal v2

Retain `TACTICAL-SIGNAL-v1.1.0` and its artifacts for reproducibility, but use
`TACTICAL-SIGNAL-v2.0.0` for new evaluations. Do not change Objective Rating v1
or `LONG-HORIZON-RESEARCH-v1.0.0`.

Separate setup type, horizon opportunity, rebound potential, entry timing,
payoff asymmetry, risk, entry stage, and actionability. A decline may increase
rebound potential but cannot independently produce a probe or confirmed entry.
Require completed-session structural reversal evidence for an early probe and
keep high-risk or falling-knife states independently blockable.

Adopt the entry stages `NONE`, `EARLY_REVERSAL_CANDIDATE`, `PROBE_ELIGIBLE`,
`CONFIRMED`, `INVALIDATED`, and `INSUFFICIENT_DATA`. An early candidate is
watch-only. A probe is capped at 0.25 of one independently configured risk
unit; a confirmed entry is capped at one risk unit. These caps are not
portfolio weights, and AI cannot change them.

Form daily signals only after a completed close, make them effective no earlier
than the next session open, and expire them after one further completed
session. Keep intraday timing as a future, separately versioned contract.

Require corporate-action-adjusted OHLC, shared security/benchmark sessions,
positive-volume completed sessions, explicit replay/live telemetry, and
model-version provenance. The previous raw-close validation artifacts remain
historical evidence but their split-crossing walk-forward diagnostics must not
be used as V2 validation.

Expose the deterministic evaluator only through the Python internal API with
caller-supplied bars. It must not fetch provider data, execute a trade, or
bypass the Spring-owned user-facing workflow.

# 2026-07-28: Separate tactical opportunity from current entry value

Supersede Tactical Signal v2.0 for new evaluations with
`TACTICAL-SIGNAL-v2.1.0` while retaining old artifacts for reproducibility.
Keep the one-week, one-month, and three-month opportunity indices, but add a
setup-specific current entry-value score and an independent momentum-extension
risk score.

Do not penalize a security solely because it is near a 52-week high. A gradual,
internally consistent breakout may remain `ENTRY`. A confirmed but abnormally
extended momentum setup must return `WAIT_FOR_PULLBACK`, map conservatively to
the legacy watch state, and carry a zero risk-unit cap. Do not change the
mean-reversion payoff-asymmetry formula or its entry gates.

# 2026-07-28: Adopt a stable provider-neutral analytics model interface

Expose `LONG-HORIZON-RESEARCH-v1.0.0` and
`TACTICAL-SIGNAL-v2.1.0` through exact model-ID and model-version routing under
one `analytics-model-result-v1.0.0` envelope. Preserve timing, expiry,
normalized-input hash, evidence hash, provider provenance, explicit missing
states, and the deterministic-versus-AI boundary.

Keep provider-native fields outside the model request. Replace a price or
fundamental provider through its normalization adapter and capability
declaration rather than by changing model formulas or public contracts.
Reject evidence available or retrieved after the decision cutoff and reject
future-dated tactical bars.

# 2026-07-28: Accept Forward validation engineering readiness without a return claim

Accept the Forward Decision-Quality framework's offline contract and integrity
checks as `PASS`, but keep the overall evidence status
`PENDING_FUTURE_OUTCOMES`. The sealed objective and tactical artifacts are not
a synchronized full-coverage daily snapshot, so enroll zero current signals.

Retain 5-, 20-, and 60-trading-day prospective horizons, next-session
execution, transaction costs, slippage, cash, sector ETF and SPY baselines,
abstention reporting, contamination controls, and immutable evidence hashes.
Historical walk-forward diagnostics remain descriptive and cannot satisfy
prospective sample requirements. Keep
`statisticalEdgeProven=NOT_ESTABLISHED` until real future episodes mature.

## 2026-07-28: Extend analytics with Market Intelligence Data Model v1

- Decision: add append-only V14-V16 migrations for reference/profile history,
  provider-neutral dataset metadata, explicit-status reusable metrics,
  sector/industry screening aggregates, and idempotent daily refresh
  operations.
- Ownership: Python owns all new `analytics.*` records; Spring Boot retains
  exclusive ownership of `app.*` and consumes new capabilities only through a
  separately versioned HTTP contract.
- Rationale: the existing V1-V13 structures already represent canonical
  securities, source lineage, normalized observations, sealed snapshots, and
  security-level deterministic ratings. Extending those structures avoids
  parallel identities and scoring models.
- Data safety: non-valid values remain explicit states rather than zero;
  economic, availability, and ingestion time remain separate; no raw licensed
  payloads or credentials are stored.
- Operations: PostgreSQL-backed plans, tasks, leases, checkpoints, freshness,
  quota telemetry, and audit records are sufficient for the current MVP.
  Partitioning and external queues are deferred until measured workloads
  require them.

# 2026-07-28: Adopt Daily Market Data Refresh v1

Run daily US price and corporate-action refreshes in the deployed Python
analytics worker against an explicit, versioned universe. Use provider-neutral
normalized contracts; make yfinance the default free adapter only where
licensing and quality permit, while retaining EODHD and future commercial
adapters as replaceable implementations.

Plan incremental overlapping windows by market session and persist separate
per-security cursors for unadjusted prices, total-return-adjusted prices, and
corporate actions. Record content lineage and explicit current, late, stale,
missing, inactive, and failed states. Price freshness does not refresh
fundamentals or establish scoring readiness.

Use PostgreSQL for the single-run advisory lock, idempotent run/item identity,
resumable checkpoints, quota usage, and structured status. Reserve worst-case
retry cost before EODHD work and reject plans that can exceed the configured
allowance. Keep live calls subject to a separately bounded preflight and
explicit approval. The required database tables are an integration handoff and
are not created by this implementation task.

# 2026-07-28: Add Market Intelligence and Screening v1 as a composition layer

Adopt `MARKET-INTELLIGENCE-SCREENING-v1.0.0` as the versioned durable security
profile and research-screening contract. Keep observed facts, classifications,
cohorts, deterministic model results, valuation evidence, and AI narrative
separate. Do not change Objective Rating v1, `TACTICAL-SIGNAL-v2.1.0`, or
`LONG-HORIZON-RESEARCH-v1.0.0`.

Require explicit missing, invalid, not-applicable, stale, cohort, and formula
eligibility states. Provider acceptance must not imply ranking eligibility.
AI may explain cited evidence but cannot set facts, scores, ranks, portfolio
weights, or trades. Defer persistence to the field-level database handoff in
`docs/market-intelligence-screening-v1.md`.

# 2026-07-28: Persist Market Intelligence profiles and screens through Python

Use the Python analytics service as the sole writer and reader of V17 Market
Intelligence profile and screening records. Resolve security, source, metric,
snapshot, provider, ingestion, and classification identities through existing
V1-V16 tables. Write a profile and all children in one transaction and treat
an identical canonical profile hash as an idempotent replay.

Seal screening runs with idempotency, request, input-snapshot, methodology, and
result hashes. Durable reads reconstruct the versioned contract from immutable
records without rerunning formulas. Keep all endpoints internal; Spring Boot
continues to own user-facing authorization and workflows. AI narrative remains
optional, cited, versioned, and constrained from deterministic fields.

## 2026-07-28: Persist the Market Intelligence Screening v1 profile layer

- Decision: add append-only V17 for immutable assembled profiles, selected
  fact/source lineage, cohort sufficiency, four versioned horizon views,
  valuation evidence, ranking exclusions, profile screening runs/results, and
  optional cited AI narratives.
- Reuse: canonical securities, identifiers, classifications, normalized
  observations, source records, snapshots, Objective Rating calculation
  results, group screening results, and freshness events remain in V1-V16.
- Boundary: the V17 profile-screening run ranks already assembled profiles; it
  does not replace the existing Objective Rating `screening_run`.
- AI safety: narrative records are physically separate and constrained never
  to affect deterministic facts, eligibility, scores, or ranks.
- Integration: the committed Python screening service still requires an
  idempotent persistence adapter. No `app.*`, Spring Boot, formula, provider,
  or live-data behavior changes are authorized by this migration.

# 2026-07-28: Bind Daily Market Data Refresh v1 to the V16 operations schema

Replace the provisional refresh persistence contract with the database-owned
V16 contract. Use `refresh_plan`, `refresh_run`, `refresh_task`,
`refresh_checkpoint`, `security_dataset_freshness`, and
`provider_usage_event` directly. Resolve configured public security identities,
providers, and dataset codes through existing reference tables.

Write normalized prices and corporate actions only through the existing
append-only `ingestion_batch`, `source_record`, `daily_price_observation`, and
`corporate_action` structures. Repeated source content is idempotent; changed
content appends a revision. Never update immutable evidence, freshness events,
checkpoints, usage events, or terminal V16 tasks/runs.

## 2026-07-28: Establish the authoritative current-state documentation boundary

- Decision: use `docs/current-state.md` as the authoritative implementation
  and operational status entry point.
- Lifecycle: keep dated methodology reports and Git-safe generated acceptance
  artifacts immutable. A newer implementation updates the current-state,
  architecture, roadmap, module, decision, and development documentation
  rather than rewriting historical evidence.
- Rationale: the repository now contains many versioned gates and historical
  reports. Separating current intent from immutable evidence prevents an old
  run from being mistaken for the active production state.
- Current next gate: complete the Market Intelligence end-to-end vertical
  slice from bounded refresh through PostgreSQL, Python, Spring Boot, and
  Next.js before expanding model scope.

## 2026-07-28: Use managed PostgreSQL for the first closed-test deployment

- Decision: deploy one managed PostgreSQL database in the same private region
  and network as the Spring Boot and FastAPI services. Retain separate
  `app.*` and `analytics.*` ownership boundaries.
- Initial platform: Render managed services are the preferred first closed-test
  path. Amazon RDS remains the later production-learning target.
- Migration boundary: Flyway is the only DDL authority. A controlled
  single-instance release may initially run Flyway, but horizontal deployment
  requires a one-off migration release job and non-DDL runtime credentials.
- Security: the database is not public; connections require TLS; credentials
  live in encrypted deployment secrets; frontend code never receives a
  database URL.
- Recovery: enable managed daily backups, take an on-demand backup before
  migrations, retain at least 14 days when the selected plan permits it, and
  rehearse restoration before deployed user portfolio state becomes unique.
- Deployment status: design only. No cloud resource, billing, scheduler, or
  production database has been activated.
