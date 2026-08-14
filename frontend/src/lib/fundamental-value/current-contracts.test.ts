import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { decodeCurrentFundamentalValueAssessment } from "./current-contracts.ts";
import { currentFundamentalValueAssessmentPath, latestCurrentFundamentalValueAssessmentPath } from "./current-route.ts";
import { formatPercentDecimal } from "./presentation.ts";

const fixturePath = new URL("../../../../contracts/fundamental-value-v1/internal-current-assessment-response.example.json", import.meta.url);
const fixture = JSON.parse(readFileSync(fixturePath, "utf8"));

test("decodes the Git-safe current-assessment fixture and binds its read-only path", () => {
  const decoded = decodeCurrentFundamentalValueAssessment(fixture);
  assert.equal(decoded.modelEvidenceLabel, "NOT_VALIDATED");
  assert.equal(decoded.investmentView.category, "ATTRACTIVE_FOR_FURTHER_RESEARCH");
  assert.equal(decoded.finalPortfolioWeightAuthorized, false);
  assert.equal(currentFundamentalValueAssessmentPath(decoded.assessmentId), `/api/v1/fundamental-value/current-assessments/${decoded.assessmentId}`);
  assert.equal(latestCurrentFundamentalValueAssessmentPath("GOOG"), "/api/v1/fundamental-value/current-assessments/latest/GOOG");
  assert.throws(() => latestCurrentFundamentalValueAssessmentPath("goog"));
});

test("current workspace percentage formatting preserves arbitrary precision", () => {
  assert.equal(
    formatPercentDecimal("999999999999999999999999.9999", 1),
    "100000000000000000000000000.0%",
  );
  assert.equal(formatPercentDecimal("0.0000000000000000001", 1), "0.0%");
});

test("rejects extra private evidence, authority, score, ordering and content identity drift", () => {
  const mutations = [
    { ...fixture, inputs: {} },
    { ...fixture, deterministicActionAuthorized: true },
    { ...fixture, assessmentContentHash: `sha256:${"b".repeat(64)}` },
    { ...fixture, companyQuality: { ...fixture.companyQuality, score: "101" } },
    { ...fixture, fairValue: { ...fixture.fairValue, central: "200" } },
  ];
  for (const value of mutations) assert.throws(() => decodeCurrentFundamentalValueAssessment(value));
});

test("current workspace reaches Spring only and exposes no private evidence path", () => {
  const backend = readFileSync(new URL("./current-backend.ts", import.meta.url), "utf8");
  const route = readFileSync(new URL("./current-route.ts", import.meta.url), "utf8");
  const workspace = readFileSync(new URL("../../app/research/components/current-fundamental-value-workspace.tsx", import.meta.url), "utf8");
  assert.match(route, /\/api\/v1\/fundamental-value\/current-assessments\//);
  assert.match(route, /\/latest\/\$\{symbol\}/);
  assert.doesNotMatch(`${backend}\n${route}`, /ANALYTICS_BASE_URL|postgres|provider|EODHD_API_KEY|\.post\(/i);
  assert.match(workspace, /No AI narrative, raw provider payload, automatic ranking/);
  assert.doesNotMatch(workspace, /Number\(value\)/);
});
