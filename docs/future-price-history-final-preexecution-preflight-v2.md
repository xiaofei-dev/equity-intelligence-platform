# Future Price History Final Pre-Execution Preflight v2

## Purpose

This preflight is the final zero-network and zero-database control immediately
before the first post-freeze completed-session price capture for Forward DQV
v2.2. It does not authorize an execution merely because the local market
calendar has reached the target date.

The preflight binds:

- the final successor-readiness closeout v2;
- the final PostgreSQL V18 acceptance;
- the frozen 66-security closed-test universe;
- the v2.2 preregistration seal and external benchmark references;
- the exact Future Price History Capture v2 plan and implementation sources.

## Current state

The target session is 2026-07-30. Before that session has completed, including
the deterministic close grace period, the only valid status is:

`BLOCKED_AWAITING_TARGET_SESSION_COMPLETION`

No network request, database read or write, score, rank, enrollment, outcome,
commit, push, or deployment is performed by this preflight.

## Frozen request plan

- 67 direct Yahoo Chart JSON requests;
- one official NYSE calendar request;
- one official Nasdaq calendar request;
- 69 physical attempts and 69 configured-weight units at most;
- zero provider retries;
- 420 calendar days requested;
- at least 253 parsed completed sessions for every price symbol.

The capture must retain exact raw transport hashes, raw and adjusted daily
bars, dividends and splits, the action-adjustment binding, 20-session raw
close-times-volume ADTV evidence, availability timestamps, and provider
revision lineage.

## Execution safety

The capture requires a heartbeat lease and an append-only physical-request
journal. Each physical request must move from `INTENT` to either `COMPLETED` or
`FAILED`. An unresolved state is `UNKNOWN`; it stops execution and is never
retried automatically. A completed replay requires a verified checkpoint and
must issue zero additional physical requests.

Any calendar, lease, journal, checkpoint, source hash, universe hash, response
format, semantic, history coverage, request-count, weight, adjustment, action,
or ADTV anomaly stops the run.

## Only approved post-close command

After the 2026-07-30 session is complete, a named operator must independently
review the official NYSE and Nasdaq session and close evidence. The one bounded
command is:

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

Do not add `--write-database`, `--resume`, or a larger request budget. Capture
acceptance and database persistence are separate operations.
