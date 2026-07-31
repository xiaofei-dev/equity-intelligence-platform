# Validation Evidence Persistence Gap / V18 Necessity Audit v1

## Decision

V18 is not required for the accepted v1 validation-evidence contracts.

The two authoritative diagnostics remain genuinely blocked:

- `docs/generated/price-promotion-preflight-20260729-beaa9952.json`
- `docs/generated/forward-benchmark-db-readiness-v2-1-beaa9952.json`

Their blockers must not, however, be treated as proof that PostgreSQL lacks the
necessary persistence structures. V14-V17 already provide append-only source
lineage, versioned metric observations, profile fact and classification lineage,
refresh checkpoints, immutable observations, and a generic immutable analytics
audit event.

The correct next step is to implement and execute bounded persistence contracts
against those existing structures. This audit does not authorize promotion,
scoring, enrollment, or any database write.

## Classification

| Requirement | Disposition | Reason |
| --- | --- | --- |
| Completed-session calendar evidence | `CODE_ONLY` | Official NYSE/Nasdaq bodies can be stored as separate source records and bound, reviewed, and hashed in an immutable audit event. The bodies and review are currently absent. |
| Raw transport body hash/reference | `CODE_ONLY` | A separate raw-transport source record can retain the raw body hash and durable external storage reference. A versioned audit event can bind it to normalized evidence. Existing normalized hashes must never be relabeled as raw hashes. |
| Action-to-adjusted-price binding | `CODE_ONLY` | Existing action rows, price revisions, checkpoints, source hashes, and audit events can express a complete versioned reconciliation. The reconciliation contract has not been run. |
| Price validation/promotion hashes | `CODE_ONLY` | Immutable audit events can bind validation and promotion decisions to exact prior/new price revisions without modifying older rows. |
| Decision-time ADTV | `REUSE_V14_V17` | V15 metric definitions and metric observations already retain value, unit, state, decision date, PIT timestamps, source, and revision. The observations are missing, not the schema. |
| Objective score lineage/timing | `REUSE_V14_V17` | Objective scores can be persisted as metric observations and attached to V17 profiles with ordered fact lineage. Current profile score columns were not accompanied by those existing bindings. |
| Real sector lineage | `REUSE_V14_V17` | V14 company-profile classifications and V17 classification lineage already preserve taxonomy, source, and PIT timing. `VALIDATION` is a data-quality placeholder, not a schema limitation. |

## Why the generic audit event is sufficient

`analytics.analytics_audit_event` is append-only, content-hashed, correlated,
and stores a versioned JSON object. It is appropriate for evidence envelopes
whose fields are contract-defined but do not represent reusable numeric
observations. The event must contain exact row/source identifiers and hashes;
an untyped narrative blob is not sufficient.

Reusable numeric evidence remains in typed tables. ADTV and Objective scores
belong in `analytics.metric_observation`, with profile facts and ordered source
lineage where applicable.

## Raw transport boundary

V4 `source_record.content_hash` does not identify whether a hash covers a raw
response or normalized content. Existing yfinance hashes are normalized evidence
and remain so.

The code-only contract must:

1. create a separate source record explicitly designated by schema/version as a
   raw transport body;
2. hash the raw response bytes;
3. retain the body outside PostgreSQL using `storage_reference`;
4. bind raw and normalized source IDs in a versioned immutable audit event; and
5. reject replay when either hash or binding differs.

No licensed raw body is stored in Git or PostgreSQL.

## Ownership and migration testing

- `analytics.*` remains owned by Python Analytics.
- `app.*` is unchanged.
- No migration is created.
- Existing clean PostgreSQL 17 V1-to-V17 and V16-to-V17 tests remain mandatory.
- New tests should cover audit-event replay/conflict, raw/normalized semantic
  separation, PIT ADTV selection, Objective score lineage reconstruction, and
  classification placeholder rejection.

If future evidence cannot be represented after implementing these exact
contracts, a new audit must identify the irreducible relational constraint
before an append-only migration is proposed.
