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
