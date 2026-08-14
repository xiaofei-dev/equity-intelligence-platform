# Fundamental Value Stage 7C-4 Support and Empirical Semantics Gate

Date: 2026-08-01

## Result

Stage 7C-4 stopped before reading controlled financial values. The supplied
PNG has the expected SHA-256
`4F79D7FFEC8539951337DBD4510B1B7CEFA750566D2D21D5602C73713CDD24D2`,
but visual inspection shows an EODHD Individual subscription-plan card. It
does not display the supplied live-chat statement. The human-provided quote is
recorded exactly and separately, but the screenshot cannot authenticate or
bind that quote to the provider.

The support gate is therefore
`BLOCKED_SUPPORT_EVIDENCE_BINDING_MISMATCH`. No empirical comparison and no
current-revision approximation replay ran. This is an evidence-provenance stop,
not a conclusion about whether EODHD quarterly records are cumulative.

## Sealed support record

The Git-safe record includes the source type, file hash, size and filesystem
timestamp, exact human-supplied quote, semantic implication, restatement and
revision limitation, human-provided provenance, observed visual content, and
the failed corroboration state. The screenshot binary is not stored in Git.

The quoted statement is: “Financials values for the quarters are not
cumulative. Restatement data is updated when possible.” If authenticated, it
would support noncumulative quarterly semantics only for
`CURRENT_REVISION_APPROXIMATION`; it could not establish strict PIT revision or
publication history.

## Pre-frozen empirical protocol

The following protocol was sealed before any controlled financial-value read:

- Deterministic SHA-256 ranking with sector round-robin selection.
- At least 20 controlled-overlap securities across at least eight sectors.
- Exact security, field, period end, unit, and currency matching between EODHD
  quarterly rows and SEC `DISCRETE_QUARTER` facts.
- Frozen fields: revenue, operating income, net income, operating cash flow,
  and capital expenditure. Each binds an exact EODHD Financials JSON path,
  exact SEC v4 normalized operand and concept/duration-selection policy, and
  explicit sign policy. No approximate field equivalence is allowed.
- Separate comparison of four distinct, 60-120-day EODHD quarters with the
  matching EODHD annual fiscal-period identity. The annual start/end must equal
  the chain boundaries, and adjacent quarter boundaries must be within seven
  days under the inclusive/exclusive convention; duplicate annual keys,
  material overlaps, gaps, and irregular chains fail.
- Tolerance: the greater of one currency unit or 1% of the larger absolute
  compared value.
- At least 100 cross-provider matches and 60 complete annual comparisons.
- At least 95% overall agreement, at least 90% agreement for every field, and
  no more than 2% contradictions, defined as contradictory exact comparisons
  divided by all exact comparisons; a zero denominator is insufficient.
- Missing fields remain missing and are reported outside agreement numerators.
- Any threshold, mapping, tolerance, or protocol-hash change requires a new
  version before comparisons; it cannot be tuned after results.

Protocol hash:
`DCB4609B165C1467C91FE6EABBB3EEA5E8B5BE9B6A88DCEF10E93F534B28DF75`.

## Boundary and hashes

- Outcome, price, benchmark, rank, drawdown and performance reads: zero.
- Network, provider, database and cloud calls: zero.
- Controlled financial values read: false.
- Empirical audit: `NOT_RUN`.
- Approximation replay: `NOT_RUN_SEMANTIC_GATE_FAILED`.
- Support-record hash:
  `10A38E8F906A8DA02828249E18CDD05CE46757C5DBAE78331E20AB55F7588F78`.
- Complete C4 artifact hash:
  `E3F219F8C7DEC6158E9B51AC6492559F1A11E94A73260E05330A3689D0C271AE`.

C1, C2, and C3 remain immutable. A screenshot or transcript that actually
shows the provider statement, with a verified hash and provenance, is required
before the frozen empirical comparison may read controlled financial values.
