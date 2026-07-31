# Objective Current Replay Recovery

Date: 2026-07-29

## Purpose

This note records the recovery boundary between the accepted offline Objective
Rating v1 current-decision gate and the closed 66-security Market Intelligence
product universe.

The recovery does not change formulas, factor weights, cohort thresholds,
point-in-time rules, or explicit missing-data behavior. It performs no AI
ranking and authorizes no automatic trading.

## Accepted Evidence

- Source snapshot:
  `beaa9952-9852-4088-9dc3-92047824414b`
- Universe:
  `market-intelligence-closed-test-us-v1.0.0`
- Accepted Objective gate content hash:
  `131FD6C59A596056CB6A329FDA3BB73404CADDF2976826B2CDD211D5CB593F4B`
- Accepted gate population: 136 scored securities
- Closed-universe overlap: 32 scored `INCLUDED` securities
- Closed-universe remainder: 23 `INCLUDED` securities with
  `INSUFFICIENT_DATA`
- Non-rankable by design: 11 reference-only or excluded securities

## Zero-Network Cache Recovery

The cached Fundamentals replay validated 44 content-addressed provider
responses and wrote:

- 44 current company-profile projections;
- 44 current market-capitalization projections;
- 44 current classification projections; and
- 44 `PROVIDER_CACHE_REPLAY` audit events.

The operation made zero network requests. A second execution wrote zero new
business rows, proving idempotency.

## Corrected Replay Contract

`objective-current-gate-replay-v1.1.0` retains the full 66-member snapshot but
limits Objective coverage persistence to the 55 `INCLUDED` securities.

This is necessary because V8 requires a numeric size cohort on every coverage
row. A benchmark, ETF, specialized-model company, or excluded security must not
receive an invented cohort merely to satisfy that storage shape. V17 Market
Intelligence assembly reads immutable universe membership and preserves those
11 securities as `NOT_APPLICABLE` views with their original membership reason.

The replay version participates in the controlled ingestion batch, derived
snapshot, screening run, request hash, and manifest hash identities. Existing
v1.0 records are not changed or deleted.

## Transactional Stop and Remaining Repair

The first enriched replay stopped transactionally at AAPL with
`MISSING_MARKET_CAP_FOR_COHORT[AAPL]`. No corrected snapshot or run was
partially committed.

The following 11 `INCLUDED` securities still lack a persisted current
market-capitalization projection:

- AAPL
- ABT
- ACN
- CAT
- COST
- EXPO
- JNJ
- MDT
- NEE
- PEP
- TMO

Their existing fundamentals rows and freshness records do not by themselves
create the current profile projection introduced by the recovery writer.
The database contains `shares_outstanding` facts for all 11, but their quality
state is `NOT_VERIFIED`. Multiplying those values by a price would therefore
manufacture a valid market-cap input from an explicitly unverified operand.
That shortcut is rejected.

The bounded repair plan is:

- symbols: the exact 11-security list above;
- endpoint: EODHD Fundamentals only;
- maximum physical requests: 11;
- configured EODHD weight: 110;
- provider retries: 0;
- stop on authentication, rate-limit, payload, journal, lease, universe-hash,
  source-hash, or persistence inconsistency.

The operation is not executable until `EODHD_API_KEY` is present in the local
ignored `.env`. The key must never be copied into chat, documentation, Git, or
generated artifacts.

## Historical Non-Authoritative Evidence

Snapshot `aa266ccf-0cc5-5994-8e23-e93556707ccd` and screening run
`c3193573-3bbe-5640-97e4-670b1ffc5695` remain append-only historical evidence
of the superseded v1.0 replay. The run contains 32 quantitative, 23
insufficient-data, and 11 specialized-model coverage rows. It does not contain
the corrected supplemental profile lineage and must not be used as the final
recovery result.

## Verification

- Python Ruff: passed.
- Python suite: 541 passed, 13 environment-gated tests skipped.
- Isolated PostgreSQL 17 V1-to-V17 replay suite: 5 passed.
- The isolated test database was removed after verification.
- `git diff --check`: passed, with only local line-ending notices.
- `.env`: ignored and untracked.
- No provider request, commit, push, cloud resource, or deployment was created
  by this recovery phase.
