# Fundamental Value Investment System v1

Date: 2026-07-31

## Status

`FUNDAMENTAL-VALUE-v1.0.0` is the frozen deterministic methodology contract
for the `LONG_TERM_CORE` sleeve. This Stage 1 freeze defines scope, method
roles, state handling, safety boundaries, persistence responsibility, and
validation sequencing. It does not yet implement valuation calculations,
persist an assessment, call a provider, validate investment performance, or
authorize a portfolio weight or trade.

The initial model evidence label is `NOT_VALIDATED`.

## Supported scope and applicability

The generic model supports mature nonfinancial United States listed operating
companies only. Applicability is resolved before any factor or valuation
calculation.

| Company type | Generic v1 result |
| --- | --- |
| Mature nonfinancial operating company | `APPLICABLE` after evidence gates |
| Bank, including NBN | `SPECIALIZED_MODEL_REQUIRED` |
| Insurer | `SPECIALIZED_MODEL_REQUIRED` |
| REIT | `SPECIALIZED_MODEL_REQUIRED` |
| Resource or commodity producer | `SPECIALIZED_MODEL_REQUIRED` |
| High-uncertainty biotechnology company | `SPECIALIZED_MODEL_REQUIRED` |
| Other financial company | `SPECIALIZED_MODEL_REQUIRED` |
| Incompatible conglomerate | `SPECIALIZED_MODEL_REQUIRED` |
| Benchmark | `NOT_APPLICABLE` |
| Insufficient public history | `INSUFFICIENT_EVIDENCE` |

There is no generic fallback for a specialized, unknown, conflicting, or
insufficient-history case. A future specialized model requires its own model
version, formulas, evidence requirements, freeze, and validation.

## Deterministic output boundaries

The assessment keeps the following concepts independent:

1. company quality and security attractiveness;
2. central fair value and the ordered fair-value range;
3. reference price and margin of safety;
4. expected return and downside risk;
5. deterministic evidence/calculation and AI narrative; and
6. model risk-cap ceiling and final human portfolio allocation.

Every output component uses one explicit state:

- `VALID`
- `MISSING`
- `STALE`
- `INVALID`
- `NOT_APPLICABLE`
- `EXCLUDED`

A non-`VALID` component requires a stable reason and carries no fabricated
numeric value. Missing, stale, invalid, conflicting, or excluded evidence is
never converted to zero, a neutral contribution, or favorable evidence.

## Company economics

Stage 2 will implement separately versioned deterministic dimensions for:

- company quality;
- financial resilience;
- earnings and cash-flow quality; and
- capital allocation quality.

Capital allocation quality is a separate price-independent dimension. The
frozen core requires three provider-neutral deterministic evidence measures:
incremental return on
invested capital, acquisition discipline, and shareholder-distribution
coverage. Incremental ROIC is scored linearly from -5 percent to 20 percent;
the two normalized discipline and coverage measures are scored from zero to
one. Every factor is required in v1. A missing, stale, invalid, excluded, or
not-applicable factor propagates explicitly and cannot become zero or neutral.
Scores below 40, 55, and 70 cap the Fundamental Value ceiling at 1, 2, and 3
percent respectively. Capital-allocation quality can only preserve or lower a
cap, never increase it.

Price-sensitive evidence cannot change company quality. Advanced evidence,
including debt maturities and lease/refinancing obligations, is explicit.
Missing advanced evidence normally lowers the claim ceiling and risk-cap tier.
It blocks valuation when leverage or refinancing exposure makes the missing
evidence material under the frozen risk policy.

## Valuation family

The frozen primary valuation methods are:

1. FCFF discounted cash flow;
2. normalized free cash flow or Owner Earnings; and
3. Earnings Power.

Comparable valuation is a cross-check only. It cannot be the controlling
primary conclusion and has a maximum aggregation weight of 15 percent.

Every eligible method returns an ordered low, central, and high value with:

- explicit method and formula versions;
- assumption-policy version;
- complete evidence identifiers and hashes;
- decision and evidence timestamps;
- currency and reference security identity;
- terminal-value and sensitivity evidence where applicable; and
- explicit limitations and claim ceiling.

## Aggregation

`FUNDAMENTAL-VALUE-WEIGHTED-MEDIAN-QUANTILE-v1.0.0` aggregates eligible
methods using:

- a preregistered weighted median for the central estimate;
- ordered weighted 25th and 75th quantiles for the range; and
- maximum method weights that prevent any single method from dominating.

An unrestricted minimum/maximum envelope is prohibited. The output must
satisfy exact Decimal ordering:

```text
fairValueLow <= fairValueCentral <= fairValueHigh
```

The aggregation policy never selects a provider, method, assumption, or
revision because it improves a score, historical result, or recommendation.

## Price attractiveness and expected return

Reference price is separately selected through the V22 completed-session and
evidence-selector boundary. Margin of safety is derived from the reference
price and fair-value estimates; it does not alter company quality.

Expected return is an ordered range, not a promise. It remains separate from
downside evidence. A favorable expected-return range cannot hide a material
leverage, impairment, concentration, liquidity, or refinancing risk.

## Thesis and invalidation evidence

Deterministic thesis, counter-thesis, and invalidation records are structured
evidence bindings. Each record carries a stable claim or condition code,
state, threshold where applicable, evidence IDs and hashes, timestamps, and
version references. Free-form AI text is not a deterministic thesis input.

## LONG_TERM_CORE risk-cap boundary

`LONG-TERM-CORE-RISK-CAP-TIERS-v1.0.0` permits only these security-level
allocation ceilings:

- 0 percent;
- 1 percent;
- 2 percent;
- 3 percent; or
- 5 percent.

The result is a ceiling, never a target or final portfolio weight. Spring-owned
user and portfolio constraints may only reduce the permitted allocation. An
explicit human decision remains required for every final allocation and every
real-world action. The model never authorizes brokerage execution.

## Evidence and AI boundary

The assembly layer may consume provider-neutral V22 canonical evidence and
sealed selector outcomes by immutable ID and hash; the engine consumes only a
complete typed assembly, which current V22 coverage cannot yet produce.
Provider-native fields and provider identity never enter a formula. V22 strict identity, chronology, conflict,
freshness, correction, missing-state, and claim-class rules remain unchanged.

AI is a cited, versioned narrative layer. It cannot fill evidence, change a
state, formula, factor, valuation, rank, risk cap, model-evidence label, final
weight, or trade decision.

The Quantitative Trading system is not an input. Its scores, signals, setup,
position-risk output, sleeve cash, and validation results cannot affect this
model.

## Persistence decision

V23 is reserved as a narrowly scoped append-only Fundamental Value successor.
It may persist complete method, scenario, evidence-binding, thesis,
invalidation, validation-label, and risk-cap cardinality without changing or
reinterpreting V1-V22. V21 `CORE` and `TACTICAL` remain legacy and unwired.

V23 excludes raw-payload retention, deletion, jurisdiction, deadline,
legal-hold, disposition-event, and deletion-proof governance. If that product
responsibility is later approved, it must use the next migration version
available after V23.

## Validation sequence

Validation is target-specific for company quality, security attractiveness,
expected return, downside risk, and margin-of-safety usefulness.

1. structural and deterministic acceptance;
2. reproducible historical time-slice validation with realistic point-in-time
   availability where supported;
3. an honest target-level conclusion, including `NOT_VALIDATED`; and
4. prospective Forward Decision-Quality Validation only after structural and
   historical acceptance.

Historical evidence retains its correct ceiling. Current-revision or already
observed evidence is not promoted to `PIT_SUPPORTED` or `FORWARD_SUPPORTED`.
Observed outcomes cannot modify this frozen methodology merely to improve a
result.

## Stage 2 deterministic formulas

Stage 2 implements a provider- and persistence-independent Decimal core.

## Stage 3 V22 evidence assembly

`fundamental-value-v22-assembly-v1.0.0` consumes only repository-rehydrated
V22 `PersistedSelectorAggregate` records and a content-hashed applicability
routing. Callers provide selector request IDs, never metric values, and bind
independently expected durable identity, completed
session, decision cutoff, and sealed-ingestion cutoff. Evidence seals are
repository-rehydrated and verified internally against the deterministic V22
request ID, request hash, result hash, selector replay, selected evidence ID,
source and normalized hashes, and source revision before any operand can be
read.

The repository Protocol is a trusted-adapter test seam, not evidence
provenance by itself. The production persisted-read boundary is the accepted
`EvidenceFoundationRepository`; its PostgreSQL readback recomputes request,
result, and routing hashes and deterministic selector replay. Arbitrary
duck-typed implementations must not be described as persisted V22 evidence.

The classification selector and applicability routing run first. Their company
ID, classification evidence ID, company type, routing revision, routing hash,
and effective time must match. NBN and every other bank stop as
`SPECIALIZED_MODEL_REQUIRED` before operand assembly. Insurers, REITs,
resources, biotechnology, other financials, special-situation/incompatible
conglomerates, benchmarks, and insufficient-history cases follow the frozen
fail-closed routes and cannot invoke the generic core.

For an applicable mature company, every selector must share the full durable
security/company/instrument/share-class/listing/ticker-assignment identity,
ticker, MIC, currency, completed calendar/session, decision cutoff, and sealed
ingestion cutoff. The adapter preserves selector states and reasons. It rejects
duplicate operand/request/evidence bindings, ambiguous or nonreproducible
selection, future evidence, stale evidence, conflicts, semantic mismatch, and
version drift. Missing is never converted to zero or a neutral value.

The preregistered direct V22 operands are:

- unadjusted completed-session close for `reference_price`;
- diluted shares;
- cash and equivalents;
- total debt;
- operating income as EBIT;
- capital expenditure; and
- normalized free cash flow.

Each fundamental selector binds an exact metric code, `TTM` or `INSTANT`
period semantics, unit, currency/null-currency rule, mapping version,
normalization version, freshness policy, and operand-specific selector policy.
Gross cash, debt, capital expenditure, diluted shares, and reference price
must be nonnegative where required by the core sign contract.

Current V22 normalized fundamentals do not contain all bases required for tax,
D&A, working-capital changes, EBITDA, distributions, multi-period stability,
valuation assumptions, risk evidence, debt maturities, or the three
capital-allocation operands. V22 also permits persisted engine-derived evidence
only for liquidity. Stage 3 therefore records each unavailable core operand as
an explicit `MISSING` derivation or policy-evidence requirement and does not
invoke the core. It does not broaden V22 semantics, accept a provider-native
field, or invent a policy constant. A later gate must close these evidence gaps
through an explicitly approved canonical-evidence responsibility before a
mature-company assembly becomes usable.

The Git-safe assembly manifest contains identities, chronology, states,
reasons, selector request/result hashes, evidence IDs, source/normalized
hashes, revisions, provider-schema and adapter lineage versions, routing
versions, the validated three-to-ten-year projection horizon, and
formula/assumption v1.1 bindings. Provider-neutral means provider-native
fields, formulas, and licensed values never enter the engine or Git-safe
manifest; provider/adapter schema lineage may identify the source adapter. It
excludes canonical numeric values, raw provider values and payload/storage
references, scores, ranks, recommendations, weights, and trade instructions.
The entire manifest has a deterministic SHA-256 content hash.

## Stage 4 V23 persistence

V23 is an append-only `analytics.*` successor for deterministic Fundamental
Value assembly and assessment records. It does not alter V1-V22, V21 lane
semantics, or the `app.*` ownership boundary. The persisted assembly keeps the
complete Stage 3 identity, routing and classification seals, session and
cutoffs, projection horizon, state and reasons, version set, operand states,
and manifest hash. Non-usable assemblies are durable first-class outcomes and
cannot carry numeric substitutes or assessment children.

The public Git-safe manifest intentionally excludes licensed numeric values.
Persistence therefore adds a private deterministic input seal that binds the
full durable identity and cutoffs, complete version set, each operand's exact
canonical Decimal value or explicit non-valid reason, ordered evidence-parent
hashes, and required derivation or policy-evidence output contract. A numeric
change changes assembly identity even when the Git-safe manifest is unchanged.

Applicable mature-company assemblies preserve the canonical ordered set of 34
operands. Specialized, not-applicable, and insufficient-evidence routes carry
zero generic operands. Each valid operand binds an ordered, immutable set of
canonical evidence parents by durable evidence ID, source and normalized
hashes, revision, and chronology. Direct V22 operands additionally bind the
exact selector request/result seal. This parent relation exists because a
deterministic derivation can depend on more than one evidence record; a single
JSON provenance blob is not sufficient relational cardinality.
Daily-price and direct-fundamental operands are replayed against the selected
V22 `canonicalData` value and exact unit, currency, field, and period
semantics. Derived and policy-evidence operands require a governed producer
contract with a matching executable Python evaluator, exact ordered parent
roles and semantics, currency, period identity, output semantics, and contract
hash. V23 seeds no production producer contracts, so every currently
unsupported derived or policy operand remains `MISSING`. Future production
approval requires an append-only successor migration/contract and matching
evaluator; the semantic writer cannot self-register one. Disposable tests may
install explicit `TEST_ONLY` identity evaluators that recompute controlled
synthetic outputs. They are not production economics or evidence.

A completed valid assessment preserves five ordered dimensions, the three
primary methods and optional non-controlling comparable cross-check, ordered
method scenarios, fair-value/margin-of-safety/expected-return ranges, thesis,
counter-thesis and invalidation conditions, component reasons, the
`NOT_VALIDATED` evidence label, and the discrete `LONG_TERM_CORE` risk-cap
ceiling. The repository and PostgreSQL backend rebuild typed objects and
recompute assembly, assessment, input, producer, and core arithmetic on
readback. A backend using the empty production producer registry cannot
directly load a test-only-derived record. Exact replay is idempotent;
changed content under an existing identity fails closed. Update and delete are
rejected after sealing.

PostgreSQL enforces relational identity, cardinality, finite numeric domains,
sealing, claim/cap ceilings, append-only behavior, and the dedicated writer
role. The trusted Python persistence repository is the sole semantic writer
and replays the complete Stage 2 formula on write/readback; PostgreSQL does not
duplicate the investment formula. Ordinary analytics application writers are
denied direct V23 DML. Assessment identity is scoped to its assembly, so an
evidence-only assembly revision can preserve an unchanged deterministic result
without collapsing the two publications.

Controlled synthetic valid fixtures prove persistence mechanics only. They do
not establish provider coverage, point-in-time support, historical validity,
or a usable real-company score. Current real mature-company assembly remains
non-usable until approved canonical evidence closes the Stage 3 operand gaps.
Intermediate arithmetic is not rounded. Published money values use two decimal
places, rates use four decimal places, and scores use two decimal places, all
with half-even rounding.

### Company dimensions

Company quality equally weights normalized ROIC, operating margin, FCF margin,
earnings stability, and cash-flow stability. Financial resilience equally
weights inverse net-debt/EBITDA, interest coverage, current ratio, and inverse
diluted-share growth. Earnings/cash-flow quality equally weights CFO/net-income
conversion, FCF margin, cash-flow stability, and inverse dilution. Every
declared factor is required; missing weights are never redistributed.

### FCFF DCF

```text
NOPAT = normalized EBIT * (1 - cash tax rate)
FCFF = NOPAT + D&A - capital expenditure - change in working capital
enterprise value = explicit FCFF present value + terminal-value present value
equity value = enterprise value + cash - debt
per-share value = equity value / diluted shares
```

The discount rate must exceed terminal growth. Every low/base/high scenario
must satisfy ordering, and no scenario may exceed the 80 percent terminal-value
share ceiling.

### Normalized Owner Earnings

Normalized free cash flow is treated as an equity cash flow and capitalized
with the required equity return less growth. Cash and debt are not bridged a
second time. This prevents enterprise/equity double counting.

### Earnings Power and comparable cross-check

Earnings Power capitalizes zero-growth normalized after-tax operating earnings
as enterprise value, then applies the cash/debt equity bridge once. Comparable
valuation applies a dated EV/EBITDA cross-check and the same bridge once. Its
frozen 10 percent weight remains below the 15 percent contract ceiling.

### Aggregation and expected return

All three distinct primary methods must be `VALID`; comparable valuation is
optional and may occur at most once. Duplicate methods fail closed. Weighted
quantiles are the left-continuous inverse weighted empirical distribution over
method lows, centrals, and highs separately. Crossed scenarios are invalid and
are never repaired by sorting.

Expected return is calculated from explicit shareholder cash-flow scenarios:
the initial reference-price outflow, nonnegative annual net distributions, and
the scenario terminal equity value. A deterministic Decimal bisection solves
the annual IRR. Net distribution yield is bounded from zero to 25 percent and
growth from negative 20 to positive 20 percent. Downside risk is calculated
separately and never adjusts the expected-return range.

### Advanced evidence and caps

Missing debt-maturity evidence is nonmaterial only when debt, leverage, and
coverage are valid and leverage is no greater than one with interest coverage
at least eight. Missing evidence then limits the claim ceiling and cap. With
positive debt, stale or invalid maturity evidence blocks valuation. Missing or
invalid debt, leverage, or coverage also blocks.

The final risk cap is the minimum of valuation usability, company quality,
financial resilience, earnings/cash-flow quality, capital-allocation quality,
downside, margin of safety, advanced-evidence completeness, and model-evidence
ceilings. `NOT_VALIDATED`
and `DEVELOPMENT_OBSERVED` cannot exceed 2 percent; `BACKTEST_SUPPORTED` and
`PIT_SUPPORTED` cannot exceed 3 percent; 5 percent requires
`FORWARD_SUPPORTED` plus the strongest economic and evidence conditions.

## Implementation artifacts

- `analysis-python/src/equity_analysis/fundamental_value/contracts_v1.py`
- `analysis-python/src/equity_analysis/fundamental_value/core_v1.py`
- `analysis-python/tests/test_fundamental_value_contract_v1.py`
- `analysis-python/tests/test_fundamental_value_core_v1.py`
- `contracts/fundamental-value-v1/decision-contract.example.json`
- `contracts/fundamental-value-v1/core-assessment.example.json`

The canonical fixture is synthetic and Git-safe. It contains no provider
values, licensed payloads, portfolio weights, or trade instructions.

## Stage 5 service contract

The internal command contract is
`internal-fundamental-value-command-v1.0.0`. It accepts only the durable V22
routing ID, classification-request ID, exact operand request-ID collection,
and projection horizon. FastAPI derives all identity, chronology, evidence,
and version bindings from sealed repositories and never accepts caller metric
values or deterministic outputs.

At each raw JSON boundary, `projectionYears` is an integral JSON number in
the inclusive range 3 through 10, and every durable identifier is an exact
lowercase hyphenated UUID string. Distinct wire spellings are rejected rather
than normalized. A `VALID` assembly has no reason code; every non-`VALID`
assembly has at least one stable sanitized reason.

The Stage 5 accepted internal result contract was
`internal-fundamental-value-result-v1.0.0`; its fixtures remain immutable
historical acceptance evidence. The current readback projection is the
result-only `internal-fundamental-value-result-v1.1.0`. The command remains
v1.0, and the result revision does not change the deterministic core, V22/V23
semantics, or persisted economics. Result v1.1 adds the complete durable
security identity, ticker assignment, display ticker, MIC, identity currency,
and completed session date. Python, Spring, and Next.js each require the
returned assembly ID to equal the requested assembly ID. A usable result's
assessment ID is independently re-derived as UUIDv5 over the frozen assessment
persistence version, assembly ID, and assessment content hash. The completed
session date cannot be later than the UTC date of the decision cutoff.

The result preserves explicit state, applicability, reasons, immutable hashes,
cutoffs, model evidence and claim ceilings, deterministic assessment structure
when one exists, and the LONG_TERM_CORE risk-cap ceiling. It explicitly denies
final portfolio-weight and automatic brokerage authority. Spring Boot validates
and projects this contract but does not reproduce its calculations. The Spring
boundary checks the frozen applicability matrix, recursive deterministic-result
shape and states, cross-field bindings, and the Python canonical assessment
content hash before returning a defensive public copy.

All deterministic Decimal values use the same finite ordinary base-10 text
used by Python content hashing: exponent notation, non-finite values, floating
conversion, and signed-zero drift are forbidden. Spring validates the fixed
method cardinality and ordering, ordered ranges, exact risk-cap domain, and
the FCFF terminal-value-share ceiling of 0.80 before exposing a result. The
eight thesis, counter-thesis, and invalidation conditions also bind their
exact frozen thresholds and inclusive or strict comparison directions. The
quality, resilience, conservative margin-of-safety, downside-risk, and
central margin-of-safety condition observations additionally bind to their
corresponding exposed score or range value; `satisfied` is recomputed from that
bound value. Missing durable references map to 404, durable V22/V23 integrity
conflicts to 409,
malformed internal requests to 422, and malformed public Spring requests to
400. Invalid upstream success bodies fail closed as sanitized 502 responses.

## Stage 6 workspace contract

Next.js reads immutable decisions only through the Spring public endpoint. Its
TypeScript decoder accepts only result v1.1 and preserves the full durable
identity and completed-session envelope, explicit applicability and evidence
states, stable root and nested reasons, sealed cutoffs, hashes, versions, claim
ceiling, `NOT_VALIDATED`, and absent deterministic outputs. It rejects unknown
fields, coercion, hash drift, noncanonical decimals including alternate zero
spellings, invalid cutoff grammar or chronology, frozen condition drift, and
claim, cap, authority, or version drift. It re-derives assessment identity,
orders completed session against the decision cutoff, and binds exposed
condition observations to their source fields. The transport binds each
decoded result to the requested assembly ID. It neither calls Python,
PostgreSQL, or providers nor reimplements the deterministic model.

The workspace displays ordered fair value, reference price, margin of safety,
expected return, downside risk, quality dimensions, valuation methods,
conditions, and the `LONG_TERM_CORE` risk-cap ceiling only when the public
contract includes a usable assessment. Annualized expected return is visibly
bound to the assessment's projection horizon. The evidence seal shows the
durable security and listing IDs, ticker, MIC, identity currency, and completed
session, while nested failure reasons remain visible. Percent formatting uses
arbitrary-precision decimal text and cannot overflow through JavaScript Number
conversion. Missing and specialized outcomes remain non-numeric. The risk cap
is never described as a final portfolio weight, and AI narrative remains absent
from this stage.
