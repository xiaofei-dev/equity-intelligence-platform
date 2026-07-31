# Tactical v2.2 Tier-1 Retrospective

## Scope

The Tier-1 retrospective replays the frozen Tactical v2.2 implementation on
sealed historical decision dates with completed-session outcomes. It preserves
the frozen universe, missing-data behavior, benchmark policy, transaction
costs, and actionability ceiling.

The evidence label remains `DEVELOPMENT_OBSERVED`. Current-universe
survivorship bias, current-revision adjusted prices, non-PIT classifications,
and previously observable outcomes prevent a formal validation claim.

## Publication boundary

Security decisions, paths, returns, ranks, drawdowns, and benchmark metrics
remain in the Git-ignored controlled result. The public manifest contains only
hashes, versions, horizon and population counts, availability states, and
claim limitations.

Git-safe manifest:

`docs/generated/tactical-v2-2-tier1-retrospective-manifest-v1.json`

Missing controlled local data cause the retrospective integration tests to
skip in a clean clone. Contract, score, chronology, and aggregation tests do
not depend on those files and continue to run.

See [Licensed Market Data Publication Policy](licensed-market-data-publication-policy.md).
