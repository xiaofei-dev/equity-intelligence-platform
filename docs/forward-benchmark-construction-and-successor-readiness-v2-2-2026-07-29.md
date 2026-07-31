# Forward Benchmark Construction and Successor Readiness v2.2

## Purpose

This implementation supplies the missing v2.2 adapter between the immutable
Forward benchmark v2.2 preregistration and a future prospective enrollment
workflow.

It has two strictly offline responsibilities:

1. construct all six benchmark evidence families when complete synchronized
   evidence is supplied; and
2. return `READY` or `BLOCKED` for the successor prospective workflow.

It cannot enroll a decision, calculate a model score or outcome, call a
provider, write PostgreSQL, or authorize trading.

The v1 and v2.1 construction and readiness contracts remain unchanged.

## Frozen inputs

The v2.2 construction contract requires exact canonical bindings to:

- Forward DQV v2 parent preregistration;
- Forward benchmark v2.2 preregistration and seal;
- the 55-security Fundamentals capture and coverage artifacts;
- the frozen v2.2 value and quality candidate construction;
- the SPY plus 11-sector-ETF external-reference universe;
- the Future Price History v2 Git-safe execution contract;
- the frozen parent liquidity-sensitive cost policy; and
- stable public security identities.

The successor controller additionally requires:

- a complete v2.2 six-family benchmark manifest;
- one immutable decision manifest strictly after the v2.2 freeze; and
- explicit V18 acceptance evidence.

The legacy `beaa9952-9852-4088-9dc3-92047824414b` snapshot is rejected and
cannot be upgraded.

## Benchmark construction

The exact required families are:

1. `SPY`;
2. `SECTOR`;
3. `EQUAL_WEIGHT`;
4. `PURE_MOMENTUM`;
5. `PURE_VALUE`; and
6. `PURE_QUALITY`.

Every available family is bound to one completed trading session, validated
total-return-adjusted price evidence, action reconciliation, decision-time
ADTV, the frozen cost policy, constituent and weight hashes, selection hashes,
and source-evidence hashes.

The first four families preserve the accepted v2.1 mechanics.

The v2.2 value and quality families use the post-freeze candidate artifact:

- at least 44 of the 55 included securities must be valid;
- only valid candidates may be ranked;
- the selected count is `ceiling(valid_count * 0.20)`;
- ties use ascending stable `publicSecurityId`; and
- each selected security must have synchronized price, action, ADTV and cost
  evidence.

The Git-safe construction manifest contains no provider prices, ADTV values,
factor values, model scores, or returns.

## Successor readiness controller

The controller only returns:

- `READY`, when every frozen hash, synchronized evidence, all six benchmark
  families, the post-freeze decision manifest, and V18 acceptance evidence
  pass; or
- `BLOCKED`, with explicit reason codes.

Malformed or mismatched immutable evidence cannot be promoted. Missing,
stale, invalid and conflicting evidence is never replaced with zero or a
neutral state.

The controller reports zero network requests, database reads, database
writes, enrollment actions, score calculations, outcome calculations and
automatic-trading authority.

## Fixture acceptance

The complete-success fixture covers:

- the unchanged 55 included stable identities;
- all 12 external reference identities;
- 253 aligned completed sessions for every required price series;
- per-security action reconciliation and decision-session ADTV;
- the exact frozen liquidity-sensitive cost policy;
- all six available benchmark families;
- 11 pure-value and 11 pure-quality members;
- deterministic order-independent hashes;
- stable-ID tie-breaking for equal momentum values;
- a 66-security decision manifest strictly after the freeze; and
- a complete V18 acceptance contract.

Separate tests cover:

- immutable artifact tampering;
- action/price/ADTV binding mismatch;
- missing completed-session price execution;
- missing six-family construction;
- missing or pre-freeze decision manifests;
- AI contamination of deterministic fields;
- incomplete family coverage;
- missing or incomplete V18 acceptance; and
- the current-repository blocked state.

## Current repository closeout

The current repository is honestly `BLOCKED`. It has accepted v2.2
Fundamentals coverage and candidate sets, but it does not yet have:

- completed-session price evidence for the evaluated and reference
  securities;
- an executed six-family v2.2 benchmark construction;
- a post-freeze decision manifest; or
- an authoritative V18 acceptance artifact.

Artifact:

- `docs/generated/forward-v2-2-successor-readiness-closeout.json`
- file SHA-256:
  `B9C198DB41798EBCF08FF71E1F1ECECC4BBD73AFF3B0917AB3D0C7521749F193`
- canonical content hash:
  `sha256:45c148f3bdb1303910cecb460da885b6544681255b50785257b97bf5ae722868`

Blocked reasons:

- `COMPLETED_SESSION_PRICE_EVIDENCE_MISSING`;
- `SIX_BENCHMARK_CONSTRUCTION_MISSING`;
- `POST_FREEZE_DECISION_MANIFEST_MISSING`; and
- `V18_ACCEPTANCE_EVIDENCE_MISSING`.

No readiness claim was fabricated from the old decision manifest or the old
pre-implementation V18 audit.
