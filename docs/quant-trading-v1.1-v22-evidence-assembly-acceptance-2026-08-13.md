# Quant Trading v1.1 V22 Evidence Assembly Acceptance

Date: 2026-08-13

## Decision

Accept `quant-trading-v22-assembly-v1.1.0` as the provider-neutral,
fail-closed input boundary for the deterministic Quant Trading v1.1 research
signal core.

This acceptance does not validate the strategy, authorize a current portfolio
simulation, publish an API, persist a Quant decision, or permit brokerage
execution. The model evidence label remains `NOT_VALIDATED`.

## Accepted Scope

- Rehydrate exact persisted V22 selector aggregates by request ID.
- Recompute request IDs and request/result hashes and replay the deterministic
  selector.
- Read the V22 security/listing/share-class/instrument/company graph, active
  instrument type, complete ticker intervals, calendar, and completed-session
  authority through a typed read-only PostgreSQL adapter.
- Require exactly 253 ordered `TOTAL_RETURN_ADJUSTED` daily observations for
  SPY and every expected member.
- Require an exact sorted cross-sectional denominator of at least 20 durable
  security IDs.
- Preserve missing and not-applicable members as explicit empty histories in
  the denominator.
- Raise an integrity failure for invalid, stale, excluded, future, ambiguous,
  identity-mismatched, chronology-drifting, or hash-drifting selector evidence.
- Keep numeric OHLCV values out of the Git-safe assembly manifest.

## Verification

- Quant V22 assembly unit/read-adapter suite: 7 passed.
- Quant successor plus V22 selector/domain/persistence regression: 121 passed.
- Quant contract, v1/v1.1 engine, simulator, and assembly regression:
  143 passed.
- Ruff: passed.
- Canonical Git-safe contract hash:
  `sha256:fb0108137eefa55b8eabf38e6bef8ccbfe7f0e6c0d035e4a3cb3481b8e08c880`.

## Remaining Boundary

V22 does not provide a governed Quant event or lifecycle interval proof. The
accepted boundary therefore authorizes the pure v1.1 research-signal core only.
Append-only Quant decision persistence, internal/public APIs, the research UI,
current-evidence portfolio simulation, and prospective validation remain later
stages.
