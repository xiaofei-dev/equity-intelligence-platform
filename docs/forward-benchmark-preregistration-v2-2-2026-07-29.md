# Forward Benchmark Preregistration v2.2

## Decision

Forward benchmark v2.2 is registered as a pre-outcome feasibility correction.
It replaces the infeasible dependency of the pure value and pure quality
benchmark families on formal Objective Rating scores with two simple,
mechanical, provider-field rules. It does not change the evaluated 66-security
population, the cost or liquidity policy, price requirements, missing-data
semantics, or any Tactical, Long Horizon, Objective, or PIT formula.

The rules were frozen at `2026-07-30T03:55:37.171620Z` and registered and
sealed at `2026-07-30T03:55:37.171621Z`. Both timestamps are strictly later
than the predecessor v2.1 seal at `2026-07-30T03:12:23.237053Z`.

The registered state is `DATA_PENDING`. Benchmark construction is not
authorized yet.

## Candidate rules

`PURE_VALUE` uses:

```text
Highlights.EBITDA / Valuation.EnterpriseValue
```

Enterprise value must be strictly positive. Negative EBITDA remains a valid
negative yield and is not coerced to zero.

`PURE_QUALITY` uses:

```text
Highlights.GrossProfitTTM / Highlights.RevenueTTM
```

Revenue must be strictly positive. Negative gross profit remains valid and is
not coerced to zero.

Both rules require:

- a `VALID` status for both operands;
- the same unit, currency, cutoff, and source-response hash;
- controlled evidence IDs and period IDs;
- a sealed current-snapshot source revision with response-content, schema,
  parser, normalization, availability, and ingestion bindings; and
- explicit exclusion of missing, stale, invalid, or conflicting inputs.

The revision policy authorizes only the sealed observed current revision.
Future provider changes create a new source record. It makes no historical PIT,
publication-history, or immutable-provider-revision claim.

## Coverage and deterministic selection

The denominator remains the 55 included members of the frozen 66-security
population. At least 44 of 55 members must be `VALID` before either pure
benchmark may be constructed.

Only `VALID` candidates are ranked. The selected count is:

```text
ceiling(valid candidate count * 0.20)
```

Therefore 44 valid candidates select 9 and 55 valid candidates select 11.
Scores sort descending, with `publicSecurityId` ascending as the deterministic
tie-break. Missing, stale, invalid, and conflicting members are excluded from
ranking but still count against the 44-of-55 coverage gate. There is no
winsorization, interpolation, neutral substitution, or Objective score
dependency.

The existing hash-verified cache is diagnostic only. It currently supports 42
of 55 members for each rule, or 76.36%, below the required 44. The exact 13
missing members are:

`AAPL`, `CAT`, `ACN`, `COST`, `PEP`, `JNJ`, `ABT`, `MDT`, `SYK`, `TMO`,
`NEE`, `EXPO`, and `CALM`.

No score, rank, selected portfolio, or result was generated.

## External benchmark reference universe

External price references are separated from the evaluated population:

- market: `SPY`;
- sectors: `XLC`, `XLY`, `XLP`, `XLE`, `XLF`, `XLV`, `XLI`, `XLK`, `XLB`,
  `XLRE`, and `XLU`.

`SPY` and `XLK` reuse their existing frozen 66-universe
`publicSecurityId`. Only the ten genuinely new sector ETFs receive stable IDs
from the v2.2 external-reference namespace. All 12 IDs are unique. This
reference universe does not change the 66-security identity-binding hash or
any evaluated role.

## Data preflight

The offline preflight covers all 55 included securities at the EODHD
Fundamentals endpoint:

- endpoint-attempt ceiling: 55;
- configured-weight ceiling: 550;
- retries: 0;
- network execution authorized: false.

Execution must stop on authentication, entitlement, rate-limit, schema or
semantic drift, journal or lease inconsistency, universe or policy hash
change, or any ceiling breach. A later separately authorized refresh must
produce post-freeze evidence before construction may begin.

## Evidence boundary

The v2.2 seal binds the v2.0 parent preregistration, the v2.1 benchmark
preregistration and seal, the unchanged 66-security identity binding, the new
candidate policy, the external reference universe, and the data preflight.

The earlier `beaa9952-9852-4088-9dc3-92047824414b` decision and every prior
decision or result remain ineligible for upgrade. The v2.2 seal records both
legacy-decision and legacy-result upgrade as false. Only a decision strictly
after the v2.2 seal may enter a future prospective process.

The existing v2.1 readiness controller requires an explicit v2.2 adapter. No
existing readiness result is silently reclassified.

## Immutable artifacts

| Artifact | Canonical content hash | File SHA-256 |
| --- | --- | --- |
| `docs/generated/forward-benchmark-v2-2-feasibility.json` | `sha256:f606c80e2ca1d6d0ecd62c2ea41ddd680de43d7267d50fc7184f60a14e7f9812` | `20FE891395400085BB318AD2EC5B5BDCDA27B48C4A29EE4D25D10872B0C32531` |
| `docs/generated/forward-benchmark-candidate-policy-v2-2.json` | `sha256:6f03ed3c092983d691ef8f32a71384ef329528b0a69a85e84579587901ee69d8` | `3C498C8D68317E937562C894F60633F16945EB5FB6AC179F1F53131005E84975` |
| `docs/generated/forward-benchmark-external-reference-universe-v2-2.json` | `sha256:20885e4ca21345f152220430966141303b26ff7b49e9361825702471779e7a05` | `FBBB9F9DB5EAABC67291259B803196445B099F4A3E7E853FA76E2BBC80A33764` |
| `docs/generated/forward-benchmark-v2-2-data-preflight.json` | `sha256:e9492ca18e4a1c6a17025a12c6d55953199d33313451943a86c7344f66e8814e` | `CDE8EE08F047BEAB1C93026E5ACB23BAC4F0F60250BE42D72A11E9D51A83BE4A` |
| `docs/generated/forward-benchmark-preregistration-v2-2.json` | `sha256:cbeaa8e2fbb524a2e16084e80c0e52a47948e4ec208fa20ec37864a7ed2b5444` | `8E96142E6D876A6681209ECF68A3232115B983A6D51F31A73041A346D9D43987` |
| `docs/generated/forward-preregistration-seal-v2-2.json` | `sha256:ed3e796290c3509c94429b7273346612c40f2b4db4b94889e0db7d583c7c8e0d` | `B97B91B2C3F063EAE4FF6F23A6F4DB6A2C8130D4AB3725B861D911DB697F53FC` |

An exact CLI replay preserved every file hash. This work performed no provider
request, benchmark construction, deterministic scoring, outcome observation,
database write, commit, push, or deployment.
