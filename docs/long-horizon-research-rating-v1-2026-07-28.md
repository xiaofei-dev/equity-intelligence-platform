# Long-Horizon Research Rating v1

Date: 2026-07-28

## Purpose

`LONG-HORIZON-RESEARCH-v1.0.0` is an absolute 12-month-plus research rubric.
It complements, but does not replace, the cohort-normalized Objective Rating
v1 contracts.

## General-company rubric

The deterministic score contains:

- quality, 30%: operating margin, net margin, and return on equity;
- growth, 25%: year-over-year quarterly revenue and earnings growth;
- resilience, 20%: current ratio and debt-to-equity;
- valuation, 25%: price/earnings, enterprise value/EBITDA, and PEG.

At least 70% of required evidence must be present. Missing evidence is never
replaced with a neutral score.

## Bank rubric

Banks do not use EBITDA, current ratio, or industrial-company leverage
interpretations. The bank model contains:

- profitability, 40%: return on equity, net margin, and earnings growth;
- asset quality and capital, 35%: nonperforming assets and Tier 1 leverage;
- valuation, 25%: price/earnings and price/book.

## Recent IPO rule

A recent IPO without adequate public-market cycle evidence receives
`INSUFFICIENT_PUBLIC_HISTORY` and no numeric long-horizon score.

## Evidence overlay

`RESEARCH-EVIDENCE-OVERLAY-v1.0.0` can record cited management, governance,
operating, and event evidence. Each item preserves:

- the observed fact;
- the model inference;
- source reference;
- direction and confidence.

The combined overlay is bounded to plus or minus 10 points. It cannot replace
missing deterministic data, alter raw facts, set portfolio weights, or make an
independent trade decision.

## Validation

The bounded validation used seven EODHD Fundamentals responses. Raw values and
the complete derived-input record are retained only under the Git-ignored
`storage/long-horizon-validation` directory.

Accepted controlled result:

- `storage/long-horizon-validation/20260728T103237Z/long-horizon-validation.json`
- file SHA-256:
  `CC606237E934A956511DD325E7AD1E9F1FEC36F4A24543E0287BEB23B8E45559`

This is a research rubric, not an expected-return forecast or proof of
investment performance.
