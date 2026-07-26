# Equity Intelligence Platform

Equity Intelligence Platform is a decision-support system for systematic equity research and portfolio construction. It combines deterministic quantitative screening, evidence-based AI research, explicit portfolio rules, and continuous performance evaluation.

The platform is not intended to guarantee returns, replace human judgment, or execute trades automatically. Its purpose is to improve research consistency, reduce emotional decision-making, and make every recommendation explainable and reproducible.

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
Deterministic eligibility filters
            |
            v
Sector and stock ranking
            |
            v
Evidence-based AI risk review
            |
            v
Explicit composite scoring
            |
            v
Short-term and long-term portfolio rules
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
- [Investment Methodology](docs/investment-methodology.md)
- [AI Analysis](docs/ai-analysis.md)
- [Data and Backtesting](docs/data-and-backtesting.md)
- [Roadmap](docs/roadmap.md)
- [Decision Log](docs/decision-log.md)

## Current Status

The project is in the initial setup phase. Product boundaries and the first architecture decisions have been documented. Application frameworks have not yet been initialized.
