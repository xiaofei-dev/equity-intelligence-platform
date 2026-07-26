# Frontend

The frontend is the Next.js user interface for the Equity Intelligence
Platform. It presents research evidence, deterministic score explanations,
simulated portfolio workflows, and performance results.

The frontend calls the Spring Boot public API. It must not call the internal
Python analytics service directly, and browser-exposed environment variables
must never contain secrets.

## Development

```powershell
npm ci
npm run dev
```

Open `http://localhost:3000`.

## Validation

```powershell
npm run lint
npm run build
```

The service health endpoint is `GET /health`.

## Implemented Routes

- `/`: product foundation and navigation
- `/market-data`: latest PostgreSQL-backed daily observation for the initial
  six-symbol engineering universe
- `/health`: container health contract

The market-data page is dynamically rendered by the Next.js server and calls
`GET /api/v1/market-data/latest` through `BACKEND_INTERNAL_URL`. Features that
are not implemented must be presented as planned states rather than
interactive controls.
