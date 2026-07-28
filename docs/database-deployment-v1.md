# Database Deployment v1

## Decision

The first closed-test deployment will use a managed PostgreSQL service in the
same region and private network as the Spring Boot and FastAPI services.
Render is the preferred first platform because it matches the planned
single-region MVP deployment. Amazon RDS remains the later production-learning
target.

The database will not run inside either application container, and production
state will not rely on a Docker named volume or an application filesystem.

The repository is currently verified on PostgreSQL 17. A managed service must
provide PostgreSQL 17 or pass the complete migration and acceptance matrix
before it is accepted.

## Deployment Topology

```text
Public internet
    |
    +--> Next.js
    |
    +--> Spring Boot public API
              |
              +------ private TLS ------+
                                      Managed PostgreSQL
              +------ private TLS ------+
              |
          FastAPI analytics worker

Scheduled refresh job ---> FastAPI worker/runtime ---> Managed PostgreSQL
```

The browser never receives a database URL. The Python service is private and
the public frontend calls Spring Boot only.

## Schema and Ownership

One PostgreSQL database is sufficient for the closed-test MVP:

- `app.*` is owned by the Spring Boot business boundary.
- `analytics.*` is owned by the Python analytics boundary.
- Flyway is the only DDL migration authority.
- `analytics_writer` and `analytics_reader` remain `NOLOGIN` group roles.
- Deployment login roles receive the minimum required memberships outside
  committed migrations.

The target credential separation is:

| Credential | Allowed use |
| --- | --- |
| Migration login | Flyway and deployment-time DDL only |
| Spring runtime login | `app.*` read/write and approved analytics projections |
| Analytics runtime login | `analytics.*` read/write only |
| Operations read-only login | Diagnostics and backup verification only |

The current local stack uses a shared development credential. Separate runtime
logins and grants are a deployment prerequisite, not an assumption that is
already satisfied.

## Secret and Network Controls

- Store database credentials in the deployment platform's encrypted secret
  store.
- Require private networking and TLS for every database connection.
- Do not expose PostgreSQL to the public internet.
- Do not place credentials in `NEXT_PUBLIC_*`, container images, logs, or Git.
- Rotate a credential immediately if it is displayed or committed.
- Use separate credentials and databases for local, closed-test, and future
  production environments.

Required application configuration:

- Spring Boot: `SPRING_DATASOURCE_URL`,
  `SPRING_DATASOURCE_USERNAME`, and `SPRING_DATASOURCE_PASSWORD`
- FastAPI: `ANALYTICS_DATABASE_URL`

## Migration Release Procedure

Only one release step may apply migrations:

1. create an on-demand managed backup;
2. run the full migration matrix against a disposable PostgreSQL 17 database;
3. deploy the exact tested application commit;
4. execute Flyway once with the migration login;
5. run `analytics_schema_acceptance.sql` and `app_schema_acceptance.sql`;
6. verify the schema version and application health checks;
7. start or restart the runtime services with non-DDL credentials; and
8. record the commit, migration version, backup identifier, and verification
   result.

For the first single-instance closed test, Spring Boot may run Flyway during a
controlled release. Before horizontal scaling, this must become an explicit
one-off release job so runtime replicas do not own deployment orchestration.

Applied migrations are append-only. A deployed migration is never edited;
corrections use a new migration.

## Backup and Recovery Baseline

Closed-test targets:

- managed automated backup at least daily;
- at least 14 days of backup retention where the selected plan permits it;
- an on-demand backup before every migration;
- target recovery point objective: 24 hours;
- target recovery time objective: 4 hours; and
- a documented restore rehearsal before the database becomes the only copy of
  user-entered portfolio state.

Market prices can often be reacquired, but user portfolio snapshots, decisions,
and audit records cannot be treated as disposable. Backup validation must
include both `app.*` and `analytics.*`.

## Monitoring

Monitor at minimum:

- connection count and rejected connections;
- storage use and growth;
- CPU and memory pressure;
- slow queries and lock waits;
- failed Flyway migrations;
- refresh-run failures and stale dataset counts;
- backup age and restore-test status; and
- database availability from both Spring Boot and FastAPI.

Application health must not expose credentials, SQL text containing sensitive
data, or private portfolio records.

## Rollout Stages

### Stage 0: Local

Docker Compose, PostgreSQL 17, development credentials, and synthetic or
controlled data.

### Stage 1: Closed Test

Managed PostgreSQL, private services, no public registration, a small fixed
user set, bounded market-data refresh, automated backups, and no brokerage
execution.

### Stage 2: Public Demo

Production authentication, explicit licensing review, rate limiting,
observability, incident procedures, and sanitized display data.

### Stage 3: AWS Learning Migration

Amazon RDS, ECS Fargate, ECR, EventBridge, CloudWatch, private subnets, and a
tested backup/restore and rollback process.

## Deployment Readiness Checklist

- [ ] Managed PostgreSQL version selected and migration-tested
- [ ] Private network and TLS verified
- [ ] Migration and runtime credentials separated
- [ ] Runtime grants tested
- [ ] Automated backups enabled
- [ ] Restore rehearsal completed
- [ ] One-off migration release step implemented
- [ ] Health and freshness monitoring enabled
- [ ] Closed-test identities provisioned outside migrations
- [ ] Market-data licensing checked for the deployed use
- [ ] Daily refresh quota and safety limits configured
- [ ] No secrets or controlled provider values in Git or images

No cloud resource is created by this document. Provisioning, billing, and
production activation require a separate explicit deployment approval.
