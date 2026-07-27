# Portfolio Calculation Internal API Contract v1

## Status

This document defines the next Java-to-Python boundary. It does not activate a
portfolio calculation endpoint. No current scenario may leave `DRAFT` until
Python implements this contract and shared compatibility tests pass.

## Ownership

Spring Boot owns users, account state, constraints, scenario lifecycle,
portfolio-specific results, and human decisions. It resolves authorization,
freezes complete inputs, and persists the returned immutable result.

Python owns deterministic portfolio calculations. It may read only the
de-identified request supplied through this contract and must not read or write
`app.*`. The calculation must not modify screening scores, authorize execution,
or determine a human decision.

## Request

The reserved operation is:

```http
POST /internal/v1/portfolio-calculations
Idempotency-Key: <scenario-id-and-input-hash>
Content-Type: application/json
```

The request includes:

- Contract and scenario identifiers
- Scenario type, as-of time, USD base currency, and new money
- Frozen account cash, positions, and account liabilities
- Explicitly included user-level liabilities
- The resolved tightening constraint set
- Per-security rebalancing permissions
- Screening-run and market-data snapshot references

The request does not include names, email addresses, authentication subjects,
free-form private notes, or other personally identifying fields.

Decimal values are encoded as JSON strings. Timestamps are UTC RFC 3339.
Security identifiers are stable analytics public identifiers, not tickers.

## Scenario Rules

- `NEW_MONEY` must reject any result that decreases an existing position.
- `CONSTRAINED_REBALANCING` must enforce every frozen per-security permission.
- `TARGET_PORTFOLIO` may calculate a theoretical constrained target but must
  label every transaction as simulated.
- All scenario types evaluate the complete supplied portfolio.
- Missing FX or required market data produces `INCOMPLETE` valuation. It must
  not silently substitute a value.
- A hard constraint violation must be explicit and must not be hidden by a
  score or model inference.

## Lifecycle and Result

The future lifecycle is `PENDING -> RUNNING -> SUCCEEDED | FAILED`. The same
idempotency key and canonical input return the same calculation. Reuse with a
different input returns `409`.

A successful result contains target positions, simulated transactions,
constraint violations, valuation status, constraint status, result hash, and
completion time. Java validates the result against the frozen request before
persisting it in `app.portfolio_scenario_result`.

The result is decision support only. It contains no brokerage order, execution
credential, or human decision.

## Compatibility Artifact

[`contracts/portfolio-calculation-request-v1.example.json`](../contracts/portfolio-calculation-request-v1.example.json)
is the initial Java compatibility fixture. Python must parse the same fixture
before endpoint activation.
