# Forward DQV Maturity-to-Statistics Adapter v2.2

## Status

The versioned adapter contract is implemented and tested offline. It has not
adapted a real prospective observation and does not establish model
validation.

The checked-in preflight is deliberately `BLOCKED`. The repository has no
executed prospective enrollment, no naturally matured Gate-H outcome batch,
and no production controlled decision values for the frozen 66-security
population.

## Purpose

`FORWARD-DQV-MATURITY-STATISTICS-ADAPTER-v2.2.0` is the strict boundary
between:

1. the immutable prospective enrollment and post-freeze decision manifest;
2. the per-security controlled Tactical v2.2 and Long Horizon v1.1 outputs;
3. the Gate-H maturity outcome batch and path analytics; and
4. `FORWARD-DQV-STATISTICS-INPUT-v2.2.0`.

The adapter does not calculate a new score, change a model result, or fill a
missing value. It only performs a hash-bound join and maps already sealed
evidence into the Statistics v2.2 input contract.

## Exact population join

Every invocation requires exactly the same 66 unique stable
`publicSecurityId` values in:

- the post-freeze decision snapshot;
- the controlled per-security decision evidence;
- and the Gate-H security outcomes.

Duplicates, missing members, replacement members, or an identity set
difference stop the adapter. The join never falls back to ticker symbols.
Gate-H supplemental path analytics are joined only by the typed
`SECURITY:<public UUID>` stable identity. The display-oriented `subjectId`
is never a join key. Benchmark supplements are kept outside the security join.

## Hash and chronology bindings

The adapter revalidates and binds:

- the v2.1.1 enrollment canonical hash;
- the post-freeze decision manifest canonical hash;
- every post-freeze decision row hash;
- every controlled decision evidence hash;
- the Gate-H outcome batch hash;
- the Gate-H maturity analytics bundle hash;
- every consumed Gate-H supplemental evidence hash;
- the sealed decision-session-index evidence hash;
- the preregistration hash;
- the frozen population hash;
- both model freeze hashes;
- the benchmark contract hash; and
- the frozen cost policy hash.

The decision session index is not a caller-supplied integer. A sealed evidence
record binds it to the decision manifest, completed session, decision cutoff,
calendar version, and the same calendar evidence hash carried by Gate-H.

The adapter rejects mixed decision dates, mixed horizons, mixed model versions,
maturity schedule drift, classification-binding drift, and evidence available
after the applicable cutoff. A `CONTRACT_FIXTURE` decision snapshot can never
feed a real statistics observation.

## Per-security deterministic fields

For formal Tactical horizons, the adapter uses only the sealed horizon row:

- `opportunityScore` as the deterministic Tactical score;
- `selectedThesis`; and
- `actionability`.

Abstention is derived mechanically from the frozen actionability. AI or human
provenance cannot change it.

For Long Horizon observations, the adapter keeps distinct fields:

- business quality;
- valuation-entry attractiveness;
- downside risk; and
- the ordered expected-return low/base/high scenario range.

The 126-session horizon is always Long Horizon diagnostic evidence. It is
never emitted as a formal Tactical observation or relabeled as a formal
252-session Long result.

## Gate-H outcome fields

An `ASSESSED` statistics row requires:

- gross return;
- the frozen round-trip cost;
- net return;
- all six benchmark net returns;
- all six benchmark maximum drawdowns;
- per-security MAE, MFE, and MDD;
- per-security downside capture; and
- per-security realized volatility;
- liquidity participation rate.

The formal Gate-H `SupplementalPathAnalyticsV22` is the only producer boundary
for these values. Its canonical evidence hash covers the typed stable identity,
order notional, average daily dollar volume, liquidity participation, downside
capture state/value, and path statistics. The adapter does not introduce a
parallel extension artifact.

Gate-H now produces per-security downside capture when SPY has a compatible
negative-session path. A valid numeric zero is preserved as a real result;
missing SPY evidence remains missing. A completed path with no negative SPY
session preserves the typed
`NOT_APPLICABLE_NO_SPY_NEGATIVE_SESSIONS` metric state while its other usable
row evidence remains intact; it is never converted to zero or collapsed into
generic row missing. Gate-H does not currently have a frozen portfolio
denominator, so `portfolioTurnover` remains explicitly not computable. The
Statistics v2.2 engine computes turnover from adjacent frozen top-band sets
instead of requiring a fabricated per-security contribution. The adapter
therefore binds Gate-H liquidity participation, but does not derive portfolio
turnover from order notional alone.

## Missing-state behavior

A non-assessed output:

- retains an explicit terminal state and reason codes;
- carries no return, benchmark, path, score, or model-result number;
- never converts missing values into zero or a neutral score; and
- cannot be used as an assessed Statistics v2.2 row.

Excluded and reference-only members remain part of the exact 66-security
population, but preserve their explicit non-assessed states.

## AI and human provenance

AI and human evidence are typed as provenance strata:

- AI: `NOT_EXECUTED` or `NARRATIVE_ONLY`;
- human: `NOT_REVIEWED`, `REVIEWED_NO_ACTION`, or
  `REVIEWED_SEPARATE_ACTION`.

Each non-empty provenance record requires a hash and must be available by the
decision cutoff. Both `may affect deterministic result` fields are literal
`false`. Provenance may support later descriptive stratification but cannot
alter scores, returns, benchmarks, terminal states, or validation
classification.

## Current blockers

The contract preflight records:

1. `REAL_PROSPECTIVE_DECISION_SNAPSHOT_NOT_AVAILABLE`;
2. `PROSPECTIVE_ENROLLMENT_NOT_EXECUTED`;
3. `NATURALLY_MATURED_GATE_H_BATCH_NOT_AVAILABLE`;
4. `CONTROLLED_PER_SECURITY_DECISION_VALUES_NOT_AVAILABLE`;
5. `HASH_BOUND_DECISION_SESSION_INDEX_EVIDENCE_NOT_AVAILABLE`;
6. `FORMAL_GATE_H_PER_SECURITY_DOWNSIDE_CAPTURE_NOT_AVAILABLE`; and
7. `CONTROLLED_BENCHMARK_CONSTITUENT_LEDGER_NOT_IMPLEMENTED`.

The deterministic decision-output contract now implements the production
binding for item 4. At execution time the adapter consumes the exact sealed
output set created by the same Tactical and Long Horizon model pass; it does
not rerun either model. The preflight remains blocked until a real output set
exists.

Therefore the current real observation count is zero. No model was evaluated
or validated by this implementation.

## Execution boundary

This work is strictly offline:

- provider requests: zero;
- database reads: zero;
- database writes: zero;
- scores or ranks computed: zero;
- commits, pushes, and deployments: zero; and
- raw provider values in Git-safe artifacts: none.
