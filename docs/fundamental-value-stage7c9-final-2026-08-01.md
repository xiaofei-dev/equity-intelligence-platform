# Fundamental Value Stage 7C-9 Final Confirmation

## Disposition

Stage 7C-9 closes the retrospective Stage 7 program with `MIXED_NOT_VALIDATED`.
The corrected deterministic ordinal-rank protocol passed every frozen
market-first numeric threshold, but the evidence remains
`DEVELOPMENT_OBSERVED_CURRENT_REVISION_APPROXIMATION`. It does not change the
production model label from `NOT_VALIDATED`.

C9 is not an untouched holdout. Its dates were selected after C8 aggregate
results were known, and it reuses the same 191-security current-survivor
population, current-revision fundamentals, Yahoo transport history, and partly
overlapping market windows. C8 remains immutable and rejected; no C8 sign was
reversed or reinterpreted.

## Frozen boundary and execution

- Nine deterministic confirmatory dates were selected from Q4 2015-2022 and
  Q1 2023 using the sealed SPY calendar and a domain-separated SHA-256 rank.
- Predictor coverage was 111-168 per date; every date exceeded 100 before any
  C9 outcome access.
- One immutable outcome-access intent was written. No network request was made;
  all 203 controlled Yahoo receipts were reused.
- The terminal registry contains exactly 5,157 unique
  security/date/horizon rows: 4,140 `USABLE` and 1,017 explicit `MISSING`.
- The first local calculation stopped before emitting a result because a new
  validator incorrectly demanded contiguous ranks after missing outcome pairs.
  The same sealed inputs were resumed under the same intent after removing only
  that contradictory reranking assertion. Dates, predictors, formulas, costs,
  groups, thresholds, and receipts did not change.

## Primary 756-session results

All nine dates were eligible. Complete-pair counts were 111-168 and coverage
was 99.33%-100%.

- Median corrected deterministic ordinal rank correlation: 0.1107; positive on
  9/9 dates.
- Median high-minus-low net annualized spread: 6.10 percentage points; positive
  on 8/9 dates.
- Median high-minus-SPY net annualized excess: 6.58 percentage points; high won
  on 9/9 dates.
- Minimum leave-one-date-out median high-minus-SPY excess: 6.38 percentage
  points.
- The immutable stored field labelled median MDD deterioration is actually
  `HIGH gross MDD - SPY gross MDD`, with median -0.85 percentage points. The
  correctly signed deterioration is `SPY gross MDD - HIGH gross MDD`, with
  median +0.85 percentage points; it still passes the frozen <=5 percentage
  point threshold. The original stored label is semantically misleading and is
  preserved only because C9 is immutable.

The sibling immutable `worstHighGrossMddDeteriorationVsSpy` field is likewise
mislabelled: its stored value +2.10 percentage points is the maximum of
`HIGH MDD - SPY MDD`. The correctly signed worst deterioration is the maximum
of `SPY MDD - HIGH MDD`, +3.94 percentage points, which still passes the frozen
<=5 percentage point ceiling.
- Strict `HIGH >= MIDDLE >= LOW` portfolio ordering occurred on only 2/9 dates.

The last item is why the outcome is reported as mixed despite favorable rank,
spread, and SPY comparisons. Sector diagnostics were not observed because a
classification mapping was not bound to the C9 predictor seal. C8 stress dates
remain prior descriptive diagnostics and are not C9 acceptance evidence.

## Immutable identities

- Policy: `11A639CA376DE3C1205F6F22EF312210E5A8620D549431168A7CCA67C5419D73`
- Predictor seal: `E110C20287CB1B9E2260E9DAA33C2F2A8B5CD290F11E20EB733B918F61F595DD`
- Outcome intent: `641B9463500E26274C7DEC28C01ACD8B79957CA899F501DD2F0EA18AF36E7DE5`
- Terminal registry: `77BD6811C5041E381C9D484806464DEFE642CDBA0D60A8071BF03D12DD7951C1`
- Outcome result: `E30E1CEFA08A2DA4DC21087ED7B813B012BFA24022E72860A48F580B796D4431`
- Final interpretation: `785988E194E28E0F8681064911CD9C8EA86164D5998D48C7DFA19DAB72B6456F`

## Claim boundary

This result is a practical retrospective diagnostic for one company-quality
component on a survivorship-limited controlled overlap. It is not strict PIT,
SEC-equivalent, a complete Fundamental Value assessment, production evidence
eligibility, `BACKTEST_SUPPORTED`, or `FORWARD_SUPPORTED`. No further
retrospective iteration is authorized by this stage.

## Post-closeout engineering replay acceptance

A new append-only acceptance identity freezes Decimal precision 28 with
`ROUND_HALF_EVEN` inside the complete runner. A read-only replay performed under
an outer precision of 50 reproduced the immutable 5,157-row registry and
27-row result exactly, including hashes. Nonvarying raw predictor scores or raw
returns now produce `NOT_OBSERVED` before security-identity tie-breaking.

The acceptance artifact also states the complete numeric threshold matrix and
recomputes the immutable final summary deterministically. This is post-outcome
engineering evidence only; it does not alter C9, its mixed disposition, or the
model evidence label. Stage 8A remains readiness-only.

The original outcome intent did not bind the replay code dependencies, Python
implementation/version/cache tag, or Decimal/libmpdec runtime. Original
pre-outcome provenance therefore remains `FAIL_PARTIAL`. The append-only
acceptance binds those dependencies and CPython 3.14.2 runtime and may claim
only current post-closeout engineering replay provenance `PASS`; it cannot
retroactively repair the original pre-outcome boundary.

The original C9 policy's `UNCHANGED_C8` text is not sufficient by itself; the
append-only acceptance artifact binds every exact numeric threshold. Its greedy
closed-interval 756-session anchor diagnostic selects 2015-11-12
(2015-11-13..2018-11-14), 2019-11-25 (2019-11-26..2022-11-28), and 2023-01-09
(2023-01-10..2026-01-15). This diagnostic does not affect acceptance.

No pre-reseal registry/result files or C9 execution journal were preserved.
Consequently, the claim that numeric values were independently proven unchanged
across the downstream reseal is retracted and recorded as
`NOT_INDEPENDENTLY_VERIFIABLE_FROM_PRESERVED_ARTIFACTS`. The current final chain
is exactly replayable; that is a narrower statement.
