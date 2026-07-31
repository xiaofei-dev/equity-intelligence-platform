# Future Price Evidence Persistence Adapter v1

## Status

`Future Price Evidence Persistence Adapter v1` is an offline implementation
contract for persisting completed-session future price evidence into the
existing analytics schema. It does not authorize provider access, execute a
preflight, score a security, enroll a decision, or change any scoring,
point-in-time, missing-data, or benchmark rule.

The adapter is implemented in:

- `analysis-python/src/equity_analysis/future_price_evidence/persistence_adapter_v1.py`

Its focused contract tests are in:

- `analysis-python/tests/future_price_evidence/test_future_price_evidence_persistence_adapter_v1.py`

## Versioned scope

Every persistence request binds both:

- a versioned universe; and
- a versioned symbol plan.

The adapter does not hard-code a permanent 57-symbol universe. The current v1
refresh plan may be used as a technical input when explicitly selected, but it
must not be described as sufficient for Forward Decision-Quality Validation
v2.1. That protocol requires a `REFERENCE_ONLY` ETF for every included sector.
Any additional sector benchmark must be added through a newly versioned
preregistration and symbol plan before execution.

## Existing-schema decision

No V18 migration is required. The adapter reuses the following existing
structures:

| Evidence | Existing structure | Write rule |
| --- | --- | --- |
| Official NYSE and Nasdaq calendar bodies | `analytics.source_record` | One immutable source record per exact body |
| Exact Yahoo response body | `analytics.source_record` | `RAW_TRANSPORT_BODY` semantics and a durable storage reference |
| Sanitized Yahoo HTTP envelope | `analytics.source_record` | Separate `NORMALIZED_CONTENT` record |
| Normalized price/action evidence | `analytics.source_record` | Separate from both body and envelope |
| Completed daily price bars | `analytics.daily_price_observation` | Append-only `TOTAL_RETURN_ADJUSTED` revisions |
| Promotion result | `analytics.daily_price_observation` | A new `VALIDATED` target-session revision only when promoted |
| Twenty-session ADTV | `analytics.metric_definition` and `analytics.metric_observation` | Versioned numeric observation with source lineage |
| Calendar, transport, action, and promotion evidence | `analytics.analytics_audit_event` | Four immutable validation events |
| Recovery and exact replay | `analytics.refresh_checkpoint` | Final checkpoint written after all other writes |

Spring Boot-owned `app.*` objects are not read or written.

## Raw and normalized evidence

Raw transport and normalized content have deliberately different meanings:

1. `YAHOO_RAW_BODY` binds the SHA-256 of the exact HTTP response body. It uses
   `RAW_TRANSPORT_BODY` semantics and requires a durable body reference.
2. `YAHOO_RESPONSE_ENVELOPE` binds the sanitized transport envelope, including
   the approved response metadata and body hash.
3. `NORMALIZED_PRICE_ACTION` binds the deterministic normalized evidence
   artifact.

The raw body and normalized artifact must have different source records and
different source references. A normalized DataFrame or reconstructed JSON
cannot be relabeled as raw transport.

Normalized daily rows are stored using the existing daily-refresh
`TOTAL_RETURN_ADJUSTED` convention: raw OHLC and volume remain bound to the
provider response, `adjusted_close` is persisted, and the downstream loader
constructs adjusted OHLC from the adjustment factor. The action audit event
binds the adjusted bar-set hash. A populated `adjusted_close` column alone does
not qualify an `UNADJUSTED` row for Forward v2.1; both provisional and promoted
revisions therefore carry the explicit accepted adjustment mode.

## Action evidence

Action evidence is explicit:

- `SELECTED_ACTIONS` requires at least one immutable action revision hash and a
  non-empty selected-action-set hash.
- `CONFIRMED_NO_ACTIONS` is positive evidence. It requires the canonical empty
  action-set hash, zero selected revision hashes, and a reconciled event.
- `INCOMPLETE_ACTION_EVIDENCE` permits no selected revision hashes and records a
  blocked reconciliation. It must not be treated as no actions.

Missing action evidence is never converted to a zero dividend, zero split, or
neutral adjustment.

## Atomic transaction and recovery

The PostgreSQL repository performs the following work in one database
transaction:

1. acquire a transaction-scoped advisory lock;
2. reject conflicting or malformed existing checkpoints;
3. verify that the V16 refresh task owns the requested security;
4. append or verify the five source records;
5. append provisional daily price revisions;
6. append a validated target-session revision only for `PROMOTED`;
7. append the ADTV definition and observation;
8. append the four validation audit events; and
9. append the final recovery checkpoint.

A failure before the final checkpoint rolls back the entire transaction.
The fake repository applies the same stage-then-commit behavior and has a
failure injection test that proves no source, price, metric, audit event, or
checkpoint survives a failed transaction.

An exact replay returns the stored checkpoint receipt. Reuse of the same
idempotency key with any different evidence, universe version, symbol-plan
version, action state, or promotion decision is a conflict.

## Execution safety

`PREFLIGHT` is not execution and cannot persist evidence.

`UNKNOWN` physical-request state stops before all database work. The adapter
does not infer success from a body file and does not retry an unknown request.
Only a request explicitly marked `COMPLETED` reaches the repository.

The persistence adapter does not perform provider requests. Network execution
must remain in the bounded future-price runner with its own lease, request
journal, ceilings, and stop conditions.

## SQL boundary

The SQL contract contains only:

- transaction-scoped advisory locking;
- reads from `analytics.refresh_task` and `analytics.refresh_checkpoint`;
- append or exact-identity reads for `analytics.source_record`;
- append-only revisions in `analytics.daily_price_observation`;
- append-only versioned definitions and observations in
  `analytics.metric_definition` and `analytics.metric_observation`;
- append-only `analytics.analytics_audit_event` rows; and
- an append-only final `analytics.refresh_checkpoint`.

It contains no DDL, `UPDATE`, `DELETE`, `TRUNCATE`, or `app.*` access.

## History coverage audit and v2 successor

The immutable v1 acquisition plan intentionally requests only a 45-calendar-day
window, which is sufficient for the 20 completed sessions used by ADTV. It is
not sufficient for all frozen model inputs:

| Consumer | Maximum lookback | Required completed price rows |
| --- | ---: | ---: |
| ADTV | 20 sessions | 20 |
| Tactical one week | 20-session return | 21 |
| Tactical one month | 60-session return | 61 |
| Tactical three months | 120-session return | 121 |
| Forward v2.1 pure momentum 12-1 | start offset 252, end offset 21 | 253 |

The exact combined requirement is therefore 253 ordered, unique completed
sessions ending on the decision session. For pure momentum, the first row is
the 252-session start anchor and row `-22` is the one-month exclusion anchor.

The v1 price-evidence and preflight artifacts remain unchanged. A successor
coverage contract is versioned separately as
`FUTURE-PRICE-HISTORY-COVERAGE-v2.0.0` in
`future_price_evidence/history_coverage_v2.py`. It explicitly reports readiness
for ADTV, each Tactical horizon, and pure momentum. A future v2 acquisition
preflight is defined separately as
`FUTURE-PRICE-HISTORY-PREFLIGHT-v2.0.0` in
`future_price_evidence/history_preflight_v2.py`.
The offline writer is exposed through
`future_price_evidence/history_preflight_cli_v2.py` and writes
`docs/generated/future-price-history-preflight-v2.json` using create-once,
exact-replay semantics. A changed artifact cannot overwrite the existing file.

The v2 preflight freezes:

- the existing 57 refreshable symbols, including `SPY` and `XLK`;
- ten new `REFERENCE_ONLY` sector ETFs: `XLB`, `XLC`, `XLE`, `XLF`, `XLI`,
  `XLP`, `XLRE`, `XLU`, `XLV`, and `XLY`;
- 67 unique price symbols total;
- an exact hash-verified predecessor 57-symbol plan in its frozen order;
- the authoritative
  `FORWARD-EXTERNAL-BENCHMARK-REFERENCE-UNIVERSE-v2.2.0` artifact, including
  each new ETF's stable public security ID and sector mapping;
- an ordered-symbols hash and a terminal v2 symbol-plan hash;
- two official calendar bodies plus 67 Yahoo Chart requests, for 69 physical
  attempts maximum;
- zero provider retries;
- a bounded 420-calendar-day request window; and
- an enforced minimum of 253 parsed completed sessions per symbol.

The 420-day transport window is a request ceiling, not proof of coverage.
Parsed, ordered, unique completed sessions must still be counted. Any symbol
with fewer than 253 rows stops the downstream momentum-readiness claim. The v2
plan loads and verifies the authoritative
`FORWARD-PREREGISTRATION-SEAL-v2.2.0`, including its file and content binding to
the external reference artifact. It does not reuse the predecessor v2.1 seal.
The target session must be strictly later than the v2.2 preregistration cutoff
date in `America/New_York`; a target on the same local date or an earlier date
is rejected mechanically. A caller cannot substitute or reorder one of the
predecessor 57 symbols by supplying another tuple of the same length: the
repository universe version, exact file SHA-256, ordered base symbols,
authoritative external reference rows, external artifact hash, and terminal
plan hash are all bound. The implementation remains network-disabled.

Persistence of a shorter valid capture remains allowed, but the coverage
contract must report the unavailable consumers as `INSUFFICIENT_HISTORY`.
Persisting 20 or 25 bars is not evidence that Tactical one-month, Tactical
three-month, or 12-1 momentum inputs are ready.

## Git and licensing boundary

The receipt contains IDs, versions, dates, hashes, and status metadata only.
It excludes raw provider bodies, normalized licensed values, ADTV numeric
values, scores, and ranks. Raw and normalized controlled artifacts must remain
under configured ignored storage paths.

## Acceptance boundary

This adapter is accepted when:

- focused tests prove raw/normalized separation;
- exact replay and conflict behavior are deterministic;
- confirmed no-action evidence remains explicit;
- incomplete and unknown states stop safely;
- promotion appends rather than mutates a prior row;
- injected failure rolls back all staged writes;
- SQL remains inside the existing analytics schema; and
- the complete offline Python suite and Ruff pass.

This acceptance does not mean a provider run occurred, a benchmark universe is
complete, a decision is enrolled, or Forward Decision-Quality Validation has
started.
