# Forward Decision-Quality Validation v2.2 Protocol

Date: 2026-07-29

## Objective

This protocol defines how `TACTICAL-SIGNAL-v2.2.0` and
`LONG-HORIZON-RESEARCH-v1.1.0` will be evaluated without converting already
observed history into an untouched holdout.

Success means producing reproducible evidence and an honest terminal status.
It does not require a favorable result. The allowed outcomes include
`VALIDATED`, `MIXED`, `NOT_VALIDATED`, `INSUFFICIENT_EVIDENCE`, and
`BLOCKED_BY_DATA`.

The current protocol fixture is
`BLOCKED_AWAITING_PROSPECTIVE_DATA`. It is a contract fixture, not a model
result, enrollment, or authorization to collect outcomes.

## Evidence roles

### Historical diagnostic slices

All historical slices currently available to this project are
`DEVELOPMENT_OBSERVED`. Historical returns existed and prior aggregate results
were reviewed before this protocol. A deterministic random draw made now can
reduce discretionary date selection, but it cannot make those outcomes
unobserved.

Historical slices therefore have:

- `formalGateEligible=false`;
- `untouchedHoldout=false`; and
- `claimCeiling=DIAGNOSTIC_ONLY`.

Two date-selection views are frozen before replay:

1. six seed-controlled completed-session draws in each of the
   3-9-month, 1-3-year, and 4-10-year age bands; and
2. the last completed session on or before the 3, 6, 9, 12, 18, 24, 48, 72,
   and 120-month calendar offsets.

The seed is `20260729`. Outcomes are loaded only after the slice-plan hash is
sealed. Horizons without a complete future path remain explicitly missing.
These safeguards make the diagnostic reproducible; they do not upgrade its
claim.

### Prospective enrollment

Formal evidence starts only with a post-freeze, post-preregistration decision
snapshot enrolled before any outcome is observed. Enrollment must bind:

- the accepted Tactical v2.2 and Long Horizon v1.1 freezes;
- the complete 66-security frozen population and every terminal state;
- the benchmark v2.2 contract and all six available benchmark constructions;
- the completed-session price, corporate-action, liquidity, and cost evidence;
- model inputs, results, versions, and canonical hashes;
- `aiMayAffectDeterministicFields=false`; and
- the V18 enrollment and five-row maturity schedule.

An exact idempotent replay is allowed. A conflicting replay or a prior
decision upgrade is rejected.

## Horizons

| Completed sessions | Role | Formal |
| ---: | --- | --- |
| 5 | Tactical formal | Yes |
| 20 | Tactical formal | Yes |
| 60 | Tactical formal | Yes |
| 126 | Long Horizon interim diagnostic | No |
| 252 | Long Horizon formal | Yes |

Each outcome must mature naturally. The purge, embargo, and minimum bootstrap
block length are at least the outcome horizon. A formal assessment requires:

- at least 100 eligible security decisions;
- at least 80% frozen-population coverage;
- at least two distinct decision dates;
- a matured calendar span of at least two outcome horizons; and
- the complete six-benchmark outcome family.

The 126-session observation remains `DIAGNOSTIC_ONLY` regardless of its
direction.

## Historical leakage controls

A historical diagnostic must retain the weakest actual evidence state:

- decision inputs must have been available and ingested by the decision
  cutoff;
- current-universe retrospective membership is labeled diagnostic and cannot
  stand in for historical membership;
- delisted or later-excluded securities remain in the population with an
  explicit terminal state;
- sector and market-cap classifications must be dated;
- a current restatement cannot be backdated into a historical decision;
- decision features use only corporate actions known at the cutoff;
- outcome adjustment evidence is recorded separately from decision evidence;
- no missing, stale, invalid, or inapplicable value becomes zero or neutral;
  and
- any formula, threshold, applicability, universe, benchmark, cost, or
  evidence-policy change after replay creates a new version.

If exact point-in-time membership, revisions, or classifications cannot be
proved, the result remains an approximate development diagnostic.

## Benchmarks, costs, and path evidence

Every formal outcome records all six benchmarks:

- SPY;
- dated sector benchmark;
- equal-weight frozen universe;
- pure momentum;
- pure value; and
- pure quality.

Returns are measured from the next completed-session open to the
preregistered completed-session close. Securities and benchmarks use the same
frozen liquidity-sensitive cost policy. Every assessed row retains gross
return, cost, net return, and source evidence. Formal comparisons use net
returns.

Required metrics include:

- rank information coefficient where a target-specific ordering is
  authorized;
- top-minus-bottom net return;
- top-minus-each-benchmark net return;
- maximum adverse and favorable excursion;
- maximum drawdown and typed downside capture (`VALID`,
  `MISSING_SPY_PATH_NOT_READY`, or
  `NOT_APPLICABLE_NO_SPY_NEGATIVE_SESSIONS`);
- deterministic top-band turnover and hash-bound liquidity participation;
- coverage; and
- assessed, missing, stale, invalid, not-applicable,
  specialized-model-required, excluded, and abstention counts.

Long Horizon v1.1 retains separate `BUSINESS_QUALITY`,
`SECURITY_ATTRACTIVENESS`, and `DOWNSIDE_RISK` targets. It does not gain a
default aggregate ranking.

## Statistical protocol

Formal dependent observations use a deterministic circular block bootstrap
with:

- 10,000 iterations;
- seed `20260729`;
- 90% confidence intervals; and
- a block length no shorter than the evaluated horizon.

Ordinary IID bootstrap is prohibited. Confirmatory families use
Holm-Bonferroni control with family-wise alpha `0.10`.

Each Tactical horizon has its own eight-test family containing
top-minus-bottom discrimination, the paired within-decision-date net-return
spread between frozen `ENTRY`/`LIMITED_ENTRY` and frozen abstention
categories, and net excess return versus all six benchmarks. The
actionability comparison requires at least two comparable dates and 20
observations in each group. Single-group dates are reported as not comparable
for this test rather than invalidating later paired dates. This test evaluates
the frozen participation/timing decision; it does not claim to predict an
exact market bottom and cannot regroup securities after outcomes. Long
Horizon has three separate families: future-fundamental discrimination for business quality,
discrimination plus all six net benchmark comparisons for security
attractiveness, and drawdown/downside controls for downside risk.

A positive claim requires every confirmatory test in the relevant family to
pass its adjusted bound. A favorable subset cannot replace a failed
confirmatory test.

## Sector and size stability

Every report is stratified by dated sector and market-cap size band. Missing
classification is explicit and is not imputed. All strata are reported, but a
stratum needs at least 20 eligible decisions and two distinct decision dates
for inferential language. An underpowered stratum is
`INSUFFICIENT_EVIDENCE`.

An adequately powered, predeclared stratum with a Holm-adjusted adverse upper
bound caps the track at `MIXED`. Strata cannot be selected after results are
seen.

## Failure and stop rules

`BLOCKED_BY_DATA` applies to hash or version drift, incomplete population,
missing required benchmarks, leakage, premature outcome observation, or an
invalid resampling method.

`INSUFFICIENT_EVIDENCE` applies when sample, coverage, distinct-date,
calendar-span, interval, or path-metric requirements are not met.

`NOT_VALIDATED` applies when a required adjusted positive lower bound is not
above zero or a frozen drawdown/downside guardrail fails.

Long Horizon is `MIXED` when its separately preregistered targets disagree.
Historical diagnostics and the 126-session interim observation cannot return
`VALIDATED`.

No threshold may be optimized to fit these observed results. No validation
contract authorizes automatic trading or guaranteed-return language.

## Current execution boundary

This work:

- did not run historical or prospective scoring;
- did not call Yahoo, EODHD, SEC, or another provider;
- did not write PostgreSQL;
- did not enroll a decision or observe an outcome;
- did not use AI for a deterministic field; and
- did not commit, push, or deploy.

The machine-verifiable fixture is:

`docs/generated/forward-decision-quality-validation-v2-2-protocol-fixture.json`

The next formal step is a real post-freeze READY decision snapshot followed by
V18 prospective enrollment. Model-quality assessment must then wait for each
natural maturity.
