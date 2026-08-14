# Fundamental Value Stage 7C-5 Provider-Native Coverage and Outcome Preflight

Date: 2026-08-01

## Boundary

This immutable track is
`EODHD_PROVIDER_NORMALIZED_DISCRETE_CURRENT_REVISION_APPROXIMATION` with claim
ceiling `DEVELOPMENT_OBSERVED_CURRENT_REVISION_APPROXIMATION`. It does not claim SEC equivalence,
strict PIT, immutable revisions, production evidence eligibility, or forward
support. C1-C4R remain unchanged, including the failed C4R reconciliation
diagnostic.

The replay used only existing hash-verified EODHD fundamentals checkpoints. It
made zero network, database, cloud, or provider requests and opened no price,
return, benchmark-return, drawdown, rank-performance, or outcome values.

## Frozen producer and protocol

The contract freezes provider-native Financials paths for revenue, operating
income, net income, pretax income, tax, operating cash flow, capital
expenditure, equity, debt, and cash. Capital expenditure is outflow-positive;
other values remain as reported. Only USD rows qualify. Current revisions use
the latest filing date per distinct period end; incompatible same-latest rows
are missing. Period start is unclaimed. TTM uses four distinct quarters,
stability eight, with 60-120-day adjacent end spacing. Balance points are
prior-only and within 120 days of the inferred TTM boundary.

The unchanged Stage-2 formulas, weights, threshold, and bounds remain frozen:
tax 0-0.50, operating margin -1 to 1, FCF margin -2 to 2, and ROIC -1 to 2.
Specialized sectors and industries are routed to
`SPECIALIZED_MODEL_REQUIRED`; absent or unrecognized taxonomy fails closed as
`INSUFFICIENT_DATA`.

- Producer contract hash: `A9A8787104D9CB9BB764A21DF3DE6B22807F893FF86DA5C69609B6BBBD89A995`
- Validation protocol hash: `2BD3705BF406E9F123E0BE919A7FB339E424716E7A502401B62C7908F7592C41`

## Value-free coverage and predictor seal

The deterministic phases contain 25, 100, and 216 identities. OFFLINE216
coverage is:

| Date | Role | Complete | Missing | Specialized | ROIC | Op margin | FCF margin | Earnings stability | Cash-flow stability |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 2015-05-07 | Primary | 165 | 33 | 18 | 165 | 185 | 185 | 183 | 183 |
| 2016-05-19 | Primary | 154 | 44 | 18 | 154 | 188 | 188 | 185 | 185 |
| 2017-06-30 | Primary | 163 | 35 | 18 | 163 | 188 | 188 | 188 | 188 |
| 2018-04-09 | Primary | 107 | 91 | 18 | 107 | 188 | 188 | 188 | 188 |
| 2019-06-21 | Primary | 159 | 39 | 18 | 160 | 191 | 191 | 188 | 188 |
| 2020-04-20 | Primary | 151 | 47 | 18 | 151 | 193 | 192 | 191 | 191 |
| 2021-06-02 | Primary | 154 | 44 | 18 | 154 | 190 | 191 | 193 | 192 |
| 2022-05-18 | Primary | 169 | 29 | 18 | 170 | 194 | 193 | 193 | 193 |
| 2023-05-18 | Primary | 164 | 34 | 18 | 166 | 196 | 196 | 195 | 194 |
| 2018-09-20 | Stress | 105 | 93 | 18 | 105 | 188 | 188 | 188 | 188 |
| 2020-02-19 | Stress | 154 | 44 | 18 | 154 | 193 | 192 | 190 | 190 |
| 2022-01-03 | Stress | 159 | 39 | 18 | 159 | 194 | 193 | 193 | 192 |

Every date exceeds the frozen 100-result gate; the minimum is 105. Before any
outcome access, 1,804 exact predictor records were sealed in controlled,
Git-ignored storage. Each record binds security identity, symbol, cutoff,
primary/stress role, value, source hash, producer contract, validation protocol,
track, and its own content hash. The checkpoint binds the 100-result threshold
and asserts `outcomesReadBeforeSeal=false`.

- PILOT25 hash: `C530513C95BC24E54C4D1B08DF475765715D4D9AD283C22CD05E486A14F189D4`
- CONTROLLED100 hash: `46C055838B2C82D33170E78B87CB68231D1FF472740686AF405B33D5B7D76AF1`
- OFFLINE216 hash: `B826574C07CF01FC435B73AC25FE2839D5267365B87DE03CE1F127C7312E3553`
- Predictor checkpoint canonical hash: `D9BF09661416214C1FF9788D41AC9E1FD6505FB72E02C091B762DA4F98CCA712`
- Predictor checkpoint file SHA-256: `F96E6DE65D77D4263B52F46F605AEF9844C0A755EE7CFCD433F7AB1FB4E43B85`
- Coverage canonical hash: `848ED7DE1A55F3EBE56B6DAB4E5BF8E347C303BF803A0FAC1F096FDA7E09DB4C`
- Coverage file SHA-256: `6136495A50D4EF99C642D1C30CA9FA3823675CDADF88870ADBD05DEE5C340B66`

## Outcome preflight and stop

The predictor gate passed, but the outcome path is
`BLOCKED_OUTCOME_PATH_INCOMPLETE`. Existing caches do not provide one exact
registry binding the sealed identities and dates to completed-session calendars,
equity daily paths, adjustment/action lineage, terminal acquisition/delisting
cash treatment, numeric cost/liquidity policy, SPY, all 11 sector ETFs, and
dated sector classifications. Yahoo has a complete 56-symbol cache including
SPY but no sector ETFs; cached EODHD EOD data cover 216 equity symbols but no
benchmark/action registry. Global date ranges do not prove per-security
252/504/756-session maturity.

No live request plan is executable: the durable 310-security manifest remains
blocked and the accepted execution layer remains
`BLOCKED_EXECUTION_CONTRACT_INCOMPLETE`. Therefore no provider request was
created or attempted, UNKNOWN replay semantics were not engaged, and outcomes
remain unopened. Stage 8 is also blocked because Stage 7 has no complete
outcome/integrity result and production still lacks a usable four-target current
decision contract.
