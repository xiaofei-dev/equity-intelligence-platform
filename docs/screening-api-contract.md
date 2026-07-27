# Screening Internal API Contract v1

## Ownership

Python owns eligibility, factor calculations, normalization, strategy scoring,
ranking and screening-run results. Java coordinates user-facing workflows and
consumes the result; it must not reproduce the formulas.

The current implementation provides immutable Python Pydantic models, matching
Java records, a pure scoring engine, and a shared JSON compatibility fixture.
The HTTP task lifecycle below is implemented with PostgreSQL-backed scheduling
and persistence. Authentication remains deferred.

The analytics database now provides the persistence boundary for that future
HTTP lifecycle. A run references a sealed data snapshot, a versioned universe,
and immutable strategy definitions. Database surrogate keys, source manifests,
and normalization internals remain private to Python; `security.public_id` is
the contract `securityId`. Java still consumes results only through this
contract and does not read rating tables directly.

## Create a Screening Run

```http
POST /internal/v1/screening/runs
Idempotency-Key: <caller-stable-key>
Content-Type: application/json
```

```json
{
  "asOfTime": "2026-07-25T20:00:00Z",
  "dataSnapshotId": "snapshot-2026-07-25",
  "universeVersion": "universe-us-general-company-v1.0.0",
  "strategyVersions": ["QC-v1.0.0", "UQ-v1.0.0"],
  "includeNearTermMarketCondition": true
}
```

Success is `202 Accepted` with `runId`, `status: PENDING`, and `submittedAt`.
The same idempotency key and canonical request return the original run. Reuse
with a different request returns `409 Conflict`.

Spring Boot exposes the same operation at `POST /api/v1/screening/runs` and
forwards the caller's `Idempotency-Key`.

## Build a Data Snapshot

```http
POST /internal/v1/screening/snapshots
```

The request supplies a snapshot key, as-of time, ingestion cutoff, universe
version, and market, fundamental, and action normalization versions. Python
selects source records satisfying both cutoffs, constructs dated universe
membership, hashes the canonical manifest, and seals the snapshot. The same
key and inputs are idempotent; changed inputs return `409 Conflict`.

Snapshot creation remains an internal ingestion operation and is not exposed
by Spring Boot.

## Read Status and Ratings

```http
GET /internal/v1/screening/runs/{runId}
GET /internal/v1/screening/runs/{runId}/ratings?cursor={cursor}
```

Run states are `PENDING`, `RUNNING`, `SUCCEEDED`, and `FAILED`. Status includes
the immutable input versions, coverage counts, and an optional stable error
code. Results are cursor-paginated and available only for a succeeded run.
Spring Boot mirrors these reads under `/api/v1/screening/runs/{runId}` and
`/api/v1/screening/runs/{runId}/ratings`.

Rating pages are reconstructed exclusively from the completed run's immutable
coverage, factor, lineage, horizon, strategy, and contribution records. A GET
request never reruns normalization or scoring.

Each rating exposes:

- Security identity, `asOfTime`, company type, size cohort and coverage state.
- Separate `qualityScore` and `valuationScore`.
- Raw, winsorized and normalized factor values with cohort level and size.
- Separate `NEAR_TERM`, `MEDIUM_TERM`, and `LONG_TERM` assessments.
- Strategy versions, scores, ranks, exact weighted contributions and missing
  factors.
- Risk flags, missing reasons and source lineage.

Decimal values are serialized as strings to preserve precision. Timestamps are
UTC RFC 3339 values. Unknown enum values are contract-breaking in v1 and
require a new compatible contract version before use.

## Stable Error Codes

- `UNSUPPORTED_COMPANY_TYPE`
- `INSUFFICIENT_DATA`
- `STALE_DATA`
- `PIT_LINEAGE_FAILED`
- `INVALID_UNITS`
- `COHORT_TOO_SMALL`
- `STRATEGY_VERSION_UNSUPPORTED`
- `ANALYSIS_FAILED`

An error code never substitutes a zero factor or neutral score.

## Compatibility Artifact

[`contracts/screening-rating-v1.example.json`](../contracts/screening-rating-v1.example.json)
is parsed by both Python and Java tests. It is the minimum wire-compatibility
fixture, not a recommendation or production response.

The directory also contains shared run-request, accepted-task, status, and
error fixtures parsed by both Python and Java tests.
