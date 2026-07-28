# Forward Decision-Quality Final Offline Acceptance

Date: 2026-07-28

## Decision

The Forward Decision-Quality Validation framework has passed offline contract
acceptance. Its current status is `PENDING_FUTURE_OUTCOMES`, not a performance
pass.

The acceptance verifies that the deterministic objective-rating model, the
current tactical model, the preregistered counterfactual experiment, the daily
incremental protocol, and the enrollment preflight form one hash-bound and
internally consistent evidence chain.

No signal has been enrolled. No future return has been observed. No
statistical edge, recommendation, realized-return improvement, or automatic
trading authority is claimed.

## Accepted model contracts

- Objective model: `QC-v1.0.0`
- Objective scope: `CURRENT_DECISION_ONLY`
- Objective scored universe: 136 securities
- Tactical model: `TACTICAL-SIGNAL-v2.1.0`
- Tactical schema: `tactical-signal-validation-v2.1.0`
- Tactical assessed set: 10 securities
- Tactical evidence cadence: completed daily sessions
- Tactical execution boundary: no earlier than the next session open
- Tactical signal time to live: one completed session
- Forward horizons: 5, 20, and 60 trading days

The acceptance runner discovers and freezes the model and schema versions from
the sealed input artifacts. It does not hard-code Tactical Signal v2.0 or v2.1
as the only acceptable version. A later run must first create a new expected
contract manifest bound to the exact sealed model artifacts it evaluates.

## Current enrollment status

The current decision artifacts are individually valid but are not a
synchronized enrollment snapshot:

- The objective artifact is dated 2026-07-28.
- The tactical artifact uses completed-session evidence through 2026-07-27.
- Tactical evidence covers 10 named securities rather than the full
  136-security objective universe.
- Their intersection contains two securities.

The joint status is therefore
`PENDING_FRESH_SYNCHRONIZED_DECISION_SNAPSHOT`. The framework must not promote
the current artifacts into prospective episodes. A daily enrollment may begin
only after a fresh objective and tactical decision set uses the same completed
session and passes the identity, corporate-action, benchmark, and operational
gates.

## Prospective evaluation

Every prospective horizon currently remains `PENDING_FUTURE_OUTCOMES`:

| Horizon | Completed episodes | Baseline comparison | Sector ETF | SPY | Calibration |
| --- | ---: | --- | --- | --- | --- |
| 5 trading days | 0 | Pending | Pending | Pending | Pending |
| 20 trading days | 0 | Pending | Pending | Pending | Pending |
| 60 trading days | 0 | Pending | Pending | Pending | Pending |

The minimum reporting thresholds remain 20 completed episodes overall and 10
within a sector or size group. Missing or stale inputs remain explicit and are
never converted to zero or a neutral score.

The accepted counterfactual arms are:

- lump sum;
- fixed four-tranche entry;
- state-gated four-tranche entry;
- cash only;
- sector ETF; and
- SPY.

The state-gated arm is evaluated against the lump-sum, fixed-tranche, and cash
baselines and against both the sector ETF and SPY. The frozen round-trip cost
and slippage assumption is 40 basis points: 10 basis points of transaction
cost and 10 basis points of slippage on each side.

## Tactical coverage and abstention

The sealed Tactical Signal v2.1 artifact contains 10 assessed securities:

- 2 `ENTRY`;
- 1 `LIMITED_ENTRY`; and
- 7 `WATCH_ONLY`.

The seven non-actionable assessments are treated as abstentions, not hidden
failures and not neutral entries. Future reporting must retain the abstention
rate and reason, missing/stale input rate, horizon calibration, entry-stage
calibration, objective top-minus-bottom spread, and cost-adjusted relative
returns.

## Historical diagnostic boundary

The tactical artifact contains historical walk-forward diagnostics totaling
215 episode rows at each of the 5-, 20-, and 60-day horizons. These rows are
cost-adjusted descriptive diagnostics only.

They are not prospective observations, do not prove statistical edge, and do
not establish survivorship control for the named-security sample. They cannot
be merged with the future append-only episode ledger or used to satisfy the
prospective minimum sample.

## Contamination controls

The offline acceptance confirms:

- all source file hashes and embedded canonical hashes;
- immutable decision artifacts;
- completed-session-only tactical inputs;
- next-session execution rather than same-session execution;
- no relabeling of the current objective snapshot as historical PIT evidence;
- explicit overlap reporting for daily cohorts; and
- a 60-trading-day same-security, strategy, and bucket cooldown.

Identity, delisting, and unresolved corporate-action coverage remain
enrollment-time gates. Survivorship control therefore remains
`PENDING_PROSPECTIVE_IDENTITY_AND_ACTION_GATES`.

## Evidence artifacts

Expected contract manifest:

`docs/generated/forward-decision-quality-expected-contracts-v1.json`

- File SHA-256:
  `0FDFC987556BC496AE2190128573F21E6B8A37ADB8B391A8C4AEFBED32FCAE3E`
- Canonical content hash:
  `CA963812D9BCD65B77F93F074BC7377BD8AC430AFB87DDB0A668D6F1DA6536B9`

Final offline acceptance:

`docs/generated/forward-decision-quality-final-acceptance-v1.json`

- File SHA-256:
  `6FE3990801B84988B366621525D734EB1D245B8A95DD6AFCE144CDBD500684A6`
- Canonical content hash:
  `3C56150D6706802071A504B51E94D6B059D8EF097330CA164C2E415EB88FDA69`

Primary sealed model inputs:

- Objective Rating file SHA-256:
  `AB438EB24D3D1EF477252E91DE63B46911BDF2FDB66ECB69BB65715F1675B6FC`
- Objective Rating canonical content hash:
  `131FD6C59A596056CB6A329FDA3BB73404CADDF2976826B2CDD211D5CB593F4B`
- Tactical Signal file SHA-256:
  `D01BEBB339402959EBBCF219701DAF621C4F316D2FAF36A7B0D51314BCAF6EDC`
- Tactical Signal canonical content hash:
  `DCFF8D6510BE7BDDF80401E878B66DF213DF7C6E171F1E9CD253985A146D97FF`

The earlier `120259Z` Tactical Signal artifact is an intermediate artifact
with a canonical serialization defect. It is not referenced by either final
acceptance artifact.

## Execution boundary

This acceptance was produced entirely offline. It made no provider or network
request, wrote no database record, executed no new score, enrolled no signal,
and performed no commit, push, pull request, or deployment.
