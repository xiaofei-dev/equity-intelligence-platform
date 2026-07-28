# Objective Rating v1 Cross-Provider Current Interest Ruling

Date: 2026-07-28
Policy version: `current-interest-cross-provider-evidence-v1.0.0`
Input contract version: `current-interest-cross-provider-input-v1.0.0`
Acceptance status: `AWAITING_PROVIDER_ARTIFACT`

## Decision

Frozen Objective Rating v1 accepts a source-agnostic, provider-normalized
`interest_expense_ttm` operand. It does not require the operand to originate
from SEC `us-gaap:InterestExpense`, and its original specification did not
require issuer-specific proof that every operating and nonoperating gross
interest component was included.

The later SEC evidence policies correctly prevented economically narrower SEC
concepts from being silently substituted for the normalized operand. They
must not retroactively turn one SEC taxonomy concept into the only admissible
source for frozen v1.

A current EODHD four-record sum may therefore be accepted as the frozen
provider-normalized TTM operand when it exactly matches a Yahoo observation
explicitly labeled `TTM`, subject to the contract below. This is a
`CURRENT_SNAPSHOT_ONLY` route. It proves reproducibility of the current
normalized aggregate; it does not prove complete gross-interest scope,
historical PIT availability, revision history, or quarter-level comparability.

No provider result is accepted by this document. Formal acceptance remains
blocked until Provider Integration supplies an immutable artifact satisfying
the contract and source-hash requirements.

## Frozen v1 semantic boundary

The authoritative v1 specification requires:

```text
interest coverage = EBIT / absolute interest expense
```

The denominator must be positive after `abs`, use the same currency and TTM
period as EBIT, and preserve missing states. The factor implementation accepts
a normalized Decimal operand and is not coupled to SEC or EODHD.

The cross-provider policy therefore distinguishes:

- `frozenV1ProviderNormalizedOperandAuthorized = true`: sufficient for the
  frozen current interest-coverage input;
- `grossEconomicScopeProven = false`: the comparison does not establish a
  universal accounting definition;
- `historicalPitAuthorized = false`;
- `quarterHistoryAuthorized = false`.

This is a correction of evidence routing, not a formula or threshold change.

## Per-security evidence contract

The input must contain:

1. Exactly four latest EODHD `Financials.Income_Statement.quarterly`
   `interestExpense` records, retained in chronological order after validation.
2. Exactly four Yahoo quarterly interest-expense observations explicitly
   labeled `periodType = 3M`.
3. One Yahoo trailing interest-expense observation explicitly labeled
   `periodType = TTM`.
4. The same security identity, reporting currency, and latest period end for
   the EODHD aggregate and Yahoo TTM observation.
5. Decimal strings after an explicit, versioned unit normalization.
6. Source reference, SHA-256 content hash, retrieval/ingestion time, provider
   parser version, and normalization version for every observation.
7. Every source response ingested no later than the sealed current-snapshot
   cutoff.

The four EODHD dates must be unique and chronologically quarter-like, with
adjacent period ends 60 to 120 days apart. This guards against duplicates and
missing records. It does not declare the individual EODHD records to be
discrete quarters.

The accepted operand is:

```text
EODHD four-record sum
```

and acceptance requires:

```text
EODHD four-record sum == Yahoo explicit TTM
```

after currency and unit normalization, using exact Decimal equality. The
Yahoo TTM observation is corroboration, not the value source. Both sides and
their hashes remain in lineage.

## Outcomes

### `CURRENT_TTM_CONFIRMED`

Return this state when all contract fields pass, the two current aggregates
match exactly, and the four Yahoo `3M` observations also sum to Yahoo TTM.

The normalized operand is `VALID` only for a sealed current snapshot.

### `CURRENT_TTM_CONFIRMED_WITH_QUARTER_CONFLICT`

Return this state when the EODHD sum exactly matches Yahoo explicit TTM, but
Yahoo's four displayed `3M` observations do not sum to its own TTM.

The explicit Yahoo TTM observation may still corroborate the current aggregate
because it is the duration-specific field being tested. The internal Yahoo
quarter conflict must be recorded as
`YAHOO_QUARTER_SERIES_CONFLICT`; neither provider's quarter series may then be
used for stability, historical reconstruction, or quarter-level validation.

This is the provisional routing for CIEN if the formal Provider artifact
confirms the observations supplied to the methodology review.

### `PROVIDER_CONFLICT`

Return `MISSING` with no numeric substitute when:

- EODHD four-record sum differs from Yahoo TTM;
- currencies differ; or
- latest period ends differ.

FIX, PLAB, and WDFC remain provisional `PROVIDER_CONFLICT` cases. They cannot
be upgraded unless an already-local, hash-verified SEC route proves a complete
current TTM denominator. No new SEC request is authorized.

### `INSUFFICIENT_EVIDENCE`

Return `MISSING` for absent records, invalid hashes, non-Decimal values,
unsupported period labels, future ingestion, incomplete lineage, duplicate
periods, or a non-quarter-like date sequence.

Missing and conflict states are never converted to zero or neutral.

## Correlated-provider risk

Yahoo and EODHD may share issuer filings, aggregators, or other upstream
sources. Exact matching is therefore called `CROSS_PROVIDER_CORROBORATION`,
not statistical independence or independent economic-scope proof.

Every accepted result records:

- `upstreamIndependenceProven = false`;
- both provider identities and response hashes;
- the field paths and parser versions;
- the normalization version;
- any internal provider conflict.

The match authorizes only the observed security and cutoff. It does not
establish a universal contract for EODHD, Yahoo, other issuers, or later
provider revisions.

## Sample, coverage, and cohort thresholds

### Evidence canary

- Frozen sample: the ten predeclared symbols AMAT, CIEN, COO, CSCO, DHR, FAST,
  FIX, PLAB, TSN, and WDFC.
- Required artifact coverage: 10 of 10 symbols, or `100.0000%`.
- Each symbol must terminate as confirmed, confirmed with a quarter conflict,
  provider conflict, or insufficient evidence.
- Duplicate, unexpected, unclassified, or system-failure records make the
  artifact unacceptable.
- At least one exact-match branch and one conflict branch must be exercised so
  that both acceptance and rejection behavior are tested.

There is no required pass-rate. The policy is per security; a low match rate
reduces coverage rather than weakening the rule.

The observations supplied before the formal artifact suggest seven matches
and three conflicts. These counts are provisional and are not an acceptance
result.

### Rating cohorts

This policy only establishes an input operand. It creates no score, rank, or
cohort membership.

Frozen normalization thresholds remain unchanged:

- sector × market-cap × company-type: minimum 20;
- sector × company-type fallback: minimum 30;
- general-company fallback: minimum 100.

Only securities that pass the complete strategy input contract may count
toward those thresholds. `PROVIDER_CONFLICT` and `INSUFFICIENT_EVIDENCE`
securities do not enter numeric normalization.

## Purpose boundaries

### Current snapshot rating

Allowed after the formal artifact passes. The result must carry the sealed
cutoff and both providers' lineage.

### Forward Decision-Quality Validation

Still stopped. This ruling does not start enrollment or authorize a forward
experiment.

### Historical backtest

Not authorized. Current response hashes and retrieval times do not prove when
the same values or revisions were historically available. EODHD annual
duration, exact period start, and revision history remain unresolved for
historical reconstruction.

## Formal acceptance step

When Provider Integration publishes its immutable artifact, the acceptance
review must:

1. Verify artifact and source response hashes.
2. Verify the exact ten-symbol set and 100% terminal coverage.
3. Recompute every classification offline with
   `cross_provider_interest_policy.py`.
4. Confirm that provider conflicts remain missing.
5. Confirm that no licensed raw value is copied into Git artifacts.
6. Report accepted current-only count and every limitation.

Algorithm scoring remains stopped until that separate acceptance completes.
