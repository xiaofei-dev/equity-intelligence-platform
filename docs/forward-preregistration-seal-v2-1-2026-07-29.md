# Forward DQV v2 and Benchmark v2.1 Preregistration Seal

## Decision

The first formal offline preregistration seal is complete. It was created only
after the accepted Tactical v2.2 and Long Horizon v1.1 model freezes and before
any future prospective decision snapshot.

The seal contains two ordered preregistrations:

1. `FORWARD-DQV-PREREGISTRATION-v2.0.0`, registered at
   `2026-07-30T03:12:23.237045Z`.
2. `FORWARD-BENCHMARK-PREREGISTRATION-v2.1.0`, registered at
   `2026-07-30T03:12:23.237053Z`.

Both timestamps are timezone-aware UTC values and strictly follow the two model
freeze timestamps of `2026-07-30T00:45:00Z`.

## Bound contracts

The parent preregistration binds:

- `TACTICAL-SIGNAL-v2.2.0`;
- `LONG-HORIZON-RESEARCH-v1.1.0`;
- the accepted model-validation governance, historical validation protocol,
  and purged walk-forward implementation;
- the closed 66-security universe, including all deterministic UUID5 public
  security IDs and role/exclusion states;
- point-in-time availability, independent dataset freshness, explicit missing
  states, and no neutral substitution;
- the liquidity-sensitive cost policy;
- the 5, 20, 60, 126, and 252 completed-session horizons; and
- the exact six formal benchmarks: SPY, sector, equal weight, pure momentum,
  pure value, and pure quality.

The benchmark preregistration additionally binds the v2.1 construction policy,
including construction-family versions, objective coverage thresholds,
benchmark-specific cost policy, and the parent liquidity-cost hash.

## Evidence boundaries

The parent contract freezes three distinct roles:

- `DEVELOPMENT_OBSERVED`: previously inspected evidence remains diagnostic and
  cannot be upgraded.
- `SEALED_HISTORICAL_VALIDATION`: formal eligibility requires unobserved
  outcomes, complete point-in-time evidence, and the accepted purged protocol.
- `PROSPECTIVE_FORWARD`: only decisions strictly after the completed benchmark
  preregistration may enroll, with outcomes observed only after natural
  maturity.

The earlier `beaa9952-9852-4088-9dc3-92047824414b` decision was sealed at
`2026-07-29T02:57:08.988871Z`, before either formal preregistration. The seal
therefore records `preregistrationEligible=false` and
`upgradeAllowed=false`. It remains development/operational evidence only.

## Immutable artifacts

| Artifact | Canonical content hash | File SHA-256 |
| --- | --- | --- |
| `docs/generated/forward-dqv-preregistration-v2.json` | `sha256:cb63d2600b42c9003be8a99a76de967e5921ef68440bcd3a0d6dd8934efac966` | `300CF5D7B6FCBFF5EE2A21E4E43EA4D969417586380C8AAD3DF8B2A13E328CA2` |
| `docs/generated/forward-benchmark-preregistration-v2-1.json` | `sha256:5356f9ad16ff246e4f5565daee8316a9fae56f94bc126593bd10adec7c62d5a4` | `25CC20D603476EF186C8AB6577067B3F7E0070B07A8DDAAA064CCFF9C71AF791` |
| `docs/generated/forward-preregistration-seal-v2-1.json` | `sha256:8f6c3232f9ca5f2ace25f770c447c1d3bae2b17205151dc93fcc9b30cf15e889` | `9D96F6A3FEE8B28F81A47D5CE3FE83FFCE712C5AE4C90C4A71FF8DBBC6E44553` |

The prospective universe identity-binding hash is
`sha256:ed5ce0a4a587ce8c18e24b9f9d9d4194ac21257e9fde4d10a63d4e34b3b3e42d`.
The benchmark construction policy hash is
`sha256:ee0b1de73e19b8475a056231aa6e03817ae273f40f7ca74e4f693446bc4a62df`.

## Operational boundary

The CLI is:

```powershell
.\analysis-python\.venv\Scripts\python.exe -m `
  equity_analysis.forward_validation.preregistration_seal_cli_v21 `
  --repository-root .
```

An exact replay validates and returns the existing seal. Any changed byte under
an existing immutable path is rejected as a conflict. A V16 audit payload is
constructed and hash-bound by the seal, but it is not written to PostgreSQL.

This step made zero provider requests, produced no score or outcome, wrote no
database record, and performed no commit, push, or deployment.
