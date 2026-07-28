# Objective Rating v1 QC Current Reassembly and Residual Evidence Plan

## Outcome

The accepted current-input methodology was implemented offline without changing
`QC-v1.0.0`, its weights, its missing-data rules, or the cohort minimum.

The authoritative reassembled manifest contains 55 hash-verified controlled
snapshots and reports six current-QC-input-ready securities:

`AMAT`, `CIEN`, `COO`, `DHR`, `FAST`, and `TSN`.

`CSCO` is no longer ready because its oldest required current financial window
is 185 days old at the sealed cutoff. The frozen maximum is 150 days. The
cohort therefore requires 14 additional ready securities to reach 20.

The earlier `v1-6` development output rebuilt from the pre-interest assembler
and did not preserve the accepted v1.5 interest evidence. It is retained as
non-authoritative development evidence. The authoritative `v1-7` migration
starts from each immutable v1.5 snapshot and preserves that lineage.

## Accepted Current-Only Fields

The reassembly permits these cached EODHD fields only for the sealed current
snapshot:

- `Highlights.DilutedEpsTTM`
- `Highlights.RevenueTTM`
- `Highlights.GrossProfitTTM`

Each controlled operand retains its provider path, normalized policy version,
period end, retrieval-derived availability time, sanitized source reference,
and source-response hash. Historical use is not authorized.

`Highlights.OperatingMarginTTM` remains excluded from formula inputs. Operating
margin still requires raw operating income divided by raw revenue.

## Conditional Target Audit

The exact post-reassembly matrix is in the machine-readable residual-evidence
artifact. The principal result is:

- `TTC` is the only target whose complete residual signature could
  conditionally be addressed by the authorized Yahoo evidence classes.
- `AVGO` also requires current TTM net income, which the bounded Yahoo policy
  does not authorize.
- `HRL`, `GPC`, `DOV`, `BDX`, `APD`, and `ROK` require raw current or historical
  financial windows beyond current-interest or diluted-EPS evidence.
- `ADSK`, `AMD`, `APH`, `BF-B`, `BLDR`, and `CNC` require multiple raw TTM,
  share, margin, or historical operands that Yahoo cannot legally substitute.

Repeated irreducible blockers include EBIT/operating income, three-year margin
endpoints, aligned eight-quarter histories, FCF-per-share inputs, current
weighted-average shares, income tax, pretax income, and net income.

## Bounded Yahoo Preflight

The smallest eligibility-relevant public Yahoo plan contains only `TTC`:

- Endpoint: public `fundamentals-timeseries`
- Types: `quarterlyInterestExpense`, `trailingInterestExpense`,
  `quarterlyDilutedEps`, and `trailingDilutedEps`
- Physical HTTP attempt ceiling: 1
- Retries: 0
- EODHD and SEC requests: 0
- Required controls: cross-process lock, INTENT/COMPLETED journal, unique
  immutable output, and gitignored controlled raw-response storage

Annual diluted EPS is not an acceptable TTM endpoint. Four quarterly diluted
EPS observations are usable only if they are explicit non-overlapping 3M
records that satisfy the accepted comparable-TTM policy.

Even perfect evidence for `TTC` would increase readiness only from 6 to 7.
The frozen cohort minimum of 20 would remain unreachable. The preflight status
is therefore `DO_NOT_EXECUTE_COHORT_COMPLETION_PRECHECK_FAIL`, and no request
was made.

## Exact Residual Evidence Decision

At least 13 additional securities beyond the theoretical `TTC` success still
require a different, explicitly approved evidence route for raw current TTM
facts, comparable three-year TTM endpoints, or eight-quarter histories.
Provider ratios, annual EPS substituted for TTM EPS, guessed equivalence, and
missing-to-zero conversion remain prohibited.

The next decision belongs to the Algorithm methodology owner: either authorize
a bounded raw-field/history evidence contract that matches the frozen operands,
or retain the gate below the cohort minimum. Yahoo current-interest confirmation
alone cannot complete the cohort.

No network request, score, rank, supplement, Forward Decision-Quality
Validation, commit, push, or deployment occurred.
