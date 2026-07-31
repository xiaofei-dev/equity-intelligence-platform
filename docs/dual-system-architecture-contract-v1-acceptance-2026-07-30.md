# Dual-System Architecture Contract v1 Acceptance

Date: 2026-07-30

## Result

Result: `PASS`

This result includes the cross-language fail-closed parity repair completed
after the initial contract review.

The Phase 0 contract freeze is implemented as documentation, one canonical
Git-safe fixture, strict Python/Java/TypeScript decoders, and offline tests.
No database migration, scoring formula, point-in-time selector, provider
execution, public API replacement, portfolio calculation, or brokerage path
was introduced.

## Accepted Boundaries

- Fundamental Value, Quantitative Trading, and Unified Portfolio/Risk have
  separate responsibilities.
- `LONG_TERM_CORE` and `QUANT_TRADING` are isolated sleeves.
- A security may exist in both sleeves without mixing holdings, cash, basis,
  thesis, exits, constraints, benchmarks, risk, or attribution.
- Cross-engine score averaging and automatic cash transfer are prohibited.
- Fundamental Value retains a central fair value and range, emphasizes margin
  of safety, and returns only a cap.
- Quant v1 is US-equity, daily, completed-session, long-only research without
  leverage, shorting, options, or execution.
- AI remains narrative-only and final allocation remains human-controlled.
- Provider-neutral evidence strictness, claim classes, conflict policy, and
  field-specific tolerance rules are frozen.
- `BUYING_OPPORTUNITY` is compatibility-only long-term valuation evidence;
  `VALUATION_OPPORTUNITY` is the successor name.

## Verification

- Python Dual-System plus analytics-model regression:
  `143 passed`.
- Python Ruff for the new decoder and tests: passed.
- Java Dual-System plus Market Intelligence contract regression:
  `18 passed`, Maven `BUILD SUCCESS`.
- TypeScript Dual-System plus Market Intelligence contract regression:
  `27 passed`.
- `git diff --check`: passed.
- Migration inventory: unchanged at V1-V17.

The frontend ESLint binary was not installed in this clean worktree, so ESLint
was not executed. No dependency download was authorized or attempted. The
TypeScript contract tests executed successfully with the repository's
dependency-free Node test command.

The parity matrix proves that all three decoders accept the canonical fixture
and reject missing, null, unknown, incomplete, or unsafe variants for:

- engine state and specialized-model applicability;
- completed-session identity and `COMPLETED` status;
- decision and sealed-ingestion cutoffs;
- quant market/cadence/direction/control flags and trade-plan structure;
- fundamental fair-value range, margin of safety, cap, and benchmarks;
- portfolio sleeves, benchmarks, score isolation, and cash-transfer authority;
- all human-control and AI-isolation flags;
- field-specific tolerance alignment and blank metadata;
- non-`VALID` scores without explicit reasons;
- required version identifiers, liquidity/cost assumptions; and
- evidence claim-ceiling and no-model-label-upgrade invariants.
- explicit missing/null Java safety declarations rather than primitive defaults;
- required provider lineage, revisions, timestamps, and conflict structure;
- optional `retrievedAt`/`staleAfter` timestamp behavior;
- tolerance policy required only for domain-tolerant numeric evidence; and
- fail-closed contract/enumeration versions versus nonblank opaque component
  version references resolved by Task 1.
- durable security identity and current ticker/MIC/currency declarations;
- immutable engine output, model, strategy, decision-contract, and evidence
  references;
- sleeve-to-engine-output binding and cross-binding rejection;
- the complete compatibility tuple and governed model-evidence labels; and
- the complete expressible session, decision-cutoff, ingestion-cutoff, and
  evidence chronology.
- strict ordinary finite decimal-string syntax across every declared value;
- exact arbitrary-precision signed decimal comparison for fair-value ordering,
  including distinct 401-digit ordered and reversed-range regressions;
- strict RFC 3339 instant syntax with timezone and real ISO session dates; and
- wrong-type structured evidence, tolerance, conflict, and Boolean coercion
  rejection, including optional timestamp values when present.
- JsonNode-first Java wire validation of every canonical string/Boolean/object/
  array field before record binding, with numeric/Boolean identity, calendar,
  version, engine-binding, and benchmark coercion explicitly rejected.

## Task 1 Handoff

Task 1 remains unimplemented. Its first work should:

1. add stable company, instrument, share-class, listing, ticker, and provider
   mapping identities through append-only successor migrations;
2. persist versioned exchange calendars and completed sessions;
3. establish raw-manifest, normalized-observation, and engine-derived evidence
   boundaries;
4. add provider-neutral selectors for prices/actions/adjustments,
   fundamentals/periods/revisions, classifications, benchmarks, and liquidity;
5. harden provider budget, stop, journal, and recovery policies; and
6. expose internal selectors before replacing any legacy public market-data
   compatibility surface.

Task 1 requires a separately approved implementation start. It must preserve
V1-V17, scoring formulas, missing-data behavior, PIT rules, validation claim
ceilings, AI isolation, and human control.

## Remaining Non-Blocking Decisions

Phase 0 has no blocking decision. Task 1 will need implementation-level
approval for migration grouping/names, raw-storage retention policy, initial
specialized model coverage, and the exact internal selector endpoint shapes.
