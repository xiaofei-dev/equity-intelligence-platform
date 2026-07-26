# Database Assets

PostgreSQL migrations live in `migrations/` and are packaged into the Spring
Boot application. Flyway applies them during backend startup.

## Schema Ownership

- `app.*`: user-facing workflows and system-of-record state
- `analytics.*`: normalized market data and analysis results

Cross-schema changes require an explicit contract and migration.

## Applied Migrations

- `V1`: create `app` and `analytics` schemas
- `V2`: create the security master and daily-price tables; seed the
  six-symbol engineering universe
- `V3`: consolidate duplicate United States ticker identities and enforce
  unique normalized symbols

Migration files are append-only after they have been applied to a shared
environment. Corrections require a new migration rather than editing deployed
history.
