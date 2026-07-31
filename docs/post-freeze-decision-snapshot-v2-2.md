# Post-Freeze Decision Snapshot v2.2

## Purpose

The post-freeze decision snapshot v2.2 contract defines the first decision
artifact that may be assembled after the Forward Decision-Quality Validation
v2.2 preregistration seal. It is deliberately separate from legacy decision
snapshot contracts. A legacy artifact cannot be relabeled, migrated, or
upgraded into this contract.

The checked-in generated artifact is a contract fixture only. It proves the
shape, invariants, identity bindings, and terminal-state coverage of the
contract. It is not a real decision run, does not contain scores or ranks, and
does not authorize enrollment.

## Required bindings

Every artifact binds:

- the immutable v2.2 preregistration seal and its cutoff;
- one completed market session strictly after the seal cutoff;
- one completed-session price-evidence hash shared by all rows;
- all 66 preregistered stable public security IDs, symbols, and roles;
- Tactical Signal v2.2 terminal states for 1W, 1M, and 3M;
- Long Horizon v1.1 terminal state for 12M+;
- SPY, sector, equal-weight, pure-momentum, pure-value, and pure-quality
  benchmark evidence;
- the accepted cost-policy hash;
- sector-classification and source-snapshot hashes;
- explicit `MISSING`, `STALE`, `INVALID`, `NOT_APPLICABLE`, or `EXCLUDED`
  reason codes whenever a result is not assessed; and
- the AI narrative boundary
  `may_affect_deterministic_fields=false`.

The snapshot requires exactly 66 terminal rows: 48 primary, 7 reserve,
2 reference-only, and 9 excluded. Reference-only and excluded securities keep
their preregistered non-scoring terminal states. Missing evidence is never
coerced to zero or a neutral result.

## Temporal and immutability rules

- `decisionCutoff` and completed-session price evidence must be strictly after
  the v2.2 seal cutoff.
- Every security row must use the same decision cutoff, completed session, and
  completed-session price-evidence hash.
- A completed session cannot be inferred from an intraday observation.
- The full artifact and each security row are canonically hashed.
- Rewriting an immutable path with different content is rejected.
- `FORWARD-DECISION-SNAPSHOT-v2.0.0` and other legacy input contracts are
  rejected with `LEGACY_DECISION_SNAPSHOT_UPGRADE_PROHIBITED`.

## Contract fixture

The current checked-in fixture is
`docs/generated/post-freeze-decision-snapshot-v2-2-contract-fixture-v2.json`.
It supersedes, but does not overwrite,
`docs/generated/post-freeze-decision-snapshot-v2-2-contract-fixture.json`.
contains all 66 Git-safe terminal rows. Primary and reserve rows are
`MISSING` because no model execution is represented by the fixture.
Reference-only rows are `NOT_APPLICABLE`, and excluded rows are `EXCLUDED`.
The fixture contains no provider values, database writes, scores, ranks, AI
research, or enrollment.

The fixture can be reproduced offline:

```powershell
$env:PYTHONPATH = "analysis-python/src"
analysis-python/.venv/Scripts/python.exe `
  -m equity_analysis.forward_validation.post_freeze_decision_snapshot_v22_cli `
  --write-contract-fixture
```

The immutable writer accepts an identical replay and rejects conflicting
content. Producing a real prospective artifact requires separately approved
post-cutoff completed-session evidence and actual versioned model terminal
results. This contract alone does not make those inputs ready.
