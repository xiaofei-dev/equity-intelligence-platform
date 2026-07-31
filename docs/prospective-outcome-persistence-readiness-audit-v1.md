# Prospective Outcome Persistence Readiness Audit v1

## Decision

Successor note: V18 and the Forward outcome v2.1 contract/repository were
implemented and PostgreSQL 17 accepted on 2026-07-29. See
`docs/forward-dqv-v2-outcome-ledger-v18.md`. The immutable v1 audit artifact
continues to describe the pre-V18 state and was not overwritten.

PostgreSQL V1–V17 cannot serve as the authoritative Forward DQV v2 outcome
ledger without an append-only V18 migration. No migration was created by this
audit.

This decision is narrower than, and does not supersede, the earlier validation
runtime-evidence persistence audit. V14–V17 remain sufficient for calendar,
transport, price-promotion, ADTV, score-lineage, and classification evidence.
The new gap concerns naturally matured Forward v2 enrollment and numeric
outcomes.

## Existing capability

V11 already provides append-only legacy experiments, enrollments, signals,
orders, fills, valuations, versioned observation results, generic metrics, and
reports. Its observation result supports a supersession link. V16 adds an
append-only generic analytics audit event, and V17 provides immutable Market
Intelligence profiles and screens.

These structures remain useful and must not be reinterpreted or mutated.

## Structural blockers

V11 restricts observation horizons to 5, 20, and 60 trading days. It therefore
rejects the Forward v2 126-session Long Horizon diagnostic and 252-session
formal outcome.

The V11 shadow arms are entry-policy experiment arms. They include a sector ETF
and SPY but do not define the complete formal benchmark set: SPY, sector,
equal-weight, pure momentum, pure value, and pure quality. There is no
one-row-per-kind completeness rule.

The current Forward v2 contracts bind all five maturities, six benchmarks,
preregistration, immutable decision artifacts, the frozen population, model
freezes, costs, gross and net returns, and price evidence. Their persistence is
content-addressed controlled files. There is no PostgreSQL v2 outcome
repository.

V16 audit JSON can preserve an event trace, but it has no typed horizon,
benchmark, population, maturity, numeric-state, source-chain, or correction
constraints. It must not become an unvalidated substitute for an authoritative
outcome ledger.

The current v2 outcome contract also lacks maximum adverse and maximum
favorable excursion fields. The legacy ledger calculates maximum adverse
excursion but not maximum favorable excursion. A new versioned contract must
define those metrics before they are persisted; immutable v2.0 artifacts must
not be silently changed.

## Exact V18 responsibility

The proposed migration name is
`V18__create_forward_dqv_v2_outcome_ledger.sql`. It adds Python-owned
`analytics.*` tables for:

1. immutable Forward v2 enrollment;
2. the exact 5/20/60/126/252 maturity schedule;
3. versioned outcome batches and single-successor corrections;
4. terminal security outcomes;
5. all six benchmark outcomes;
6. typed path and risk metrics, including MAE, MFE, maximum drawdown, and
   downside capture;
7. target-specific Forward v2 quality reports.

Every new table must reject update and delete. Missing, stale, invalid,
not-applicable, and excluded evidence must retain null numeric values and an
explicit reason. Complete batches must bind the entire frozen population and
all six benchmark states. Corrections must append a new same-enrollment,
same-horizon version and must not branch, cycle, or overwrite prior evidence.

The migration must not alter `app.*`, V1–V17 data, formulas, model weights,
brokerage execution, or the AI boundary.

## Verification boundary

This audit read only migration and source files. It made no provider request,
database connection, database write, scoring run, formula change, commit,
push, or deployment.

The machine-readable evidence is:

`docs/generated/prospective-outcome-persistence-readiness-audit-v1.json`
