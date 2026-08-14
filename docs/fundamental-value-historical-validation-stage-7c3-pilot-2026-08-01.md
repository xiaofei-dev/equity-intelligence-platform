# Fundamental Value Stage 7C-3 Current-Revision Approximation Pilot

Date: 2026-08-01

## Boundary and conclusion

This pilot was zero-network, outcome-blind, and database-free. It used only
hash-verified repository and controlled offline evidence. It did not read
returns, benchmark returns, drawdowns, ranks, performance, or outcome files.
It did not change Stage 1-6 formulas or any production producer registry.

The pilot is a distinct `CURRENT_REVISION_APPROXIMATION` lineage with claim
ceiling `DEVELOPMENT_OBSERVED_CURRENT_REVISION_APPROXIMATION`. It is not strict
PIT evidence and does not reuse the Stage 7C-1 or Stage 7C-2 producer hashes.

## Semantic gate

The checked EODHD documentation audit has file SHA-256
`1A6C69CE011CF1E6974437A803891DEF4F4275791BCEEFFC712E51991AFAB938`.
It records that EODHD financial records have a `date` and `filing_date`, but
that the provider's quarterly flow duration is not documented as a discrete
quarter, year-to-date duration, or TTM. It also records that historical values
may be recalculated without field-level immutable revision identity.

Consequently, the approximation producer does not sum quarterly flow values.
All five frozen company-quality operands terminate `MISSING` with reason
`QUARTERLY_DISCRETE_YTD_TTM_SEMANTIC_UNSPECIFIED`. This preserves the frozen
TTM formulas and distinct-quarter chain policy without manufacturing period
starts or publication history.

## Evidence contract

The separate producer registry is
`FV-STAGE7-COMPANY-QUALITY-APPROXIMATION-PRODUCERS-v1.0.0`. Each evidence
envelope binds the approximation stratum, producer version and content hash,
operand and durable security identities, decision cutoff, period and filing
chronology when available, provider/schema/adapter/revision identifiers,
ordered source and parent hashes, unit, currency, terminal state and reason,
current-revision limitation, and output hash. Each approximation contract also
binds the corresponding frozen strict economic-contract hash, without reusing
its evidence identity. A non-`VALID` envelope cannot carry a numeric value.
While quarterly duration semantics remain undocumented, the registry is
`TERMINAL_MISSING_ONLY` and rejects every attempted `VALID` envelope after
validating its period/effective/filing/cutoff chronology. This prevents an
arbitrary ratio or incomplete parent set from being admitted later.

## Coverage

The same deterministic 25, controlled 100, and offline 216 cohorts were run on
all nine frozen Q2 decision dates. Every date has the following counts:

| Phase | Security denominator | Each operand MISSING | Complete company quality MISSING |
|---|---:|---:|---:|
| PILOT25 | 25 | 25 | 25 |
| CONTROLLED100 | 100 | 100 | 100 |
| OFFLINE216 | 216 | 216 | 216 |

There are no `VALID` or `INVALID` operand rows. Per offline-216 date, the
reason count is 1,080 missing operands plus 216 incomplete target components.
The minimum complete company-quality coverage is zero, below the frozen 100
minimum, so the gate is `STOPPED_BELOW_MINIMUM_COVERAGE`.

The immutable phase hashes are:

- PILOT25: `130D6A96BA99D78A3F6C0C27AE5FAFA43FC47E559693662C076370E7F8FB00EF`
- CONTROLLED100: `4EBDA489EB7F3B70718F2F52086DF2D3C164D6AC01E3810C430D6FF34B2F48D2`
- OFFLINE216: `4FB903263348B194C73C78A53B0D588CF6A7FEA33E9AAEBF374B0A7D15BF4C9E`

The full replay hash is
`C693ABAB0FB16FEB36D87BEFB845EA3F9E7F4ED5CD228BFEE4298C19D21D10A1`.
No historical outcomes or 310-security acquisition may follow from this
insufficient-coverage result.
