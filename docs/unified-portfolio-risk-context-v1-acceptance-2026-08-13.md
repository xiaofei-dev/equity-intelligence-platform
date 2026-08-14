# Unified Portfolio and Risk Context v1 Acceptance

Date: 2026-08-13

## Result

PASS for the local engineering product slice. This acceptance does not deploy
V28, create a business portfolio context, calculate final allocation weights,
or authorize brokerage execution.

## Accepted behavior

- V12 remains authoritative for user identity, portfolios, sealed complete USD
  account snapshots, cash, liabilities, and versioned constraint policies.
- The request's security set, cash, liabilities, as-of time, and four risk
  thresholds must reconcile to the selected immutable V12 records.
- FastAPI calculates exact cash, asset, liability, leverage, position, sector,
  and sleeve exposure with explicit missing valuation state.
- Spring validates the full cross-language result identity, canonical content
  hash, positions, evidence references, thresholds, states, and authority
  fields before V28 persistence.
- V28 rejects incomplete sealing, late children, updates, deletes, duplicate
  business identities, unsafe Quant v2 research authority, and automated
  execution authority.
- Human review is separate, immutable, idempotent, and visible on the public
  read model.
- Next.js uses only the Spring public latest-context route and renders the two
  independent sleeves without score blending.

## Verification

- Python portfolio contract and FastAPI route: 10 passed; Ruff passed.
- Spring Boot complete offline suite: 156 passed.
- Next.js complete Node suite: 72 passed; ESLint passed; production build
  passed and emitted the dynamic `/portfolio` route.
- PostgreSQL 17 complete migration, upgrade, preservation, refusal, and
  acceptance matrix through V28: passed. The matrix included clean V1 to V28,
  existing upgrade paths, the unchanged populated V18 to V19 refusal, and the
  V28 representative account/portfolio/context/review graph.
- Shared Python-generated JSON fixture was accepted by Python, Java, and
  TypeScript; drift in identity, constraints, authority, or missing-value state
  was rejected.
- `git diff --check`, English-only Task 4 artifact scan, JSON parsing, local
  documentation links, and migration-runner shell syntax passed.

## Boundaries

- V21 remains unchanged and is not reinterpreted.
- Quant v2 remains `NOT_VALIDATED` and excluded from research-use authority.
- The application does not derive position market values from quantities; the
  caller must bind each valuation to accepted research evidence and V28 keeps
  its state explicit.
- No commit, push, provider request, deployment, cloud mutation, business
  database write, portfolio order, or brokerage action occurred.
