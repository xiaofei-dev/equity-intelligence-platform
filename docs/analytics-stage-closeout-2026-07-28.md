# Analytics Stage Closeout

Date: 2026-07-28

## Outcome

The current analytics implementation has reached an engineering acceptance
checkpoint.

The deterministic model contracts, provider-substitution boundary, tactical
entry-value refinement, and Forward Decision-Quality framework are implemented
and testable. This is not a claim that either model produces excess returns.

## Accepted model contracts

| Decision domain | Model contract | Evidence cadence |
| --- | --- | --- |
| Long-horizon research | `LONG-HORIZON-RESEARCH-v1.0.0` | Sealed normalized fundamental evidence |
| Daily tactical research | `TACTICAL-SIGNAL-v2.1.0` | Completed adjusted daily sessions |

Both models use exact ID-and-version routing and return
`analytics-model-result-v1.0.0`. The result envelope preserves:

- decision timing and expiry;
- normalized-input and evidence hashes;
- provider provenance;
- explicit missing inputs and missing-data state;
- the complete deterministic result; and
- an explicit boundary that keeps AI as a separately validated overlay.

## Provider replacement boundary

Daily prices enter through the normalized `DailyPriceProvider` contract.
EODHD, yfinance, Twelve Data, or a future implementation can be substituted
without changing the tactical model request or formula.

Long-horizon fundamentals enter only after provider-specific data has been
normalized and passed the existing point-in-time, formula-readiness, lineage,
and missing-data gates. A future fundamentals provider changes this upstream
adapter, not the long-horizon scoring contract.

Provider identity is excluded from the normalized-input hash and retained in
the evidence hash and provenance. Equal normalized inputs therefore remain
deterministic while different source evidence stays auditable.

## Tactical Signal v2.1

V2.1 keeps horizon opportunity distinct from current entry value. It adds:

- momentum-extension risk;
- setup-specific entry value; and
- `WAIT_FOR_PULLBACK`.

A security is not penalized solely for reaching a 52-week high. A gradual
breakout can remain actionable, while an abnormally accelerated and extended
confirmed setup is blocked from immediate entry and receives a zero risk-unit
cap.

Authoritative sealed replay:

`docs/generated/tactical-signal-validation-20260728T120349Z-all-requested.json`

- File SHA-256:
  `D01BEBB339402959EBBCF219701DAF621C4F316D2FAF36A7B0D51314BCAF6EDC`
- Canonical content hash:
  `DCFF8D6510BE7BDDF80401E878B66DF213DF7C6E171F1E9CD253985A146D97FF`
- Physical provider requests: `0`

The earlier `120259Z` artifact is an intermediate serialization-defect
artifact and is not accepted.

## Forward Decision-Quality Validation

The offline framework acceptance is `PASS`. The overall evidence status is
`PENDING_FUTURE_OUTCOMES`.

The framework verifies:

- immutable model and evidence hashes;
- completed-session decisions and next-session execution;
- 5-, 20-, and 60-trading-day outcomes;
- transaction costs and slippage;
- lump-sum, fixed-tranche, state-gated, cash, sector ETF and SPY arms;
- abstentions and explicit missing states;
- calibration and benchmark-relative reporting contracts; and
- look-ahead, overlap, cooldown and contamination controls.

No current signal was enrolled because the sealed objective and tactical
artifacts do not yet form a synchronized full-coverage daily snapshot. No
prospective outcome has matured. Historical walk-forward rows remain
descriptive and cannot establish a prospective edge.

Final acceptance:

`docs/generated/forward-decision-quality-final-acceptance-v1.json`

- File SHA-256:
  `6FE3990801B84988B366621525D734EB1D245B8A95DD6AFCE144CDBD500684A6`
- Canonical content hash:
  `3C56150D6706802071A504B51E94D6B059D8EF097330CA164C2E415EB88FDA69`
- Framework acceptance: `PASS`
- Overall status: `PENDING_FUTURE_OUTCOMES`
- Statistical edge: `NOT_ESTABLISHED`

## Verification

The final local acceptance checks produced:

- Python full suite from repository root: `448 passed`;
- Python full suite from the CI working directory `analysis-python`:
  `448 passed`;
- independent focused tactical, analytics-interface and Forward tests:
  `69 passed`;
- Ruff across `analysis-python`: passed;
- frontend lint and production build: passed;
- PostgreSQL 17 empty-database and V3-upgrade migration acceptance through
  V13: passed;
- all four Docker Compose services after migration verification: healthy;
- final artifact file and canonical hashes: independently recomputed and
  matched;
- `git diff --check`: passed, with only line-ending notices;
- `.env` tracked by Git: no; and
- live provider requests during this closeout: zero.

The CI-working-directory run exposed and fixed a current-working-directory
dependency in the mature-gate CLI. The Windows Maven wrapper's null symlink
target handling was also corrected and `mvnw.cmd --offline --version` now
starts Maven successfully.

A fresh local backend test remains unverified in offline mode because the
configured Spring Boot 4.1.0 parent POM is not present in the local Maven
cache. This is an environment/dependency verification limitation, not a
backend test pass. The backend was unchanged by this analytics closeout; the
network-enabled CI backend job must provide the fresh backend verdict when the
changes are later pushed.

## Remaining work

The next analytics stage is prospective operation, not another retrospective
performance claim:

1. create a fresh synchronized objective and tactical decision snapshot after
   a completed session;
2. pass identity, corporate-action, benchmark and operational gates;
3. append eligible signals to the prospective ledger;
4. observe and seal real 5-, 20-, and 60-session outcomes; and
5. report calibration, abstention, cost-adjusted and benchmark-relative
   results only after the preregistered sample thresholds are met.

AI evidence review, user portfolio fit and human decisions remain separate
layers. Automatic brokerage execution and guaranteed-return claims remain out
of scope.
