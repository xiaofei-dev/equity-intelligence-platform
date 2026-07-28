# Equity Intelligence Platform

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
- Initial deployment: Render
- Later deployment: Amazon ECS Fargate and Amazon RDS

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
- [MVP Scope](docs/mvp-scope.md)
- [System Architecture](docs/architecture.md)
- [Local Development](docs/development.md)
- [Investment Methodology](docs/investment-methodology.md)
- [Tactical Signal v2.1 Methodology](docs/tactical-signal-v2-1-methodology-2026-07-28.md)
- [Long-Horizon Research Rating v1](docs/long-horizon-research-rating-v1-2026-07-28.md)
- [Analytics Model Interface v1](docs/analytics-model-interface-v1.md)
- [Forward Decision-Quality Final Offline Acceptance](docs/forward-decision-quality-final-acceptance-2026-07-28.md)
- [Analytics Stage Closeout](docs/analytics-stage-closeout-2026-07-28.md)
- [AI Analysis](docs/ai-analysis.md)
- [Data and Backtesting](docs/data-and-backtesting.md)
- [Quantitative Screening Design](docs/quantitative-screening.md)
- [Quantitative Screening v1 Specification and Data Acceptance Plan](docs/quantitative-screening-v1-specification.md)
- [Data Source Validation Matrix](docs/data-source-validation-matrix.md)
- [Provider Acceptance Report: 2026-07-26](docs/provider-acceptance-report-2026-07-26.md)
- [Screening Internal API Contract v1](docs/screening-api-contract.md)
- [Objective Rating v1 Validation Report](docs/objective-rating-v1-validation.md)
- [Roadmap](docs/roadmap.md)
- [Decision Log](docs/decision-log.md)
- [Development Log](docs/development-log/README.md)

## Current Status

Phase 0 is complete and Phase 1 analytics has reached an engineering
acceptance checkpoint. The complete local stack runs through Docker Compose,
and GitHub Actions validates the frontend, backend, analytics service, and full
Git history for secrets.

The current analytics foundation includes:

- provider-neutral, point-in-time-aware market and fundamental evidence
  boundaries;
- deterministic `LONG-HORIZON-RESEARCH-v1.0.0` and
  `TACTICAL-SIGNAL-v2.1.0` models behind one stable versioned interface;
- a sealed current-decision-only `QC-v1.0.0` snapshot for 136 securities;
- daily tactical one-week, one-month, and three-month opportunity states with
  separate entry value, extension risk, actionability, expiry, and risk caps;
- a source-backed AI review contract that remains separate from deterministic
  scores; and
- an accepted Forward Decision-Quality framework with transaction costs,
  slippage, cash, sector ETF, and SPY counterfactuals.

Market-data ingestion remains replaceable through `MARKET_DATA_PROVIDER`.
EODHD is the current bounded licensed source, yfinance is used only for
development or bounded cross-checking, and Twelve Data remains supported
through the same normalized boundary. Provider acceptance does not by itself
make a security scoreable; formula readiness and explicit missing-data states
remain separate gates.

Forward Validation is operationally ready but not a performance result. No
prospective signal has yet matured through the 5-, 20-, or 60-trading-day
horizon, and `statisticalEdgeProven` remains `NOT_ESTABLISHED`.

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
