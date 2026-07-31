# Forward DQV v2.2 Statistical Evaluation Engine

## Status

This document defines the strictly offline statistical evaluator for naturally
matured Forward Decision-Quality Validation v2.2 observations.

The implementation is:

- `FORWARD-DQV-STATISTICS-INPUT-v2.2.0`;
- `FORWARD-DQV-STATISTICS-POLICY-v2.2.0`; and
- `FORWARD-DQV-STATISTICS-REPORT-v2.2.0`.

The current repository preflight remains `BLOCKED`. It is a contract fixture,
not a model-quality result. No prospective enrollment has yet produced the
minimum naturally matured population.

## Input boundary

The evaluator consumes immutable, canonical-hash-verified per-security rows.
The maturity persistence layer may have a different internal representation,
but an adapter must provide every required field without inference from later
data:

- enrollment, decision manifest, outcome batch and security identity;
- decision date and completed-session ordinal;
- model track and exact frozen model version;
- complete terminal state and reason codes;
- dated sector and market-cap size band;
- frozen deterministic Tactical or Long result fields;
- gross return, frozen round-trip cost and net return;
- frozen order participation divided by point-in-time average daily dollar
  volume plus its evidence hash;
- all six benchmark net returns and benchmark drawdowns;
- MAE, MFE, maximum drawdown, typed downside-capture state and realized
  volatility;
- AI and human provenance with both influence flags fixed to `false`; and
- source, provenance and observation hashes.

Every enrollment/horizon must contain all 66 frozen security identities. A
missing row is an operational blocker, not an abstention or a zero return.

## Horizon roles

Formal prospective evaluation uses:

- Tactical: 5, 20 and 60 completed sessions;
- Long Horizon: 252 completed sessions.

The 126-session Long result is always `DIAGNOSTIC_ONLY`. It can describe
interim behavior but cannot validate Long Horizon v1.1.

## Population and evidence gates

A formal horizon requires:

- at least 100 assessed security decisions;
- coverage of at least 0.80 after excluding only frozen
  `NOT_APPLICABLE`, `SPECIALIZED_MODEL_REQUIRED` and `EXCLUDED` rows;
- at least two distinct prospective decision dates;
- a matured completed-session span of at least twice the horizon;
- complete path and volatility metrics; and
- complete six-benchmark evidence.

Hash/version drift, incomplete frozen populations, chronology or evidence
blockers, and untrusted provenance influence return
`BLOCKED_BY_EVIDENCE`. Sample and coverage deficiencies return
`INSUFFICIENT_DATA`.

## Return and risk accounting

Formal comparisons use cost-adjusted net returns. Gross return and the frozen
round-trip cost remain separately reported. The evaluator also reports:

- rank information coefficient;
- top-quintile minus bottom-quintile net return;
- top-quintile net excess against each of SPY, the dated sector benchmark,
  frozen-universe equal weight, pure momentum, pure value and pure quality;
- MAE and MFE;
- maximum drawdown;
- downside capture;
- realized volatility;
- deterministic equal-weight top-band selection turnover between adjacent
  decision dates;
- mean and maximum hash-bound liquidity participation;
- coverage and every terminal-state count; and
- Tactical abstention count.

Score bands are fixed at 20 percent before prospective outcomes. Outcome-driven
band or threshold optimization is prohibited.

## Dependence-aware inference

The evaluator uses a deterministic circular block bootstrap:

- 10,000 iterations;
- seed `20260729`;
- 90 percent confidence intervals;
- decision-date clusters retained as indivisible units; and
- block duration no shorter than the evaluated horizon.

Ordinary IID bootstrap is prohibited.

### Null-centered one-sided p-values

For an observed statistic `T`, each circular block replicate produces `T*`.
The null distribution is explicitly centered as `T* - T`. The one-sided
positive-effect p-value is:

`(1 + count(T* - T >= T)) / (B + 1)`.

The evaluator does **not** call the uncentered proportion
`count(T* <= 0) / B` a p-value. A positive claim requires both:

- a Holm-adjusted p-value no greater than 0.10; and
- a 90 percent lower confidence bound strictly above zero.

## Holm families

Families follow the preregistered target separation.

Each Tactical horizon has one eight-test family:

1. top-minus-bottom discrimination; and
2. frozen `ENTRY`/`LIMITED_ENTRY` net return minus the frozen abstention
   categories; and
3. top net excess against each of the six benchmarks.

The actionability comparison uses only the decision-time actionability. It
does not regroup securities after observing returns and does not claim to
predict the exact market bottom. It first computes a paired participation
minus abstention spread within every decision date that contains both frozen
groups, then applies the block bootstrap to those dated spreads. Dates with
only one group are reported as not comparable and excluded from this one
test; they do not invalidate later paired dates. The comparison requires at
least two paired dates and at least 20 observations in each group across
those dates. Otherwise that test is `NOT_IDENTIFIABLE`, the Tactical target
is `INSUFFICIENT_DATA`, and no threshold is changed.

Long Horizon uses three separate confirmatory families:

- `LONG_252_BUSINESS_QUALITY`: future-fundamental discrimination;
- `LONG_252_SECURITY_ATTRACTIVENESS`: discrimination plus six benchmark
  comparisons; and
- `LONG_252_DOWNSIDE_RISK`: maximum-drawdown noninferiority and downside
  capture not above one.

Holm-Bonferroni is applied within each preregistered family with family-wise
alpha 0.10. Sector/size and provenance summaries are descriptive and cannot
manufacture a confirmatory claim. An adequately powered adverse predeclared
sector or size stratum caps an otherwise validated track at `MIXED`.

## Tactical entry thesis and timing

The frozen Tactical v2.2 fields `SetupThesis` and `Actionability` are evaluated
jointly. Each observed thesis/timing cell reports:

- count and abstention status;
- mean net return and positive-return rate;
- mean MAE, MFE, maximum drawdown and volatility; and
- time to first positive close and time to maximum favorable excursion when
  the maturity evidence supplies them.

The thesis-by-action cells remain descriptive because theses have no natural
preregistered ordering. Separately, the frozen participation-versus-abstention
comparison is confirmatory as described in the Tactical Holm family. The
evaluator does not retune an entry threshold after observing which thesis or
action performed well.

## Turnover and liquidity

Turnover is not supplied by the adapter and is never imputed as zero. For
each decision date, the engine constructs the frozen top 20 percent set from
the Tactical deterministic score or Long security-attractiveness score. For
each pair of adjacent dates it calculates one-way equal-weight turnover as
half the sum of absolute security-weight changes. The first decision has no
transition. Every transition binds the selected rows' observation hashes,
and the report binds the resulting transition ledger with a canonical hash.
If a decision lacks the relevant frozen score or tied scores make the top
band unidentifiable, turnover reports `MISSING` or `NOT_IDENTIFIABLE` with
explicit reasons. It does not crash, impute zero, or change another target's
classification.

Liquidity is a separate per-security input. Each assessed row must retain the
frozen order-notional-to-average-daily-dollar-volume participation rate and a
liquidity evidence hash. Missing participation evidence returns
`BLOCKED_BY_EVIDENCE`; transaction cost is not treated as a substitute for
liquidity evidence.

## Downside-capture applicability

Each row retains one of `VALID`, `MISSING_SPY_PATH_NOT_READY`, or
`NOT_APPLICABLE_NO_SPY_NEGATIVE_SESSIONS`. A numeric downside-capture value is
required only for `VALID` and prohibited for the other states. The evaluator
never converts not-applicable capture to zero.

Tactical and Long downside-capture controls use only the applicable `VALID`
subset and report valid, not-applicable and missing counts plus applicable
coverage. The subset requires at least 20 observations across at least two
decision dates. If it is smaller, the capture control is
`NOT_IDENTIFIABLE` and the affected target is `INSUFFICIENT_DATA`; other row
metrics remain available.

## Long target separation

Long Horizon v1.1 remains four separate evaluations:

1. business quality against a separately observed future-fundamental outcome;
2. security attractiveness against cost-adjusted return and six benchmarks;
3. downside risk against drawdown and downside capture; and
4. expected-return range calibration.

No default combined Long rank is created.

### Expected-return range calibration

The low/base/high range is treated as a scenario range, not a probability
interval. The operational calibration policy is frozen before prospective
outcomes:

- lower 90 percent bound of empirical range coverage at least 0.60;
- upper bound of mean absolute error normalized by range width at most 1.00;
- normalized bias interval contained in `[-0.25, 0.25]`; and
- lower bound of the calibration slope above zero.

The report also retains base forecast error, absolute error and empirical
range coverage. It does not claim that the range is a 60, 90 or 95 percent
probability interval.

## AI and human provenance

AI narrative and human review may be reported as descriptive provenance
strata only. Their influence flags are hard-false. They cannot change:

- scores or ranks;
- benchmark or cost evidence;
- observations;
- confirmatory statistics; or
- the terminal model-quality classification.

## Terminal classifications

Formal results may be:

- `VALIDATED`;
- `MIXED`;
- `INSUFFICIENT_DATA`;
- `NOT_VALIDATED`; or
- `BLOCKED_BY_EVIDENCE`.

The implementation does not require a favorable result. Failure of a required
confirmatory test returns `NOT_VALIDATED`; a favorable subset cannot replace
it. Disagreement among separately validated/not-validated Long targets or an
adequately powered adverse predeclared stratum returns `MIXED`.

## Current evidence blockers

The Gate-H-to-statistics adapter is implemented as
`FORWARD-DQV-MATURITY-STATISTICS-ADAPTER-v2.2.0`. It enforces an exact
66-security UUID join, immutable decision and session-calendar bindings, typed
downside-capture states, six benchmarks, frozen costs, and hash-bound liquidity
evidence.

Real prospective adapter inputs do not exist yet. The first naturally matured
batch must provide per-security:

- Tactical score, setup thesis and actionability;
- Long dimension scores and low/base/high expected-return range;
- future business-quality outcome;
- dated sector and size;
- benchmark drawdowns; and
- frozen liquidity participation rates with evidence hashes;
- typed AI/human provenance.
- a hash-bound completed-session index.

No field may be filled from a later rerun. The current preflight therefore
remains blocked by evidence and time, not by a missing adapter implementation,
and makes no real validation claim.
