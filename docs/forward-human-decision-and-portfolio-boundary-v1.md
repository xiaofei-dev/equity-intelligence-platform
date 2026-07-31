# Forward Human Decision and Portfolio Boundary v1

## Decision

Prospective Forward Decision-Quality Validation keeps three independent
records:

1. the immutable deterministic model output;
2. an optional, later human research-decision record;
3. an explicit portfolio-suitability boundary.

The human record cannot change a score, rank, model evidence label, missing
state, or model result. Portfolio suitability is
`NOT_ASSESSED_BY_MODEL`. A separate user-owned portfolio workflow may be
hash-bound as external evidence, but this contract never stores portfolio
weights, trade decisions, or an automatic-execution instruction.

## Human record contract

`FORWARD-DQV-HUMAN-DECISION-RECORD-v1.0.0` is a deterministic,
content-addressed append-only record. Each record preserves:

- the prospective enrollment identity when one already exists;
- public security identity;
- the immutable output-set and security-output hashes;
- output seal evidence and its timestamp;
- actor and closed-test identity;
- the timezone-aware human decision timestamp;
- cited evidence references, hashes, kinds, availability times, and citation
  times;
- rationale, confidence in the inclusive range 0 to 1, and a research-only
  disposition;
- the immediate predecessor hash;
- the superseded record hash when the record is an explicit correction.

The root has no predecessor or supersession hash. Every later record points to
the previous chain head. A record may supersede an earlier member of the same
chain only once. Duplicate IDs, duplicate hashes, chronology regression,
cross-security roots, cross-test roots, and cross-output roots fail closed.

The human timestamp must be on or after the immutable model-output seal. When
the record is bound to a prospective enrollment, it must be recorded no later
than the enrollment's effective completed-session entry open. This prevents a
later observed outcome from being presented as a prospective human decision.

Allowed dispositions are research workflow states:

- `REVIEW_ONLY`
- `ACCEPT_FOR_RESEARCH`
- `WATCH_ONLY`
- `ABSTAIN`
- `ESCALATE_RESEARCH`

They are not orders or portfolio instructions.

## Portfolio boundary

`FORWARD-DQV-PORTFOLIO-SUITABILITY-BOUNDARY-v1.0.0` always records:

- `modelAssessmentState = NOT_ASSESSED_BY_MODEL`;
- `modelMayDeterminePortfolioSuitability = false`;
- `portfolioWeightsIncluded = false`;
- `tradeDecisionIncluded = false`;
- `automaticExecutionAuthorized = false`.

The default user-owned workflow state is `NOT_SUPPLIED`. If a separate
Spring-owned user portfolio workflow is supplied, the boundary requires its
reference, content hash, and user/test identity atomically. That external
binding does not turn portfolio suitability into a model output.

## Prospective binding

`FORWARD-DQV-PROSPECTIVE-GOVERNANCE-SIDECAR-v1.0.0` binds the separate records
to:

- the post-freeze decision manifest hash;
- the deterministic decision-output set hash;
- the decision-controlled composite hash;
- the model-output seal timestamp;
- an optional, fully verified `FORWARD-DQV-ENROLLMENT-v2.1.1` identity and
  content hash.

The sidecar carries an ordered human-record set hash and chain-head hash. Its
human record hash is compatible with the existing maturity statistics
`humanReviewHash` provenance field, while remaining separate from the frozen
deterministic snapshot.

Human judgment is deliberately not included in the model output or the
existing enrollment content hash. Rebuilding either immutable object after a
human review would corrupt the prospective chronology.

## Persistence readiness

The code contract and immutable Git-safe policy artifact are ready, but formal
database persistence is blocked. V18 and V19 do not contain:

- an append-only human decision ledger;
- predecessor and supersession constraints;
- durable output-set, security-output, and enrollment hash bindings;
- a separate user-owned portfolio workflow binding.

The sidecar therefore reports
`BLOCKED_SUCCESSOR_SCHEMA_REQUIRED`. A successor migration must add these
capabilities without changing or reinterpreting V18 or V19. Until that
migration and typed readback are accepted, an immutable controlled sidecar may
preserve evidence, but it is not the authoritative database ledger required
for formal Forward DQV.

## Files

- Contract:
  `analysis-python/src/equity_analysis/forward_validation/human_decision_governance_v1.py`
- Focused tests:
  `analysis-python/tests/test_human_decision_governance_v1.py`
- Git-safe policy:
  `docs/generated/forward-human-decision-governance-policy-v1.json`

No provider request, database write, score, rank, trade decision, commit, push,
or deployment was performed for this contract.
