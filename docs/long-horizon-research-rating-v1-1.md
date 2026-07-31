# Long-Horizon Research Rating v1.1

Date: 2026-07-29

## Status

`LONG-HORIZON-RESEARCH-v1.1.0` is a deterministic general-company research
model. It is implemented as a new version and does not reinterpret or replace
`LONG-HORIZON-RESEARCH-v1.0.0`.

The model has not been historically or prospectively validated. Its formulas
are an engineering contract for subsequent leakage-resistant walk-forward and
Forward Decision-Quality Validation. The previously observed 2014-2026
long-horizon results are development evidence and are not an untouched
holdout for this version.

Objective Rating v1 remains a separate model with separate formulas, cohort
rules, evidence requirements, and acceptance status.

## Design correction

v1.0 was an absolute research rubric, but its historical diagnostic treated
the single combined score as a cross-sectional expected-return rank. The top
bucket sometimes beat SPY while still underperforming the bottom bucket and
experiencing deeper drawdowns.

v1.1 removes that ambiguity. It does not provide a default ranking score.
Instead, it separates company economics, security price, expected return,
risk, relative evidence, and evidence confidence.

## Supported scope

The implemented core supports mature general operating companies.

The following company models do not receive a general-company score:

- banks;
- insurance companies;
- REITs;
- resource companies;
- biotechnology companies;
- recent IPOs without enough public-cycle evidence.

Specialized companies return `SPECIALIZED_MODEL_REQUIRED`. Recent IPOs return
`INSUFFICIENT_PUBLIC_HISTORY` and `SPECULATIVE_RESEARCH_ONLY`.

## Input-state contract

Every metric is provided as `MetricEvidence` with one of four states:

- `VALID`, with one finite Decimal value;
- `MISSING`, with no value;
- `INVALID`, with no value;
- `NOT_APPLICABLE`, with no value.

Missing, invalid, and not-applicable values are never converted to zero or a
neutral contribution. A dimension receives a score only when every required
factor for that dimension is valid.

Pre-normalized ratios and scores have explicit domains. Values outside those
domains become `INVALID`; they are not clipped into apparent validity.
Economically meaningful raw ratios may exceed their scoring ranges, in which
case their normalized contribution is capped at zero or 100.

All arithmetic uses `Decimal`. Scores are rounded half-even to two decimal
places. Expected-return rates are rounded half-even to four decimal places.

## Economic dimensions

### Business quality

`BUSINESS_QUALITY` is the equal-weight average of:

- return on invested capital, normalized from -5% to 25%;
- operating margin, normalized from -5% to 30%;
- free-cash-flow margin, normalized from -10% to 25%;
- earnings stability, supplied on a zero-to-one scale;
- cash-flow stability, supplied on a zero-to-one scale.

The score describes observed or deterministically derived business quality.
It is not an expected-return rank.

### Financial strength

`FINANCIAL_STRENGTH` is the equal-weight average of:

- inverse net debt to EBITDA, normalized from -1 to 5;
- interest coverage, normalized from zero to 12;
- current ratio, normalized from 0.5 to 2.0;
- inverse diluted-share growth, normalized from -5% to 10%.

Higher scores mean stronger balance-sheet and financing evidence.

### Capital allocation

`CAPITAL_ALLOCATION` is the equal-weight average of:

- incremental return on invested capital, normalized from -5% to 25%;
- reinvestment efficiency, supplied on a zero-to-one scale;
- shareholder yield, normalized from -10% to 10%;
- acquisition discipline, supplied as a zero-to-100 evidence-backed score.

An upstream assembler must define the period, derivation, availability, and
lineage of these inputs. The core model does not infer missing capital
allocation evidence.

### Valuation and entry

`VALUATION_ENTRY` is the equal-weight average of:

- free-cash-flow yield, normalized from zero to 12%;
- earnings yield, normalized from zero to 12%;
- inverse enterprise value to EBITDA, normalized from 5 to 30;
- own-history valuation attractiveness, supplied as a zero-to-one percentile.

Price-sensitive inputs can change this dimension without changing business
quality, financial strength, or capital allocation.

### Expected-return range

Expected return is a range, not a score and not a promise.

The deterministic base rate is:

```text
average(free-cash-flow yield, earnings yield)
+ conservative fundamental growth
+ shareholder yield
+ annualized valuation normalization
```

Conservative fundamental growth is capped to -10% through 20%, shareholder
yield to -10% through 15%, and annualized valuation normalization to -15%
through 15%. The base estimate is capped to -50% through 50%.

The low estimate subtracts:

```text
3% + downside-risk score / 100 * 12%
```

The high estimate adds:

```text
3% + business-quality score / 100 * 7%
```

The range is available only when its component inputs, business quality, and
downside risk are valid. The range does not authorize a default ranking.

### Permanent-loss and downside risk

`PERMANENT_LOSS_AND_DOWNSIDE_RISK` reports zero as low risk and 100 as high
risk. It combines the inverse safety contributions of:

- net debt to EBITDA;
- interest coverage;
- earnings stability;
- cash-flow stability;
- diluted-share growth;
- cyclicality risk;
- concentration risk;
- event risk.

The last three inputs are evidence-backed zero-to-100 risk scores. AI
narrative cannot provide or alter them.

### Sector-relative evidence

`SECTOR_RELATIVE` combines:

- peer quality percentile;
- peer valuation-attractiveness percentile.

Both percentiles use zero as weak and one as strong or attractive. The model
requires a versioned cohort with at least 20 members by default. A smaller
cohort returns `COHORT_INSUFFICIENT`, no relative score, and no final research
classification.

Raw margins, leverage, and valuation ratios are not treated as universally
comparable across unrelated industries.

## Evidence confidence

`EVIDENCE_CONFIDENCE` is the equal-weight average of:

- evidence coverage ratio;
- point-in-time verified ratio;
- revision-lineage ratio;
- semantic-evidence ratio.

Each component uses a zero-to-one scale.

Confidence is epistemic metadata. It does not multiply, discount, improve, or
otherwise change:

- business quality;
- financial strength;
- capital allocation;
- valuation and entry;
- the expected-return range;
- downside risk;
- sector-relative evidence;
- the research classification.

Missing confidence evidence remains explicit in the assessment's missing
fields.

## Research classification

Classification rules are deterministic and use separate dimensions:

1. `HIGH_PERMANENT_LOSS_RISK` when financial strength is below 40 or downside
   risk is at least 70.
2. `CHEAP_BUT_FRAGILE` when valuation is at least 70 and quality or financial
   strength is below 45, or downside risk is above 65.
3. `GOOD_COMPANY_EXPENSIVE` when quality is at least 70 and valuation is below
   45.
4. `QUALITY_AT_REASONABLE_PRICE` when quality is at least 70, financial
   strength at least 60, capital allocation at least 55, valuation at least
   55, and downside risk no greater than 50.
5. `ATTRACTIVE_FOR_FURTHER_RESEARCH` when quality and financial strength are
   at least 55, capital allocation at least 45, valuation at least 55, base
   expected return at least 10%, and downside risk no greater than 60.
6. Otherwise, a fully evidenced company receives `SELECTIVE_RESEARCH`.

Invalid economic evidence returns `INVALID_DATA`. Missing required economic
evidence returns `INSUFFICIENT_DATA`. An insufficient peer cohort returns
`COHORT_INSUFFICIENT`.

The classification is a research routing label. It is not a trade instruction,
portfolio weight, or guarantee of future performance.

## Ranking boundary

The assessment always returns:

```text
default_ranking_score = null
deterministic_ranking_authorized = false
```

Any future ranking policy must:

1. choose an explicit target, such as quality durability, security
   attractiveness, or downside protection;
2. define the corresponding dimension and benchmark;
3. freeze a new versioned ranking contract;
4. validate it independently;
5. preserve missing and not-applicable states.

The business-quality score must not be silently used as an expected-return
rank.

## Validation requirements

The initial structural tests prove:

- price-sensitive valuation changes do not change business quality;
- higher debt cannot improve financial strength or downside risk;
- removing evidence cannot inherit or improve a dimension score;
- confidence changes cannot alter economic outputs;
- high-quality expensive and cheap-but-fragile cases remain distinct;
- expected-return ranges are ordered;
- insufficient cohorts remain explicit;
- invalid pre-normalized inputs are not clipped into validity;
- recent IPO and specialized-company states remain explicit;
- v1.0 retains its original version identity.

These are structural tests, not evidence of investment performance.

Historical development must use nested or otherwise leakage-resistant
walk-forward evaluation. The already inspected 2014-2026 v1.0 results may be
used for failure diagnosis, but not as an untouched final holdout for v1.1.
Approximate current-revision or retrospective-universe evidence must remain
explicitly labeled and cannot be promoted to verified PIT evidence.

Prospective Forward Decision-Quality Validation must evaluate different
targets with different outcomes:

- business quality against future fundamental durability and impairment;
- security attractiveness against future benchmark-relative return;
- downside risk against future drawdown and downside capture.

A positive SPY-relative top-bucket return is insufficient when
top-minus-bottom discrimination or downside protection is negative.

## Integration and persistence boundary

This implementation adds only the standalone v1.1 core. It does not:

- register a new HTTP evaluator;
- change the v1.0 interface;
- change Market Intelligence;
- change Objective Rating v1;
- add a database migration;
- run historical scoring;
- execute provider requests;
- generate AI narrative;
- enable automatic trading.

The existing V17 horizon view stores one score and label but does not provide
a structured durable representation for all v1.1 dimensions and the
expected-return range. Persistence integration must stop for a separate
schema decision rather than hiding structured dimensions in prose.
