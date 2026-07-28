# Objective Rating v1 QC Cohort Completion Feasibility

Date: 2026-07-28
Audit policy: `objective-rating-qc-completion-routing-v1.0.0`
Status: `NOT_FEASIBLE_OFFLINE_UNDER_CURRENT_ACCEPTED_CONTRACTS`

## Outcome

The accepted v1.5 factor manifest and all 55 controlled factor snapshots were
hash verified. Seven securities are current-QC input-ready. The frozen minimum
cohort remains 20, so 13 additional securities are required.

The remaining 48 securities were evaluated without any provider request,
supplement, score, or threshold change. None can be upgraded to QC input-ready
using only already-approved evidence and derivations currently present in the
repository.

This is not a claim that completion is impossible. It means that 13 additional
ready securities cannot be honestly demonstrated from the existing accepted
offline contracts. Bounded provider confirmation, additional evidence, or an
Algorithm methodology ruling is required first.

UQ historical PIT FCF-yield history is outside this current-QC audit and did
not count as a blocker.

## Verified source chain

- v1.5 manifest:
  `docs/generated/objective-rating-v1-current-factor-input-manifest-v1-5.json`
- v1.5 artifact content hash:
  `FDB6554260A08FB83D36C13E880B004AB81B2D80653F679DC11BEF144A7B3C32`
- controlled v1.5 snapshots verified: 55
- SEC v4 timelines verified for the 48 not-ready securities: 48
- existing EODHD Fundamentals response hashes verified for candidate-field
  presence
- existing Yahoo cross-provider evidence reused only as immutable hash
  metadata

No numeric provider value appears in the Git-safe feasibility artifact.

## Factor blocker coverage

| QC factor | Not-ready securities |
|---|---:|
| Interest coverage | 48 |
| FCF margin | 42 |
| Cash conversion | 42 |
| Margin quality | 42 |
| Valuation guardrail raw inputs | 42 |
| FCF per diluted share growth | 41 |
| ROIC | 40 |
| Diluted EPS growth | 39 |
| Dilution | 37 |
| Stability | 12 |

Every not-ready security still has an interest-coverage blocker:

- 45 have not received the bounded Yahoo-EODHD current-TTM confirmation used
  by the accepted seven;
- FIX, PLAB, and WDFC have an existing
  `PROVIDER_VALUE_CONFLICT`.

Across unique security/operand blockers, 420 require unavailable or
unproven current/history semantics and 201 are potential documented-current
field or bounded-confirmation routes. There are zero securities whose complete
blocker set is already fixable from accepted cached evidence.

## Blocker signatures

The 48 securities form 17 exact factor-blocker signatures. The largest group
contains 25 securities:

`ADSK, AMD, APH, BF-B, BLDR, CNC, CROX, CVS, DELL, DXCM, FLEX, FSLR, GWW,
IDXX, KDP, KO, MCHP, MCK, MLM, MO, MOS, OLED, ORCL, TGT, VMC`.

The next groups contain:

- AMCR, APTV, and NVDA;
- FTV, IFF, and PH;
- FIX, PLAB, and WDFC;
- DDOG and KVUE;
- twelve single-security signatures.

The machine-readable artifact contains the full per-security, per-factor,
per-operand matrix, exact `VALID`, `MISSING`, `INVALID`, or `NOT_APPLICABLE`
state, reason code, period IDs, accessions, evidence hashes, timeline hashes,
and resolution route. It contains no values.

## Minimum 13-security diagnostic path

This ranking orders the smallest blocker sets and penalizes an already
confirmed provider conflict more heavily than an untested bounded route. It is
a remediation queue, not an eligibility forecast.

| Rank | Symbol | Blocking factors | Unique blocking operands | Current status |
|---:|---|---:|---:|---|
| 1 | TTC | 2 | 2 | Not currently completable |
| 2 | AVGO | 3 | 4 | Not currently completable |
| 3 | HRL | 4 | 8 | Not currently completable |
| 4 | FIX | 1 | 1 | Provider conflict |
| 5 | PLAB | 1 | 1 | Provider conflict |
| 6 | WDFC | 1 | 1 | Provider conflict |
| 7 | GPC | 5 | 7 | Not currently completable |
| 8 | DOV | 7 | 7 | Not currently completable |
| 9 | BDX | 7 | 8 | Not currently completable |
| 10 | APD | 7 | 9 | Not currently completable |
| 11 | ROK | 8 | 10 | Not currently completable |
| 12 | ADSK | 9 | 14 | Not currently completable |
| 13 | AMD | 9 | 14 | Not currently completable |

TTC is the smallest unresolved non-conflict candidate, but still needs both a
current-interest evidence route and a valid three-year diluted-EPS endpoint.
AVGO additionally lacks a current net-income TTM route and both diluted-EPS
endpoints. The remaining candidates require progressively broader current,
three-year, or aligned-quarter evidence.

## Existing current-field candidates

Hash-verified EODHD caches expose current-only candidate structures among the
not-ready set:

- `Highlights.RevenueTTM`;
- `Highlights.GrossProfitTTM`;
- `Highlights.OperatingMarginTTM`; and
- `Highlights.DilutedEpsTTM`.

Field presence is not authorization. These paths may be useful only after
their semantics, cutoff treatment, and compatibility with the frozen factor
operand are accepted. They cannot supply three-year endpoints or eight-quarter
stability history by themselves.

## Implementation and methodology audit

No deterministic parser or hash defect was confirmed that would immediately
upgrade a security.

Three issues require Algorithm review:

1. Frozen v1 names diluted EPS directly, while the current assembler builds
   diluted EPS only from net income and weighted-average shares. Existing
   caches expose `DilutedEpsTTM`, but current and three-year comparability have
   not been authorized.
2. Explicit EODHD current fields for revenue, gross profit, and operating
   margin are present but are not part of the accepted factor-window source
   contract.
3. The factor-window implementation uses a 200-day freshness rule while the
   frozen quantitative specification states 150 days. The implementation is
   less strict, so this discrepancy does not explain the observed stale
   blockers, but it must be reconciled before scoring.

The audit did not change any of these rules.

## Conclusion

The current evidence supports only seven QC input-ready securities. It does
not support an honest offline path to 20, and it does not prove that 13
additional securities can be completed without new bounded evidence or a
methodology decision.

Machine-readable artifact:

`docs/generated/objective-rating-v1-qc-cohort-completion-feasibility-v1-1.json`

- artifact content hash:
  `4AEF2143F09DE937DA6F49FA9DB4D5281A916C5265C1ACD854C0D60B7973709D`
- file SHA-256:
  `C915A4633EB1A8FE5717F165E59FF483532FD9B5B00148E76870818F60E3E9D3`

The earlier `v1.json` development artifact remains immutable. `v1-1` is the
authoritative final artifact with provider-conflict-aware ranking.
