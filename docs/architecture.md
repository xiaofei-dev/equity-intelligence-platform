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
   +-----------> Market, fundamental, news, and filing providers
   |
   +-----------> OpenAI API
```

This structure combines enterprise business-system practices in Java with the Python data and quantitative ecosystem.

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

The analytics service returns structured results through versioned contracts.

### Database

The initial system uses one PostgreSQL instance with clear ownership boundaries. Separate schemas may be used:

```text
app.*
analytics.*
```

The applications must not modify each other's tables without an explicit contract and migration.

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

