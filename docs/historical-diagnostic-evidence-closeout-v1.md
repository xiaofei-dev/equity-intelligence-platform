# Historical Diagnostic Evidence Closeout v1

## Purpose

This closeout records what the available historical evidence can and cannot
support before prospective Forward Decision-Quality Validation begins. It is a
strictly offline, read-only evidence integration. It does not run a model,
compute a score, read or write PostgreSQL, call a provider, or change any
formula, threshold, cohort, weight, sample, or missing-data rule.

## Final disposition

| Track | Frozen model | Horizon | Evidence disposition |
| --- | --- | ---: | --- |
| Tactical | `TACTICAL-SIGNAL-v2.2.0` | 5 completed sessions / 1 week | `DIAGNOSTIC_ONLY` |
| Tactical | `TACTICAL-SIGNAL-v2.2.0` | 20 completed sessions / 1 month | `DIAGNOSTIC_ONLY` |
| Tactical | `TACTICAL-SIGNAL-v2.2.0` | 60 completed sessions / 3 months | `DIAGNOSTIC_ONLY` |
| Long Horizon | `LONG-HORIZON-RESEARCH-v1.1.0` | 252 completed sessions / 12 months or more | `BLOCKED` |

The Historical PIT Slice Feasibility Audit contains 54 tactical
`DIAGNOSTIC_ONLY` candidates, 18 blocked Long Horizon candidates, and zero
formal PIT-eligible candidates. Long Horizon v1.1 has zero historical
decision-ready records and zero v1.1 historical scores.

## Why the evidence is not a formal validation

The local historical price payloads are hash-verified, but the evidence uses
the current closed pool retrospectively. Historical membership,
classification, listing state, corporate-action availability, fundamentals,
and Objective evidence are not proven point in time at each decision cutoff.
The closed pool therefore has survivorship bias.

The observed tactical and Long Horizon evidence is development evidence. It is
not an untouched holdout. The Long Horizon retrospective artifact also applies
the older v1.0 model and cannot be transferred into a v1.1 validation claim.
Overlapping retrospective outcomes, conservative availability assumptions, and
current revisions do not prove future returns or a repeatable statistical edge.

Favorable slices may help diagnose implementation behavior. They must never be
selected, combined, or re-labelled to manufacture a validation pass. Adverse
results remain valid diagnostic warnings; favorable results do not raise the
claim ceiling.

## Formal path

The only formal path from this closeout is prospective Forward
Decision-Quality Validation. That path must use a preregistered frozen model,
frozen prospective universe, post-preregistration completed-session evidence,
the complete benchmark contract, explicit costs, immutable decision snapshots,
and outcome evidence unavailable when each decision was sealed.

The machine-readable closeout is:

`docs/generated/historical-diagnostic-evidence-closeout-v1.json`

It contains file SHA-256 and canonical artifact hashes for the direct evidence,
the transitive price and universe bindings, both model freezes, and every file
bound into those freezes. It contains no provider values, returns, security
scores, or ranks.
