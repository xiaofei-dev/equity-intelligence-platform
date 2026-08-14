# Equity Intelligence Platform

## Unified Portfolio and Risk Context

Task 4 now provides a human-controlled `/portfolio` workspace over an immutable
V28 risk context. The view keeps `LONG_TERM_CORE` and `QUANT_TRADING` separate,
binds the calculation to V12 account snapshots and a versioned constraint
policy, preserves missing valuations, and shows cash, liabilities,
concentration, and risk reasons. Spring owns the public workflow, FastAPI owns
the stateless calculation, and Next.js reads Spring only. Human reviews are
immutable; final weights, orders, brokerage execution, and LLM decision
authority remain prohibited. See
[Unified Portfolio and Risk Context v1](docs/unified-portfolio-risk-context-v1.md).

## Quantitative Trading

The independent Quantitative Trading sleeve has a deterministic Python engine,
event-driven portfolio simulator, and frozen historical-validation boundary.
The first `MOMENTUM_CONTINUATION` strategy is reproducible but rejected for
production: its development-only current-survivor replay produced 1.13% CAGR
versus 13.68% for SPY. Its evidence label remains `NOT_VALIDATED`.

A distinct post-outcome `DUAL_MOMENTUM_TREND` v1.1 successor completed one
controlled development replay and was not directionally supportive against
SPY, so its evidence label remains `NOT_VALIDATED`. The Python service now has
a provider-neutral V22 read/assembly boundary for exact 253-session histories,
durable identity, completed-session authority, and fail-closed common-stock/SPY
applicability. V27, FastAPI, Spring Boot, and Next.js now provide an immutable
research-signal product slice with candidate/hold/exit/no-signal states and
entry/stop context. The public path is GET-only and prohibits final weights,
orders, brokerage instructions, AI authority, and guaranteed-return claims.
Portfolio execution and production validation claims remain closed. See
[Quantitative Trading System v1](docs/quant-trading-system-v1.md).

Quant v2 implements a separately versioned regime-filtered mean-reversion
engine, trade simulator, and one-pass historical runner. Its controlled replay
was not directionally supportive: USD 100,000 became USD 107,516.24 at 0.63%
CAGR versus USD 434,189.17 and 13.53% CAGR for SPY. The result is sealed
`NOT_VALIDATED` with no same-outcome retuning. It is retained as reproducible
research code and is intentionally not promoted into the public decision path.
See [Quant v2 methodology](docs/quant-trading-v2-methodology-2026-08-13.md).

Equity Intelligence Platform is a decision-support system for systematic equity research and portfolio construction. It combines deterministic quantitative screening, evidence-based AI research, explicit portfolio rules, and continuous performance evaluation.

The platform is not intended to guarantee returns, replace human judgment, or execute trades automatically. Its purpose is to improve research consistency, reduce emotional decision-making, and make every recommendation explainable and reproducible.

[![CI](https://github.com/xiaofei-dev/equity-intelligence-platform/actions/workflows/ci.yml/badge.svg)](https://github.com/xiaofei-dev/equity-intelligence-platform/actions/workflows/ci.yml)

## Product Objectives

1. Improve the user's existing investment process through measurable, risk-aware analysis.
2. Serve as a production-quality portfolio project demonstrating full-stack, backend, data, AI, and cloud engineering skills.
3. Establish a foundation that could evolve into a commercial financial research product after user validation and compliance review.

## Planned Technology Stack

- Frontend: Next.js and TypeScript
- Main backend: Java 21 and Spring Boot
- Analytics service: Python and FastAPI
- Database: PostgreSQL
- Local orchestration: Docker Compose
- Initial closed-test deployment: Render managed services and managed
  PostgreSQL
- Later production-learning deployment: Amazon ECS Fargate and Amazon RDS

## Repository Structure

```text
equity-intelligence-platform/
|-- frontend/
|-- backend-java/
|-- analysis-python/
|-- database/
|-- docs/
|-- AGENTS.md
`-- README.md
```

## Core Product Flow

```text
Market and fundamental data
            |
            v
Point-in-time data and eligibility filters
            |
            v
Strategy-specific stock rankings
            |
            v
Evidence-based AI risk review
            |
            v
AI-reviewed candidate set
            |
            v
User portfolio fit and constrained scenarios
            |
            v
Human review and simulated execution
            |
            v
Performance tracking and strategy evaluation
```

## Documentation

- [Product Vision](docs/product-vision.md)
- [Current Project State](docs/current-state.md)
- [MVP Scope](docs/mvp-scope.md)
- [System Architecture](docs/architecture.md)
- [Dual-System Architecture Contract v1](docs/dual-system-architecture-contract-v1.md)
- [Unified Market Data and Evidence Foundation v1](docs/unified-market-data-evidence-foundation-v1.md)
- [Fundamental Value Investment System v1](docs/fundamental-value-investment-system-v1.md)
- [Fundamental Value v1 Contract](docs/fundamental-value-contract-v1.md)
- [Fundamental Value Stage 4 Acceptance](docs/fundamental-value-investment-system-v1-stage-4-acceptance-2026-07-31.md)
- [Database Deployment v1](docs/database-deployment-v1.md)
- [Local Development](docs/development.md)
- [Investment Methodology](docs/investment-methodology.md)
- [Model Validation Master Plan v2](docs/model-validation-master-plan-v2.md)
- [Tactical Signal v2.2 Methodology](docs/tactical-signal-v2-2-methodology-2026-07-29.md)
- [Long-Horizon Research Rating v1.1](docs/long-horizon-research-rating-v1-1.md)
- [Historical Walk-Forward Validation v2](docs/historical-walk-forward-validation-v2.md)
- [Practical Tactical v2.2 Tier-1 Backtest](docs/practical-tactical-v2-2-backtest-v1.md)
- [Practical Long Horizon v1.1 Tier-1 Backtest](docs/practical-long-horizon-v1-1-tier1-backtest-2026-07-30.md)
- [Forward Decision Snapshot v2](docs/forward-decision-snapshot-v2.md)
- [Forward Decision-Quality Validation v2](docs/forward-decision-quality-validation-v2.md)
- [End-to-End Validation Completion Gap Audit](docs/end-to-end-validation-completion-gap-audit-2026-07-29.md)
- [Forward Validation v2 Persistence Decision](docs/forward-validation-v2-persistence-decision.md)
- [Analytics Model Interface v1](docs/analytics-model-interface-v1.md)
- [Market Intelligence and Screening v1](docs/market-intelligence-screening-v1.md)
- [Market Intelligence Vertical Slice v1 Closeout](docs/market-intelligence-vertical-slice-v1-closeout-2026-07-28.md)
- [Forward Prospective Enrollment v1 Closeout](docs/forward-prospective-enrollment-v1-closeout-2026-07-28.md)
- [Forward Decision-Quality Final Offline Acceptance](docs/forward-decision-quality-final-acceptance-2026-07-28.md)
- [Analytics Stage Closeout](docs/analytics-stage-closeout-2026-07-28.md)
- [AI Analysis](docs/ai-analysis.md)
- [Data and Backtesting](docs/data-and-backtesting.md)
- [Licensed Market Data Publication Policy](docs/licensed-market-data-publication-policy.md)
- [Historical Decision-Quality Validation v1](docs/historical-decision-quality-validation-v1.md)
- [Market Intelligence Data Model v1](docs/market-intelligence-data-model-v1.md)
- [Market Intelligence Screening v1 Persistence Mapping](docs/market-intelligence-screening-persistence-v1.md)
- [Quantitative Screening Design](docs/quantitative-screening.md)
- [Quantitative Screening v1 Specification and Data Acceptance Plan](docs/quantitative-screening-v1-specification.md)
- [Data Source Validation Matrix](docs/data-source-validation-matrix.md)
- [Daily Market Data Refresh v1](docs/daily-market-data-refresh-v1.md)
- [Provider Acceptance Report: 2026-07-26](docs/provider-acceptance-report-2026-07-26.md)
- [Screening Internal API Contract v1](docs/screening-api-contract.md)
- [Objective Rating v1 Validation Report](docs/objective-rating-v1-validation.md)
- [Roadmap](docs/roadmap.md)
- [Decision Log](docs/decision-log.md)
- [Development Log](docs/development-log/README.md)

## Current Status

Phase 0 and the local Market Intelligence end-to-end engineering slice are
implemented through their PostgreSQL V17 boundary. The append-only migration
chain continues with the V18-V21 Forward DQV and portfolio lineage and the V22
Unified Market Data and Evidence Foundation. The complete local stack runs
through Docker Compose. Spring Boot publishes the versioned Market
Intelligence API, and Next.js provides the `/research` screening and durable
profile workspace.

Task 1 Stage 3A carries an exact, curated V18-V21 Forward/portfolio migration
lineage from reachable commit `87e2a88`; its PostgreSQL 17 matrix is accepted.
V21 remains legacy and unwired: its `CORE`/`TACTICAL` lanes are not the
accepted `LONG_TERM_CORE` and `QUANT_TRADING` sleeves. Stage 3B adds the
append-only V22 Unified Market Data and Evidence Foundation successor with
durable identity, completed-session, lineage, canonical evidence, selector,
and specialized-model applicability persistence. V22 does not reinterpret or
wire V21. The controller accepted its exact PostgreSQL 17 migration matrix
and fresh-database typed Python round trips.

Migration-free Stage 3C adds internal-only FastAPI selection/readback and
model-applicability projections plus an offline provider-adapter refresh
coordinator. It reuses the existing lease, journal, checkpoint, and resume
controls and performs no provider fetch at service startup. No public Spring
API is replaced. Task 1 is accepted: the final adapter module passed 33 tests
and Ruff, and all three typed Python/PostgreSQL integration tests passed on a
fresh disposable PostgreSQL 17 database migrated from V1 to V22. This is
bounded test evidence, not a business-database deployment or provider run.

Task 2 Stage 1 now freezes the Fundamental Value Investment System v1 contract
for mature nonfinancial companies and reserves V23 for its narrowly scoped
append-only persistence successor. V23 will not contain raw-retention,
deletion, or legal-hold governance. Governed raw-payload deletion remains
unimplemented; any future approved retention successor must use the next
available migration version after V23.

Stages 2 and 3 add the pure deterministic core and strict V22 evidence
assembly. Stage 4 adds append-only V23 persistence for both honest non-usable
assemblies and future complete deterministic results, including ordered
relational evidence parents and typed hash/core replay. Current real
mature-company evidence remains incomplete and the model remains
`NOT_VALIDATED`; the V23 synthetic valid fixture proves storage mechanics only.

The current analytics foundation includes:

- provider-neutral, point-in-time-aware market and fundamental evidence
  boundaries;
- deterministic `LONG-HORIZON-RESEARCH-v1.1.0` and
  `TACTICAL-SIGNAL-v2.2.0` models with accepted immutable freeze records;
- a sealed current-decision-only `QC-v1.0.0` snapshot for 136 securities;
- daily tactical one-week, one-month, and three-month opportunity states with
  separate entry value, extension risk, actionability, expiry, and risk caps;
- a source-backed AI review contract that remains separate from deterministic
  scores;
- durable Market Intelligence profiles and sector, industry, and
  security-level screening contracts;
- a provider-neutral daily refresh planner with resumable PostgreSQL tasks,
  checkpoints, freshness states, and usage telemetry; and
- a versioned 66-security universe plus aggregate no-network preflight and
  one-command confirmed daily refresh workflow;
- public Spring Boot screening, profile, search, and facets endpoints;
- a Next.js research list and security/profile detail workspace; and
- an accepted Forward Decision-Quality framework with transaction costs,
  slippage, cash, sector ETF, and SPY counterfactuals.

Market-data ingestion remains replaceable through versioned provider adapters.
The closed-test vertical slice uses yfinance for bounded daily prices and EODHD
for bounded fundamentals and corporate actions. The approved recovery completed
the 57-security price scope, 57-security corporate-action scope, and 55-security
fundamental scope. ACN retained 259 valid completed sessions while its malformed
2026-07-28 bar was rejected; its latest price freshness is explicitly
`STALE/LATE_DATA` rather than fabricated. Provider acceptance does not by itself
make a security scoreable; formula readiness and explicit missing-data states
remain separate gates.

The existing V11 Forward bridge is operationally ready but not a performance
result. No
prospective signal has yet matured through the 5-, 20-, or 60-trading-day
horizon, and `statisticalEdgeProven` remains `NOT_ESTABLISHED`. The typed
V17-to-V11 bridge has recorded an idempotent `NO_ELIGIBLE_SIGNALS` attempt for
the current screen; it created no signal or outcome row. The 12-month-plus
model remains context only.

The strict historical terminals remain blocked where complete PIT inputs
cannot be reconstructed. A separate Practical Tier-1 current-universe
retrospective now executes the frozen models instead of stopping at engineering
readiness. Tactical v2.2 is unsupported at five sessions, mixed at 20
sessions, and modestly directionally positive at 60 sessions. Long Horizon
v1.1 shows modest one-year SPY-relative association for its Business Quality
top cohort, but not validated score ordering; Security Attractiveness remains
unvalidated. These claims retain survivorship and provider-revision
limitations and are deliberately weaker than repeatable excess-return proof.

The local Forward v2 infrastructure now includes the append-only V18 outcome
ledger, the accepted V19/v2.1.1 chronology boundary, the V20 benchmark-outcome
successor, the offline Gate H maturity evaluator, a strict
maturity-to-statistics adapter, and the frozen Forward DQV statistics engine.
These are offline engineering capabilities, not a performance result. The
target post-close session has not completed, the real 66-security inputs and
six-family controlled benchmark ledger are not sealed, no prospective
v2.1.1 enrollment or naturally matured outcome exists, and no statistics run
has occurred. The authoritative prospective Gate Z conclusion is
`CRITICAL_BLOCKED_NOT_VALIDATED`; neither model is Forward-validated.

The separately named
[Dual-System Architecture Contract v1](docs/dual-system-architecture-contract-v1.md)
is now frozen. It defines independent Fundamental Value and Quantitative
Trading systems, isolated `LONG_TERM_CORE` and `QUANT_TRADING` sleeves, and a
Unified Portfolio/Risk View that never averages their scores. This is a
contract milestone. Completed Task 1 adds the deterministic provider-neutral
evidence-selection kernel, canonical Git-safe fixtures for prices, actions,
fundamentals, classifications, benchmarks, and liquidity, V22 persistence,
and internal-only FastAPI selection, readback, applicability, and offline
refresh coordination. It does not change scoring behavior, expose a public
Spring selector API, or enable brokerage execution.

The local engineering path is described in the
[Vertical Slice closeout](docs/market-intelligence-vertical-slice-v1-closeout-2026-07-28.md).
Its real-data acceptance is deliberately `PARTIAL`: 66 durable profiles and an
honest `NO_ELIGIBLE_RESULTS` screen were produced after the bounded provider
refresh completed. `PARTIAL` describes product eligibility, not an unfinished
provider run: all 66 profiles remain explicitly excluded from deterministic
ranking until their required evidence is ready. No cloud database, production
scheduler, public registration, or automatic trading is active.

## Quick Start

Prerequisites:

- Node.js 20.9 or later
- Java 21
- Python 3.12 through 3.14
- Docker Desktop with Docker Compose

Start the complete local environment:

```powershell
Copy-Item .env.example .env
docker compose up --build
```

Set the credential required by the selected provider in the local `.env`
file. Twelve Data uses `TWELVE_DATA_API_KEY`; EODHD uses `EODHD_API_KEY`;
yfinance does not use an API key. Never commit `.env` or place credentials in
browser-exposed variables.

Then open:

- Frontend: `http://localhost:3000`
- Market data page: `http://localhost:3000/market-data`
- Backend health: `http://localhost:8080/actuator/health`
- Analytics health: `http://localhost:8000/health`

See [Local Development](docs/development.md) for service-specific commands,
tests, configuration, and troubleshooting.
