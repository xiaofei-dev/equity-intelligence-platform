# Forward Decision Snapshot v2

Date: 2026-07-29

## Purpose

`FORWARD-DECISION-SNAPSHOT-v2.0.0` is the first no-migration foundation for
prospective validation of:

- `TACTICAL-SIGNAL-v2.2.0`; and
- `LONG-HORIZON-RESEARCH-v1.1.0`.

It does not modify the immutable QC-specific Forward v1 preregistration, the
V11 prospective ledger, the V17 Market Intelligence projection, any model
formula, or any provider evidence. It does not execute an outcome observation,
database write, provider request, historical score, trade, or deployment.

The contract seals what the models actually decided for every security in one
READY daily data snapshot. Future Forward v2 work may observe naturally
matured outcomes against that immutable decision.

## Accepted model freezes

The snapshot loader verifies each freeze against its source contracts and
binds three independent identities: the canonical artifact content hash, the
governance freeze-record hash, and the physical file SHA-256.

| Track | Artifact content hash | Freeze-record hash | File SHA-256 |
| --- | --- | --- | --- |
| Tactical v2.2 | `A596080CD7936A6881A38E759C597934DAE1125EC83026DF6DB0434F6FE31910` | `D6E3EDB1160856ADE700C37D42A4C9E2CDDA3B88A4080DBC8ED73354B4C5BF99` | `5D541315F62990BC5F44A4E421F404D737F6FFCF039E586B18BA362A113DC49F` |
| Long Horizon v1.1 | `233271457387A5D7212379AE2C77D69C743DC69F7345FE2D834FF7DC98D4FA59` | `8F8E7FB671A8C35E771FDAD6B9E3ED5D90950135ACC9297BBFF571F27780E6C3` | `E208C280355077009C4AF102383881D89D3139242086E859B5EEC4BEB6873024` |

A future model or freeze must use a new version and explicit acceptance. A
self-consistent but different freeze cannot silently enter this v2.0
contract.

`INPUT_CONTRACT_ONLY` remains representable for offline construction before a
freeze exists. Such a snapshot is always
`prospectiveReady=false/MODEL_FREEZE_ARTIFACT_PENDING` and cannot be treated as
prospective evidence.

## Snapshot identity

Every controlled snapshot binds:

- one PostgreSQL data-snapshot UUID in `READY` state;
- the exact decision cutoff and seal timestamp;
- universe version, universe hash, and source-snapshot hash;
- the ordered frozen population and its canonical SHA-256;
- the exact V17 profile set and its canonical SHA-256;
- both accepted model freezes;
- dated market and sector benchmark evidence;
- the frozen cost-policy contract;
- prospective availability, frozen-universe, action-ledger, evaluation-role,
  and outcome-dependence evidence states;
- an idempotency key and independently derived idempotency hash; and
- `aiUsedForDeterministicDecisions=false`.

Every frozen public security ID must have exactly one terminal row for each
model track. Valid terminal states are `ASSESSED`, `MISSING`, `STALE`,
`INVALID`, `NOT_APPLICABLE`, `SPECIALIZED_MODEL_REQUIRED`, and `EXCLUDED`.
Missing rows, duplicate public IDs, duplicate profile IDs, or a mismatched
profile-set hash fail construction.

## Tactical v2.2 boundary

The controlled artifact retains:

- the exact input, feature, and model versions;
- decision cutoff, completed as-of session, next-session effective rule, and
  one-completed-session TTL;
- market and sector benchmark identities;
- all eleven component states and scores;
- deterministic event-risk state;
- independent one-week, one-month, and three-month thesis, continuation,
  mean-reversion, opportunity, entry-value, risk, outlook, actionability,
  confidence, and risk-unit-cap fields;
- missing inputs, reasons, warnings, and canonical result hash.

The builder rejects any TTL other than one completed session and requires
exactly the 5-, 20-, and 60-session horizons. Missing evidence cannot carry a
neutral score.

## Long Horizon v1.1 boundary

The controlled artifact retains:

- business quality;
- financial strength;
- capital allocation;
- valuation and entry;
- expected-return low, base, and high range;
- downside risk;
- sector-relative evidence;
- evidence confidence;
- factor states and normalized scores;
- missing, invalid, not-applicable, cohort, and specialized-model states;
- input, evidence, and canonical result hashes.

Long Horizon v1.1 has no default ranking score. The snapshot contract requires
`defaultRankingScore=null` and
`deterministicRankingAuthorized=false`. It must not be coerced into the
single-score V17 horizon projection or the TOP/BOTTOM V11 signal contract.

## Controlled artifact and Git-safe manifest

The complete deterministic decision is a content-addressed controlled
artifact under:

`storage/forward-validation/decision-snapshots-v2/<sha256>.json`

The repository-safe manifest contains only:

- stable IDs and symbols;
- terminal and exclusion states;
- model input, evidence, result, freeze, universe, profile-set, controlled
  artifact, and manifest hashes;
- counts, readiness, and blocker codes.

It explicitly records:

- `rawProviderValuesIncluded=false`;
- `deterministicNumericResultsIncluded=false`; and
- `aiUsedForDeterministicDecisions=false`.

The manifest does not contain Tactical scores, Long Horizon dimension scores,
expected-return values, or raw licensed provider observations. Repeating the
same idempotency key with different evidence is a conflict. Existing artifacts
are verified byte-for-byte and are never overwritten.

## First real local handoff

The first executed local handoff sealed:

- source READY snapshot:
  `beaa9952-9852-4088-9dc3-92047824414b`;
- universe: `market-intelligence-closed-test-us-v1.0.0`;
- decision as-of and seal time: `2026-07-29T02:57:08.988871Z`;
- complete population: 66 securities, comprising 55 included, 2
  reference-only, and 9 excluded;
- controlled artifact hash:
  `sha256:b00971fee0500a8d02f22e28b5402b8db36322127dc6500b6e354c60eb9d839c`;
  and
- Git-safe manifest:
  `docs/generated/forward-v2-decision-snapshot-20260729T025708Z-beaa9952.json`,
  with content hash
  `sha256:6afcfa078cafaa16dacf302d9cd71a63c586f0f1d8b5a157eaf7f0aab3247b30`.

The handoff made zero provider calls and records
`aiUsedForDeterministicDecisions=false`. It is not prospective-ready. The
v2.0 manifest reports the aggregate
`REQUIRED_BENCHMARK_EVIDENCE_UNAVAILABLE` blocker, but the later v2.1
evidence audit resolved the underlying causes rather than treating that
aggregate code as sufficient proof:

- all stored price rows used by the handoff are `PROVISIONAL`, not
  `VALIDATED`;
- the member sector value is the placeholder `VALIDATION`, not a dated real
  classification;
- no complete real-sector ETF assignment is frozen; and
- the stored Objective quality and value evidence cannot construct the
  required pure-quality and pure-value families.

Consequently no enrollment or outcome was created and model quality remains
`INSUFFICIENT_EVIDENCE`. The sealed v2.0 artifact remains byte-identical and
cannot be upgraded after the decision by attaching the later v2.1 benchmark
preregistration.

## V16 audit-event handoff

`build_v16_audit_event_payload()` creates an append-only event compatible with
`analytics.analytics_audit_event`:

`FORWARD_V2_DAILY_DECISION_SNAPSHOT_SEALED`

The payload includes only stable identity, hashes, terminal counts, readiness,
and blocker evidence. The core builder performs no database write and records
`providerNetworkRequests=0`.

The approved local assembler recorded the first handoff in V16 with audit event
hash
`sha256:eff628373f0c4a354cf761e30387713db1a2cb5acb41ce7fef61862a2e034542`.
An exact replay confirmed the same event instead of creating divergent
evidence. This V16 event remains an audit handoff, not the structured Forward
v2 ledger.

## Readiness and stop conditions

A snapshot is prospective-ready only when:

1. both accepted model freezes are sealed;
2. the source data snapshot is READY;
3. the complete frozen population and V17 profile set match;
4. every Tactical cutoff equals the READY snapshot cutoff;
5. price and classification evidence is valid at the decision cutoff;
6. all six v2.1 benchmark constructions are independently available;
7. both the parent liquidity-cost policy and benchmark-construction cost
   policy match their preregistered hashes;
8. the benchmark preregistration predates the decision; and
9. no deterministic decision used AI.

This stage stops before enrollment, outcome observations, V18, routes, Java
APIs, or automatic execution. Forward v2 outcome maturity, benchmark-return
calculation, and a durable PostgreSQL ledger require separate controller
acceptance.
