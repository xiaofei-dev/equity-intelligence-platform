# Unified Portfolio and Risk Context v1

## Purpose

Unified Portfolio and Risk Context v1 gives the user one read model for cash,
liabilities, security valuations, concentration, and two independent research
sleeves. It does not combine Fundamental Value and Quant Trading scores. It
does not calculate final weights or authorize orders.

## Ownership

- PostgreSQL V12 remains the source of users, identities, portfolios, account
  snapshots, liabilities, and versioned constraint policies.
- FastAPI owns the deterministic provider-neutral exposure and constraint
  calculation. It is stateless and has no access to `app.*` tables.
- Spring Boot owns the public workflow, verifies the authenticated owner,
  account-snapshot membership, V12 constraint-policy identity and values, and
  the complete analytics response before writing V28.
- Next.js reads only the Spring public API.
- V21 `CORE` and `TACTICAL` records remain an unchanged legacy lane. V28 uses
  only `LONG_TERM_CORE` and `QUANT_TRADING`.

## Immutable context

The input contract is `unified-portfolio-risk-input-v1.0.0`; the output is
`unified-portfolio-risk-result-v1.0.0`. A sealed context contains:

- one or more sealed, complete USD account snapshots, their exact security set
  and cash balance, current portfolio liabilities, and one V12
  constraint-policy version;
- cash, invested assets, liabilities, net value, cash weight, and leverage;
- every security with explicit valuation state and no missing-value
  substitution;
- sector and security concentration;
- separate Fundamental Value and Quant Trading evidence references;
- the exact four risk thresholds and deterministic reason codes; and
- a public-safe payload and content hash.

Spring rejects hidden or invented securities, cash that does not reconcile to
the selected account snapshots, missing/non-USD liabilities, future snapshots,
and thresholds that do not equal the referenced V12 policy.

The context is append-only. Child rows cannot be inserted after sealing, and
updates or deletes are rejected. A human review is a separate immutable,
idempotent record. It can acknowledge, require further review, or record no
action; it cannot create an order.

## APIs

FastAPI:

- `POST /internal/v1/portfolio-context/risk-evaluations`

Spring Boot:

- `POST /api/v1/me/portfolios/{portfolioId}/contexts`
- `GET /api/v1/me/portfolios/{portfolioId}/contexts/latest`
- `GET /api/v1/me/portfolios/{portfolioId}/contexts/{contextId}`
- `POST /api/v1/me/portfolios/{portfolioId}/contexts/{contextId}/reviews`

The browser workspace is `/portfolio`. Closed-test identity is resolved by
Spring configuration; no client-supplied user identifier is accepted.

## Safety boundary

All contexts require human review. Final-weight authority, order authority,
automatic brokerage execution, and LLM decision authority are always false.
Quant v2 remains `NOT_VALIDATED` after its unsupportive controlled replay and
cannot be marked eligible for portfolio research use. Risk thresholds are
policy controls, not expected-return claims.

The accepted local verification evidence is recorded in
[Unified Portfolio and Risk Context v1 Acceptance](unified-portfolio-risk-context-v1-acceptance-2026-08-13.md).
