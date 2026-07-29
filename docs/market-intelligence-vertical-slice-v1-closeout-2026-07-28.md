# Market Intelligence Vertical Slice v1 Closeout

Date: 2026-07-28

## Decision

The local end-to-end engineering slice is implemented on the working tree based
on `main@c5e9d66`. No commit, push, cloud resource, production scheduler, or
deployment is part of this closeout.

The product path now exists:

```text
versioned 66-security universe
    -> bounded Daily Refresh worker
    -> PostgreSQL V14-V17 evidence and durable profiles
    -> FastAPI Market Intelligence contract
    -> Spring Boot /api/v1/market-intelligence/*
    -> Next.js /research
    -> sealed decision-snapshot audit handoff
```

The deterministic models, point-in-time rules, missing-data semantics, AI
boundary, and investment-safety rules were not relaxed.

## Frozen Universe

`market-intelligence-closed-test-us-v1.0.0` contains 66 durable securities:

- 48 `PRIMARY`;
- 7 `RESERVE`;
- 2 `REFERENCE_ONLY`; and
- 9 `EXCLUDED`.

The refresh scope is deliberately different from ranking eligibility:

- 57 securities are price/action refresh targets;
- 55 primary/reserve securities are fundamental refresh targets; and
- financials, REITs, resources, biotechnology, emerging growth, delisted
  securities, and special situations may remain visible while excluded from
  the general-company rank.

Stable `analytics.security.public_id` values, not ticker text alone, identify
the securities after bootstrap.

## Daily Refresh

The Python operator CLI supports:

- idempotent reference-data bootstrap;
- per-plan no-network preflight and confirmed execution;
- aggregate `workflow-preflight`; and
- one-command `workflow-run` for prices, actions, and fundamentals.

The aggregate confirmation token binds the universe, completed session,
symbols, datasets, configuration hashes, physical ceilings, and shared EODHD
budget. The workflow constructs each provider lazily and proceeds only after a
`SUCCEEDED` stage. `PARTIAL`, `FAILED`, lock contention, budget rejection,
`UNKNOWN`, and terminal journal evidence stop the workflow before another
provider is constructed.

Provider adapters have zero internal retries. The operator may authorize one
or two cumulative runner attempts. PostgreSQL advisory locking, task leases,
append-only checkpoints, immutable request journals, source hashes, freshness
events, and usage events support bounded restart and reconciliation.

FastAPI does not fetch provider data at startup. A future Render Cron Job or
AWS EventBridge task may invoke the same CLI, but no scheduler is deployed.

## Bounded Live Evidence

The approved Yahoo six-symbol canary completed with six physical wrapper calls
and zero retries. The first 57-security run stopped safely when ACN supplied an
internally inconsistent 2026-07-28 OHLC row. The invalid row was confirmed as
provider evidence, not a rounding error.

The recovery was separately bounded and approved. It retained ACN's 259 valid
completed sessions, rejected the one malformed row, and persisted both price
modes as `STALE/LATE_DATA` through 2026-07-27. No price was guessed or repaired.
ABT provided the paired successful control.

The completed terminal runs are:

- ACN plus ABT price canary
  `d26068e7-9193-4e63-9944-4ee7bd575368`: 2 Yahoo requests, 4 terminal
  partitions, `PARTIAL` only because ACN is stale;
- remaining price run `16136539-42b3-46a8-995f-ceeae05ab292`: 41 Yahoo
  requests, 82 successful partitions, `SUCCEEDED`;
- corporate-action run `0c8000db-4cfc-41d2-92f8-56a73f9b95c2`: 57
  securities, 114 EODHD requests/weight units, `SUCCEEDED`; and
- fundamental run `c2633ef9-809a-4d71-939f-5d508c987dde`: 55 securities,
  55 EODHD requests, 550 weight units, `SUCCEEDED`.

Provider retries were zero. Matching immutable transport evidence, usage
events, source records, and terminal tasks were verified. No active refresh
run, task lease, provider lock, or `UNKNOWN` request remains.

## Market Intelligence Persistence

Python now selects only a sealed `READY` data snapshot with an exact universe,
as-of time, and approved provider scope. It assembles stored evidence into:

- current market data and independent freshness domains;
- typed facts with immutable lineage;
- Objective Rating v1 status;
- one-week, one-month, and three-month Tactical Signal v2.1 views;
- the 12-month-plus long-horizon view;
- valuation state;
- ranking exclusions; and
- an AI narrative fixed to `NOT_EXECUTED` unless a separately validated AI
  workflow supplies cited evidence.

V17 stores the immutable profile, horizons, facts, lineage, exclusions,
narrative state, sealed screening runs, and results. Repeating the same
profile build or screening request preserves the same durable identity and
does not duplicate business records.

A refreshed real snapshot was accepted locally:

- data snapshot ID: `beaa9952-9852-4088-9dc3-92047824414b`;
- profile-set hash:
  `sha256:c7d50a74834c4c6b07fb8a0b1c543a0a30dc5d7af99c851deae85592a967f5e7`;
- 66 durable profiles;
- zero ranking-eligible profiles;
- 66 explicit exclusions; and
- gate status `NO_ELIGIBLE_RESULTS`.

The sealed screening run is `de13f205-f3a2-40af-a06d-a5e5c2208144`.
Its Forward handoff event hash is
`sha256:01442f9858c2af6608d833f69c9d580b563f14b970c51f01b44cdc988bed90f8`.
Repeating profile assembly, screening persistence, and decision-event
persistence preserved the same durable identities.

Real prices remained visible where persisted; unavailable facts remained
`MISSING`, `STALE`, `INVALID`, or `NOT_APPLICABLE`. Nothing was converted to
zero or a neutral score.

## Public API

Spring Boot is the browser-facing boundary and calls Python over the versioned
internal HTTP contract. It does not reimplement formulas or query
Python-owned rating tables.

Public endpoints:

- `POST /api/v1/market-intelligence/screening-runs`;
- `GET /api/v1/market-intelligence/screening-runs/{runId}`;
- `GET /api/v1/market-intelligence/screening-runs/{runId}/results`;
- `GET /api/v1/market-intelligence/profiles/{profileId}`;
- `GET /api/v1/market-intelligence/securities/{securityId}/profiles/latest`;
- `GET /api/v1/market-intelligence/securities`; and
- `GET /api/v1/market-intelligence/facets`.

The closed-test identity header is resolved by Spring Boot. Stable public error
codes hide internal response bodies. Python snake-case query fields and Java
camel-case public fields are translated explicitly.

## Research Workspace

Next.js provides:

- `/research` for security search, sector/industry/company-type filtering,
  sorting, pagination, and sealed-run results;
- `/research/securities/{securityId}` for the latest durable profile; and
- `/research/profiles/{profileId}` for an immutable profile.

The UI displays current price, trading date, provider, freshness, four horizon
states, valuation, exclusions, factors, and model versions. Deterministic
results and AI narrative are visually separate. Partial/no-eligible outcomes
are first-class states rather than errors. The browser calls Spring Boot only.

## Forward Decision-Quality Boundary

Sealing a screening run appends an idempotent decision-snapshot audit handoff
that can be consumed by the existing V11 Forward Decision-Quality workflow.
It does not fabricate an investment decision, enroll an invalid rank, or
claim future performance. Prospective outcomes remain a later, time-dependent
stage.

## Verification

The implementation was checked with:

- Python Ruff and 513 PostgreSQL-enabled analytics tests with no skips;
- a clean-clone-equivalent analytics run where local controlled-data tests
  skip and pure contract tests run: 495 passed and 12 skipped;
- an isolated PostgreSQL V17 Market Intelligence integration test;
- 36 Spring Boot client, controller, identity, contract, and error tests;
- 7 frontend contract tests, lint, and a Next.js 16.2.12 production build;
- production dependency audit with zero known production vulnerabilities;
- PostgreSQL 17 clean and V3, V12, and V16 upgrade paths through V17;
- duplicate, resume, partial-failure, and no-eligible acceptance;
- a four-service Docker smoke test covering Spring search/facets/latest profile,
  the Next.js no-eligible workspace, and an immutable security detail page;
- Gitleaks v8.30.1 full-history and clean-snapshot scanning; and
- `.env`, credential, and licensed-value boundary checks.

The new PostgreSQL regression proves that a same-date metric transition from
`MISSING` to `VALID` appends revision 2 and remains idempotent. The snapshot
assembler now binds facts to their exact observation date and keeps the latest
effective lineage item for a shared source. All verification completed with
`git diff --check` clean.

The four local images were then rebuilt from the final working tree and bound
to refreshed snapshot `beaa9952-9852-4088-9dc3-92047824414b` and screening run
`de13f205-f3a2-40af-a06d-a5e5c2208144`. FastAPI and Spring Boot were healthy;
Spring returned the sealed 0/66 no-eligible result, security search and facets;
and Next.js returned HTTP 200 for `/research` and the AAPL detail route. The
AAPL envelope remained `PARTIAL`, `NOT_ELIGIBLE`, with valid current price
evidence.

## Remaining Gates

1. Replace local closed-test identity with production authentication before a
   public deployment.
2. Provision managed PostgreSQL, a scheduled worker, private networking,
   backups, and separate credentials only under an explicit deployment task.
3. Accumulate prospective decision snapshots and matured outcomes before
   making any statement about decision quality or investment benefit.
