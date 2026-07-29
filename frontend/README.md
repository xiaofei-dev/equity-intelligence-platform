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
npm test
npm run lint
npm run build
```

The service health endpoint is `GET /health`.

## Implemented Routes

- `/`: product foundation and navigation
- `/research`: sealed-snapshot security browser and deterministic screener
- `/research/securities/[securityId]`: latest security research profile
- `/research/profiles/[profileId]`: immutable research profile
- `/market-data`: latest PostgreSQL-backed daily observation for the initial
  six-symbol engineering universe
- `/health`: container health contract

The market-data page is dynamically rendered by the Next.js server and calls
`GET /api/v1/market-data/latest` through `BACKEND_BASE_URL`.

## Research configuration

The research workspace uses only Server Components and Server Actions for
Spring Boot API access. Configure these server-only environment variables:

- `BACKEND_BASE_URL`: Spring Boot HTTP(S) origin
- `CLOSED_TEST_IDENTITY`: fixed local test identity recognized by Spring Boot
- `RESEARCH_DATA_SNAPSHOT_ID`: sealed data snapshot UUID
- `RESEARCH_SNAPSHOT_AS_OF`: exact ISO timestamp of the sealed snapshot
- `RESEARCH_SCREENING_RUN_ID`: optional sealed run UUID shown by default

None of these values use the `NEXT_PUBLIC_` prefix. Browser code does not call
Spring Boot, Python, PostgreSQL, or a market-data provider directly.

Future research views should favor concise natural-language assessments,
supporting evidence, counterarguments, portfolio impact, and data freshness.
Internal numeric factors may be available in an expanded research view, but the
interface must not present a composite score as a probability of profit.
