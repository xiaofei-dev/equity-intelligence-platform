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
