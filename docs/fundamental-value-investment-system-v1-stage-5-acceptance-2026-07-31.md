# Fundamental Value Investment System v1 - Stage 5 Acceptance

Date: 2026-07-31

## Scope

Stage 5 publishes the accepted Fundamental Value assembly, deterministic core,
and V23 persistence through a versioned internal FastAPI contract and a strict
Spring Boot client/public workflow contract. It makes no provider request and
does not add frontend, validation, Forward DQV, deployment, or brokerage work.

## Accepted boundaries

- FastAPI commands contain durable V22 routing, classification-request, and
  operand-request IDs plus projection years. Caller metric values,
  provider-native fields, formula results, and unsealed JSON are rejected.
- Repository readback supplies durable identity, completed session, cutoffs,
  chronology, evidence seals, and frozen versions.
- Specialized companies, including NBN and all banks, exit before generic
  operand assembly or core execution.
- Non-usable evidence states persist and return without numeric substitution.
- Spring Boot calls the versioned internal service and owns the curated public
  workflow. It contains no Fundamental Value formula or analytics-table query.
- Nested deterministic assessments are exact-field validated before Spring
  exposes a defensive public copy. Unknown provider, raw-storage, AI,
  portfolio-action, or contract-drift fields fail closed.
- Risk cap remains a ceiling; final weights, ranking, trades, and brokerage
  authority remain absent.
- Raw commands require exact canonical UUID strings and an integral
  `projectionYears` JSON number from 3 through 10. FastAPI internal malformed
  requests map to 422; Spring public malformed requests map to 400.
- Exact missing durable references map to 404, V22/V23 durable-integrity and
  immutability conflicts map to 409, and invalid upstream success bodies map
  to sanitized 502 responses.
- `VALID` assemblies carry no reasons; non-`VALID` assemblies carry stable
  nonempty reasons. Decimal output uses the same finite ordinary base-10 text
  as Python hashes and V23 replay, and FCFF terminal-value share cannot exceed
  the frozen 0.80 maximum.

## Contracts and fixtures

- Internal command: `internal-fundamental-value-command-v1.0.0`
- Internal result: `internal-fundamental-value-result-v1.0.0`
- Public Spring path: `/api/v1/fundamental-value/decisions`
- Git-safe fixtures:
  `contracts/fundamental-value-v1/internal-command.example.json` and
  `contracts/fundamental-value-v1/internal-missing-response.example.json`, plus
  the controlled Python-generated
  `contracts/fundamental-value-v1/internal-valid-response.example.json`

The fixtures contain synthetic identifiers and no licensed values, raw
provider payloads, storage references, secrets, or portfolio instructions.

## Verification

- Focused Python route suite: 49 passed. The final Stage 1-5, dual-system, V22,
  provider-neutral, core, persistence, and route matrix passed 504 tests in
  2.87 seconds.
- Focused Spring client/service/controller/contract/architecture suite:
  28 passed offline: 6 client, 1 architecture, 3 contract, 7 controller, and
  11 service tests. This includes strict ingress, routing, defensive-copy,
  hash replay, and the exact 0.80 FCFF terminal-value-share ceiling.
- A cross-language numeric audit found no further exposed-bound drift: method
  identity/cardinality and order, ordered ranges, score domains, projection
  horizon, claim/risk-cap matrix, and condition cardinalities are checked.
  The eight thesis, counter-thesis, and invalidation conditions bind their
  exact thresholds and inclusive/strict comparison semantics. Method weights
  are not accepted or emitted on this wire and remain owned by the Python core.
- Disposable PostgreSQL 17 V1 through V23 typed suite, including ID-only
  FastAPI mature-MISSING and NBN specialized POST/GET paths, passed all six
  tests twice sequentially on the same database: 6 passed in 6.41 seconds,
  then 6 passed in 5.82 seconds. Stable TEST_ONLY selector,
  routing, and assembly revisions append truthfully without weakening V22 or
  production versions; the exact container was removed.
- Python source/test syntax compilation, JSON parsing, secret scan, license
  scope, Ruff, and `git diff --check` passed.
- The complete offline Spring suite passed 95 tests across 21 suites. No SQL
  changed during the final Stage 5 hardening, so the independently accepted
  Stage 4 migration/upgrade/refusal matrix remains unchanged; the V1-to-V23
  typed route suite was freshly rerun twice as recorded above.

Fixture SHA-256 values are:

```text
internal-command.example.json: 211dfee8dc6171a9a104991eccfe0f25d7e930e4efeb20774107ca5445a51b17
internal-missing-response.example.json: 0bb47785f92bafc5144fbabc4de5ffacfd0c16317597ddea4dd18c463c781ccb
internal-valid-response.example.json: 384bd345f95b7be54e04868221669f7fa4718955f968775989ee556018b7ef73
```

## Honest accepted status

Stage 5 demonstrates offline engineering API readiness, not investment
validation. No real mature-company usable assessment exists because approved
canonical evidence does not yet supply the complete operand contract. Model
evidence remains `NOT_VALIDATED`. Historical validation, prospective Forward
DQV, frontend work, provider access, deployment, and any investment action are
outside this stage.

Stage 5 is master-controller accepted. This acceptance authorizes no later
stage and does not change the remaining product-data or validation blockers.
