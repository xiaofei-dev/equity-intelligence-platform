import assert from "node:assert/strict";
import test from "node:test";

import {
  decodeQuantResearchDecision,
  deterministicQuantDecisionId,
  quantResearchContentHash,
} from "./contracts.ts";
import { quantResearchDecisionPath } from "./route.ts";

function decision(): Record<string, unknown> {
  const signals = Array.from({ length: 20 }, (_, index) => ({
    securityId: `27000000-0000-4000-8000-${String(index + 1).padStart(12, "0")}`,
    assemblyState: "MISSING",
    applicability: "INSUFFICIENT_EVIDENCE",
    assemblyReasonCodes: ["TEST_EVIDENCE_MISSING"],
    rawSignal: {
      state: "MISSING",
      reasonCodes: ["TEST_EVIDENCE_MISSING"],
      inputHash: `sha256:${"b".repeat(64)}`,
      contentHash: `sha256:${"c".repeat(64)}`,
      signalClose: null,
      features: null,
    },
    ranking: {
      state: "NOT_RANKED",
      rank: null,
      crossSectionCount: 0,
      momentum252Percentile: null,
      momentum126Percentile: null,
      compositeScore: null,
      crossSectionHash: `sha256:${"d".repeat(64)}`,
      contentHash: `sha256:${"e".repeat(64)}`,
    },
    entryPlan: null,
    researchClassification: "INSUFFICIENT_EVIDENCE",
  }));
  const body: Record<string, unknown> = {
    contractVersion: "quant-trading-research-decision-v1.1.0",
    projectionVersion: "quant-trading-public-projection-v1.1.0",
    assemblyVersion: "quant-trading-v22-assembly-v1.1.0",
    modelVersion: "QUANT-TRADING-v1.1.0",
    strategyVersion: "DUAL-MOMENTUM-TREND-v1.1.0",
    formulaVersion: "DUAL-MOMENTUM-TREND-FORMULAS-v1.1.0",
    entryExitPolicyVersion: "DUAL-MOMENTUM-TREND-ENTRY-EXIT-v1.1.0",
    modelEvidenceLabel: "NOT_VALIDATED",
    decisionDate: "2026-08-13",
    rebalanceOrdinal: 0,
    expectedSecurityCount: 20,
    assemblyManifestHash: `sha256:${"a".repeat(64)}`,
    signals,
    authority: {
      deterministicResearchSignal: true,
      deterministicFinalPortfolioWeight: false,
      automaticBrokerageExecution: false,
      llmSignalOrWeightAuthority: false,
      futureReturnGuaranteed: false,
    },
  };
  const contentHash = quantResearchContentHash(body);
  return {
    decisionId: deterministicQuantDecisionId(contentHash),
    ...body,
    contentHash,
  };
}

test("decodes a complete immutable missing decision", () => {
  const decoded = decodeQuantResearchDecision(decision());
  assert.equal(decoded.signals.length, 20);
  assert.equal(decoded.modelEvidenceLabel, "NOT_VALIDATED");
  assert.equal(decoded.authority.automaticBrokerageExecution, false);
  assert.equal(quantResearchDecisionPath(decoded.decisionId),
    `/api/v1/quant-trading/research-decisions/${decoded.decisionId}`);
});

test("rejects authority, denominator, classification, and hash drift", () => {
  for (const mutate of [
    (value: Record<string, unknown>) => ((value.authority as Record<string, unknown>).automaticBrokerageExecution = true),
    (value: Record<string, unknown>) => ((value.signals as unknown[]).pop()),
    (value: Record<string, unknown>) => (((value.signals as Record<string, unknown>[])[0]).researchClassification = "ENTRY_CANDIDATE"),
    (value: Record<string, unknown>) => (value.rebalanceOrdinal = 5),
  ]) {
    const value = decision(); mutate(value);
    assert.throws(() => decodeQuantResearchDecision(value));
  }
});

test("rejects malformed identifiers before route construction", () => {
	assert.throws(() => quantResearchDecisionPath("NOT-A-UUID"));
});
