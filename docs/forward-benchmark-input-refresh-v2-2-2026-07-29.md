# Forward Benchmark v2.2 Input Refresh

## Decision

The single authorized post-freeze EODHD Fundamentals refresh completed for
the 55 included securities bound to the immutable Forward benchmark v2.2
preregistration.

This refresh establishes current input coverage and deterministic candidate
sets only. It does not produce model scores, benchmark returns, enrollment,
outcomes, or evidence of future performance.

## Frozen binding

- Candidate policy:
  `sha256:6f03ed3c092983d691ef8f32a71384ef329528b0a69a85e84579587901ee69d8`
- Preregistration:
  `sha256:cbeaa8e2fbb524a2e16084e80c0e52a47948e4ec208fa20ec37864a7ed2b5444`
- Seal:
  `sha256:ed3e796290c3509c94429b7273346612c40f2b4db4b94889e0db7d583c7c8e0d`
- Included population: 55 securities
- Minimum valid coverage: 44 securities
- Provider endpoint: EODHD Fundamentals
- Approved physical attempts: 55
- Configured provider weight: 550
- Retry count: zero

## Execution

The completed run is
`20260730T041722Z-02f8ddea2f6e`.

- Physical attempts: 55
- Completed responses: 55
- Failed responses: zero
- Configured weight: 550
- Retries: zero
- Normalized controlled payloads: 55
- Symbol checkpoints: 55
- Lease released: yes
- Provider request journal terminal state: `COMPLETE`

The raw provider responses, normalized numeric values, request journal, and
checkpoints remain in Git-ignored controlled storage. Git-safe artifacts
contain stable identities, statuses, source hashes, controlled-payload
hashes, and selected candidate identities, but no provider values.

An earlier sandboxed invocation
(`20260730T041703Z-7a6bcca641ef`) recorded one transport `INTENT` followed by
`FAILED/URLERROR` and an `ABORTED` run before any completed provider response.
Its exact journal remains retained. It did not produce a capture artifact and
was not used in the successful construction.

## Coverage

All 55 included securities are `VALID` under both frozen mechanical input
rules:

- Pure value: `Highlights.EBITDA / Valuation.EnterpriseValue`, with a positive
  denominator.
- Pure quality:
  `Highlights.GrossProfitTTM / Highlights.RevenueTTM`, with a positive
  denominator.

Both rules retain valid negative numerators and require same-currency,
same-cutoff, freshness, schema, identity, and hash-bound evidence. Missing,
stale, invalid, or conflicting inputs remain explicit and are never converted
to zero or a neutral value.

The 44-of-55 coverage gate therefore passes for both candidate families.

## Deterministic candidate sets

The frozen rule ranks only valid inputs, selects
`ceiling(valid_count * 0.20)`, and uses ascending `publicSecurityId` as the
tie-break. With 55 valid securities, each set contains 11 securities.

Pure value:

1. PLAB
2. CALM
3. ACN
4. CROX
5. UFPI
6. TGT
7. UPS
8. DIS
9. DUK
10. HON
11. OLED

Pure quality:

1. META
2. AVGO
3. OLED
4. NVDA
5. MSFT
6. JNJ
7. ORCL
8. MDT
9. SYK
10. CSCO
11. KO

These are benchmark candidate memberships, not buy recommendations, company
ratings, or observed performance results.

## Immutable Git-safe artifacts

1. `docs/generated/forward-benchmark-input-capture-v2-2.json`
   - File SHA-256:
     `3474C1CAE6051571816FEC76C32760EEEFE338D6C36A1215F75127F8A388EEC0`
   - Canonical content hash:
     `sha256:6421f584a5e1e8adf9e35ee88eb259982f72956dd475bc6897570e5d158b0693`
2. `docs/generated/forward-benchmark-input-coverage-v2-2.json`
   - File SHA-256:
     `81C545EC576D8B188FE94A53E260FFA2FFEEF44E5EA2DB1480CFE2C55A8F03C3`
   - Canonical content hash:
     `sha256:03ec8cfa4a923a5b2c53ce2fef68b80e5a7cad165c97f4259ec0a914411327f1`
3. `docs/generated/forward-benchmark-candidate-construction-v2-2.json`
   - File SHA-256:
     `A208F2B86D08FD17622634F1A23013F5D3B0FC201CD5D17E64D92AECA6C11DE5`
   - Canonical content hash:
     `sha256:f5c23ad459349a7aa125d0cd492094d016ae3471affc8cce560facea5da91385`

The verification routine recomputed all three canonical hashes, all 55
controlled-payload hashes, all 55 checkpoint hashes, all 55 raw response
hashes, and the completed request-journal binding.

## Remaining boundary

Full benchmark construction remains blocked on:

- synchronized completed-session price evidence;
- liquidity screening;
- transaction-cost inputs; and
- the SPY plus sector-ETF external reference price series.

No price request, database write, benchmark return calculation, prospective
enrollment, commit, push, or deployment was performed in this step.
