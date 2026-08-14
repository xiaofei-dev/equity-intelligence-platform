# Fundamental Value Investment System v1 Stage 4 Acceptance

Date: 2026-07-31

## Recommendation

The prior Stage 4 `PASS` candidate is retracted. This document records the
repaired append-only V23 candidate for independent master-controller review.
Stage 5 remains closed until that review passes.

This conclusion is not investment validation. No real mature-company assembly
is currently usable, no real-company Fundamental Value score exists, and the
model-evidence label remains `NOT_VALIDATED`.

## Migration responsibility

`V23__create_fundamental_value_persistence_v1.sql` is an append-only
`analytics.*` successor. It does not alter V1-V22, reinterpret V21 `CORE` or
`TACTICAL`, add `app.*` ownership, or implement raw-payload retention,
deletion, jurisdiction, deadline, legal-hold, disposition, final-weight,
ranking, order, or brokerage responsibilities.

The migration adds 17 append-only tables:

- an empty-by-default governed operand-producer registry and ordered parent
  slots, readable but not writable by application roles;
- assembly root, ordered reasons, canonical operands, ordered evidence
  parents, operand reasons, and assembly seal;
- assessment root, five dimensions, valuation methods, ordered scenarios,
  three ordered ranges, thesis/counter-thesis/invalidation conditions,
  component reasons, risk-cap reasons, and assessment seal.

Applicable mature-company assemblies require the exact ordered 34-operand
contract. Specialized, not-applicable, and insufficient-evidence routes require
zero generic operands. A valid operand has one or more ordered evidence-parent
links; direct operands additionally bind the exact V22 selector and selected
evidence. Non-valid operands have no numeric value or evidence parents. A
non-usable assembly cannot create an assessment graph.

The three primary method identities and weights are exact: FCFF DCF 0.35,
normalized Owner Earnings 0.30, and Earnings Power 0.25. The comparable
cross-check is 0.10 and remains non-controlling. A complete valid assessment
has five dimensions, four method rows, twelve ordered scenarios, three ranges,
and eight structured conditions. Stage 2 retains 0/1/2/3/5 percent tiers, but
V23 freezes `modelEvidenceLabel=NOT_VALIDATED`, so persisted assessments are
restricted to 0, 1, or 2 percent. Limited advanced evidence is at most 1
percent and material refinancing uncertainty requires zero. The ceiling is
never a final portfolio weight.

## Python persistence

`fundamental-value-assessment-persistence-v1.0.0` writes and rehydrates the
normalized graph through `PostgresFundamentalValueBackendV1`. The repository:

- recomputes Stage 3 manifest and Stage 2 input/result hashes;
- rebuilds Decimal values from exact plain text;
- validates ordered child and evidence-parent cardinality;
- replays the deterministic Stage 2 core and refuses changed arithmetic;
- validates producer availability and executable output replay on repository
  and direct PostgreSQL backend readback;
- enforces exact version, security, session, cutoff, method-weight, claim,
  evidence-label, and risk-cap bindings;
- permits exact idempotent replay; and
- rejects conflicting identity reuse, incomplete sets, tampering, updates,
  and deletes.

The Git-safe Stage 3 manifest remains value-free. A private input seal binds
exact Decimal values or non-valid reasons, ordered evidence parents,
governed producer/output versions and hashes, identity, cutoffs, and the
complete version set. Direct operands replay the selected V22 canonical value.
No production derived/policy producer is approved or seeded. Such operands
remain `MISSING` until an append-only successor and matching executable Python
evaluator are accepted. Disposable tests install explicit `TEST_ONLY`
contracts whose identity evaluator recomputes each controlled output from an
exact synthetic parent; these contracts prove mechanics, not economics.
PostgreSQL
enforces structure and sealing, while the trusted Python repository owns full
Stage 2 formula replay and emits `ASSESSMENT_CORE_RECOMPUTATION_DRIFT` for any
semantic mismatch. Ordinary `analytics_writer` callers cannot write V23.

## PostgreSQL 17 acceptance

The final repository migration runner passed in 68.4 seconds. It covered clean
V1-to-V23 installation, V22-to-V23 upgrade and V22 row-count preservation,
the existing V18-to-V19 refusal, prior V18-V22 acceptance paths, the mature
`MISSING` 34-operand outcome, and the synthetic NBN bank route with zero
generic operands.

A separate fresh disposable PostgreSQL 17 database passed all five typed V23
integration tests in 8.64 seconds. The suite covered the honest mature-company
`MISSING` graph, NBN specialized zero operands, a controlled synthetic `VALID`
graph, an evidence-only revision with unchanged arithmetic, value/hash
tampering, dependency substitution, claim/cap elevation, non-finite numerics,
writer-role bypass, exact readback, a real two-connection concurrent initial
insert, and a distinct-content revision-2 race followed by exact idempotent
replay. Direct default-backend load of the controlled test-only record rejects
`OPERAND_PRODUCER_UNAVAILABLE`; a backend with the exact injected test registry
loads the identical typed record. The current honest `MISSING` record had 34 operands, one available
direct evidence parent, and no assessment. The controlled synthetic `VALID`
record had 34 operands, 34 recomputed evidence parents, one assessment, four
methods, and twelve scenarios.

The evidence-only revision intentionally has the same Git-safe manifest but a
different private seal, assembly ID, and assessment ID. The disposable
database and container were removed after evidence capture. All fixture data
was synthetic; no licensed provider value was written to Git.

Final Stage 4 file hashes are:

```text
V23 migration: sha256:2fe3f86e75d28b41c9c8149e74c2369dcd5efe5dc90cf3121ee563c1582b96e8
SQL acceptance: sha256:6076bbc544037aab1a4dfefb77e727d8f072855868f2414988f3fa13250cf787
Python persistence: sha256:1ef7963858d0cb2a5fa32a9a68ca30e712641578d2c983c9a8ac824dabeabc11
Python producer boundary: sha256:ff81ce13aa67843cce62ca2ffd35f946b72e51feec03f4113bc466fb382b3c33
```

## Offline verification

```text
427 focused Stage 1-4, dual-system, V22, and provider-neutral tests passed
5 real PostgreSQL V23 typed integration tests passed
1 No-License/Git-safe boundary test passed
Ruff --no-cache: All checks passed
JSON parse: 3 Fundamental Value contracts passed
Python compile: passed
Markdown local-link check: 13 changed documents passed
git diff --check: passed
```

The broader repository Python suite was sampled through 35 percent before the
bounded 240-second command timeout; no test failure was observed. This partial
run is not counted as a pass and is not used for the Stage 4 recommendation.
The focused regression contains the relevant prior Stage 3 matrix plus V23.
The direct-load repair changed no SQL. The previously passed final migration
matrix therefore remains applicable; the typed suite was rerun from a fresh
V1-to-V23 PostgreSQL 17 database after the Python repair.

The workspace-wide secret scanner still reports 11 pre-existing findings in
unchanged historical generated artifacts. Stage 4 did not modify those files.
The changed-file secret-pattern check and the existing Git-safe license test
passed. The repository remains at No License.

## Remaining product blocker

Current approved V22 canonical evidence does not supply all tax, D&A,
working-capital, EBITDA, distribution, multi-period stability, valuation-policy,
risk, debt-maturity, and capital-allocation inputs. The real mature-company
assembly therefore remains explicitly non-usable. The controlled valid fixture
proves persistence mechanics only; it does not establish provider coverage,
point-in-time support, historical usefulness, forward support, or favorable
investment performance.

No provider request, network fetch, business-database write, API, Spring,
frontend, AI narrative, Quantitative Trading change, migration beyond V23,
commit, push, deployment, cloud resource, brokerage action, or license change
was performed.

## Stage 5 readback-parity correction

The later service-boundary audit standardized successful assembly reasons to
the empty tuple and reused the core canonical finite ordinary Decimal text for
all FastAPI result serialization. V23 typed reconstruction, private seals, and
Python formula replay retain those same canonical semantics; no migration or
persisted arithmetic rule changed.
