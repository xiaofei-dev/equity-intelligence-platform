# Post-Freeze Deterministic Decision Output v2.2

## Purpose

This contract seals the real deterministic result of one post-freeze model
execution without rerunning either model. It is the only accepted bridge from
the exact 66-security execution to the prospective decision snapshot and the
maturity statistics adapter.

## Controlled payload

Each stable public security UUID has one content-addressed controlled payload.
It preserves:

- the exact Tactical 1-week, 1-month, and 3-month terminal state, opportunity
  score, selected thesis, and actionability;
- the exact Long Horizon terminal state, business quality, security
  attractiveness, downside risk, and expected-return low/base/high values;
- explicit typed missing or excluded reason codes instead of zero or a neutral
  value;
- the source snapshot, post-freeze row, classification, input, result, and
  evidence hashes;
- the direct Tactical and Long Horizon model-freeze artifact hashes; and
- the latest deterministic input-evidence availability time.

`inputEvidenceAvailableAt` describes input evidence chronology. It is not the
output seal time and must not follow the decision cutoff.

## Git-safe output set

Controlled payloads may contain deterministic result values and therefore stay
in controlled Git-ignored storage. The Git-safe manifest contains only stable
identities, terminal states, reason codes, source/model/classification/result
hashes, and the output-set hash. It contains no licensed provider values.

The set is valid only when all 66 identities occur exactly once and every
payload binds the same completed session, cutoff, source snapshot, population,
and two model freezes. Replays are byte-identical; a changed payload at an
existing content-addressed path is a hard conflict.

## Integration

`execute_post_freeze_models_v22` returns the rows and their sealed output set
from the same execution pass. The post-close orchestrator and the maturity
statistics adapter consume that same set. Neither component may reconstruct or
rerun a decision.

## Current blocked preflight

The production preflight remains blocked because real post-freeze inputs and
classification bindings are not yet available. It also records
`CONTROLLED_BENCHMARK_CONSTITUENT_LEDGER_NOT_IMPLEMENTED`: future benchmark
construction must bind an immutable per-constituent and weight ledger-set hash.
No constituent data is fabricated by this contract.

This implementation made no provider request, database read or write, real
score, prospective enrollment, commit, push, or deployment.
