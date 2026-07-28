# Objective Rating v1 QC Current-Input Methodology Review

## Decision

This review preserves the frozen `QC-v1.0.0` formula, weights, missing-data
semantics, PIT rules, and cohort thresholds. It authorizes three
provider-normalized raw fields for a sealed current snapshot only:

- `Highlights.DilutedEpsTTM` as current diluted EPS.
- `Highlights.RevenueTTM` as current TTM revenue.
- `Highlights.GrossProfitTTM` as current TTM gross profit.

The authorization requires an explicit TTM period type, period end, acquisition
before the sealed cutoff, source reference and content hash, normalization
version, unit, currency, and the frozen 150-day freshness rule. It does not
authorize historical PIT use or silently create a three-year endpoint.

`Highlights.OperatingMarginTTM` is not an authorized formula operand. The
frozen specification says vendor ratios are comparison-only, so operating
margin remains `TTM operating income / TTM revenue`. The provider ratio may be
retained as diagnostic evidence.

## Diluted EPS

The frozen raw-data contract names diluted EPS directly. Therefore, current
diluted EPS does not have to be derived from net income divided by diluted
weighted-average shares. That derivation is an implementation route, not the
only frozen-v1 economic definition.

Three-year EPS growth still requires comparable endpoints. Both endpoints must
be explicit TTM diluted EPS values with:

- period ends 1,000 through 1,200 days apart;
- the same provider field identity and normalization version;
- the same currency, unit, and split-adjustment mode;
- complete source references, hashes, and acquisition times; and
- a current endpoint no more than 150 calendar days old.

Yahoo trailing diluted EPS may confirm a same-date current EODHD TTM value.
Yahoo annual diluted EPS cannot be mixed with a trailing current value to
manufacture a three-year TTM endpoint. A cross-provider current match does not
prove historical PIT availability.

## Freshness Correction

The frozen specification requires 150 days. The current factor-window
implementation uses 200 days and must not be used for Algorithm Gate
eligibility until corrected and reassembled.

Applying 150 days to the seven previously ready snapshots removes `CSCO`.
Its oldest required current TTM period end is 185 days before the sealed
cutoff. The corrected baseline is therefore six ready securities, not seven.
No other previously ready security is removed.

This changes the completion target from 13 to 14 additional securities. A
13-security acquisition plan cannot reach the minimum cohort of 20.

## Bounded Evidence Plan

The conflict-free target set is:

`TTC`, `AVGO`, `HRL`, `GPC`, `DOV`, `BDX`, `APD`, `ROK`, `ADSK`, `AMD`,
`APH`, `BF-B`, `BLDR`, and `CNC`.

This set is capable of reaching 20 only if every target passes every required
operand check. It is not a forecast or promise. `FIX`, `PLAB`, and `WDFC`
remain excluded because their current interest evidence has unresolved
provider conflicts.

The minimum acquisition order is:

1. Reassemble accepted existing-cache fields for current diluted EPS, revenue,
   and gross profit under the new policy and 150-day freshness limit.
2. Obtain bounded Yahoo current TTM interest evidence only for targets lacking
   accepted interest evidence, applying the existing exact-match policy.
3. For `TTC` and `AVGO`, obtain an explicit comparable historical TTM diluted
   EPS endpoint. `AVGO` also needs a valid current TTM net-income input.
4. For `HRL`, obtain raw operating income for current operating margin,
   comparable three-year raw margin endpoints, and eight aligned discrete
   quarters for operating and FCF margins. Direct `OperatingMarginTTM` is not a
   substitute.
5. For the remaining targets, acquire only the blockers recorded in the
   authoritative feasibility artifact: explicit current raw TTM fields,
   comparable three-year TTM endpoints, or eight aligned discrete-quarter
   histories. No missing value may be replaced with zero or a neutral score.

Any Yahoo request must be bounded to the public financial-data fields needed
for a named target and must preserve period type, period end, currency,
acquisition time, and response hash. Annual EPS is diagnostic unless both
frozen TTM endpoints are independently established.

## Gate Result

The provider feasibility artifact is accepted as an authoritative blocker
inventory. Existing caches may be reassembled using the three authorized raw
field paths. The Algorithm Gate remains stopped because the corrected cohort
has only six ready securities, below the frozen minimum of 20. No score, rank,
supplement, network request, or Forward Decision-Quality Validation run was
performed by this review.
