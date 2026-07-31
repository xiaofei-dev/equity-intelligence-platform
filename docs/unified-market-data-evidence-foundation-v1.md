# Unified Market Data and Evidence Foundation v1

Status: Task 1 Stages 1 through 3C accepted on bounded local and PostgreSQL 17
evidence; no business-database deployment or provider execution

## Purpose

Unified Market Data and Evidence Foundation v1 implements the provider-neutral
data contract beneath the accepted Dual-System Architecture Contract v1. It
does not merge the Fundamental Value and Quantitative Trading systems, change
their formulas, or grant either system permission to trade.

The first independently testable stage is a migration-free deterministic
selection kernel. It establishes the input contract that later PostgreSQL
registries, calendars, evidence tables, and internal selector endpoints must
satisfy.

## Implementation Preflight

The Stage 1 preflight established:

- the worktree is detached at `57fa7ed`, equal to `origin/main`;
- the accepted, uncommitted Phase 0 artifacts remain present and are the
  contract baseline;
- the active migration head is V17;
- current `main` and `origin/main` do not contain a V18 or V19 migration; and
- reachable snapshot commit `87e2a88` assigns V18 through V21 to Forward
  Decision-Quality and portfolio-decision responsibilities.

Stages 1 and 2 therefore added no migration. The later Stage 3A migration
decision classified V21 application as `NOT_PROVABLE`. V18 through V21 must
therefore retain their historical versions and exact contents rather than be
rewritten, reused, or assigned new checksums.

## Stage 3A: Curated V18-V21 Migration Lineage Adoption

Stage 3A copies only the reviewed migration SQL and the necessary PostgreSQL
acceptance assets from reachable commit `87e2a88`. It does not cherry-pick
that commit's larger snapshot. The repository migration source head at that
stage became V21, while the shared operational application baseline remained
V17.

The four migration files are byte-for-byte identical to their source blobs:

| Version | Git blob | SHA-256 |
| --- | --- | --- |
| V18 | `b42c8d0c6af658a9019ff1e12a00c3aa67d6738e` | `01a01a2ecd11157a1ecce0ea0ff46bb7d1254b5c13a088ab239db2e8f31b054b` |
| V19 | `0ded2a07f26540000e7b6e52ac2532b3340c9d93` | `fc76371dae2294c542c2e6a8f6ef254dbb820338dff51cc9951a84831af0ffb0` |
| V20 | `a12148f6c8017a751b5dc3f39dfe4c862e4b96e8` | `3cf67134a6abb5737a540a2ccf01b9cc40ea4e557556d2dee36701473c826037` |
| V21 | `f2092c0d9b63268ee5d2f1abff39be28bc7bb50e` | `0b88caa2bbeb46468750c675056798ddb0ebdbc33a9c3c884a8129ccc9957846` |

Byte identity applies to these four migration SQL files. The V21 acceptance
asset was intentionally strengthened after adoption to cover all five
append-only tables, their trigger bindings, and both `UPDATE` and `DELETE`
rejection. That test-only strengthening is not represented as byte-identical
source adoption and does not change the V21 migration or checksum.

V19 intentionally refuses to repair an existing v2.1.0 enrollment. That
fail-closed behavior is preserved and has a dedicated negative upgrade path in
the migration runner.

V21 is legacy and unwired. Its historical `CORE` and `TACTICAL` portfolio
lanes are not the accepted `LONG_TERM_CORE` and `QUANT_TRADING` sleeves and
must not be connected to `dual-system-architecture-v1.0.0`. V21 remains
immutable historical lineage, not a persistence implementation of the frozen
dual-system contract. Any future dual-system persistence must use a separately
approved append-only successor. At the Stage 3A boundary, V22 remained
reserved and uncreated.

The database runner now verifies the four source blob identities and defines
dedicated paths for clean V1-to-V21, V17-to-V21, empty V18-to-V19, refusal of
populated v2.1.0 V18-to-V19, V19-to-V21, and V20-to-V21 upgrades. It invokes
the V20 Forward DQV and V21 portfolio schema/immutability acceptance scripts.
The empty V18 path continues through V21 and executes the full V21 suite. The
refusal path requires the exact V19 refusal reason and proves that the original
v2.1.0 row, hashes, V18 constraints, and completeness-trigger state remain
unchanged. The V19-to-V21 and V20-to-V21 paths create representative rows
before the later migrations and verify their identifiers, cardinalities, and
content hashes after upgrade. V21 acceptance verifies the exact five immutable
trigger bindings and both `UPDATE` and `DELETE` rejection on every V21 table.
These PostgreSQL paths must not be reported as passed until they execute on
PostgreSQL 17. Stage 3A performed no application wiring.

## Stage 3B: Append-only V22 Successor

V22 is the separately approved analytics-owned successor. It does not modify
V18-V21, reinterpret V21 `CORE`/`TACTICAL` records, or introduce portfolio
wiring. Its responsibility is durable persistence of the already accepted
provider-neutral contract:

- hierarchical company, instrument, share-class, listing, ticker-assignment,
  and compatibility security identity;
- versioned calendars and completed-session chronology;
- provider contract references and private Git-ignored raw manifests;
- normalized and engine-derived canonical evidence with full lineage,
  revisions, source and normalized hashes, freshness, explicit conflicts,
  field-specific tolerances, canonical domain data, and non-valid states;
- explicit derived-parent evidence identifiers and hashes, authorized
  parent-domain/security/cutoff binding, and sealed parent sets whose
  liquidity cardinality, distinct completed-session dates, and window end
  match the declared observations;
- sealed immutable selector policies, ordered provider priority, requests,
  complete supplied candidate sets, deterministic per-candidate rejection
  reasons, and outcomes;
- successor-only evidence and applicability corrections; and
- classification-bound Fundamental Value applicability routing with a
  deterministic content hash and a latest-only monotonic successor chain.

All V22 state is append-only. Child sets are explicitly sealed and share a
transaction-level lock with child inserts, so a late parent, priority,
candidate, or rejection cannot change an effective aggregate. A correction
creates a complete successor record and must retain the same
provider/source/domain/listing identity with the next source revision.
`MISSING`, `STALE`, `INVALID`, `NOT_APPLICABLE`, and
`EXCLUDED` evidence requires a reason and cannot carry canonical numeric
values. Raw licensed payloads remain outside Git. Canonical domain JSON is
restricted to the frozen provider-neutral keys and cannot contain provider
scores or deterministic model scores.

All RFC 3339 instants are normalized to UTC `Z` before wire serialization or
content hashing. PostgreSQL `TIMESTAMPTZ` session display settings therefore
cannot change a selector request hash or typed readback.

Non-`VALID` engine-derived liquidity uses an explicit zero-parent contract:
it retains the derived layer, derivation version, output/lineage hash, state,
and reason, but has no canonical data, input-parent references, parent rows,
or parent seal. It never fabricates a window or observations. Only `VALID`
derived liquidity may bind and seal parents.

Completed sessions must use a declared IANA timezone and bind the session date
to both scheduled local timestamps. A requested `ADJUSTED_CLOSE` must be a
non-null ordinary decimal string even though `adjustedClose` may remain null
when a different daily-price field is requested. Selector aggregates preserve
and classify every supplied candidate, including request-mismatch evidence,
without allowing it to win.

The Python adapter in
`analysis-python/src/equity_analysis/evidence_foundation/persistence_v1.py`
revalidates `EvidenceCandidate` before persistence and after readback. It
persists only private raw-manifest references for normalized evidence and
requires derived evidence to bind ordered parent evidence identifiers and
normalized hashes. It also persists and reads typed selector
policy/request/candidate/result/rejection aggregates and Fundamental Value
applicability routing. Readback recomputes policy, request, result, and
applicability content hashes before returning typed records. Raw-manifest
conflicts resolve the actual existing row identifier only after every lineage
and private-storage field matches.

The V22 database acceptance covers clean V1-to-V22, V17-to-V22,
prepopulated V21-to-V22, preserved V19 refusal behavior, and representative
V19/V20/V21 row/hash preservation. Negative cases cover ambiguous provider
revisions, missing durable identity bindings, cutoff violations, raw hash
drift, append-only mutation, missing-as-zero, recursive provider-score/rank
leakage, domain value typing, correction chains, tolerance/conflict behavior,
provider ownership, parent binding, deterministic ties, and late-child
sealing. The advanced matrix also covers null adjusted-close selection,
incorrect rejection reasons, liquidity parent cardinality, local-session-date
binding, applicability mapping/hash/successor failures, and audited
request-mismatch candidates. Selector failure precedence is cutoff, dependent
conflict, stale/freshness, explicit non-`VALID` state and reason, tolerance
mismatch, then domain mismatch. A tolerance mismatch cannot replace an
explicit non-`VALID` reason. Conflict `affectedFactors` must be an array of
nonblank strings; nulls, blanks, scalars, and objects fail before selection.

## Stage 1 Contract

Contract version:
`unified-market-data-evidence-foundation-v1.0.0`

Selector version:
`deterministic-evidence-selector-v1.0.0`

The canonical Git-safe fixture is
`contracts/unified-market-data-evidence-v1/selector-request.example.json`.
It contains lineage, identifiers, timestamps, version references, and hashes,
but no licensed raw provider payload.

Stage 2 adds
`contracts/unified-market-data-evidence-v1/domain-canonical-data.example.json`
with synthetic, Git-safe canonical examples for daily prices, corporate
actions, fundamentals, classifications, market benchmarks, dated sector
benchmarks, and derived liquidity.

### Durable identity

Every request and candidate carries:

- security ID;
- company ID;
- instrument ID;
- share-class ID;
- listing ID;
- ticker-assignment ID; and
- current ticker, MIC, and currency presentation attributes.

Stage 1 validates exact identity equality. V22 now persists the approved
registry cardinality while retaining `analytics.security.public_id` as the
compatibility anchor.

### Completed sessions

The selector accepts only `COMPLETED` sessions with a calendar ID and version,
MIC, real session date, timezone, scheduled open and close, early-close flag,
and completion timestamp. The required chronology remains:

```text
scheduledOpen < scheduledClose <= completedAt
              <= decisionCutoff <= sealedIngestionCutoff
```

Stage 1 consumes this contract. V22 persists the versioned calendar/session
identity without replacing the existing refresh-planning calendar.

### Evidence boundaries

The contract separates:

1. a raw manifest containing only allowed storage classification and content
   hash;
2. a normalized observation reference eligible for deterministic selection;
   and
3. engine-derived evidence with a versioned derivation, unique ordered
   parent-evidence ID/hash references, and an output hash bound to its
   canonical record.

Licensed raw payloads must remain under the existing Git-ignored `storage/`
boundary or a future encrypted restricted store. A raw manifest must declare
`PRIVATE_GIT_IGNORED`, `payloadStoredInGit=false`, and the same content hash as
the provider lineage.

### Lineage and usability

Each normalized candidate requires:

- provider code and provider schema version;
- adapter and normalization versions;
- source record ID and positive source revision;
- source and normalized content hashes;
- effective, available, retrieved when present, and ingested timestamps;
- a freshness-policy version and optional stale-after instant;
- strictness and claim classes;
- explicit state and reason for every non-`VALID` state; and
- structured conflict status, criticality, and affected fields.

`DOMAIN_TOLERANT_NUMERIC` candidates require a field-specific policy and
`alignmentSatisfied=true`. Approximate historical research cannot be relabeled
strict PIT or sealed prospective evidence.

### Canonical domain contracts

Stage 2 establishes exact provider-neutral canonical data shapes:

- daily prices: completed session date, explicit adjustment mode, currency,
  ordinary decimal-string OHLC/adjusted close, and integer volume;
- corporate actions: internal action identity, effective date, and
  action-specific dividend, split, or symbol-change terms;
- fundamentals: canonical metric, numeric value, unit, currency, period,
  fiscal period, filing identity/time, and mapping version;
- classifications: taxonomy code/version, sector, industry, company type, and
  effective date;
- market and sector benchmarks: kind, code, security identity, dated mapping,
  and required sector binding for sector benchmarks; and
- liquidity: a versioned engine derivation over a completed-session window,
  valid observation count, dollar/share volume, currency, and policy version.

The domain decoder rejects unknown/provider-native fields, JSON coercion,
noncanonical decimal syntax, impossible or reversed periods, incomplete
action-specific terms, benchmark cross-binding, and liquidity presented as a
raw or normalized provider observation. These contracts validate structure
and semantics only; they add no scoring, valuation, signal, or position-risk
formula.

Stage 2 implementation artifacts are:

- `analysis-python/src/equity_analysis/evidence_foundation/contracts_v1.py`;
- `analysis-python/src/equity_analysis/evidence_foundation/selector_v1.py`;
- `analysis-python/src/equity_analysis/evidence_foundation/domain_contracts_v1.py`;
- `analysis-python/tests/test_evidence_foundation_v1.py`;
- `analysis-python/tests/test_evidence_domain_contracts_v1.py`;
- `contracts/unified-market-data-evidence-v1/selector-request.example.json`;
  and
- `contracts/unified-market-data-evidence-v1/domain-canonical-data.example.json`.

### Deterministic selection

The selector:

1. requires exact security, domain, normalization, strictness, and claim
   alignment;
2. rejects evidence available after the decision cutoff or ingested after the
   sealed ingestion cutoff;
3. applies a nonblank, versioned provider fallback order;
4. chooses the greatest source revision within the first eligible provider,
   then normalized hash and evidence ID as deterministic replay tie-breaks;
5. checks every structurally matching same-provider, same-revision group
   before state, freshness, cutoff, or value eligibility, and fails differing
   normalized hashes as `AMBIGUOUS_PROVIDER_REVISION`;
6. propagates explicit `MISSING`, `STALE`, `INVALID`, `NOT_APPLICABLE`, and
   `EXCLUDED` outcomes;
7. fails the affected selection contract for critical conflicts;
8. blocks only the requested dependent field for noncritical conflicts; and
9. never reads a deterministic score or provider-native field.

The request field is part of the selection identity. Unsupported field codes
fail closed. Daily-price requests bind their field, completed session, listing,
MIC, currency, and adjustment mode to each candidate. Domain constraints bind
fundamental metric/period/unit/currency, action type/date, classification
taxonomy/as-of date, dated benchmark mapping, or liquidity window as
applicable.

Zero candidates are a valid `MISSING` result. An explicit non-`VALID` envelope
requires a reason but cannot carry canonical observation values. No missing
price, volume, fundamental, or other numeric field is fabricated.

Field tolerance is valid only for `DOMAIN_TOLERANT_NUMERIC`, retains a field
code equal to the requested field, and declares semantic, identity, period,
unit, currency, adjustment, and chronology alignment explicitly.
`STRICT_IDENTITY_AND_CHRONOLOGY` cannot carry a tolerance. A
`RESOLVED_WITHIN_TOLERANCE` conflict must be noncritical; every critical
conflict fails the affected selection contract.

Provider provenance remains in the result for audit and licensing. Provider
identity does not change any model formula or score.

### Specialized-model applicability

The Stage 1 data contract routes mature operating companies to generic-model
applicability, banks, insurers, financial companies, REITs, and other approved
specialized types to `SPECIALIZED_MODEL_REQUIRED`, benchmarks to
`NOT_APPLICABLE`, and unknown types to `INSUFFICIENT_EVIDENCE`. It does not
implement a specialized valuation model.

## Verification

The bounded Stage 2 verification is:

```powershell
python -m ruff check src/equity_analysis/evidence_foundation `
  tests/test_evidence_foundation_v1.py `
  tests/test_evidence_domain_contracts_v1.py
python -m pytest tests/test_evidence_domain_contracts_v1.py `
  tests/test_evidence_foundation_v1.py `
  tests/test_dual_system_contract_v1.py `
  tests/test_provider_neutral_market_data.py `
  tests/test_daily_refresh_v1.py -q
```

Result on 2026-07-30 after Stage 2 repair: Ruff passed and `197 passed`.

Stage 3B adds `tests/test_evidence_persistence_v1.py` and
`tests/integration/test_evidence_persistence_postgres_v1.py`. The final
PostgreSQL-backed test requires `TEST_DATABASE_URL`; it performs real
insert/read exact typed equality for normalized, derived, non-valid,
correction, selector/rejection, and applicability records. Its unique
module-scoped fixture seeds every prerequisite on a schema-only database
migrated through V22; it does not depend on acceptance-script rows or test
execution order.

The controller accepted the exact final Stage 3B snapshot on PostgreSQL 17:
the complete V1-to-V22 matrix reported
`Database migration acceptance passed.`, `TEST_EXIT=0`, and container exit
code zero. A fresh schema-only V1-to-V22 database passed both typed
Python/PostgreSQL tests, and the rejection test passed alone on a different
fresh database. Independent Python/persistence and relational audits reported
no residual blocker. This evidence does not claim a business-database
deployment or provider execution.

The final offline bounded regression reports Ruff passed, `228 passed`, and
`2 skipped`; the two skips are exactly the PostgreSQL integration tests gated
by `TEST_DATABASE_URL`.

The tests cover canonical acceptance, deterministic provider fallback,
revision ordering, identity and normalization mismatch, completed-session and
cutoff chronology, freshness, critical and field-dependent conflicts,
non-`VALID` state propagation, raw/normalized/derived separation, raw hash
binding, no-score isolation, ambiguous revisions, tolerance alignment,
claim-ceiling preservation, and specialized-model applicability.
Stage 2 adds canonical acceptance and negative tests for all six domain
families, strict decimal and JSON typing, action-specific fields, fundamental
periods and filing timestamps, classification versions, dated benchmark
bindings, and liquidity parent/output derivation hashes.
The repaired matrix also covers unsupported fields, stale-session candidate
rejection, listing/currency/MIC/adjustment binding, zero-candidate and explicit
missing daily/fundamental outcomes, tolerance-field mismatch, complete
alignment dimensions, strict-evidence tolerance rejection, and
resolved-critical conflict rejection.
It also proves that a `STALE` or `MISSING` envelope without canonical values
cannot hide a normalized-hash conflict with a `VALID` row at the same provider
revision.
Stage 3B additionally proves typed normalized, non-valid, correction, and
engine-derived round trips; private raw-reference enforcement; explicit
parent identity/hash preservation; policy/request/result/rejection and
applicability persistence; raw-manifest identifier reuse; and write/read
contract and content-hash revalidation. The PostgreSQL integration suite also
contains an order-independent database-level liquidity parent-cardinality
negative; it does not depend on the SQL acceptance fixtures.

## Stage 3C: Internal Operational Integration

Stage 3C is migration-free and internal-only:

- `POST /internal/v1/evidence-foundation/selections` accepts a versioned
  command containing canonical request context and persisted evidence IDs.
  Python loads and revalidates every V22 candidate, executes the frozen
  deterministic selector, and seals or idempotently replays the aggregate. A
  new seal returns 201 and a fully loaded, hash-verified exact replay returns
  200. Incomplete, invalid, unreadable, or mismatching durable replay state
  returns stable 409 `EVIDENCE_FOUNDATION_INTEGRITY_CONFLICT`; clean malformed
  input remains 422.
- `GET /internal/v1/evidence-foundation/selections/{requestId}` revalidates
  policy, request, result, rejection, and content hashes before returning the
  internal projection. The result hash is request-bound and covers the
  canonical selector output plus the complete deterministic per-candidate
  rejection map, so equal outputs for different requests cannot collide.
- `GET /internal/v1/evidence-foundation/model-applicability/{companyId}`
  requires `routingVersion` and returns the single unsuperseded,
  hash-verified applicability route.
- Yahoo, EODHD, and future replacements implement
  `provider-evidence-adapter-v1.0.0`. Provider-specific transport parsing and
  licensed raw storage terminate inside the adapter. The coordinator sees
  only canonical typed evidence and Git-safe lineage references. Every batch
  is nonempty, UUID-unique, reparsed through the strict evidence contract, and
  bound to its provider, security, domain, and requested date range. An
  overlap or backfill batch may contain any daily session from `startDate`
  through `endDate`; `endDate` remains the completed-session date. Provider
  absence is an explicit non-VALID envelope, never an empty success.
  Corporate actions require the canonical `CORPORATE_ACTION` field and an
  `effectiveDate` inside the inclusive request range. Fundamental observations
  use snapshot/as-of semantics: they require a requested `metricCode`, and
  `periodEnd` may predate `startDate` but cannot exceed `endDate`. Fundamental
  `startDate` is transport and planning context, not a fiscal-period lower
  bound.
  Classification requests explicitly map `SECTOR_CODE`, `INDUSTRY_CODE`, and
  `COMPANY_TYPE` to their canonical fields and use snapshot semantics:
  `effectiveFrom` may predate `startDate` but cannot exceed `endDate`.
  Non-VALID daily-price and corporate-action evidence uses the candidate
  `effectiveAt` local date inside the inclusive request range. Non-VALID
  fundamental and classification evidence may predate `startDate` but cannot
  be future-effective relative to `endDate`. Adapters should normally use
  `endDate` when recording snapshot absence, while an earlier explicit
  fundamental or classification absence remains valid.
- Unimplemented provider domains fail closed even when a descriptor advertises
  them. `MARKET_BENCHMARK`, `SECTOR_BENCHMARK`, and `LIQUIDITY` require a
  separately implemented governed adapter or engine path with explicit
  canonical field and chronology bindings; they are not pass-through domains
  in Stage 3C.
- Provider request field collections and descriptor domain collections are
  immutable tuples. Descriptor members must be canonical `EvidenceDomain`
  values, preventing post-hash scope mutation or string-valued domain bypass.
- The offline coordinator reuses the existing execution lease, immutable run
  and item journals, content-hashed checkpoints, and resume validation.
  `bind_daily_refresh_plan_v1` deterministically projects the existing
  `daily_refresh.RefreshPlan` onto canonical adapter requests and collapses
  its intentionally shared price-adjustment transport into one physical
  request identity. Request, item, run, plan, and checkpoint identity binds
  the complete durable security and completed-session context. Exact
  canonical evidence replay across runs reuses the immutable V22 row;
  conflicting identity reuse fails closed.
  Fixture tests prove duplicate invocation, partial failure, resume, and
  `UNKNOWN` fail-closed behavior. FastAPI startup does not construct an
  adapter or fetch provider data.

No current Spring Boot public endpoint is replaced, and no model, selector,
portfolio, AI, brokerage, scoring, PIT, missing-state, conflict, or provider
fallback rule changes.

The final deep-immutability snapshot is accepted. The independent Stage 3C
module run reported `33 passed`, and Ruff passed. A fresh disposable
PostgreSQL 17 database migrated from V1 to V22 passed all three typed
Python/PostgreSQL integration tests in 5.05 seconds and was removed. The
complete V1-to-V22 migration, upgrade, refusal, base, and advanced matrix had
already passed on the unchanged V22 schema. Independent relational and
Python/provider/refresh/persistence/API audits reported PASS with no residual
blocker. This does not claim business-database deployment or provider
execution.

A broader historical analytics run reported `727 passed`, `16 skipped`, and
five failures in pre-existing generated-artifact SHA-256 chains. Stage 3C did
not modify those immutable generated artifacts or their source evidence, so
their drift was not rewritten as part of this task.

### Raw Licensed Storage Retention Audit

V22 safely records an immutable Git-safe manifest with provider, source
revision/hash, private storage class/reference, and chronology. It cannot
express durable retention or deletion governance without weakening audit
lineage. An append-only successor needs:

- a versioned retention-policy binding per raw manifest, including policy
  class, jurisdiction or license authority, retention deadline, and legal-hold
  state;
- append-only disposition events keyed to the raw manifest, with ordered
  revision/supersession, event type, effective and recorded timestamps,
  authority, reason code, and storage-reference/content-hash proof;
- constraints preventing deletion before the governed deadline or during a
  legal hold while preserving the immutable manifest and all canonical
  evidence references; and
- uniqueness/cardinality that permits one current governed disposition chain
  per manifest and rejects history rewriting.

V23 is deferred for the MVP. Stage 3C performs no raw-payload deletion and
does not create V23. A future V23 becomes necessary only if the product owns
physical raw-object retention/deletion governance with the policy,
deadline/jurisdiction, legal-hold, disposition-event, proof, and
chain-cardinality responsibilities above.

## Deferred or Separately Governed Boundaries

The following are outside the completed Task 1 scope and remain separately
gated:

- public selector API replacement and operational migration release;
- physical raw-storage retention and deletion governance, deferred with V23;
- any provider execution.

No live provider request, cloud resource, secret change, portfolio operation,
brokerage action, commit, push, or deployment was performed by Stages 1
through 3C. No migration was applied to a business database.
