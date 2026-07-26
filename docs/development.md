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
