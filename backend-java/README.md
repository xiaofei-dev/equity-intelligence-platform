# Spring Boot Backend

The Spring Boot application is the system of record and public API for the
Equity Intelligence Platform. The frontend calls this service; browser clients
must not call the Python analytics service directly.

## Implemented Contracts

- `GET /actuator/health`: service health
- `GET /api/v1/system/status`: stable application status
- `GET /api/v1/market-data/latest`: latest stored daily observation for every
  active security
- `GET/POST /api/v1/me/accounts`: list or create accounts for the resolved
  closed-test identity
- `POST /api/v1/me/accounts/{accountId}/snapshots`: record an immutable cash
  and position snapshot
- `GET/POST /api/v1/me/portfolios`: list or create aggregate portfolios
- `PUT /api/v1/me/portfolios/{portfolioId}/accounts`: replace an aggregate
  portfolio's explicit account set
- `POST /api/v1/me/portfolios/{portfolioId}/scenarios`: freeze complete account
  snapshots for a new-money, constrained-rebalancing, or target scenario

The `/api/v1/me` slice does not implement login. In an explicitly enabled
closed-test environment, `X-Test-Identity` contains an opaque external subject
that is resolved to an internal user and identity. It is not a user identifier
and must not be enabled on a public deployment.

Snapshot and scenario creation require `Idempotency-Key`. Scenario creation
currently produces an immutable-input `DRAFT`; portfolio calculation and
decision submission remain later slices.

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

## Next Responsibility

After the Python candidate contract exists, the backend will coordinate
analysis tasks and expose stable public candidate and coverage APIs. It must not
own or duplicate the quantitative formulas.

The user and portfolio foundation now includes the `app.*` schema, closed-test
identity resolution, account snapshots, aggregate portfolio membership, and
scenario input freezing. The next slice should expose investment-profile,
liability, and versioned-constraint commands, resolve tightening constraint
inheritance, and define the versioned portfolio-calculation contract before a
scenario can leave `DRAFT`.

Java must provide validated portfolio inputs to Python; Python must not modify
user account or holding state.

The current validation slice includes Java records for the future screening-run
contract and a test that deserializes the same canonical rating fixture as the
Python service. Java does not calculate or normalize rating factors.
