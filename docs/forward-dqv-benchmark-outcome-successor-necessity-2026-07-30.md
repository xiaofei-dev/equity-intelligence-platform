# Forward DQV Benchmark Outcome Successor Necessity

Date: 2026-07-30

## Decision

The controlled v2.2 benchmark ledger is implementation-ready, but the formal
outcome schema is not ready for an honest Forward Decision-Quality Validation
run.

These are separate readiness claims:

- The ledger retains all six benchmark families, every dated sector variant,
  fixed constituent weights, price and corporate-action evidence, liquidity
  evidence, and holding-level transaction-cost inputs.
- V18 and the current Gate H/statistics contracts cannot express the required
  security-specific sector comparison or the nonlinear cost of a multi-holding
  benchmark portfolio.

No formal benchmark outcome, score, rank, or validation claim may be produced
by copying one sector return across all securities or by averaging holding
liquidity.

## Confirmed v18 and Gate H constraints

`analytics.forward_dqv_benchmark_outcome_v2` has the primary key
`(outcome_batch_id, benchmark_kind)`. It has neither a security identifier nor
a benchmark variant identifier. It can therefore persist only one `SECTOR`
outcome for an outcome batch even though the frozen protocol requires each
assessed security to be compared with its own dated sector ETF.

The current maturity path gives Gate H one order notional and one average daily
dollar volume for an entire benchmark path. This shape is sufficient for a
single-security benchmark, but not for equal-weight, momentum, value, or
quality portfolios containing several holdings. Liquidity-sensitive cost is
nonlinear and must be evaluated for each holding.

The current statistics adapter builds one global six-benchmark return map and
passes that same map to every security observation. That behavior cannot be
used for the sector benchmark.

The maturity loader correctly stops instead of guessing:

- `SEALED_SECTOR_VARIANT_SELECTION_NOT_BOUND`
- `SEALED_BENCHMARK_LIQUIDITY_AGGREGATION_NOT_PROVEN`

## Minimum successor design

A future append-only migration, suggested as V20, should persist the complete
decision-time ledger before adding maturity outcomes:

1. An immutable ledger header bound to the enrollment, cutoff, population,
   model, classification, benchmark, and cost-policy roots.
2. Exactly six family rows per ledger.
3. Every family variant, including all dated sector ETF variants.
4. Every decision-time holding with weight, notional, ADTV, cost, selection,
   price, action, and lineage evidence.
5. Exactly one variant binding for every frozen security and benchmark kind.
6. A benchmark-variant maturity outcome keyed by outcome batch, benchmark kind,
   and variant identifier.
7. A benchmark-holding maturity outcome keyed by outcome batch, benchmark
   kind, variant, and holding security.

The existing V18 outcome batch can remain the maturity-run header, but it must
reference the exact decision-time ledger. The maturity holding record must
preserve gross contribution, holding cost, and evidence hashes. Portfolio cost
must be computed as:

`sum(holding notional * holding cost rate) / sum(holding notional)`

The liquidity-sensitive cost function must first be evaluated separately for
each holding. ADTV must not be averaged and one holding cost must not be copied
to the portfolio.

For `SECTOR`, the selected variant must come from each security's sealed dated
classification binding. For the other five benchmark families, a shared
variant may be referenced only after its own fixed constituent path and
holding-level costs have been computed.

V20 acceptance must cover clean V1-to-V20 migration, V18-to-V20 and V19-to-V20
upgrade paths, exact six-family and 66-by-6 binding completeness, dated sector
selection, holding-level cost calculation, rejection of aggregate ADTV, and
append-only correction chains.

## Current boundary

This document and its machine-readable companion are a design necessity
record. They do not create V20, write PostgreSQL, compute outcomes, or claim
that Forward Decision-Quality Validation has passed.

Machine-readable evidence:
`docs/generated/forward-dqv-benchmark-outcome-successor-necessity-v1.json`.
