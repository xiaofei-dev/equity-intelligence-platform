# Forward DQV Maturity Path Loader v2.2

## Purpose

The maturity path loader is the production-read boundary between a
prospectively sealed Forward Decision-Quality Validation enrollment and Gate H.
It discovers naturally due maturities and assembles only already-persisted,
hash-verified evidence. It does not fetch provider data, write database rows,
compute outcomes, or run a model.

## Accepted enrollment boundary

Only `FORWARD-DQV-ENROLLMENT-v2.1.1` is accepted. The repository reconstructs
the enrollment from V19 rows and verifies the enrollment and every maturity
schedule canonical hash before returning a due item. A v2.1.0 enrollment is
rejected; it cannot be treated as production chronology evidence.

The supported horizons are exactly 5, 20, 60, 126, and 252 completed sessions.
The 126-session result is diagnostic-only. The other four horizons remain
formal-gate eligible under their sealed schedule.

## Stored evidence

The loader reads:

- the frozen public-security identities and roles from the enrollment's
  controlled decision artifact;
- the official completed-session evidence stored in
  `analytics.analytics_audit_event`;
- latest validated `TOTAL_RETURN_ADJUSTED` price revisions from
  `analytics.daily_price_observation`;
- the corresponding action-adjustment reconciliation evidence;
- decision-time `ADTV-20-COMPLETED-SESSIONS-v1.0.0` observations;
- the exact six-family
  `FORWARD-DQV-BENCHMARK-PATH-LEDGER-v2.2.0`, when its controlled reference
  and canonical hash are atomically bound by the decision composite; and
- SPY through the same stored security-path rules after its public security ID,
  single holding, and full weight are verified from that ledger.

The controlled ledger retains exact rational weights and holding-level
notional, ADTV, and cost evidence. Gate H currently accepts only one
notional/ADTV pair for a whole benchmark. Because execution costs are
nonlinear, the loader must not collapse the holding-level liquidity evidence
into an invented aggregate. Equal-weight, pure-momentum, pure-value, and
pure-quality therefore return
`SEALED_BENCHMARK_LIQUIDITY_AGGREGATION_NOT_PROVEN` until Gate H carries
holding-level cost inputs.

The SECTOR family has multiple dated sector variants. A single global
`BenchmarkKind.SECTOR` outcome cannot represent the security-specific sector
comparison without a frozen subject-to-sector binding. It therefore returns
`SEALED_SECTOR_VARIANT_SELECTION_NOT_BOUND`; variants are never averaged,
merged, or selected implicitly. Missing ledgers remain explicitly `MISSING`,
and SPY is not substituted for another family.

## Exact-session policy

The entry timestamp must be the official 09:30 America/New_York session open.
The loader derives the exact entry-through-maturity completed-session sequence
from the accepted US market calendar and requires the last close to equal the
sealed maturity close. Every session must have official dual-authority
completion evidence and one eligible stored adjusted-price revision available
by the observation cutoff.

Natural-day fallback, forward filling, nearest-session substitution, and
implicit corporate-action adjustment are prohibited.

## Terminal states

- `READY`: all frozen security paths and all six benchmark paths are complete.
- `PARTIAL`: at least one required item is explicitly missing, stale,
  excluded, or not applicable.
- `INVALID`: at least one hash, identity, calendar, action, or semantic
  invariant is invalid.
- `NOT_DUE`: the sealed maturity session has not completed.
- `ALREADY_MATERIALIZED`: an outcome batch already exists and no explicit
  correction was requested.

Missing prices, actions, ADTV, synthetic benchmark ledgers, or frozen
population material remain explicit reason-coded states. They are never zero,
neutral, or silently dropped.

## Replay and recovery

The manual CLI uses an exclusive local lease, an immutable canonical request,
per-read hash-verified checkpoints, and an immutable completion record.
Reusing a run ID with the same request returns the exact completed assembly.
Changed request content is rejected. An interrupted run can resume verified
population, calendar, security, and benchmark reads without overwriting
checkpoints.

Outcome corrections remain append-only: an explicit correction uses the next
result version and binds its predecessor batch. This loader never writes the
correction; persistence remains the outcome repository's responsibility.

## Manual command

The safe default writes only the blocked preflight:

```powershell
cd C:\Projects\equity-intelligence-platform
$env:PYTHONPATH = "analysis-python/src"
.\analysis-python\.venv\Scripts\python.exe -m `
  equity_analysis.forward_validation.maturity_path_loader_cli_v22 `
  --observed-at 2026-07-30T22:00:00Z `
  --checkpoint-root storage/forward-dqv/maturity-loader-v2-2 `
  --output docs/generated/forward-dqv-maturity-path-loader-v2-2-preflight.json
```

`--execute-read-only` may be added only in a production-read environment with
`DATABASE_URL` configured. It reads due schedules and stored evidence and
writes controlled local assembly files. It still performs zero provider
requests, zero database writes, zero model runs, and zero outcome calculations.

## Database decision

V19 is sufficient. The due schedule is derived from the existing V18/V19
enrollment, maturity schedule, and outcome batch tables. Price, action,
calendar, and liquidity evidence use existing analytics tables. No V20
migration is justified by this read-only loader.

## Current preflight

The Git-safe preflight is `BLOCKED` because there is no real v2.1.1
enrollment, no naturally due maturity, no complete stored 66-security
price/action/ADTV path set, and no real enrollment-bound controlled benchmark
ledger. Even after a ledger is bound, synthetic Gate-H paths remain blocked
until holding-level cost inputs and the subject-specific sector mapping can be
represented without changing their semantics. This is an evidence and
contract boundary, not an implementation failure.
