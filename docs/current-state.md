# Current Project State

Last updated: 2026-07-30

This document is the authoritative current-state summary for the repository.
Historical methodology reports and generated acceptance artifacts remain
immutable evidence of the state that existed when they were produced.

## Verified Baseline

- Repository baseline before the current uncommitted eligibility-recovery and
  Dual-System/Task 1 integration work:
  local `main@57fa7ed4422b96e25cecb73e496f07692d026ec4`;
  `origin/main@57fa7ed4422b96e25cecb73e496f07692d026ec4`
- Market Intelligence product persistence remains owned by its V14-V17
  structures; V17 is the last shared operational application baseline
- Repository migration source and isolated-test head: `V22`; V18-V20 are the
  Forward DQV outcome, chronology, and benchmark-successor migrations, V21 is
  legacy/unwired portfolio-decision persistence, and V22 is the Unified Market
  Data and Evidence Foundation successor
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
V23 is deferred for the MVP. It becomes necessary only if the product assumes
physical raw-object retention/deletion governance, which requires policy,
deadline/jurisdiction, legal-hold, append-only disposition-event, proof, and
chain-cardinality controls. Task 1 creates neither V23 nor deletion operations.

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

## Documentation Lifecycle

- This file, `README.md`, `docs/architecture.md`, and `docs/roadmap.md` describe
  the current intended system.
- Versioned methodology documents describe frozen calculation contracts.
- Dated development logs describe completed engineering work.
- `docs/generated/` contains immutable, Git-safe evidence artifacts. Those
  artifacts are not rewritten merely to reflect a newer project state.
- Controlled provider values and raw responses remain outside Git under the
  ignored `storage/` boundary.
