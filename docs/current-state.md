# Current Project State

Last updated: 2026-08-13

## Portfolio Decision Support and Evaluation v1

Task 5 is engineering-complete through migration V35. A fresh disposable
PostgreSQL 17 database was migrated from V1 to V35, populated with the offline
controlled GOOG evidence fixture, and exercised through FastAPI, Spring Boot,
and the Next.js `/portfolio` workspace. The public workflow created a V28
context, sealed all four V29 scenario types, bound one recommendation, recorded
an immutable human `ACCEPTED` conclusion, and verified exact replay plus changed
same-key conflict refusal.

V34 fixes PostgreSQL/Python ratio replay at scale 20 with `ROUND_HALF_EVEN`.
V35 binds current portfolio valuation to V22 `CLOSE_PRICE` with
`UNADJUSTED` semantics while leaving V31 longitudinal total-return evaluation
unchanged. No provider request, future maturity, brokerage action, final weight,
or model-label upgrade was created. Existing controlled longitudinal evidence
remains workflow-mechanics evidence rather than a claim of investment returns.

## Unified Portfolio and Risk Context v1

Task 4 is implemented through the V28 repository head. FastAPI calculates a
deterministic provider-neutral risk context; Spring verifies authenticated
portfolio ownership, sealed V12 account snapshots, the exact V12
constraint-policy version and values, cross-language result identity, and
human-control invariants before sealing V28. Next.js provides `/portfolio` and
calls Spring only.

The snapshot preserves missing valuations, cash, liabilities, leverage,
position and sector concentration, and separate `LONG_TERM_CORE` and
`QUANT_TRADING` evidence. Human reviews are immutable and idempotent. No final
weight, order, automatic brokerage execution, or LLM decision authority exists.
Quant v2 remains excluded from research-use authority. V21 is unchanged and
remains a legacy/unwired lane.

The final local acceptance recorded 10 Python tests, 156 Spring tests, 72
frontend tests, ESLint and production build success, and a complete PostgreSQL
17 migration/upgrade/refusal matrix through V28. No business portfolio context
or deployment was created.

## Quantitative Trading v2 controlled result

Quant v2 now has a separately versioned `REGIME_FILTERED_MEAN_REVERSION`
signal core, cross-sectional ranking, entry/exit plan, event-driven portfolio
simulator, nonlinear and fixed-cost scenarios, and an immutable one-execution
historical runner. Twenty-seven focused contract, simulator, protocol, and
result tests pass.

The one authorized development replay completed over the existing 191-security
current-survivor cache. USD 100,000 became USD 107,516.24 at 0.63% CAGR with a
-5.62% maximum drawdown; SPY became USD 434,189.17 at 13.53% CAGR with a -33.70%
maximum drawdown. Quant v2 passed 4 of 8 frozen gates and is sealed
`NOT_DIRECTIONALLY_SUPPORTIVE_NO_RETUNING_ON_SAME_OUTCOME`. It remains
`NOT_VALIDATED` and is not wired into V27, FastAPI, Spring, or Next.js decision
paths. This is an intentional economic stop, not unfinished parameter tuning.

## Quantitative Trading v1 Disposition and v1.1 Successor

The independent `QUANT_TRADING` sleeve has completed its first deterministic
engine, portfolio simulator, and development-only historical replay. The frozen
v1 `MOMENTUM_CONTINUATION` result is rejected for production economic
performance: USD 100,000 became USD 113,808.46 at 1.13% CAGR, while SPY became
USD 438,691.69 at 13.68% CAGR. Drawdown was lower, but the opportunity cost was
not acceptable. The immutable disposition remains `NOT_VALIDATED`.

Quant v1.1 is a new `DUAL_MOMENTUM_TREND` identity, not a rewrite of v1. It
uses standard 12-1 and 6-1 cross-sectional momentum, positive security and SPY
trend filters, five-session rebalancing, next-open entry, no profit target,
three-ATR trailing risk, and at most ten positions. The successor was designed
after v1 outcomes were observed, so any replay on the same cache is development
evidence only and cannot be called an untouched holdout. Research-decision
persistence and read-only product APIs now exist, but production allocation and
brokerage paths remain unauthorized.

The v1.1 controlled development replay is complete. It grew USD 100,000 to
USD 237,071.67 at 7.76% CAGR, versus USD 437,644.04 and 13.63% CAGR for SPY.
Five of nine frozen gates passed; benchmark-relative CAGR, total return,
Sharpe, and positive subperiod gates failed. The governing disposition is
`NOT_DIRECTIONALLY_SUPPORTIVE_NO_RETUNING_ON_SAME_OUTCOME`, and the model
remains `NOT_VALIDATED`.

The current product slice implements the provider-neutral V22
research-signal assembly boundary. It replays exact V22 selection request and
result hashes, requires 253 ordered `TOTAL_RETURN_ADJUSTED` daily observations,
hydrates durable identity/ticker intervals and completed-session authority, and
applies fail-closed active USD common-stock and SPY/ARCX applicability. Missing
or not-applicable members remain explicit inside the exact denominator;
invalid, stale, excluded, future, ambiguous, or hash-drifting selector evidence
raises an integrity failure. The Git-safe manifest contains no price values.

V27 now persists the resulting public-safe research projection as an
append-only immutable decision. FastAPI owns the internal ID-only create/read
workflow, Spring Boot validates and exposes the public GET-only decision, and
Next.js provides `/research/quant-trading`. The projection includes candidate,
hold-review, exit-review, no-signal, not-applicable, and insufficient-evidence
states together with deterministic entry-price/stop context where applicable.
It cannot contain a final portfolio weight, order quantity, brokerage
instruction, LLM authority, or guaranteed-return claim. V22 still lacks
governed Quant event/lifecycle interval evidence, so this slice does not
authorize current portfolio simulation, order workflows, or execution.

This document is the authoritative current-state summary for the repository.
Historical methodology reports and generated acceptance artifacts remain
immutable evidence of the state that existed when they were produced.

## Fundamental Value Current-Assessment Completion

The Fundamental Value persistence chain reaches V26; the repository migration
source head is V28 after the Quant research projection and unified portfolio
context. V25 remains the durable
security-identity authority; V22 owns provider-neutral current classification,
completed-session, price evidence, selection, and applicability; V26 owns the
append-only current Fundamental Value assessment graph and its separate,
explicit assessment-write authority. Passing identity or V22 evidence gates
does not implicitly authorize an investment assessment.

The accepted private receipt set contains EODHD fundamentals and daily prices
for GOOG, FOX, and MSFT. The offline operator reopens the exact plan, manifest,
journal, and response bytes, replays the frozen decoders, and ignores previously
generated assessment JSON. The local business database was migrated from V25
to V26 through Flyway, explicit provider/session and assessment authorities
were installed, and the rebuilt assessments were sealed in V22/V26. Exact
replay returned the same three assessment IDs without adding business rows.

The current local results are GOOG and MSFT
`WATCHLIST_QUALITY_PRICE_NOT_ATTRACTIVE`, and FOX
`NEUTRAL_RESEARCH_REQUIRED`. These are deterministic research classifications,
not promises about future returns. They remain
`DEVELOPMENT_OBSERVED_CURRENT_REVISION_APPROXIMATION` with model evidence label
`NOT_VALIDATED`; the label records the historical and point-in-time evidence
limits rather than requiring perfect prediction accuracy.

The read path is GET-only: Next.js calls Spring Boot, Spring Boot calls the
Python internal API, and Python reads immutable V26 state. The public projection
excludes licensed payloads, input operands, raw manifests, and checkpoint paths.
It preserves `NOT_VALIDATED` and denies deterministic ranking, final portfolio
weights, automatic brokerage execution, and evidence-label upgrades.

## Verified Baseline

- Repository baseline before the current uncommitted eligibility-recovery and
  Dual-System/Task 1 integration work:
  local `main@57fa7ed4422b96e25cecb73e496f07692d026ec4`;
  `origin/main@57fa7ed4422b96e25cecb73e496f07692d026ec4`
- Market Intelligence product persistence remains owned by its V14-V17
  structures; V17 is the last shared operational application baseline
- Last accepted pre-current-work migration checkpoint: `V24`; the current
  uncommitted candidate source and isolated-test head is `V28`. V18-V20 are the
  Forward DQV outcome, chronology, and benchmark-successor migrations, V21 is
  legacy/unwired portfolio-decision persistence, V22 is the Unified Market
  Data and Evidence Foundation successor, and V23 is the append-only
  Fundamental Value persistence successor; V24 is the isolated narrow
  company-quality Forward enrollment readiness successor, V25 is the durable
  identity-authority successor, V26 is the current-assessment persistence
  successor, V27 is the append-only Quant research-decision persistence, and
  V28 is the append-only unified portfolio/risk context and human-review
  successor
- Primary market: United States listed equities
- Data cadence: completed daily or end-of-day sessions
- Runtime architecture: Next.js, Spring Boot, FastAPI, and PostgreSQL
- CI run:
  [30369516000](https://github.com/xiaofei-dev/equity-intelligence-platform/actions/runs/30369516000)
- CI result: Backend, Frontend, Analytics, Database migrations, and Secret scan
  passed

The current task revalidated a clean-clone-equivalent analytics run, the
isolated PostgreSQL V17 Market Intelligence integration path, and PostgreSQL
17 clean `V1 -> V17`, populated `V3 -> V17`, `V12 -> V17`, and `V16 -> V17`
paths. Separate Forward DQV acceptance verifies the V18 outcome ledger and
V19 chronology repair on their clean and supported upgrade paths. Final counts
are recorded in the development log.

Task 1 is accepted through Stage 3C. The complete PostgreSQL 17
V1-to-V22 migration, upgrade, refusal, base, and advanced matrix passed on the
accepted V22 schema. On the final Python adapter snapshot, the Stage 3C module
reported `33 passed`, Ruff passed, and all three typed Python/PostgreSQL
integration tests passed in 5.05 seconds on a fresh disposable PostgreSQL 17
database migrated from V1 to V22. The temporary database was removed.
Independent relational and Python/provider/refresh/persistence/API audits
reported PASS with no residual blocker. This is bounded test evidence, not a
business-database deployment or provider execution.

## Capability Status

| Capability | Engineering state | Operational state |
| --- | --- | --- |
| Local four-service stack | Implemented and tested | Available through Docker Compose |
| Provider-neutral daily price ingestion | Implemented | Bounded manual use only |
| Daily refresh planning and persistence | Implemented through V16 with a 66-universe CLI | Manual confirmed execution; no deployed scheduler |
| Market Intelligence profiles | Implemented through Python and V17 | Published through Spring Boot closed-test API |
| Sector, industry, and security screening | Implemented through Python and V17 | Spring Boot and Next.js `/research` implemented |
| Objective Rating v1 | Versioned and reproducible | Limited by explicit data eligibility |
| Eligibility Recovery v1 | DB-backed factor/operand preflight implemented | Read-only Spring and Next.js status; current cohort blocked with no provider plan |
| Tactical Signal v2.2 | Deterministic model, accepted freeze, and Practical Tier-1 retrospective implemented | 5 sessions unsupported; 20 sessions mixed; 60 sessions modestly directionally supported; prospective validation still required |
| Long Horizon Research v1.1 | Separate quality and valuation dimensions executed in a 100-security Practical Tier-1 retrospective; no default rank | Business Quality has modest SPY-relative cohort evidence; its ordering and Security Attractiveness remain unvalidated |
| AI research contract | Defined and simulated | No production AI evidence pipeline is active |
| User and portfolio context | Schema and backend foundation implemented | Closed-test identity only |
| Forward Decision-Quality framework | V18 ledger, accepted V19/v2.1.1 chronology, Gate H evaluator, maturity-statistics adapter, and statistics engine implemented offline | Post-close evidence blocked by time; no real v2.1.1 enrollment, natural maturity, statistics run, or validated model |
| Deployment | Designed | Not deployed |
| Dual-System Architecture Contract v1 | Frozen in shared documentation and cross-language contract fixtures | Accepted Phase 0 baseline |
| Unified Market Data and Evidence Foundation v1 | Task 1 Stages 1-3C accepted, including V22 persistence, internal selection/readback/applicability projections, and offline provider-adapter refresh integration | No provider execution, public API replacement, raw-payload deletion, or business-database deployment |
| Fundamental Value Investment System v1 | Stages 1-6 master accepted offline, including the strict result v1.1 Spring-only Next.js workspace | Production producer registry is empty; mature-company V22 operand gaps prevent core invocation, no real assessment exists, and engineering UI readiness is not investment validation |
| Curated Forward/portfolio migration lineage | Exact V18-V21 migration SQL adopted; V21 acceptance tests were strengthened without changing migration bytes; V21 remains legacy/unwired | PostgreSQL 17 matrix accepted; no application wiring |

Provider acceptance, formula readiness, scoring eligibility, ranking, AI
review, portfolio fit, and a human decision are separate states. A successful
provider fetch must never be interpreted as a recommendation.

## Current Data Strategy

- EODHD is the current bounded licensed source for fundamentals and other
  provider capabilities that have passed a specific acceptance gate.
- SEC EDGAR remains the authoritative filing and filing-availability source
  where the methodology requires it.
- yfinance may provide no-key daily price refreshes and bounded development
  cross-checks. Its unofficial interface and licensing terms must be reviewed
  before any public or commercial deployment.
- Twelve Data remains supported behind the provider-neutral interface but is
  not the default broad-market source.

Daily prices may be refreshed every completed session. Fundamentals, identity,
and classifications use independent freshness policies and must not be fetched
merely because a price is stale.

## Current Product Gate Result

**Market Intelligence End-to-End Vertical Slice v1** is locally implemented:

1. a versioned 66-security universe and bounded Daily Refresh CLI exist;
2. normalized observations and freshness states are written to PostgreSQL;
3. durable profiles and sealed screening runs are built from `READY` snapshots;
4. Spring Boot exposes the versioned public contract;
5. Next.js renders search, filters, results, and profile detail;
6. sealing a screen emits an idempotent Forward decision-snapshot handoff; and
7. the V17-to-V11 bridge records a typed, idempotent prospective attempt
   without creating signal or outcome rows when the screen has no eligible
   results.

The bounded provider refresh is complete for the v1 scope: Yahoo prices for 57
securities, EODHD corporate actions for 57, and EODHD fundamentals for 55.
ACN's malformed 2026-07-28 Yahoo bar was rejected while 259 prior valid
sessions were retained, so its price status is explicitly `STALE/LATE_DATA`.
A new `READY` snapshot produced 66 durable profiles, zero eligible results,
55 `INSUFFICIENT_DATA` Objective outcomes, 11
`SPECIALIZED_MODEL_REQUIRED` outcomes, and all 66 explicit exclusions. The
prospective bridge records `NO_ELIGIBLE_SIGNALS`; its 5-, 20-, and 60-session
maturity checkpoints are therefore `NOT_APPLICABLE`, while the 12-month-plus
model remains context only. The real product result remains `PARTIAL` without
changing the fact that the approved bounded provider workflow is complete. See
[vertical-slice closeout](market-intelligence-vertical-slice-v1-closeout-2026-07-28.md)
and the
[prospective-enrollment closeout](forward-prospective-enrollment-v1-closeout-2026-07-28.md).

Raw provider facts are no longer treated as final factor values. The
provider-neutral persisted-fact adapter requires proven period semantics,
units, availability, revisions, freshness, continuity, quality, and lineage.
The current daily-refresh fundamentals remain unscoreable when they are marked
`Q_UNPROVEN` or `NOT_VERIFIED`; missing cohort valuation or historical PIT
evidence also remains explicit. No Objective formula, threshold, or PIT rule
was relaxed.

The current DB-backed eligibility-recovery preflight reports 66 profiles and
66 sealed results, with 0 eligible against the frozen minimum of 20. The
approved Yahoo and EODHD routes cannot increase that maximum because repeating
the same fundamentals endpoint does not prove the missing duration, TTM, or
historical PIT semantics. The status is `BLOCKED_COHORT_UNREACHABLE`, the
provider request plan is empty, and no quota was consumed.

An accepted offline Objective current-decision gate now exists independently
of that earlier profile run. It scores 136 securities in its accepted
normalization universe; 32 are `INCLUDED` members of the closed 66-security
product universe. Recovery replayed 44 hash-verified cached EODHD Fundamentals
responses into PostgreSQL with zero network requests and produced current
profile, market-capitalization, and classification projections. Repeating the
cache replay wrote zero additional business rows.

The corrected PostgreSQL replay contract is
`objective-current-gate-replay-v1.1.0`. It clones all 66 immutable universe
members but writes Objective coverage only for the 55 `INCLUDED` securities.
The 11 reference-only or excluded securities remain explicit snapshot members
and become `NOT_APPLICABLE` Market Intelligence views; the replay does not
invent a size cohort for them and does not require V18.

The corrected v1.1 replay has not yet been executed against the working
database. Eleven `INCLUDED` securities still lack a persisted current market
capitalization: AAPL, ABT, ACN, CAT, COST, EXPO, JNJ, MDT, NEE, PEP, and TMO.
Their earlier fundamentals evidence is present but predates the current
profile-projection writer. The bounded repair is exactly 11 EODHD Fundamentals
requests with provider retries disabled and configured weight 110. It remains
stopped until `EODHD_API_KEY` is available in the local ignored `.env`.

Historical snapshot `aa266ccf-0cc5-5994-8e23-e93556707ccd` and screening run
`c3193573-3bbe-5640-97e4-670b1ffc5695` remain append-only evidence of the
superseded v1.0 replay. They are not the authoritative recovery output and
must not be used to claim current product eligibility. See
[Objective current replay recovery](objective-current-replay-recovery-2026-07-29.md).

## Deliberately Inactive

- Public registration and production authentication
- Automatic brokerage execution
- LLM-determined scores, weights, or trade decisions
- Full historical point-in-time UQ claims
- Multi-market coverage
- Production scheduler and cloud deployment
- Commercial redistribution of licensed market data
- Public selector API replacement and production migration release

## Dual-System Contract Boundary

`dual-system-architecture-v1.0.0` defines the future Fundamental Value and
Quantitative Trading systems as independent engines. It also defines isolated
`LONG_TERM_CORE` and `QUANT_TRADING` sleeves and a Unified Portfolio/Risk View
that reports separate and aggregate attribution without averaging engine
scores.

The contract preserves current formulas and compatibility surfaces. Legacy
`BUYING_OPPORTUNITY` means long-term valuation evidence; its successor name is
`VALUATION_OPPORTUNITY`. The freeze does not claim that fair-value decisions,
complete quant trade plans, sleeve persistence, or a new database migration
are implemented.

Task 1 Stage 1 now provides a migration-free Python evidence-selection kernel
for exact durable identity tuples, completed-session chronology, provider
lineage, raw/normalized/derived boundaries, explicit data states, deterministic
versioned fallback, freshness, conflicts, and specialized-model applicability.
It does not claim that the durable identities or calendars are persisted.
Stage 2 adds strict canonical data contracts for daily prices and adjustments,
corporate actions, fundamentals and periods, classifications, market/sector
benchmarks, and engine-derived liquidity. It reuses V1-V17 concepts and adds no
table.

Task 1 Stage 3A adopts the exact historical V18-V21 Forward DQV and portfolio
migration lineage from reachable commit `87e2a88` because V21 application is
`NOT_PROVABLE`. Those versions and checksums are immutable. V21's `CORE` and
`TACTICAL` lanes are legacy and remain unwired from the accepted dual-system
contract. The curated historical lineage ends at V21, while V17 remains the
last shared operational application baseline.

Task 1 Stage 3B adds V22 as a separate append-only successor. It persists the
accepted durable identity chain, completed-session calendars, private
raw-manifest lineage, canonical normalized/derived evidence, versioned
selector contracts and immutable outcomes, and specialized-model
applicability routing. Completed sessions bind to their IANA-timezone local
date; derived liquidity seals exact distinct completed-session parents;
selectors classify every supplied candidate with deterministic rejection
reasons; and applicability routes use verified content hashes and latest-only
successor chains. V22 does not change model formulas, evidence claim
ceilings, missing-data behavior, AI/human control, provider fallback, or V21
portfolio semantics.

Task 1 Stage 3C adds internal-only FastAPI contracts for executing a selector
from persisted evidence IDs, reading a sealed selector aggregate, and looking
up the unsuperseded applicability route for a governed routing version. The
Python service hydrates and revalidates V22 records before selection; it does
not accept provider-native model inputs or replace any Spring Boot public API.
The provider-neutral offline refresh coordinator reuses the existing
execution lease, immutable journal, checkpoint, and resume controls. Fixture
adapters prove exact replay, partial-failure recovery, and `UNKNOWN`
fail-closed behavior without making a provider request or fetching during
FastAPI startup. Canonical request and plan identities bind the full security,
listing, calendar, and completed-session context. Strict nonempty batches
support bounded overlap/backfill ranges, and exact immutable evidence can be
reused by later runs without treating a uniqueness replay as `UNKNOWN`.

Selector result hashes bind their request, policy, output, and full
deterministic rejection map. Distinct requests may therefore persist the same
selector outcome without a global hash collision, while changed same-request
content fails closed. The controller's final fresh V1-to-V22 PostgreSQL 17
run passed all three typed integration tests on the deep-immutability snapshot.

V22 can retain a Git-safe raw manifest and private storage reference, but it
cannot durably govern raw-payload retention or deletion. It lacks a versioned
retention policy, retention deadline/legal-hold state, and append-only
disposition-event cardinality. No raw payload deletion is implemented.
V23 is now reserved for the separately approved, narrowly scoped Fundamental
Value persistence successor. It must not contain physical raw-object
retention/deletion governance. If the product later assumes that responsibility,
its policy, deadline/jurisdiction, legal-hold, append-only disposition-event,
proof, and chain-cardinality controls require the next migration version
available after V23. No deletion operation is implemented.

## Fundamental Value Investment System v1

Task 2 Stage 1 freezes `FUNDAMENTAL-VALUE-v1.0.0` for mature nonfinancial
United States listed operating companies. Banks including NBN, insurers,
REITs, resources, high-uncertainty biotechnology companies, other financials,
incompatible conglomerates, benchmarks, and insufficient-history companies
cannot fall back to the generic model.

The frozen valuation family is FCFF DCF, normalized Owner Earnings, and
Earnings Power, with comparable valuation limited to a cross-check. Eligible
methods aggregate by preregistered weighted median and ordered weighted
quantiles. The only risk-cap ceilings are 0, 1, 2, 3, and 5 percent; they are
not final portfolio weights. The initial evidence label is `NOT_VALIDATED`.
The accepted Stage 2 core adds the pure Decimal factor, valuation,
aggregation, margin-of-safety, expected-return, downside, thesis-condition,
canonical-hash, and cap engine, including the separately frozen
capital-allocation-quality dimension and fail-closed Decimal-domain handling.
It has no V22 repository, persistence, provider, HTTP, application-layer, AI,
Quantitative Trading, portfolio-weight, or brokerage dependency. Historical
and prospective investment validation have not run.

Stage 3 adds a pure assembly boundary over repository-rehydrated V22 selector
aggregates and applicability routing. It verifies exact request/result and
selected-evidence seals, cross-selection identity/session/cutoff coherence,
canonical semantics for VALID and non-VALID results, immutable canonical IDs,
the three-to-ten-year projection horizon, versions, and state propagation. Its
Git-safe manifest contains IDs, hashes, revisions, chronology, reasons,
provider-schema/adapter lineage versions, and model versions but no
provider-native fields, licensed values, or raw provider payload/storage
references. A disposable PostgreSQL V22 run proves exact repository readback,
tamper and missing-ID refusal, direct cash-operand assembly, and NBN stopping at
bank-specialized routing before any generic operand or core path.

Existing V22 evidence can directly support reference price and a bounded set
of normalized fundamentals, but it cannot yet support every required v1
operand or derivation. The Stage 3 candidate therefore remains non-usable for
mature-company core invocation and reports explicit missing requirements. No
V22 schema, persistence semantics, migration, or business data was changed.

Stage 4 adds append-only V23 persistence under `analytics.*`. It stores usable
and non-usable assemblies without numeric substitution, preserves the
canonical 34-operand mature-company cardinality and zero-operand specialized
routing, and binds ordered evidence parents relationally. Completed synthetic
valid assessments preserve exact methods, scenarios, dimensions, ranges,
conditions, reasons, versions, claim ceiling, evidence label, and risk-cap
ceiling. Typed PostgreSQL readback replays hashes and deterministic core
arithmetic. This engineering capability does not change the current product
status: no real mature-company usable score exists and model evidence remains
`NOT_VALIDATED`.

V23 keeps the Git-safe Stage 3 manifest value-free while adding a private
input seal over exact Decimal operands, non-valid reasons, ordered evidence
parents, derivation/policy output contracts, versions, durable identity, and
cutoffs. Direct price/fundamental values are replayed from selected V22
`canonicalData`. PostgreSQL owns relational checks and sealing; the trusted
Python repository owns full Stage 2 arithmetic replay. Only the dedicated
Fundamental Value writer role may perform V23 DML, preventing ordinary
analytics writers from bypassing semantic replay.

The PostgreSQL Python backend also replays producer availability and output
semantics after full typed reconstruction on direct reads. A default backend
with the empty production registry rejects a controlled `TEST_ONLY`-derived
record; only an explicitly injected matching disposable test registry can
rehydrate it.

V23 deliberately seeds no production contracts for derived or policy-evidence
operands. The Python production registry is likewise empty. Those operands
remain `MISSING` until a future append-only governed contract supplies an
economically sufficient executable evaluator with exact parent roles,
semantics, currency, periods, chronology, and deterministic output replay.
Controlled `TEST_ONLY` evaluators exist only in disposable acceptance tests.

Stage 8B adds V24 engineering readiness for a narrow, development-only
`COMPANY_QUALITY` prospective enrollment with 252/504/756-session maturities.
It preserves `NOT_VALIDATED`, current-revision approximation, current-survivor
limitations, explicit terminal population states, and empty future maturity
rows. The engineering contract has no singular session fallback: it requires
exact `XNYS` and `XNAS` completed-decision children plus separate
`SCHEDULED_NOT_COMPLETED` planned-entry children, all hash-bound to the frozen
122/69 member distribution. No real enrollment exists.
The disposable acceptance cohort is exactly 110 usable plus 81 explicit `MISSING`
members, with 63 ordered parents per usable member and 6,930 parent rows. Python and
PostgreSQL now reproduce the same aligned-quarter, ROIC balance-boundary, per-row CAPEX,
finite chronology, injective hash-input, and Decimal-context gates. The offline
calendar ends on 2026-07-28, and
the controlled current inputs lack contractual ingestion timestamps and a
complete durable V22 identity projection for the exact C5 191-member
denominator, so status is
`BLOCKED_BY_CURRENT_EVIDENCE_AND_CHRONOLOGY`. No historical C9 row was backdated
or relabelled as prospective.

## Historical Reliability Validation

`HISTORICAL-DECISION-QUALITY-VALIDATION-v1.0.0` now provides a pure offline
cross-sectional time-slice evaluator. It separates verified PIT evidence from
conservative availability assumptions, enforces chronological outcomes and
costs, and caps retrospective current-universe claims.

The first local tactical diagnostic evaluated 55 primary and reserve
securities against SPY from 2025-07-16 through 2026-07-28. Cost-adjusted
average excess return was negative at 5, 20, and 60 sessions, so the current
tactical diagnostic at that pre-v2.2 development stage was
`UNFAVORABLE_RECENT_PERIOD`; no statistical edge was claimed.
The period is now development evidence and cannot be reused as an untouched
holdout after model changes.

The expanded 2014-2026 replay confirms that conclusion across six sealed random
dates per age band and 105 month-end dates. Tactical v2.1 remains
`MIXED_OR_UNFAVORABLE`; small positive older month-end results do not persist
in the sealed older random dates.

Strict Objective historical validation remains blocked before scoring by
cohort size, missing period starts and discrete-quarter semantics, historical
market value, and historical membership evidence. No current Objective score
was copied into the past.

A separate approximate replay of `LONG-HORIZON-RESEARCH-v1.0.0` used annual
current-revision facts with a 150-day lag. On 73 older month-end holdout slices,
the top bucket beat SPY but underperformed the bottom bucket by 2.53 percent at
126 sessions and 4.18 percent at 252 sessions. Its result is `UNFAVORABLE`, not
only because return ranking failed: daily-close running-peak measurement also
shows the top bucket had 2.73 and 3.23 percentage points deeper average maximum
drawdown. This is not a validated long-horizon ranking or downside-protection
edge. The claim remains
current-universe-retrospective and conservative-lag only.

Those v2.1 and v1.0 results are retained only as
`DEVELOPMENT_OBSERVED`. Their dates and outcomes were observed before Tactical
v2.2 and Long Horizon v1.1 were frozen, so they are not an untouched holdout
for either current model.

The current deterministic models and their accepted freeze records are now:

- `TACTICAL-SIGNAL-v2.2.0`, with independent 1-week, 1-month, and 3-month
  continuation and mean-reversion theses plus explicit falling-knife, chase,
  volatility, liquidity, and event-risk gates; and
- `LONG-HORIZON-RESEARCH-v1.1.0`, which separately reports company quality,
  financial strength, capital allocation, valuation and entry, expected-return
  range, permanent-loss and downside risk, and evidence confidence. It has no
  default ranking score.

The strict PIT current-model historical terminals remain honestly
`BLOCKED_BY_DATA`.
Tactical v2.2 records 55 `MISSING`, 2 `NOT_APPLICABLE`, and 9 `EXCLUDED`
securities because dated sector mapping and benchmarks, deterministic event
evidence, and point-in-time value and quality benchmark evidence are
incomplete. Its terminal artifact SHA-256 is
`43FCFCFB4066BDFCF530308C8B04DDC409B6D6E6CFDB4DA0098424A9A207B7A0`.
Long Horizon v1.1 records the same 55/2/9 complete-population states because
the required historical decision-time financial, valuation, downside,
sector-relative, confidence, and benchmark evidence is incomplete. Its
readiness artifact SHA-256 is
`46352B1539D475F15ABA9B4E8CFE5D8E4E5D4E33AAB2313030578612F1563773`.
Neither terminal contains scores or outcome claims.

A separate Practical Tier-1 route executes frozen models against hash-verified
current-revision historical data without claiming PIT history. Numeric
provider-derived outcomes remain in Git-ignored controlled storage. Public
artifacts retain only versions, hashes, counts, availability, evidence labels,
and limitations.

Both Practical Tier-1 routes explicitly disclose current-universe survivorship
bias, provider revision risk, observed-development history, and incomplete PIT
membership. AI did not rank securities, no formula was retuned, and no
automatic trading was authorized. See the
[Tactical Practical Tier-1 report](practical-tactical-v2-2-backtest-v1.md) and
[Long Horizon Practical Tier-1 report](practical-long-horizon-v1-1-tier1-backtest-2026-07-30.md).
The publication boundary is defined in the
[Licensed Market Data Publication Policy](licensed-market-data-publication-policy.md).

The shared v2 validation infrastructure now supplies deterministic nested
chronological folds, purge and embargo rules, non-overlapping formal schedules,
separately labeled overlapping diagnostics, block bootstrap support, six
explicit benchmarks, liquidity-sensitive costs, turnover, coverage, drawdown,
downside, and benchmark-relative metrics. Missing benchmark evidence remains
missing and is never replaced by zero or SPY.

See the [master plan](model-validation-master-plan-v2.md),
[Tactical v2.2 methodology](tactical-signal-v2-2-methodology-2026-07-29.md),
[Long Horizon v1.1 methodology](long-horizon-research-rating-v1-1.md), and
[walk-forward protocol](historical-walk-forward-validation-v2.md).

## Forward Decision-Quality Validation v2

Local contracts now exist for an immutable dual-model decision snapshot,
preregistration, prospective enrollment, and terminal outcomes at 5, 20, 60,
126, and 252 completed sessions. They bind both accepted model freezes,
complete-population terminal states, benchmark and cost policies, source
hashes, and the rule that AI cannot modify deterministic fields.

The pre-preregistration local Forward v2 engineering handoff is sealed from
READY snapshot
`beaa9952-9852-4088-9dc3-92047824414b`, universe
`market-intelligence-closed-test-us-v1.0.0`, at
`2026-07-29T02:57:08.988871Z`. Its complete population is 66 securities: 55
included, 2 reference-only, and 9 excluded. The controlled artifact hash is
`sha256:b00971fee0500a8d02f22e28b5402b8db36322127dc6500b6e354c60eb9d839c`;
the Git-safe manifest content hash is
`sha256:6afcfa078cafaa16dacf302d9cd71a63c586f0f1d8b5a157eaf7f0aab3247b30`.

The V16 audit event hash is
`sha256:eff628373f0c4a354cf761e30387713db1a2cb5acb41ce7fef61862a2e034542`,
and exact replay was confirmed. The handoff made zero provider calls and
records `aiUsedForDeterministicDecisions=false`.

That historical handoff remains ineligible for prospective use and created no
enrollment or outcome. Since that handoff, V18 added the append-only structured Forward
DQV ledger and V19 accepted the corrected v2.1.1 chronology:

```text
decisionAsOf <= sealedAt <= effectiveEntryOpen
```

The legacy v2.1.0 write path is rejected and the old HTTP writer is disabled.
The post-close v4 preflight binds the current V19 chronology evidence and V20
activation acceptance. V20 resolves the former controlled-ledger
implementation blocker. The pipeline remains blocked by the incomplete target
session, missing real 66-security input evidence, and the absence of a real
decision-time controlled benchmark ledger.

Gate H is implemented offline for the 5/20/60/126/252-session horizons. It
requires the exact six benchmarks and computes gross, frozen-cost, and net
returns plus MAE, MFE, maximum drawdown, typed downside capture, and realized
volatility. The maturity-to-statistics adapter and Forward DQV statistics
engine are also implemented offline, including deterministic circular block
bootstrap, Holm correction, sector/size strata, Tactical timing groups, Long
expected-return calibration, and typed AI/human provenance.

No real prospective post-freeze model run, prospective decision snapshot, v2.1.1
enrollment, naturally matured outcome, statistics execution, or quality report
exists. Real per-security deterministic outputs, the decision-session index,
liquidity evidence, and formal Gate H analytics remain unavailable. The target
post-close session is incomplete, so natural maturity is necessarily a future
condition. The authoritative Gate Z state is
`CRITICAL_BLOCKED_NOT_VALIDATED`; neither model is Forward-validated.

The strict historical terminal closeout is complete and remains unchanged.
The newer Practical Tier-1 results provide weaker current-universe,
current-revision evidence: Tactical 60-session ranking has modest positive
direction, while Long Horizon Business Quality has modest top-cohort
association against SPY. Neither result supersedes the prospective Gate Z
state, supplies strict PIT proof, validates Tactical entry timing, validates
Long Horizon Security Attractiveness ordering, or claims calibrated
probabilities or future excess returns.

The current Forward DQV work is offline infrastructure and immutable
preflight/acceptance evidence only. It has not made provider requests, executed
scores, enrolled decisions, observed outcomes, created cloud resources, or
deployed a service.
See [Forward Decision Snapshot v2](forward-decision-snapshot-v2.md),
[Forward Decision-Quality Validation v2](forward-decision-quality-validation-v2.md),
the [Forward v2 persistence decision](forward-validation-v2-persistence-decision.md),
the [model validation terminal closeout](model-validation-terminal-closeout-2026-07-30.md),
and the
[Gate Z completion-gap audit](end-to-end-validation-completion-gap-audit-2026-07-29.md)
and
[V20 prospective activation](forward-dqv-v20-prospective-activation-2026-07-30.md).

## Fundamental Value Stage 5 internal API

The versioned Fundamental Value FastAPI and Spring Boot contracts are
implemented, tested offline, and master accepted as Stage 5. FastAPI accepts
durable V22 IDs, replays the
accepted V22/V23 repositories, invokes the generic core only when the sealed
assembly authorizes it, and returns immutable readback. Spring Boot provides
the public workflow projection through a strict analytics client without
reimplementing formulas or reading Python-owned tables.

Both language boundaries reject noncanonical durable UUID spellings and
non-integral projection horizons before normalization. A valid assembly has no
reason; non-usable outcomes retain stable reasons. Python emits canonical
finite ordinary Decimal text, and Spring replays the assessment hash and
enforces the frozen 0.80 FCFF terminal-value-share ceiling. Missing references,
durable integrity conflicts, malformed input, and invalid upstream bodies use
distinct sanitized HTTP error classes.

Current real mature-company evidence remains `MISSING`, banks such as NBN
remain specialized-model-required, and the model label remains
`NOT_VALIDATED`. Stage 5 is engineering API readiness only: it creates no
validated investment claim, usable real-company score, final portfolio
weight, trade, brokerage authority, or provider request. The services have not
been deployed.

## Fundamental Value Stage 6 workspace

The Next.js research workspace at `/research/fundamental-value` reads immutable
decisions only through the Spring public API. Stage 6 advances only the current
readback projection to `internal-fundamental-value-result-v1.1.0`; the command
remains v1.0 and Stage 5's v1.0 result fixtures remain historical acceptance
evidence. Result v1.1 carries the complete durable security identity, ticker,
MIC, identity currency, and completed session. Python, Spring, and Next.js all
bind the response assembly ID to the requested assembly ID. Python, Spring,
and TypeScript independently re-derive a usable assessment ID from its
persistence version, assembly ID, and content hash. The completed session
cannot be later than the decision cutoff. The workspace has no Python,
PostgreSQL, provider, formula, AI-generation, ranking,
portfolio-weight, trading, or brokerage path.

The strict TypeScript decoder replays the assessment hash and rejects unknown
fields, coercion, noncanonical decimals and timestamps, chronology drift,
blank nested reasons, frozen condition drift, and claim, risk-cap, authority,
or version drift. Five conditions whose source values are exposed bind exactly
to the corresponding quality, resilience, margin-of-safety, or downside-risk
field and recompute `satisfied`. The decoder preserves explicit usable, missing,
specialized-model-required, not-applicable, and insufficient-evidence outcomes
without substituting values.

When a deterministic assessment exists, the workspace displays company and
financial dimensions, method-level valuation states, ordered fair value,
reference price, margin of safety, annualized expected return visibly tied to
the projection horizon, downside risk,
thesis/counter-thesis/invalidation evidence, and the `LONG_TERM_CORE` risk-cap
ceiling. It labels that ceiling as non-final, displays the sealed decision and
ingestion cutoffs, durable security and listing IDs, ticker, MIC, identity
currency, completed session, hashes, versions, nested reasons, and
`NOT_VALIDATED`. Percent rendering stays in arbitrary-precision decimal text.
When no assessment exists, it displays the stable Spring reason codes and does
not render numeric placeholders. No AI narrative is added.

Stage 6 is master accepted. The offline Java 21 and Spring Boot 4.1.0 runtime
passed all 71 focused Fundamental Value cases and all 138 Spring cases with
zero failures, errors, or skips; Maven reported `BUILD SUCCESS` in 21.963
seconds. This is an engineering acceptance only and does not change the
remaining evidence-coverage or investment-validation blockers.

Stage 7 retrospective work is closed. C8 remains immutably rejected for its
rank-direction and reproducibility defects. The separately preregistered C9
confirmation used nine fresh deterministic dates and a checked best-to-best
ordinal-rank runner. All frozen market-first numeric thresholds passed, but
strict high/middle/low ordering occurred on only 2/9 primary dates and sector
and fresh stress confirmation were not observed. The honest disposition is
`MIXED_NOT_VALIDATED`, with an evidence ceiling of
`DEVELOPMENT_OBSERVED_CURRENT_REVISION_APPROXIMATION`; the production model
remains `NOT_VALIDATED`. See
`docs/fundamental-value-stage7c9-final-2026-08-01.md` and the final canonical
hash `785988E194E28E0F8681064911CD9C8EA86164D5998D48C7DFA19DAB72B6456F`.

## Fundamental Value Stage 8C current-evidence acquisition

Stage 8C remains pre-enrollment engineering work. The first explicitly
authorized OpenFIGI canary under acquisition v1.2 planned four physical
requests and 18 logical jobs. It sent three requests: two completed, the third
stopped on a response-backed known semantic failure, and the fourth was never
sent. Retry remained zero and no transport outcome was unknown. The exact
failure was a parser mismatch between the valid provider share-class ticker
`BF/B` and the frozen platform ticker `BF-B`; it was not an authentication,
rate-limit, or provider-schema failure. The old run is terminal and immutable.

Acquisition v1.3 now preserves the raw provider ticker while applying a
versioned, request-bound single-slash-to-hyphen comparison only when it exactly
matches the already frozen platform ticker. Paired ISIN/CUSIP provider
identities must still agree on their exact raw ticker and FIGI tuple. Canary
acceptance and later execution rebuild the review from immutable checkpoints;
a forged/resealed review stops before any later transport. The append-only
successor addendum binds the exact current contract set without rewriting the
terminal v1.2 failure record. The 156-case Stage 8C matrix passes, and the saved
failed response reparses offline without changing the old journal or creating
a completed receipt. A new canary still requires a new run ID, plan, preflight,
authorization, and explicit network approval. SEC, Yahoo, EODHD, evidence
writes, V24 enrollment, portfolio actions, and model-label promotion remain
unauthorized. The real enrollment state remains
`BLOCKED_BY_CURRENT_EVIDENCE_AND_CHRONOLOGY`, and the model remains
`NOT_VALIDATED`.

The approved v1.3 successor canary completed four of four physical requests
and all 18 logical jobs with retry zero and no unknown transport outcome. The
review returned five unique primary mappings and thirteen unresolved provider
warnings. All twelve `XNAS` jobs were unresolved; the six `XNYS` jobs produced
five unique mappings and one unresolved mapping. Both `BF-B` identifiers
successfully preserved raw `BF/B` and converged, proving the alias repair. The
controller rejected the canary as `CANARY_REJECTED_13_UNRESOLVED`; the same
plan cannot be retried and no later phase is authorized.

The authorized v1.4 diagnostic then executed its separately frozen two-request,
ten-job boundary. Both physical requests completed once with HTTP 200; retry
remained zero and there was no failed or unknown transport outcome. Exact
private-checkpoint replay required zero sends and reproduced four unique
primary mappings, six ambiguous primary mappings, and two complete convergent
pairs. The diagnostic is rejected as `DIAGNOSTIC_REJECTED_GATE_NOT_MET`.
Its [Git-safe result](../contracts/fundamental-value-v1/stage8c-openfigi-diagnostic-v14-result-v1.json)
contains only counts and cryptographic bindings. It authorizes neither durable
identity nor the remaining OpenFIGI population, and operating-MIC binding still
requires SEC corroboration. No evidence write, V24 enrollment, outcome access,
or model-label promotion follows from this result. Broader controller authority
is separate and can be exercised only through a new exact plan.

The v1.5 US-composite successor subsequently completed its separate frozen
two-request, six-job boundary. Both requests completed once; retry remained
zero, and there was no failure or unknown transport outcome. All six jobs had
one unique primary mapping and all three identifier pairs converged, with zero
warning, error, ambiguity, missing-primary result, or pair conflict. A
zero-send replay reopened both private checkpoints and reproduced the same
review and acceptance. The
[Git-safe result](../contracts/fundamental-value-v1/stage8c-openfigi-us-composite-diagnostic-v15-result-v1.json)
records only counts and hashes. Raw identifiers, FIGI values, and response
bodies remain outside Git.

The v1.5 decision is `US_COMPOSITE_DIAGNOSTIC_COMPLETE_CONVERGENT`, but this
is a post-v1.4 engineering method repair rather than a holdout. It remains
diagnostic-only: durable identity, population remainder, V22 evidence writes,
V24 enrollment, outcome access, and evidence-label promotion are not
authorized. Operating-MIC ownership still requires SEC corroboration. The
next gate is SEC corroboration plus a target-database identity inventory and
a forward-projection-v2 contract plus a V25 identity-authority ledger; all
four are required before a governed write. The old projection-v1 path is not
an authorized continuation. The model remains `NOT_VALIDATED`.

## Documentation Lifecycle

## Quant Trading v1.1 controlled development result

`QUANT-V11-CONTROLLED-20260812-008` completed its exact six-event journal,
post-access pre-performance seal, four immutable output artifacts, and
zero-send replay. The frozen result is
`NOT_DIRECTIONALLY_SUPPORTIVE_NO_RETUNING_ON_SAME_OUTCOME`: 5 of 9 numeric
gates passed and 4 failed. The failed gates were CAGR excess versus SPY, total
return excess versus SPY, Sharpe advantage versus SPY, and positive SPY-CAGR
excess across subperiods.

From USD 100,000 over 2015-01-05 through 2026-07-27, the primary replay ended
at USD 237,071.67 with 7.76% CAGR, -14.33% maximum drawdown, and 0.770
zero-rate Sharpe. SPY ended at USD 437,644.04 with 13.63% CAGR, -33.69%
maximum drawdown, and 0.816 Sharpe. The fixed-five-bps sensitivity ended at
USD 231,463.75. Lower drawdown and completed operational gates do not override
the frozen benchmark-relative failures.

The [Git-safe aggregate fixture](../contracts/quant-trading-v1.1/historical-execution-v1.1.8-controlled-result.json)
and [English result report](quant-trading-v1.1-controlled-result-2026-08-13.md)
bind the exact run, journal, seal, terminal, output files, metrics, and gate
evaluation without raw payloads, licensed rows, orders, daily paths, security
rows, or private storage paths. The model remains `NOT_VALIDATED`; same-outcome
retuning and evidence-label promotion are prohibited.

## Quant Trading v1.1.8 digest-wire compatibility

`QUANT-V11-CONTROLLED-20260812-007` is durably
`FAILED_PRE_POST_ACCESS_SEAL` on
`payload_contract_validation_hash_must_be_an_uppercase_SHA-256`. All 203
payloads and the complete execution terminal inputs had been constructed, but
the authenticated validator emitted its native `sha256:<lowercase-64-hex>`
content reference while the runner seal requires an uppercase 64-hex digest.
No post-access seal, output, or performance value was created; the run cannot
retry.

The append-only v1.1.8 repair accepts only the exact typed validation result,
replays its content hash, and converts the proven equivalent digest to the
runner wire form. Malformed references, untyped substitutes, and even a
well-formed but altered digest fail closed. All other immediate post-seal digest
arguments are explicitly audited as uppercase SHA-256 values. Payload bytes,
terminal rows, representation, formula, ranking, cost, threshold, and claim
rules are unchanged. The model remains `NOT_VALIDATED`.

## Quant Trading v1.1.7 execution-denominator compatibility

`QUANT-V11-CONTROLLED-20260812-006` is durably
`FAILED_PRE_POST_ACCESS_SEAL` on `nontradable_session_registry_drift`. Its
203-source payload validation completed, but the checked executor incorrectly
passed zero-volume session maps for 11 unused diagnostic ETFs into the exact
execution denominator. No post-access seal, output, or performance value was
created; the run cannot retry.

The append-only v1.1.7 repair retains typed payload evidence for all 203 sources
while projecting nontradable sessions onto exactly 191 securities plus SPY.
Diagnostic ETF zero-volume evidence cannot enter the execution registry.
Explicit execution registries require exact key equality with loaded payloads;
missing and extra keys fail closed. All v1.1.6 representation, formula, cost,
threshold, and claim rules are unchanged. The model remains `NOT_VALIDATED`.

## Quant Trading v1.1.6 historical-execution compatibility

`QUANT-V11-CONTROLLED-20260812-005` is durably
`FAILED_PRE_POST_ACCESS_SEAL` on `Yahoo_bar_value_is_invalid`, diagnosed as a
producer-rounding high-price envelope failure. No post-access seal, output, or
performance value was created and the run cannot retry.

The outcome-blind scan of 629,552 usable bars found exactly 37 representation
closures across 15 symbols: 21 high and 16 low, each no larger than `1e-26`.
After v1.1.5 exact producer replay and zero-volume exclusion, v1.1.6 requires
ordered raw OHLC and producer-derived tactical open inside tactical high/low,
then closes only the direct adjusted-close escape by exact max/min. Open and
close remain unchanged; there is no epsilon, tolerance, or quantization. Each
closure binds its source, payload hashes, date, field, original/closed values,
correction, and hash. Formula, ranking, cost, threshold, and claim rules remain
unchanged; the model remains `NOT_VALIDATED`.

## Quant Trading v1.1.5 historical-execution compatibility

`QUANT-V11-CONTROLLED-20260812-004` is durably
`FAILED_PRE_POST_ACCESS_SEAL`. It opened cached payload JSON under its sealed
intents and failed on `Yahoo_adjusted_OHLC_arithmetic_drift`. No post-access
seal, output, signal, rank, return, PnL, benchmark, performance, or acceptance
value was created, and the run cannot retry.

An outcome-blind scan of all 630,672 bound wire rows found 3,100 legacy close
product differences of only `1e-27` or `1e-26`. Under the retained producer's
exact Decimal context, precision 28 with `ROUND_HALF_EVEN`, every row had exact
factor identity `AdjClose/RawClose`, exact adjusted open/high/low products, and
exact tactical-close-to-adjusted-close identity. The append-only v1.1.5 decoder
replays that arithmetic exactly with no tolerance and without dependence on the
caller's Decimal context. The v1.1.4 zero-volume missing semantics and all
formula, rank, cost, threshold, and claim rules remain unchanged. A new
immutable run is required; the model remains `NOT_VALIDATED`.

## Quant Trading v1.1.4 historical-execution compatibility

`QUANT-V11-CONTROLLED-20260812-003` is durably
`FAILED_PRE_POST_ACCESS_SEAL`. The v1.1.3 execution opened cached payload JSON
under its sealed intents and stopped on the first producer-valid zero-volume
wire row with `Yahoo_bar_wire_type_drift`. It created no post-access input seal,
output artifact, signal, rank, return, PnL, benchmark result, performance value,
or acceptance result and cannot retry.

The outcome-blind wire-domain audit covered all 630,672 bound rows and found
1,120 zero-volume rows across seven symbols, with no negative, non-integer, or
above-signed-int64 volume and no nonpositive or nonfinite price or adjustment
factor. The append-only v1.1.4 decoder validates every wire row completely,
accepts exact integer volume greater than or equal to zero, and converts zero
volume to explicit `ZERO_VOLUME_NONTRADABLE_MISSING`. Those rows remain bound
to source counts, date ranges, per-source excluded-date hashes, the complete
SPY session vector, and terminal missing rows, but never enter tradable bars,
ADTV, liquidity, signals, ranks, costs, or returns. Negative or non-integer
volume still fails closed. Formula, ranking, cost, threshold, and claim rules
are unchanged. A new immutable run is required and the model remains
`NOT_VALIDATED`.

## Quant Trading v1.1.3 historical-execution compatibility

`QUANT-V11-CONTROLLED-20260812-002` is durably `FAILED` before its post-access
input seal. After both access intents, ADM payload JSON passed the inherited
nullable provider-record-ID repair and then failed because the v1.1.2 decoder
required `sourceAdjustmentMode=UNADJUSTED`. The retained producer contract
actually emits `TOTAL_RETURN_ADJUSTED` when `Adj Close` is present, while still
recording raw OHLC, adjusted OHLC, the adjustment factor, and
`sourceAutoAdjust=false`. Run 002 produced no output or performance value and
cannot retry.

The append-only v1.1.3 decoder now requires exactly
`sourceAdjustmentMode=TOTAL_RETURN_ADJUSTED`. `UNADJUSTED` and every other
value are rejected. All other adjustment metadata and per-bar arithmetic
checks are unchanged, as are every strategy, cost, threshold, and claim rule.
The v1.1.3 post-access seal binds the new addendum version/hash and the complete
203-source validation hash. A new immutable run is required; the model remains
`NOT_VALIDATED`.

## Quant Trading v1.1.2 historical-execution compatibility

The first controlled v1.1 run,
`QUANT-V11-CONTROLLED-20260812-001`, is durably `FAILED` before its post-access
input seal. Numeric payload JSON access began with ADM, whose producer-owned
`providerRecordId` was null. No output or performance value was produced or
observed. The run is preserved and cannot retry.

The append-only v1.1.2 executor accepts `providerRecordId` as either a nonempty
string or null, leaving every economic and validation rule unchanged. Its
checked path decodes all 203 dual-hash-bound payloads only after a new execution
intent, under the same canonical lease, before the post-access input seal and
before performance. The all-source step has no standalone public preflight and
calculates no signal, rank, return, PnL, performance, or acceptance value. A new
immutable controlled run is required. The model remains `NOT_VALIDATED`.

## Quant Trading v1.1.1 historical-validation chronology

Quant Trading v1.1.1 is frozen before any v1.1 outcome access as an append-only
chronology repair to the unexecuted v1.1.0 engineering protocol. Pre-access
state now contains only facts knowable without decoding numeric payloads:
denominator and source identities, calendar authority and bounds, derivation
rules, source-code/runtime identities, economic rules, acceptance thresholds,
one-evaluation authority, and output paths. It does not fabricate actual
session schedules, formula rows, ranks, or terminal-input hashes.

In one uninterrupted noninteractive checked run, both access intents must be
sealed before the first numeric byte is read. The runner then decodes the
hash-bound bars, derives exact PILOT25, EXPANSION100, and FULL191 input
manifests, proves prefix equality, and writes a
`POST_ACCESS_PRE_PERFORMANCE_INPUT_SEAL` before calculating any return, PnL,
benchmark-performance, or acceptance value. Only FULL191 may then execute the
single performance aggregation. Decoded bytes necessarily expose bars to the
process; the protocol does not misstate this as data unavailability. The model
remains `NOT_VALIDATED`, and no real v1.1 outcome has been opened.

- This file, `README.md`, `docs/architecture.md`, and `docs/roadmap.md` describe
  the current intended system.
- Versioned methodology documents describe frozen calculation contracts.
- Dated development logs describe completed engineering work.
- `docs/generated/` contains immutable, Git-safe evidence artifacts. Those
  artifacts are not rewritten merely to reflect a newer project state.
- Controlled provider values and raw responses remain outside Git under the
  ignored `storage/` boundary.
