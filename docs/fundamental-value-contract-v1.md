# Fundamental Value v1 Contract

Date: 2026-07-31

## Purpose

`fundamental-value-investment-system-v1.0.0` is the strict Stage 1 semantic
contract for the future deterministic assessment. The executable decoder
fails closed on unknown versions, company types, applicability states,
valuation methods, method roles, aggregation rules, risk-cap tiers, validation
sequencing, persistence scope, and safety flags.

## Frozen version set

The contract requires nonblank opaque references for:

- V22 evidence contract;
- deterministic selector;
- applicability routing;
- Fundamental Value formulas;
- assumption policy;
- benchmark policy;
- risk policy; and
- validation governance.

Changing semantics requires a successor version. Provider and normalization
versions may change without changing formulas only when canonical semantics
remain identical and the V22 selector accepts the evidence.

## Method contract

The exact method family is FCFF DCF, normalized Owner Earnings, Earnings
Power, and a comparable cross-check. The three primary methods collectively
retain controlling weight. The comparable cross-check cannot exceed 15
percent, and no method can exceed 50 percent.

The aggregation contract is a weighted median central estimator and ordered
weighted quantile range. JSON numbers, exponent notation, hexadecimal values,
NaN, and infinities are rejected; declared numeric policy values use ordinary
finite base-10 strings.

## Applicability contract

Only `MATURE_OPERATING_COMPANY` maps to generic `APPLICABLE`. Banks, insurers,
REITs, resources, biotechnology, financials, and incompatible conglomerates
map only to `SPECIALIZED_MODEL_REQUIRED`. Benchmarks map to
`NOT_APPLICABLE`; insufficient public history maps to
`INSUFFICIENT_EVIDENCE`.

NBN is an explicit bank regression case. It cannot receive the generic result.

## Safety contract

- Quantitative Trading input is prohibited.
- AI is narrative-only.
- Missing advanced evidence never becomes zero.
- Material unknown refinancing risk blocks valuation.
- Risk caps are exactly 0, 1, 2, 3, or 5 percent.
- The model cannot return a final portfolio weight.
- Historical validation may conclude `NOT_VALIDATED`.
- Forward validation follows only after prior gate acceptance.
- V23 is append-only Fundamental Value persistence and excludes raw-retention
  governance.
- Automatic brokerage execution is prohibited.

## Canonical fixture

The Git-safe fixture is
`contracts/fundamental-value-v1/decision-contract.example.json`.
It freezes semantics without claiming that Stage 2 calculations or V23
persistence already exist.
