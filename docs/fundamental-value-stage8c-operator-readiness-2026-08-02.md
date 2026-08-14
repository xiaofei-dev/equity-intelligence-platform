# Fundamental Value Stage 8C Operator Readiness

## Decision

Stage 8C adds a migration-free, offline operator contract around the existing
V24 company-quality forward-enrollment lane. The operator is engineering
readiness only. It does not authorize a provider call, evidence write, V24
enrollment, or evidence-label change. Real enrollment remains
`BLOCKED_BY_CURRENT_EVIDENCE_AND_CHRONOLOGY`.

The Git-safe example is a value-free `IDENTITY_BLOCKED` readiness artifact.
Its legacy `OperatorPreflight` representation is deliberately non-executable;
attempts to promote it fail with
`LEGACY_GIT_SAFE_PREFLIGHT_IS_NON_EXECUTABLE`. Runtime progression uses the
separate typed `ForwardOperatorRun` contract described below.

## Authoritative acquisition boundary

The runtime operator accepts only the authoritative Stage 8C acquisition
contract. A plan must contain exactly 271 physical requests in the frozen
order:

- 77 OpenFIGI v3 requests for 382 ISIN/CUSIP jobs;
- one SEC ticker/exchange snapshot;
- two Yahoo completed-session requests, one for each MIC;
- 191 EODHD fundamentals requests.

The plan, phase authorizations, receipt set, execution summaries, identity
adjudication, and completed-session artifact are revalidated by the acquisition
module. Retry remains zero. The identity prefix and the later fundamentals
phase have separate authorizations. A `FAILED`, unmatched `INTENT`, or
`UNKNOWN` acquisition is terminal and removes all write authority.

Production plan construction and execution re-open and validate the actual
rich 191-member population metadata manifest and mechanically project its
simplified acquisition input. A caller-supplied metadata hash is insufficient,
and execution requires exact equality with a freshly rebuilt production plan
before transport construction or network access. Production execution accepts
only the exact sealed stdlib HTTP transport type and version, with production
kind, environment proxies disabled, retry zero, and the frozen parser registry.
Arbitrary transport, wall-clock, monotonic-clock, or sleep injection is
test-only and fails closed in production.

OpenFIGI is a separately reviewed canary boundary. Exactly four physical
requests containing 18 logical jobs must complete first. Their typed outcomes,
including warnings, errors, ambiguity, and candidate cardinality, are sealed as
`CANARY_REVIEW_PENDING`; a human-controlled, content-hash-bound acceptance is
required before the remaining identity requests can be authorized. A completed
canary is never promoted automatically.

The first explicitly authorized production canary under acquisition v1.2 sent
three of the four planned OpenFIGI requests and then stopped without retry. Two
requests completed, the third retained an HTTP 200 response in a private
response-backed `FAILED` checkpoint, and the fourth request was never sent.
The provider returned the valid raw share-class ticker `BF/B` for the platform
ticker `BF-B`; the v1.2 parser incorrectly rejected the slash syntax. The
append-only
[Git-safe failure disposition](../contracts/fundamental-value-v1/stage8c-openfigi-canary-failure-v1.json)
records the exact terminal counts and hashes.
The old run remains terminal and is not reopened or reclassified.

The predecessor failure record named an earlier successor identity contract.
It remains immutable. The append-only
[successor contract addendum](../contracts/fundamental-value-v1/stage8c-openfigi-canary-successor-addendum-v1.json)
binds the exact current acquisition, parser, adapter, identity-adjudication,
canary-review, canary-acceptance, checkpoint-replay, and alias-policy versions.

Acquisition v1.3 adds a versioned, request-bound OpenFIGI ticker-alias policy.
It preserves `BF/B` in the raw wire payload, normalized record, and provider
hash lineage. Comparison succeeds only when the raw ticker equals the already
bound platform ticker, or when replacing exactly one slash between nonempty
uppercase alphanumeric share-class parts with one hyphen exactly reproduces
that expected ticker. It performs no trimming, case folding, dot conversion,
multiple-slash conversion, or unbound identity creation. The projection's
top-level contract and UUID namespace remain unchanged; only the OpenFIGI wire
and primary-filter subcontracts advance. A new canary requires a new run ID,
plan, preflight, authorization, and explicit network approval.

Both ISIN and CUSIP jobs may individually map a raw provider ticker to the
same frozen platform ticker, but the paired provider identities must still
agree exactly on FIGI, share-class FIGI, composite FIGI, raw ticker, and
exchange code. A `BF/B` versus `BF-B` raw-pair disagreement is therefore a
conflict, not convergence. Canary acceptance and every later execution
boundary rebuild the full review from immutable response checkpoints and
require byte-for-byte equality with the supplied review before any subsequent
transport call. Operator record validation is structural only and never
substitutes for this checkpoint-backed I/O authority gate.

The explicitly approved v1.3 successor canary completed all four physical
requests and 18 logical jobs with retry zero, no failed transport, and no
unknown outcome. Its human review found five unique primary mappings, zero
ambiguities, thirteen provider-warning unresolved jobs, zero no-primary data
responses, and zero paired raw-provider conflicts. Every `XNAS` job was
unresolved; the `XNYS` set had five unique jobs and one unresolved job. The
`BF/B` to `BF-B` alias path succeeded for both ISIN and CUSIP and converged on
the same provider identity, so the earlier parser defect is repaired.

The canary is nevertheless rejected because complete paired identity coverage
is required. The same plan is not retried. The Git-safe
[v1.3 result](../contracts/fundamental-value-v1/stage8c-openfigi-canary-v13-result-v1.json)
binds the exact run, review, replay, and rejection hashes. The remaining
OpenFIGI requests and every later phase stay closed until a new successor
contract resolves the identifier and MIC semantics without weakening the
acceptance gate after observing provider responses.

The separately authorized v1.4 diagnostic froze ten public-identifier jobs in
two physical requests. It preserved exact operating-MIC filters only where the
available authority supported them, omitted the NASDAQ operating-MIC filter
without inventing a segment MIC, and used the distinct CINS identifier route
where required. Both requests completed once with HTTP 200, retry zero, no
failure, and no unknown transport outcome. A zero-send replay reopened the two
private checkpoints and reproduced the exact review and receipt set.

The v1.4 review produced four unique primary mappings, six ambiguous primary
mappings, and two complete convergent identifier pairs. It therefore failed
the frozen ten-job/five-pair completeness gate and was rejected as
`DIAGNOSTIC_REJECTED_GATE_NOT_MET`. The
[Git-safe v1.4 result](../contracts/fundamental-value-v1/stage8c-openfigi-diagnostic-v14-result-v1.json)
contains hashes and counts only; it contains no provider response values. The
result is diagnostic-only, does not authorize a durable identity or the
remaining OpenFIGI population, and leaves operating-MIC ownership subject to
SEC corroboration. It grants no evidence write or V24 enrollment authority.
Any broader controller authorization remains a separate authority basis and
requires another frozen exact plan; it is not inherited from this rejected
diagnostic.

The append-only v1.5 successor is a post-v1.4 method repair, not an untouched
holdout. It replaced the ambiguous unfiltered venue set with the preregistered
US-composite filter for the three affected identifier pairs. The exact
two-request, six-job plan completed once with two HTTP 200 responses, retry
zero, no failure, and no unknown transport outcome. A subsequent zero-send
replay sent no request, reopened both completed private checkpoints, and
reproduced the immutable review and acceptance hashes.

All six jobs produced one unique US-composite primary mapping and all three
identifier pairs converged, with no warning, error, ambiguity, missing primary
result, or pair conflict. The result therefore passed its frozen diagnostic
gate as `US_COMPOSITE_DIAGNOSTIC_COMPLETE_CONVERGENT`. The
[Git-safe v1.5 result](../contracts/fundamental-value-v1/stage8c-openfigi-us-composite-diagnostic-v15-result-v1.json)
contains only counts and cryptographic bindings; raw identifiers, FIGI values,
and response bodies remain outside Git in private controlled storage.

This is an engineering diagnostic pass only. It does not authorize a durable
security or listing identity, the remaining OpenFIGI population, a V22 write,
a V24 enrollment, an outcome read, or an evidence-label upgrade. A US
composite identity is not proof of the operating MIC. The next identity gate
requires independent SEC operating-MIC corroboration, an exact inventory of
the target database identities, a forward-projection-v2 contract, and a V25
identity-authority ledger. All four are required before a governed write. The
old projection v1 path is not authorized.

The old operator-local 191-call provider representation remains parseable only
inside the blocked Git-safe fixture. It cannot execute and cannot substitute
for the 271-request acquisition plan.

## Receipt-to-projection binding

The operator does not infer a completed session from a date, local schedule,
wall clock, or arbitrary hash. Every accepted identity and session projection
must bind an exact acquisition receipt:

- acquisition plan hash;
- request identity and request-content hash;
- immutable journal/checkpoint hash;
- response-content hash;
- terminal `COMPLETED` state.

A trusted injected `ProjectionAuthorityVerifier` must replay the underlying
journal/checkpoint and validate the receipt chronology. OpenFIGI and SEC
projection evidence are matched to their exact physical request and semantic
receipt. MIC-specific completed-session proofs are matched to the exact Yahoo
receipt and acquisition artifact. Immediate-next-session proofs remain a
separate schedule-authority receipt and must bind their completed predecessor.
Missing exact receipt chronology or a trusted verifier stops progression; the
operator does not synthesize it.

The first 80 identity/session requests are verified through the concrete
acquisition-prefix authority before fundamentals can be authorized. After all
271 requests complete, the operator reconstructs the full acquisition
authority and requires the stable prefix receipt scope to remain identical.
OpenFIGI jobs, SEC lineage, Yahoo sessions, and EODHD raw manifests are decoded
through the projection module's typed acquisition decoders and compared to the
persisted projection objects; caller-created semantic receipts cannot replace
those decoders.

OpenFIGI is intentionally bound at two levels. The physical batch request
identity and journal/checkpoint hash come from the acquisition receipt, while
the request and response hashes are recomputed for the exact individual job
inside that batch. The operator also replays the job identifier kind/value,
ticker, MIC, and accepted FIGI tuple against the typed acquisition artifact.
It never equates a five-job physical batch hash with an individual OpenFIGI
job hash.

## Provider-normalized parent boundary

V24 provider-normalized parents are admitted only through an exact
receipt-backed `ProviderRawManifest`. The raw manifest must bind the EODHD
request, payload hash, provider/schema/source revision, private storage
reference, and effective/available/retrieved/ingested chronology. The
`NormalizedParentProjection` must then exact-cross-bind that raw manifest.

The operator requires a deterministic normalized-parent set:

- at least 100 members;
- exactly four `INCOME_TAX` and four `PRETAX_INCOME` parents for each usable
  member;
- the same four period ends for both fields;
- one exact EODHD request/receipt/raw manifest per member;
- unique normalized-parent identities and normalized-record hashes.

No empty parent set, neutral substitution, or arbitrary content hash can reach
evidence ingestion or a V24 dry run.

## Projection and V24 replay

Evidence ingestion binds all of the following in one immutable proof:

- authoritative acquisition plan and full execution summary;
- normalized-parent set hash and count;
- exact projection foundation and enrollment-projection request;
- exact V22/V24 projection readback result.

The readback is not accepted as a caller-supplied result object. The operator
requires the exact `ProjectionPersistenceCoordinatorV1`, invokes its
read-only `readback_exact` path for the bound foundation, and requires the
recomputed `EXACT_REPLAY` result to equal the supplied result byte-for-byte.
An `INSERTED_AND_VERIFIED` result must first be followed by this independent
durable readback. Missing objects, a fabricated hash, a weak adapter, or a
different checked-object cardinality stops evidence ingestion.

The projection foundation must contain the same 191-member identity manifest,
the same two completed sessions, the same two planned entries, and exactly the
receipt-backed raw manifests and normalized parents held by the operator.
The full-chain test uses the projection module's sealed test-only schedule
registry. No accepted production next-session registry exists, so production
planned-entry authority and real enrollment remain blocked.

For a dry run, the operator calls the accepted
`build_enrollment_candidate` function with an injected typed V22 selected-
evidence reader and trusted projection verifier. The supplied V24 candidate
must equal that recomputed candidate exactly. Its durable member set,
normalized-parent set, enrollment ID, root content hash, usable-member count,
and repository readback hash are sealed. Enrollment requires a separately
authorized repository write followed by exact typed readback; a different ID,
different object, partial readback, or conflicting replay fails closed.

## State and authorization model

The admitted progression is:

1. `IDENTITY_BLOCKED`
2. `ACQUISITION_PLAN_SEALED`
3. `CANARY_FETCH_AUTHORIZED`
4. `CANARY_REVIEW_PENDING`
5. `CANARY_ACCEPTED`
6. `IDENTITY_FETCH_AUTHORIZED`
7. `IDENTITY_SEALED`
8. `COMPLETED_SESSION_EVIDENCE_SEALED`
9. `FUNDAMENTALS_FETCH_AUTHORIZED`
10. `CHECKPOINTS_VALIDATED`
11. `EVIDENCE_WRITE_AUTHORIZED`
12. `EVIDENCE_INGESTED`
13. `DRY_RUN_PASSED`
14. `ENROLLMENT_WRITE_AUTHORIZED`
15. `ENROLLED`

Network identity fetch, network fundamentals fetch, evidence writes, and
enrollment writes are independent exact booleans. Each transition may change
only its declared fields; all accumulated plan, receipt, projection, and V24
artifacts are frozen. Later artifacts in an earlier state are rejected.
`UNKNOWN_BLOCKED` records the exact authorized acquisition state from which it
stopped and revalidates that complete prior state before accepting the stop.

## Acceptance evidence

The focused offline operator suite passes 22 tests. It covers the canonical
Git-safe fixture, the non-executable legacy boundary, exact 191-member and
122/69 MIC cardinality, the authoritative 271-request plan, authorization
timing, the explicit canary review and acceptance boundary, immutable transition
fields, content-hash drift, premature later artifacts, terminal acquisition
stops, strict normalized-parent types and replay, injected-repository-only
writes, idempotency, and conflicts. Ruff and `git diff --check` pass for the
owned operator files.

The final integration case executes the complete offline state chain from the
271-request acquisition plan through identity and completed-session seals,
191 fundamentals receipts, at least 100 exact 4+4 normalized-parent member
sets, concrete two-role projection persistence and exact readback, deterministic
V24 candidate replay, separate enrollment authorization, and exact repository
readback. It also proves that a fabricated projection preflight hash cannot
cross the evidence-ingestion boundary.

On Windows, the full-chain test harness retries the accepted execution lease's
real heartbeat only when `os.replace` encounters a transient `PermissionError`
(`WinError 5`). Production lease behavior is unchanged and remains fail-closed;
the retry wrapper exists only in the offline test.

The acquisition and projection modules retain their own focused acceptance and
combined integration gates. The final five-suite Stage 8C matrix passes 156
tests, including exact `BF/B` raw-lineage to `BF-B` platform comparison,
paired raw-ticker disagreement at both canary and identity boundaries, and a
forged/resealed review and acceptance that stops before any remainder
transport. The saved v1.2 failed response also reparsed offline under v1.3
without manufacturing a completed receipt. This Stage 8C operator result does
not claim a successful provider canary or a database integration run.

## Boundaries

The bounded v1.2 production canary made exactly three OpenFIGI POST requests
under explicit approval and stopped on the known semantic failure described
above. The successor v1.3 canary made exactly four additional approved POST
requests and was rejected after review; it did not authorize a remainder. No
PostgreSQL write, migration, Stage 1-7 artifact rewrite, V22/V23/V24 semantic
change, Java/frontend change, portfolio action, brokerage action, commit, push,
deploy, cloud action, or evidence-label promotion occurred. The model remains
`NOT_VALIDATED` and Stage 8A remains readiness-only, not enrolled.
