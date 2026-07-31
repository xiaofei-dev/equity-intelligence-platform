# Future Completed-Session Price History Capture Runner v2

## Status

The runner is implemented and offline-validated. It is intentionally blocked
until the 2026-07-30 United States market session is complete and a separately
authorized live command is supplied.

The runner does not start from FastAPI, does not compute scores or ranks, and
does not write PostgreSQL by default.

## Frozen input

The runner accepts only:

- `docs/generated/future-price-history-preflight-v2.json`
- the v2.2 preregistration seal and the external-reference artifact bound by
  that seal
- the exact 57-symbol predecessor plan
- the exact ten additional sector ETF references

It reconstructs and re-verifies the complete plan before execution:

- 67 Yahoo Chart JSON requests
- one official NYSE calendar request
- one official Nasdaq calendar request
- 69 physical attempts and 69 configured-weight units at most
- zero provider retries
- a 420-calendar-day request window
- at least 253 parsed completed sessions for every price symbol

Any plan, universe, seal, reference, endpoint-count, request-count, weight, or
coverage change stops execution.

## Safety sequence

1. Verify the immutable preflight and all source bindings.
2. Verify that the deterministic United States market calendar reports the
   target session as completed after its close grace period.
3. Require the explicit live flag and exact live confirmation token.
4. Acquire a cross-process heartbeat lease.
5. Append a run preflight event.
6. Capture the two official calendar responses with
   `INTENT -> COMPLETED/FAILED` request journals.
7. Require a named dual-authority review that affirms the scheduled session
   and regular or published early close. A negative review stops before any
   Yahoo request.
8. Capture the 67 direct Yahoo Chart JSON responses with the same journal.
9. Persist exact raw response bytes and separate sanitized-envelope hashes in
   content-addressed, Git-ignored storage.
10. Normalize adjusted close, corporate actions, raw price/volume, ADTV, and
    action-adjustment bindings.
11. Require all five history-coverage checks, including 253 sessions for the
    frozen 12-1 momentum contract.
12. Write an immutable controlled manifest, completion checkpoint, and
    Git-safe report.

An unresolved `INTENT` is `UNKNOWN` and blocks an explicit resume. It is never
retried automatically. A completed run may be explicitly replayed by run ID;
the immutable checkpoint/report/manifest are verified and no new request is
made.

## Controlled and Git-safe data

Exact response bodies, normalized bars, adjusted closes, volumes, ADTV values,
and corporate-action observations remain under:

`storage/future-price-history-capture-v2`

That directory is Git-ignored. Git-safe reports contain only identity,
lineage, timestamps, status, counts, and SHA-256/content hashes. They contain
no provider numeric values.

## PostgreSQL boundary

The standalone CLI never writes PostgreSQL. An embedded operations caller may
set the separate database-write flag only with the exact database confirmation
token and an `AdapterPersistenceGateway`.

That gateway uses the existing
`FuturePriceEvidencePersistenceAdapter`. Each request is handled by its
repository transaction and idempotent checkpoint contract. The live capture
must finish and pass all history checks before the gateway is invoked.

## Offline status command

This command never performs network or database work:

```powershell
cd C:\Projects\equity-intelligence-platform
$env:PYTHONPATH = "analysis-python/src"
.\analysis-python\.venv\Scripts\python.exe -m `
  equity_analysis.future_price_evidence.history_capture_cli_v2
```

Before the target session is complete, the expected status is:

`BLOCKED_AWAITING_TARGET_SESSION_COMPLETION`

After completion, the expected status is:

`READY_FOR_COMPLETED_SESSION_EXECUTION`

## Future live command

Run only after reviewing the two official market calendars and receiving
separate live authorization:

```powershell
cd C:\Projects\equity-intelligence-platform
$env:PYTHONPATH = "analysis-python/src"
.\analysis-python\.venv\Scripts\python.exe -m `
  equity_analysis.future_price_evidence.history_capture_cli_v2 `
  --execute-live `
  --confirm-live I_CONFIRM_FUTURE_PRICE_EVIDENCE_LIVE_CAPTURE `
  --reviewed-by "<named reviewer>" `
  --confirm-nyse-session `
  --confirm-nyse-close `
  --confirm-nasdaq-session `
  --confirm-nasdaq-close
```

The operator must not add `--write-database`. Database persistence is a
separate embedded operation after capture acceptance.

## Stop conditions

Execution stops on:

- incomplete target session
- failed or negative dual-authority review
- changed preflight, seal, universe, reference, or symbol-plan hash
- an unplanned request
- any authentication, limit, transport, HTTP, schema, or semantic anomaly
- an attempt or weight above 69
- an unresolved physical request
- fewer than 253 completed sessions for any symbol
- immutable artifact conflict
- missing database confirmation or persistence gateway

No stopped run authorizes scoring, enrollment, Forward Decision-Quality
Validation, commit, push, or deployment.
