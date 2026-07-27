# Forward Validation Internal API Contract v1

## Ownership

Python owns enrollment selection, trading-calendar decisions, entry-policy
state, shadow ledgers, cash accrual, corporate-action handling, metrics, and
reports. Java coordinates workflows and consumes immutable results. Java must
not reproduce the formulas.

All Decimal values are JSON strings and timestamps are UTC RFC 3339. Creation
requests require `Idempotency-Key`.

## Experiments

```http
POST /internal/v1/forward-validation/experiments
GET  /internal/v1/forward-validation/experiments/{experimentId}
```

The request references a succeeded screening run and all five rule versions.
It defaults to `DRY_RUN`. `FORMAL` is rejected unless
`providerAcceptanceId` references an immutable `ACCEPTED` record with a
300-to-500-security stratified universe. States are `PENDING`, `ACTIVE`,
`PAUSED`, `COMPLETED`, and `FAILED`.

## Enrollments and Results

```http
POST /internal/v1/forward-validation/experiments/{experimentId}/enrollments
GET  /internal/v1/forward-validation/experiments/{experimentId}/signals
GET  /internal/v1/forward-validation/experiments/{experimentId}/observations
GET  /internal/v1/forward-validation/experiments/{experimentId}/reports/{reportType}
```

Enrollment accepts a succeeded sealed screening run and an enrollment
timestamp. Python freezes the QC and UQ top/bottom quintiles, excluding an
already active security/path/bucket episode. Signals and later results are
append-only.

Report types are `ONE_MONTH` and `TWO_MONTH`. In v1,
`statisticalEdgeProven` must be `NOT_ESTABLISHED`.

## Stable Errors

- `PIT_LINEAGE_FAILED`
- `PROVIDER_NOT_ACCEPTED`
- `TRADING_CALENDAR_UNAVAILABLE`
- `PRICE_UNAVAILABLE`
- `BENCHMARK_UNAVAILABLE`
- `CORPORATE_ACTION_UNRESOLVED`
- `CASH_RATE_UNAVAILABLE`
- `INSUFFICIENT_SAMPLE`
- `EXPERIMENT_VERSION_UNSUPPORTED`
- `ANALYSIS_FAILED`

The shared compatibility artifact is
[`contracts/forward-validation-v1.example.json`](../contracts/forward-validation-v1.example.json).
