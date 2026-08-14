import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import test from "node:test";
import { decodeFundamentalValueDecision } from "./contracts.ts";
import { formatPercentDecimal, presentFundamentalValueDecision, rangeText } from "./presentation.ts";

function fixture(name: string): Record<string, unknown> {
  return JSON.parse(readFileSync(resolve("..", "contracts", "fundamental-value-v1", name), "utf8"));
}

test("workspace presentation exposes usable valuation and keeps cap a ceiling", () => {
  const decision = decodeFundamentalValueDecision(fixture("internal-valid-response-v1.1.example.json"));
  const view = presentFundamentalValueDecision(decision);
  assert.equal(view.mode, "USABLE");
  assert.match(view.summary, /not a recommendation or final portfolio weight/i);
  assert.equal(rangeText(decision.deterministicAssessment!.fairValue, { currency: "USD" }), "USD 102.00 – USD 160.50 – USD 388.67");
  assert.equal(rangeText(decision.deterministicAssessment!.expectedReturn, { percent: true }), "4.3% – 15.9% – 40.2%");
});

test("workspace presentation distinguishes missing, specialized, and not applicable", () => {
  const missingRaw = fixture("internal-missing-response-v1.1.example.json");
  assert.equal(presentFundamentalValueDecision(decodeFundamentalValueDecision(missingRaw)).mode, "NON_USABLE");
  const specializedRaw = structuredClone(missingRaw);
  specializedRaw.state = "NOT_APPLICABLE";
  specializedRaw.applicability = "SPECIALIZED_MODEL_REQUIRED";
  specializedRaw.companyType = "BANK";
  specializedRaw.reasonCodes = ["APPLICABILITY_SPECIALIZED_MODEL_REQUIRED"];
  assert.equal(presentFundamentalValueDecision(decodeFundamentalValueDecision(specializedRaw)).mode, "SPECIALIZED");
  const benchmarkRaw = structuredClone(missingRaw);
  benchmarkRaw.state = "NOT_APPLICABLE";
  benchmarkRaw.applicability = "NOT_APPLICABLE";
  benchmarkRaw.companyType = "BENCHMARK";
  benchmarkRaw.reasonCodes = ["APPLICABILITY_NOT_APPLICABLE"];
  assert.equal(presentFundamentalValueDecision(decodeFundamentalValueDecision(benchmarkRaw)).mode, "NOT_APPLICABLE");
});

test("percent display uses exact decimal strings for tiny and huge values", () => {
  assert.equal(formatPercentDecimal("0.0000000000000000001", 1), "0.0%");
  assert.equal(
    formatPercentDecimal("999999999999999999999999.9999", 1),
    "100000000000000000000000000.0%",
  );
  assert.equal(formatPercentDecimal("0.005", 0), "1%");
  assert.equal(formatPercentDecimal("-0.0001", 1), "0.0%");
  assert.equal(formatPercentDecimal("0.0100", 0), "1%");
  assert.throws(() => formatPercentDecimal("1E-7", 1));
});
