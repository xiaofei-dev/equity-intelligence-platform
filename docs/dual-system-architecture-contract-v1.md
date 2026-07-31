# Dual-System Architecture Contract v1

Date: 2026-07-30

## Status and Scope

`dual-system-architecture-v1.0.0` is the normative architecture and semantic
contract for two independent investment-research systems and one unified
portfolio/risk view. It is a contract freeze, not a scoring, data migration,
provider, deployment, or trading implementation.

This contract does not replace the repository's legacy Phase 0 foundation
milestone. It introduces the separately named **Dual-System Architecture
Contract v1**.

The product remains United States listed equities at daily cadence. It does
not support shorting, leverage, options, automatic brokerage execution, or
LLM-controlled weights or trades.

## System Responsibilities

### Fundamental Value Investment System

The Fundamental Value Investment System owns long-term company research,
specialized-model applicability, fair-value methods, fair-value ranges,
margin-of-safety calculations, thesis and counter-thesis evidence, invalidation
conditions, and eligibility or risk caps for `LONG_TERM_CORE`.

It returns an allocation or risk cap, never an automatic final portfolio
weight. The fair-value range and margin of safety are the decision emphasis;
a central fair-value estimate is retained as supporting evidence.

### Quantitative Trading System

The Quantitative Trading System owns daily, completed-session, long-only
setups, entry conditions or ranges, stops, targets, expiry, invalidation,
liquidity/cost assumptions, and position-risk caps for `QUANT_TRADING`.

It does not create brokerage orders, connect to a broker, enable leverage,
shorting, or options, or convert a research result into execution authority.

### Unified Portfolio and Risk View

The Unified Portfolio and Risk View consumes immutable outputs from both
systems by reference. It owns per-sleeve and aggregate exposure, concentration,
liquidity, performance, drawdown, turnover, cost, benchmark, and risk
attribution.

It does not average Fundamental Value and Quantitative Trading scores and does
not create a new blended security score.

## Sleeve Contract

The only v1 sleeves are:

- `LONG_TERM_CORE`
- `QUANT_TRADING`

The same security may appear in both sleeves, but holdings, cash, cost basis,
thesis, exits, constraints, benchmarks, risk, performance, and attribution
remain isolated. Cash transfers require an explicit immutable human decision
and are never automatic.

The long-term benchmark set is SPY plus a dated sector benchmark. The
quantitative benchmark set is SPY, a dated sector benchmark, and a cash
benchmark.

## Shared Identity Contract

A security is referenced by durable internal identifiers for:

- legal company or issuer;
- instrument;
- share class;
- listing;
- ticker assignment; and
- security compatibility identity.

Ticker, exchange label, and provider symbol are temporal attributes, not
durable identities. Task 1 will implement these cardinalities. Until then,
`analytics.security.public_id` remains the external compatibility anchor and
no ambiguous identity may be invented.

The canonical Phase 0 context requires nonblank company, instrument,
share-class, listing, ticker-assignment, and security identifiers, plus the
current ticker, MIC, and currency presentation attributes. Task 1 resolves
their registry identities and relational cardinality.

## Completed-Session Contract

A tactical input must reference a versioned exchange calendar and one session
whose state is `COMPLETED`. The session contract includes MIC, session date,
timezone, scheduled open and close, early-close status, completion state, and
completion timestamp.

Weekends, scheduled holidays, exceptional closures, halts, and sessions that
have not completed are not completed-session inputs. A prior completed session
may be valid; a future or incomplete session is not.

## Evidence Lineage and Time

Evidence retains:

- provider and source identifiers for audit;
- provider schema, adapter, parser, and normalization versions;
- source record and revision;
- source content and normalized record hashes;
- `effectiveAt`, `availableAt`, `retrievedAt`, and `ingestedAt`;
- dataset/freshness policy versions; and
- explicit conflict status.

The canonical lineage envelope requires nonblank provider, provider-schema,
adapter, normalization, source-record, source-content-hash,
normalized-record-hash, and freshness-policy references; a positive source
revision; valid effective, availability, and ingestion timestamps; and a
structured conflict status and criticality. `retrievedAt` and `staleAfter` are
optional, but must be valid timestamps when present.

`effectiveAt` is economic applicability. `availableAt` is when the source made
the evidence usable. `retrievedAt` is the transport observation time when
relevant. `ingestedAt` is when the platform accepted the evidence.

Current decisions require availability by the decision cutoff and ingestion
by the sealed ingestion cutoff. Evidence selected after those cutoffs cannot
be moved backward in time.

Every canonical decision context therefore carries both an explicit
`decisionCutoff` and `sealedIngestionCutoff`. Contract decoders enforce the
chronology structurally; Task 1 remains responsible for implementing selectors.

The canonical chronology is:

`scheduledOpen < scheduledClose <= completedAt <= decisionCutoff <= sealedIngestionCutoff`

and:

`effectiveAt <= availableAt <= ingestedAt`.

When `retrievedAt` exists, it also satisfies
`availableAt <= retrievedAt <= ingestedAt`.

Every required or optional timestamp, when present, uses an RFC 3339 date-time
instant with either `Z` or an explicit numeric UTC offset. Date-only, local,
locale-formatted, numeric, Boolean, blank, and malformed values fail closed.
`sessionDate` is a real ISO calendar date, not merely a digit pattern.

## Data Usability Policy

Provider provenance is retained for audit, licensing, revision, and conflict
resolution. Provider identity never changes a deterministic score.

Every evidence selection uses one strictness class:

### `STRICT_IDENTITY_AND_CHRONOLOGY`

Required for security/listing identity, currency and unit, completed sessions,
splits and corporate actions, adjustment identity, and decision cutoffs.
These fields do not permit numeric-tolerance repair.

### `DOMAIN_TOLERANT_NUMERIC`

Permits aligned financial observations or ratios to differ within a
field-specific, versioned tolerance. Tolerance evaluation occurs only after
identity, fiscal period, unit, currency, adjustment mode, and chronology are
aligned.

There is no global tolerance. A tolerance is field/domain specific, versioned,
and symmetric where appropriate. Small numeric noise may be acceptable.
Look-ahead, survivorship, identity, unit, period, corporate-action, and
completed-session errors are not.

`fieldTolerancePolicy` is required only for `DOMAIN_TOLERANT_NUMERIC`.
`STRICT_IDENTITY_AND_CHRONOLOGY` and
`APPROXIMATE_HISTORICAL_RESEARCH` do not require an unused tolerance object.

### `APPROXIMATE_HISTORICAL_RESEARCH`

Permits reasonable historical numeric/provider differences for development
research and backtests. It cannot be relabeled `STRICT_PIT` or
`SEALED_PROSPECTIVE` and cannot raise a validation claim ceiling.

The paired internal representation
`APPROXIMATE_HISTORICAL_RESEARCH` plus `APPROXIMATE_HISTORICAL` corresponds to
the user-facing **APPROXIMATE_HISTORICAL_BACKTEST** concept. This evidence
usability vocabulary does not replace or upgrade model-level governance labels
such as `DEVELOPMENT_OBSERVED`, `BACKTEST_SUPPORTED`, `PIT_SUPPORTED`, or
`FORWARD_SUPPORTED`.

Evidence claims remain distinct:

- `CURRENT_ONLY`
- `APPROXIMATE_HISTORICAL`
- `STRICT_PIT`
- `SEALED_PROSPECTIVE`

Provider fallback priority is deterministic and versioned. A provider value
must never be selected because it improves a score, ranking, or backtest.

Conflicts are explicit. A noncritical conflict invalidates or excludes only
dependent factors. A critical conflict fails the affected contract. Missing
or conflicting values never become zero or neutral.

A provider replacement that preserves canonical semantics may change adapter,
normalization, and evidence versions without changing model formulas. A
semantic model-input change requires an explicit successor model contract.

## Shared Data States

The domain data states are:

- `VALID`
- `MISSING`
- `STALE`
- `INVALID`
- `NOT_APPLICABLE`
- `EXCLUDED`

A non-`VALID` value must carry a reason and cannot be converted to zero or a
neutral score. Operational run status is a separate contract.

Specialized model applicability is:

- `APPLICABLE`
- `SPECIALIZED_MODEL_REQUIRED`
- `NOT_APPLICABLE`
- `INSUFFICIENT_EVIDENCE`

Banks, insurers, REITs, and other specialized companies are evaluated only by
an applicable specialized model. Unsupported cases are not forced through a
generic model.

## Version Contract

Every immutable decision context identifies applicable contract, model,
strategy, decision, evidence schema, normalization, calendar, taxonomy,
benchmark, freshness, risk, and cost-policy versions. Quantitative outputs also
identify versioned liquidity and transaction-cost/slippage assumptions. The
contract validates their presence and state, not their economic formulas.

Canonical monetary, price, ratio, risk, liquidity, transaction-cost, and
slippage values are ordinary finite base-10 decimal strings. Exponent and hex
notation, `NaN`, infinities, JSON numbers, JSON Booleans, blank strings, and
malformed values fail closed. The v1 liquidity assumption declares
`averageDailyDollarVolume` and `maximumParticipationRate`; the v1 cost
assumption declares `transactionCostBps` and `slippageBps`.
Fair-value range ordering uses exact signed base-10 comparison without
floating-point conversion or an arbitrary digit limit.

The top-level `contractVersion` and all contract enumerations fail closed.
Component identifiers in `versionSet` are required, nonblank, opaque version
references. Phase 0 does not claim to know every future supported component
version; Task 1 resolves registry support for those references. An existing
semantic version is never reinterpreted in place.

Both engine outputs require immutable output, decision-contract, model,
strategy, and evidence-hash references. The Fundamental Value output also
requires its reference price; the Quantitative Trading output requires its
setup. The portfolio/risk contract requires its own version and binds each
sleeve entry to the matching engine output ID. Cross-binding fails closed.

The governed model-evidence labels recognized by this contract are
`NOT_VALIDATED`, `DEVELOPMENT_OBSERVED`, `BACKTEST_SUPPORTED`,
`PIT_SUPPORTED`, and `FORWARD_SUPPORTED`. Evidence usability cannot select or
upgrade one of these labels.

## AI and Human-Control Boundaries

AI is a cited, versioned narrative layer. It cannot:

- alter deterministic inputs, fields, scores, ranks, or eligibility;
- fill missing evidence;
- average system scores;
- set a final weight;
- authorize a cash transfer; or
- create or execute a trade.

Final allocation, cross-sleeve cash transfer, and every real-world investment
action require a human decision. Decisions are immutable; corrections create
an explicit superseding decision.

## Raw, Normalized, and Derived Boundaries

Raw licensed data remains in Git-ignored local storage or future encrypted,
restricted storage. Git-safe artifacts retain only permitted lineage, hashes,
references, and normalized examples.

Providers map into canonical internal concepts through versioned adapters.
Models cannot depend on provider names, provider symbols, or native field
names. Current routing may use Yahoo for private/development daily data and
EODHD for bounded fundamentals/actions, subject to licensing and capability
gates.

Task 1 will implement internal selectors first. Existing public market-data
APIs remain compatibility surfaces until a separately approved replacement.

## Compatibility Map

| Current surface | Dual-System v1 interpretation | Compatibility action |
| --- | --- | --- |
| `LONG_HORIZON_RESEARCH` | Deterministic research input to the future Fundamental Value system | Preserve formula and version; do not claim it already provides fair value or a core allocation decision |
| `DAILY_TACTICAL_SIGNAL` | Deterministic research input to the future Quantitative Trading system | Preserve formula and version; do not claim it already provides the complete v1 trade-plan output |
| Market Intelligence horizon views | Presentation/composition of independent deterministic results | Preserve; label engine and sleeve explicitly in successor contracts |
| `BUYING_OPPORTUNITY` | Legacy long-term valuation evidence | Retain for compatibility; successor name is `VALUATION_OPPORTUNITY`; never present it as a blended recommendation |
| Objective Rating screening | Existing deterministic screening evidence | Preserve unchanged; provider acceptance remains separate from eligibility |
| `/api/v1/market-data/latest` and `analytics.daily_price` | Legacy compatibility read surface | Preserve until separately approved replacement; do not use as the new PIT engine selector |
| V12 portfolio context/scenarios | Spring-owned user and portfolio foundation | Preserve; future successor adds sleeve and immutable engine-output references |
| Forward validation | Validation-specific evidence framework | Preserve claim ceilings; do not treat it as the production decision ledger |
| AI narrative | Optional cited explanation | Preserve narrative-only isolation |

The canonical compatibility tuple fixes the legacy meaning as
`LONG_TERM_VALUATION_EVIDENCE`, the successor metric as
`VALUATION_OPPORTUNITY`, and the legacy public market-data API status as
`COMPATIBILITY_SURFACE`.

## Canonical Contract Artifact

The shared fixture is
`contracts/dual-system-architecture-v1/decision-context.example.json`.
Python, Java, and TypeScript decoders enforce the same fail-closed safety
boundaries. It is a semantic compatibility artifact, not a live API payload or
a persisted database record.

Java wire callers must enter through
`DualSystemArchitectureContract.decode(JsonMapper, String)`. That JsonNode-first
decoder validates exact JSON string, Boolean, object, array, integer, decimal,
date, and timestamp types before Jackson record binding; record constructors
alone are not a safe wire decoder because Jackson may coerce scalar values.

## Change Rule

Task 1 may implement identity, calendar, evidence, benchmark, liquidity, and
selector foundations without changing this contract's system boundaries.
Any change to sleeve semantics, deterministic model inputs, automatic-control
rules, evidence claim classes, or no-averaging/no-execution rules requires an
explicit successor and user approval.
