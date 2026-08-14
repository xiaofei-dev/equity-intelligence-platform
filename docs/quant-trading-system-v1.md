# Quantitative Trading System v1

Date: 2026-08-12

## Status

`quant-trading-system-v1.0.0` is the methodology and decision contract for the
independent `QUANT_TRADING` sleeve. Stage 0 froze the policy surface. Stage 1
adds the pure deterministic `QUANT-TRADING-ENGINE-v1.0.0`, and Stage 2 adds its
event-driven portfolio simulator. Stage 3 rejected the frozen strategy for
production economic performance: USD 100,000 became USD 113,808.46 at 1.13%
CAGR, versus USD 438,691.69 and 13.68% CAGR for SPY. The model-evidence label
remains `NOT_VALIDATED`; no persistence, API, brokerage integration, or
production allocation is authorized.

The separately versioned `quant-trading-system-v1.1.0` successor is a new
post-outcome development hypothesis. It does not change or reinterpret v1 and
cannot claim the reused historical cache as an untouched holdout. Its first
controlled replay grew USD 100,000 to USD 237,071.67 at 7.76% CAGR versus
USD 437,644.04 and 13.63% CAGR for SPY. Five of nine gates passed, which is
retained as `NOT_DIRECTIONALLY_SUPPORTIVE_NO_RETUNING_ON_SAME_OUTCOME`, not as
validation.

## v1.1 Dual-Momentum Trend Successor

`DUAL-MOMENTUM-TREND-v1.1.0` uses exactly 253 aligned security/SPY sessions and
forms decisions only after the completed close. Absolute eligibility requires
price of at least USD 5, median 20-session dollar volume of at least USD 5
million, security and SPY closes above their 200-session averages, positive
12-minus-1-month and 6-minus-1-month momentum, and ATR no greater than 10% of
price.

Every fifth eligible SPY session, the engine ranks the complete eligible cross
section by 60% 12-1 momentum percentile and 40% 6-1 momentum percentile, using
security ID ascending as the deterministic tie break. At least 20 securities
are required. The highest ten securities with composite percentile at least 80
may enter at the next open; existing positions remain rank-eligible at 60 or
above.

The successor deliberately has no profit target. Its economic hypothesis is
that persistent medium-term winners should be allowed to run. Initial risk is
the more conservative of three ATR and 10% below the signal close, with at
least 2% stop distance. A monotonic highest-close-minus-three-ATR stop protects
gains. Market-regime failure, security close at or below SMA100, rank below 60,
126 held sessions, or unexplained missing active data schedules a next-open
exit. Same-session stops remain conservative and take priority.

Portfolio and cost assumptions remain USD 100,000, ten positions, 0.5% of
prior-close NAV risk per position, 10% notional cap, whole shares, and the C9
nonlinear cost on each side. This is a deliberate new strategy identity, not a
claim that the v1 result can be repaired by tuning its observed outcomes.

## v1.1 V22 Research-Signal Assembly

`quant-trading-v22-assembly-v1.1.0` is the provider-neutral boundary between
V22 evidence and the deterministic v1.1 cross-sectional signal core. The
public assembly command carries only immutable V22 selector request IDs, an
exact sorted security denominator, a SPY series reference, the rebalance
ordinal, and sealed decision/ingestion cutoffs. A read-only PostgreSQL adapter
hydrates the accepted V22 identity graph, ticker intervals, calendar/session
rows, and selector aggregates. It performs no provider fetch and opens no
historical outcome.

Each SPY or security series requires exactly 253 unique selector requests in
strict date order. Every request must replay its canonical ID, request hash,
deterministic selection result, strict identity and chronology policy,
`CURRENT_ONLY` claim, `canonical-equity-v1.0.0` normalization,
`daily-price-completed-session-v1.0.0` freshness policy, and
`TOTAL_RETURN_ADJUSTED` OHLCV semantics. The selected ticker assignment must
cover its session and the V22 completed-session row must match exactly.

Quant applicability is intentionally narrow. Members must be active USD common
stocks. The market series must be the active USD SPY ETF on ARCX. Missing
identity or prices remain explicit; unsupported instruments are
`NOT_APPLICABLE`; missing and not-applicable members remain in the exact
cross-sectional denominator with empty histories. Invalid, stale, excluded,
future, ambiguous, or hash-drifting selector evidence raises an integrity failure rather than
being converted to a neutral signal.

The value-bearing OHLCV tuples exist only in the in-memory engine input. The
Git-safe manifest contains evidence IDs, states, timestamps, versions, and
hashes, but no price values. This boundary authorizes only deterministic
research-signal calculation. V22 has no governed Quant event/lifecycle interval
proof, so current portfolio simulation, order workflows, and brokerage
execution remain closed. The model label remains `NOT_VALIDATED`.

## v1.1 Research Product Slice

`V27__create_quant_research_decision_v1.sql` persists the deterministic output
as an immutable, public-safe research projection. It stores the exact expected
denominator, research classifications, evidence and signal hashes, ranking,
and entry-plan context. It cannot store a final portfolio weight, order
quantity, brokerage instruction, LLM authority, or future-return guarantee.

FastAPI exposes internal create and read routes under
`/internal/v1/quant-trading/research-decisions`. Creation requires the full
V22 selector-request identity graph and performs no startup or provider fetch.
Spring exposes only GET
`/api/v1/quant-trading/research-decisions/{decisionId}` and revalidates the
complete version, state, decimal, ordering, authority, content-hash, and
deterministic-ID contract. The browser reads Spring only through
`/research/quant-trading`; it never calls Python, PostgreSQL, a provider, or a
brokerage service.

This product slice makes the existing research model usable without upgrading
its validation claim. `ENTRY_CANDIDATE` means the frozen conditions are met at
the sealed decision point; it is not an instruction to buy. `HOLD_REVIEW` and
`EXIT_REVIEW` remain human-review signals rather than autonomous actions.

## First Executable Strategy

The only v1 strategy is long-only `MOMENTUM_CONTINUATION`. Mean reversion is
not mixed into this strategy and requires a separately versioned successor.
Tactical v2.2 remains immutable; legacy 1-week, 1-month, and 3-month views are
display diagnostics only. V21 `CORE`/`TACTICAL` tables remain legacy and
unwired.

Signals are formed only after an exchange session is completed. Entry is valid
only at the next eligible scheduled-session open and expires after that
session; replay may use it only after that session is subsequently sealed as
completed. Every plan must state
an entry range, gap rule, initial stop, targets, trailing stop, invalidation,
and a maximum 60-session time stop. Exit precedence is invalidation, stop,
target, then time stop. An open inside the entry range fills at the open. An
open above the range or below the stop is skipped. An open below the range but
above the stop fills at the inclusive range low only if the daily high reclaims
that level; otherwise it is skipped.

The entry range must be ordered. For every permitted fill, executable price
geometry must satisfy
`0 < initialStop < fill <= entryRangeHigh < firstTarget`. Targets are nonempty
and strictly ascending. Before the next session, an active long trailing stop
is monotonic nondecreasing and strictly below the current executable reference.
Invalid plans fail closed as ineligible rather than being clamped.

Stop or target gaps fill at the session open; ordinary touches fill at the
active stop or first target. If both are touched in one daily bar, the stop
wins. An open-range entry starts intraday stop-first evaluation after the open.
For a reclaimed limit entry, the bar is resolved adversely but observably: a
high at or above the range low creates the entry; a low at or below the initial
stop then exits at that stop; otherwise a high at or above the first target
exits there; otherwise the position is held. If stop and target are both
possible, the stop wins. The first target exits the full position. Trailing stops
are calculated after a completed close and take effect next session;
invalidation is evaluated after close and exits next session open. Open-phase
pending invalidation precedes stop and target gaps; intraday stop precedes
target; at close the 60th-session time stop precedes trailing calculation and
invalidation. The time stop fills at that 60th completed-session close.

## Evidence and Point-in-Time Boundary

All inputs require the V22 durable security, company, instrument, share-class,
listing, ticker-assignment, completed-session, and selector identities.
Evidence retains source and normalized hashes, revisions, availability and
ingestion chronology, adjustment lineage, and provider-neutral canonical
semantics. Missing corporate-action or event evidence makes the setup
ineligible. Missing data never becomes zero or a neutral signal.

Decimal inputs are ordinary finite decimal strings. Decision timestamps are
whole-second UTC instants. Provider-native fields terminate at versioned
adapters and do not enter the model.

## Portfolio Simulation

The frozen simulation starts with USD 100,000, holds at most ten concurrent
positions, risks at most 0.5% of current NAV per position, and caps position
notional at 10% of NAV. Stop-distance sizing and the notional ceiling are both
calculated from NAV at the prior completed close. Risk includes price-to-stop
loss plus estimated entry and stop-price exit costs. The initial whole-share
candidate is the floor of the stop-risk, 10%-notional, and available-cash
bounds; it is decremented one share until both risk-budget and cash-after-cost
inequalities pass. Rates use half-even Decimal rounding and only shares use
flooring, all within an isolated precision-50 half-even context. Estimated exit
cost uses initial-stop notional and the same entry-decision prior-20-session
ADTV, never future liquidity. More than ten candidates are selected by momentum score descending
then durable security ID ascending. Slots reopen only after exit fills, and
rejected or unfilled capital stays in cash.

Leverage, shorting, options, automatic brokerage execution, AI-determined
signals, and model-determined final portfolio weights are prohibited.

## Costs and Benchmarks

SPY is the primary benchmark. Cash and equal-weight portfolios are
supplemental. Sector results remain diagnostic until dated sector mappings are
available.

The primary C9 cost policy is:

```text
participation = orderNotional / averageDailyDollarVolume
impactBps = min(50, 25 * sqrt(participation))
perSideBps = 1 + impactBps
totalCostRate = entryCostRate + exitCostRate
netReturn = grossReturn - entryCostRate - exitCostRate
```

Each side separately pays `1 + impactBps`, using that side's fill-price
notional, participation, impact, and
median dollar volume of the prior 20 completed sessions. A fixed
5-basis-point-per-side sensitivity must also be reported. Missing or invalid
liquidity evidence fails closed. Actual exit cost uses exit-fill notional and
the prior 20 completed sessions before exit, under the same isolated
precision-50 half-even Decimal context. Cash earns 0% in v1. SPY buy-and-hold and the
decision-date-rebalanced eligible equal-weight benchmark use the same calendar,
cost, adjusted-price, and terminal-event rules.

Basis points convert exactly as `sideRate = perSideBps / 10000`, then
`sideCostUsd = orderNotional * sideRate` and total cost is the sum of entry and
exit side costs. Pure simulation monetary values retain canonical Decimal
precision without quantization; only the share count is floored.

Adjusted OHLCV is split- and dividend-adjusted, so separate dividend/split cash
flows are prohibited. Durable identity survives ticker/listing changes. Halts
and suspensions never receive assumed fills. Acquisition, delisting, and
bankruptcy require explicit terminal consideration or cash value; missing
terminal evidence invalidates the affected observation.

## Deterministic Stage 1 Signal

The Stage 1 engine requires exactly 253 security and SPY completed sessions,
aligned by session date and available and ingested no later than the sealed
decision cutoff. It uses exact `Decimal` arithmetic inside an isolated
precision-50, `ROUND_HALF_EVEN` context. All OHLCV observations are adjusted,
positive, provider-neutral, immutable tuples. The signal session, six-part
durable identity, selector IDs, source and normalized hashes, revisions, and
event, corporate-action, and lifecycle evidence are content-hash bound.
The exact aligned-session set is separately sealed and binds each security and
SPY bar's session ID, session hash, date, and completion instant. SPY must bind
the `MARKET_BENCHMARK_SPY` role, ticker `SPY`, `ARCX` listing context, and USD;
the traded security must also be USD. Price lineage includes provider, provider
schema, adapter, normalization, freshness policy/state, and adjustment mode.
Event, action, and lifecycle selector evidence includes request/result,
normalized/source hashes, revision, and an effective interval covering all 253
sessions. Synthetic tests use weekday-only session rows bound to the explicit
test-only calendar seal; they do not claim exchange-holiday authority.
The Stage 1 session-set and benchmark-identity inputs are explicitly a
`TRUSTED_PREVALIDATED_ADAPTER_SEAM`: the engine recomputes their complete
canonical content seals and exact row bindings, but does not independently
establish exchange-calendar or identity authority. Stage 2 must hydrate this
seam from governed V22 calendar/session, identity-authority, SPY, and selector
records and reject TEST_ONLY authorities. Until then, the synthetic `READY`
fixture proves formula mechanics only and is not a production decision.

For the final session `t`, the formulas are:

```text
ATR14 = mean(TR[t-13..t])
SMA20/50/200 = mean of closes ending at t
M252 = C[t-20] / C[t-252] - 1
M126 = C[t-20] / C[t-126] - 1
M63 = C[t] / C[t-63] - 1
RS252 = M252_security - M252_SPY
RS126 = M126_security - M126_SPY
trendSpread = SMA50 / SMA200 - 1
prior20High = max(H[t-20..t-1])
prior10Low = min(L[t-10..t-1])
breakoutATR = (C[t] - prior20High) / ATR14
volumeRatio = V[t] / median(V[t-20..t-1])
closeLocation = (C[t] - L[t]) / (H[t] - L[t])
medianADTV20 = median(C * V over t-19..t)
chaseATR = max(0, (C[t] - SMA20) / ATR14)
atrPercent = ATR14 / C[t]
linear(x,a,b) = 100 * clamp((x-a)/(b-a), 0, 1)
```

The momentum score is the unrounded weighted sum of `linear` transforms:

| Input | Bounds | Weight |
| --- | --- | ---: |
| M252 | -0.10 to 0.40 | 15% |
| M126 | -0.08 to 0.25 | 10% |
| M63 | -0.05 to 0.20 | 15% |
| RS252 | -0.10 to 0.25 | 15% |
| RS126 | -0.08 to 0.20 | 10% |
| trendSpread | 0 to 0.20 | 15% |
| breakoutATR | 0 to 1 | 10% |
| volumeRatio | 0.80 to 2 | 5% |
| closeLocation | 0.50 to 1 | 5% |

The engine compares the unrounded score and emits score displays at two decimal
places only. A `READY` decision requires all of: price at least USD 5; median
ADTV at least USD 5 million; `C > SMA50 > SMA200`; SPY close above its SMA200;
positive M252, M126, and RS252; close above prior20High; volume ratio at least
1.10; close location at least 0.65; ATR percent at most 0.08; chase ATR at most
3; score at least 60; and valid identity, event, corporate-action, lifecycle,
and chronology evidence. Sector evidence is diagnostic only and cannot create
or block the v1 signal.

For a ready setup:

```text
entryLow = max(prior20High, close - 0.5 * ATR14)
entryHigh = close + 0.25 * ATR14
rawStop = max(prior10Low, entryLow - 2 * ATR14)
initialStop = min(rawStop, entryLow * 0.98)
stopDistanceFraction = (entryLow - initialStop) / entryLow
```

The stop fraction must be within the inclusive range 0.02 to 0.12. After an
actual fill `F`, `R = F - initialStop` and the sole v1 target is `F + 2R`.
After each completed close, the next-session trailing candidate is the highest
completed close since entry minus three current ATR14 values; the active stop
is the greater of that candidate and the prior stop and may never be at or
above the current executable reference. Invalidation is one close at or below
`breakoutLevel - 0.5 * currentATR14`, or two consecutive closes below their
current SMA20 values. It exits at the next eligible session open. The time
stop remains the close of the 60th completed holding session.

The output states are `READY`, `NO_SETUP`, `INELIGIBLE`, `MISSING`, `STALE`,
and `INVALID`. Explicit missing, stale, invalid, or ineligible evidence never
produces numeric features, a score, or a plan. A valid but economically weak
setup may produce auditable features in `NO_SETUP`, but never a trade plan.
Input and result hashes bind every version and evidence identity. Canonical
Decimals never use exponents, trailing fractional zeroes, or signed zero;
scores alone are displayed with exactly two decimal places.

## Validation Boundary

The 5-, 20-, and 60-session outcomes are diagnostics, not separate buy-and-hold
products and not sufficient alone to validate the model. Historical evidence
starts at `DEVELOPMENT_OBSERVED_CURRENT_REVISION_CURRENT_SURVIVOR`; production
remains `NOT_VALIDATED`. Backtests need realistic costs, complete terminal
states, current-survivor disclosure, and chronology controls. Results may show
value without perfect prediction, but cannot guarantee future returns or tune
this frozen methodology after outcomes are seen.

The canonical Git-safe artifacts are
`contracts/quant-trading-v1/decision-contract.example.json` and
`contracts/quant-trading-v1/engine-assessment.example.json`. They contain policy
metadata and controlled synthetic engineering evidence only, not licensed
provider values or brokerage instructions.

## Deterministic Stage 2 Simulator

Stage 2 adds a pure precision-50 event-driven USD 100,000 simulator. It binds
the exact unrounded Stage 1 selection score and READY result, processes each
sealed date in open, intraday, then close order, applies whole-share risk
sizing and primary C9 nonlinear costs, and force-liquidates remaining strategy
and SPY positions at the final completed close. It emits complete immutable
cash, NAV, order/rejection, position, terminal-event, and session ledgers.

Execution inputs remain a trusted prevalidated simulation-adapter seam. Stage
2 checks structural session, adjusted-price, action, lifecycle, evidence hash,
and cross-window history consistency but does not claim real multi-MIC calendar
or provider authority. That production assembly belongs to Stage 3. Terminal
events execute at close, use explicit dated evidence and the same exit-side
cost, and cannot release cash or a slot earlier in the session. If a newly
calculated trailing stop is not executable below the close, the position exits
at the next open under `TRAILING_STOP_NOT_EXECUTABLE`.

SPY and zero-return cash are available benchmarks. Equal weight is explicitly
`NOT_OBSERVED/BLOCKED_POPULATION_SEAL_REQUIRED` until a pre-outcome immutable
eligible-population contract exists. Primary and fixed five-basis-point-per-side
cost-only sensitivity results are separate. Passing synthetic tests does not
upgrade the model above `NOT_VALIDATED`.
