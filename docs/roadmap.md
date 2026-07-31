# Roadmap

## Current Position

Phase 0, the first end-to-end market-data slice, and the internal Market
Intelligence data and screening foundation are complete. The current
checkpoint includes Market Intelligence persistence through V17, the Forward
DQV migration chain through V20, legacy/unwired V21 portfolio-decision
persistence, the V22 Unified Market Data and Evidence Foundation,
provider-neutral model and refresh interfaces, durable security profiles,
sector/industry/security screening, a 136-security QC snapshot, frozen
Tactical Signal v2.2 and Long Horizon v1.1 contracts, and local Forward
Decision-Quality v2 contracts.
The repository migration and isolated-test head is V22; V17 remains the last
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
- [x] Defer V23 for the MVP and keep raw-payload retention, legal-hold, and
  deletion governance outside Task 1 without adding deletion operations

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
reported no residual blocker. V23 is deferred until physical raw-object
retention/deletion governance becomes product scope.

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
