# Forward Decision-Quality Validation v2 Persistence Decision

Date: 2026-07-29

## Decision status

`V18_IMPLEMENTED_FOR_STRUCTURED_DURABLE_FORWARD_V2`

The bounded successor was implemented on 2026-07-29 as
`V18__create_forward_dqv_v2_outcome_ledger.sql`. The original gap analysis
below is retained as decision history. The authoritative implemented contract
is documented in `docs/forward-dqv-v2-outcome-ledger-v18.md`.

V16 audit events remain content-addressed trace evidence. They are not
reinterpreted as typed outcome rows.

## Why V11 cannot be extended implicitly

PostgreSQL V11 is a ranked-signal experiment ledger. Its candidate rows require:

- a numeric score;
- a `TOP` or `BOTTOM` score bucket;
- a positive notional allocation; and
- observation horizons restricted to 5, 20, or 60 trading sessions.

Forward v2 must retain the complete frozen population, including abstentions,
missing evidence, excluded securities, and long-horizon assessments that
intentionally have no default ranking score. It must also mature 126- and
252-session outcomes. Writing these records into V11 would either violate its
constraints or misrepresent the v2 contract.

Existing V11 records remain immutable and continue to represent Forward v1.

## Why V17 is a projection, not the Forward v2 ledger

PostgreSQL V17 persists Market Intelligence product profiles. An assessed
horizon view requires a numeric score. Long Horizon v1.1 intentionally does not
authorize a default cross-sectional score or ranking.

V17 may continue to expose compatible product projections, but it cannot be the
canonical store for:

- both accepted model freezes;
- a complete-population daily decision snapshot;
- typed Tactical and Long Horizon terminal states;
- low/base/high expected-return ranges without a default rank;
- immutable 5/20/60/126/252-session outcomes; or
- superseding Forward v2 reports.

## Safe no-migration bridge

V16 `analytics.analytics_audit_event` can record an append-only event that
references:

- the decision snapshot manifest hash;
- the controlled artifact hash and storage reference;
- the idempotency hash;
- the frozen universe and profile-set hashes;
- both model-freeze hashes;
- the decision cutoff; and
- whether the snapshot is prospectively eligible.

The audit event does not replace a structured ledger. It must not contain raw
licensed provider values, secrets, or mutable local-file state.

## Proposed V18 responsibilities

A separately approved append-only V18 should create purpose-specific Forward v2
tables for:

1. **Model freeze registrations**
   - model track and version;
   - freeze, artifact-content, and file hashes;
   - observed-evidence cutoff and freeze time;
   - benchmark, cost, protocol, and governance versions.

2. **Daily decision snapshots**
   - one idempotent snapshot for a frozen universe and decision cutoff;
   - controlled artifact and Git-safe manifest hashes;
   - READY data snapshot and profile-set hashes;
   - prospective readiness and explicit blockers.

3. **Complete-population decision rows**
   - stable public security ID;
   - Tactical and Long Horizon terminal states;
   - input, evidence, and result hashes;
   - explicit missing, invalid, not-applicable, and exclusion reasons;
   - no required numeric score.

4. **Outcome observations**
   - 5, 20, 60, 126, and 252 completed-session horizons;
   - immutable result versions with supersession links;
   - benchmark and cost-adjusted results;
   - operational and evidence states separate from performance;
   - no mutation of the originating decision.

5. **Validation report snapshots**
   - naturally matured population and coverage;
   - dependence-aware uncertainty evidence;
   - benchmark, cost, risk, and abstention metrics;
   - validation terminal state and claim ceiling;
   - immutable superseding report versions.

All V18 tables must reject update and delete operations. Exact duplicate
idempotent writes may return the existing row; a reused idempotency key with
different evidence must fail.

## Required migration acceptance

If V18 is authorized, acceptance must include:

- clean PostgreSQL 17 `V1 -> V18`;
- populated `V3 -> V18`, `V12 -> V18`, `V16 -> V18`, and `V17 -> V18`;
- append-only trigger tests;
- exact replay and conflicting replay tests;
- complete-population accounting;
- nullable-score and typed-missing-state tests;
- all five horizon constraints;
- immutable snapshot-to-outcome foreign-key tests;
- superseding outcome and report tests;
- analytics runtime roles without DDL authority; and
- confirmation that no `app.*` object is written by Python.

## Authorization gate

The migration and internal Python v2.1 PostgreSQL repository are accepted.
Route exposure, Java integration, frontend changes, actual outcome collection,
quality claims, commit, push, and deployment still require their own gates.
