# Roadmap

## Current Position

Phase 0 is complete. Phase 1 is in progress: the market-data path reaches the
browser, while the minimal quantitative candidate path remains the next
milestone.

## Phase 0: Foundation — Complete

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

## Phase 1: End-to-End Vertical Slice — In Progress

- [x] Select United States equities and Twelve Data for the first slice
- [x] Ingest the six-symbol engineering universe
- [x] Store normalized daily price data
- [x] Expose latest stored observations through Spring Boot
- [x] Display latest observations in Next.js
- [ ] Calculate a minimal, versioned factor set
- [ ] Expose candidate rankings through FastAPI
- [ ] Call the candidate contract from Spring Boot
- [ ] Display candidate rankings and score explanations in Next.js

Exit condition: one stock moves through the complete data-to-interface path.

## Phase 2: Explainable Screening

- Implement eligibility filters
- Add sector ranking
- Add factor normalization
- Add score breakdowns
- Version strategy configuration
- Store daily candidate snapshots

Exit condition: candidate rankings are reproducible and explainable.

## Phase 3: AI Research

- Retrieve source documents
- Extract source metadata
- Define the AI output schema
- Add citation validation
- Add risk and counterargument analysis
- Store prompt and model versions
- Add safe failure behavior

Exit condition: candidate reports are source-backed, structured, and reviewable.

## Phase 4: Portfolio and Evaluation

- Define short-term and long-term sleeves
- Add portfolio constraints
- Create simulated transactions
- Add benchmark comparison
- Add performance and drawdown metrics
- Add immutable recommendation review

Exit condition: the platform supports paper portfolios and honest performance evaluation.

## Phase 5: Public Demo

- Improve user experience
- Add authentication appropriate for a demo
- Add monitoring and structured logs
- Add secure secret handling
- Deploy to Render
- Add a public project overview and demonstration flow

Exit condition: a reviewer can access and understand the product without local setup.

## Phase 6: Production Learning

- Extend the existing GitHub Actions baseline for deployment
- Add stronger observability
- Add backup and recovery procedures
- Migrate a deployment to Amazon ECS Fargate and Amazon RDS
- Document architecture tradeoffs and operational lessons

Exit condition: the project demonstrates a credible cloud deployment path.

## Deferred Capabilities

The following require separate approval and demonstrated need:

- Redis-based task processing
- Kafka event streaming
- Kubernetes
- Multiple equity markets
- Native mobile applications
- Brokerage connectivity
- Automated execution
- Commercial billing
