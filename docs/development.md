# Local Development

## Purpose

This guide explains how to run and verify the Phase 0 service foundation. It
does not require real market data or third-party API credentials.

## Prerequisites

- Node.js 20.9 or later
- Java 21
- Python 3.12 through 3.14
- Docker Desktop with Docker Compose

On Windows, Docker Desktop is the recommended way to obtain both Docker Engine
and the `docker compose` command.

## Environment Configuration

Create a local environment file:

```powershell
Copy-Item .env.example .env
```

The committed `.env.example` contains development placeholders only. Replace
passwords and provider keys in `.env`; never commit `.env` or real credentials.

Variables prefixed with `NEXT_PUBLIC_` are embedded in browser-accessible
frontend code. Never place secrets in those variables.

Phase 1 market data ingestion uses `MARKET_DATA_PROVIDER=twelve_data` and reads
the credential from `TWELVE_DATA_API_KEY`. Keep this key only in the local
`.env` file or a deployment secret store. The analytics database URL is
constructed automatically inside Docker Compose.

## Run the Complete Stack

From the repository root:

```powershell
docker compose up --build
```

If the Docker installation exposes Compose as a standalone command, use
`docker-compose up --build` instead.

The services are:

| Service | Local URL | Health endpoint |
| --- | --- | --- |
| Frontend | `http://localhost:3000` | `http://localhost:3000/health` |
| Spring Boot backend | `http://localhost:8080` | `http://localhost:8080/actuator/health` |
| FastAPI analytics | `http://localhost:8000` | `http://localhost:8000/health` |
| PostgreSQL | `localhost:5432` | Container health check |

Stop the services with:

```powershell
docker compose down
```

Use `docker-compose down` when running the standalone command.

The PostgreSQL named volume is intentionally preserved. Removing it is a
destructive action and should only be done when local data loss is acceptable.

## Run Services Individually

### Frontend

```powershell
Set-Location frontend
npm ci
npm run dev
```

Validation:

```powershell
npm run lint
npm run build
```

### Spring Boot Backend

PostgreSQL must be available before starting the backend with its default
profile.

```powershell
Set-Location backend-java
.\mvnw.cmd spring-boot:run
```

Validation:

```powershell
.\mvnw.cmd test
```

The Maven Wrapper keeps the required Maven version project-local.

### FastAPI Analytics Service

```powershell
Set-Location analysis-python
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m uvicorn equity_analysis.main:app --reload
```

Validation:

```powershell
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m pytest
```

## Database Migrations

Migration source files live in `database/migrations`. The backend packages and
runs them with Flyway during startup. Migration files are append-only after
they have been applied to a shared environment.

The first migration creates separate `app` and `analytics` schemas to preserve
the documented ownership boundary.

## Health and Status Contracts

- The frontend exposes `GET /health`.
- The backend exposes Spring Boot Actuator health endpoints and
  `GET /api/v1/system/status`.
- The analytics service exposes `GET /health`.

Health responses communicate service availability only. They must not expose
credentials, internal exception details, or private data.

## Market Data Ingestion

The bounded Phase 1 ingestion endpoint is internal to the analytics service:

```text
POST /internal/v1/market-data/daily-prices/ingest
```

It accepts up to 20 symbols and an inclusive date range. The operation is
idempotent: a repeated provider, symbol, trading date, and adjustment mode
updates the existing row rather than creating a duplicate.

When `TWELVE_DATA_API_KEY` is not configured, the endpoint returns
`MARKET_DATA_NOT_CONFIGURED` without contacting the provider. Do not expose
this internal endpoint directly from a public deployment.

## Continuous Integration

GitHub Actions validates every pull request targeting `main` and every push to
`main`. The workflow performs these independent checks:

- Frontend dependency installation, linting, and production build
- Spring Boot tests with Java 21
- FastAPI linting and tests with Python 3.14
- Full-history secret scanning with Gitleaks

The workflow can also be started manually from the GitHub Actions page. A
failed secret scan must be investigated before merging. Removing a secret from
the latest commit is not sufficient because the value can remain in Git
history; revoke the credential first, then remove it from the affected history.

CI secret scanning is a detection layer, not permission to store secrets in the
repository. Keep credentials in local `.env` files or the deployment
platform's encrypted secret store.
