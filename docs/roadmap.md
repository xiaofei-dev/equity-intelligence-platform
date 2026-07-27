# Roadmap

## Current Position

Phase 0 is complete. Phase 1 has a visible six-security market-data path. The
next analytics milestone is provider and methodology validation, not a claim
that the current engineering universe is a production screen.

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

## Phase 1B: Data and Methodology Validation - Next

- [x] Define the 20-security provider-validation universe
- [x] Define reference, price, corporate-action, and fundamental data contracts
- [ ] Validate point-in-time dates, adjustments, identifiers, null handling,
  and SEC consistency
- [ ] Validate sector and industry normalization
- [ ] Add major sector ETF history for sector market-condition research
- [ ] Approve or reject the leading paid provider candidate
- [x] Document the first factor definitions and exclusion rules

Exit condition: required inputs for the first two strategy paths are available,
traceable, and proven suitable for historical use.

## Phase 2: Explainable Quantitative Screening

- Implement general-company eligibility and data-quality filters
- Implement `Quality Compounder`
- Implement `Undervalued Quality`
- Compare within sector, size, company-type, and strategy cohorts
- Preserve raw factors, normalized contributions, exclusions, and confidence
- Version strategy configuration
- Store candidate and coverage snapshots
- Evaluate a 300-to-500-security stratified sample
- Compare with passive and simple-factor baselines

Exit condition: deterministic rankings are reproducible, explainable, and
evaluated without obvious point-in-time or survivorship leakage.

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
