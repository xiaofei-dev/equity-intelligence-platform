# Fundamental Value Stage 7C-7 Outcome Acquisition and Protocol Stop

Date: 2026-08-01

## Result

The bounded Yahoo acquisition completed successfully, but numeric outcomes
remain unopened at `BLOCKED_OUTCOME_PROTOCOL_UNRESOLVED`. This preserves the
claim ceiling `DEVELOPMENT_OBSERVED_CURRENT_REVISION_APPROXIMATION`. It is not
strict PIT, SEC equivalence, production eligibility, or evidence of future
performance. C1-C6 remain unchanged.

The population is exactly the C5 controlled-overlap current-survivor cohort:
191 `EODHD:{symbol}` logical identities and 1,804 sealed predictor rows across
12 dates. It is not a 310-security or survivorship-free claim. The alias policy
is `CURRENT_SYMBOL_AS_RETROSPECTIVE_TRANSPORT_ALIAS`; all 191 aliases are direct
and collision-free, including already Yahoo-formatted `BF-B`.

## Pre-outcome seals

- Plan hash: `FDBF01FF086A47A746639A5436C466BAEF175D1E233489667A5417FE27899166`
- Plan canonical hash: `0D188304DEA0F1183C8C3C5CCE6BD8BFD9EF676532B2F7FF30558A39831A1A74`
- Alias-map hash: `4231308230D2156229BF9F12369157E887337CDAA2B45C35EB12DCD73E78CCD5`
- Rank/group seal: `50069390D4AD07431D44E5ECDEAC78CFBA960BC16103D7F8D684F41867F6DB0C`
- Rank/group file SHA-256: `603795211525AEB9DA9F99ABDCE5C50D7FB431F06080B9D492AE34D77FD6C93E`
- SPY calendar seal: `7FE1CA16970AE0346C67120DD4F32BA3BEF039276B9800757D15D3744189AA2C`
- SPY calendar file SHA-256: `AF107891BB758C021EC012FDAB52AADDD8A07664F41CFCB7A686434A7B477CE8`

The SPY observed-session calendar contains 3,160 ordered sessions from the
same sealed Yahoo adapter. Every date resolves to the first session strictly
after cutoff and exact later indices 252, 504, and 756, with entry excluded
from elapsed sessions. The latest primary exit is 2026-05-27. The acquisition
envelope is frozen at 2014-01-01 through 2026-07-28, which covers the required
60-session liquidity lookback and all exits.

Ranks and 20/60/20 groups were sealed before outcome access. Ranking is
company-quality descending with durable security-ID ascending tie-break and
floor(N/5) high and low groups.

## Execution

The exact plan contains 191 equities, SPY, and the 11 frozen sector ETFs: 203
unique Yahoo wrapper requests. Existing receipts matched adapter, range,
schema, identity, and adjustment policy for 36 equities plus SPY. The remaining
155 equities and 11 ETFs were acquired once.

- Planned/completed: 203/203
- Verified reuse: 37
- New physical wrapper calls: 166
- Retry limit and actual retries: 0
- UNKNOWN requests: 0
- Receipt canonical hash: `B74761883F9395F1334B3F78983DB4237DF0F3F245F449EFFDC73F98FBB738AD`
- Receipt file SHA-256: `CD830491016535733CB9FE5C4BEAEBC6EE6D48F0186B6C82F131BF30FE8168C8`

Each new request was plan-derived, INTENT-first, one-call limited, checkpointed
before COMPLETED, and bound to chained event hashes, request identity, plan,
security, symbol, range, adapter, and payload hashes. Existing receipts were
hash-verified. Prior INTENT, FAILED, malformed chains, unsafe/orphan
checkpoints, plan drift, and lease conflicts fail closed without replay.

Yahoo adjusted close is the only total-return representation; separate
dividend or split application is forbidden. This is
`WRAPPER_NORMALIZED_ADJUSTED_CLOSE_CURRENT_REVISION`, not immutable history.

The Git-safe acquisition summary binds `LIQUIDITY-SENSITIVE-COST-v1.0.0`:
fixed round-trip 2 bps, base one-way slippage 1 bp, impact at full
participation 25 bps, maximum one-way impact 50 bps, USD 100,000 group and
benchmark notional, and arithmetic-mean raw-close-times-volume ADV over exactly
60 positive observed sessions strictly before entry. Missing liquidity blocks
the outcome. Only the precise application order remains unresolved.

## Why outcomes remain closed

The methodology ruling fixes the cost policy parameters and broad statistical
design, but the independent pre-outcome audit found calculation choices that
are not yet mechanically frozen in accepted artifacts:

- exact cost application order and benchmark notional semantics;
- downside-capture definition and zero-denominator behavior;
- severe-loss threshold;
- daily portfolio cash and terminal-event path handling;
- portfolio and SPY MDD formula, sampling, and horizon-window rules;
- Spearman tie/minimum-sample/missing-pair rules;
- horizon-specific coverage and group-minimum rules;
- inclusive interval rule for greedy non-overlapping anchors.

Selecting these now without master approval would add economic/statistical
policy after acquisition and before outcome access. No return or performance
value was read. Stage 7D/E/F and Stage 8 remain closed.

## Git-safe summary

- Acquisition summary canonical hash:
  `3CB9D9032D6C3E8407B02E6F214B8E3B42269C9B83DFF5FAB1D2E8A2C08105C9`
- Acquisition summary file SHA-256:
  `C34522BEF8CA9CFE607B94194BD6064F89C59D4A3A07140D155151B6F711A6CB`

Git-safe artifacts contain no Yahoo price values. Controlled provider payloads,
rank values, and execution receipts remain outside Git.
