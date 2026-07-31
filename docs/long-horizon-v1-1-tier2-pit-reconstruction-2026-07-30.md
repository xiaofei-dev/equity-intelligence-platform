# Long Horizon v1.1 Tier-2 PIT Reconstruction

Date: 2026-07-30

## Outcome

The Tier-2 reconstruction completed offline for four historical decision
anchors. It used only hash-verified SEC v4 timelines, the frozen 55-security
closed-test universe, and the existing adjusted-price manifest. It made zero
provider requests.

This phase improves on Tier 1 by proving which fundamental primitives were
available at each historical cutoff. It does not produce a Long Horizon v1.1
score, classification, aggregate rank, or validation claim.

The terminal conclusion is:

`PARTIAL_TIER2_EVIDENCE_MODEL_VALIDATION_NOT_YET_AVAILABLE`

## Historical anchors

The anchors are completed SPY trading sessions measured backwards from the
latest complete cached session. Each cutoff is the end of the anchor date in
UTC. Only SEC observations or already-approved SEC derivations whose
`availableAt` is at or before the cutoff are admitted.

| Anchor | Trading date | SEC timelines | Business quality partial | Security attractiveness partial | Downside-risk partial |
| --- | --- | ---: | ---: | ---: | ---: |
| One year | 2025-07-25 | 42 / 55 | 42 | 42 | 42 |
| Two years | 2024-07-23 | 42 / 55 | 41 | 41 | 41 |
| Three years | 2023-07-21 | 42 / 55 | 38 | 38 | 38 |
| Five years | 2021-07-20 | 42 / 55 | 35 | 35 | 33 |

No target dimension is complete at any anchor. The partial count means at
least one required factor has a reproducible aligned primitive input set. It
does not mean the full dimension can be scored.

## Reconstructable input evidence

The strongest one-year anchor has the following primitive input-set coverage:

| Frozen factor | Reconstructable input sets | Partial primitives | Missing |
| --- | ---: | ---: | ---: |
| Operating margin | 36 | 0 | 19 |
| Free-cash-flow margin | 34 | 0 | 21 |
| Earnings stability | 42 | 0 | 13 |
| Cash-flow stability | 41 | 0 | 14 |
| Diluted-share growth | 42 | 0 | 13 |
| Earnings-yield numerator | 0 | 42 | 13 |
| Free-cash-flow-yield numerator | 0 | 36 | 19 |

`RECONSTRUCTABLE_INPUT_SET` means the required number of aligned
`DISCRETE_QUARTER` primitive observations is present. It does not mean the
factor value was computed. Factor formulas, period aggregation, and scoring
remain frozen and were not inferred by this phase.

The controlled evidence stores selected period identifiers, observation IDs,
content hashes, availability times, and source type. It intentionally omits
new model scores and ranks.

## Remaining blockers

The complete dimensions remain unavailable for explicit reasons:

- 13 of the 55 closed-test candidates do not have an authoritative SEC v4
  timeline in the frozen manifest. Four are recorded there as cache-missing;
  nine are absent from that 223-security manifest.
- Return on invested capital and net-debt-to-EBITDA remain blocked by
  unproven historical total-debt component completeness and non-overlap.
- Historical EBITDA and gross-interest TTM evidence remain unproven.
- Earnings yield and free-cash-flow yield have partial numerator evidence,
  but historical market-capitalization share-class identity is not proven.
- Enterprise value, own-history valuation distributions, cyclicality,
  concentration, and event-risk inputs are unavailable under the existing
  historical evidence contract.
- Historical membership and classification are still current-universe
  retrospective evidence, so survivorship bias is not controlled.

Missing, invalid, and unavailable evidence was not converted to zero or a
neutral score. Current fundamentals were not projected backwards.

## Evidence and claim boundary

Git-safe artifact:

`docs/generated/long-horizon-v1-1-tier2-pit-reconstruction-2026-07-30.json`

Controlled per-security evidence is content-addressed under:

`storage/historical-validation/long-horizon-v11-tier2`

The controlled directory is ignored by Git. The Git-safe artifact contains
only aggregate counts, source hashes, and the controlled-payload binding. It
contains no raw provider values or per-security model output.

This evidence can support a later Tier-3 implementation that freezes the
missing upstream factor-assembly rules and acquires or reconstructs the
remaining historical PIT operands. Until then, Long Horizon v1.1 historical
decision quality is not validated.
