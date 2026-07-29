# Spring Boot Backend

The Spring Boot application is the system of record and public API for the
Equity Intelligence Platform. The frontend calls this service; browser clients
must not call the Python analytics service directly.

## Implemented Contracts

- `GET /actuator/health`: service health
- `GET /api/v1/system/status`: stable application status
- `GET /api/v1/market-data/latest`: latest stored daily observation for every
  active security
- `POST /api/v1/market-intelligence/screening-runs`: create or replay an
  idempotent sealed-snapshot screen
- `GET /api/v1/market-intelligence/screening-runs/{runId}`: screening metadata
- `GET /api/v1/market-intelligence/screening-runs/{runId}/results`: paginated
  immutable results
- `GET /api/v1/market-intelligence/profiles/{profileId}`: immutable profile
- `GET /api/v1/market-intelligence/securities/{securityId}/profiles/latest`:
  latest available durable profile
- `GET /api/v1/market-intelligence/securities`: paginated security search
- `GET /api/v1/market-intelligence/facets`: snapshot-bound filter facets
- `GET/POST /api/v1/me/accounts`: list or create accounts for the resolved
  closed-test identity
- `POST /api/v1/me/accounts/{accountId}/snapshots`: record an immutable cash
  and position snapshot
- `GET/POST /api/v1/me/portfolios`: list or create aggregate portfolios
- `PUT /api/v1/me/portfolios/{portfolioId}/accounts`: replace an aggregate
  portfolio's explicit account set
- `POST /api/v1/me/portfolios/{portfolioId}/scenarios`: freeze complete account
  snapshots for a new-money, constrained-rebalancing, or target scenario
- `GET/POST /api/v1/me/investment-profile`: read the latest profile or append
  an immutable version with goals and sector preferences
- `GET/POST /api/v1/me/liabilities`: list or create account-level and
  user-level liabilities
- `POST /api/v1/me/liabilities/{liabilityId}/balances`: append an immutable
  liability balance
- `PUT /api/v1/me/portfolios/{portfolioId}/liabilities`: explicitly select
  user-level liabilities for an aggregate portfolio
- `POST /api/v1/me/constraints`: append a user, portfolio, or account policy
  version
- `GET /api/v1/me/constraints/resolved?portfolioId={id}`: resolve the strictest
  inherited limits for the portfolio and each member account

The `/api/v1/me` slice does not implement login. In an explicitly enabled
closed-test environment, `X-Test-Identity` contains an opaque external subject
that is resolved to an internal user and identity. It is not a user identifier
and must not be enabled on a public deployment.

Snapshot, profile-version, liability-balance, constraint-policy, and scenario
creation require `Idempotency-Key`. Scenario creation freezes complete account
snapshots, the latest profile, every applicable policy, and included liability
balances. It currently produces an immutable-input `DRAFT`; portfolio
calculation and decision submission remain later slices.

Flyway packages migrations from `../database/migrations` and runs them during
startup.

## Development

```powershell
.\mvnw.cmd spring-boot:run
```

PostgreSQL and the required datasource environment variables must be available.
For the reproducible full-stack environment, prefer `docker compose up --build`
from the repository root.

## Validation

```powershell
.\mvnw.cmd test
```

CI runs the backend tests with Java 21. When local Maven or Java configuration
is unavailable, the same validation can run in a Java 21 development container.

## Market Intelligence Boundary

The backend consumes the internal Market Intelligence HTTP contract and
publishes stable public candidate, profile, coverage, freshness, search, and
facets APIs. It does not own or duplicate quantitative formulas, read
Python-owned ranking tables as an alternative contract, or expose the Python
service directly to the browser.

The public contract preserves profile/run identifiers, model versions, data
timestamps, explicit missing and exclusion states, deterministic
contributions, and the separation between deterministic output and AI
narrative. Closed-test routes require `X-Test-Identity`; screening creation
also requires `Idempotency-Key`.

The user and portfolio foundation now includes the `app.*` schema, closed-test
identity resolution, account and liability snapshots, versioned profiles,
aggregate portfolio membership, tightening constraint resolution, and complete
scenario input freezing. The Java-side
`portfolio-calculation-v1` contract and compatibility fixture are defined, but
the internal Python endpoint is intentionally not active. Python must implement
and parse the same contract before a scenario can leave `DRAFT`.

Java must provide validated portfolio inputs to Python; Python must not modify
user account or holding state.

The current validation slice includes Java records for the future screening-run
contract and a test that deserializes the same canonical rating fixture as the
Python service. Java does not calculate or normalize rating factors.
