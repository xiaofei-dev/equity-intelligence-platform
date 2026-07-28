# System Architecture

## Architecture Style

The initial system uses a modular main application and a separate analytics service:

```text
Browser
   |
   v
Next.js frontend
   |
   v
Spring Boot backend
   |
   +-----------> PostgreSQL
   |
   v
FastAPI analytics service
   |
   +-----------> Replaceable market and fundamental providers
   |
   +-----------> SEC filings and trusted evidence sources
   |
   +-----------> AI model API
```

This structure combines enterprise business-system practices in Java with the Python data and quantitative ecosystem.

## Implemented Vertical Slice

The current Phase 1 path is:

```text
Configured market-data provider
(Twelve Data, yfinance, or EODHD)
    |
    v
FastAPI ingestion endpoint
    |
    v
PostgreSQL analytics.security and analytics.daily_price
    |
    v
Spring Boot GET /api/v1/market-data/latest
    |
    v
Next.js /market-data
```

The browser receives normalized records from Spring Boot. It never receives
provider credentials and does not call FastAPI or PostgreSQL directly.
The provider-validation and quantitative candidate paths remain the next
unimplemented analytics slices.

The screening integration adds a second backend slice:

```text
Immutable SEC and price observations
    -> sealed analytics.data_snapshot
    -> PostgreSQL-backed FastAPI screening task
    -> immutable coverage, factors, and ratings
    -> Spring Boot /api/v1/screening/*
```

FastAPI owns snapshot construction, point-in-time observation selection,
rating execution, recovery, and result persistence. Spring Boot is an HTTP
gateway for the versioned contract and does not query screening result tables.

## Component Responsibilities

### Frontend

The Next.js application owns:

- User-facing navigation and presentation
- Candidate lists and filters
- Charts and score explanations
- Research report presentation
- Simulated portfolio workflows
- Performance dashboards

The frontend calls the Spring Boot API. It does not call the Python analytics service directly.

### Main Backend

The Spring Boot application owns:

- Public API
- User and authorization concerns
- Watchlists
- Portfolio definitions
- Analysis task lifecycle
- Strategy configuration references
- Recommendation records
- Audit history
- Coordination with the analytics service

Spring Boot is the system of record for user-facing business workflows.

### Analytics Service

The FastAPI application owns:

- Market and fundamental data ingestion
- Data quality checks
- Indicator and factor calculation
- Universe screening
- Candidate ranking
- Backtesting
- Portfolio optimization calculations
- AI evidence preparation and structured analysis
- Coverage-state and data-lineage reporting

The analytics service returns structured results through versioned contracts.
Deterministic calculations and AI evidence assessments must remain separate in
those contracts.

### Database

The initial system uses one PostgreSQL instance with clear ownership
boundaries. Flyway creates separate schemas:

```text
app.*
analytics.*
```

Public market observations and reusable company research belong in
`analytics.*`. User identities, investment profiles, accounts, holdings,
decisions, and portfolio-specific recommendation records belong in `app.*`.
Python may write analytics-owned observations and results, but Java remains the
only owner of user-facing account and decision state.

The applications must not modify each other's tables without an explicit contract and migration.

Analytics observations use append-only revisions with economic, availability,
ingestion, and recording timestamps. Sealed data snapshots bind an analysis to
an as-of cutoff, ingestion cutoff, source manifest, universe version, and
normalization versions. Screening runs persist Python-owned coverage, factors,
ratings, contributions, and lineage under those immutable inputs.

The SEC normalization path resolves securities through immutable public IDs,
creates idempotent provider, ingestion-batch, and source lineage, and inserts
only observed or explicitly derived numeric facts. Its request identity
includes the source content hash, so a changed provider response creates a new
source revision instead of overwriting an earlier fact.

Python writes these records through the `analytics_writer` role. Java does not
query rating tables or reproduce formulas; it consumes screening status and
rating pages through the versioned internal HTTP contract. Database read
projections exist for analytics implementation and diagnostics, not as an
additional Java rating contract.

Every provider adapter emits the same normalized daily-price,
corporate-action, security-metadata, and lineage models. Provider-native field
names are removed before persistence or scoring. A sealed snapshot records one
market-data provider and one normalized adjustment mode, so price selection
cannot silently mix configured market providers. SEC EDGAR remains the primary
financial filing and revision-lineage authority.

Market Intelligence Data Model v1 extends this boundary with normalized
exchange and taxonomy references, point-in-time company profiles and lifecycle
evidence, explicit-status reusable metrics, sector/industry screening
aggregates, and PostgreSQL-backed daily refresh operations. These are all
Python-owned `analytics.*` objects. Spring Boot continues to own `app.*` and
must use a versioned HTTP contract before exposing refresh or group-screening
state.

The initial United States security master treats normalized ticker symbols as
unique ingestion identities and exchange labels as mutable metadata. A future
multi-market expansion requires a durable global identity design.

## Initial Communication Pattern

Spring Boot calls FastAPI through synchronous HTTP for bounded operations.

Long-running operations are represented as tasks:

```text
PENDING -> RUNNING -> SUCCEEDED
                  \-> FAILED
```

Every task should have:

- A stable task identifier
- An idempotency mechanism
- Input metadata
- Status and timestamps
- Failure details
- Strategy and model versions
- Result location or result payload

Daily market-data updates use the provider-neutral
`Daily Market Data Refresh v1` planner and worker. PostgreSQL owns its
cross-process advisory lock, resumable checkpoints, dataset-specific freshness,
and structured run status. Price freshness is never reused as fundamental-data
freshness or scoring eligibility.

Screening tasks use PostgreSQL as their queue. Workers acquire advisory locks,
recover pending or stale-running tasks after restart, and seal results in one
transaction. A security-level data failure is a coverage result; only a
run-level failure changes the task to `FAILED`.

Kafka may replace or supplement HTTP when event volume, multiple consumers, durable replay, or asynchronous reliability requirements justify it.

## Deployment

### Local Development

Docker Compose will coordinate:

- Frontend
- Spring Boot backend
- FastAPI analytics service
- PostgreSQL

### Initial Public Deployment

Render is the planned initial platform:

- Web service for Next.js
- Web service for Spring Boot
- Private service or worker for Python
- Managed PostgreSQL
- Scheduled jobs for daily updates

### Later Production Deployment

The planned migration target is:

- Amazon ECS Fargate
- Amazon RDS for PostgreSQL
- Amazon ECR
- Application Load Balancer
- Amazon CloudWatch
- Amazon S3
- EventBridge scheduled tasks

Kubernetes is deferred until cluster-level scaling, availability, or organizational requirements make it necessary.

## Portability Requirements

- Build every service as an independent container image.
- Read runtime configuration from environment variables.
- Keep secrets outside source control.
- Use standard PostgreSQL features where practical.
- Write application logs to standard output.
- Provide liveness and readiness endpoints.
- Avoid important state in ephemeral container filesystems.
- Do not use platform-specific APIs in core business logic.

## Future Evolution

Potential future additions include:

- Redis for caching and lightweight task coordination
- Kafka for durable event streaming
- Independent analytics workers
- Object storage for large source documents
- Kubernetes for multi-node container orchestration

These additions require an observed problem and an architecture decision record.
