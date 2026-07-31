# Prospective Enrollment Adapter v2.2

## Purpose

The prospective enrollment adapter v2.2 is the only bridge from a verified
post-freeze Forward DQV v2.2 decision to the append-only V18 outcome ledger.
It reuses `ForwardDqvOutcomeRepositoryV21` and the
`FORWARD-DQV-ENROLLMENT-v2.1.0` database contract. It does not modify V18.

The adapter is fail-closed. It prepares an enrollment candidate only when all
of the following evidence is present and canonically valid:

- the successor readiness controller is `READY` with no blockers;
- the post-freeze decision has purpose `PROSPECTIVE_DECISION`;
- the decision contains the exact 66 preregistered stable identities and
  roles;
- all six benchmark families are `AVAILABLE`;
- the successor controller, decision, benchmark, seal, completed-session and
  V18 acceptance hashes form one consistent chain;
- the V18 implementation acceptance is still valid against the current
  migration, model, and repository source hashes; and
- an explicit V18 persistence binding names the READY data snapshot,
  universe, controlled artifact reference, idempotency key, and seal time.

Contract fixtures, legacy decisions, partially available benchmarks, stale V18
acceptance, missing persistence bindings, or a non-READY controller remain
blocked.

## Population semantics

Enrollment covers the complete frozen population of 66 securities. The
adapter derives one mutually exclusive population terminal state per security:

- `ASSESSED`;
- `MISSING`;
- `STALE`;
- `INVALID`;
- `EXCLUDED`; or
- `ABSTAINED`.

Reference-only members are retained as `ABSTAINED`. Frozen excluded members
remain `EXCLUDED`. Missing or stale model inputs are never converted to
assessed or neutral values. The terminal counts must sum to 66 before an
enrollment candidate is constructed.

## Maturity schedule

The adapter constructs exactly five US completed-session maturities:

| Sessions | Evaluation role | Formal gate eligible |
| ---: | --- | --- |
| 5 | `TACTICAL_FORMAL` | yes |
| 20 | `TACTICAL_FORMAL` | yes |
| 60 | `TACTICAL_FORMAL` | yes |
| 126 | `LONG_HORIZON_INTERIM_DIAGNOSTIC` | no |
| 252 | `LONG_HORIZON_FORMAL` | yes |

The prospective entry is the next scheduled US session open after the decision
session. Each maturity timestamp is the scheduled close of the corresponding
completed session. The 126-session result is diagnostic only and cannot pass a
formal long-horizon gate.

## Persistence and idempotency

Preparation is read-only. Persistence requires:

1. a `READY_FOR_PERSISTENCE` preparation;
2. an injected repository implementing `persist_enrollment`; and
3. the explicit `execute=true` write authorization.

The real repository writes the enrollment and five maturity rows in one
transaction. The enrollment ID and request hash are deterministic. An exact
replay returns the existing enrollment, while the same idempotency key with a
different request or enrollment hash is rejected.

The tests use an in-memory fake repository to verify the atomic intent,
five-row contract, exact replay, and conflict behavior. They do not connect to
PostgreSQL.

## Repository-current status

The current checked-in preflight
`docs/generated/prospective-enrollment-adapter-v2-2-v19-preflight-v2.json`
is intentionally `BLOCKED`. The repository currently
has only the v2.2 contract fixture, whose purpose is `CONTRACT_FIXTURE`, whose
benchmark terminal states are missing, and which has no successor-controller
READY artifact or V18 persistence binding. It cannot be promoted into a real
prospective decision.

The current v2 preflight also records
`V19_CHRONOLOGY_ACCEPTANCE_INVALID`, because the old V19 acceptance does not
bind the repository-current additive source. The prior
`docs/generated/prospective-enrollment-adapter-v2-2-v19-preflight.json`
remains immutable historical evidence. It binds the earlier contract-fixture
decision-manifest hash and is not the current CLI default. The v2 successor
updates the fixture binding and records the separately documented V19
source-hash drift; it does not bypass that drift, make the adapter
enrollment-ready, or authorize a database write.

Regenerate the read-only preflight with:

```powershell
$env:PYTHONPATH = "analysis-python/src"
analysis-python/.venv/Scripts/python.exe `
  -m equity_analysis.forward_validation.prospective_enrollment_adapter_v22_cli `
  --write-blocked-preflight
```

This command performs no network request, database read, database write,
scoring, outcome calculation, enrollment, or automatic trading action.
