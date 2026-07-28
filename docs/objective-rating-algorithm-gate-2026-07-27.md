# Objective Rating v1: 100-Security Algorithm Scoring Gate

## Decision

The 100-security Algorithm Scoring Gate is **NOT_ACCEPTED**.

The merged provider acceptance contains 100 unique, live-confirmed `PASS`
securities. That result establishes the bounded provider test only. It does not
establish that an Objective Rating input snapshot exists or that any security
is eligible for `QC-v1.0.0` or `UQ-v1.0.0`.

All 100 securities therefore return `INSUFFICIENT_DATA` for both strategies.
No score or rank is emitted.

## Verified input

- Merged acceptance:
  `mature-company-data-gate-20260727T180044Z-2f1f1849e3a3-merged-acceptance.json`
- File SHA-256:
  `5080DA05519C2F03B603BC499698A3298C1225A4BCF4EBFF8A6961697C730475`
- Unique live-confirmed provider `PASS`: 100
- Offline status upgrades accepted: none
- Additional live requests performed by this gate: none

Each source component report is hash-verified against the merged ledger. The
reports intentionally state `rawProviderValuesIncluded: false`.

## Why scoring is blocked

Provider acceptance proves that the tested endpoint responses met the provider
gate's coverage rules. The committed reports do not contain the complete,
recomputable Objective Rating inputs:

1. Raw numeric values are absent.
2. Units and currencies are absent at the observation level.
3. Observation-level `availableAt` timestamps are absent.
4. Factor-ready historical series are absent.
5. Versioned company-type classification is absent.

The reports contain hashes and field-presence diagnostics, but a hash cannot be
used as a financial value. A report-level PIT `PASS` cannot replace the
observation-level availability records required to reproduce a rating.

## Scoring-ready snapshot contract

Integration may produce a scoring-ready snapshot only after the following
contract is satisfied.

### Snapshot envelope

| Field | Type | Rule |
|---|---|---|
| `dataSnapshotId` | string | Durable immutable identifier |
| `asOfTime` | UTC RFC 3339 timestamp | Rating cutoff |
| `sealedAt` | UTC RFC 3339 timestamp | Must be at or after `asOfTime` |
| `sealed` | boolean | Must be `true` before scoring |
| `universeVersion` | string | Exact immutable universe definition |
| `strategyVersions` | string array | Exactly the requested supported versions |
| `normalizationVersion` | string | Identifies winsorization and percentile rules |
| `companyTypeVersion` | string | Identifies classification rules |
| `securityCount` | integer | Must equal the unique security record count |
| `sourceArtifacts` | array | Hash-verified source manifest |
| `securities` | array | Factor-ready observations |
| `snapshotContentHash` | SHA-256 | Canonical snapshot payload hash |

### Source artifact

Every source artifact record requires:

- provider;
- immutable source reference;
- retrieval timestamp;
- content SHA-256;
- parser version;
- normalization version;
- redistribution status.

### Security observation

Every security record requires:

- durable security public ID and point-in-time symbol;
- sector, market-cap value, market-cap cohort, and company type;
- the version used for each classification;
- every factor required by each requested strategy;
- factor status: `VALID`, `MISSING`, `INVALID`, or `NOT_APPLICABLE`;
- a `Decimal` value serialized as a JSON string when status is `VALID`;
- explicit reason code when status is not `VALID`;
- formula version and input-observation references;
- lineage for every underlying observation.

Specialized company types must return `SPECIALIZED_MODEL_REQUIRED`; they must
not enter ordinary-company cohorts.

### Observation lineage

Every underlying observation requires:

- provider and immutable source reference;
- source content SHA-256;
- period start and end where applicable;
- filing timestamp where applicable;
- `availableAt` in UTC;
- ingestion timestamp in UTC;
- value serialized as a decimal string;
- unit and currency;
- period type;
- revision and quality status;
- accession or equivalent provider record identifier.

`availableAt` must be no later than `asOfTime`. A later filing, revision,
classification, price, or corporate action cannot alter the sealed snapshot.
Inputs with conflicting units, missing availability, or unverifiable hashes
are `INVALID` or `MISSING`; they never become zero or neutral.

### Canonical hash

The snapshot hash is SHA-256 over UTF-8 canonical JSON with:

- recursively sorted object keys;
- original array order;
- no insignificant whitespace;
- no `NaN` or infinity;
- decimal values encoded as strings;
- UTC timestamps encoded in RFC 3339 form.

The snapshot payload excludes `snapshotContentHash` itself. Replaying the same
snapshot and strategy versions must produce identical factor values, cohort
selection, scores, ranks, and result hash.

## Preserved Objective Rating rules

- `QC-v1.0.0` and `UQ-v1.0.0` weights are unchanged.
- Winsorization remains at the 5th and 95th percentiles.
- Cohort fallback remains sector × size × company type (20), sector × company
  type (30), then all mature ordinary companies (100).
- Missing required factors do not receive zero, neutral values, or redistributed
  weights.
- Provider `PASS` and algorithm score eligibility are independent states.
- No LLM participates in values, classifications, normalization, scores, or
  ranks.

## Acceptance result

| Check | Result |
|---|---|
| Merged acceptance file hash | PASS |
| 100 unique live-confirmed provider PASS records | PASS |
| Component report hash chain | PASS |
| Deterministic gate decision and artifact hash | PASS |
| Formula/version manifest preserved | PASS |
| Scoring-ready PIT snapshot | FAIL |
| QC scores/ranks | NOT_EVALUABLE |
| UQ scores/ranks | NOT_EVALUABLE |
| Cohort and distribution analysis | NOT_EVALUABLE |

The next admissible input is an offline, immutable backfill satisfying the
scoring-ready snapshot contract. Producing that backfill belongs to Integration;
this gate does not make additional provider requests.
