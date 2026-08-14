# Fundamental Value Investment System v1 Stage 3 Acceptance Candidate

Date: 2026-07-31

## Recommendation

Stage 3 is an engineering `PASS` candidate for strict fail-closed V22 assembly,
with one explicit product-data blocker: accepted V22 canonical evidence does not
yet cover every mature-company operand. The adapter therefore cannot authorize
generic core invocation for a mature company. The master controller must decide
whether that honest non-usable outcome accepts Stage 3 or blocks progression.
Stage 4 remains closed.

## Implemented

- `fundamental-value-v22-assembly-v1.0.0` over repository-rehydrated V22
  selector aggregates and applicability routing;
- exact selector request ID/hash, result hash/replay, selected evidence
  ID/source hash/normalized hash/revision seal verification;
- full durable identity, listing, completed session/calendar, decision cutoff,
  sealed ingestion cutoff, chronology, state, conflict, freshness, semantics,
  and version coherence;
- applicability before operand assembly, including an explicit NBN bank case;
- deterministic enumeration of all 34 `FundamentalValueInputsV1` metric
  operands with no missing-to-zero or missing-to-neutral substitution;
- direct reference-price and supported normalized-fundamental bindings;
- explicit derivation/policy-evidence requirements for V22 coverage gaps;
- duplicate operand/request/evidence refusal and stable failure reasons;
- formula and assumption-policy v1.1.0 parity without a Stage 2 core change;
- exact three-to-ten-year non-Boolean projection-horizon validation and hash
  binding;
- immutable typed canonical selector-request ID collections;
- preregistered selector-contract validation before any non-VALID state can
  propagate;
- deterministic value-free manifest hashing; and
- a canonical Git-safe NBN specialized-routing fixture.

## Verification

Focused Stage 1-3, dual-system, V22 domain, selector, Stage 3C, persistence,
Fundamental Value contract, pure-core, and assembly regressions:

```text
415 passed in 2.27s
Ruff --no-cache: All checks passed
```

The assembly suite contains 67 cases and covers repository ID-only
rehydration, absent/mismatched persisted records, independently expected
identity/session/cutoff anchors, mixed durable/listing
identity, session/calendar/cutoff mismatch, future/stale/ambiguous evidence,
request/result/evidence seal drift, selector/normalization/freshness/routing and
model-version drift, duplicates, unit/currency/period/metric/sign semantics,
provider-native leakage, provider-schema/adapter lineage, projection horizons,
mutable/wrong ID collections, manifest tampering, specialized routing, NBN,
all seven direct operands, and all three capital-allocation gaps. Existing V22
tests retain critical/dependent
conflict, tolerance, canonical-domain, persistence readback, and immutability
coverage.

The Protocol remains a trusted-adapter test seam, not independent evidence
provenance. Production provenance uses `EvidenceFoundationRepository`, whose
PostgreSQL readback recomputes V22 request/result/routing hashes and selector
replay. Five typed tests passed in 4.48 seconds on a clean disposable V1-V22 PostgreSQL 17
database, including exact readback, tampered-hash and missing-ID refusal, a
direct cash operand, and a durable NBN route that loaded no generic operands.

## Git-safe manifest

`contracts/fundamental-value-v1/evidence-assembly-manifest.example.json` is a
synthetic NBN bank route. Its content hash is:

```text
sha256:0dd9f7c67c390b2ef9b0ea13a531a338d6fa1980909a317c300e8c9af15f365b
```

It contains identities, timing, applicability/routing, the projection horizon,
model versions, and provider-schema/adapter lineage versions. It contains no
licensed or canonical value, provider-native field, raw payload/storage
reference, score, rank, weight, or action.

## Remaining blocker

V22 does not currently provide accepted canonical bases for tax rate, D&A,
working-capital changes, EBITDA, distributions, multi-period stability,
valuation-assumption evidence, downside factors, debt maturities, or the full
capital-allocation dimension. V22 permits persisted engine derivation only for
liquidity. Stage 3 does not reinterpret or broaden that responsibility.

Consequently:

- mature-company assembly is explicitly `MISSING` and non-usable;
- `inputs` remains absent;
- `coreInvocationAuthorized` remains false; and
- no ranking, cap, final weight, or action is produced.

An approved future evidence-contract responsibility is required before the
generic model can consume a complete mature-company assembly.

## Stage 5 contract-parity correction

The later service-boundary audit clarified the already intended state/reason
invariant: a fully `VALID` assembly carries an empty `reasonCodes` tuple, while
every non-`VALID` assembly carries stable nonempty reasons. The Stage 3
assembler and cross-language fixtures now use that exact convention. This
changes no operand, formula, applicability, or mature-company coverage claim.

## Boundaries not crossed

No V23 migration, V22 schema/persistence change, business-database write, provider or
network request, API, Spring, frontend, AI narrative, Quantitative Trading,
ranking, final weight, brokerage action, license change, generated historical
evidence rewrite, commit, push, deployment, or cloud resource was created.
Database writes were restricted to the disposable synthetic V22 acceptance
database.
