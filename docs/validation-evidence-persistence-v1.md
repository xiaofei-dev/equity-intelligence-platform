# Validation Evidence Persistence v1

## Status

`VALIDATION-EVIDENCE-PERSISTENCE-v1.0.0` is the code-only persistence contract
for evidence required by price promotion and Forward Decision-Quality
Validation. It reuses the existing `analytics.source_record` structure from V4
and the append-only `analytics.analytics_audit_event` structure from V16.

This contract does not require V18. It does not modify an observation, promote
a price by itself, execute a provider request, or run a score.

## Safety boundary

- Python Analytics owns all writes.
- Source records must already exist before an evidence event is appended.
- The repository verifies the exact source record ID, content hash, source
  reference, schema version, availability time, ingestion time, and storage
  reference.
- Every event is Git-safe metadata. It contains hashes and durable references,
  never a raw provider body, credential, price value, action value, score, or
  licensed fundamental value.
- Events are append-only. The repository exposes no update or delete operation,
  and V16 rejects database updates or deletes through
  `tr_analytics_audit_append_only`.
- A PostgreSQL transaction-scoped advisory lock serializes one contract version,
  event type, and idempotency key.
- An exact replay returns the existing event ID and event hash.
- Reusing an idempotency key with different canonical evidence is rejected.
- Existing normalized source hashes are never reinterpreted as raw body hashes.

## Event contracts

### `COMPLETED_SESSION_CALENDAR_EVIDENCE`

The event binds one target trading session to two independent, hash-verified
official calendar bodies:

- one NYSE `source_record`;
- one Nasdaq `source_record`;
- each authority's explicit `COMPLETED` state;
- the reviewer and review timestamp;
- the canonical agreement state `BOTH_AUTHORITIES_COMPLETED`.

The two authorities must use distinct source records. Both sources declare
`OFFICIAL_CALENDAR_BODY` hash semantics.

### `RAW_TRANSPORT_BINDING`

The event binds:

- one request journal hash;
- one raw body `source_record`;
- one normalized content `source_record`;
- the normalization version;
- the binding timestamp.

The raw source must:

- declare `RAW_TRANSPORT_BODY`;
- use a schema beginning with `raw-transport-`;
- have a durable `storage_reference`.

The normalized source must declare `NORMALIZED_CONTENT` and must not use the
raw-transport schema namespace. Raw and normalized evidence must use distinct
source record IDs and source references.

Two payloads can theoretically have the same SHA-256 digest, but the digest
does not carry meaning by itself. Their source IDs, typed schema namespaces,
source references, and event roles preserve the different semantics. An older
normalized record therefore cannot be relabeled as raw evidence.

### `ACTION_ADJUSTMENT_RECONCILIATION`

The event binds:

- a stable public security ID and target session;
- the action checkpoint hash;
- the action source manifest hash;
- every selected action revision hash;
- raw and adjusted price revision manifest hashes;
- the adjustment policy hash;
- the reconciliation state and explicit action evidence state;
- all contributing `source_record` bindings.

The state machine distinguishes three cases:

- `SELECTED_ACTIONS` requires at least one selected action revision hash. Its
  reconciliation may be `RECONCILED` or `BLOCKED`.
- `CONFIRMED_NO_ACTIONS` requires zero selected revisions and can only be
  `RECONCILED`. The complete action checkpoint and source manifest are the
  positive evidence that the session contains no applicable action.
- `INCOMPLETE_ACTION_EVIDENCE` requires zero selected revisions and can only be
  `BLOCKED`.

This prevents missing action data from being interpreted as evidence that no
action occurred. The event also records `selectedActionCount` mechanically.

The event records only the reconciliation decision. It does not update an
action or price row.

### `PRICE_VALIDATION_PROMOTION_DECISION`

The event binds:

- a stable public security ID, trading date, and adjustment mode;
- the reviewed evidence cutoff and decision timestamp;
- the validation decision, promotion evidence, and policy hashes;
- every selected prior `daily_price_observation` row ID, revision, and source;
- the new validated row ID and revision only for `PROMOTED`;
- all contributing `source_record` bindings.

`BLOCKED` and `REJECTED` events cannot claim a new validated row. Every bound
price row must refer to a source record declared by the event. Existing rows
remain unchanged.

## Canonical hashing and idempotency

The canonical request payload includes:

- contract version;
- event type;
- idempotency key;
- entity type and entity ID;
- UTC event time;
- correlation hash;
- sorted exact source bindings;
- normalized event-specific evidence.

The canonical request hash is included in the event detail. The final event hash
is the SHA-256 of the complete detail, including the request hash and explicit
`appendOnly` and `gitSafe` flags.

Source record and unordered manifest collections are canonicalized before
hashing. Evidence with equivalent ordering therefore has the same request and
event hashes.

## Exact SQL boundary

The PostgreSQL repository performs only these operations:

1. Acquire
   `pg_advisory_xact_lock(hashtextextended(contract:event:key, 0))`.
2. Read an existing `analytics.analytics_audit_event` by event type, contract
   version, and idempotency key.
3. Read the exact referenced rows from `analytics.source_record`.
4. Insert one row into `analytics.analytics_audit_event` with
   `ON CONFLICT (event_hash) DO NOTHING`.
5. If needed, read that event by its unique event hash.

There is no SQL `UPDATE`, `DELETE`, DDL, price insert, action insert, source
record insert, migration write, or application-schema access in this
repository.

## Repository implementations

- `FakeValidationEvidenceRepository` is a deterministic, append-only fixture
  repository. It validates exact source bindings and uses the event hash to
  derive a stable fixture event ID.
- `PostgresValidationEvidenceRepository` executes the SQL boundary above in one
  transaction and relies on V16's unique event hash and append-only trigger.

The fake repository is the primary unit-test seam. PostgreSQL integration can
reuse the same contract fixtures without changing evidence semantics.

## Verification matrix

The focused test suite verifies:

- all four versioned event types;
- canonical hashes and Git-safe detail;
- exact replay without duplicate append;
- conflict rejection for each event type;
- raw versus normalized hash semantics;
- source-record mismatch rejection;
- canonicalization of unordered source and revision inputs;
- selected-action, confirmed-no-action, and incomplete-evidence state
  transitions;
- promotion-state and new-row invariants;
- PostgreSQL source verification and replay through a SQL fixture;
- SQL limited to V4 `source_record` and V16 `analytics_audit_event`;
- absence of update, delete, or DDL statements.

No provider request, real price promotion, scoring run, database migration,
commit, push, or deployment is part of this contract.
