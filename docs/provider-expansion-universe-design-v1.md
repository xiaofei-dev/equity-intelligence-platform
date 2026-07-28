# Provider Expansion Universe and Slice Design v1

## Scope

This design defines a deterministic 400-security provider-validation universe.
It does not authorize an Objective Rating run, a full-market download, or a
change to any rating, PIT, missing-data, cohort, or provider PASS rule.

The 400-security manifest is frozen before provider outcomes are observed.
Provider failures must not cause an easier company to replace a failed company
inside the same manifest. Reserves are reported as reserves; they do not erase
failed primary observations.

## Universe composition

The target contains 400 unique primary US listings:

| Role | Count | Purpose |
|---|---:|---|
| `GENERAL_CANDIDATE` | 320 | Companies intended for the general-company Objective Rating data contract |
| `RESERVE` | 40 | Predeclared general-company candidates used to measure robustness, not to hide primary failures |
| `REFERENCE_ONLY` | 40 | Deliberately model-excluded company types used to expose selection and provider-coverage bias |

The existing 120-security universe is retained unchanged within the first 360
general-company records. The expansion adds 240 general-company records and 40
reference-only records. Historical live evidence may be reused only through the
hash-verified latest-valid-result rule.

### General-company sector quotas

| Sector | General candidates | Reserves | Total |
|---|---:|---:|---:|
| Information Technology | 45 | 6 | 51 |
| Communication Services | 25 | 3 | 28 |
| Consumer Discretionary | 50 | 6 | 56 |
| Consumer Staples | 35 | 4 | 39 |
| Health Care | 45 | 6 | 51 |
| Industrials | 65 | 8 | 73 |
| Utilities | 25 | 3 | 28 |
| Materials | 30 | 4 | 34 |
| **Total** | **320** | **40** | **360** |

Sector is frozen from the manifest's cited classification snapshot. A later
provider classification disagreement is recorded and reviewed; it does not
silently mutate the stratum.

### General-company market-cap targets

| Verified band | Count |
|---|---:|
| Mega, at least USD 200 billion | 45 |
| Large, USD 10 billion to less than USD 200 billion | 115 |
| Mid, USD 2 billion to less than USD 10 billion | 105 |
| Small, USD 500 million to less than USD 2 billion | 55 |
| **Total** | **320** |

The 40 reserves are balanced within sector and size shortfalls after the 320
general-candidate quota is frozen. Market capitalization is verified during
metadata preflight. A company that crosses a band remains in the manifest and
is reported in the realized distribution. A company below USD 500 million is
`INAPPLICABLE`; it is not promoted merely to satisfy a quota.

### Reference-only type quotas

| Company type | Count |
|---|---:|
| Bank, insurer, broker, or financial conglomerate | 10 |
| REIT or mortgage REIT | 8 |
| Energy producer, miner, or extractive resource company | 8 |
| Biotechnology or pre-commercial drug developer | 6 |
| Foreign issuer or ADR | 4 |
| Special situation, recent major restructuring, or unsuitable issuer | 4 |
| **Total** | **40** |

Reference records receive provider coverage and lineage results but can never
be counted as scoring-ready for the general-company model.

## Deterministic manifest contract

The versioned JSON manifest uses this structure:

```json
{
  "schemaVersion": "provider-expansion-universe-v1.0.0",
  "universeVersion": "provider-expansion-us-400-v1.0.0",
  "frozenAt": "ISO-8601 timestamp",
  "selectionAsOf": "YYYY-MM-DD",
  "sourceReferences": [
    {
      "category": "constituent-and-classification-snapshot",
      "reference": "sanitized immutable reference",
      "sha256": "uppercase SHA-256"
    }
  ],
  "quotaPolicy": {
    "targetCount": 400,
    "minimumGeneralCompanyCount": 300,
    "sectorTargets": {},
    "marketCapTargets": {},
    "referenceTypeTargets": {}
  },
  "securities": [
    {
      "ordinal": 1,
      "symbol": "AAPL",
      "providerSymbol": "AAPL.US",
      "securityIdentity": "stable manifest identity",
      "sector": "Information Technology",
      "candidateRole": "GENERAL_CANDIDATE",
      "companyType": "GENERAL_COMPANY",
      "targetMarketCapBand": "MEGA",
      "selectionReasonCode": "STRATIFIED_EXISTING_BASELINE",
      "sourceUniverseVersion": "mature-company-data-gate-us-v3.0.0"
    }
  ],
  "contentHash": "canonical manifest SHA-256"
}
```

Required validation rejects duplicate symbols, duplicate stable identities,
unknown roles/types/sectors/bands, quota mismatches, missing source hashes,
non-US primary listings in a general-company role, and a manifest whose
canonical hash does not match.

Slice assignment is computed before live execution with a deterministic
stratified round-robin:

1. Partition records by role, sector or reference type, and target market-cap
   band.
2. Sort every partition by symbol.
3. Visit partitions in the fixed quota-table order and place each next record
   into the slice with the lowest count for that partition's sector/type, then
   the lowest total count, then the lowest slice number.
4. Sort records inside each slice by role, sector/type, band, and symbol and
   assign the final ordinal.

The manifest persists `sliceId` and `sliceOrdinal`, and validation recomputes
both. This prevents a daily quota stop from leaving only large-cap or technology
securities validated and ensures a resumed execution cannot reshuffle slices.

## Selection and exclusion rules

Candidates are selected from a frozen, cited constituent/classification
snapshot, then reviewed using only facts available at `selectionAsOf`.
Selection must not use provider-gate PASS outcomes.

`GENERAL_CANDIDATE` and `RESERVE` require:

- A US primary common-equity listing and unambiguous durable identity.
- A non-financial, non-REIT, non-extractive, non-biotechnology general-company
  classification.
- A mature operating history compatible with the frozen data lookback.
- A target capitalization of at least USD 500 million at selection time.

The following receive `REFERENCE_ONLY`, not general-company eligibility:

- Financial companies, REITs, extractive/resource companies, biotechnology,
  unsuitable foreign instruments, and special situations.

Funds, ETFs, SPACs, shells, preferred shares, warrants, duplicate share classes,
and unresolved identities are `EXCLUDED` before live execution. Excluded
records remain in a separate value-free exclusion ledger and consume no
provider calls.

## Slice execution and recovery

There are twenty immutable 20-security, cross-sector slices. Every slice has:

- A unique run ID and exclusive-create report and diagnostic paths.
- The manifest hash and exact ordered symbol list.
- A cross-process lock.
- An explicit live confirmation phrase.
- Dashboard counter before and after execution.
- Endpoint attempts, retries, configured local weights, provisional billing,
  and observed dashboard delta recorded separately.
- A terminal state of `COMPLETED`, `STOPPED_BUDGET`, or `FAILED`; a failed slice
  is never automatically retried.

Only a new explicitly approved recovery run may supersede individual results.
It references the original slice and preserves both hashes. Offline replay may
verify persistence idempotency but cannot upgrade a provider status.

## Per-slice and daily budgets

The observed provisional one-pass cost is 23 provider-billed calls per
security. The configured local model remains 14 weighted calls per security.
Endpoint-level billing remains `NOT_RECONCILED`.

For each 20-security first-pass slice:

| Measure | Ceiling |
|---|---:|
| EODHD physical HTTP attempts | 100 |
| SEC physical HTTP attempts | 60 |
| Total physical HTTP attempts | 160 |
| Configured local EODHD weights | 280 |
| Provisional provider billing | 460 |
| Provider-billed safety ceiling at 1.5x | 690 |

Across 400 securities, the planned first pass is 9,200 provisional calls and a
13,800-call safety budget. At most five securities across the complete universe
may receive a second network fetch, adding 115 provisional calls and a
173-call safety budget. All other idempotency checks replay immutable normalized
payloads without provider requests. The total expansion safety budget is
13,973 calls.

At the last confirmed dashboard value of 15,238 out of 100,000, the nominal
remaining balance is 84,762 and the usable balance after the mandatory 20,000
reserve is 64,762. This is planning evidence only. Every live slice must use a
fresh dashboard value, and execution must refuse to start unless:

`current dashboard count + slice safety ceiling <= 80,000`.

An unexpected observed delta, an occupied lock, a duplicate process, a manifest
or budget mismatch, authentication/entitlement failure, or a report-path
collision stops execution. No later slice starts automatically.

## Aggregate and scoring-ready semantics

The final ledger uses the existing latest-valid-result rule:

- A symbol appears once.
- Only a later hash-verified immutable live report using the same frozen gate
  standard may supersede an earlier status.
- Offline evidence cannot upgrade a status.
- Reference-only and excluded records cannot count toward general-company
  scoring readiness.

`SCORING_READY` means only that the normalized input contract, PIT evidence,
lineage, hashes, and provider gate are complete for that security. It is not an
Objective Rating result and does not authorize scoring.

The aggregate reports status counts by sector, realized market-cap band,
candidate role, company type, required field, PIT match state, source run, and
billing reconciliation. The immutable handoff contains normalized data and
hashes only; provider-native licensed values and credentials are excluded.
