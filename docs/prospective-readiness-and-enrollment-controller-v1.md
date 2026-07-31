# Prospective Readiness and Enrollment Controller v1

## Purpose

The controller is a fail-closed, offline readiness gate for a future Forward
Decision-Quality Validation enrollment. It verifies evidence and returns either
`READY` or deterministic `BLOCKED` reasons. It does not fetch data, compute
scores, write PostgreSQL, or enroll a decision.

## Required evidence chain

Readiness requires all of the following:

1. the parent Forward DQV v2 preregistration;
2. the Benchmark v2.1 preregistration;
3. the immutable joint preregistration seal;
4. a decision strictly after the preregistration cutoff;
5. 66 stable public identities and all 57 refreshable identities;
6. reviewed dual-authority completed-session evidence;
7. exact raw HTTP transport bindings for all 57 price captures;
8. action-to-adjusted-price reconciliation;
9. validated append-only price-promotion decisions;
10. 20-completed-session ADTV observations;
11. all six Benchmark v2.1 families as `AVAILABLE`;
12. accepted PURE_VALUE and PURE_QUALITY Objective coverage audits;
13. a common completed session and consistent cutoffs across every input;
14. an immutable `READY` decision manifest; and
15. `AI=false` for every deterministic field.

Missing artifacts never receive optimistic defaults. The Objective coverage
audit is an explicit versioned input so that a later Objective implementation
can be integrated without hard-coding an assumed count.

## Mechanical rejection rules

The controller explicitly rejects:

- the legacy `beaa9952-9852-4088-9dc3-92047824414b` decision or any attempt to
  upgrade it after preregistration;
- a preflight presented as executed evidence;
- any `UNKNOWN` physical request;
- stale ACN price evidence;
- incomplete raw-body or envelope hashes;
- partial benchmark sets;
- an unavailable PURE_VALUE or PURE_QUALITY benchmark;
- mismatched completed sessions;
- fewer than 66 decision identities or fewer than 57 refreshable identities;
- AI participation in deterministic fields; and
- any broken artifact or preregistration hash chain.

## Frozen sector-benchmark contradiction

Benchmark v2.1 requires every included sector benchmark security to exist in
the same frozen universe with role `REFERENCE_ONLY`.

The current 66-security preregistration contains only two reference-only
identities: SPY and XLK. The included population covers multiple sectors.
XLK cannot represent every sector, and a mapping hash cannot substitute for
missing reference-only securities.

Therefore the current sealed preregistration cannot honestly reach six-family
`READY` status. Resolving this requires a new versioned universe and new
preregistration/benchmark seal with explicit reference-only sector benchmark
identities. The existing seal must not be silently edited or reinterpreted.

## Current result

The current repository state is `BLOCKED` because:

- the only decision is pre-preregistration;
- future price evidence is a network-disabled preflight, not execution;
- completed-session, raw transport, action, promotion, and ADTV evidence have
  not been captured;
- all six stored benchmark diagnostics are `MISSING`;
- sector benchmark mapping is structurally incomplete; and
- no accepted Objective coverage audit exists.

The offline command is:

```powershell
.\analysis-python\.venv\Scripts\python.exe -m `
  equity_analysis.forward_validation.prospective_readiness_controller_cli_v1
```

The command only reads hash-bound Git-safe artifacts and writes one immutable
Git-safe readiness result. It never enrolls.
