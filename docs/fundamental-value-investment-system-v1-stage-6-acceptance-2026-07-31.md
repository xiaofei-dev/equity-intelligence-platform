# Fundamental Value Investment System v1 - Stage 6 Master Acceptance

Date: 2026-07-31

## Scope

Stage 6 adds the Next.js Fundamental Value research workspace through the
master-accepted Spring public API. It also advances only the current readback
projection to `internal-fundamental-value-result-v1.1.0` so the public result
can carry durable identity and completed-session provenance. The internal
command remains v1.0, and Stage 5's v1.0 result fixtures remain immutable
historical acceptance evidence. This stage does not change Python calculations,
V22/V23 evidence or persistence semantics, provider access, historical
validation, Forward DQV, Quantitative Trading, or deployment.

## Boundary

- The browser renders a Next.js server page whose only analytics dependency is
  `/api/v1/fundamental-value/decisions/{assemblyId}` on Spring.
- Python, Spring, and Next.js each reject a returned assembly ID that differs
  from the requested assembly ID.
- Python, Spring, and TypeScript independently re-derive a usable assessment ID
  as UUIDv5 over
  `fundamental-value-assessment-persistence-v1.0.0`, the assembly ID, and the
  assessment content hash. The canonical usable fixture assessment ID is
  `ccdcaa6b-6254-5141-9aca-294a40f91292`.
- The workspace never calls FastAPI, PostgreSQL, or a provider and contains no
  valuation, aggregation, scoring, or risk-cap formula.
- Result v1.1 includes the complete durable security identity, ticker
  assignment, ticker, MIC, identity currency, and completed session. The
  Git-safe fixtures are
  `internal-missing-response-v1.1.example.json` and
  `internal-valid-response-v1.1.example.json`, whose exact SHA-256 file hashes
  are `3558c2acf468f0b88f4659787a485a077da6f523fc3048528fa0b969cd46b94d`
  and `649008649eb0b6e22895d2ad31e9323e7e810b4b2d056afe58cbaa28b5ca34b7`.
- TypeScript rejects unknown fields, coercion, noncanonical IDs, exponent or
  alternate-zero decimals, invalid state/value parity, blank nested reasons,
  hash drift, invalid cutoff grammar or chronology, frozen condition drift,
  claim/risk-cap/version drift, forbidden authority, and incompatible
  cross-language fixture shapes.
- Completed-session date cannot be later than the decision cutoff. Quality,
  resilience, conservative margin-of-safety, downside-risk, and central
  margin-of-safety condition observations bind to their exposed source fields,
  with `satisfied` recomputed from the bound observation and frozen comparison.
- `MISSING`, `STALE`, `INVALID`, `EXCLUDED`, specialized-required,
  not-applicable, and insufficient-evidence results remain visibly non-usable.
- A usable synthetic response displays ordered fair value, reference price,
  margin of safety, annualized expected return with its projection horizon,
  downside risk, quality dimensions, valuation methods, evidence conditions,
  nested reasons, durable identity/session provenance, sealed cutoffs, hashes,
  versions, claim ceiling, `NOT_VALIDATED`, and the risk-cap ceiling.
- Percent display uses arbitrary-precision decimal text and cannot overflow
  through JavaScript Number conversion.
- No AI narrative is generated or displayed. No result is described as a
  guaranteed return, final portfolio weight, trade, or brokerage action.

## Verification

```text
Python Fundamental Value contract/core/assembly/persistence/route suite: 233 passed
Python Fundamental Value internal-route suite: 51 passed
Frontend Node contract/route/presentation suite: 59 passed
Fundamental Value-focused frontend tests: 16 passed
Spring focused v1.1 suite: 71 passed, 0 failures, 0 errors, 0 skipped
Full Spring suite: 138 passed, 0 failures, 0 errors, 0 skipped
Maven: BUILD SUCCESS; Java 21; Spring Boot 4.1.0; 21.963 seconds
ESLint: passed
Next.js 16.2.12 production build: passed
Dynamic route emitted: /research/fundamental-value
git diff --check: passed
```

The 71 focused Spring results comprise 32 analytics-client cases, one
architecture case, three contract cases, eight controller cases, and 27
service cases. The final Java-only hardening adds successful service and public
GET assertions for all six durable identity UUIDs plus ticker, MIC, currency,
and completed session; ten malformed-identity cases; 14 value-drift/omission
cases covering the result contract and all six nested frozen versions; and 12
toggle/omission cases covering every root and nested authority flag, including
automatic brokerage authority.

The master runtime used the existing offline repository environment with Java
21 and Spring Boot 4.1.0. Both the 71-case focused Fundamental Value suite and
the complete 138-case Spring suite completed with zero failures, errors, or
skips. Maven reported `BUILD SUCCESS` in 21.963 seconds.

The tests decode the exact accepted Spring missing fixture and the
Python-generated valid fixture. Architecture checks prohibit internal Python,
database, provider, and alternate-data paths. Presentation checks cover
usable, missing, bank-specialized, and benchmark-not-applicable outcomes.

## Honest status

This is engineering UI readiness, not investment validation. Current approved
V22 evidence still cannot produce a real mature-company usable assessment;
the production producer registry remains empty and model evidence remains
`NOT_VALIDATED`. The valid fixture is controlled synthetic mechanics evidence.

Stage 6 is master-controller accepted as offline engineering workspace
readiness. This acceptance does not upgrade `NOT_VALIDATED`, resolve the V22
operand-coverage blocker, or authorize investment use. No provider or
financial-data network request, migration, business-database write, historical
validation, Forward DQV, Quantitative Trading blend, commit, push, deployment,
cloud resource, brokerage action, or license change occurred.
