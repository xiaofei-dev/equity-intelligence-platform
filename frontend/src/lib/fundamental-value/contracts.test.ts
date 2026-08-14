import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import test from "node:test";
import {
  canonicalAssessmentContentHash,
  bindDecisionToRequestedAssembly,
  decodeFundamentalValueDecision,
  deterministicAssessmentId,
  FundamentalValueContractError,
  isCanonicalUuid,
} from "./contracts.ts";

function fixture(name: string): Record<string, unknown> {
  return JSON.parse(readFileSync(resolve("..", "contracts", "fundamental-value-v1", name), "utf8"));
}

function assessment(root: Record<string, unknown>): Record<string, unknown> {
  return root.deterministicAssessment as Record<string, unknown>;
}

function resealAssessment(root: Record<string, unknown>): void {
  const value = assessment(root);
  value.contentHash = canonicalAssessmentContentHash(value);
  root.assessmentId = deterministicAssessmentId(
    root.assemblyId as string,
    value.contentHash as string,
  );
}

test("Spring missing and Python-generated valid fixtures have exact TypeScript parity", () => {
  const missing = decodeFundamentalValueDecision(fixture("internal-missing-response-v1.1.example.json"));
  const valid = decodeFundamentalValueDecision(fixture("internal-valid-response-v1.1.example.json"));
  assert.equal(missing.contractVersion, "internal-fundamental-value-result-v1.1.0");
  assert.equal(missing.state, "MISSING");
  assert.equal(missing.deterministicAssessment, null);
  assert.deepEqual(missing.reasonCodes, ["REQUIRED_OPERAND_MISSING"]);
  assert.equal(valid.state, "VALID");
  assert.equal(valid.assessmentId, "ccdcaa6b-6254-5141-9aca-294a40f91292");
  assert.equal(valid.assessmentId, deterministicAssessmentId(
    valid.assemblyId,
    valid.deterministicAssessment?.contentHash as string,
  ));
  assert.equal(valid.identity.securityId, "10000000-0000-4000-8000-000000000010");
  assert.equal(valid.identity.listingId, "10000000-0000-4000-8000-000000000014");
  assert.equal(valid.identity.completedSessionDate, "2026-07-29");
  assert.equal(valid.modelEvidenceLabel, "NOT_VALIDATED");
  assert.equal(valid.deterministicAssessment?.fairValue.central, "160.50");
  assert.equal(valid.deterministicAssessment?.riskCap.ceiling, "0.02");
  assert.equal(valid.finalPortfolioWeightAuthorized, false);
  assert.equal(valid.automaticBrokerageExecutionAuthorized, false);
});

test("transport binding rejects a valid response for a different requested assembly", () => {
  const decision = decodeFundamentalValueDecision(fixture("internal-valid-response-v1.1.example.json"));
  assert.equal(bindDecisionToRequestedAssembly(decision, decision.assemblyId), decision);
  assert.throws(
    () => bindDecisionToRequestedAssembly(decision, "10000000-0000-4000-8000-000000000099"),
    FundamentalValueContractError,
  );
});

test("decoder rejects noncanonical zero, blank nested reasons, invalid reference state, and identity drift", () => {
  for (const spelling of ["-0", "-0.0", "-0.00", "-0.000000", "0.0", "0.00"]) {
    const root = fixture("internal-valid-response-v1.1.example.json");
    (assessment(root).marginOfSafety as Record<string, unknown>).low = spelling;
    resealAssessment(root);
    assert.throws(() => decodeFundamentalValueDecision(root), FundamentalValueContractError);
  }
  for (const mutate of [
    (value: Record<string, unknown>) => {
      (value.companyQuality as Record<string, unknown>).score = "0.00";
    },
    (value: Record<string, unknown>) => {
      const conditions = value.thesisEvidence as Array<Record<string, unknown>>;
      conditions[0].observedValue = "0.00";
    },
    (value: Record<string, unknown>) => {
      const valuations = value.valuations as Array<Record<string, unknown>>;
      valuations[0].terminalValueShare = "0.00";
    },
  ]) {
    const root = fixture("internal-valid-response-v1.1.example.json");
    mutate(assessment(root));
    resealAssessment(root);
    assert.throws(() => decodeFundamentalValueDecision(root), FundamentalValueContractError);
  }
  for (const mutate of [
    (root: Record<string, unknown>) => {
      assessment(root).capitalAllocationQuality = {
        state: "MISSING", score: null, reasonCodes: ["   "],
      };
      resealAssessment(root);
    },
    (root: Record<string, unknown>) => { (root.identity as Record<string, unknown>).ticker = "   "; },
    (root: Record<string, unknown>) => {
      assessment(root).referencePrice = { state: "MISSING", value: null, reasonCode: "PRICE_MISSING" };
      resealAssessment(root);
    },
    (root: Record<string, unknown>) => { (root.identity as Record<string, unknown>).completedSessionDate = "2026-02-30"; },
    (root: Record<string, unknown>) => { (root.identity as Record<string, unknown>).completedSessionDate = "2099-01-01"; },
    (root: Record<string, unknown>) => { (root.identity as Record<string, unknown>).securityId = "abcdef00-0000-4000-8000-000000000010".toUpperCase(); },
  ]) {
    const root = fixture("internal-valid-response-v1.1.example.json");
    mutate(root);
    assert.throws(() => decodeFundamentalValueDecision(root), FundamentalValueContractError);
  }
});

test("historical v1.0 fixtures remain retained but are not current wire results", () => {
  for (const name of [
    "internal-missing-response.example.json",
    "internal-valid-response.example.json",
  ]) {
    const root = fixture(name);
    assert.equal(root.contractVersion, "internal-fundamental-value-result-v1.0.0");
    assert.throws(() => decodeFundamentalValueDecision(root), FundamentalValueContractError);
  }
});

test("decoder rejects unknown fields, exponent decimals, and authority drift", () => {
  for (const mutate of [
    (root: Record<string, unknown>) => { root.providerPayload = "forbidden"; },
    (root: Record<string, unknown>) => { (root.deterministicAssessment as Record<string, unknown>).riskCap = { ceiling: "2E-2", bindingReasons: ["MODEL_EVIDENCE_CEILING"] }; },
    (root: Record<string, unknown>) => { root.finalPortfolioWeightAuthorized = true; },
  ]) {
    const root = fixture("internal-valid-response-v1.1.example.json");
    mutate(root);
    assert.throws(() => decodeFundamentalValueDecision(root), FundamentalValueContractError);
  }
});

test("decoder preserves explicit specialized and not-applicable outcomes", () => {
  const root = fixture("internal-missing-response-v1.1.example.json");
  root.state = "NOT_APPLICABLE";
  root.applicability = "SPECIALIZED_MODEL_REQUIRED";
  root.companyType = "BANK";
  root.reasonCodes = ["APPLICABILITY_SPECIALIZED_MODEL_REQUIRED"];
  const decision = decodeFundamentalValueDecision(root);
  assert.equal(decision.companyType, "BANK");
  assert.equal(decision.applicability, "SPECIALIZED_MODEL_REQUIRED");
});

test("canonical UUIDs do not collapse distinct wire spellings", () => {
  assert.equal(isCanonicalUuid("10000000-0000-4000-8000-000000000001"), true);
  assert.equal(isCanonicalUuid("00000000-0000-0000-0000-000000000000"), true);
  for (const value of [
    "10000000-0000-4000-8000-00000000000A",
    "10000000000040008000000000000001",
    "{10000000-0000-4000-8000-000000000001}",
    " 10000000-0000-4000-8000-000000000001",
  ]) assert.equal(isCanonicalUuid(value), false);
});

test("audited semantic, frozen-condition, and hash drifts fail closed", () => {
  const reseal = (root: Record<string, unknown>) => {
    resealAssessment(root);
  };
  const probes: Array<(root: Record<string, unknown>) => void> = [
    (root) => { root.sealedIngestionCutoff = "2026-07-29T20:04:59Z"; },
    (root) => {
      assessment(root).companyQuality = { state: "MISSING", score: null, reasonCodes: [] };
      reseal(root);
    },
    (root) => {
      const thesis = assessment(root).thesisEvidence as Array<Record<string, unknown>>;
      thesis[0].code = "QUALITY_ABOVE_65";
      reseal(root);
    },
    (root) => {
      const counter = assessment(root).counterThesisEvidence as Array<Record<string, unknown>>;
      counter[0].threshold = "999";
      counter[0].satisfied = false;
      reseal(root);
    },
    (root) => {
      const invalidations = assessment(root).invalidationConditions as Array<Record<string, unknown>>;
      invalidations[0].satisfied = true;
      reseal(root);
    },
    (root) => {
      root.assessmentId = "10000000-0000-4000-8000-000000000032";
    },
    (root) => {
      const thesis = assessment(root).thesisEvidence as Array<Record<string, unknown>>;
      thesis[0].observedValue = "70";
      thesis[0].satisfied = true;
      reseal(root);
    },
    (root) => {
      const thesis = assessment(root).thesisEvidence as Array<Record<string, unknown>>;
      thesis[1].observedValue = "70";
      thesis[1].satisfied = true;
      reseal(root);
    },
    (root) => {
      const thesis = assessment(root).thesisEvidence as Array<Record<string, unknown>>;
      thesis[2].observedValue = "0.20";
      thesis[2].satisfied = true;
      reseal(root);
    },
    (root) => {
      const counter = assessment(root).counterThesisEvidence as Array<Record<string, unknown>>;
      counter[0].observedValue = "70";
      counter[0].satisfied = true;
      reseal(root);
    },
    (root) => {
      const invalidations = assessment(root).invalidationConditions as Array<Record<string, unknown>>;
      invalidations[2].observedValue = "-0.1";
      invalidations[2].satisfied = true;
      reseal(root);
    },
    (root) => {
      root.riskCapCeiling = "0.99";
      (assessment(root).riskCap as Record<string, unknown>).ceiling = "0.99";
      reseal(root);
    },
    (root) => {
      const valuations = assessment(root).valuations as Array<Record<string, unknown>>;
      valuations[0].terminalValueShare = "0.99";
      reseal(root);
    },
    (root) => {
      root.claimCeiling = "FORWARD_SUPPORTED";
      assessment(root).claimCeiling = "FORWARD_SUPPORTED";
      reseal(root);
    },
    (root) => {
      assessment(root).formulaVersion = "evil-v9";
      reseal(root);
    },
    (root) => {
      (assessment(root).riskCap as Record<string, unknown>).bindingReasons = [];
      reseal(root);
    },
    (root) => {
      (assessment(root).referencePrice as Record<string, unknown>).value = "999";
    },
  ];
  for (const probe of probes) {
    const root = fixture("internal-valid-response-v1.1.example.json");
    probe(root);
    assert.throws(() => decodeFundamentalValueDecision(root), FundamentalValueContractError);
  }
});

test("UTC grammar and chronology reject offsets, naive values, and impossible dates", () => {
  for (const cutoff of [
    "2026-07-29T13:05:00-07:00",
    "2026-07-29T20:05:00",
    "2026-07-29 20:05:00Z",
    "2026-02-30T20:05:00Z",
  ]) {
    const root = fixture("internal-missing-response-v1.1.example.json");
    root.decisionCutoff = cutoff;
    assert.throws(() => decodeFundamentalValueDecision(root), FundamentalValueContractError);
  }
});
