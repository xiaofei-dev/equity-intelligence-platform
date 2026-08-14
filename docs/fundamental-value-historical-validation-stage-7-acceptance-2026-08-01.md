# Fundamental Value Stage 7 Historical Validation Audit Report

Date: 2026-08-01

## Final disposition

Stage 7 is **not accepted**. The execution and chronology audits passed, but
the independent statistical and implementation audits failed. The governing
validation outcome is `BLOCKED_BY_PROTOCOL_DEFECT`; the model remains
`NOT_VALIDATED`. The favorable aggregate result is preserved as observed data
but cannot support a directional evidence claim.

The sealed rank-IC contract is internally reversed: predictor ordinal 1 means
highest company quality, while return ordinal 1 means lowest return. Pearson
correlation of those vectors is negative when higher quality accompanies higher
returns, yet C8 interpreted positive IC as favorable. Post-outcome sign reversal
or retuning is prohibited. A new preregistered successor and fresh validation
boundary are required.

The checked repository also lacks the deterministic C8 calculation runner and
the complete per-security/date/horizon terminal registry needed to reproduce
all aggregates. The cost parameters are sealed, but the precise
participation-to-impact function was not included in the C8 policy artifact.

- Audit disposition canonical hash:
  `8C0610A47178CE54993E93B5926BDC94D05FF59E29A7B38B662AEC4E66C54385`
- Audit disposition file SHA-256:
  `3032ADF54CECD46FF436DA1FA626BF53378E18E57D6CB77BEECA57E795FDF5B1`

The population is exactly 191 C5 identities and 1,804 predictor/date rows,
labelled `CONTROLLED_OVERLAP_CURRENT_UNIVERSE_RETROSPECTIVE`. It is not the
planned 310-security universe and is subject to current-universe survivorship
bias. Specialized companies were excluded before predictor formation.

## Immutable outcome boundary

- C8 policy canonical hash:
  `FD2451B51EFC7B96F69D1CABE4CEA8337B7B43498A8158EBB317057F30DD19A1`
- C8 policy file SHA-256:
  `97933AF453B07200DE6566F82AC297CA08DFA94DEDBD9ECBEF134DC653CBCD52`
- Reuse registry canonical hash:
  `2F3B706745B8E99F14037CC52C83FA360580761E462A307E11C6BB28DBEFD711`
- Reuse registry file SHA-256:
  `44193C240BF1C2D98549B18E57FEF2AB392ACB225FC8748B6344F54F5AFCF2A8`
- Outcome-access intent canonical hash:
  `30997628421AC4C10A1AEF184698C5325DC66312E3EEB5CB22487AAA431E2E00`
- Outcome-access intent file SHA-256:
  `492AF8B27D8648B358758AA0A0E200297B4C6C95E7272816EE57B0BD5F72272E`
- Outcome result canonical hash:
  `9533393392F9539DD2B39516FD12FE020129AB5C9FCEADFE24CD2767B96F92E1`
- Outcome result file SHA-256:
  `EC5DEC2E7C3CE62C9B628F2909F3CE734CBC4F034C0918A7BF72159481454A9B`
- Final summary canonical hash:
  `104D3B414A9F5638AF1A5A7CB5334589AF1A1A866F5E58284C90EBF9378963F0`
- Final summary file SHA-256:
  `92B0ABB5001F56069709B9A1E806F7DC5A5B3027D7FC3770F0D43081136B9878`

The outcome acquisition completed 203/203 Yahoo aliases: 37 exact receipt
reuses and 166 new physical calls, retry zero, with no UNKNOWN or failed
request. A repaired C8 reuse registry binds all legacy receipts to exact C7
request identity, logical security, range, schema/parser, adjustment policy,
and payload hashes.

## Observed primary 756-session result - statistically invalid interpretation

All nine primary dates passed the frozen security, SPY, high/low group,
liquidity, and exact-path coverage gates.

| Metric | Result | Frozen threshold |
|---|---:|---:|
| Eligible primary dates | 9/9 | at least 7 |
| Median rank IC | 0.1366 | at least 0.05 |
| Positive rank-IC dates | 9/9 | at least 6 |
| Median high-minus-low annualized spread | 2.76 pp | at least 2 pp |
| Median high-minus-SPY annualized excess | 5.90 pp | at least 1 pp |
| High-versus-SPY wins | 9/9 | at least 6 |
| Leave-one-date-out SPY excess | nonnegative for every omission | nonnegative |
| Median high gross-MDD deterioration versus SPY | within 5 pp | at most 5 pp |
| Stress veto nodes | 0/3 | fewer than 2 |

The three greedy non-overlapping 756-session diagnostic anchors are
2015-05-07, 2019-06-21, and 2023-05-18. They do not replace the full nine-date
overlapping descriptive summary.

## Diagnostic horizons

| Horizon | Eligible dates | Median rank IC | Median high-low annualized | Median high-SPY annualized |
|---|---:|---:|---:|---:|
| 252 sessions | 9 | 0.1033 | 4.68 pp | 7.07 pp |
| 504 sessions | 9 | 0.0666 | 2.95 pp | 5.59 pp |
| 756 sessions | 9 | 0.1366 | 2.76 pp | 5.90 pp |

All three stress nodes avoided the frozen veto. Their high-minus-SPY
annualized excesses were approximately 11.97 pp, 4.15 pp, and 6.29 pp. Stress
results are diagnostics and never enter the primary estimate.

## Interpretation and limitations

The raw market-first aggregates were favorable, but the independent audit
invalidated the signed rank-IC interpretation and therefore the combined
all-thresholds-passed claim. The result does not validate security attractiveness, expected return,
downside risk, a composite score, or production investability. Current-revision
fundamentals and adjusted prices can include later revisions. The population is
a current controlled overlap and excludes unproven terminal-event paths rather
than reconstructing delisting consideration.

Sector-relative diagnostics are `NOT_OBSERVED` because no C8 implementation
bound the current provider classification to the sealed identity/date rows.
SPY results remain valid under the frozen market-first rule; sector data were
not replaced with SPY.

The checked aggregate result records coverage, high/middle/low gross and net
returns, cost contributions, annualized SPY excess, hit rate, severe-loss
frequency, true gross portfolio/benchmark MDD, downside capture, rank IC,
missing-reason counts, and horizon eligibility for every date and horizon.

## Stage 8 boundary

Stage 8A is closed because Stage 7 was not accepted. No real enrollment, forward outcome,
V24 migration, business-database write, production evidence-label change,
portfolio weight, brokerage path, deployment, commit, or push is authorized by
this result.
