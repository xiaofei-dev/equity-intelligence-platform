# Licensed Market Data Publication Policy

## Purpose

The public repository contains software, contracts, methodology, synthetic
fixtures, hashes, and value-free execution manifests. It does not publish
licensed or personal-use market-data values, reconstructed price paths, or
numeric analytics derived from those values.

This boundary is conservative. EODHD labels its personal plans for personal
use and directs commercial users to a commercial plan. The yfinance project
states that Yahoo Finance data are intended for personal use and that users
must review Yahoo's terms for rights to downloaded data. The repository does
not infer redistribution or public-display rights from API access.

## Public Git boundary

Public Git artifacts may include:

- schemas, formulas, policies, and source code;
- synthetic contract fixtures;
- provider names and endpoint capability descriptions;
- content hashes, immutable identifiers, versions, and timestamps;
- request, sample, state, and coverage counts;
- explicit `MISSING`, `STALE`, `INVALID`, `NOT_APPLICABLE`, and exclusion
  reasons;
- a reference to a content-addressed controlled result under `storage/`.

Public Git artifacts must not include:

- raw provider payloads or provider-native numeric values;
- security-level historical price or fundamental observations;
- reconstructed price paths;
- provider-derived returns, excess returns, drawdowns, excursions, hit rates,
  information coefficients, ratios, or comparable performance metrics;
- API keys, account identifiers, credentials, or private financial data.

## Controlled local boundary

Licensed inputs and their numeric derivatives belong under Git-ignored
`storage/`. A value-free manifest may bind a controlled file by:

- storage type;
- relative storage path;
- file SHA-256;
- canonical artifact hash;
- model, policy, and evidence versions;
- nonnumeric population and execution metadata.

The manifest must state that raw provider values are not included in the
manifest and that any licensed derived metrics remain in the controlled
result.

## Tests

Pure formula, policy, parsing, hashing, and contract tests must run in a clean
clone.

Tests requiring controlled local data must use the shared controlled-data
precondition helper. They must skip with an explicit reason when the local
data are absent. Missing controlled data must not be synthesized, replaced
with zero, or treated as a passing model result.

The repository includes a publication-boundary regression that fails if a
Git-safe generated artifact publishes raw provider values or exposes numeric
licensed derivatives outside a Git-ignored controlled-result reference.

## Commercial transition

Before external users can view market data or derived analytics, the product
must obtain and document the necessary provider, exchange, display, and
redistribution rights. This policy does not constitute legal advice and does
not expand any provider license.
