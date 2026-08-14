# Roadmap

## Task 4: Unified Portfolio and Risk Context v1

- [x] Reuse V12 users, portfolios, immutable account snapshots, liabilities,
  and versioned constraints without rewriting V21.
- [x] Freeze separate `LONG_TERM_CORE` and `QUANT_TRADING` evidence bindings.
- [x] Implement deterministic cash, asset, liability, leverage, position, and
  sector exposure calculations with explicit missing valuation state.
- [x] Add append-only V28 context, child cardinality, sealing, immutable human
  review, and no-automation controls.
- [x] Add Spring ownership, constraint-policy, idempotency, and upstream hash
  validation plus public create/read/review APIs.
- [x] Add the Spring-only Next.js `/portfolio` workspace.
- [x] Preserve Quant v2 as `NOT_VALIDATED` and ineligible for portfolio
  research authority.

The Task 4 product slice is engineering-complete. It is decision support, not
an allocation optimizer or execution system. Real portfolios still require
the user to create sealed account snapshots and a V12 constraint policy.

## Task 3: Quantitative Trading System

- [x] Freeze the Stage 0 long-only momentum-continuation decision contract.
- [x] Freeze completed-session, next-session entry, exit, risk, cost, benchmark,
  V22 evidence, and validation boundaries.
- [x] Implement the deterministic Stage 1 signal and trade-plan core.
- [x] Implement the event-driven USD 100,000 portfolio simulator and cost replay.
- [x] Run the frozen v1 development replay and retain the honest
  `NOT_VALIDATED` economic rejection.
- [x] Freeze a separately versioned v1.1 dual-momentum/trend successor without
  rewriting the observed v1 strategy.
- [x] Complete the v1.1 simulator and outcome-blind validation protocol.
- [x] Complete the one authorized v1.1 FULL191 development observation without
  same-run tuning; retain the honest 5/9-gate
  `NOT_DIRECTIONALLY_SUPPORTIVE_NO_RETUNING_ON_SAME_OUTCOME` result.
- [x] Assemble provider-neutral V22 evidence and fail-closed applicability.
- [x] Add append-only V27 research-decision persistence, internal/public read
  APIs, and the Next.js research workspace without portfolio-weight or
  brokerage authority.
- [x] Freeze and implement the independent Quant v2 regime-filtered
  mean-reversion core, simulator, costs, and one-pass historical protocol.
- [x] Run the single v2 controlled replay and retain the honest 4/8-gate
  `NOT_DIRECTIONALLY_SUPPORTIVE_NO_RETUNING_ON_SAME_OUTCOME` result.
- [x] Stop v2 without same-outcome retuning or promotion into the public
  decision path.
- [ ] Start sealed prospective validation after retrospective development.

v1 is reproducible but economically rejected: 1.13% CAGR versus SPY at 13.68%
on the same development-only current-survivor calendar. v1.1 also completed and
was not directionally supportive: 7.76% CAGR versus SPY at 13.63%, with 5 of 9
frozen gates passing. Quant v2 mean reversion was implemented independently and
also stopped after an unsupportive result: 0.63% CAGR versus SPY at 13.53%, with
4 of 8 gates passing. None of these retrospective results is an untouched
holdout.

## Fundamental Value Current-Assessment Closeout

- [x] Freeze and verify the V25 GOOG/FOX/MSFT durable identity authority.
- [x] Replay the exact private EODHD fundamentals and price receipts offline.
- [x] Require explicit EODHD provider and governed completed-session authority
  before V22 evidence registration.
- [x] Implement V22 current classification, applicability, and price selection.
- [x] Accept the final V26 assessment authority, append-only persistence,
  formula replay, TOCTOU, upgrade, and refusal matrix on PostgreSQL 17.
- [x] Apply V26 to the local business database and persist the three rebuilt
  current assessments.
- [x] Expose GET-only Python, Spring Boot, and Next.js read paths by assessment
  ID and latest symbol.
- [x] Verify real PostgreSQL-to-FastAPI readback plus the accepted Spring and
  Next.js strict read contracts, private-data redaction, and documentation
  closeout.

The Quant Trading product slice is tracked separately and is not part of this
Fundamental Value closeout.
Fundamental Value v1 is considered an engineering-complete research aid at this
checkpoint. Future validation should measure useful relative direction and risk,
not optimize for perfect prediction accuracy.

## Current Position

Phase 0, the first end-to-end market-data slice, and the internal Market
Intelligence data and screening foundation are complete. The current
checkpoint includes Market Intelligence persistence through V17, the Forward
DQV migration chain through V20, legacy/unwired V21 portfolio-decision
persistence, the V22 Unified Market Data and Evidence Foundation, the V23
Fundamental Value persistence successor, the isolated V24 company-quality
Forward enrollment readiness successor,
provider-neutral model and refresh interfaces, durable security profiles,
sector/industry/security screening, a 136-security QC snapshot, frozen
Tactical Signal v2.2 and Long Horizon v1.1 contracts, and local Forward
Decision-Quality v2 contracts, the V25 identity authority, V26 current
Fundamental Value assessments, V27 Quant research-decision persistence, and
V28 Unified Portfolio/Risk Context persistence. The repository migration and
isolated-test head is V28; V17 remains the last
shared operational application baseline.

Historical point-in-time UQ validation, prospective outcome maturation,
source-verified AI operation, a deployed scheduler, production authentication,
and portfolio recommendation workflows remain separate later gates. Public
Market Intelligence API code and the local frontend research workflow are now
implemented for closed-test use. The current engineering acceptance is not a
claim of proven excess returns.

The separately named **Dual-System Architecture Contract v1** is frozen. It
does not replace the legacy Phase 0 foundation milestone below. It establishes
independent Fundamental Value and Quantitative Trading systems, isolated
`LONG_TERM_CORE` and `QUANT_TRADING` sleeves, a non-blended Unified
Portfolio/Risk View, provider-neutral evidence usability classes, AI isolation,
and explicit human control. Task 1 is complete through the accepted
migration-free Stage 3C operational integration.

## Dual-System Architecture Contract v1 - Complete

- [x] Freeze independent Fundamental Value and Quantitative Trading boundaries
- [x] Freeze `LONG_TERM_CORE` and `QUANT_TRADING` sleeve isolation
- [x] Prohibit cross-engine score averaging and automatic cash transfers
- [x] Freeze evidence strictness, claim classes, conflicts, and tolerance rules
- [x] Freeze AI narrative-only and human-decision boundaries
- [x] Add shared Python, Java, and TypeScript compatibility fixtures/tests

Exit status: contract freeze achieved. Task 1 progress is tracked below;
public selector/API replacement remains unstarted.

## Task 1: Unified Market Data and Evidence Foundation v1 - Complete

- [x] Reconfirm `57fa7ed`, the accepted Phase 0 worktree, and V17 migration head
- [x] Resolve the reachable Forward/portfolio V18-V21 assignments and assign
  the separate Task 1 successor to V22
- [x] Add a Git-safe provider-neutral evidence selection fixture
- [x] Add deterministic identity, chronology, lineage, freshness, conflict,
  revision, and provider-fallback validation
- [x] Add explicit specialized-model applicability routing
- [x] Add canonical price/action/fundamental/classification/benchmark/liquidity
  domain contracts and engine-derived evidence binding
- [x] Adopt the exact curated V18-V21 Forward/portfolio migration lineage
  without changing its versions or checksums
- [x] Mark V21 legacy/unwired and add dedicated V18-V21 migration acceptance
  paths, including the V19 populated-v2.1.0 refusal
- [x] Strengthen the static matrix with exact V19 refusal verification,
  pre-upgrade V19/V20 preservation fixtures, and five-table V21 immutability
  coverage
- [x] Execute the curated V18-V21 acceptance matrix on PostgreSQL 17
- [x] Implement the append-only V22 durable identity/calendar/evidence
  successor without reinterpreting V21
- [x] Add the Python typed V22 canonical-evidence persistence/read adapter
- [x] Close V22 selector aggregates over every supplied candidate and verify
  deterministic per-candidate rejection reasons
- [x] Bind completed-session local dates, liquidity parent cardinality, and
  hash-verified latest-only applicability successors
- [x] Execute final clean V1-to-V22, V17-to-V22, and prepopulated V21-to-V22
  paths on PostgreSQL 17
- [x] Add PostgreSQL-backed selectors and internal selector endpoints
- [x] Complete final bounded clean, upgrade, refusal, preservation,
  immutability, relational-sealing, and typed round-trip acceptance
- [x] Bind fake-transport provider adapters to the existing lease, journal,
  checkpoint, idempotency, and resume controls without startup fetching
- [x] Freeze the Yahoo/EODHD/future-replacement adapter boundary so
  provider-native fields terminate before canonical V22 consumers
- [x] Bind selector result hashes to request/policy identity and the complete
  deterministic rejection map
- [x] Bind offline refresh identities to full security/session context,
  strictly revalidate nonempty overlap/backfill batches, and make exact
  cross-run evidence replay idempotent
- [x] Rerun the fresh V1-to-V22 PostgreSQL Stage 3C matrix after the final
  request-hash and replay hardening
- [x] Keep raw-payload retention, legal-hold, and deletion governance outside
  Task 1 without adding deletion operations; after Task 2 reserves V23 for
  Fundamental Value persistence, any future raw-governance successor uses the
  next available migration version

Stage 2 acceptance: Ruff passed and the bounded Python regression set reports
`197 passed`. No migration, provider request, scoring change, or public API
replacement was included. Reachable Forward/portfolio lineage V18-V21 is
adopted exactly in Stage 3A and its PostgreSQL 17 matrix is
accepted. V21 remains legacy and unwired. Stage 3B adds V22 as a separate
analytics-owned successor and verifies preservation of representative V19,
V20, and V21 rows and hashes. The controller accepted the exact PostgreSQL 17
V1-to-V22 matrix, two typed tests on a fresh schema-only database, and an
order-independent rejection test on a second fresh database. Stage 3C is
migration-free and internal-only. It does not authorize a provider request,
public API replacement, business-database deployment, or raw-data deletion.
Final Stage 3C acceptance additionally records `33 passed` for the adapter
module, Ruff PASS, and three typed Python/PostgreSQL integration tests passing
in 5.05 seconds on a fresh disposable PostgreSQL 17 V1-to-V22 database.
Independent relational and Python/provider/refresh/persistence/API audits
reported no residual blocker. Physical raw-object retention/deletion governance
remains deferred and is not part of the Task 2 V23 successor.

## Task 2: Fundamental Value Investment System v1 - In Progress

- [x] Freeze mature-nonfinancial applicability and fail-closed specialized routing
- [x] Freeze FCFF DCF, normalized Owner Earnings, and Earnings Power as primary methods
- [x] Limit comparable valuation to a non-controlling cross-check
- [x] Freeze weighted-median central value and ordered weighted-quantile range
- [x] Freeze 0/1/2/3/5 percent `LONG_TERM_CORE` risk-cap ceilings
- [x] Reserve append-only V23 for Fundamental Value persistence and exclude raw governance
- [x] Freeze historical-before-prospective validation sequencing and honest `NOT_VALIDATED`
- [x] Accept the repaired pure deterministic Python core
- [x] Accept the Stage 3 V22 evidence assembly and applicability boundary
  with the mature-company operand coverage blocker explicit
- [x] Implement the repaired V23 persistence candidate with private value seals,
  exact 34-operand authority, identity-scoped revisions, and Python semantic replay
- [x] Remove unapproved derived/policy economics and freeze an empty production
  producer registry with executable `TEST_ONLY` acceptance seams
- [x] Obtain master-controller acceptance for the repaired Stage 4 candidate
- [x] Implement internal FastAPI and Spring Boot contracts
- [x] Obtain master-controller final acceptance for the repaired Stage 5 candidate
- [x] Implement the Spring-only Next.js Fundamental Value workspace candidate
  with result-only v1.1 durable identity/session projection, exact
  request/result assembly binding, strict hash and semantic replay, and
  projection-horizon-aware presentation
- [x] Obtain master-controller acceptance for the Stage 6 workspace
- [ ] Execute separately gated historical time-slice validation
- [ ] Prepare prospective Forward DQV readiness after historical acceptance

Stage 1 is an engineering contract freeze, not investment validation.

## Phase 0: Foundation - Complete

- [x] Initialize the monorepo structure
- [x] Create the Next.js frontend
- [x] Create the Spring Boot backend
- [x] Create the FastAPI analytics service
- [x] Configure PostgreSQL
- [x] Add Docker Compose
- [x] Add health checks
- [x] Establish formatting, testing, CI, and secret-scanning conventions

Exit condition: all services build and start locally.

Exit status: achieved.

## Phase 1A: Market Data Vertical Slice - Complete

- [x] Select United States equities and Twelve Data for the first slice
- [x] Ingest the six-security engineering universe
- [x] Store normalized daily price data
- [x] Expose latest stored observations through Spring Boot
- [x] Display latest observations in Next.js

Exit condition: a real provider observation moves through Python, PostgreSQL,
Java, and the frontend.

Exit status: achieved.

## Phase 1B: Data and Methodology Validation - Current Use Accepted

- [x] Define the 20-security provider-validation universe
- [x] Define reference, price, corporate-action, and fundamental data contracts
- [x] Validate current-decision dates, adjustments, identifiers, null handling,
  and SEC consistency
- [ ] Validate sector and industry normalization
- [ ] Add major sector ETF history for sector market-condition research
- [x] Accept EODHD for bounded current use with capability-specific limitations
- [x] Document the first factor definitions and exclusion rules

Current-use status: achieved for the sealed QC route. Historical point-in-time
and revision suitability remains open and must not be inferred from current
acceptance.

## Phase 2: Explainable Quantitative Screening

- [x] Implement the versioned screening task and immutable result pipeline
- [x] Connect the Spring Boot public API to the FastAPI screening contract
- [x] Complete a sealed current-decision general-company raw-input route
- [x] Implement `Quality Compounder`
- [x] Implement `Undervalued Quality`
- [x] Compare within sector, size, company-type, and strategy cohorts
- [x] Preserve raw factors, normalized contributions, exclusions, and confidence
- [x] Version strategy configuration
- [x] Store candidate and coverage snapshots
- [x] Evaluate a 300-security stratified provider sample
- [x] Run a 2014-2026 closed-universe historical diagnostic with sealed random
  and month-end decision dates
- [x] Implement and freeze deterministic Tactical v2.2 and Long Horizon v1.1
- [x] Add one unified chronological walk-forward, six-benchmark, cost, risk,
  coverage, and dependent-outcome validation contract
- [x] Preserve complete-population `BLOCKED_BY_DATA` historical terminals for
  both current models instead of manufacturing partial scores
- [x] Complete the one-retrospective Tactical v2.2 Tier 1 statistical closeout
  and Long Horizon v1.1 Tier 2 PIT reconstruction without observed-outcome
  tuning
- [x] Execute and independently accept Practical Tier-1 current-universe
  retrospectives for Tactical v2.2 and the target-100 Long Horizon v1.1
  quality and valuation dimensions
- [ ] Obtain new evidence that can support a genuine post-freeze holdout or
  prospective model-quality conclusion
- [ ] Acquire the PIT duration, valuation, and membership evidence required for
  a strict Objective historical replay
- [x] Implement local immutable Forward v2 snapshot, preregistration,
  enrollment, and 5/20/60/126/252-session outcome contracts
- [x] Implement and accept the append-only V18 structured Forward DQV ledger
- [x] Implement and accept V19/v2.1.1 chronology repair; keep v2.1.0
  unreachable for production writes
- [x] Implement and accept the append-only V20 successor for dated sector
  bindings, benchmark variants and holdings, nonlinear holding costs, and
  typed benchmark outcomes
- [x] Implement the offline Gate H maturity evaluator for 5/20/60/126/252
  sessions
- [x] Implement the strict maturity-to-statistics adapter and frozen Forward
  DQV statistical engine
- [x] Seal and retain the pre-preregistration 66-security Forward v2 audit
  handoff as historical engineering evidence only
- [ ] Capture the completed target session and seal real 66-security model
  inputs plus all six benchmark families
- [ ] Supply the required benchmark evidence and enroll the sealed decision
  without changing its models, evidence, or hashes
- [ ] Execute real v2.1.1 enrollment on at least two decision dates and reach
  the frozen 100-decision cohort
- [ ] Mature all preregistered horizons naturally and run Gate H, the adapter,
  and the frozen statistics engine

Current status: deterministic current-decision rankings are reproducible and
explainable. Practical Tier-1 Tactical evidence is unsupported at 5 sessions,
mixed at 20 sessions, and modestly positive at 60 sessions; entry timing
remains `NOT_VALIDATED`. Practical Tier-1 Long Horizon evidence supports a
modest one-year Business Quality top-cohort association against SPY, but not
score ordering, Security Attractiveness, Expected Return, or Downside Risk.
The stricter PIT historical terminals remain blocked. Forward v2 contracts,
V18/V19/V20 persistence, Gate H,
the statistics adapter, and the statistical engine are implemented offline.
The first local snapshot handoff remains historical engineering evidence, not
a prospective enrollment. The target session and naturally matured outcomes
are blocked by time; real 66-security inputs, the controlled six-family
benchmark ledger, and per-security decision evidence are blocked by evidence.
No real v2.1.1 enrollment or statistics run exists. The prospective Gate Z
state remains `CRITICAL_BLOCKED_NOT_VALIDATED`.

## Phase 2B: Market Intelligence Persistence - Complete

- [x] Define versioned company and security profile contracts
- [x] Compose objective, tactical, valuation, and evidence statuses without
  changing their source models
- [x] Add sector, industry, and security filters and rankings
- [x] Persist immutable profiles, horizon views, exclusions, and screening
  results through PostgreSQL V17
- [x] Keep AI narrative records isolated from deterministic ranking
- [x] Add provider-neutral daily refresh plans, tasks, checkpoints, freshness,
  and usage telemetry
- [x] Validate clean and upgrade migration paths through V17

Exit status: achieved for internal Python and database contracts.

## Phase 2C: End-to-End Market Intelligence Productization - Implemented Locally

- [x] Freeze a bounded 66-security daily refresh plan
- [x] Use yfinance for permitted closed-test daily prices and EODHD only for
  datasets whose accepted capability requires it
- [x] Publish Market Intelligence profile and screening contracts through
  Spring Boot
- [x] Build the Next.js candidate list, filters, and stock detail view
- [x] Display data timestamps, missing states, exclusions, and model versions
- [x] Seal synchronized daily decision-snapshot handoffs
- [x] Add an idempotent V17-to-V11 prospective enrollment bridge without
  changing frozen models; the current attempt honestly records
  `NO_ELIGIBLE_SIGNALS`
- [x] Complete the approved 57-price/57-action/55-fundamental refresh while
  rejecting ACN's malformed row, retaining its 259 prior valid sessions, and
  recording its latest freshness as `STALE/LATE_DATA`

Exit condition: a completed market session can be refreshed once, persisted,
screened, exposed through Java, and reviewed in the frontend with complete
lineage and no direct browser access to Python, PostgreSQL, or provider
credentials. The bounded refresh, approved recovery, and product path meet the
engineering condition. The real product-eligibility state remains `PARTIAL`,
and the sealed 66-security screen honestly records `NO_ELIGIBLE_RESULTS` with
0 eligible results. That result is separate from provider-run completion and
does not imply that the refresh is unfinished.

## Phase 3: AI Evidence Review

- Retrieve SEC and other approved source documents
- Extract source metadata
- Define the structured evidence schema
- Add citation validation
- Add supporting, contradictory, and unresolved evidence
- Store prompt and model versions
- Add review queue priorities, caching, and safe failure behavior
- Keep quantitative-only and AI-reviewed rankings distinct

Exit condition: candidate reports are source-backed, structured, and
reviewable.

## Phase 4: User and Portfolio Context

- Add a development user with a future-safe user identifier
- Add investment approach, horizon, risk profile, and sector preferences
- Add accounts, cash, liabilities, leverage limits, and holdings
- Calculate position, cash, and sector exposure
- Record allowed rebalancing scope
- Preserve investment theses and invalidation conditions

Exit condition: the system can represent the complete context required for
portfolio-aware analysis.

## Phase 5: Portfolio Decision Support and Evaluation

Task 5 is engineering-complete. Its contract uses V29 for
the current portfolio decision graph, V30 for simulated evaluation enrollment,
V31 for controlled buy-and-hold observation and natural-maturity evaluation,
V32 for the exact-four comparison cohort, daily-path longitudinal metrics,
and thesis review, V33 for runtime timestamp and longitudinal-seal hardening,
V34 for exact ratio replay parity, and V35 for current unadjusted-close evidence.
V12, V21, and V28 retain their existing meanings. See
[Portfolio Decision Support and Evaluation v1](portfolio-decision-support-v1.md)
and the [acceptance report](portfolio-decision-support-v1-acceptance-2026-08-13.md).

- Evaluate candidate fit against the complete portfolio
- Compare new-money-only allocation
- Compare constrained rebalancing
- Compare a target-portfolio simulation
- Add immutable recommendation and human-decision snapshots
- Add benchmark, return, drawdown, turnover, and cost evaluation
- Add longitudinal thesis review

Exit condition: the platform supports human-controlled simulated decisions and
honest performance evaluation.

## Phase 6: Public Demo

- Improve user experience
- Add authentication appropriate for a demo
- Add monitoring and structured logs
- Add secure secret handling
- Confirm commercial data and AI licensing
- Deploy the closed-test architecture to Render
- Use managed PostgreSQL with private networking, separated credentials,
  automated backups, and a one-off migration release step
- Add a public project overview and demonstration flow

Exit condition: a reviewer can access and understand the product without local
setup.

## Phase 7: Production Learning

- Extend the existing GitHub Actions baseline for deployment
- Add stronger observability
- Add backup and recovery procedures
- Migrate a deployment to Amazon ECS Fargate and Amazon RDS
- Document architecture tradeoffs and operational lessons

Exit condition: the project demonstrates a credible cloud deployment path.

## Deferred Capabilities

Quant Trading v1.1.1 chronology/provenance is preregistered before outcome
access. Its next gate is runner/executor parity with the exact journal sequence
ending in a post-access, pre-performance input seal. PILOT25 and EXPANSION100
remain integrity-only; one FULL191 aggregation is the sole permitted
performance run. No v1.1 outcome may be opened until calculation-source/runtime
TOCTOU checks, exact source file/content hashes, typed manifest prefix equality,
FAILED/UNKNOWN handling, and result-to-input-seal binding pass. The frozen
strategy economics and numeric acceptance thresholds are unchanged.

Fundamental Value Stage 7 retrospective validation is closed after the C9
protocol-repair confirmation. C8 remains immutably rejected. C9 is
`MIXED_NOT_VALIDATED` and development-only; it does not establish strict PIT,
backtest support, forward support, or production eligibility. Only
migration-free Stage 8A readiness/preregistration and the isolated V24 Stage 8B
engineering contract are complete. Real enrollment remains blocked until a
current completed-session calendar, contractual evidence ingestion chronology,
durable population identities, exact per-MIC decision sessions, and authoritative
per-MIC planned-entry schedules are sealed. Provider traffic remains subject
to a separately accepted, exact request matrix. The first approved OpenFIGI
canary stopped after three of four requests on a known `BF/B` versus `BF-B`
parser defect, with retry zero and no unknown outcome. Its v1.2 run is terminal.
The offline v1.3 request-bound ticker-alias repair is complete, but a successor
also requires exact ISIN/CUSIP raw-provider identity convergence and rebuilds
the review from immutable checkpoints at acceptance and execution. A successor
canary requires a new exact plan and explicit network approval before any
request is sent. SEC, Yahoo, EODHD, evidence writes, and enrollment remain
closed.

The v1.3 successor canary completed its exact four-request boundary but was
rejected after review: 5 of 18 logical jobs had unique primary mappings and 13
were unresolved, including every `XNAS` job. The `BF/B` alias repair itself
passed for both identifiers. A same-plan retry is prohibited. Any v1.4
successor must freeze corrected MIC and identifier semantics with adversarial
tests before another provider request; it may not relax the complete-pair gate.

That v1.4 diagnostic is now complete and rejected. Its two requests and ten
jobs completed with HTTP 200, retry zero, no failure, and no unknown outcome;
a zero-send checkpoint replay found four unique mappings, six ambiguous
mappings, and only two of five complete convergent pairs. The diagnostic does
not authorize durable identities, population expansion, evidence writes, or
V24 enrollment. The next identity step must use a new frozen exact plan,
preserve the ambiguity as an explicit terminal state, and obtain independent
SEC corroboration for operating-MIC ownership before any enrollment claim.

The append-only v1.5 US-composite diagnostic has now passed its own exact
engineering gate: 2 of 2 requests and 6 of 6 jobs completed, all six mappings
were unique, all three identifier pairs converged, and no warning, error,
ambiguity, missing-primary result, failure, unknown outcome, or retry occurred.
A zero-send replay reproduced the same two private checkpoints and immutable
hashes. This was a post-v1.4 method repair, not a holdout, and it does not
promote the model beyond `NOT_VALIDATED`. The result authorizes neither a
durable identity nor the remaining population, V22/V24 writes, or enrollment.
The next bounded identity work is SEC operating-MIC corroboration, target
database identity inventory, a forward-projection-v2 contract, and a V25
identity-authority ledger. All four are required before a governed write.
Projection v1 must not be reused for that work.

The following require separate approval and demonstrated need:

- Emerging-growth and specialized industry models
- Redis-based task processing
- Kafka event streaming
- Kubernetes
- Multiple equity markets
- Native mobile applications
- Brokerage connectivity
- Automated execution
- Commercial billing
# Task 5 acceptance checkpoint (2026-08-13)

Portfolio Decision Support and Evaluation v1 passed its final fresh
mutation-driven four-service gate on V35. The accepted controlled evidence is
recorded in [Portfolio Decision Support and Evaluation v1 Acceptance](portfolio-decision-support-v1-acceptance-2026-08-13.md).
Production investment validation, natural maturity, and deployment remain
separate future gates.
