# Objective Benchmark Coverage and Lineage Feasibility Audit v1

## Decision

The frozen 66-security universe is **not ready** to construct either formal
`PURE_QUALITY` or `PURE_VALUE` benchmarks after preregistration.

The formal denominator is the 55 `INCLUDED` securities: 48 primary and 7
reserve members. The frozen requirement is at least 20 eligible scores and at
least 80% included-population coverage. For 55 included securities, the
effective minimum is therefore 44.

This audit did not run a score, modify a formula, relax a threshold, reinterpret
provider `PASS` as eligibility, issue a provider request, or write PostgreSQL.

## Results

| Benchmark | Formal post-preregistration scores | Pre-registration diagnostic evidence | Required | Status |
| --- | ---: | ---: | ---: | --- |
| `PURE_QUALITY` / `QC-v1.0.0` | 0 | 32 | 44 | `MISSING` |
| `PURE_VALUE` / `UQ-v1.0.0` | 0 | 0 input-ready and 0 accepted scores | 44 | `MISSING` |

The 32 quality diagnostics represent 58.18% of the included population. Even if
their evidence were otherwise complete, 12 more diagnostic candidates would be
needed to reach 80%. They are not formal candidates because they were produced
before preregistration and cannot be upgraded.

The current database snapshot contains:

- zero succeeded screening runs;
- zero `QUANT_ELIGIBLE` coverage rows;
- zero quality or valuation coverage scores;
- zero scored `QC-v1.0.0` or `UQ-v1.0.0` strategy ratings;
- zero factor results and factor-to-source lineage rows; and
- zero scored V17 profile projections.

## Lineage reconstruction

The existing controlled cache contains 42 included-security input manifests.
All 42 payload hashes are valid and all 42 retain operand-level lineage. Across
those payloads, 249 unique operand source-content hashes are retained. The 32
quality diagnostics depend on 192 unique source-content hashes.

For those 32 diagnostics, the audit can reconstruct:

- stable public security identity;
- model version `QC-v1.0.0`;
- the diagnostic gate `effectiveAt`;
- the maximum operand `availableAt`;
- the controlled input payload hash;
- ordered evidence identifiers;
- period identifiers;
- source accessions; and
- source-content hashes.

It cannot reconstruct a complete accepted score ledger:

- score-level `ingestedAt` is absent;
- the current PostgreSQL `analytics.source_record` ledger matches none of the
  192 diagnostic source-content hashes;
- no succeeded V8 screening run binds the scores to factor results and source
  records; and
- the evidence predates the formal preregistration cutoff.

The diagnostic evidence is useful for gap analysis only. It is not eligible
for prospective enrollment.

## Database reuse and gaps

| Migration | Decision | Role |
| --- | --- | --- |
| V14 | Reuse | Stable security identity, classifications, and reference lineage |
| V15 | Reuse | PIT observations and source-record time/hash evidence |
| V16 | Reuse for freshness | Dataset freshness and refresh audit evidence |
| V17 | Reuse as projection only | Immutable product profile after an accepted scoring run |
| V8 | Required authoritative ledger | Coverage, strategy ratings, factor results, and factor-to-source lineage |

V17 cannot replace V8 scoring evidence. No new migration is justified by this
audit: the current blocker is absent accepted evidence, not inability of the
existing schema to represent it.

## Independent prospective blocker

Completing the quality and value score counts would still not authorize
prospective enrollment.

The benchmark v2.1 construction contract requires each included sector
benchmark assignment to resolve to a `REFERENCE_ONLY` security in the same
frozen universe. The frozen universe currently contains only `SPY` and `XLK` as
reference-only securities. This does not provide a reference ETF for every
included sector, so sector benchmark construction remains independently
blocked.

## Required next evidence

Before a future post-preregistration construction attempt:

1. Create a new decision strictly after the preregistration cutoff.
2. Produce at least 44 lineage-complete `QC-v1.0.0` scores for the 55 included
   members.
3. Produce at least 44 lineage-complete `UQ-v1.0.0` scores; the missing
   historical PIT FCF-yield evidence remains a separate prerequisite.
4. Persist score, factor, and source lineage through the V8 ledger with
   `effectiveAt`, `availableAt`, `ingestedAt`, model version, source record, and
   content hash evidence.
5. Resolve the frozen-universe sector reference benchmark conflict through a
   separately governed universe/benchmark decision. Do not silently mutate the
   preregistered universe.

## Reproducible artifact

The Git-safe machine artifact is:

`docs/generated/objective-benchmark-coverage-lineage-feasibility-v1.json`

- File SHA-256:
  `A9BE2C3CC3CFDDDC1C59C64F82EF8875C6188F123C29553DA3850E57D02610D0`
- Canonical artifact hash:
  `sha256:e81249cc0b12114f22e0737546f576a2539ada9d5888aa0c012c829076a89cf5`
- Database writes: `0`
- Provider requests: `0`
- Scores or ranks included: `false`
- Licensed provider values included: `false`

An exact rerun against unchanged inputs must reproduce identical bytes and
hashes. A conflicting artifact is rejected rather than overwritten.
