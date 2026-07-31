# Post-Close Pipeline Orchestrator v2.2

## Purpose

The post-close orchestrator provides one typed, fail-closed control path from a
completed-session price capture to a chronology-safe prospective Forward DQV
enrollment. It coordinates existing deterministic implementations. It does not
reimplement Tactical v2.2, Long Horizon v1.1, benchmark formulas, costs, PIT
rules, missing-data behavior, or persistence.

The orchestrator cannot invoke provider transport. The only approved future
network entry point remains the dedicated
`future_price_evidence.history_capture_cli_v2` command. The capture must finish
and seal its immutable artifact before the orchestrator can proceed.

## Ordered stages

1. `PRICE_CAPTURE_VERIFICATION`
2. `SIX_BENCHMARK_CONSTRUCTION`
3. `FROZEN_MODEL_EXECUTION`
4. `POST_FREEZE_DECISION_SNAPSHOT`
5. `SUCCESSOR_READINESS`
6. `PROSPECTIVE_ENROLLMENT`

Every stage returns a typed terminal state:

- `COMPLETED`
- `BLOCKED`
- `UNKNOWN`
- `CONFLICT`
- `NOT_EXECUTED`

An `UNKNOWN`, immutable-artifact conflict, canonical-hash mismatch, source
binding mismatch, or incomplete upstream stage stops every later stage.
Completed stages may be reused only through their immutable native artifacts
and verified hashes. The orchestrator never retries an unknown physical
request.

## Real decision snapshot binding

The earlier readiness controller accepted a compatibility projection whose
artifact hash differed from the controlled
`PostFreezeDecisionSnapshotV22.manifestContentHash`. The enrollment adapter,
correctly, required the controlled snapshot hash. The v2.2.1 readiness bridge
fixes the mismatch without changing the immutable v2.2 controller:

1. Re-parse the controlled snapshot through its typed contract.
2. Recompute all 66 row hashes and the controlled manifest hash.
3. Compare stable public security IDs with the frozen 66-member population.
4. Recompute terminal counts from all three Tactical horizons and the Long
   Horizon terminal.
5. Require purpose `PROSPECTIVE_DECISION`.
6. Require all six benchmark states to be `AVAILABLE`.
7. Require every benchmark source binding to equal the six-benchmark manifest
   hash.
8. Require the completed-session capture hash in the snapshot price-evidence
   sources.
9. Run the immutable v2.2 readiness controller through a compatibility
   projection.
10. Emit a versioned v2.2.1 result whose
    `postFreezeDecisionManifestHash` is the real controlled snapshot hash.

The projection hash and controlled snapshot hash are both retained, so the
bridge is auditable and cannot silently replace the controlled decision.

## V19 chronology boundary

V18 acceptance and the v2.1.0 enrollment adapter are not sufficient for new
enrollment. A real run requires:

- `FORWARD-DQV-V19-CHRONOLOGY-ACCEPTANCE-v1.0.0`
- migration version 19
- a validated chronology constraint
- the chronology-safe v2.1.1 enrollment adapter

The repository now contains the verified V19 acceptance and production
v2.1.1 adapter. `ProductionEnrollmentChronologyAdapterV221` projects the
versioned readiness bridge back to the adapter's frozen v2.2 readiness shape
while preserving the controlled decision-snapshot hash. The adapter prepares
the v2.1.1 enrollment, and the orchestrator still requires separate explicit
authorization before persistence. Tests use a fake repository and never use
the business database.

## Full-population model input boundary

The model command must return exactly 66 terminal
`PostFreezeSecurityDecisionV22` rows. The orchestrator verifies:

- one unique stable public security ID per frozen member;
- each row's canonical `rowHash`;
- 1-week, 1-month, 3-month, and 12-month-plus terminal outcomes;
- explicit missing, stale, invalid, excluded, or not-applicable states;
- no AI effect on deterministic fields.

The model command is the only connection point to
`execute_post_freeze_model_rows_v22`. Data assembly must occur in the existing
provider/analytics adapters before invoking it. The orchestrator does not
invent missing inputs, transform provider fields, or convert missing evidence
to neutral scores.

## Execution authorization

Preparing an enrollment does not write the database. Persistence occurs only
when all stages are complete and the caller supplies all three:

1. an explicit `execute_enrollment=True`;
2. the chronology-safe V19 enrollment adapter;
3. an explicit enrollment repository.

No browser, provider, or web service can implicitly activate persistence.

## Current repository state

The current checked-in preflight is:

`docs/generated/post-close-pipeline-orchestrator-v2-2-preflight-v4.json`

It is intentionally `BLOCKED` for:

- `TARGET_SESSION_NOT_COMPLETED`
- `PRODUCTION_66_MODEL_INPUT_EVIDENCE_MISSING`
- `REAL_CONTROLLED_BENCHMARK_LEDGER_MISSING`

V20 resolves the former
`CONTROLLED_BENCHMARK_CONSTITUENT_LEDGER_NOT_IMPLEMENTED` infrastructure
blocker. It does not prove that a real decision-time ledger exists. The prior
v2 and v3 preflights remain immutable, are superseded for current-state
evaluation, and are not overwritten.

It executed zero provider requests, database reads, database writes, scores,
ranks, outcomes, AI calls, or enrollments.

Generate it offline with:

```powershell
$env:PYTHONPATH = "analysis-python/src"
.\analysis-python\.venv\Scripts\python.exe -m `
  equity_analysis.forward_validation.post_close_pipeline_orchestrator_cli_v22 `
  --write-blocked-preflight
```

## Future provider budget

The orchestrator's network budget is always zero. After the target session is
complete and both official calendars are reviewed, the separate capture CLI
has the already frozen ceiling:

- 67 Yahoo Chart requests
- 2 official calendar requests
- 69 total physical attempts
- provider retry limit 0

The orchestrator begins only after the resulting immutable READY capture is
available. It does not hide or combine that live action with model execution or
enrollment.
