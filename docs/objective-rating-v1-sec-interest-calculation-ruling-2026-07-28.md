# Objective Rating v1 SEC Interest Calculation-Linkbase Ruling

Date: 2026-07-28
Methodology version: `SEC-INTEREST-CALCULATION-EVIDENCE-v1.0.0`
Parser version: `sec-interest-calculation-linkbase-parser-v1.0.0`
Policy version: `sec-interest-scope-continuity-calculation-policy-v1.0.0`

## Decision

The calculation linkbases for the 18 frozen AMAT, CSCO, and FIX
accessions are not approved for collection.

A calculation linkbase can supply structural support or positive
contradiction evidence. It cannot, by itself, prove that
`us-gaap:InterestExpenseNonoperating` represents the issuer's complete
gross interest expense or that no operating-interest component was
omitted. The bounded request could therefore preserve `PARTIAL` or produce
`REJECT`, but it has no mechanically scalable path to `PASS`. Collecting
the 18 files would not resolve the only remaining canary blocker.

This ruling does not change Objective Rating v1 formulas, weights, PIT
rules, cohorts, or missing-data semantics. Interest coverage remains
missing when complete gross interest expense is not proven.

## Authoritative semantics

XBRL 2.1 defines a calculation relationship as a
`summation-item` relationship:

- Arcrole must be
  `http://www.xbrl.org/2003/arcrole/summation-item`.
- The `from` concept is the summation parent and the `to` concept is a
  contributing child.
- The `weight` is the multiplier applied to the child. SEC filing rules
  restrict it to `1` or `-1`.
- Relationships are scoped by the calculation extended-link role.
- A calculation binds only to facts with equivalent contexts and units.
  Context equivalence includes entity, period, and dimensions.
- Arithmetic consistency applies only to facts and relationships present
  in the filing's discoverable taxonomy set.

The SEC requires calculation relationships when disclosed line items
contribute to a displayed total, but also warns that EDGAR acceptance does
not establish completeness or compliance. These facts make the linkbase
useful structural evidence, not a complete economic-scope declaration.

Official references:

- SEC EDGAR Filer Manual, Volume II, sections 6.14 and 6.15:
  <https://www.sec.gov/submit-filings/edgar-filer-manual>
- SEC sample letter on missing calculation relationships:
  <https://www.sec.gov/rules-regulations/staff-guidance/disclosure-guidance/divisionscorpfinguidancexbrl-calculation>
- XBRL 2.1, section 5.2.5:
  <https://www.xbrl.org/Specification/XBRL-2.1/REC-2003-12-31/XBRL-2.1-REC-2003-12-31%2Bcorrected-errata-2013-02-20.html>

## Strict evidence contract

For every accession, a parser must retain:

- Filing accession, form, accepted time, source URL, response hash, and
  ingestion time.
- Calculation-link extended role.
- Exact arcrole, parent concept, child concept, weight, order, priority,
  and `use`.
- The matching statement-of-operations presentation role and labels.
- The numeric facts' entity, duration start and end, unit, currency,
  dimensions, decimals, and nil state.
- The full frozen accession set and all source hashes.

The parser must not treat a standalone `_cal.xml` document as proof that
the filing's complete discoverable taxonomy set was resolved. Prohibited
or overridden arcs require effective-relationship resolution. Unsupported
arcroles must be preserved and must not be interpreted as
`summation-item`.

Cross-accession structural support requires all of the following:

1. The exact frozen accessions were processed.
2. Both concepts occur in statement-of-operations roles.
3. Any overlapping facts use the same entity, period, unit, currency,
   dimensions, and sign convention.
4. Calculation neighborhoods are evaluated within the same extended-link
   role.
5. Parent/child direction and weights are stable around the transition.
6. No network contains a broader interest total, an additional interest
   component, interest income, capitalized interest, financing cost, debt
   fee, or negative-weight netting that contradicts equivalence.

Even when every condition holds, the automated result is
`PARTIAL: STRUCTURAL_CONTINUITY_SUPPORTED_BUT_ECONOMIC_SCOPE_NOT_PROVEN`.

## Mechanical outcomes

### PASS

Calculation evidence alone can never produce `PASS`.

An issuer-specific `PASS` would additionally require authoritative filing
text or an accounting-policy note that explicitly establishes that the
conditional concept is the issuer's complete gross interest expense,
excludes interest income, excludes capitalized interest and debt fees, and
omits no operating-interest component. That conclusion requires semantic
judgment and cannot be inferred from equal values.

### PARTIAL

Return `PARTIAL` for any of the following:

- Calculation linkbase is missing, empty, not collected, or not uniquely
  discoverable.
- The conditional concept has no calculation relationship.
- Only equivalent reported values are available.
- Calculation neighborhoods are stable but economic completeness is not
  explicitly established.
- Context, dimensions, roles, effective-arc resolution, or complete-DTS
  evidence is incomplete.

Absence of an arc is absence of structural evidence. It is not evidence
that an economic component does not exist.

### REJECT

Return `REJECT` only on positive contradiction evidence, including:

- `InterestExpenseNonoperating` is a component of a broader interest
  total that has other contributing children.
- The conditional concept participates in a netting relationship with
  weight `-1`.
- Its calculation neighborhood includes interest income, capitalized
  interest, debt issuance cost, other debt expense, or financing cost.
- Comparable contexts or statement roles show different economic
  aggregation structures across the transition.
- A binding calculation is arithmetically inconsistent after decimals,
  unit, context, and dimensions are applied.

`REJECT` means the conditional substitution is contradicted. It does not
invalidate the filing or the issuer's reporting.

## Canary request ruling

The frozen preflight set contains 18 accessions: six each for AMAT, CSCO,
and FIX. Existing index responses could mechanically identify at most one
issuer `_cal.xml` file per accession, making 18 additional SEC document
requests the smallest possible collection.

The request is nevertheless `NOT_APPROVED`. It is bounded and could reveal
a contradiction, but it cannot produce automatic gross-interest
authorization under this policy. The SEC-only collection route stops
unless a future use case explicitly needs contradiction diagnostics.

## Narrative and accounting-policy notes

Filing narrative may contain the missing economic-scope statement.
However, locating and interpreting issuer-specific prose, reconciling it
across amended filings, and determining whether it covers every
interest-bearing activity requires human accounting judgment. It is not a
scalable deterministic policy for a 300-security screen.

Narrative review may be recorded as a separate manual evidence decision
with reviewer identity, exact filing citation, decision version, and
supersession history. It must not silently populate the automated
scoring-input pipeline. For the scalable pipeline, the remaining options
are:

1. Keep interest coverage `MISSING` for these issuers, or
2. Validate a licensed provider-normalized gross-interest field whose
   documented semantics match the frozen Objective Rating v1 operand.

## Implementation

`sec_interest_calculation_policy.py` provides:

- Optional deterministic `_cal.xml` discovery.
- A filing-local calculation-linkbase parser.
- Structural neighborhood extraction.
- Conservative `PARTIAL` and positive-contradiction `REJECT`
  classification.
- A hard prohibition on automatic scope authorization.

The implementation does not issue network requests and does not execute
ratings.
