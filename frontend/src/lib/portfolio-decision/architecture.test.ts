import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

test("portfolio decision browser path reaches Spring only and has no order affordance", () => { const backend = readFileSync(new URL("./backend.ts", import.meta.url), "utf8"); const ui = readFileSync(new URL("../../app/portfolio/decision-scenarios.tsx", import.meta.url), "utf8"); assert.match(backend, /\/api\/v1\/me\/portfolios\/\$\{portfolioId\}\/decision-scenarios/); assert.doesNotMatch(`${backend}${ui}`, /internal\/v1|analysis-python|brokerageInstruction|orderQuantity/); assert.match(ui, /never orders or final weights/i); });

test("browser workflow exposes the complete Spring-owned decision chain", () => {
  const backend = readFileSync(new URL("./backend.ts", import.meta.url), "utf8");
  const workflow = readFileSync(new URL("../../app/portfolio/decision-workflow.tsx", import.meta.url), "utf8");
  const actions = readFileSync(new URL("../../app/portfolio/workflow-actions.ts", import.meta.url), "utf8");
  assert.match(backend, /\/contexts\/current-evidence/);
  assert.match(backend, /\/decision-scenarios/);
  assert.match(backend, /\/evaluations/);
  assert.match(backend, /\/decision-scenarios\/comparisons/);
  assert.match(actions, /createExactFourScenarioComparison/);
  assert.doesNotMatch(actions, /for \(const scenarioType of scenarioTypes\)/);
  assert.match(workflow, /Current evidence/);
  assert.match(workflow, /Four deterministic scenarios/);
  assert.match(workflow, /Human candidate permissions/);
  assert.match(workflow, /Simulation evaluation/);
  assert.doesNotMatch(`${backend}${workflow}${actions}`, /internal\/v1|analysis-python|postgres|placeOrder|brokerageExecution/);
});

test("controlled V32 commands never accept browser-computed market outcomes", () => {
  const backend = readFileSync(new URL("./backend.ts", import.meta.url), "utf8");
  const workspace = readFileSync(new URL("../../app/portfolio/v32-workspace.tsx", import.meta.url), "utf8");
  const actions = readFileSync(new URL("../../app/portfolio/workflow-actions.ts", import.meta.url), "utf8");
  assert.match(backend, /\/longitudinal\/seal/);
  assert.doesNotMatch(backend, /maturationCommandId/);
  assert.match(backend, /\/thesis-reviews/);
  assert.match(workspace, /Run controlled maturity seal/);
  assert.match(workspace, /Record root thesis review/);
  assert.match(workspace, /Supersede thesis review/);
  assert.match(actions, /INSUFFICIENT_EVIDENCE/);
  assert.doesNotMatch(`${backend}${workspace}${actions}`, /benchmarkPrice|securityPrice|grossReturn:|netReturn:|trueMaximumDrawdown:/);
});
