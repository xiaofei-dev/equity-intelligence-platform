# Spring Boot Backend

The Spring Boot application is the system of record and public API for the
Equity Intelligence Platform. The frontend calls this service; browser clients
must not call the Python analytics service directly.

## Implemented Contracts

- `GET /actuator/health`: service health
- `GET /api/v1/system/status`: stable application status
- `GET /api/v1/market-data/latest`: latest stored daily observation for every
  active security

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

Later user-facing responsibilities include investment profiles, accounts,
cash, liabilities, holdings, portfolio constraints, decisions, and immutable
recommendation records. Java must provide validated portfolio inputs to Python;
Python must not modify user account or holding state.

The current validation slice includes Java records for the future screening-run
contract and a test that deserializes the same canonical rating fixture as the
Python service. Java does not calculate or normalize rating factors.
