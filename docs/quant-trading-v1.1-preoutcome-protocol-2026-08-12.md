# Quant Trading v1.1.1 Pre-Outcome Historical Validation Protocol

Date: 2026-08-12

## Status and Claim Boundary

This document preregisters the first historical evaluation of
`QUANT-TRADING-v1.1.0` before any v1.1 numeric price, return, portfolio, or
benchmark outcome is opened. It is a successor protocol, not an amendment to
the rejected or observed v1 run.

Protocol v1.1.1 is an append-only chronology and provenance successor to the
unexecuted v1.1.0 engineering draft. The draft incorrectly required actual
session schedules, formula rows, ranks, and terminal-input manifests before
the sealed bars needed to derive them had been decoded. Its canonical hash
`0592A9A24F7975366B0C11DC1F6A991C2330F79671A96320CA30DE182FC438BE`
is preserved as the superseded identity. This repair was made before any v1.1
outcome access and changes no economic formula, population, cost rule,
threshold, or interpretation.

The v1 outcome was known before v1.1 was designed, and v1.1 will reuse the same
controlled current-survivor history. The strongest result this evaluation can
produce is therefore
`DEVELOPMENT_OBSERVED_SAME_HISTORY_POST_V1_OUTCOME`. It is not an untouched
holdout, strict point-in-time evidence, `BACKTEST_SUPPORTED`,
`FORWARD_SUPPORTED`, or production eligibility. The production model-evidence
label remains `NOT_VALIDATED` whether the numeric gates pass or fail.

No same-outcome tuning loop is allowed. Once v1.1 outcomes are opened, a
formula, threshold, batch, cost, terminal, benchmark, metric, or acceptance
change requires a new version and new preregistration. Reusing the observed
history cannot upgrade the evidence claim.

Canonical machine contract:
[historical-validation-protocol-v1.1.json](../contracts/quant-trading-v1/historical-validation-protocol-v1.1.json).
Its canonical content hash is
`FB239E0F1D7AFC3F755E2E4BF15DDE6745143BC2614C1352459109D67A0B95F4`.

## Frozen Controlled Inputs

The protocol binds, without opening their numeric outcomes:

- v1 protocol hash
  `84B5DEEDF5ABE572C135E3E1CF3D4FF7ED391F93A20A82D4F3B6C1BF48F070BC`;
- v1.1 decision-contract hash
  `BF9BF8D473CA10C0944E2F900824CE2B64B22C8778684E32AA4E5056CF5BE954`;
- the 191-security current-survivor identity set
  `B29306CE3B1A047C074B68FDA07149FFF72F7B2ECD2BC0D78AAD7B42692656C7`;
- the C9 identity-projection source seal
  `E110C20287CB1B9E2260E9DAA33C2F2A8B5CD290F11E20EB733B918F61F595DD`,
  with its predictor values explicitly unused;
- the C7 Yahoo receipt and file hashes
  `B74761883F9395F1334B3F78983DB4237DF0F3F245F449EFFDC73F98FBB738AD`
  and
  `CD830491016535733CB9FE5C4BEAEBC6EE6D48F0186B6C82F131BF30FE8168C8`;
- the C7 SPY calendar and file hashes
  `7FE1CA16970AE0346C67120DD4F32BA3BEF039276B9800757D15D3744189AA2C`
  and
  `AF107891BB758C021EC012FDAB52AADDD8A07664F41CFCB7A686434A7B477CE8`.

The development track is Yahoo adjusted OHLCV, current revision, and current
survivor only. It makes no historical-membership, delisted-population, strict
V22 identity, halt, suspension, or terminal-authority claim.

## Population and Batch Order

The 191 identities are ordered by uppercase SHA-256 of the UTF-8 durable
security ID, then by security ID ascending. The cumulative batches are exact:

| Batch | Cumulative | New rows | Purpose |
| --- | ---: | ---: | --- |
| `PILOT25` | 25 | 25 | Engineering integrity only |
| `EXPANSION100` | 100 | 75 | Engineering integrity only |
| `FULL191` | 191 | 91 | Sole primary acceptance population |

The sets are nested. Pilot and expansion performance cannot stop or change the
strategy. Advancement depends only on hashes, formula/runner parity, calendar
and adjustment identity, complete terminal rows, and deterministic replay. A
failed integrity checkpoint is preserved and closes the current protocol; it
does not authorize an in-place repair followed by a favorable reinterpretation.

## Exact v1.1 Strategy

The strategy is `DUAL_MOMENTUM_TREND-v1.1.0`, evaluated with precision 50 and
`ROUND_HALF_EVEN`.

- Each security and SPY require 253 aligned completed sessions.
- Decisions occur on every fifth completed SPY session from the first session
  with a complete SPY history and at least 20 structurally usable security
  histories.
- Absolute eligibility requires price at least USD 5, median prior-20-session
  ADTV at least USD 5 million, security and SPY closes above SMA200, positive
  12-1 and 6-1 momentum, and ATR percent no greater than 10%.
- Eligible securities receive cross-sectional 12-1 and 6-1 percentile scores
  weighted 60% and 40%. Rank ties use durable security ID ascending.
- New entries require percentile at least 80 and rank no greater than ten.
  Existing positions require percentile at least 60.
- The next observed session open is the only entry fill. An open at or below
  the initial stop or above signal close plus two ATR is skipped. There is no
  intraday reclaim entry.
- The initial stop is the greater of signal close minus the greater of three
  ATR or 2%, and 90% of signal close. There is no profit target.
- The trailing stop is the monotonic maximum of the active stop and highest
  completed close since entry, including the entry close, minus three current
  completed-session ATR, effective on the next session.
- Market-regime and SMA100 exits are evaluated after every completed close;
  retention-rank exits are evaluated only on the five-session rebalance. The
  entry session is holding session one, and the time exit is the next open
  after holding-session 126 closes. An unexplained active-bar gap schedules a
  next-tradable-open diagnostic exit and permanently marks the performance
  result incomplete even if that later exit succeeds. Stop gaps fill at the
  open; ordinary stop touches fill at the stop; stops win same-bar ambiguity.
  Same-session reentry after any exit is prohibited.
- Decisions stop early enough to provide the entry session, 126 completed
  holding sessions, and one exit session. End-of-sample forced liquidation is
  forbidden.

The portfolio starts with USD 100,000, holds at most ten long positions, risks
at most 0.5% of prior-close NAV per position, caps each position at 10% of NAV,
and uses whole shares. Sizing includes fill-to-stop loss and estimated entry
and stop-price exit costs. The minimum stop-risk, notional, and cash share bound
is floored, then decremented until both risk and cash constraints pass. Cash
earns zero; leverage and shorting are prohibited.

## Cost and Terminal Rules

Each entry and exit side pays the C9 nonlinear cost separately:

```text
participation = side fill notional / prior-20-session median ADTV
impactBps = min(50, 25 * sqrt(participation))
perSideBps = 1 + impactBps
sideRate = perSideBps / 10000
sideCostUsd = side fill notional * sideRate
```

Every execution bar has separate pre-open and completed-close ADTV fields. A
fill uses only the pre-open field: the median adjusted close times volume for
exactly twenty completed sessions strictly before that execution session. The
execution session's close and volume are excluded from all fills. The completed
field may update only after close for the next session's reserve. The entry window
therefore ends on the decision session, while the exit window ends on the
session before exit. The checked runner must recompute this field and reject a
mismatch. Missing or invalid liquidity means no fill. A separate
five-basis-point-per-side sensitivity is a complete independent replay from
USD 100,000 over the identical input and decision stream. It replaces, rather
than adds to, C9 costs; it independently recomputes sizing, cash, orders, and
positions using 5 bps entry cost and a 5 bps stop-exit reserve. Signals, ranks,
stops, exit conditions, terminal window, and metrics are unchanged. It cannot
replace the primary policy.

Adjusted OHLCV already includes split and dividend adjustment, so separate
dividend or split cash flows are forbidden. Missing candidate bars remain
explicit and cannot be imputed. An unexplained missing bar for an active
position permanently invalidates performance completion and schedules only a
next-tradable-open diagnostic exit; later bar recovery cannot restore a valid
performance result. Halts and suspensions receive no assumed fills. V1.1 has no
terminal-event input contract, so a known acquisition, delisting, or bankruptcy
cannot be modeled; the affected batch is invalid rather than substituting zero
or cash.

## Benchmarks and Metrics

SPY buy-and-hold is the primary benchmark. It uses USD 100,000, whole shares,
residual cash, the identical calendar, terminal treatment, and nonlinear entry
and exit costs from the first strategy entry open through the final maturity
close. Zero-return cash is supplemental. Equal weight is `NOT_OBSERVED`
because the accepted v1.1 decision contract does not authorize it. Sector is
`NOT_OBSERVED` because no dated sector mapping is bound. Benchmark substitution
is prohibited.

The primary metric window begins immediately before the first actual strategy
entry open with a USD 100,000 seed and ends after close on the final maturity
session after all strategy positions exit. If no strategy entry occurs, the
primary result is invalid and no performance claim is made. The first daily
return is first entry-session after-close NAV divided by USD 100,000 minus one;
CAGR calendar days are the exact final-maturity date minus first-entry date.

The full report must include final NAV, total return, CAGR, total-return and
CAGR excess over SPY, maximum drawdown, annualized volatility, zero-rate
Sharpe, turnover, costs, trade counts, net win/loss/breakeven rates, severe-loss
rate, time in market, per-decision population/ranking coverage, missing reasons,
three fixed subperiods, and the three predeclared stress windows. Daily returns
are simple after-close NAV returns; volatility uses sample standard deviation
and 252-session annualization. Maximum drawdown is the minimum of NAV divided
by its running peak minus one. A zero-volatility Sharpe is `NOT_OBSERVED`.
Each closed trade pairs one filled buy with the next filled sell for the same
security, with no intervening buy. Net return is exit cash inflow after exit
cost minus entry cash outflow including entry cost, divided by that entry cash
outflow. Open trades at the end are prohibited by the `COMPLETE_CASH` gate.

Subperiods are slices of the one unchanged primary full-run ledger, not three
independent simulations. The first point is the first completed SPY session on
or after the calendar boundary and the last point is the last completed SPY
session on or before it. Strategy and SPY returns are end after-close NAV over
start after-close NAV minus one. CAGR uses their exact session-date day
difference and 365.2425 days. Open positions and cash carry across boundaries;
there is no reset, synthetic boundary trade, or boundary transaction cost. The
warm-up and five-session decision schedule remain those of the primary run.

## One-Pass Acceptance

Only `FULL191` is evaluated for acceptance. All integrity gates and every
numeric gate are conjunctive:

- primary and fixed-cost-sensitivity strategy terminal states must both be
  `COMPLETE_CASH`;
- SPY must exit at the final maturity close and pay the frozen exit cost;

- at least 2,000 completed portfolio sessions;
- at least 50 closed trades;
- CAGR minus SPY CAGR at least zero;
- total return minus SPY total return strictly greater than zero;
- strategy zero-rate Sharpe minus SPY zero-rate Sharpe at least 0.10;
- absolute strategy drawdown minus absolute SPY drawdown no greater than 5
  percentage points;
- positive SPY CAGR excess in at least two of the three fixed subperiods;
- severe-loss rate no greater than 10%;
- five-basis-point-per-side sensitivity final NAV strictly above USD 100,000.

A complete pass is only
`DIRECTIONALLY_SUPPORTIVE_DEVELOPMENT_OBSERVATION_SAME_HISTORY_ONLY`. A numeric
failure is `NOT_DIRECTIONALLY_SUPPORTIVE_NO_RETUNING_ON_SAME_OUTCOME`. Missing
or irreproducible evidence is `INVALID_OR_INCOMPLETE_NO_PERFORMANCE_CLAIM`.
None of these states authorizes production persistence, ranking, final
portfolio weights, brokerage execution, or an evidence-label upgrade.

## Execution Stop

This preregistration does not by itself authorize outcome execution. Before the
first numeric payload byte is read, a checked runner must seal the exact
191-member denominator, all 203 source paths and file/content hashes, calendar
authority and declared bounds, decision/maturity/batch derivation rules, exact
calculation source bytes and runtime, all formula/cost/metric/acceptance rules,
retry zero, UNKNOWN-no-retry, one evaluation, and four exclusive output paths.
It must then append both the outcome-access and outcome-execution intents.
Future value-derived schedule, formula, rank, or terminal hashes must not be
fabricated in this pre-access seal.

The exact journal grammar is:

1. `PREPARATION_INTENT`;
2. `PREPARATION_STRUCTURAL_COMPLETE`;
3. `OUTCOME_ACCESS_INTENT`;
4. `OUTCOME_EXECUTION_INTENT`;
5. `POST_ACCESS_PRE_PERFORMANCE_INPUT_SEAL`;
6. exactly one `COMPLETED`, `FAILED`, or `UNKNOWN` terminal.

After decoding the already hash-bound payloads, the same uninterrupted,
noninteractive checked run must derive and durably append the exact SPY session
vector, first eligible and last mature decision dates, decision schedule, and
the PILOT25, EXPANSION100, and FULL191 formula and terminal-input manifests.
FULL191 additionally binds the exact rank manifest. Shared records must be
identical across the 25-to-100-to-191 prefixes. PILOT25 and EXPANSION100 are
integrity and replay gates only and may not calculate performance.

The post-access input seal must state that performance has not been evaluated
and may contain no return, PnL, benchmark-performance, or acceptance values.
Only after that seal is appended may the same checked run aggregate one FULL191
primary, fixed-cost, and SPY result. Every result and the terminal must bind
both the execution-intent hash and the post-access input-seal hash. A
deterministic failure before uncertain durable output is `FAILED`; an uncertain
partial durable state is `UNKNOWN` and cannot retry.

Decoding payload bytes necessarily exposes historical bars to the checked
process. The pre-performance seal does not claim those bars were unavailable.
Its honest boundary is narrower: no return, PnL, future-return comparison,
benchmark performance, or acceptance value may be calculated, inspected,
emitted, shown to a human or LLM, or used to pause and alter the frozen run
before the input seal. Bias protection comes from the complete pre-access
code/rule/source freeze, one uninterrupted noninteractive execution, immutable
journaling, and the prohibition on same-outcome tuning.

The runner must support exact read-only replay without rewriting the original
chain.

## Append-Only v1.1.2 Decoder Compatibility Addendum

`QUANT-V11-CONTROLLED-20260812-001` opened the first hash-bound ADM payload
JSON only after both access intents had been sealed. It then failed
deterministically because the producer emitted `providerRecordId: null` while
the v1.1.1 decoder required a nonempty string. The immutable terminal reason is
`Yahoo_payload_string_type_drift`. No post-access input seal, output artifact,
signal, rank, return, PnL, benchmark comparison, performance result, or
acceptance result was created. The failed run is not retryable and remains
unchanged.

The append-only v1.1.2 compatibility successor accepts exactly a nonempty JSON
string or JSON null for `providerRecordId`. Empty strings and every other JSON
type remain invalid. All root keys, other field types, adjustment arithmetic,
chronology, formula, ranking, cost, and acceptance rules remain unchanged.
Before a new run may reach its post-access seal, the checked executor must
decode all 203 dual-hash-bound payloads under the same canonical execution
lease and after a new execution intent. This integrated contract-only step
calculates no signal, rank, return, PnL, benchmark performance, or acceptance
value and is not available as a standalone pre-intent preflight. The v1.1.2
post-access input seal binds both the addendum identity and the exact 203-source
contract-validation content hash.

The Git-safe addendum is
`contracts/quant-trading-v1.1/historical-execution-v1.1.2-addendum.json`, with
canonical content hash
`D78C8E093CF334BD737FED3ACAFEFEAEFB10550EB4047762BA4B51E4AA62E19E`.
The v1.1.1 protocol above remains frozen. The model remains `NOT_VALIDATED`.

## Append-Only v1.1.3 Adjustment-Metadata Compatibility Addendum

`QUANT-V11-CONTROLLED-20260812-002` preserved both v1.1.2 access intents and
opened ADM payload JSON under the canonical execution lease. It then failed
deterministically with `Yahoo_source_adjustment_drift`, before the 203-source
contract pass, post-access seal, signal, rank, return, PnL, benchmark,
performance, output, or acceptance boundary completed. Its immutable terminal
artifact hash is
`354AB99AF9C856A16668650D929C8740222BEE2D1871BD4EF78840FA159CE5C5`;
the terminal event hash is
`3623D5A9684A22B40FE571F60BA89915F12B01473C323DA8B31703491E40D3E2`.
The run is preserved and cannot retry.

The retained Yahoo producer writes `sourceAutoAdjust=false` and, when `Adj
Close` exists, `sourceAdjustmentMode=TOTAL_RETURN_ADJUSTED`. It separately
retains raw OHLC, adjusted tactical OHLC, and the adjustment factor. The v1.1.3
successor therefore requires that exact source mode and continues to require
`normalizedAdjustmentMode=TOTAL_RETURN_ADJUSTED`, the other exact adjustment
metadata, and every per-bar identity and multiplication check. `UNADJUSTED`
and all other values fail closed. No strategy, ranking, cost, metric,
acceptance, or claim rule changes.

The Git-safe addendum is
`contracts/quant-trading-v1.1/historical-execution-v1.1.3-addendum.json`, with
canonical content hash
`E84E4F7F3D51AAABBCE3BC718D5A2240129B9A43BA9668F2E42B85453A9F9AD1`.
Runner dataclass and factory validation require that exact identity, and the
v1.1.3 post-access seal binds it plus the 203-source validation hash. Runs 001
and 002 remain immutable failed evidence. The model remains `NOT_VALIDATED`.

## Append-Only v1.1.4 Zero-Volume Compatibility Addendum

`QUANT-V11-CONTROLLED-20260812-003` preserved both access intents and opened
cached payload JSON under the canonical execution lease. It failed before the
post-access seal with `Yahoo_bar_wire_type_drift` when the v1.1.3 decoder met a
producer-valid integer zero-volume row. Its immutable execution-intent artifact
hash is `E5DBFCE2C74EA23B5BD8D8FCEDEBFF1C1E096EBF817D3D4E76DAC05860E43B08`,
failed-terminal artifact hash is
`4553C700338334DB520043F292EBDE8D7E361A4716CA7C95C7A51423CEFE5AC6`,
and terminal event hash is
`45D0307A1F68E09466803EB299462B890C71E8EEFF293A178A59D6A6ED3D6850`.
No signal, rank, return, PnL, benchmark, performance, output, or acceptance
value was created. The run is immutable and cannot retry.

The outcome-blind controlled wire scan bound 630,672 rows and found exactly
1,120 zero-volume rows across AMCR, XLRE, DXCM, CNC, AMD, CHD, and XEL. It
found no negative, non-integer, or above-signed-int64 volume and no
nonpositive or nonfinite price or adjustment factor. The v1.1.4 successor
therefore accepts exact integer volume greater than or equal to zero only. It
validates the complete row first, including dates, decimals, adjustment factor,
raw-to-tactical OHLC arithmetic, and adjusted-close identity. A zero-volume row
then becomes explicit `ZERO_VOLUME_NONTRADABLE_MISSING`; it is excluded from
tradable bars, ADTV, liquidity, signals, ranks, and execution economics.

Header bar count and first/last dates bind all wire rows. Each source binds its
wire, usable, and zero-volume counts plus the exact excluded-date-set hash. The
controlled aggregate must reconcile 630,672 wire rows as 629,552 usable plus
1,120 excluded rows across seven symbols. SPY wire sessions remain the fixed
calendar even if a SPY row is nontradable; such a session becomes an explicit
missing terminal rather than compressing time. Negative and non-integer volume
remain invalid. Formula, rank, group, cost, metric, acceptance, and claim rules
are unchanged.

The Git-safe addendum is
`contracts/quant-trading-v1.1/historical-execution-v1.1.4-addendum.json`, with
canonical content hash
`FF86ECBB940AE47017FF01A3B1E16878D68422C47E5BB3AC19C41F87F1EC36FF`.
Runs 001 through 003 remain immutable failures. Any continuation requires a
new execution identity; the model remains `NOT_VALIDATED`.

## Append-Only v1.1.5 Exact Producer-Arithmetic Addendum

`QUANT-V11-CONTROLLED-20260812-004` preserved both access intents and opened
cached payload JSON under the canonical execution lease. It failed before the
post-access seal with `Yahoo_adjusted_OHLC_arithmetic_drift`. The execution
intent artifact/event hashes are
`1533E872EA31480A263330C3588C4C0A30276E18EDCAE3332192CA79D8019AF8` and
`127FF6D4392722DFBFA77A82F7533A88D30384BBF7FAEE37CDCFB2EAE83EAACC`;
the failed terminal artifact/event hashes are
`1305F787D9C92DAFB31BC2C5CFB9FFDF1CCF087392897B5972BA0D586D461726` and
`F63C4E81C7FA059E1700AC194B2F7B66E05A0797D7419CDF7E145ADAF6BBF7FF`.
The addendum binds all five event-file hashes. No output or performance value
was created, and the immutable run cannot retry.

The outcome-blind arithmetic scan covered all 630,672 bound rows. The legacy
check found 3,100 `rawClose * factor` differences, each exactly `1e-27` or
`1e-26`, with maximum absolute difference `1e-26`. Replaying the retained
producer at Decimal precision 28 and `ROUND_HALF_EVEN` produced zero factor,
open/high/low product, or adjusted-close identity discrepancies across the
complete denominator.

The v1.1.5 decoder enters that local Decimal context for each complete wire row.
It requires exact `factor == adjustedClose / rawClose`, exact products for open,
high, and low, and exact `tactical.close == raw.adjustedClose`. It applies no
tolerance and ignores the caller's Decimal context. Bounded finite positive
prices and factor, full wire validation, and v1.1.4 zero-volume nontradable
missing behavior remain required. Formula, ranking, cost, metric, acceptance,
and claim rules are unchanged.

The Git-safe addendum is
`contracts/quant-trading-v1.1/historical-execution-v1.1.5-addendum.json`, with
canonical content hash
`379FB2D5D49DAE47ECBF0AC88C96FDE5EBF79D3A8311DEE2253C735C1D42452C`.
Runs 001 through 004 remain immutable failures. Any continuation requires a new
execution identity; the model remains `NOT_VALIDATED`.

## Append-Only v1.1.6 Representation-Closure Addendum

`QUANT-V11-CONTROLLED-20260812-005` failed before its post-access seal on
`Yahoo_bar_value_is_invalid`, diagnosed as high price below another OHLC value.
Its exact five event-file hashes and execution/terminal artifact and event
hashes are bound by the addendum. It created no output or performance value and
cannot retry.

The outcome-blind usable-bar scan found 21 high and 16 low closures, exactly 37
rows across 15 symbols, with maximum correction `1e-26` and zero remaining
TrendBar domain violation. The v1.1.6 decoder first requires v1.1.5 exact
producer arithmetic and excludes zero volume. Raw OHLC must already be ordered,
and the producer-derived tactical open must lie inside producer high/low. Only
the direct adjusted-close escape may close the representation: canonical high
is exact max and canonical low exact min of tactical O/H/L/C. Open and close do
not change; no epsilon, tolerance, or quantization is allowed.

Every closure record binds source ordinal, durable identity, symbol, both
payload hashes, date, field, original value, closed value, exact correction,
and content hash. Per-source and aggregate closure set hashes bind the exact
record set; the controlled aggregate must remain 629,552 usable, 21 high, 16
low, 37 rows, 15 symbols, maximum `1e-26`, and zero residual violation.

The addendum is
`contracts/quant-trading-v1.1/historical-execution-v1.1.6-addendum.json`, with
canonical hash
`7DC449B2B1CB0B5CB170E0C29644ECCCA2764684888DA6AA092582224216F98E`.
Runs 001 through 005 remain immutable failures; the model remains
`NOT_VALIDATED`.

## Append-Only v1.1.7 Execution-Denominator Addendum

`QUANT-V11-CONTROLLED-20260812-006` failed before the post-access seal with
`nontradable_session_registry_drift`. The addendum binds its exact five event
files and execution/terminal artifact and event hashes. The run created no
output or performance value and cannot retry.

Payload validation remains exactly 203 sources and retains all typed
zero-volume evidence, including diagnostics. Checked execution now projects
that evidence onto exactly 192 loaded identities: 191 securities plus SPY.
The 11 diagnostic benchmarks are not execution inputs and cannot leak through
the nontradable registry. The loaded executor requires exact registry-key and
payload-key equality when a registry is supplied; both missing and extra keys
fail closed.

The addendum is
`contracts/quant-trading-v1.1/historical-execution-v1.1.7-addendum.json`, with
canonical hash
`F2C5D937018AFB80D80477F3FAD02833DD4B7EE509A62D5D9BC5564767A95563`.
All prior payload, representation, strategy, cost, threshold, and claim rules
remain unchanged. Runs 001 through 006 remain immutable failures and the model
remains `NOT_VALIDATED`.

For this stage, network authorization is false, provider requests are zero,
and database writes are unauthorized. Run 001 read the first cached payload
JSON only after both intents; it produced no post-access seal, output artifact,
or performance result.

## Append-Only v1.1.8 Digest-Wire Addendum

`QUANT-V11-CONTROLLED-20260812-007` failed after complete payload and terminal
input construction but before its post-access seal. The exact failure was
`payload_contract_validation_hash_must_be_an_uppercase_SHA-256`: the typed
validator's authenticated content reference is `sha256:<lowercase-64-hex>`,
whereas the runner seal stores `<uppercase-64-hex>`. Its five event-file hashes
and all preparation, prepared, access, execution, and failed-terminal
artifact/event hashes are frozen in the addendum. It created no output or
performance value and cannot retry.

The v1.1.8 bridge takes the typed validation object rather than a
caller-provided digest, replays its canonical content hash, decodes the suffix
with `bytes.fromhex`, requires exactly 32 bytes, and emits those identical bytes
with `raw.hex().upper()`. It does not hash again. A valid-looking altered hash
fails typed replay, and malformed formats fail before the runner factory. The
execution intent, calculation-source manifest, runtime, population, source
registry, addendum, and converted validation digest are all checked against the
runner digest grammar immediately before seal creation.

The addendum is
`contracts/quant-trading-v1.1/historical-execution-v1.1.8-addendum.json`, with
canonical hash
`D58278CFB1070382275BC58B940C4CF904D9DC05F50EA65976D9476C77EBA7A2`.
All payload, denominator, representation, strategy, cost, threshold, and claim
rules remain unchanged. Runs 001 through 007 remain immutable failures and the
model remains `NOT_VALIDATED`.

## Completed Run008 Development Result

The new immutable identity `QUANT-V11-CONTROLLED-20260812-008` completed the
only authorized FULL191 development outcome. The journal has exactly six
events, including the v1.1.8 post-access pre-performance seal and completed
terminal. Exact replay reads the same four output files and hashes without
opening provider transport or changing the result.

Five of nine frozen gates passed. Completed-session count, closed-trade count,
drawdown deterioration, severe-loss rate, and fixed-five-bps sensitivity
passed. CAGR excess, total-return excess, Sharpe advantage, and positive
subperiod CAGR excess versus SPY failed. The governing interpretation is
`NOT_DIRECTIONALLY_SUPPORTIVE_NO_RETUNING_ON_SAME_OUTCOME`, the model remains
`NOT_VALIDATED`, and the same observed outcome cannot be used to retune v1.1.

The Git-safe aggregate result has canonical hash
`56FB135C51432362049BA163E78F98995D9C583C3CD656DF216BE1E5B3C52814`.
It binds aggregate metrics and exact artifact/file hashes only; it contains no
raw payload, licensed row, security row, order, daily path, or private storage
path.
