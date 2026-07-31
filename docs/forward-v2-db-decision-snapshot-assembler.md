# Forward v2 Database Decision Snapshot Assembler

## Status

`FORWARD-V2-DB-DECISION-ASSEMBLER-v1.0.0` is a bounded, no-migration
assembler for one PostgreSQL V17 `READY` data snapshot and its exact closed
66-security profile set.

It creates the input needed by `FORWARD-DECISION-SNAPSHOT-v2.0.0` without
changing V11, V16, V17, any public route, or any model formula.

## Ownership and non-goals

- Python owns the assembler, deterministic model execution, controlled
  artifacts, and the V16 audit handoff.
- Flyway remains the sole DDL authority. This implementation adds no V18.
- The assembler has no provider client and performs no network request.
- It does not call an LLM and records that AI did not influence deterministic
  fields.
- It does not reinterpret V17 horizon projections as Tactical v2.2 decisions.
- It does not reinterpret Objective Rating or legacy long-horizon projections
  as Long Horizon v1.1 evidence.
- It does not write V11 Forward Validation or V17 product tables.

## Exact database boundary

The assembler accepts one snapshot only when all of the following are true:

1. `analytics.data_snapshot.status = READY`.
2. The snapshot declares exactly 66 securities.
3. The requested immutable universe definition exists.
4. There are exactly 66 unique stable `analytics.security.public_id` values.
5. Every universe member has exactly one V17
   `analytics.security_profile_snapshot`.
6. Every profile has the exact snapshot `snapshot_as_of`.
7. The recorded source count equals the actual sealed ingestion-batch count.
8. Membership status, reason, company type, sector, symbol, public ID, and
   profile ID are included in the canonical universe/member-role hashes.

An ambiguous or incomplete profile set is rejected. The assembler never
selects a convenient latest profile from multiple candidates.

## Membership semantics

Every frozen public security ID receives exactly one terminal row.

| Universe membership | Tactical v2.2 terminal | Long Horizon v1.1 terminal |
| --- | --- | --- |
| `INCLUDED` | Assessed only when its exact v2.2 evidence is sufficient; otherwise `MISSING`, `STALE`, or `INVALID` | Assessed only from exact v1.1 inputs; otherwise the model's explicit missing or specialized state |
| `REFERENCE_ONLY` | `NOT_APPLICABLE` | `NOT_APPLICABLE` |
| `EXCLUDED` | `EXCLUDED` | `EXCLUDED` |

The membership reason is retained as an explicit exclusion reason. Missing
data is never converted to zero or a neutral score.

## Tactical v2.2 evidence

The assembler reads only snapshot-bound, cutoff-valid, completed daily price
observations. It:

- selects one highest revision per trading date;
- uses the snapshot's frozen provider and adjustment mode;
- applies the stored adjusted-close factor consistently to OHLC;
- keeps availability, ingestion, normalization, revision, and source hashes;
- marks an old latest session `STALE` rather than scoring it;
- requires SPY as the explicit market benchmark identity;
- recognizes a sector benchmark only from an explicit frozen
  `REFERENCE_ONLY` membership whose reason begins with `SECTOR_BENCHMARK`;
- does not synthesize a sector benchmark from the current cross-section;
- leaves event evidence `MISSING` when no versioned event input exists.

If all three series are valid, their actual shared completed sessions determine
the model session date. Fewer than 21 shared sessions produce
`INSUFFICIENT_DATA`. The one-week, one-month, and three-month decisions are
then evaluated by the frozen Tactical v2.2 implementation. No Tactical v2.1
score is queried or copied.

## Long Horizon v1.1 evidence

Only V17 profile facts with the exact metric version
`LONG-HORIZON-INPUT-v1.1.0` and exact v1.1 operand name may become model
inputs. Legacy `MARKET-INTELLIGENCE-INPUT-v1.0.0` facts are not promoted.

Company types that explicitly identify a bank, insurer, REIT, resource
company, biotech, or recent IPO are routed to the corresponding v1.1
applicability policy. Unknown types receive no inferred specialized score.

V17 Objective Rating scores, V17 horizon scores, and the old Long Horizon v1.0
result are deliberately outside this adapter.

## Artifacts and V16 handoff

`decision_snapshot_v2` creates:

- one controlled, content-addressed decision artifact under the Git-ignored
  `storage/forward-validation/decision-snapshots-v2` root;
- one Git-safe manifest with IDs, terminal states, evidence hashes, freeze
  hashes, and no provider values or deterministic numeric results;
- one `FORWARD_V2_DAILY_DECISION_SNAPSHOT_SEALED` V16 audit payload.

`ForwardV2AuditEventRepository` persists the audit payload to
`analytics.analytics_audit_event` under a transaction advisory lock.

- Exact replay returns the existing event ID.
- Reuse of an idempotency key with different evidence raises
  `FORWARD_V2_DB_IDEMPOTENCY_CONFLICT`.
- A noncanonical event hash is rejected before a database connection.
- The append-only V16 event is a handoff record, not a substitute for the
  future structured V18 Forward v2 ledger.

## Local execution

No configured PostgreSQL URL was available during implementation, so no real
66-security artifact or V16 event was created. The integration test is
skip-safe and uses the existing isolated V17 PostgreSQL fixture when
`MARKET_INTELLIGENCE_V17_TEST_DATABASE_URL` is configured.

Run the PostgreSQL integration test:

```powershell
cd C:\Projects\equity-intelligence-platform\analysis-python
$env:MARKET_INTELLIGENCE_V17_TEST_DATABASE_URL = "<isolated PostgreSQL 17 test URL>"
.\.venv\Scripts\python.exe -m pytest `
  tests/test_forward_db_decision_snapshot_v2.py -q
```

Seal the latest qualifying real `READY` snapshot after reviewing the selected
database and using a fixed seal timestamp:

```powershell
cd C:\Projects\equity-intelligence-platform
$env:MARKET_INTELLIGENCE_V17_TEST_DATABASE_URL = "<reviewed PostgreSQL URL>"
.\analysis-python\.venv\Scripts\python.exe -m `
  equity_analysis.forward_validation.db_decision_snapshot_v2 `
  --latest-ready `
  --repository-root C:\Projects\equity-intelligence-platform `
  --idempotency-key "forward-v2:<completed-session>:closed-66:v1" `
  --sealed-at "<reviewed timezone-aware ISO-8601 timestamp>" `
  --manifest-path `
  "C:\Projects\equity-intelligence-platform\docs\generated\forward-v2-<run-id>.json" `
  --persist-audit
```

The command prints the selected snapshot ID, universe version, membership
counts, role hash, artifact hashes, readiness blockers, audit event ID, and
replay status. It performs zero provider requests.

## Acceptance tests

The focused tests prove:

- legacy facts cannot become Long Horizon v1.1 inputs;
- exact v1.1 facts retain their states and values;
- reference-only and excluded roles remain non-scoring;
- invalid audit hashes fail before database access;
- the PostgreSQL fixture creates all 66 terminal rows;
- stable public IDs and the exact V17 profile-set hash are retained;
- stale prices and missing sector benchmarks remain explicit;
- both model versions are the accepted v2.2/v1.1 versions;
- Long Horizon v1.1 never authorizes a default rank;
- exact V16 audit replay is idempotent;
- conflicting evidence under one idempotency key is rejected.
