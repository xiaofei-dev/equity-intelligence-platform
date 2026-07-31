# Historical DQV v2.2 Slice Diagnostic

Date: 2026-07-29

## Purpose

This work executes the historical diagnostic portion of the frozen
`FORWARD-DQV-EVALUATION-PROTOCOL-v2.2.0` without representing already
observable outcomes as an untouched holdout.

The result is intentionally bounded to development diagnostics:

- `evaluationRole=DEVELOPMENT_OBSERVED`;
- `claimCeiling=DIAGNOSTIC_ONLY`;
- `formalGateEligible=false`; and
- `untouchedHoldout=false`.

No historical result in this report can establish a statistical edge, satisfy
Forward Decision-Quality Validation, or justify model retuning.

## Plan sealing

The deterministic slice plan uses seed `20260729`.

It contains:

- six random completed sessions from 3-9 months before the frozen history end;
- six random completed sessions from 1-3 years before the history end;
- six random completed sessions from 4-10 years before the history end; and
- nine fixed-offset anchors at 3, 6, 9, 12, 18, 24, 48, 72, and 120 months.

Random samples have at least 15 completed sessions of spacing within each
stratum. The plan covers the 5-, 20-, 60-, 126-, and 252-session horizons only
when the horizon matures inside the frozen price history.

The plan builder verifies the historical-price manifest and SPY payload file
hash, extracts only `tradingDate` lines, and writes the immutable plan before
the outcome loader parses any OHLCV value. A source hash, calendar, universe,
or model-freeze drift aborts evaluation.

Plan artifact:

- path:
  `docs/generated/historical-dqv-v2-2-slice-plan.json`;
- file SHA-256:
  `1F4FB7FF27BE1E8B653FEA75E184EA7512DCD6F92E8E980920EB7D2CBEF960FB`;
- canonical hash:
  `sha256:4e9f1d64b0ccf13c355c4cddcabda5a97a597cd97a0717c6b22c76015fce13e0`.

## Evidence result

The sealed plan has 27 anchors and 120 matured anchor-horizon combinations.
Hash-verified, current-revision total-return price history supports
development-only path diagnostics for:

- SPY: 120 of 120;
- current-universe equal weight: 120 of 120; and
- trailing-126-session pure momentum: 120 of 120.

For each available benchmark and slice, controlled evidence records gross
return, liquidity-sensitive cost, net return, maximum adverse excursion,
maximum favorable excursion, maximum drawdown, downside deviation, coverage,
and holding count. Controlled horizon aggregates also record downside capture
against SPY where a negative-SPY observation exists.

The following required benchmark families remain explicit `MISSING`:

- dated sector benchmark: no historical dated sector mapping and complete
  sector ETF history;
- pure value: no decision-time PIT value-score evidence; and
- pure quality: no decision-time PIT quality-score evidence.

The derived numeric metrics remain in Git-ignored controlled storage. The
Git-safe closeout contains only statuses, counts, lineage, hashes, and claim
boundaries.

## Model disposition

No Tactical v2.2 or Long Horizon v1.1 score was produced.

All 81 matured Tactical anchor-horizon rows are
`REJECTED_FOR_MODEL_EVALUATION` because historical event evidence, dated
sector mapping, and complete decision-time model inputs are unavailable.

All 39 matured Long Horizon anchor-horizon rows are
`REJECTED_FOR_MODEL_EVALUATION` because historical PIT fundamentals,
revision lineage, and historical membership are incomplete.

Every rejected model row preserves the full 55-security current-universe
retrospective population as `MISSING`; missing inputs are not converted to
zero, neutral scores, or exclusions.

The current universe cannot be represented as historical membership.
Survivorship bias, ex-post total-return adjustment, and prior outcome
observability cap the entire result at `DIAGNOSTIC_ONLY`.

## Artifacts

Git-safe closeout:

- path:
  `docs/generated/historical-dqv-v2-2-slice-diagnostic-closeout.json`;
- file SHA-256:
  `CAD3FF14152B704F70559AF1CE1DD93702265BEAC4D5886361BCF00EADC159EA`;
- canonical hash:
  `sha256:c087760f8d0333ba2ab138cdf5b09a7f11e11f12336d5a7ac8abe10314e8f529`.

Controlled result:

- storage type: Git-ignored local;
- file SHA-256:
  `5B6ADF18AD2EB6C56F16B4DB073395902FE71AFF3D43CDC36C5531F600760915`;
- canonical hash:
  `sha256:19f949ed14d83cb83f5a57396faa4c25fb1bf840b2f5b83c6dda31768768fd2f`.

## Claim ceiling

The terminal status is `CLOSED_WITHOUT_MODEL_VALIDATION`.

This work demonstrates:

- deterministic sampling before replay;
- hash-bound offline evidence loading;
- realistic price-based cost and path calculations;
- complete benchmark availability accounting; and
- explicit rejection when PIT model evidence is insufficient.

It does not demonstrate that Tactical v2.2 or Long Horizon v1.1 is validated.
The only formal validation path remains prospective Forward DQV with
naturally matured immutable decisions.

## Execution boundary

- Provider network requests: 0
- Database reads: 0
- Database writes: 0
- Model scores or ranks: 0
- Formula, weight, threshold, or PIT changes: 0
- AI influence over deterministic fields: none
- Automatic trading: not authorized
- Commit, push, or deployment: not performed
