# Fundamental Value Investment System v1 Stage 1 Acceptance

Date: 2026-07-31

## Decision

Stage 1 is accepted as `PASS` for contract and methodology engineering.
`FUNDAMENTAL-VALUE-v1.0.0` remains `NOT_VALIDATED` as an investment model.

## Accepted scope

- mature nonfinancial United States listed operating companies only;
- fail-closed specialized, benchmark, and insufficient-history routing;
- NBN bank regression protection;
- FCFF DCF, normalized Owner Earnings, and Earnings Power primary methods;
- comparable valuation as a non-controlling cross-check;
- weighted-median central estimate and ordered weighted-quantile range;
- missing advanced evidence lowering claim ceiling and cap, with material
  refinancing uncertainty blocking valuation;
- exact 0/1/2/3/5 percent `LONG_TERM_CORE` risk-cap ceilings;
- narrative-only AI and explicit human final-allocation control;
- append-only Fundamental Value V23 reservation without raw-retention,
  deletion, or legal-hold governance; and
- separately gated historical validation before prospective Forward DQV.

## Verification

Focused offline acceptance:

```text
159 passed in 0.28s
Ruff: All checks passed
git diff --check: PASS
```

The pytest count combines the new Fundamental Value contract suite and the
pre-existing Dual-System Architecture Contract suite. The canonical fixture
content hash is recomputed by the decoder, and semantic drift without resealing
fails closed.

The test tools were installed in an isolated temporary directory because the
checkout has no local virtual environment. The temporary directory was removed
after verification. No provider endpoint was called.

## Boundaries not crossed

Stage 1 did not:

- implement valuation calculations;
- create or apply V23;
- access a business database;
- call Yahoo, EODHD, SEC, or another data provider;
- change Quantitative Trading;
- create a portfolio weight or brokerage instruction;
- create cloud resources or deploy;
- change the repository's No License state;
- rewrite historical generated evidence; or
- commit, push, or merge.

## Next gate

Stage 2 may implement the pure deterministic Python core against the frozen
contract. A source-hash model freeze belongs after the Stage 2 implementation
is stable, so it can bind actual formulas rather than placeholder paths.
