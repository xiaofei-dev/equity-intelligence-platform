# Practical Tier-1 Benchmark Evaluation v1

## Purpose

This contract evaluates whether frozen Tactical v2.2 and Long Horizon v1.1
decision rows contain useful ranking, return, entry, or downside information.
It is deliberately practical: current-universe and non-point-in-time evidence
may be evaluated when stricter evidence is unavailable, but its limitations
remain explicit.

The evaluation does not require perfect accuracy or a profit on every date.
Directionally useful evidence means that the frozen model performs better than
an explicit benchmark often enough, by enough, and with acceptable downside,
turnover, coverage, and stability to justify prospective testing.

## Frozen input boundary

The evaluator consumes model decision rows. It does not calculate, change, or
tune the model score. Every run binds:

- model identifier and exact version;
- preregistered signal dimension;
- decision identifier, time, and trading-session index;
- horizon in trading sessions;
- eligible-universe count;
- stable security identity and explicit decision state;
- deterministic score only for `ASSESSED` rows;
- post-decision security and SPY returns;
- optional same-date eligible-universe equal-weight return;
- optional per-security dated sector-benchmark return;
- optional cumulative post-decision return path;
- sector, size-band, and regime diagnostic labels.

Outcomes must become available after the decision. Missing, invalid, excluded,
and abstained rows remain separate states and never become a neutral score.

## Portfolio views and costs

Each eligible date and horizon produces three equal-weight views:

1. top score bucket;
2. bottom score bucket;
3. all assessed securities.

The bucket fraction is frozen before evaluation. Score ties are resolved only
by stable security ID, which prevents unstable output without changing scores.
Turnover is one for the initial portfolio and one half of the absolute weight
change thereafter. Net return equals gross return minus the frozen round-trip
cost rate multiplied by turnover.

This is a deliberately simple cost model. It is suitable for Tier-1 comparison,
not a claim of exact execution cost.

The default preregistered target is 100 assessed securities per date and the
default minimum is 20. A bounded experiment may explicitly choose a smaller
minimum, but the 100-security target and whether it was met remain in every
slice result.

Tactical v2.2 uses the `TACTICAL_RANKING` dimension. Long Horizon v1.1 has no
default aggregate ranking. It must be evaluated independently for:

- `COMPANY_QUALITY`;
- `SECURITY_ATTRACTIVENESS`;
- `EXPECTED_RETURN`;
- `DOWNSIDE_RISK`.

The evaluator rejects rows from another dimension. It must not invent a Long
Horizon composite unless a separate frozen composite contract is supplied.

## Benchmarks

SPY is mandatory and is evaluated first.

The same-date eligible-universe equal-weight portfolio is evaluated when it is
available. It separates model ranking value from the performance of the chosen
universe.

Sector comparison is evaluated only when every selected security has a dated,
honestly bound sector return. The sector benchmark is security-specific; the
evaluator never attaches one global sector return to every company.

Missing optional benchmarks do not block SPY evaluation and remain `MISSING`.

## Statistics

For each date and horizon the evaluator reports:

- assessed count, coverage, abstention, and explicit state counts;
- Spearman rank information coefficient;
- top, bottom, and assessed-portfolio gross and net returns;
- excess return versus SPY, equal weight, and sector when available;
- top-minus-bottom net spread;
- turnover and simple transaction cost;
- maximum drawdown, maximum adverse excursion, maximum favorable excursion,
  and annualized realized volatility when full paths are available.

Across dates it reports:

- mean return and excess return;
- benchmark hit rate;
- median rank information coefficient and its positive fraction;
- annualized information ratio;
- mean turnover and path-risk measures;
- positive top-versus-SPY date fraction;
- deterministic 90% exploratory dependency-block bootstrap intervals;
- sector, size-band, and regime stability diagnostics.

Overlapping decision windows are kept together in dependency blocks before
bootstrap resampling. The interval is exploratory and is unavailable when fewer
than four independent blocks exist.

The primary statistical unit is the date-level portfolio, not each security
row. Aggregate metrics weight dates equally. Securities are first collapsed
into the preregistered portfolio; overlapping dates are then clustered by the
holding window. Sector/size/regime outputs are descriptive diagnostics rather
than independent-certainty claims.

## Evidence labels and limitations

Evidence tier is one of:

- `CURRENT_UNIVERSE_NON_PIT`;
- `PARTIAL_PIT`;
- `STRICT_PIT`.

Current-universe, non-PIT evaluation can demonstrate practical diagnostic value,
but it can contain survivorship, look-ahead, and revision bias. It must not be
called an untouched holdout or strict historical proof. Previously observed
history also cannot be relabeled as an untouched holdout.

Stability groups are diagnostics. They must not be used for post-hoc model
selection. A favorable Tier-1 result supports continued prospective testing;
it does not prove future excess return or authorize automated trading.

AI narratives do not contribute to scores, ranks, portfolio membership, or
these statistics.

## Acceptance behavior

The evaluator fails closed on:

- model identity or version drift;
- duplicate security decisions;
- inconsistent decision metadata;
- an outcome available at or before the decision;
- a path whose final value differs from the recorded forward return;
- inconsistent SPY or equal-weight values inside one decision slice.

Insufficient slice coverage produces no portfolio or rank metric. Missing
sector or equal-weight data does not become zero and does not block SPY.

The machine-readable methodology artifact is
`docs/generated/practical-tier1-benchmark-evaluation-policy-v1.json`.
