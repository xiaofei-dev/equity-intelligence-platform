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

The normative future engine and sleeve boundaries are frozen separately in
[Dual-System Architecture Contract v1](dual-system-architecture-contract-v1.md).
The Fundamental Value and Quantitative Trading systems produce independent
outputs for `LONG_TERM_CORE` and `QUANT_TRADING`. The Unified Portfolio/Risk
View consumes those outputs by immutable reference and never averages their
scores.

## Implemented Vertical Slices

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

Market Intelligence adds an implemented end-to-end composition and persistence
slice:

```text
Provider-neutral observations and explicit coverage states
    -> deterministic objective, tactical, valuation, and horizon inputs
    -> durable FastAPI Market Intelligence profile
    -> PostgreSQL V17 immutable profile and screening result
    -> Spring Boot /api/v1/market-intelligence/*
    -> Next.js /research
```

Daily Refresh v1 adds a separate V16 operational slice:

```text
Dataset-specific freshness
    -> bounded refresh plan
    -> resumable per-security tasks and checkpoints
    -> append-only observations and corporate actions
    -> usage telemetry and updated freshness
```

Python remains the formula and analytics owner. Spring Boot publishes stable
DTOs, resolves the closed-test identity, and translates sanitized errors.
Next.js calls Spring Boot only and never receives provider or database
credentials.

The 66-universe Daily Refresh operator adds an aggregate no-network preflight
and confirmed workflow:

```text
workflow-preflight
    -> exact universe/session/configuration/budget token
    -> workflow-run: prices -> actions -> fundamentals
    -> stop before the next provider on any non-success result
```

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

The current compatibility implementation treats normalized ticker symbols as
unique ingestion identities and exchange labels as mutable metadata. This is
not the frozen identity target. Task 1 must introduce durable company,
instrument, share-class, listing, ticker-assignment, and provider-mapping
identities while retaining `analytics.security.public_id` as the compatibility
anchor. Ambiguous identities must remain unresolved rather than being inferred.

Task 1 Stage 1 now carries and validates that complete durable identity tuple
through a migration-free internal evidence-selection contract. It also
requires completed-session chronology, full provider lineage, explicit
freshness/conflict states, and versioned deterministic fallback. This is an
input contract that V22 now persists through a separate append-only
successor. Stage 3A adopts the exact reachable Forward/portfolio V18-V21
lineage without rewriting its versions or checksums because V21 application is
not provable. Stage 3B implements V22 as the separate append-only Task 1
successor.

V21 is legacy and unwired. Its historical `CORE` and `TACTICAL` lanes are not
aliases for `LONG_TERM_CORE` and `QUANT_TRADING`, and no application may bind
V21 records to the accepted dual-system contract. Future dual-system
persistence requires an append-only successor migration rather than a
reinterpretation of V21.

V22 is analytics-owned and persists:

- company, instrument, share-class, listing, and ticker-assignment identity;
- versioned trading calendars and completed sessions;
- private raw-manifest lineage without licensed payloads;
- normalized and engine-derived canonical evidence with revisions, hashes,
  freshness, conflicts, tolerances, explicit non-valid states, explicit
  parent IDs and hashes, sealed parent sets, and mandatory successor
  corrections;
- sealed versioned selector policies, provider priority, requests, candidates,
  per-candidate rejection reasons, and immutable results; and
- classification-bound Fundamental Value applicability routing without a
  valuation formula or score.

The Python V22 adapter revalidates evidence, complete selector aggregates, and
applicability routing on both write and read, including recomputation of
policy, request, result, and routing content hashes. Provider codes remain audit and
deterministic-priority inputs, never model-score inputs. Recursive canonical
and policy JSON validation rejects provider score, rank, and recommendation
leakage.

Selector result hashes bind the request identifier and verified request hash,
policy identity and hash, selector output, and the complete canonical
per-candidate rejection map. This permits distinct requests with equal
outcomes while preserving exact replay and rejecting a changed rejection
classification.

Completed sessions bind their declared date to scheduled open and close in the
declared IANA timezone. Derived liquidity binds one distinct completed-session
parent per valid observation and binds the latest parent to the declared
window end. Selector seals classify every supplied candidate, including
request-mismatch candidates, with a deterministic rejection reason.
Applicability routing follows the frozen company-type map and permits only a
hash-verified, monotonic successor of the latest route.

Stage 3C exposes V22 through internal-only FastAPI projections. Selection
commands carry canonical decision context and persisted evidence IDs; Python
hydrates and revalidates each candidate before running and sealing the
deterministic selector. Readback recomputes aggregate hashes, and
applicability lookup returns the single unsuperseded route for a company and
governed routing version. These endpoints do not replace Spring Boot public
APIs.

The provider evidence adapter contract is the terminal boundary for Yahoo,
EODHD, and future replacements. Provider-native fields and licensed raw
payloads remain inside an adapter and private Git-ignored storage. The
provider-neutral refresh coordinator receives only canonical typed evidence,
then reuses the existing execution lease, immutable journals, content-hashed
checkpoints, and fail-closed resume rules before V22 persistence. It is not
started by FastAPI lifespan and has no automatic provider-execution path.
Canonical adapter requests derive their UUID from the complete durable
security identity, listing presentation, completed-session/calendar context,
domain, fields, and requested date range. Daily overlap and backfill rows may
span that range, whose end remains the completed session. Batches are
nonempty, UUID-unique, strictly reparsed, and exactly bound; exact evidence
replay across refresh runs reuses the immutable row while content drift under
the same evidence identity fails closed.

Corporate-action adapter output binds its canonical action to the generic
`CORPORATE_ACTION` request field and keeps `effectiveDate` inside the inclusive
request range. Fundamental output binds `metricCode` to a requested field and
uses snapshot/as-of semantics: `periodEnd` may precede `startDate` but must not
exceed `endDate`; `startDate` is transport and planning context, not a fiscal
period lower bound. Classification is also a snapshot: requested classification
fields map explicitly to canonical fields, and
`effectiveFrom` may precede `startDate` but must not exceed `endDate`.
Non-VALID evidence carries no fabricated canonical data. Daily-price and
corporate-action scopes use the local date of `effectiveAt` inside the inclusive
range. Fundamental and classification absence may predate `startDate` but must
not exceed `endDate`; adapters should normally timestamp snapshot absence at
`endDate`.

The Stage 3C provider-adapter scope checker rejects unimplemented domains by
default. In particular, market benchmarks, sector benchmarks, and
engine-derived liquidity cannot pass through a descriptor merely because it
advertises the domain; they require a separately implemented governed adapter
or engine path with explicit field and chronology binding.

Task 1 Stage 3C is accepted on bounded local evidence. The final adapter module
reported 33 passing tests and Ruff passed. A fresh disposable PostgreSQL 17
database migrated from V1 to V22 passed all three typed Python/PostgreSQL
integration tests; the complete migration, upgrade, refusal, base, and
advanced matrix had already passed on the unchanged V22 schema. This does not
claim a business-database deployment or provider execution.

V22 does not contain enough state for governed raw-payload deletion. A future
append-only successor must bind each raw manifest to a versioned retention
policy and legal-hold state and record an ordered immutable disposition-event
chain with proofs and enforced cardinality. V23 is deferred for the MVP and
becomes necessary only if the product assumes physical raw-object
retention/deletion governance. Stage 3C does not create that migration or
delete raw payloads.

Stage 2 adds exact canonical payload contracts for prices and adjustment
modes, corporate actions, fundamental periods, classifications, dated market
and sector benchmarks, and engine-derived liquidity. Normalized observations
bind to private raw manifests by source hash. Derived liquidity binds to
ordered parent evidence IDs and hashes plus a versioned output hash.
Provider-native payload fields cannot cross this boundary.

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

Render is the planned initial closed-test platform:

- Web service for Next.js
- Web service for Spring Boot
- Private service or worker for Python
- Managed PostgreSQL on a private connection
- Scheduled jobs for daily updates

The first database deployment uses one managed PostgreSQL database with
separate `app.*` and `analytics.*` ownership boundaries, encrypted deployment
secrets, TLS, automated backups, and one migration authority. Runtime database
credentials must not own DDL. See
[Database Deployment v1](database-deployment-v1.md).

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
