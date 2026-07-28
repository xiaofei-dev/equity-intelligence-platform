# Roadmap

## Current Position

Phase 0 and the first end-to-end market-data slice are complete. The current
analytics checkpoint includes a bounded EODHD current-decision route,
provider-neutral model interfaces, a 136-security QC snapshot, Tactical Signal
v2.1, and an accepted Forward Decision-Quality framework.

Historical point-in-time UQ validation, prospective outcome maturation,
source-verified AI operation, and portfolio recommendation workflows remain
separate later gates. The current engineering acceptance is not a claim of
proven excess returns.

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
- [ ] Mature prospective sector, SPY, cash, and simple-policy comparisons

Current status: deterministic current-decision rankings are reproducible and
explainable. Historical leakage and survivorship claims remain unproven;
prospective Forward evidence is `PENDING_FUTURE_OUTCOMES`.

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
- Deploy to Render
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
