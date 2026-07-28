# Current Project State

Last updated: 2026-07-28

This document is the authoritative current-state summary for the repository.
Historical methodology reports and generated acceptance artifacts remain
immutable evidence of the state that existed when they were produced.

## Verified Baseline

- Git baseline: `9237cc4b368727f12ad9d50985c9478c6d188746`
- Database migration level: `V17`
- Primary market: United States listed equities
- Data cadence: completed daily or end-of-day sessions
- Runtime architecture: Next.js, Spring Boot, FastAPI, and PostgreSQL
- CI run:
  [30369516000](https://github.com/xiaofei-dev/equity-intelligence-platform/actions/runs/30369516000)
- CI result: Backend, Frontend, Analytics, Database migrations, and Secret scan
  passed

The clean-clone-equivalent analytics run completed with 469 passing tests and
10 controlled-data or database-dependent skips. PostgreSQL 17 migration
acceptance passed for clean `V1 -> V17`, populated `V3 -> V17`, `V12 -> V17`,
and `V16 -> V17` paths.

## Capability Status

| Capability | Engineering state | Operational state |
| --- | --- | --- |
| Local four-service stack | Implemented and tested | Available through Docker Compose |
| Provider-neutral daily price ingestion | Implemented | Bounded manual use only |
| Daily refresh planning and persistence | Implemented through V16 | No deployed scheduler is active |
| Market Intelligence profiles | Implemented through Python and V17 | Internal API only |
| Sector, industry, and security screening | Implemented through Python and V17 | Not yet exposed through Spring Boot or the frontend |
| Objective Rating v1 | Versioned and reproducible | Limited by explicit data eligibility |
| Tactical Signal v2.1 | Versioned and reproducible | Completed-session research only |
| AI research contract | Defined and simulated | No production AI evidence pipeline is active |
| User and portfolio context | Schema and backend foundation implemented | Closed-test identity only |
| Forward Decision-Quality framework | Offline contract accepted | No matured prospective outcome set |
| Deployment | Designed | Not deployed |

Provider acceptance, formula readiness, scoring eligibility, ranking, AI
review, portfolio fit, and a human decision are separate states. A successful
provider fetch must never be interpreted as a recommendation.

## Current Data Strategy

- EODHD is the current bounded licensed source for fundamentals and other
  provider capabilities that have passed a specific acceptance gate.
- SEC EDGAR remains the authoritative filing and filing-availability source
  where the methodology requires it.
- yfinance may provide no-key daily price refreshes and bounded development
  cross-checks. Its unofficial interface and licensing terms must be reviewed
  before any public or commercial deployment.
- Twelve Data remains supported behind the provider-neutral interface but is
  not the default broad-market source.

Daily prices may be refreshed every completed session. Fundamentals, identity,
and classifications use independent freshness policies and must not be fetched
merely because a price is stale.

## Next Product Gate

The next gate is **Market Intelligence End-to-End Vertical Slice v1**:

1. activate one bounded daily refresh plan for a 50-100-security closed-test
   universe;
2. write normalized observations and freshness states to PostgreSQL;
3. build durable Market Intelligence profiles and screening results;
4. expose the versioned results through Spring Boot;
5. render a candidate list and stock-detail research view in Next.js; and
6. seal daily decision snapshots for prospective Forward Decision-Quality
   evaluation.

The vertical slice must display explicit stale, missing, invalid, excluded, and
not-applicable states. It must not activate brokerage execution or infer
missing values.

## Deliberately Inactive

- Public registration and production authentication
- Automatic brokerage execution
- LLM-determined scores, weights, or trade decisions
- Full historical point-in-time UQ claims
- Multi-market coverage
- Production scheduler and cloud deployment
- Commercial redistribution of licensed market data

## Documentation Lifecycle

- This file, `README.md`, `docs/architecture.md`, and `docs/roadmap.md` describe
  the current intended system.
- Versioned methodology documents describe frozen calculation contracts.
- Dated development logs describe completed engineering work.
- `docs/generated/` contains immutable, Git-safe evidence artifacts. Those
  artifacts are not rewritten merely to reflect a newer project state.
- Controlled provider values and raw responses remain outside Git under the
  ignored `storage/` boundary.
