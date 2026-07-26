# Repository Guidance

## Project Mission

Build an explainable equity research and portfolio decision-support platform that combines quantitative analysis, AI-assisted evidence review, and explicit risk controls.

## Language

All repository content must be written in English, including:

- Source code and identifiers
- Code comments
- Documentation
- User interface text
- API fields and error messages
- Database objects
- Test names
- Commit messages

The user may communicate with Codex in Chinese, but repository artifacts must remain in English.

## Architecture

- `frontend`: Next.js and TypeScript user interface
- `backend-java`: Spring Boot system of record and public API
- `analysis-python`: FastAPI analytics, screening, backtesting, and AI research
- `database`: PostgreSQL migrations and database-related assets
- `docs`: Product, architecture, and methodology documentation

The frontend communicates with Spring Boot. Spring Boot owns user-facing business workflows and calls the Python analytics service through a versioned internal contract.

## Engineering Rules

- Keep modules cohesive and dependencies explicit.
- Prefer a modular monolith plus one analytics service over premature microservices.
- Use environment variables for runtime configuration.
- Never commit secrets, API keys, credentials, or private financial data.
- Provide health checks for deployable services.
- Use database migrations for schema changes.
- Keep important state out of container-local filesystems.
- Use structured logs and stable error codes.
- Design long-running analysis as identifiable tasks with idempotent execution.
- Record relevant data timestamps and strategy, prompt, and model versions.
- Add tests for business rules, scoring logic, data transformations, and API contracts.

## Investment and AI Safety Rules

- Do not claim or imply guaranteed investment returns.
- Do not present backtested performance as proof of future performance.
- Do not enable automatic brokerage execution in the MVP.
- Do not let an LLM independently determine final portfolio weights or trade decisions.
- Treat LLM output as untrusted until validated against source material.
- Require citations, source timestamps, and confidence indicators for AI research.
- Distinguish observed facts, deterministic calculations, model inferences, and human decisions.
- Keep scoring formulas explicit, versioned, and reproducible.
- Include transaction costs, slippage, and realistic data availability in strategy evaluation.
- Prevent look-ahead bias, survivorship bias, and train-test contamination.

## Scope Discipline

The MVP should focus on one equity market, daily data, research assistance, simulated portfolios, and performance tracking. Do not introduce Kafka, Kubernetes, automated trading, high-frequency data, social features, billing, or multiple markets without an approved requirement.

## Documentation Maintenance

When a product or architecture decision changes, update the relevant document and append a dated entry to `docs/decision-log.md`. Code and documentation should not intentionally contradict each other.

