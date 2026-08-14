# Decision Log

## 2026-08-13: Implement Unified Portfolio and Risk Context v1 on V28

- Reuse V12 portfolio, sealed account-snapshot, liability, and versioned
  constraint-policy ownership instead of creating a second account system.
- Preserve V21 `CORE`/`TACTICAL` persistence unchanged as a legacy lane; V28
  uses only `LONG_TERM_CORE` and `QUANT_TRADING`.
- Keep FastAPI stateless over `app.*`; Spring owns identity, policy validation,
  public workflow, persistence, and cross-language result verification.
- Persist the exact risk thresholds together with their V12 policy ID so a
  historical violation remains explainable and cannot be reinterpreted by a
  later policy.
- Store missing valuations as explicit states, never zero. Keep the two engine
  evidence references independent and prohibit score averaging.
- Add immutable, idempotent human reviews while keeping final-weight, order,
  brokerage, and LLM decision authority false.
- Keep Quant v2 `NOT_VALIDATED` and reject any request that marks it eligible
  for portfolio research use.

This file records product and architecture decisions. New entries should be appended rather than rewriting historical decisions.

## 2026-08-13: Stop Quant v2 after one unsupportive mean-reversion replay

- Freeze Quant v2 as an independent `REGIME_FILTERED_MEAN_REVERSION` model;
  do not rewrite or blend the observed v1 or v1.1 momentum systems.
- Accept the deterministic signal, ranking, entry/exit, sizing, nonlinear-cost,
  fixed-cost-sensitivity, and one-execution historical engineering boundaries.
- Seal the only controlled replay as
  `NOT_DIRECTIONALLY_SUPPORTIVE_NO_RETUNING_ON_SAME_OUTCOME`: USD 100,000 ended
  at USD 107,516.24 with 0.63% CAGR, versus USD 434,189.17 and 13.53% CAGR for
  SPY. Four of eight preregistered gates passed.
- Preserve the favorable low-drawdown and positive-expectancy observations as
  development evidence, but do not treat them as sufficient economic support.
- Retain `NOT_VALIDATED`, prohibit same-outcome retuning, and do not promote v2
  into V27 or the FastAPI/Spring/Next.js decision path.

## 2026-08-13: Accept the Quant v1.1 provider-neutral V22 signal assembly

- Keep Quant v2 deferred and productize only the frozen v1.1 research boundary.
- Add a read-only V22 adapter for security identity, ticker intervals,
  calendars, completed sessions, and persisted selector aggregates.
- Require 253 exact total-return-adjusted sessions for SPY and every expected
  member, plus an exact sorted denominator of at least 20 securities.
- Preserve missing and not-applicable members in the denominator. Raise an
  integrity failure for invalid, stale, excluded, future, ambiguous, or
  drifting selector evidence; never substitute zero or a neutral signal.
- Keep price values out of the Git-safe manifest and retain `NOT_VALIDATED`.
- Authorize only deterministic research-signal calculation. V22 lacks governed
  Quant event/lifecycle interval proof, so persistence, APIs, portfolio
  execution, and brokerage remain closed.

## 2026-08-12: Reject Quant Trading v1 and freeze a distinct v1.1 successor

- Seal the v1 full-population result as
  `REJECTED_FOR_PRODUCTION_ECONOMIC_PERFORMANCE` and retain `NOT_VALIDATED`.
  USD 100,000 ended at USD 113,808.46 with 1.13% CAGR versus SPY at
  USD 438,691.69 and 13.68% CAGR. Lower drawdown does not compensate for the
  observed opportunity cost.
- Prohibit in-place changes to the observed v1 thresholds, formulas, entries,
  exits, risk sizing, and costs. Any successor requires new model, strategy,
  formula, entry/exit, engine, and validation identities.
- Freeze `QUANT-TRADING-v1.1.0` / `DUAL-MOMENTUM-TREND-v1.1.0` as a separate
  economic hypothesis: positive absolute 12-1 and 6-1 momentum, security and
  SPY trend filters, five-session cross-sectional rebalancing, next-open entry,
  at most ten positions, no profit target, and trend/rank/ATR exits.
- Preserve USD 100,000, 0.5% prior-close NAV risk, 10% notional cap, whole
  shares, and C9 nonlinear entry/exit costs. Keep SPY primary and cash
  secondary; equal-weight and sector benchmarks remain unobserved.
- Record that v1.1 was designed after observing v1. Reusing the same history is
  development evidence only, not an untouched holdout, strict PIT result,
  backtest-supported label, future-return promise, or brokerage authority.
- Freeze a provider-neutral v1.1 portfolio simulator and an outcome-blind
  historical protocol before reading v1.1 prices or returns. Require the exact
  127-session maturity tail, prior-20-session execution liquidity, explicit
  untradable-SPY and active-bar failures, `COMPLETE_CASH`, exact trade pairing,
  calendar-day metrics, and a separately re-sized fixed-5-bps replay.
- Require a checked runner and one outcome-access intent that bind exact source
  hashes. Pilot 25 and expansion 100 are integrity checkpoints only; the full
  191 denominator is the sole performance evaluation.

## 2026-08-12: Freeze Quantitative Trading v1 Stage 0

- Adopt one independent long-only `MOMENTUM_CONTINUATION` strategy for the
  first executable Quantitative Trading implementation.
- Keep mean reversion in a separately versioned future strategy; do not blend
  it into momentum continuation.
- Form signals only after completed-session close and allow entry only in the
  next completed session, with explicit entry, gap, stop, target, trailing,
  invalidation, time-stop, sizing, cash, and exit-priority policies.
- Freeze USD 100,000 simulation capital, ten concurrent positions, 0.5% NAV
  risk per position, 10% notional cap, SPY primary benchmark, C9 nonlinear
  costs, and 5-basis-point-per-side sensitivity.
- Require V22 durable identities and evidence lineage. Missing event/action
  evidence fails closed. Preserve Tactical v2.2 and legacy V21 unchanged.
- Keep production `NOT_VALIDATED`; historical evidence is limited to
  `DEVELOPMENT_OBSERVED_CURRENT_REVISION_CURRENT_SURVIVOR`. Stage 0 creates no
  engine, backtest, migration, API, order, or brokerage authority.
- Freeze deterministic daily-bar fills: next eligible scheduled-session open,
  conservative stop-first same-bar handling, next-session trailing and
  invalidation effects, whole-share/cost-reserved sizing, durable lifecycle
  handling, and identical strategy/benchmark cost and terminal rules.

## 2026-08-12: Implement the pure Quantitative Trading v1 Stage 1 engine

- Implement only `MOMENTUM-CONTINUATION-FORMULAS-v1.0.0` in a new pure Python
  engine. Do not reuse Tactical v2.2 scores and do not add mean reversion.
- Require exactly 253 aligned, completed, cutoff-valid security and SPY
  adjusted-OHLCV sessions with complete durable identity, selector, source,
  normalized, event, corporate-action, lifecycle, and chronology bindings.
- Freeze the exact price momentum, SPY-relative momentum, moving-average trend,
  breakout, volume, close-location, liquidity, chase, and ATR features and
  their explicit weights and readiness thresholds.
- Use an isolated precision-50 `ROUND_HALF_EVEN` Decimal context. Compare the
  unrounded score, display scores at two decimal places, and preserve full
  canonical Decimal precision for raw features and trade-plan prices.
- Freeze the entry range, initial stop, inclusive 2%-12% stop-distance gate,
  two-risk-unit full-exit target, monotonic three-ATR trailing rule, breakout
  or two-close invalidation, and 60-session time stop.
- Preserve `NOT_VALIDATED`. Missing, stale, invalid, or ineligible evidence
  emits no numeric result or plan. Stage 1 creates no backtest, migration, API,
  brokerage order, automated execution, or final portfolio weight.

## 2026-08-12: Separate Current Fundamental Value Assessment Authority and V26 Read Path

Decision:

- Keep V25 identity authority, V22 evidence selection, and V26 investment
  assessment persistence as separate responsibilities. A V25 row with
  `investment_assessment_authorized=false` cannot be reinterpreted as assessment
  authorization.
- Add a narrow append-only V26 authority for the GOOG, FOX, and MSFT current
  Fundamental Value assessment scope. Provisioning is an explicit operation;
  the evidence registrar and assessment repository remain read-only over
  authority records.
- Bind real cached inputs through exact plan, request identity, endpoint,
  provider/schema/adapter/normalization, response Date, journal, checkpoint, and
  raw-decoder replay before V22 registration. Do not reuse old assessment JSON.
- Publish only immutable GET projections through Python to Spring Boot to
  Next.js. Do not expose licensed source values or authorize ranking, portfolio
  weights, deterministic trade action, brokerage execution, or model-evidence
  upgrades.

Status:

- The result remains `NOT_VALIDATED`. Historical C9 remains mixed development
  evidence and is not proof of future performance.
- Final V26 PostgreSQL 17 typed and migration/upgrade/refusal acceptance passed.
  The local business database was migrated through Flyway, explicit authorities
  were installed, and immutable GOOG, FOX, and MSFT assessments were persisted.
  Exact replay was idempotent, and the real FastAPI read path returned all three
  while excluding private evidence fields.
- Treat reproducible, leakage-resistant, economically useful relative direction
  as the validation objective. Do not require or imply perfect future accuracy,
  and do not tune the model merely to turn mixed historical evidence into a
  favorable label.

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

## 2026-07-28: Freeze Market Intelligence Vertical Slice v1

- Decision: use the versioned
  `market-intelligence-closed-test-us-v1.0.0` 66-security universe with 48
  primary, 7 reserve, 2 reference-only, and 9 excluded members.
- Provider boundary: use Yahoo/yfinance for bounded closed-test daily prices
  and EODHD for separately approved corporate actions and fundamentals.
  Provider acceptance remains separate from factor readiness and ranking.
- Execution boundary: require a no-network preflight and exact confirmation
  token. The aggregate operator workflow runs prices, actions, and fundamentals
  sequentially and stops before constructing the next provider after any
  non-success state.
- Persistence boundary: reuse V14-V17. No V18 is required. Python remains the
  owner of `analytics.*`, evidence selection, formulas, profiles, and screens.
  Spring Boot remains the public workflow boundary.
- API boundary: publish `/api/v1/market-intelligence/*` through Spring Boot.
  The browser calls Spring only; Java does not reimplement Python formulas or
  query Python-owned rating tables as a substitute for the versioned contract.
- UI boundary: provide a Next.js `/research` workspace with search, facets,
  pagination, durable profiles, current price/freshness, four horizons,
  valuation, exclusions, model versions, and a visibly separate AI narrative.
- Forward boundary: sealing a screen emits an idempotent decision-snapshot
  audit handoff. It does not create a trade, fill a missing rank, or claim
  future performance.
- Live result: accept the first 57-security Yahoo run as a safety-stop
  `PARTIAL` after an ACN `MALFORMED_RESPONSE`. Do not retry it or start EODHD
  stages without a new explicit authorization.
- Recovery result: after separate approval, retain ACN's 259 valid sessions,
  reject the malformed 2026-07-28 bar, and expose its price freshness as
  `STALE/LATE_DATA`. Complete the remaining Yahoo price scope and the bounded
  EODHD corporate-action and fundamental scopes without relaxing data-quality
  rules.
- Snapshot result: seal the refreshed 66-profile snapshot and preserve
  `NO_ELIGIBLE_RESULTS` with 66 explicit exclusions. Provider completion is
  not scoring eligibility.
- Deployment status: local implementation and verification only. No commit,
  push, cloud resource, scheduler, or deployment is authorized by this
  decision.

## 2026-07-28: Keep Gitleaks exceptions narrowly evidence-bound

- Preserve the existing rule/path/format-scoped exception for SHA-256 evidence
  hashes.
- For Gitleaks 8.30.1, ignore only the two complete historical fingerprints
  where the public fixture plan key `daily-market-v1` is misclassified as a
  generic API key.
- Do not add a directory-wide ignore, a generic secret regex, or an exception
  that could hide a different commit, file, rule, or line.

## 2026-07-28: Apply a minimal frontend production security update

- Update Next.js and its matching ESLint configuration from 16.2.0 to 16.2.12.
- Pin patched PostCSS 8.5.24 and Sharp 0.35.3 through npm overrides because
  Next.js otherwise resolves vulnerable transitive versions.
- Require frontend contract tests and `npm audit --omit=dev` in CI.
- Keep this as a non-major dependency repair; do not use
  `npm audit fix --force`.

## 2026-07-28: Bridge sealed V17 decisions to prospective V11 attempts

- Decision: add an idempotent prospective-enrollment bridge from sealed V17
  Market Intelligence screening decisions to the existing V11 Forward ledger.
- Audit boundary: record every accepted attempt as one append-only
  `FORWARD_PROSPECTIVE_ENROLLMENT_ATTEMPT_SEALED` audit event. Create V11
  enrollment, candidate-signal, and outcome rows only for genuinely eligible
  deterministic results.
- Current result: the 66-security screen contains 0 eligible results, 55
  `INSUFFICIENT_DATA` Objective outcomes, and 11
  `SPECIALIZED_MODEL_REQUIRED` outcomes. Preserve `NO_ELIGIBLE_SIGNALS` and
  create no V11 signal or outcome row.
- Maturity boundary: retain exact 5-, 20-, and 60-trading-session prospective
  checkpoints. Treat 12-month-plus model output as context only.
- API boundary: Spring Boot owns typed public create, latest, and detail routes;
  Next.js consumes the typed latest contract and does not call Python or the
  database directly.
- Evidence boundary: transform persisted raw fundamentals into frozen factor
  inputs only when period semantics, units, PIT availability, ingestion
  cutoff, revision, freshness, continuity, quality, and lineage are proven.
  Preserve `Q_UNPROVEN`, `NOT_VERIFIED`, missing cohort valuation, and missing
  historical PIT evidence as explicit non-eligible states.
- Safety boundary: do not change Objective or Forward formulas, weights,
  thresholds, PIT rules, or missing-data behavior. Do not treat provider
  completion as scoring eligibility.
- Operational status: local implementation and verification only. This phase
  made no provider request, outcome or performance claim, commit, push, cloud
  resource, scheduler activation, or deployment.

## 2026-07-28: Refuse provider work that cannot recover the frozen cohort

- Decision: expose a versioned, read-only eligibility-recovery status derived
  from a sealed READY snapshot and PostgreSQL V1-V17 evidence.
- The preflight reports exact missing Objective factor operands, independent
  freshness, blocker categories, persisted-evidence reuse, and the maximum
  eligible count after any approved request plan.
- Current EODHD fundamentals cannot prove missing discrete-quarter or TTM
  semantics by repeating the same endpoint, Yahoo prices cannot supply
  Objective fundamentals, and neither route supplies historical PIT FCF-yield
  evidence.
- Because the approved bounded routes cannot reach the frozen minimum cohort
  of 20, return `BLOCKED_COHORT_UNREACHABLE` with an empty request plan and
  execute zero provider requests.
- Do not read historical generated artifacts at runtime and do not weaken
  formulas, PIT rules, cohort thresholds, or explicit missing states.

## 2026-07-29: Separate Objective coverage from non-rankable universe members

- Decision: version the corrected PostgreSQL replay as
  `objective-current-gate-replay-v1.1.0`.
- Keep all 66 members in the derived immutable snapshot, but write Objective
  `coverage_result` rows only for the 55 members whose snapshot membership is
  `INCLUDED`.
- Preserve the 11 reference-only or excluded members through immutable
  membership, membership reason, and Market Intelligence `NOT_APPLICABLE`
  views. Do not manufacture a market-cap cohort merely to satisfy the V8
  coverage-row constraint.
- Reuse V1-V17. This correction does not justify V18 because the V8 table
  remains valid for the population to which the Objective model applies.
- Version batch, snapshot, run, request, and manifest identities so the
  corrected replay cannot conflict with the retained v1.0 evidence chain.
- Preserve the previously created v1.0 snapshot and run as append-only,
  non-authoritative historical evidence.
- Require a current market-cap observation for every `INCLUDED`
  `INSUFFICIENT_DATA` member. Missing market cap remains a transactional stop;
  it is never replaced with zero or a guessed cohort.
- Authorize no implicit network work. The remaining 11-security Fundamentals
  repair is a separate bounded operation and requires the ignored local
  `EODHD_API_KEY`.

## 2026-07-29: Add historical time-slice validation without weakening PIT

- Decision: add `HISTORICAL-DECISION-QUALITY-VALIDATION-v1.0.0` as a pure
  offline evaluator that measures whether frozen deterministic ranks
  discriminate later relative returns across repeated historical cutoffs.
- Accept imperfect historical data only through explicit `PIT_VERIFIED` or
  `CONSERVATIVE_LAG` evidence modes. Conservative assumptions can support a
  directional engineering result but cannot be relabeled strict PIT.
- Keep current-universe retrospective runs explicitly survivorship-limited.
  Only dated historical membership plus verified PIT evidence can reach the
  strongest historical conclusion.
- Require next-session outcomes, costs, benchmark-relative returns, coverage,
  rank information coefficient, top-minus-bottom spread, chronological
  holdout partitions, and immutable versions.
- Do not paste the current Objective score onto an earlier date. Rebuild the
  score and normalization cohort from the evidence accepted at each slice.
- Keep historical diagnostics separate from prospective V11 events and
  continue prospective Forward Decision-Quality Validation.
- Reuse V1-V17. The offline evaluator does not justify V18 and does not change
  Objective, tactical, missing-data, PIT, or AI contracts.

## 2026-07-29: Treat the first expanded historical results as adverse evidence

- Freeze one deterministic 2014-2026 plan with six random dates per recent,
  medium, and older band plus a repeated month-end schedule.
- Keep the fixed 55-security primary/reserve denominator. Missing fundamental
  evidence removes a signal, not the security from coverage.
- Use adjusted OHLC only for total-return outcomes and raw historical close for
  price-to-share valuation. Bind both price bases, derived model inputs, score,
  policy, and source hashes into the controlled snapshot identity.
- Preserve the strict Objective historical gate as blocked. Do not paste a
  current score backward or relax cohort, duration, valuation, membership, PIT,
  or missing-data requirements.
- Permit `LONG-HORIZON-RESEARCH-v1.0.0` only as a separately labeled
  current-revision retrospective diagnostic with a conservative 150-day lag.
  It is not Objective Rating v1 and cannot become a PIT claim.
- Accept the observed tactical result as `MIXED_OR_UNFAVORABLE` and the
  approximate long-horizon rank result as `UNFAVORABLE`. Do not reinterpret
  positive top-bucket benchmark excess as a successful ranking when the
  bottom bucket performs better or has lower maximum drawdown.
- Do not tune the same model against the observed older holdout. Any algorithm
  change requires a new model version and new holdout or prospective evidence.

## 2026-07-29: Freeze Tactical v2.2 and Long Horizon v1.1 without reusing observed history as a holdout

- Replace the current tactical research contract with
  `TACTICAL-SIGNAL-v2.2.0`, which evaluates 1-week, 1-month, and 3-month
  continuation and mean-reversion theses independently and applies
  non-compensating falling-knife, chase, volatility, liquidity, and event-risk
  gates.
- Add `LONG-HORIZON-RESEARCH-v1.1.0` as a research-classification contract that
  separates company quality, financial strength, capital allocation,
  valuation and entry, expected-return range, permanent-loss and downside
  risk, sector-relative evidence, and confidence.
- Do not authorize a default Long Horizon ranking score. A good company and an
  attractively priced security are separate conclusions.
- Bind both models to immutable freeze records, source hashes, the validation
  governance contract, six-benchmark protocol, cost policy, and observed
  evidence cutoff.
- Classify every prior Tactical v2.1 and Long Horizon v1.0 result as
  `DEVELOPMENT_OBSERVED`. Because those dates and outcomes were inspected
  before the new freezes, they cannot be called an untouched holdout.
- Keep AI narrative outside every deterministic score, risk gate,
  classification, eligibility decision, and outcome.

## 2026-07-29: Accept blocked historical terminals as the honest current-model result

- Require every historical run to account for the complete frozen population,
  including explicit `MISSING`, `NOT_APPLICABLE`, and `EXCLUDED` rows.
- Require cash, SPY, dated sector, equal-weight universe, pure-value, and
  pure-quality benchmark records. Missing benchmark evidence must not become
  zero, cash, or SPY.
- Use chronological folds, purge and embargo, non-overlapping formal outcome
  schedules, separately labeled overlapping diagnostics, dependent-outcome
  block bootstrap, realistic liquidity-sensitive costs, turnover, coverage,
  drawdown, downside, and benchmark-relative metrics.
- Accept Tactical v2.2 historical status `BLOCKED_BY_DATA`, with 55 `MISSING`,
  2 `NOT_APPLICABLE`, and 9 `EXCLUDED`. The terminal artifact SHA-256 is
  `43FCFCFB4066BDFCF530308C8B04DDC409B6D6E6CFDB4DA0098424A9A207B7A0`.
- Accept Long Horizon v1.1 historical readiness `BLOCKED_BY_DATA`, with the
  same complete-population 55/2/9 states and no computed score. The readiness
  artifact SHA-256 is
  `46352B1539D475F15ABA9B4E8CFE5D8E4E5D4E33AAB2313030578612F1563773`.
- Do not request provider data, relax missing-data or PIT rules, or produce a
  partial performance claim merely to avoid a blocked result.

## 2026-07-29: Implement Forward v2 contracts and defer its structured ledger to V18

- Implement local immutable contracts for dual-model decision snapshots,
  preregistration, enrollment, and terminal outcomes at 5, 20, 60, 126, and
  252 completed sessions.
- Require exact model-freeze, governance, protocol, benchmark, cost, universe,
  source, and controlled-record hashes. Preserve a terminal row for every
  enrolled security and every benchmark; no missing return may become neutral.
- Separate operational completeness from model quality. With no real
  post-freeze snapshot or matured outcomes, model quality is
  `INSUFFICIENT_EVIDENCE`, not favorable or validated.
- Permit V16 `analytics.analytics_audit_event` only as an append-only,
  content-addressed handoff. It is not the canonical structured Forward v2
  ledger.
- Record that V11 cannot represent dual-model snapshots or 126/252-session
  outcomes, and V17 is a product projection rather than the Forward ledger.
- Require a separately approved append-only V18 for durable model freezes,
  daily decisions, enrollment, 5/20/60/126/252 outcomes, and superseding
  validation reports. Do not create V18 in this phase.
- Do not claim production routes, Java or frontend integration, a real
  prospective snapshot, provider traffic, commit, push, or deployment from
  the local contract implementation.

## 2026-07-29: Seal the first real local Forward v2 snapshot and stop before enrollment

- Seal READY snapshot `beaa9952-9852-4088-9dc3-92047824414b` from universe
  `market-intelligence-closed-test-us-v1.0.0` at
  `2026-07-29T02:57:08.988871Z`.
- Preserve the complete frozen population: 55 included, 2 reference-only, and
  9 excluded securities.
- Bind controlled artifact hash
  `sha256:b00971fee0500a8d02f22e28b5402b8db36322127dc6500b6e354c60eb9d839c`
  and Git-safe manifest content hash
  `sha256:6afcfa078cafaa16dacf302d9cd71a63c586f0f1d8b5a157eaf7f0aab3247b30`.
- Record V16 audit event hash
  `sha256:eff628373f0c4a354cf761e30387713db1a2cb5acb41ce7fef61862a2e034542`
  and require an exact replay to preserve the same event and evidence.
- Record zero provider requests and
  `aiUsedForDeterministicDecisions=false`.
- Keep `prospectiveReady=false` because the sole readiness blocker is
  `REQUIRED_BENCHMARK_EVIDENCE_UNAVAILABLE`. Do not enroll the snapshot or
  create outcome rows without that frozen evidence.
- Preserve model quality as `INSUFFICIENT_EVIDENCE`. A sealed decision is
  operational evidence, not a favorable model-quality result.
- Keep V16 as the audit handoff only. Do not add V18, Forward v2 public
  API or UI integration, commit, push, or deployment in this step.

## 2026-07-29: Seal Forward DQV v2 and benchmark v2.1 preregistrations

- Seal `FORWARD-DQV-PREREGISTRATION-v2.0.0` at
  `2026-07-30T03:12:23.237045Z`, strictly after both accepted model freezes at
  `2026-07-30T00:45:00Z`.
- Seal `FORWARD-BENCHMARK-PREREGISTRATION-v2.1.0` at
  `2026-07-30T03:12:23.237053Z`, strictly after its parent.
- Bind the complete 66-security universe and deterministic stable public IDs,
  PIT availability, independent freshness, explicit missing states, no neutral
  substitution, liquidity-sensitive costs, and the exact six formal benchmark
  families.
- Freeze distinct `DEVELOPMENT_OBSERVED`,
  `SEALED_HISTORICAL_VALIDATION`, and `PROSPECTIVE_FORWARD` evidence
  boundaries. Previously observed evidence cannot be upgraded.
- Record decision snapshot `beaa9952-9852-4088-9dc3-92047824414b` as
  ineligible because its `2026-07-29T02:57:08.988871Z` decision timestamp
  precedes formal preregistration. It cannot be bound or upgraded.
- Require every future prospective decision to be strictly later than
  `2026-07-30T03:12:23.237053Z`.
- Preserve immutable exact replay and reject any conflicting bytes. Generate
  the V16 audit-event payload only in memory; do not write PostgreSQL.
- Execute zero provider requests, scoring runs, database writes, commits,
  pushes, or deployments.

## 2026-07-29: Keep Objective benchmark families blocked after feasibility audit

- Preserve the formal Objective benchmark requirement at at least 20 scores
  and at least 80% of the 55 included securities, which means 44 securities.
- Record formal post-preregistration coverage as zero for both
  `PURE_QUALITY` (`QC-v1.0.0`) and `PURE_VALUE` (`UQ-v1.0.0`).
- Retain 32 pre-registration quality diagnostics only as gap evidence:
  32/55 is 58.18%, below the frozen threshold, and the evidence lacks a
  complete persisted score-level lineage chain.
- Keep value coverage at zero. Historical PIT FCF-yield evidence remains
  missing and no accepted `UQ-v1.0.0` score exists.
- Reuse V14 identity, V15 observations, V16 freshness, and V17 projections,
  but require V8 as the authoritative coverage, score, factor, and source
  lineage ledger. Do not treat V17 as a scoring substitute.
- Record a separate benchmark blocker: the frozen universe contains only SPY
  and XLK as reference-only securities, while benchmark v2.1 requires a
  reference-only sector benchmark assignment for every included sector.
- Do not relax Objective formulas, PIT rules, missing-data semantics, cohort
  thresholds, or the frozen universe to clear either blocker.

## 2026-07-29: Register the pre-outcome Forward benchmark v2.2 correction

- Preserve the original 66-security evaluated population, identity-binding
  hash, roles, costs, liquidity, prices, missing states, and model contracts.
- Replace the infeasible formal Objective-score dependency for `PURE_VALUE`
  and `PURE_QUALITY` with two source-independent mechanical current-snapshot
  rules: EBITDA divided by positive enterprise value, and gross profit TTM
  divided by positive revenue TTM.
- Require same-unit, same-currency, same-cutoff, hash-bound evidence; retain
  valid negative numerators; reject missing, stale, invalid, or conflicting
  inputs without neutral substitution.
- Keep the 44-of-55 coverage gate. Rank only `VALID` candidates, select
  `ceiling(valid_count * 0.20)`, and use ascending `publicSecurityId` to break
  ties. This yields 9 selections at 44 valid members and 11 at 55.
- Record existing cache support as diagnostic 42/55 for both rules. Register
  v2.2 as `DATA_PENDING`; do not construct benchmarks or results.
- Add a separate SPY plus 11-sector-ETF reference universe. Reuse the frozen
  SPY and XLK IDs and generate new stable IDs only for the ten new references.
- Freeze an all-55 EODHD Fundamentals preflight at 55 attempts, configured
  weight 550, retry zero, with network execution not authorized.
- Bind and preserve the v2.0/v2.1 preregistrations and seals. Prohibit upgrade
  of the earlier `beaa9952` decision or any legacy result.
- Seal v2.2 strictly after v2.1 and require a v2.2 readiness adapter. Execute
  no provider request, score, database write, commit, push, or deployment.

## 2026-07-29: Accept the bounded Forward benchmark v2.2 input refresh

- Accept exactly one completed post-freeze EODHD Fundamentals capture for the
  55 included securities under run
  `20260730T041722Z-02f8ddea2f6e`.
- Bind the capture to the immutable v2.2 candidate policy, preregistration, and
  seal. Preserve the original 66-security identities and roles.
- Record 55 completed physical attempts, configured weight 550, zero failed
  responses, zero retries, 55 normalized payloads, and 55 checkpoints.
- Keep all provider values and raw responses in Git-ignored controlled
  storage; retain only statuses, identities, lineage hashes, and selected
  identities in Git-safe artifacts.
- Accept full 55-of-55 current input coverage for both frozen mechanical rules
  and the resulting 11-member valid-only top-quintile candidate sets.
- Do not interpret candidate membership as a score, rating, recommendation, or
  return result.
- Keep full benchmark construction blocked until synchronized price,
  liquidity, transaction-cost, and external-reference evidence is available.
- Do not enroll, calculate outcomes, write PostgreSQL, commit, push, or deploy
  in this step.

## 2026-07-29: Add a strict v2.2 benchmark and successor-readiness adapter

- Preserve the immutable v1 and v2.1 construction and readiness contracts.
- Require exact v2.2 preregistration, seal, input-capture, coverage,
  candidate-policy and external-reference hashes.
- Require all six formal benchmark families on one completed session with
  validated prices, action reconciliation, decision-time ADTV, frozen costs
  and complete source hashes.
- Preserve the SPY, sector, equal-weight and momentum mechanics from v2.1.
  Construct v2.2 pure value and pure quality only from the frozen valid-only
  top-quintile candidate artifact, with at least 44 valid members and stable-ID
  tie-breaking.
- Permit the successor controller to return only `READY` or `BLOCKED`. It
  cannot enroll, score, calculate outcomes, call providers, write a database,
  or authorize automatic trading.
- Require a strictly post-freeze 66-security decision manifest and
  authoritative V18 acceptance evidence before `READY`.
- Reject any upgrade of the legacy `beaa9952` decision and do not treat the
  old V18-required audit as V18 acceptance.
- Record the current repository as `BLOCKED` on missing completed-session
  price evidence, six-family construction, post-freeze decision manifest and
  V18 acceptance evidence.

## 2026-07-29: Implement the append-only Forward DQV v2 outcome ledger

- Accept the Prospective Outcome Persistence Readiness Audit conclusion that
  V1-V17 cannot be reinterpreted as the typed Forward DQV v2 outcome ledger.
- Add exactly seven Python-owned `analytics.*` tables in V18 for enrollment,
  five maturities, outcome batches, security outcomes, six benchmark outcomes,
  typed path metrics, and quality reports.
- Preserve V1-V17 and create no `app.*` object.
- Freeze horizons at 5/20/60/126/252, with 126 diagnostic-only, and benchmark
  kinds at SPY, sector, equal-weight, pure momentum, pure value, and pure
  quality.
- Require full frozen-population identity, explicit terminal states, source
  and version hashes, gross/cost/net arithmetic, MAE, MFE, drawdown, and
  downside-capture evidence.
- Reject updates, deletes, missing-to-zero conversion, correction branching,
  and conflicting idempotent replay.
- Add Forward outcome v2.1 as a versioned extension. Do not change immutable
  v2.0 artifacts or claim that benchmark v2.2 `DATA_PENDING` has an outcome.
- Accept PostgreSQL 17 clean V1-to-V18 and V3/V12/V16/V17 upgrade matrices plus
  real repository exact replay, conflict, readback, and correction tests.
- Make no provider request, score, formula change, quality claim, commit, push,
  deployment, or cloud-resource change.

## 2026-07-29: Seal historical DQV v2.2 slices before outcome replay

- Classify every historical slice as `DEVELOPMENT_OBSERVED`,
  `DIAGNOSTIC_ONLY`, `formalGateEligible=false`, and
  `untouchedHoldout=false`.
- Seal seed `20260729`, six random completed sessions in each of the 3-9
  month, 1-3 year, and 4-10 year strata, and fixed 3/6/9/12/18/24/48/72/120
  month offsets before parsing any OHLCV outcome value.
- Permit controlled benchmark path diagnostics only where hash-verified
  evidence exists: SPY, current-universe equal weight, and price-only
  momentum.
- Keep dated sector, pure value, and pure quality benchmarks explicit
  `MISSING`; do not substitute SPY or zero.
- Reject Tactical v2.2 evaluation when historical event and dated sector
  evidence is absent. Reject Long Horizon v1.1 evaluation when historical PIT
  fundamentals, revisions, and membership are incomplete.
- Preserve every current-universe retrospective security as an explicit
  `MISSING` model outcome. Do not claim historical membership or remove
  unfavorable or unavailable observations.
- Keep derived licensed metrics in Git-ignored storage and retain only hashes,
  statuses, counts, and claim boundaries in Git-safe artifacts.
- Make no provider request, database write, parameter change, score, commit,
  push, or deployment.

## 2026-07-30: Accept offline Forward DQV infrastructure without claiming validation

- Accept V19 and `FORWARD-DQV-ENROLLMENT-v2.1.1` as the production chronology
  boundary: `decisionAsOf <= sealedAt <= effectiveEntryOpen`. Preserve
  v2.1.0 only as immutable history and reject its production writes.
- Accept Gate H, the maturity-to-statistics adapter, and the Forward DQV
  statistics engine as `IMPLEMENTED_OFFLINE`. Their contracts cover all frozen
  horizons, six benchmarks, cost and path-risk evidence, timing and
  expected-return evaluation, Holm-adjusted inference, strata, and typed
  AI/human provenance.
- Do not treat a migration acceptance, fixture, preflight, unit test, or
  historical diagnostic as prospective execution or model-quality evidence.
- Keep target-session capture and natural maturity `BLOCKED_BY_TIME`; keep the
  real 66 inputs, six benchmarks, immutable per-security decision values,
  decision-session index, liquidity, and formal Gate H evidence
  `BLOCKED_BY_EVIDENCE`.
- Record real model execution, snapshot creation, v2.1.1 enrollment, repeated
  cohort accumulation, and statistical evaluation as `NOT_EXECUTED`.
- Retain the Gate Z terminal truth
  `CRITICAL_BLOCKED_NOT_VALIDATED`. Tactical v2.2 and Long Horizon v1.1 remain
  `NOT_VALIDATED` until naturally matured prospective evidence supports an
  honest terminal conclusion.

## 2026-07-30: Require horizon-specific evidence for repeated-date cohorts

- Accumulate repeated prospective decision dates only through
  `FORWARD-DQV-ENROLLMENT-v2.1.1`; reject v2.1.0 and any changed same-date
  replay.
- Bind every date to the preregistered exact-66 stable UUID population,
  universe, model freezes, benchmark contract, cost policy, and V19
  chronology.
- Treat decision-time terminal counts as planning evidence only. Calculate
  eligibility from per-security matured outcomes separately for
  5/20/60/126/252 completed sessions.
- Require at least 80% coverage, 100 assessed security decisions, two
  distinct dates, at least two horizons of matured calendar span, and a
  horizon-specific purged/embargoed independent schedule.
- Do not count overlapping dates as independent observations. Keep 126
  sessions diagnostic-only.
- Reuse V18/V19 persistence for read-only cohort input. Do not add V20 merely
  to prepare a derived cohort plan.
- Keep formal artifact generation blocked until a versioned superseding V19
  acceptance binds the final additive v2.1.1 repository source. Do not
  overwrite or bypass the old immutable V19 acceptance.

## 2026-07-30: Seal deterministic post-freeze results once

- Produce one content-addressed controlled result payload per stable UUID from
  the same Tactical and Long Horizon execution pass.
- Bind every payload directly to both model-freeze artifact hashes, the
  post-freeze row, classification, inputs, results, evidence, decision cutoff,
  completed session, and source snapshot.
- Define `inputEvidenceAvailableAt` as input chronology, never as output seal
  time.
- Let the snapshot, post-close orchestrator, and maturity statistics adapter
  consume the same sealed output set. They must not rerun model formulas.
- Keep deterministic result values in controlled Git-ignored storage and the
  Git-safe manifest limited to identities, states, reasons, and hashes.
- Keep production blocked until real exact-66 model inputs/classifications and
  a controlled benchmark constituent/weight ledger are available.

## 2026-07-30: Read naturally matured Forward DQV paths without a new migration

- Discover due schedules only from hash-verified
  `FORWARD-DQV-ENROLLMENT-v2.1.1` and official completed-session evidence.
- Reject legacy v2.1.0 enrollments, natural-day fallback, nearest-session
  substitution, missing-state imputation, and unsealed benchmark membership.
- Load validated total-return-adjusted prices, action reconciliation, and
  decision-time ADTV only from existing persisted analytics evidence.
- Require exactly six benchmark paths. Use SPY through the same stored path
  rules and load synthetic benchmarks only from a future sealed
  constituent/weight ledger bound by reference and hash. Keep them explicitly
  `MISSING` while that ledger is absent.
- Use V19 for due discovery and the existing V18/V19 outcome lineage. Do not
  add V20 for a read-only adapter.
- Keep 126 sessions diagnostic-only and preserve append-only outcome
  correction lineage.
- Permit only manual read-only execution with an immutable request, exclusive
  lease, hash-verified checkpoints, exact replay, and zero provider requests,
  database writes, model runs, or outcome calculations.

## 2026-07-30: Evaluate model usefulness without an accuracy-tuning loop

- Tactical v2.2 and Long Horizon v1.1 validation targets measurable decision
  usefulness rather than perfect prediction accuracy.
- A frozen version is evaluated once under its preregistered historical plan.
  An unfavorable or imperfect result does not trigger repeated tuning on the
  same observed outcomes.
- A successor requires a demonstrated implementation or methodology defect, a
  justified missing factor, or evidence of a systematically harmful design
  assumption, followed by later walk-forward or prospective evidence.
- Tier 1 current-universe retrospective evidence must be executed and labeled
  with its survivorship, current-classification, and non-PIT limitations; those
  limitations reduce the claim ceiling but do not justify skipping all model
  value assessment.
- The main controller must decompose independent validation work into bounded
  project tasks and independently accept their evidence before advancing.
- Engineering tests prove implementation behavior, not investment-model value.

## 2026-07-30: Activate Forward DQV on V20 without claiming real evidence

- Accept V20 as the append-only successor for dated per-security sector
  bindings, benchmark variants and holdings, holding-level nonlinear costs,
  typed benchmark outcomes, human-decision evidence, and the separate
  portfolio-suitability boundary.
- Treat the controlled six-family ledger and decision-controlled composite as
  implementation-ready, but do not infer that a real 66-security ledger or
  composite has been executed.
- Supersede the stale
  `CONTROLLED_BENCHMARK_CONSTITUENT_LEDGER_NOT_IMPLEMENTED` blocker with
  `REAL_CONTROLLED_BENCHMARK_LEDGER_MISSING`.
- Preserve V18/V19 and all earlier preflights as immutable historical evidence.
  Use versioned V20 acceptance and successor preflight artifacts for current
  evaluation.
- Keep enrollment explicitly authorized and chronology-safe. Offline
  activation cannot run providers, scores, enrollment, outcomes, or maturity.
- Keep model labels unchanged, human decisions post-model and append-only,
  portfolio suitability `NOT_ASSESSED_BY_MODEL`, and automatic trading
  prohibited.

## 2026-07-30: Close the frozen historical validation pass without retuning

- Accept the Tactical v2.2 Tier 1 statistical closeout as the terminal
  retrospective result for the frozen version.
- Label 5-session ranking `NOT_VALIDATED`; label 20- and 60-session ranking
  `PARTIALLY_SUPPORTED` only as constrained diagnostic evidence because the
  key ranking and excess-return intervals include zero.
- Keep every Tactical entry-timing horizon `NOT_VALIDATED` because no
  executable entry episode could be established from the available
  historical evidence.
- Keep Long Horizon v1.1 company quality, security attractiveness, expected
  return, and downside risk `NOT_VALIDATED` at 252, 504, 756, and 1,260
  sessions because no complete PIT target input was reconstructed.
- Do not start another observed-outcome optimization loop. A successor model
  requires a documented defect or new preregistered evidence and must be
  evaluated on later walk-forward or prospective observations.
- Distinguish these historical labels from Forward validation. V20 is ready
  as infrastructure, while real enrollment and naturally matured outcomes
  remain unexecuted.

## 2026-07-30: Accept Practical Tier-1 evidence without replacing strict PIT validation

- Execute frozen model scores against hash-verified current-revision history
  when strict PIT history is unavailable, rather than treating engineering
  readiness as model-value evidence.
- Keep the claim ceiling at current-universe retrospective evidence with
  survivorship and provider-revision risk. Do not relabel it as an untouched
  holdout, strict PIT backtest, or proof of future returns.
- Retain all numerical Tactical and Long Horizon retrospective outputs as
  controlled local evidence. Public Git records only value-free manifests,
  hashes, versions, counts, evidence labels, and limitations.
- Do not infer validated score ordering or future performance from
  retrospective development evidence.
- Keep target-level missing and abstention states explicit; no default
  aggregate Long Horizon rank is authorized.
- Use non-overlapping April decision blocks for primary long-horizon
  statistics; retain October and dense overlapping slices as descriptive
  diagnostics only.
- Do not tune model weights to improve these observed results. Continue
  prospective Forward Decision-Quality Validation for independent evidence.

## 2026-07-30: Freeze Dual-System Architecture Contract v1

- Decision: adopt `dual-system-architecture-v1.0.0` as a separately named
  contract milestone rather than reusing the legacy Phase 0 label.
- Systems: keep Fundamental Value Investment and Quantitative Trading
  independent; the Unified Portfolio/Risk View consumes immutable outputs and
  never averages their scores.
- Sleeves: use `LONG_TERM_CORE` and `QUANT_TRADING`. The same security may
  appear in both, but holdings, cash, basis, thesis, exits, constraints,
  benchmarks, risk, and attribution remain isolated. Cash transfers require an
  explicit human decision.
- Value boundary: retain central fair value and a fair-value range, emphasize
  range and margin of safety, and return a cap rather than a final weight.
- Quant boundary: v1 is US-equity, daily, completed-session, long-only research
  without leverage, shorting, options, brokerage orders, or execution.
- Compatibility: preserve `BUYING_OPPORTUNITY` as legacy long-term valuation
  evidence and use `VALUATION_OPPORTUNITY` as the successor name. Preserve
  legacy public market-data APIs until a separately approved replacement.
- Evidence: provider identity is audit provenance, never a scoring input.
  Freeze strict identity/chronology, domain-tolerant numeric, and approximate
  historical research classes. Tolerances are field-specific, versioned, and
  evaluated only after semantic alignment. Approximate evidence cannot be
  promoted to strict PIT or sealed prospective evidence.
- Provider boundary: models consume canonical concepts, not provider names or
  native fields. Provider fallback is deterministic and versioned, never
  selected for a favorable score.
- Safety: preserve explicit conflicts/missing states, claim ceilings, AI
  narrative-only isolation, immutable human decisions, and no automatic
  execution.
- Scope: this freeze adds no migration, scoring/PIT change, live/provider
  request, cloud resource, deployment, or Task 1 implementation.

## 2026-07-30: Start Unified Market Data and Evidence Foundation v1 safely

- Decision: begin Task 1 with a migration-free deterministic evidence-selection
  kernel over the accepted Dual-System Architecture Contract v1.
- Preflight: the active checkout is detached at `57fa7ed`, equal to
  `origin/main`, with migration head V17 and the accepted Phase 0 changes
  uncommitted.
- Migration boundary: do not claim V18. Reachable snapshot commit `87e2a88`
  already assigns V18 through V21 to Forward Decision-Quality and portfolio
  responsibilities. V22 is separately reserved for the future Task 1
  successor and has not been created. That successor requires an explicit
  integrated upgrade path before implementation.
- Contract boundary: require durable identity tuples, completed-session
  chronology, raw/normalized/derived separation, provider lineage, versioned
  deterministic fallback, explicit freshness/conflict states, and
  specialized-model applicability.
- Raw-data boundary: licensed payloads remain in Git-ignored private storage;
  Git-safe contracts contain only allowed manifests, references, and hashes.
- Safety: selection never consumes scores or provider-native fields, never
  upgrades evidence claims, and does not change formulas, sleeve isolation, AI
  isolation, human control, or execution prohibitions.
- Scope: local code, fixtures, documentation, and offline tests only. No
  provider request, migration, cloud resource, commit, push, or deployment.
- Stage 2: add strict canonical contracts for prices/adjustments, corporate
  actions, fundamentals/periods, classifications, dated market/sector
  benchmarks, and engine-derived liquidity. Reuse V1-V17 and bind derived
  outputs to parent evidence hashes without adding a table.

## 2026-07-30: Adopt curated V18-V21 lineage without reinterpreting V21

- Evidence decision: V21 application or publication cannot be proven. Preserve
  the historical V18-V21 versions, contents, and checksums exactly rather than
  rewriting or reusing any of those migration numbers.
- Adoption boundary: copy only the reviewed V18, V19, V20, and V21 migration
  SQL and necessary PostgreSQL acceptance assets from reachable commit
  `87e2a88`; do not cherry-pick its larger snapshot.
- Acceptance-asset boundary: byte identity applies to the four migration SQL
  files. The V21 acceptance asset was later strengthened as test-only coverage
  for five append-only tables and is intentionally not claimed to remain
  byte-identical to the snapshot.
- V19 safety: retain its intentional refusal when a v2.1.0 enrollment already
  exists. Do not weaken the refusal to make an upgrade pass.
- V21 boundary: classify V21 as legacy and unwired. Its `CORE` and `TACTICAL`
  lanes are not `LONG_TERM_CORE` and `QUANT_TRADING`, and no current
  application contract may bind them to Dual-System Architecture Contract v1.
- Successor: reserve the not-yet-created V22 for a separately approved
  append-only Task 1 persistence design. Never reinterpret V21 as that design.
- Acceptance: require exact migration-blob verification and dedicated clean
  V1-to-V21, V17-to-V21, empty V18-to-V19, populated-v2.1.0 V18-to-V19
  refusal, V19-to-V21, V20-to-V21, and V21 schema/immutability paths.
- Static acceptance detail: continue the empty V18 path through V21; require
  the exact V19 refusal reason and unchanged V18 data/constraints; seed
  representative V19 and V20 rows before later migrations and verify their
  hashes afterward; and prove both update and delete rejection for all five
  V21 append-only tables and trigger bindings.
- Scope: database migration lineage, database acceptance assets, and
  documentation only. No application wiring, provider request, production
  database write, commit, push, or deployment.

## 2026-07-30: Implement V22 Unified Market Data and Evidence persistence

- Decision: use V22 as the append-only analytics-owned successor for Unified
  Market Data and Evidence Foundation v1 after accepting the exact V18-V21
  lineage.
- Legacy boundary: preserve V18-V21 byte-for-byte. V21 remains legacy and
  unwired; its `CORE` and `TACTICAL` lanes are not Dual-System Architecture v1
  sleeves and are not referenced by V22.
- Persistence: store hierarchical stable identity, completed-session
  calendars, private raw-manifest lineage, normalized/derived canonical
  evidence, ordered selector policies and immutable results, and
  classification-bound model applicability.
- Correction boundary: all V22 tables are append-only. Later evidence
  revisions must supersede the latest same-stream predecessor with monotonic
  chronology; model-applicability corrections also use explicit supersession.
- Aggregate boundary: derived parents, selector provider priorities, and
  selector candidates/results/rejections use explicit immutable seals.
  Transaction-level locks serialize child insertion with sealing, so late
  inserts cannot mutate an effective aggregate. Every supplied selector
  candidate, including request-mismatch evidence, must receive either the
  selected role or a deterministic rejection reason.
- Safety: non-valid evidence cannot carry canonical values; derived evidence
  requires sealed parent IDs and hashes; liquidity parent count, distinct
  completed sessions, and window end must match the canonical declaration;
  selected evidence must satisfy cutoff, freshness, conflict, ambiguity, and
  requested-field rules; canonical data cannot carry provider-native or
  deterministic score fields.
- Non-valid derived boundary: a non-`VALID` engine-derived liquidity envelope
  is an explicit zero-parent record. It retains derivation lineage, state, and
  reason, but cannot carry canonical values, parent references, parent rows, or
  a parent seal. Only `VALID` derived evidence seals parents.
- Canonical time and selector precedence: normalize every instant to UTC `Z`
  for wire serialization and hashing. After cutoff, dependent-conflict, and
  freshness checks, preserve an explicit non-`VALID` state/reason before
  evaluating tolerance or domain mismatch.
- Conflict shape: `affectedFactors` is an array of nonblank strings. Null,
  blank, numeric, and object elements are rejected so malformed provider data
  cannot bypass dependent-field conflict handling.
- Calendar and routing boundary: completed-session dates must match scheduled
  local timestamps in the declared IANA timezone. Applicability routing must
  follow the frozen company-type map, carry a deterministic content hash, and
  supersede exactly the latest route with monotonic revision and chronology.
- Adapter: Python validates the frozen provider-neutral contract before write
  and after readback for evidence, complete selector aggregates, and
  applicability routing. Policy, request, result, and routing hashes are
  recomputed on read. Explicit parent IDs plus hashes replace unsafe
  hash-only lookup. Provider identity remains provenance and ordered fallback
  only.
- Acceptance: require clean V1-to-V22, V17-to-V22, prepopulated V21-to-V22,
  V19 refusal preservation, V18-V21 row/hash preservation, and negative
  ambiguity/binding/cutoff/hash/mutation/missing/score-leakage cases.
- Scope: no provider request, model formula, PIT or missing-state change,
  portfolio wiring, brokerage execution, cloud resource, commit, push, or
  deployment.

## 2026-07-30: Add migration-free internal V22 operational integration

- Stage 3B acceptance: record only the controller's bounded PostgreSQL 17
  evidence. The exact V1-to-V22 matrix reported
  `Database migration acceptance passed.`, `TEST_EXIT=0`, and container exit
  code zero. Two typed tests passed on a fresh schema-only V22 database, and
  the rejection test passed alone on another fresh database. Independent
  relational and Python/persistence audits found no residual blocker.
- Internal query boundary: add versioned FastAPI contracts for selecting from
  persisted evidence IDs, reading a sealed selector aggregate, and resolving
  the single unsuperseded applicability route for a company and routing
  version. These endpoints are internal-only and do not replace Spring Boot
  public APIs.
- Replay boundary: derive selector request identity from canonical content.
  An exact duplicate loads and revalidates the existing sealed aggregate;
  conflicting uniqueness failures remain errors. Result hashes bind request
  and policy identity, selector output, and the full deterministic rejection
  map, preventing collisions between distinct requests with equal outcomes.
  A fully verified exact HTTP replay returns 200. A request identity that
  resolves to incomplete, invalid, unreadable, or mismatching durable state
  returns the stable 409 integrity contract; clean malformed input remains
  422.
- Refresh boundary: bind canonical V22 persistence to the existing execution
  lease, immutable journal, content-hashed checkpoint, and resume controls.
  Deterministically project the existing daily refresh plan into canonical
  adapter requests and preserve its shared price-transport identity. Request,
  item, run, plan, and checkpoint identity binds the complete durable security
  and completed-session context. Exact canonical evidence replay reuses its
  existing immutable row; conflicting reuse fails closed.
  Fake adapters prove duplicate invocation, partial failure recovery, and
  `UNKNOWN` fail-closed behavior. FastAPI startup performs no adapter fetch.
- Provider boundary: Yahoo, EODHD, and future replacements implement one
  provider-neutral adapter contract. Native field names and licensed payloads
  terminate inside adapters; downstream selectors and models receive only
  canonical evidence concepts and Git-safe lineage. Adapter success is
  nonempty and UUID-unique, every envelope is strictly reparsed, and daily
  overlap/backfill evidence must fall within the request range whose end is
  the completed session. Corporate actions bind `effectiveDate`,
  fundamentals use snapshot/as-of semantics by binding requested `metricCode`
  and requiring `periodEnd <= endDate` without treating `startDate` as a
  fiscal-period lower bound, and classification uses explicit field mapping
  with snapshot semantics: `effectiveFrom` may predate `startDate` but not
  exceed `endDate`. Non-VALID evidence uses local `effectiveAt` scope without
  fabricating canonical data; fundamental and classification absence may
  predate `startDate` but not `endDate`, while event-range absence remains
  bounded on both sides.
- Fail-closed domain boundary: Stage 3C provider adapters reject unimplemented
  domains by default. Market benchmark, sector benchmark, and liquidity
  evidence must use a separately implemented governed adapter or engine path;
  listing one of those domains in a descriptor does not authorize pass-through.
  Request field collections and descriptor domain collections must be immutable
  tuples, and descriptor members must be canonical `EvidenceDomain` values.
- Retention decision: defer V23 for the MVP. V22 is sufficient for immutable
  Git-safe raw lineage and private storage references but does not claim
  governed physical raw-payload deletion. A future V23 is required only if the
  product owns retention/deletion governance, including policy binding,
  deadlines/jurisdiction, legal holds, append-only disposition events, proofs,
  and chain cardinality. Stage 3C performs no deletion and creates no V23.
- Verification: the final Stage 3C adapter module reported `33 passed`, and
  Ruff passed. A fresh disposable PostgreSQL 17 database migrated V1-to-V22
  from the final deep-immutability snapshot passed all three typed
  Python/PostgreSQL integration tests in 5.05 seconds and was removed. The
  complete migration, upgrade, refusal, base, and advanced matrix had already
  passed on the same unchanged V22 schema. Independent relational and
  Python/provider/refresh/persistence/API audits reported PASS with no residual
  blocker. This is bounded test evidence, not business-database deployment or
  provider execution. A broader run found five unrelated generated-artifact
  hash-chain failures, and those dated artifacts were not rewritten.
- Scope: no provider request, public API replacement, business-database
  deployment, scoring/PIT/missing/conflict change, portfolio or brokerage
  operation, cloud resource, commit, push, or deployment.

## 2026-07-31: Keep licensed market-data derivatives out of public Git

- Treat access to a personal-use market-data API as insufficient evidence of
  redistribution or public-display rights.
- Keep raw provider payloads, provider-native values, reconstructed paths, and
  numeric performance derivatives in Git-ignored controlled storage.
- Publish only code, methodology, synthetic fixtures, hashes, versions,
  timestamps, counts, explicit evidence states, and value-free manifests.
- Make controlled-data tests skip explicitly in clean clones while preserving
  pure contract, formula, chronology, and hashing tests.
- Quarantine prior numeric historical artifacts locally and publish future
  Tactical manifests under separately named value-free paths.
- Require a separate commercial license review before any external product
  displays market data or derived analytics.

## 2026-07-31: Freeze Fundamental Value Investment System v1

- Scope the generic `FUNDAMENTAL-VALUE-v1.0.0` model to mature nonfinancial
  United States listed operating companies. Specialized, benchmark, and
  insufficient-history cases fail closed without generic fallback; NBN is an
  explicit bank regression case.
- Freeze FCFF DCF, normalized Owner Earnings, and Earnings Power as primary
  methods. Comparable valuation remains a non-controlling cross-check.
- Aggregate eligible methods with a preregistered weighted median and ordered
  weighted quantiles. Prohibit unrestricted minimum/maximum envelopes and
  method dominance.
- Preserve missing advanced evidence explicitly. It lowers the claim ceiling
  and risk cap and blocks valuation when missing refinancing evidence is
  material.
- Limit the model to 0, 1, 2, 3, or 5 percent `LONG_TERM_CORE` cap ceilings.
  The result is never a final portfolio weight and requires a human decision.
- Reserve append-only V23 for Fundamental Value persistence without
  reinterpreting V1-V22 or V21 lane semantics. Exclude raw retention, deletion,
  and legal-hold governance; any future approved raw-governance migration uses
  the next available version after V23.
- Require separately accepted historical time-slice validation before
  prospective Forward DQV readiness. Permit an honest `NOT_VALIDATED` result.
- Keep AI narrative-only, Quantitative Trading independent, the repository at
  No License, and all provider, cloud, deployment, push, and brokerage actions
  outside this stage.

## 2026-07-31: Repair Fundamental Value Stage 2 domain and dimension gaps

- Bind `fundamental-value-formulas-v1.1.0` and
  `fundamental-value-assumptions-v1.1.0` to fail-closed economic domains.
- Require every explicit and terminal growth scenario to exceed negative one
  before arithmetic, and convert Decimal/domain failures into explicit
  component-level `INVALID` results.
- Require nonnegative gross cash, debt, depreciation and amortization, and
  capital expenditures while retaining signed change in working capital.
- Implement the frozen separate capital-allocation-quality dimension over
  typed incremental ROIC, acquisition-discipline, and shareholder-distribution
  coverage evidence states. Stage 3 records the currently unsupported V22
  evidence responsibilities as explicit missing inputs.
- Propagate non-valid capital-allocation evidence without neutralization and
  allow its score to preserve or lower, never raise, the discrete risk cap.
- Keep the repaired core price-independent, `NOT_VALIDATED`, migration-free,
  network-free, and isolated from providers, AI, Quantitative Trading, public
  APIs, portfolio weights, and brokerage authority.
- Bind the normative decision fixture to the same formula and assumption-policy
  v1.1.0 constants as the pure core, and require a canonical parity regression
  so future shared-contract drift fails closed.

## 2026-07-31: Bind Fundamental Value assembly to sealed V22 evidence

- Accept only repository-rehydrated V22 selector aggregates and content-hashed
  applicability routing; never accept caller-provided metric values.
- Reverify selector request IDs/hashes, result hashes/replay, selected evidence
  IDs/source hashes/normalized hashes/revisions, full durable identity,
  calendar/session, cutoffs, states, conflicts, semantics, and versions before
  reading an operand.
- Route company type before operand assembly. Banks including NBN and every
  specialized, benchmark, or insufficient-evidence case remain unable to enter
  the mature-company generic path.
- Emit a deterministic Git-safe manifest containing identity, chronology,
  state/reason, evidence IDs/hashes/revisions, provider-schema/adapter lineage,
  the validated projection horizon, and model versions. Exclude canonical and
  licensed values, provider-native fields, raw payload/storage references,
  scores, ranks, weights, and actions.
- Do not broaden V22 persistence semantics to create missing Fundamental Value
  evidence. When the accepted V22 canonical domains cannot support an operand,
  emit an explicit missing derivation/policy-evidence requirement and prohibit
  core invocation.
- Keep V23, public/internal APIs, UI, AI narrative, Quantitative Trading,
  brokerage, provider execution, and deployment outside Stage 3.

## 2026-07-31: Repair Fundamental Value Stage 3 runtime trust boundaries

- Validate the projection horizon as an exact non-Boolean integer from three
  through ten years and bind it into every result and manifest hash.
- Require an exact immutable tuple of typed canonical selector-request IDs;
  reject mutable collections, wrong members, and noncanonical durable IDs.
- Validate every operand's selector domain, field, policy, layer, evidence
  class, normalization, and domain constraints before propagating any
  non-VALID state.
- Treat the repository Protocol as a trusted-adapter seam. Production evidence
  provenance comes from `EvidenceFoundationRepository`, whose PostgreSQL
  readback recomputes request/result/routing hashes and selector replay.
- Prove the boundary on a disposable V22 database, including successful exact
  readback, tampered-hash and missing-ID refusal, a direct cash operand, and an
  NBN bank route that exits before generic operand loading.
- Define provider-neutrality narrowly: provider-native fields, formulas,
  licensed values, raw payloads, and storage references are excluded from the
  engine and Git-safe manifest, while provider-schema and adapter versions
  remain required audit lineage.

## 2026-07-31: Add append-only Fundamental Value V23 persistence

- Use V23 only for `analytics.*` Fundamental Value assembly and deterministic
  assessment persistence. Do not reinterpret V1-V22, V21 lane semantics, or
  Spring-owned `app.*` responsibilities.
- Persist non-usable Stage 3 outcomes as first-class sealed records without
  numeric substitution or assessment children. Require the canonical ordered
  34-operand set for applicable mature companies and zero generic operands for
  specialized, not-applicable, and insufficient-evidence routes.
- Add an ordered relational operand-to-evidence parent set because derived
  operands may depend on multiple canonical evidence records. Bind durable
  IDs, hashes, revisions, chronology, exact direct-selector seals, and complete
  child cardinality rather than relying on JSON provenance.
- Rehydrate typed assemblies and assessments and recompute manifests, inputs,
  result hashes, version bindings, and deterministic core arithmetic. Permit
  exact idempotent replay only; reject conflicting identity reuse, incomplete
  seals, changed arithmetic, update, and delete.
- Treat complete synthetic valid fixtures as persistence-mechanics evidence
  only. They do not close the real V22 mature-company operand blocker, validate
  the investment model, or authorize ranking, final portfolio weights,
  brokerage, AI decisions, or provider execution.
- Keep raw retention, deletion, jurisdiction, deadline, legal hold, and
  disposition governance outside V23. Any later approved responsibility uses
  the next available append-only migration.

## 2026-07-31: Harden the V23 private value and semantic-writer boundary

- Keep the Stage 3 Git-safe manifest free of licensed values, and add a private
  deterministic seal over exact operand Decimal values or non-valid reasons,
  ordered evidence parents, output-contract versions/hashes, complete versions,
  durable identity, session, and cutoffs. Use this seal in assembly identity.
- Replay daily-price and direct-fundamental values against the selected V22
  canonical record. Require preregistered derivation/policy-evidence output
  bindings over ordered parents; arbitrary valid evidence is not a derived
  output.
- Freeze applicable mature assemblies at the exact 34-operand, 31-required and
  3-optional tuple, with core authorization equivalent to complete valid typed
  inputs. Specialized routes have zero generic operands.
- Freeze V23 assessments to `NOT_VALIDATED`, exact claim ceilings, and no more
  than 2 percent risk cap; limited advanced evidence is at most 1 percent and
  material refinancing uncertainty is zero.
- Scope revision identity and locking to the complete security/listing/share-
  class identity. Bind assessment identity to assembly identity so unchanged
  arithmetic may be republished under a distinct evidence-only revision.
- Canonicalize evidence timestamps to UTC instants and reject non-finite
  persisted numerics. PostgreSQL enforces relational structure and sealing;
  only the dedicated Fundamental Value writer may write V23, while the trusted
  Python repository performs exact Stage 2 formula replay.
## 2026-07-31 - Fundamental Value V23 producer governance repair

- Retract the earlier Stage 4 PASS candidate pending independent acceptance.
- Remove fabricated derived and policy parent-set economics. V23 and Python
  seed an empty production producer registry, so unsupported operands remain
  explicitly `MISSING` and no real assessment exists.
- Require any future production producer to arrive through an append-only
  governed contract plus a matching executable evaluator with exact ordered
  roles, semantics, currency, periods, chronology, and output replay.
- Permit only explicit `TEST_ONLY` executable contracts in disposable
  acceptance databases and injected test registries. Application writer roles
  cannot register or approve them.
- Preserve the private value seal, exact 31-required/3-optional authority,
  `NOT_VALIDATED` claim/risk limits, identity-scoped revision locking, and
  trusted Python arithmetic replay boundary.
- Require producer validation inside direct PostgreSQL backend load as well as
  repository load and backend insert. Empty-production-registry callers cannot
  rehydrate a disposable test-only-derived record.

## 2026-07-31: Publish Fundamental Value v1 through an ID-only service boundary

- Accept only durable V22 routing, classification-request, and operand-request
  IDs plus the frozen projection horizon at the internal FastAPI command.
- Derive security identity, completed session, cutoffs, evidence seals, and
  versions from the accepted V22/V23 repositories; caller-supplied values and
  results are forbidden.
- Return non-usable and specialized outcomes as explicit domain results, and
  reserve HTTP errors for malformed contracts, missing IDs, persistence
  conflicts, and service failures.
- Keep Spring Boot as workflow and public-contract owner through a strict
  client. Java does not reproduce formulas or query `analytics.*` tables.
- Treat Stage 5 as offline engineering readiness only. Real mature-company
  coverage remains missing and model evidence remains `NOT_VALIDATED`.

## 2026-07-31: Harden the Fundamental Value Stage 5 wire boundary

- Require raw `projectionYears` to be an integral JSON number from 3 through
  10 and every durable ID to be an exact canonical lowercase hyphenated UUID.
  Python internal malformed requests remain 422; Spring public malformed
  requests follow the established 400 policy.
- Map exact missing durable references to sanitized 404 responses, immutable
  or durable evidence-integrity conflicts to 409, and invalid analytics
  success bodies to a sanitized Spring 502. Do not expose database, provider,
  or raw upstream detail.
- Freeze state/reason parity: a `VALID` assembly has no reasons and each
  non-`VALID` assembly has stable nonempty reasons. Spring validates the exact
  Stage 3 routing outcome matrix, including specialized companies, benchmarks,
  and insufficient-history routes.
- Serialize every deterministic Decimal as the same finite ordinary base-10
  text used by Python hashes and V23 replay. Spring rejects exponent-form wire
  decimals and enforces the frozen FCFF terminal-value-share maximum of 0.80.
- Namespace only test policy identities whose contents vary between synthetic
  test seeds. Frozen production selector versions and V22 uniqueness remain
  unchanged, and the same disposable database must support sequential reruns.
- Keep Stage 5 as an implemented candidate pending master final acceptance.
  This hardening does not create a usable real-company assessment or an
  investment-validation claim.

## 2026-07-31: Add the Spring-only Fundamental Value workspace

- Add `/research/fundamental-value` as immutable decision readback by assembly
  ID. Next.js calls only the Spring public API and has no direct Python,
  PostgreSQL, provider, or internal analytics route.
- Advance only the current readback result to
  `internal-fundamental-value-result-v1.1.0`; retain the v1.0 command and the
  Stage 5 v1.0 fixtures as immutable historical acceptance evidence. Do not
  change formulas, V22/V23 semantics, or persisted economics.
- Carry the complete durable security identity, ticker assignment, ticker,
  MIC, identity currency, and completed session in result v1.1. Require Python,
  Spring, and Next.js to reject a returned assembly ID that differs from the
  requested assembly ID.
- Re-derive each usable assessment ID as UUIDv5 over the frozen assessment
  persistence version, assembly ID, and assessment content hash at the Python,
  Spring, and TypeScript boundaries. Reject a completed-session date later than
  the decision cutoff.
- Decode the public result with a strict TypeScript contract that preserves
  canonical IDs, explicit states, applicability, reasons, sealed timestamps,
  hashes, versions, and forbidden portfolio/brokerage authority.
- Replay the canonical assessment hash and reject unknown fields, coercion,
  alternate zero spellings, exponent decimals, invalid cutoff grammar or
  chronology, blank nested reasons, frozen condition drift, and claim,
  risk-cap, authority, or version drift.
- Bind the quality, resilience, conservative margin-of-safety, downside-risk,
  and central margin-of-safety condition observations to their corresponding
  exposed source values, and recompute each condition's `satisfied` state.
- Present usable valuation ranges and dimensions only when Spring supplies a
  sealed deterministic assessment. Present missing, specialized,
  not-applicable, and insufficient-evidence results without zero or neutral
  substitution.
- Show durable security and listing identity plus completed-session provenance,
  bind annualized expected return to the projection horizon, keep nested reasons
  visible, and format percentages without JavaScript Number conversion.
- Label the risk cap as a `LONG_TERM_CORE` ceiling rather than a final weight,
  keep `NOT_VALIDATED` visible, and include no guaranteed-return, autonomous
  trade, or brokerage language.
- Keep AI narrative absent. The workspace states that AI cannot alter the
  deterministic assessment, eligibility, valuation, ranking, cap, weight, or
  action.

## 2026-07-31: Accept the Fundamental Value Stage 6 workspace

- Accept Stage 6 after the offline Java 21 and Spring Boot 4.1.0 master runtime
  passed the 71-case focused Fundamental Value suite and the complete 138-case
  Spring suite with zero failures, errors, or skips. Maven reported
  `BUILD SUCCESS` in 21.963 seconds.
- Record the focused composition as 32 analytics-client, one architecture,
  three contract, eight controller, and 27 service cases. This includes exact
  durable-identity projection, malformed-identity refusal, all frozen-version
  value/omission mutations, and every root/nested authority toggle or omission.
- Mark Fundamental Value Stages 1 through 6 master accepted as offline
  engineering readiness. Preserve `NOT_VALIDATED`, the empty production
  producer registry, the mature-company V22 operand-coverage blocker, and the
  absence of any final-weight, brokerage, provider, deployment, or investment
  authority.

## 2026-08-01: Reject the Fundamental Value Stage 7 evidence interpretation

- Preserve C1-C8 execution, policy, intent, result, and final artifacts
  immutably, including the completed 203-request Yahoo acquisition and the
  favorable observed aggregates.
- Reject the Stage 7 evidence interpretation because the sealed predictor rank
  runs highest-to-lowest while the sealed return rank runs lowest-to-highest,
  making the positive rank-IC interpretation directionally inconsistent.
- Record the additional reproducibility blockers: no checked deterministic C8
  calculation runner, no complete per-security/date/horizon terminal registry,
  and no hash-bound participation-to-impact function in the C8 policy.
- Set the validation outcome to `BLOCKED_BY_PROTOCOL_DEFECT`, keep the model
  `NOT_VALIDATED`, prohibit post-outcome sign reversal or same-outcome tuning,
  and require a newly preregistered successor with a fresh validation boundary.
- Keep Stage 8 closed. The governing audit disposition canonical hash is
  `8C0610A47178CE54993E93B5926BDC94D05FF59E29A7B38B662AEC4E66C54385`.

## 2026-08-01: Close Stage 7 after the C9 protocol-repair confirmation

- Preserve C1-C8 unchanged and run one separately versioned C9 confirmation on
  nine presealed dates not calculated in C8.
- Correct only the deterministic ordinal-rank direction and add a checked
  runner, complete terminal registry, and hash-bound square-root cost function.
- Record that all frozen market-first numeric thresholds passed while strict
  high/middle/low ordering appeared on only 2/9 dates; set the terminal
  disposition to `MIXED_NOT_VALIDATED`.
- Keep the evidence ceiling at
  `DEVELOPMENT_OBSERVED_CURRENT_REVISION_APPROXIMATION`, the production model at
  `NOT_VALIDATED`, and prohibit any further retrospective iteration.
- Permit only migration-free Stage 8A readiness/preregistration work; do not
  enroll a real decision or claim forward support.

## 2026-08-01: Accept post-closeout C9 engineering replay reproducibility

- Preserve every currently immutable C9 artifact and do not recompute outcomes.
  Because pre-reseal registry/result artifacts and a C9 execution journal were
  not retained, cross-reseal numeric identity is
  `NOT_INDEPENDENTLY_VERIFIABLE_FROM_PRESERVED_ARTIFACTS`.
- Freeze the checked runner to an internal Decimal precision of 28 with
  `ROUND_HALF_EVEN`, independent of the caller's Decimal context.
- Require nonzero raw predictor and return variance before deterministic ordinal
  tie-breaking can produce an observed correlation.
- Record that the C9 policy's `UNCHANGED_C8` indirection is insufficient alone;
  bind the full exact threshold matrix in the append-only acceptance identity.
- Accept exact read-only replay of the 5,157-row registry and 27-row result under
  an intentionally different outer precision, plus exact final-summary and
  explicit-threshold evaluation.
- Treat this as engineering reproducibility only. Keep C9
  `MIXED_NOT_VALIDATED`, keep the model `NOT_VALIDATED`, and keep Stage 8A
  readiness-only.
- Bind all direct local replay calculation/provenance dependencies plus the
  CPython and Decimal/libmpdec runtime in the post-closeout identity. Record the
  original pre-outcome provenance as `FAIL_PARTIAL`; only current post-closeout
  engineering replay provenance may pass.
- Preserve both misleading immutable MDD field names, and append correctly
  signed median and worst deterioration diagnostics. The true worst
  deterioration is 3.94 percentage points and remains within the 5-point cap.
## 2026-08-01: Add narrow company-quality Forward enrollment readiness

- Decision: add append-only V24 readiness tables for a development-only,
  `NOT_VALIDATED` `COMPANY_QUALITY` prospective contract because V18-V23 cannot
  represent its population, predictor rows, and 252/504/756-session maturity
  schedule without reinterpretation or fabrication.
- Keep the real enrollment blocked. The controlled calendar ends on 2026-07-28,
  and current inputs lack contractual ingestion timestamps and durable security
  identities. Do not backdate C9 or use filesystem times and ticker-only identity.
- Keep network authorization false. A future current-calendar and evidence
  request matrix requires separate approval after exact identities, paths,
  weights, budgets, leases, journals, and checkpoints are sealed.
- Freeze V24 without singular decision-session or entry fields. The exact 191-row
  population uses 122 `XNYS` and 69 `XNAS` members, two matching completed-session
  children, and two separate `SCHEDULED_NOT_COMPLETED` planned-entry children.
  This engineering structure does not authorize a real enrollment.
- Grant the V24 semantic writer only the V22 raw-manifest `SELECT` privilege
  required by its security-invoker deferred validator. Preserve DML denial on
  raw manifests, normalized parents, and parent-role metadata, and prove a full
  role-switched enrollment commit in disposable PostgreSQL.
- Remove the redundant provider-normalized-parent `listing_mic` column. Durable
  listing ownership already determines the listing, and the enrollment member
  owns the independently validated MIC/session binding; a second unbound MIC
  claim would permit false audit metadata.
- Harden the V24 producer replay with exact common four-quarter factor periods,
  C5-compatible at-or-before ROIC balance boundaries, and nonnegative CAPEX on every
  parent row. Preserve the independent eight-quarter stability chains.
- Make every V24 hash/chronology date and timestamp finite, require ordered period
  bounds, and constrain admitted variable hash atoms to an injective delimiter-free
  grammar. Bind SQL producer arithmetic to the Python precision-28 half-even producer
  context while preserving the unchanged Stage 2 precision-50 scoring boundary.
- Accept the disposable runtime only on the exact 191-member fixture: 110 usable,
  81 explicit `MISSING`, 63 ordered parents per usable member, and 6,930 parent rows.
- Require exact lowercase SHA-256 grammar for every Python hash-bound reference,
  normalize timestamps to UTC before the whole-second check, and reject
  fractional-offset collisions before sealing.
- Canonicalize every V24 hash-bound PostgreSQL date as finite ISO `YYYY-MM-DD`.
  Prove a complete deferred-validator commit under `DateStyle='SQL, DMY'`, followed
  by exact typed readback and idempotent replay.
- Bound every V24 date and UTC instant to the shared Python/PostgreSQL AD range
  0001 through 9999 and reject BC, year-10000, nonfinite, fractional-second, and
  fractional-offset values before hashing or persistence.
- Make the initial-only revision contract explicit (`revision=1`, no predecessor),
  require evidence cutoff to equal decision cutoff, bind planned-entry dates to
  scheduled open/close UTC dates, reject whitespace-only hash atoms, and require
  unique terminal reason codes per member.
- Define hash-atom blankness with the identical six-character ASCII whitespace
  set in Python and PostgreSQL, bind every Python V24 string to its exact SQL
  character limit before hashing, require all eight CAPEX parents to be
  nonnegative, and require completed-session recording not to precede completion.
- Reject NUL at the Python hash-atom boundary because PostgreSQL text cannot
  represent it, without imposing broader Unicode restrictions. Bind each source
  revision to the positive PostgreSQL `INTEGER` range before evidence hashing.
- Mirror only schema-proven per-enrollment uniqueness for member identity,
  decision-session identity, V22 selections, and provider-normalized parents;
  preserve permitted shared issuer hierarchy and lineage/hash reuse. Require
  exact Python integer/boolean wire types and PostgreSQL `NUMERIC` digit limits
  before any V24 value is hashed or persisted.
- Require exact Python `UUID` instances for every UUID-bearing V24 wire field so
  PostgreSQL canonicalization cannot change previously hashed identifiers.
  Bound every source-parent value to `abs(value) <= 1e100`, preserving the
  economic formulas while keeping all replay intermediates inside PostgreSQL
  `NUMERIC` and the sealed Decimal arithmetic domain.
- Bound canonical source-parent fractional scale to 100 digits, admitting zero
  and nonzero magnitudes no smaller than `1e-100`. Use context-free Decimal
  magnitude and negation/order operations so ambient precision cannot bypass
  admission or change best-first predictor ranking.
- Queue deferred aggregate replay from all seven V24 child tables. Stamp each
  seal with a trigger-owned full `xid8`: creating-transaction children remain
  covered by the single header replay, while every later child transaction must
  recompute and match the immutable seal. Reject caller-GUC bypasses and deny
  semantic-writer mutation of concurrency provenance.

## 2026-08-02: Preserve the failed OpenFIGI canary and add a narrow successor alias contract

- Preserve the acquisition v1.2 production canary as terminal. It planned four
  OpenFIGI requests and 18 logical jobs, sent three requests, completed two,
  retained one HTTP 200 response-backed `FAILED` checkpoint, and did not send
  the fourth request. Retry remained zero and no transport outcome was unknown.
- Record the exact failure as a platform parser defect: OpenFIGI returned the
  valid raw share-class ticker `BF/B` for the frozen platform ticker `BF-B`.
  Do not classify this as authentication, rate-limit, provider-schema, or
  warning failure, and do not rewrite the old `FAILED` event as completed.
- Advance the Stage 8C acquisition, parser registry, parser, identity
  adjudication, canary review, and canary acceptance contracts append-only.
  Keep the projection top-level version and UUID namespace unchanged.
- Preserve raw provider tickers in wire and hash lineage. Allow comparison only
  when the raw ticker exactly equals the expected platform ticker, or replacing
  exactly one slash between uppercase alphanumeric share-class components with
  one hyphen exactly reproduces that already-bound expected ticker. Reject
  unbound aliases, multiple slashes, trimming, case folding, and dot rewriting.
- Require a new run ID, plan, preflight, authorization, and explicit network
  approval before a successor canary. Keep the remaining OpenFIGI phase, SEC,
  Yahoo, EODHD, evidence writes, V24 enrollment, portfolio actions, and label
  promotion closed.
- Preserve the original failure record even though it names the earlier
  identity-adjudication successor. Bind the exact current successor versions in
  a separate hash-sealed addendum.
- Treat the ISIN and CUSIP raw provider ticker as part of paired identity
  convergence even when each job independently maps to the same platform
  ticker. Require zero paired conflicts for canary acceptance.
- Rebuild the complete canary review from immutable checkpoints both when
  sealing acceptance and before dispatching any later acquisition request.
  Self-resealed review or acceptance objects are structural records, not I/O
  authority.
- Execute the separately approved v1.3 canary as exactly four OpenFIGI POSTs
  and 18 logical jobs with retry zero. Record four completed requests, no
  transport failure, no unknown outcome, five unique primary mappings,
  thirteen unresolved provider warnings, and zero paired raw-ticker conflicts.
- Reject that canary as `CANARY_REJECTED_13_UNRESOLVED`. Do not retry the same
  plan or authorize the remainder. Preserve that both `BF-B` jobs succeeded
  with raw `BF/B`, while every `XNAS` job was unresolved, as successor-design
  evidence rather than weakening the complete-pair acceptance rule.

## 2026-08-02: Reject the OpenFIGI v1.4 diagnostic without identity promotion

- Execute the independently frozen v1.4 diagnostic as two OpenFIGI POSTs and
  ten public-identifier jobs. Record two new HTTP 200 completions, retry zero,
  no failed request, and no unknown transport outcome.
- Reopen both private response checkpoints without sending another request.
  Bind the exact plan, authorization, response-body, terminal-event, review,
  receipt-set, diagnostic-decision, and storage-backed-decision hashes.
- Record four unique primary mappings, six ambiguous primary mappings, zero
  warnings/errors/no-primary results, two complete convergent pairs, and zero
  pair conflicts. Do not expose provider response values in Git.
- Reject the result as `DIAGNOSTIC_REJECTED_GATE_NOT_MET`. Preserve the frozen
  requirement for ten unique mappings and five complete convergent pairs; do
  not reinterpret ambiguity as identity evidence.
- Keep the result diagnostic-only. It authorizes no durable identity, remainder
  request set, evidence write, outcome access, or V24 enrollment. Operating-MIC
  ownership still requires SEC corroboration.
- Treat the user's broader future-provider authority as a separate controller
  basis. Any next provider execution still requires a new exact plan and cannot
  inherit authority from this rejected diagnostic result.

## 2026-08-02: Accept the OpenFIGI v1.5 US-composite engineering diagnostic

- Treat v1.5 as an append-only, post-v1.4 method repair rather than an
  untouched holdout. Preserve the rejected v1.4 result and its ambiguity.
- Execute the separately frozen v1.5 plan as exactly two OpenFIGI POSTs and six
  public-identifier jobs. Record two new completions, retry zero, no failed
  request, and no unknown transport outcome.
- Reopen both completed private checkpoints without sending another request.
  Bind the exact plan, authorization, live execution, response-body,
  terminal-event, review, receipt-set, replay-verification,
  diagnostic-acceptance, storage-backed-acceptance, and zero-send replay
  summary hashes.
- Record six unique primary mappings, zero warnings/errors/ambiguities/missing
  primary results, three complete convergent identifier pairs, and zero pair
  conflicts. Keep raw identifiers, FIGI values, and response bodies outside
  Git.
- Accept the frozen diagnostic decision as
  `US_COMPOSITE_DIAGNOSTIC_COMPLETE_CONVERGENT`, while retaining
  `diagnosticOnly=true`. Do not infer a durable security or listing identity,
  an operating MIC, or a validation-label improvement from this result.
- Keep the remaining OpenFIGI population, V22 writes, V24 enrollment, outcomes,
  and evidence-label upgrade unauthorized by this result. Require SEC
  operating-MIC corroboration, an exact target-database identity inventory,
  a forward-projection-v2 contract, and a V25 identity-authority ledger before
  any governed write. Do not reuse projection v1.
## 2026-08-12: Add the Quant Trading v1 synthetic portfolio simulator candidate

- Add a pure event-driven simulator with frozen open, intraday, and close
  ordering, whole-share sizing, cash and slot controls, and C9 costs.
- Bind READY Stage 1 provenance and the exact unrounded selection score; do not
  rank candidates by the two-decimal display score.
- Recompute execution ATR, SMA, and median dollar volume from consistent
  adjusted histories and require explicit action and terminal-event lineage.
- Keep equal-weight `NOT_OBSERVED` until its eligible population is sealed
  before outcomes. Keep production multi-MIC authority for Stage 3.
- Preserve `NOT_VALIDATED`, no automated brokerage, and no historical outcome
  access in this engineering stage.
# 2026-08-12: Quant Trading v1 historical validation remains NOT_VALIDATED

- Froze a two-track, outcome-blind Stage 3 protocol before calculating Quant
  Trading returns. The governed track is blocked by missing production identity,
  action, lifecycle, halt, and terminal-event authority. The weaker Yahoo
  adjusted-OHLCV current-survivor approximation is development evidence only.
- Ran immutable 25, 100, and 191-security batches without tuning. The 191-name
  result ended at USD 113,808.46 from USD 100,000 (1.13% CAGR), versus SPY at
  USD 438,691.69 (13.68% CAGR). Strategy MDD was -12.02% versus SPY -33.69%,
  but the return sacrifice, 31.38% win rate, and evidence limitations do not
  validate the strategy.
- Retain `NOT_VALIDATED`; do not optimize this frozen version against the same
  outcomes. Any successor needs a new preregistered identity and preferably a
  historical-membership/delisting-complete dataset or prospective evidence.

## 2026-08-12: Repair Quant Trading v1.1 manifest chronology before outcome access

- Preserve the unexecuted v1.1.0 protocol and its canonical hash as a
  superseded engineering draft. Create append-only protocol v1.1.1 before any
  v1.1 outcome access; change no formula, population, cost, threshold, or claim
  ceiling.
- Freeze pre-access only facts that can be known without decoding bars:
  denominator/source identities, file and canonical content hashes, calendar
  authority and bounds, derivation rules, calculation code/runtime, economic
  policy, acceptance gates, one-run authority, and output paths.
- Do not invent future value-derived schedules, raw-signal rows, ranks, or
  terminal-input hashes. Seal both access intents before the first numeric byte,
  then derive exact 25, 100, and 191 manifests in the same uninterrupted
  noninteractive run and append a post-access, pre-performance input seal.
- Allow no return, PnL, future-return comparison, benchmark-performance, or
  acceptance calculation or inspection before that seal. State honestly that
  decoding bytes exposes historical bars to the process; protection comes from
  the prior source/rule freeze, immutable journal, no pause, and no retuning.
- Keep PILOT25 and EXPANSION100 integrity-only. Permit exactly one FULL191
  performance aggregation after the input seal. Bind all outputs and the final
  terminal to both the execution intent and input seal; classify uncertain
  partial durable state as non-retryable `UNKNOWN`.
- Retain `NOT_VALIDATED`, no production or brokerage authority, and the same
  history development-only claim ceiling under every result.

## 2026-08-12: Preserve failed Quant run 001 and add decoder successor v1.1.2

- Preserve `QUANT-V11-CONTROLLED-20260812-001` and its five-event terminal
  chain. The run opened ADM payload JSON after both access intents and failed
  because `providerRecordId` was null. It created no post-access seal, output,
  signal, rank, return, PnL, performance, or acceptance result.
- Do not retry or rewrite the failed run. Require a new immutable execution
  identity for any successor attempt.
- Add only one payload compatibility delta: accept `providerRecordId` as a
  nonempty string or null. Reject empty strings and all other JSON types. Do not
  change any other schema, arithmetic, chronology, formula, rank, cost, gate,
  or claim rule.
- Integrate an exact all-203 dual-hash decoder check after the execution intent,
  under the same canonical execution lease, and before the post-access input
  seal and performance. Do not expose it as a standalone pre-intent preflight.
- Bind the successor source bytes through the existing calculation-source
  manifest. Keep the model label `NOT_VALIDATED` and prohibit evidence upgrade.

## 2026-08-12: Preserve failed Quant run 002 and add adjustment successor v1.1.3

- Preserve `QUANT-V11-CONTROLLED-20260812-002` and its five-event terminal
  chain. It opened ADM payload JSON after both access intents and failed before
  the post-access seal with `Yahoo_source_adjustment_drift`. It produced no
  signal, rank, return, PnL, output, performance, or acceptance result.
- Record that the retained producer emits `sourceAutoAdjust=false` with
  `sourceAdjustmentMode=TOTAL_RETURN_ADJUSTED` when adjusted close exists,
  while preserving raw OHLC, adjusted OHLC, and an explicit adjustment factor.
- Require that exact source adjustment mode in v1.1.3. Reject `UNADJUSTED` and
  every other value. Preserve every other adjustment field, per-bar arithmetic
  check, formula, rank, cost, threshold, and claim rule.
- Bind the exact v1.1.3 addendum version/hash and all-203 contract-validation
  hash into the post-access seal. Keep the runner-side dataclass and factory
  exact-value checks so self-consistent rehashing cannot substitute another
  addendum.
- Do not retry or rewrite Runs 001 or 002. Require a new immutable execution
  identity and keep `NOT_VALIDATED` without evidence upgrade.

## 2026-08-12: Preserve failed Quant run 003 and add zero-volume successor v1.1.4

- Preserve `QUANT-V11-CONTROLLED-20260812-003` and its failed five-event chain.
  It stopped before the post-access seal on `Yahoo_bar_wire_type_drift` and
  created no signal, rank, return, PnL, output, performance, or acceptance
  value. Do not retry or reinterpret it.
- Bind the outcome-blind controlled scan of 630,672 wire rows: 1,120
  zero-volume rows across seven symbols, with no negative, non-integer, or
  above-signed-int64 volume and no invalid price or adjustment factor.
- In v1.1.4, accept only exact integer volume greater than or equal to zero.
  Validate every wire row and all adjustment arithmetic before treating zero
  volume as explicit `ZERO_VOLUME_NONTRADABLE_MISSING`. Exclude it from usable
  bars, ADTV, liquidity, signals, ranks, costs, and returns.
- Bind all wire rows through header count and date range, per-source
  wire/usable/zero counts and excluded-date hashes, and the aggregate identity
  `630672 = 629552 + 1120` across seven symbols. Keep the full SPY wire-session
  calendar; never compress a zero-volume SPY date.
- Change no formula, rank, cost, threshold, acceptance, or claim rule. Bind the
  exact v1.1.4 addendum and payload-validation hashes, require a new immutable
  run, and retain `NOT_VALIDATED`.

## 2026-08-12: Preserve failed Quant run 004 and replay producer arithmetic exactly

- Preserve `QUANT-V11-CONTROLLED-20260812-004` and its exact five-event chain.
  It failed before the post-access seal on
  `Yahoo_adjusted_OHLC_arithmetic_drift`, produced no output or performance
  value, and cannot retry.
- Bind the outcome-blind 630,672-row scan. The legacy close-product check had
  3,100 differences of `1e-27` or `1e-26`, while exact producer replay at
  precision 28 and `ROUND_HALF_EVEN` had zero factor, open/high/low product, or
  adjusted-close identity discrepancy.
- Replay each complete row in a local Decimal-28 half-even context with no
  tolerance. Require exact factor division, open/high/low products, and close
  identity to adjusted close. Do not depend on ambient Decimal state.
- Preserve bounded finite positive prices/factors and every v1.1.4 zero-volume
  missing rule. Change no strategy formula, ranking, cost, metric, threshold,
  acceptance, or claim rule.
- Bind the v1.1.5 addendum and payload-validation identities, require a new
  immutable run, and retain `NOT_VALIDATED`.

## 2026-08-12: Preserve failed Quant run 005 and close OHLC representation exactly

- Preserve the exact Run005 five-event chain. It failed before the post-access
  seal with no output or performance value and cannot retry.
- Bind the outcome-blind 629,552-usable-bar diagnosis: 21 high and 16 low
  closures, 37 rows across 15 symbols, maximum correction `1e-26`, and zero
  residual TrendBar-domain violation after exact closure.
- Require v1.1.5 producer replay and zero-volume exclusion first. Reject raw
  OHLC disorder and producer-derived tactical-open envelope violations before
  closure. Permit only direct adjusted-close escape to close exact max/min.
- Bind complete per-record source/payload/date/field/value/correction provenance
  and per-source and aggregate set hashes. Use no epsilon, tolerance, or
  quantization; leave open/close and all economic rules unchanged.
- Require a new immutable v1.1.6 run and retain `NOT_VALIDATED`.

## 2026-08-12: Preserve failed Quant run 006 and correct execution denominator

- Preserve Run006 and its exact five-event chain. It failed before the
  post-access seal on `nontradable_session_registry_drift`, created no output or
  performance value, and cannot retry.
- Continue validating all 203 sources and retaining all typed zero-volume
  evidence. Project execution nontradable sessions onto exactly 191 securities
  plus SPY; exclude all 11 unused diagnostic benchmarks.
- Require exact nontradable-registry and loaded-payload key equality in the
  loaded execution boundary. Reject missing and extra execution identities so
  diagnostic evidence cannot leak.
- Change no representation, strategy, ranking, cost, threshold, acceptance, or
  claim rule. Require a new v1.1.7 execution identity and retain
  `NOT_VALIDATED`.

## 2026-08-12: Preserve failed Quant run 007 and normalize the sealed digest wire

- Preserve Run007 and its exact five-event chain. It completed typed validation
  and terminal-input construction, then failed before the post-access seal on
  `payload_contract_validation_hash_must_be_an_uppercase_SHA-256`. It created no
  output or performance value and cannot retry.
- Keep the validator's canonical `sha256:<lowercase-64-hex>` content reference.
  At the seal boundary, accept only the typed validation result, replay its
  content hash, decode its suffix to exactly 32 bytes, and emit those same bytes
  as uppercase hex without hashing again.
- Reject malformed references, untyped substitutes, and well-formed altered
  hashes. Audit every other immediate seal digest against the runner grammar so
  no second representation mismatch can cross the boundary.
- Change no payload, denominator, representation, formula, ranking, cost,
  threshold, acceptance, or claim rule. Require a new v1.1.8 execution identity
  and retain `NOT_VALIDATED`.

## 2026-08-13: Close Quant v1.1 Run008 as not directionally supportive

- Preserve the exact Run008 six-event journal, post-access pre-performance
  seal, completed terminal, and four immutable result files. Do not rerun or
  rewrite the controlled result.
- Accept the frozen 5-of-9 result as
  `NOT_DIRECTIONALLY_SUPPORTIVE_NO_RETUNING_ON_SAME_OUTCOME`. Preserve the four
  failed codes: CAGR excess versus SPY, total-return excess versus SPY, Sharpe
  advantage versus SPY, and positive SPY-CAGR excess subperiod count.
- Record that the primary replay grew USD 100,000 to USD 237,071.67 at 7.76%
  CAGR, while SPY grew it to USD 437,644.04 at 13.63% CAGR. The primary's lower
  drawdown does not override its benchmark-relative return and Sharpe failures.
- Publish only a Git-safe aggregate result with hashes and summary metrics. Do
  not publish raw payloads, licensed values, security rows, orders, daily paths,
  or private storage paths.
- Keep the evidence label `NOT_VALIDATED`. Prohibit same-outcome parameter
  tuning, formula reinterpretation, portfolio authority, and brokerage action.
## 2026-08-13: Ship Quant v1.1 as an immutable research-only product slice

- Keep Quant v2 paused and preserve the observed v1.1 formula and historical
  disposition without same-outcome retuning.
- Add V27 as an append-only public-safe research-decision projection over the
  provider-neutral V22 assembly boundary.
- Permit deterministic candidate, hold-review, exit-review, no-signal, and
  evidence-state display; do not interpret any classification as a trade.
- Keep FastAPI creation internal, make Spring public access GET-only, and make
  Next.js call Spring only.
- Prohibit final weights, order quantities, brokerage instructions, automatic
  execution, LLM signal authority, guaranteed returns, and evidence-label
  upgrades in the persistence and cross-language contracts.
# 2026-08-13 - Keep Task 5 final mutation acceptance open after V33 hardening

- Add append-only V33 guards that server-normalize V31/V32 runtime timestamps to
  whole seconds and permit an unsealed longitudinal command to perform only its
  single validated seal transition.
- Require one frozen cutoff for the exact-four scenario cohort. Expose all four
  sealed economic projections before a separate human recommendation selection,
  and bind a superseding thesis review to the latest review identifier.
- Record the current V1-to-V33 PostgreSQL 17 matrix as passed, along with focused
  Python, Spring, typed PostgreSQL, frontend, lint, and production-build gates.
- Do not accept Task 5 as complete: the final fresh mutation-driven four-service
  flow remains blocked because the historical manifest lacks a V26 assessment
  reference and the controlled V26 seed cannot duplicate its deterministic GOOG
  identity. Preserve fail-closed model binding rather than fabricate a reference.

# 2026-08-13 - Freeze Task 5 as V29 decisions, V30 enrollment, V31 observation, and V32 longitudinal review

- V12 remains authoritative for onboarding, snapshots, liabilities, and
  constraint policies; its legacy scenario tables are not reinterpreted.
- V28 remains the immutable current portfolio/risk context.
- V29 will own four deterministic current scenarios, evidence bindings, a
  recommendation for human review, and an immutable human decision.
- V30 owns simulated evaluation enrollment. V31 is the append-only successor
  for frozen accepted/HOLD opening ledgers, ID-only buy-and-hold observations,
  same-calendar natural maturity, and accepted/HOLD/SPY summaries.
- V32 requires one sealed cohort containing exactly `HOLD_CURRENT`,
  `NEW_MONEY_ONLY`, `CONSTRAINED_REBALANCE`, and `TARGET_PORTFOLIO` before a
  recommendation or human acceptance. It derives gross and net return,
  HOLD/SPY comparisons, true daily-path maximum drawdown, coverage, turnover,
  cost, and an immutable longitudinal thesis-review state.
- Fundamental Value and Quant remain independent sleeves. Scores are not
  blended or used as optimizer objective coefficients, `NOT_VALIDATED` cannot
  be upgraded, and neither an LLM nor the application can create final orders.
- Economic and evaluation policies are frozen before scenario or future price
  results. The product must preserve missing evidence and cannot tune rules to
  force favorable outcomes.
# 2026-08-13: Accept Portfolio Decision Support and Evaluation v1

Task 5 is accepted as a production-shaped, human-controlled simulated workflow
through V32. Browser requests remain Spring-only; Python analytics boundaries
require service authentication; portfolio prices, evidence, labels, and
returns are hydrated and replayed rather than accepted from browsers. Four
scenarios, immutable recommendations, human decisions, SPY evaluation
enrollment, frozen HOLD comparison, and a controlled observation/maturation
writer are implemented. The synthetic USD 100,000 acceptance does not upgrade
model validation labels or claim future returns. See [the Task 5 acceptance
report](portfolio-decision-support-v1-acceptance-2026-08-13.md).

# 2026-08-13: Close the Task 5 fresh mutation gate on V35

The prior V33 blocked gate is retained as historical evidence and superseded by
a fresh disposable PostgreSQL 17 V1-to-V35 run. V34 freezes scale-20
`ROUND_HALF_EVEN` ratio replay. V35 binds current valuation to V22
`CLOSE_PRICE` with `UNADJUSTED` semantics while preserving V31 longitudinal
total-return observations. FastAPI, Spring Boot, and Next.js completed the
fresh exact-four comparison, recommendation selection, and immutable human
decision workflow. Exact replay succeeded and changed same-key commands were
refused with stable conflicts. No provider request, fabricated maturity,
brokerage action, final weight, or evidence-label upgrade occurred.
