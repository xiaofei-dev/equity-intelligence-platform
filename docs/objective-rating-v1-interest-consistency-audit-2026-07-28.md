# Objective Rating v1 SEC Interest Consistency Audit

Date: 2026-07-28

## Scope

This strictly offline audit evaluated only these ten securities:

`AMAT, CIEN, COO, CSCO, DHR, FAST, FIX, PLAB, TSN, WDFC`.

The source factor manifest proves that each security has every current QC input
except `interest_coverage`. The audit made no SEC or EODHD request, calculated
no factor or score, and changed no Objective Rating v1 formula, weight, cohort,
cutoff, or missing-data rule.

## Source Verification

The audit verified:

- the v3 current-snapshot supplement manifest and all 216 controlled payloads;
- the v1.4 current factor-input manifest and all 55 controlled payloads;
- the exact ten-security interest-only candidate set;
- every referenced payload content hash and symbol identity.

The source manifest hashes are recorded in the machine-readable audit.
Existing manifests and controlled payloads were not modified.

## Policy

Policy version: `sec-issuer-interest-consistency-v1.0.0`.

The policy:

- prefers consolidated, dimension-free `us-gaap:InterestExpense`;
- spells the conditional taxonomy concept
  `us-gaap:InterestExpenseNonoperating`;
- permits a concept transition only when economic scope, statement role, unit,
  sign convention, complete period coverage, issuer disclosure continuity,
  and cutoff eligibility are all proven;
- never treats `InterestExpenseDebt` or
  `InterestExpenseNonoperating` as total gross interest automatically;
- continues to reject `InterestAndDebtExpense`, net-interest concepts, and
  capitalized interest;
- does not use an old annual fact to fill a current quarter; and
- keeps an unproven value missing.

Equal values in overlapping comparative periods are useful consistency
evidence, but do not by themselves prove equal economic scope.

## Results

| Symbol | Status | Recent selected facts | Transition evidence | Blocking evidence |
|---|---|---:|---|---|
| AMAT | PARTIAL | 12 | 9 equal overlaps | Filing presentation/context and issuer scope continuity |
| CIEN | PARTIAL | 24 | 9 equal overlaps | Filing presentation/context and issuer scope continuity |
| COO | PARTIAL | 12 | 9 equal overlaps | Filing presentation/context and issuer scope continuity |
| CSCO | PARTIAL | 14 | 9 equal overlaps | Filing presentation/context and issuer scope continuity |
| DHR | PARTIAL | 12 | 4 equal of 9 overlaps | Filing presentation/context, value conflicts, and issuer scope continuity |
| FAST | PARTIAL | 12 | 9 equal overlaps | Filing presentation/context and issuer scope continuity |
| FIX | PARTIAL | 13 | 19 equal overlaps | Filing presentation/context and issuer scope continuity |
| PLAB | MISSING | 8 | No eligible current transition | No current acceptable gross-interest concept facts |
| TSN | PARTIAL | 12 | 3 equal overlaps | Filing presentation/context and issuer scope continuity |
| WDFC | PARTIAL | 14 | 9 equal overlaps | Filing presentation/context and issuer scope continuity |

Across the six most recent observed period ends per issuer, the audit retained:

- 112 `InterestExpenseNonoperating` facts;
- 3 old `InterestExpense` facts;
- 6 rejected `InterestAndDebtExpense` facts; and
- 12 rejected `InterestIncomeExpenseNonoperatingNet` facts.

Each retained evidence record includes concept, period start/end, duration
semantic, form, frame, dimensions, unit, accession, accepted/available time,
statement roles or an explicit `NOT_CACHED` state, source hash, and a
value-binding fact evidence hash. Raw SEC numeric values are not included in
the Git artifact.

## Conclusion

- PASS: 0
- PARTIAL: 9
- MISSING: 1
- newly QC input-ready: 0

No interest supplement or corrected factor-input snapshot was generated,
because no issuer passed the complete transition policy.

For the nine partial issuers, the smallest next evidence set is the official
SEC Inline-XBRL primary document, presentation linkbase, and label linkbase for
the accessions listed in the machine-readable audit, plus issuer disclosure
showing that the newer concept is complete gross interest and omits no
operating-interest component. PLAB instead lacks a current acceptable
gross-interest concept in the existing Company Facts cache.

Algorithm scoring and Forward Decision-Quality Validation remain prohibited.

## Artifact

`docs/generated/sec-issuer-interest-consistency-audit-v1-3.json`

The artifact is value-free, content-addressed, and immutable.

## Bounded Three-Issuer Evidence Canary

The approved SEC-only canary collected the frozen accession sets for AMAT,
CSCO, and FIX. It made exactly 72 physical SEC requests:

- 18 filing-index requests;
- 18 Inline-XBRL primary-document requests;
- 18 presentation-linkbase requests; and
- 18 label-linkbase requests.

The run made no EODHD, submissions, or Company Facts request, used no retry,
and stayed below the 100-request ceiling. Run ID
`20260728T051809Z-ff6c07bd66ff` completed safely and released its lease.

An offline review found that the original filing-evidence parser used the
incorrect taxonomy case `InterestExpenseNonOperating` and classified the
preferred `InterestExpense` concept as mixed interest. Parser
`sec-inline-xbrl-parser-v1.1.0` corrects those two deterministic defects.
The original live report and v1.0 filing evidence remain immutable. All 18
filings were rebuilt from the original hash-verified response journals with
zero additional requests.

The corrected evidence found:

| Symbol | Accessions | Interest evidence rows | Result |
|---|---:|---:|---|
| AMAT | 6 | 19 | PARTIAL |
| CSCO | 6 | 23 | PARTIAL |
| FIX | 6 | 22 | PARTIAL |

The presentation evidence locates the newer
`InterestExpenseNonoperating` facts on issuer statements of operations for
relevant filings. It does not prove that the concept includes every operating
and non-operating gross-interest component. The frozen accession set also does
not provide matching presentation evidence for every predecessor
`InterestExpense` fact, and the approved endpoint set did not include
calculation linkbases. Equal comparative values therefore remain consistency
evidence only; they do not prove economic-scope equivalence.

All three issuers remain `PARTIAL`, no interest supplement or corrected factor
snapshot was generated, and the newly QC input-ready count remains zero. Under
the approved stop rule, this evidence route stops here and does not expand to
the remaining issuers.

Artifacts:

- `docs/generated/sec-issuer-interest-evidence-20260728T051809Z-ff6c07bd66ff.json`
- `docs/generated/sec-issuer-interest-evidence-20260728T052922Z-0b0de73b0bb0-offline-replay.json`
- `docs/generated/sec-issuer-interest-consistency-20260728T052922Z-0b0de73b0bb0-canary.json`
