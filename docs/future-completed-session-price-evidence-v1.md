# Future Completed-Session Price Evidence v1

## Purpose

This contract prepares the first post-preregistration price and liquidity
evidence capture without making a provider request or writing to PostgreSQL.
It is an evidence boundary for future Forward Decision-Quality Validation, not
a live-data authorization and not a scoring workflow.

The first mechanically eligible target is the first United States market
session after the formal preregistration cutoff. The current preflight targets
July 30, 2026 and remains blocked until that session is complete, both official
calendar sources have been captured and reviewed, and a separate live
authorization is provided.

## Frozen scope and budget

The capture scope is the 57 refreshable members of
`market-intelligence-closed-test-us-v1.0.0`:

- 48 primary securities;
- 7 reserve securities; and
- SPY and XLK as reference-only securities.

Excluded securities remain represented by the sealed universe but are not
silently added to the price request scope.

The bounded request plan contains:

- one official NYSE calendar document capture;
- one official Nasdaq calendar document capture; and
- one direct Yahoo Chart JSON request for each of the 57 symbols.

The expected and hard maximum are both 59 physical HTTP attempts and 59 local
weight units. Provider retries are zero. An interrupted request left at
`INTENT` is `UNKNOWN` and stops the run; it is never automatically repeated.

## Completed-session evidence

A completed session requires independent, content-addressed evidence from both:

- the official [NYSE hours and calendars
  page](https://www.nyse.com/markets/hours-calendars); and
- the official [Nasdaq holiday
  schedule](https://www.nasdaq.com/market-activity/stock-market-holiday-schedule).

Each response body must be stored exactly, hashed as transport bytes, and
reviewed by a named reviewer. The review records the target session and whether
the source confirms a regular close or published early close. A deterministic
calendar may plan the request, but it cannot replace the two reviewed official
source bodies.

The target daily bar is accepted only after the completed-session cutoff and
only when the direct Yahoo payload contains that exact session. A partial
current-day row, a later row, a missing target row, or a calendar disagreement
stops the run.

## Raw transport boundary

Formal `RAW_TRANSPORT_BINDING` means the SHA-256 of the exact HTTP response
body and a separate hash of its sanitized response envelope. It never means:

- a pandas or yfinance DataFrame hash;
- a normalized daily-price payload hash;
- a hash reconstructed from parsed values; or
- a provider library cache key.

The existing yfinance adapter does not expose the original response body.
Therefore yfinance remains unsuitable for this formal raw-transport claim.
The implemented future route uses the direct Yahoo Chart v8 JSON endpoint. If
that exact body cannot be durably captured, the evidence remains `BLOCKED`.

Raw bodies and normalized values belong in ignored controlled storage. Git-safe
receipts contain only hashes, versions, dates, status, and lineage.

## Price, actions, adjustment, and revisions

One Chart response binds:

- unadjusted OHLCV observations;
- adjusted close;
- split and dividend events included in the response;
- the target completed session;
- the raw response-body hash; and
- the provider observation revision key.

The action-to-adjusted-price binding separately hashes the raw bar set, selected
action set, adjusted bar set, adjustment policy, and source revision status.
The normalized mode is `TOTAL_RETURN_ADJUSTED` under
`YAHOO-ADJCLOSE-RATIO-OHLC-v1.0.0`. An empty event set is still hash-bound to
the response; it is not treated as proof from an unrelated source.

Each later capture is a new observed revision. It does not overwrite or relabel
prior evidence.

## ADTV observation

Decision-time average daily dollar volume is:

`mean(raw close × raw volume)`

over the 20 completed sessions ending on the target session. The controlled
metric is versioned as `ADTV-20-RAW-CLOSE-X-RAW-VOLUME-v1.0.0` and binds the
exact ordered price-volume input hash. Fewer than 20 complete observations
stops the run. The numeric value is not written to Git-safe artifacts.

## Execution safety

The future live implementation must use:

- a cross-process `ExecutionLease`;
- a `PhysicalRequestJournal`;
- immutable response checkpoints;
- filesystem-safe request identities;
- exact replay of completed requests;
- zero provider retries; and
- the frozen attempt and weight ceilings.

Network execution defaults to disabled. The offline CLI only creates or
verifies the preflight:

```powershell
.\analysis-python\.venv\Scripts\python.exe -m `
  equity_analysis.future_price_evidence.cli
```

The implementation exposes a guard for a later live controller, but this task
contains no network-performing CLI path.

## Current status and remaining blockers

The implementation and preflight are complete offline. Live capture remains
blocked by:

1. the target session not yet being proven complete at execution time;
2. missing exact NYSE and Nasdaq response-body hashes;
3. missing named dual-authority review;
4. missing separate live authorization; and
5. the absence of database persistence acceptance for these new evidence
   receipts.

No network request, database write, migration, score, outcome observation,
commit, push, or deployment was performed.
