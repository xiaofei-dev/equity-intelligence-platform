# Current Project State

Last updated: 2026-07-28

This document is the authoritative current-state summary for the repository.
Historical methodology reports and generated acceptance artifacts remain
immutable evidence of the state that existed when they were produced.

## Verified Baseline

- Working-tree baseline: local `main@c5e9d66`; no commit or push for the
  vertical-slice implementation
- Remote baseline before this task: `origin/main@9237cc4`
- Database migration level: `V17`
- Primary market: United States listed equities
- Data cadence: completed daily or end-of-day sessions
- Runtime architecture: Next.js, Spring Boot, FastAPI, and PostgreSQL
- CI run:
  [30369516000](https://github.com/xiaofei-dev/equity-intelligence-platform/actions/runs/30369516000)
- CI result: Backend, Frontend, Analytics, Database migrations, and Secret scan
  passed

The current task revalidated a clean-clone-equivalent analytics run, the
isolated PostgreSQL V17 Market Intelligence integration path, and PostgreSQL
17 clean `V1 -> V17`, populated `V3 -> V17`, `V12 -> V17`, and `V16 -> V17`
paths. Final counts are recorded in the development log.

## Capability Status

| Capability | Engineering state | Operational state |
| --- | --- | --- |
| Local four-service stack | Implemented and tested | Available through Docker Compose |
| Provider-neutral daily price ingestion | Implemented | Bounded manual use only |
| Daily refresh planning and persistence | Implemented through V16 with a 66-universe CLI | Manual confirmed execution; no deployed scheduler |
| Market Intelligence profiles | Implemented through Python and V17 | Published through Spring Boot closed-test API |
| Sector, industry, and security screening | Implemented through Python and V17 | Spring Boot and Next.js `/research` implemented |
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

## Current Product Gate Result

**Market Intelligence End-to-End Vertical Slice v1** is locally implemented:

1. a versioned 66-security universe and bounded Daily Refresh CLI exist;
2. normalized observations and freshness states are written to PostgreSQL;
3. durable profiles and sealed screening runs are built from `READY` snapshots;
4. Spring Boot exposes the versioned public contract;
5. Next.js renders search, filters, results, and profile detail; and
6. sealing a screen emits an idempotent Forward decision-snapshot handoff.

The bounded provider refresh is complete for the v1 scope: Yahoo prices for 57
securities, EODHD corporate actions for 57, and EODHD fundamentals for 55.
ACN's malformed 2026-07-28 Yahoo bar was rejected while 259 prior valid
sessions were retained, so its price status is explicitly `STALE/LATE_DATA`.
A new `READY` snapshot produced 66 durable profiles, zero eligible results,
and all 66 explicit exclusions. The real product result therefore remains
`PARTIAL` without implying that the provider workflow is unfinished. See the
[closeout](market-intelligence-vertical-slice-v1-closeout-2026-07-28.md).

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
