# User and Portfolio Data Model

## Purpose

This model provides future-safe multi-user ownership while initially serving
two closed-test identities. Spring Boot owns all user-facing state. The Python
analytics service may calculate portfolio scenarios through a versioned HTTP
contract, but it must not write to `app.*`.

The first release does not implement login, brokerage connectivity, tax
calculation, automatic execution, or a complete transaction ledger.

## Product Model

An application user is separate from an authentication identity. A user may
eventually have several identities from different issuers. During closed
testing, a trusted external subject header is resolved through a `LOCAL_TEST`
identity. Client-supplied user identifiers are never treated as authorization.

A user may own several real, simulated, or retirement accounts. Account
history is represented by immutable point-in-time snapshots containing cash,
positions, and account liabilities. Positions preserve quantity, average cost,
and original ISO 4217 currency. Portfolio valuation uses USD as the initial
base currency and reports incomplete valuation when required FX data is
missing.

An aggregate portfolio is a named, explicit set of accounts. The same account
may be included in several portfolios but is counted only once within one
portfolio. User-level liabilities are included only through explicit portfolio
membership.

Investment intent and expected horizon remain separate. Versioned investment
profiles contain goals, risk tolerance, investment approach, liquidity needs,
sector preferences, and exclusions. Sector rules identify a taxonomy and
taxonomy version rather than relying on display text.

## Constraints

Constraint policies may be defined at user, portfolio, and account levels.
More specific policies may only tighten inherited limits. A scenario freezes
the fully resolved constraints and the source policy versions used to resolve
them.

The initial constraints cover:

- Maximum position count
- Maximum position weight
- Maximum sector weight
- Minimum cash weight
- Maximum leverage ratio
- Maximum speculative sleeve weight
- Sector-specific caps and exclusions

Initial closed-test proposals are 20 positions, 10 percent per position,
25 percent per sector, 5 percent minimum cash, zero leverage, and 5 percent in
the speculative sleeve. They are editable test configuration, not universal
investment advice.

## Portfolio Scenarios

Every scenario evaluates the complete selected portfolio:

- `NEW_MONEY` locks existing holdings and allocates only new cash.
- `CONSTRAINED_REBALANCING` follows per-position `LOCKED`, `BUY_ONLY`,
  `SELL_ONLY`, or `BUY_AND_SELL` permissions and optional change limits.
- `TARGET_PORTFOLIO` shows a theoretical portfolio subject to hard risk
  constraints. It does not grant execution authority.

Scenario inputs and completed results are immutable. Results contain simulated
transactions only. The user remains responsible for every real-world action.

## Historical State and Decisions

The latest sealed account snapshot represents current state. Earlier snapshots
remain immutable. A later transaction-ledger feature may produce the same
snapshot contract without changing portfolio APIs.

An investment decision freezes the portfolio snapshot, scenario result,
resolved constraints, analytics references, conclusion, rationale, thesis,
counterevidence, and invalidation conditions. Corrections create a new decision
that supersedes the earlier record.

## Isolation and Audit

Every user-owned aggregate carries `user_id`, and database relationships
preserve that owner across child records. Public APIs are rooted at
`/api/v1/me`; resource ownership is derived from the resolved identity.
Resources outside the current user boundary return the same not-found response
as missing resources.

Audit events are append-only and contain the resolved user, actor identity,
correlation identifier, action, entity reference, outcome, and content hashes.
Tokens, credentials, and private source documents must not be copied into the
audit trail.

Application-layer authorization, owner-preserving foreign keys, and isolation
tests protect the closed-test release. PostgreSQL row-level security is
deferred until authenticated database session context can be set reliably.

## Schema Ownership

`app.*` owns users, identities, profiles, accounts, snapshots, holdings,
liabilities, aggregate portfolios, constraints, portfolio-specific scenarios,
human decisions, and audit events.

`analytics.*` owns public security identity, market and fundamental
observations, reusable screening results, data snapshots, and general analytics
artifacts. Application position rows store the stable analytics security public
identifier without granting Python any access to user-owned tables.
