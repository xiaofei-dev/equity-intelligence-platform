import assert from "node:assert/strict";
import test from "node:test";

import { decodeSimulatedEvaluation } from "./evaluations.ts";

const portfolioId = "00000000-0000-4000-8000-000000000001";

function fixture() {
  return {
    evaluationId: "00000000-0000-4000-8000-000000000002",
    portfolioId,
    humanDecisionId: "00000000-0000-4000-8000-000000000003",
    startingContextId: "00000000-0000-4000-8000-000000000004",
    acceptedScenarioId: "00000000-0000-4000-8000-000000000005",
    holdCurrentScenarioId: "00000000-0000-4000-8000-000000000006",
    state: "AWAITING_NATURAL_MATURITY",
    benchmarkCode: "SPY",
    simulatedOnly: true,
    maturities: [20, 60, 252, 504, 756].map((horizonSessions) => ({
      horizonSessions,
      state: "AWAITING_NATURAL_MATURITY",
      terminalReason: null,
      observedAt: null,
    })),
    summaries: [],
    recordedAt: "2026-08-13T20:00:00Z",
  };
}

test("decodes an exact simulation-only evaluation with a distinct HOLD comparator", () => {
  assert.equal(
    decodeSimulatedEvaluation(fixture(), portfolioId).acceptedScenarioId,
    "00000000-0000-4000-8000-000000000005",
  );
});

test("rejects a missing accepted scenario binding and a self-comparator", () => {
  const missing = fixture() as Record<string, unknown>;
  delete missing.acceptedScenarioId;
  assert.throws(() => decodeSimulatedEvaluation(missing, portfolioId), /fields/);
  const same = fixture();
  same.holdCurrentScenarioId = same.acceptedScenarioId;
  assert.throws(() => decodeSimulatedEvaluation(same, portfolioId), /distinct/);
});

test("decodes HOLD comparator results and rejects noncanonical timestamps", () => {
  const value = fixture();
  value.state = "PARTIALLY_MATURED";
  value.maturities[0] = { horizonSessions: 20, state: "AVAILABLE", terminalReason: null, observedAt: "2026-09-10T20:00:00Z" };
  value.summaries = [{
    horizonSessions: 20,
    periodStart: "2026-08-14", periodEnd: "2026-09-10",
    expectedObservationCount: 21, observationCount: 21,
    grossReturn: "0.02", netReturn: "0.019", benchmarkReturn: "0.01",
    excessReturn: "0.009", holdCurrentReturn: "0.015",
    acceptedExcessVsHoldCurrent: "0.004", maximumDrawdown: "-0.01",
    totalTurnover: "0", totalCost: "1", coverageRate: "1",
  }];
  const decoded = decodeSimulatedEvaluation(value, portfolioId);
  assert.equal(decoded.summaries[0].holdCurrentReturn, "0.015");
  assert.equal(decoded.summaries[0].acceptedExcessVsHoldCurrent, "0.004");

  const offset = structuredClone(value); offset.recordedAt = "2026-08-13T13:00:00-07:00";
  assert.throws(() => decodeSimulatedEvaluation(offset, portfolioId), /whole-second/);
  const fractional = structuredClone(value); fractional.recordedAt = "2026-08-13T20:00:00.1Z";
  assert.throws(() => decodeSimulatedEvaluation(fractional, portfolioId), /whole-second/);
});

test("preserves NOT_OBSERVED fields and rejects date, arithmetic, coverage, and numeric-domain drift", () => {
  const value = fixture();
  value.state = "PARTIALLY_MATURED";
  value.maturities[0] = { horizonSessions: 20, state: "AVAILABLE", terminalReason: null, observedAt: "2026-09-10T20:00:00Z" };
  value.summaries = [{
    horizonSessions: 20,
    periodStart: "2026-08-14", periodEnd: "2026-09-10",
    expectedObservationCount: 21, observationCount: 21,
    grossReturn: null, netReturn: "0.019", benchmarkReturn: "0.01",
    excessReturn: "0.009", holdCurrentReturn: "0.015",
    acceptedExcessVsHoldCurrent: "0.004", maximumDrawdown: null,
    totalTurnover: "0", totalCost: "0", coverageRate: "1",
  }];
  const decoded = decodeSimulatedEvaluation(value, portfolioId);
  assert.equal(decoded.summaries[0].grossReturn, null);
  assert.equal(decoded.summaries[0].maximumDrawdown, null);

  for (const [field, invalid, pattern] of [
    ["periodEnd", "2026-02-30", /invalid/],
    ["excessReturn", "0.008", /benchmark arithmetic/],
    ["acceptedExcessVsHoldCurrent", "0.003", /HOLD_CURRENT arithmetic/],
    ["coverageRate", "0.6", /coverage/],
    ["maximumDrawdown", "-1.01", /drawdown/],
    ["totalTurnover", "-0.1", /nonnegative/],
    ["totalCost", "-1", /nonnegative/],
    ["netReturn", "-1.01", /total loss/],
    ["benchmarkReturn", "-1.01", /total loss/],
    ["holdCurrentReturn", "-1.01", /total loss/],
  ] as const) {
    const drift = structuredClone(value);
    (drift.summaries[0] as Record<string, unknown>)[field] = invalid;
    assert.throws(() => decodeSimulatedEvaluation(drift, portfolioId), pattern);
  }

  const invalidInstant = structuredClone(value);
  invalidInstant.maturities[0].observedAt = "2026-02-30T20:00:00Z";
  assert.throws(() => decodeSimulatedEvaluation(invalidInstant, portfolioId), /invalid/);

  const missingSummary = structuredClone(value);
  missingSummary.summaries = [];
  assert.throws(() => decodeSimulatedEvaluation(missingSummary, portfolioId), /matching summary/);

  const exclusiveCount = structuredClone(value);
  exclusiveCount.summaries[0].expectedObservationCount = 20;
  exclusiveCount.summaries[0].observationCount = 20;
  assert.throws(() => decodeSimulatedEvaluation(exclusiveCount, portfolioId), /horizon plus entry/);
});
