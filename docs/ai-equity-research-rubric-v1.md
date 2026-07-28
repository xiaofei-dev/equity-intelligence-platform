# AI Equity Research Rubric v1

Date: 2026-07-28

## Purpose

`AI-EQUITY-RESEARCH-v1.0.0` is the fixed qualitative evidence contract used
after deterministic screening. It is designed to reproduce the useful parts of
a careful human analyst's review without allowing persuasive narrative to
replace quantitative evidence.

The AI may review management history, governance, strategy, competitive
position, capital allocation, operating execution, regulatory exposure and
material events. It may explain or challenge a quantitative thesis. It may not
change raw observations, fill missing values, set portfolio weights, predict a
guaranteed return or authorize a trade.

## Required evidence package

Each company package should contain:

- deterministic one-week, one-month and three-month opportunity indices;
- the deterministic long-horizon score or an explicit missing state;
- the quantitative factor contributions and warnings;
- the latest annual filing and recent quarterly filings;
- recent earnings releases and investor presentations;
- recent earnings-call evidence from a licensed or company source;
- official biographies for the CEO and other material executives;
- relevant regulator or court material;
- trusted news only when primary evidence is unavailable or incomplete;
- source timestamps, retrieval timestamps and content hashes.

The model must not receive private account data, API keys or raw licensed
documents that the application's license does not permit it to process.

## Source quality

| Grade | Evidence source | Coefficient |
| --- | --- | ---: |
| A | Regulator, court, filed report or official government source | 1.00 |
| B | Company filing, investor relations release, transcript or governance document | 0.90 |
| C | Reputable independent reporting with named evidence | 0.75 |
| D | Analyst commentary or secondary summary | 0.40 |
| E | Social media, forum, anonymous claim or unverifiable content | 0.00 |

Grade E evidence may be recorded as an unresolved lead but cannot affect a
score. A CEO social-media statement is not treated as a company fact unless it
is an official disclosure or is independently corroborated.

## Long-horizon evidence overlay

The deterministic long-horizon score remains visible and immutable. The
qualitative overlay is bounded to plus or minus 10 points.

| Dimension | Maximum absolute adjustment | Review focus |
| --- | ---: | --- |
| Management execution and CEO record | 2.0 | Prior roles, tenure, promises versus outcomes, operating execution and succession |
| Governance and leadership integrity | 1.5 | Board independence, conflicts, related-party matters, controls and key-person risk |
| Strategy and competitive position | 2.0 | Strategic coherence, moat durability, dependencies, unit economics and competitive response |
| Capital allocation | 1.5 | Acquisitions, buybacks, dilution, leverage, investment discipline and return evidence |
| Operating resilience | 1.0 | Customer, supplier, geographic, product and financing concentration |
| Regulatory and legal exposure | 1.0 | Investigations, litigation, policy sensitivity and compliance |
| Accounting and disclosure quality | 1.0 | Restatements, auditor matters, non-GAAP dependence and one-time effects |
| Total | 10.0 | The final overlay is clamped to `[-10, +10]` |

For each dimension the model returns one signed assessment in `[-1, 1]`.
The dimension adjustment is:

```text
dimension maximum
  * signed assessment
  * confidence
  * source-quality coefficient
```

Corroborating records may increase confidence but must not be counted as
separate copies of the same event. Conflicting evidence lowers confidence or
produces `BLOCKED_SOURCE_CONFLICT`.

## Tactical event overlay

The one-week, one-month and three-month opportunity indices remain
deterministic. A separate event overlay may adjust the displayed research view
by no more than five points per horizon.

| Topic | Maximum absolute adjustment | Maximum normal lifetime |
| --- | ---: | --- |
| Earnings result or guidance change | 2.0 | Until the next earnings release or 90 days |
| Material company event | 1.0 | 30 days |
| Regulatory, litigation or policy event | 1.0 | 90 days |
| Leadership or governance event | 0.5 | 30 days |
| Product, customer or supply-chain event | 0.5 | 30 days |

An event adjustment must include an expiry. It cannot be used to reinterpret an
old event indefinitely. The raw opportunity index must always be shown beside
the adjusted research view.

## CEO and strategy review requirements

The model must examine, when evidence is available:

1. prior employers, companies founded or led, roles and tenure;
2. measurable outcomes during those periods, including failures;
3. promises, guidance and strategic targets versus observed delivery;
4. acquisition, divestiture, buyback, issuance and leverage decisions;
5. governance controversies, conflicts, related-party matters and succession;
6. the current strategy, its prerequisites and its critical dependencies;
7. the strongest credible counter-thesis and evidence that would invalidate the
   current conclusion.

Prestigious employment, founder status, media attention or personal wealth are
not evidence of management quality by themselves.

## Failure and abstention rules

The report must not receive a neutral or positive adjustment when evidence is
missing. Use one of:

- `COMPLETED`;
- `INSUFFICIENT_EVIDENCE`;
- `BLOCKED_SOURCE_CONFLICT`;
- `MATERIAL_RISK_REVIEW_REQUIRED`;
- `SIMULATED_NOT_SOURCE_VERIFIED`.

Material restatement, going-concern uncertainty, auditor resignation, verified
fraud allegation, major regulatory prohibition or unresolved source conflict
can block candidate eligibility. The model must state the evidence and cannot
silently convert the event into a small numeric deduction.

## Model and cost policy

Default production review:

- model: `gpt-5.6-terra`;
- Responses API, standard service tier;
- reasoning effort: `medium`;
- input budget: 12,000 tokens per security;
- output budget: 2,000 tokens per security;
- web-search budget: at most three calls when required evidence was not already
  supplied;
- target cost: no more than USD 0.15 per security;
- hard application budget: USD 0.20 per security.

Escalated review:

- model: `gpt-5.6-sol`;
- use only for source conflicts, material governance or accounting risk, or
  evaluation failures;
- retain the same input, output and search ceilings;
- hard application budget: USD 0.35 per security.

At the official standard short-context rates on 2026-07-28, 12,000 input and
2,000 output tokens cost approximately USD 0.06 on `gpt-5.6-terra` before tool
charges. Three web-search calls add USD 0.03 before search-content tokens.
Actual cost must be calculated from response usage; the application must stop
or abstain rather than exceed the hard budget.

Stable prompt prefixes should be reused to benefit from prompt caching. Model
prices and aliases are runtime configuration, not permanent investment
methodology, and must be reviewed when the provider changes them.

## Production acceptance

A production report is accepted only when:

- it validates against the versioned JSON Schema;
- every score-affecting claim has a retrieved citation;
- fact and inference are separately labeled;
- all evidence is within its applicable freshness window;
- adjustments respect the per-dimension and total bounds;
- missing deterministic scores remain missing;
- token, search-call and cost telemetry are retained;
- model, prompt, rubric and input-snapshot versions are recorded.
