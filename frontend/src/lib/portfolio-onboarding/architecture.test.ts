import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const root = new URL("../../", import.meta.url);
const source = async (path: string) => readFile(new URL(path, root), "utf8");

test("onboarding browser workflow reaches only Spring-owned safe boundaries", async () => {
  const [workspace, mutations, preview, commit] = await Promise.all([source("app/portfolio/onboarding-workspace.tsx"), source("lib/portfolio-onboarding/mutations.ts"), source("app/api/portfolio-onboarding/csv/preview/route.ts"), source("app/api/portfolio-onboarding/csv/commit/route.ts")]);
  assert.match(workspace, /\/api\/portfolio-onboarding\/csv\/preview/); assert.match(workspace, /\/api\/portfolio-onboarding\/csv\/commit/);
  assert.match(mutations, /path\.startsWith\("\/api\/v1\/me\/"\)/); assert.match(preview, /\/snapshots\/csv\/preview/); assert.match(commit, /Expected-File-Sha256/);
  for (const value of [workspace, mutations, preview, commit]) { assert.doesNotMatch(value, /postgres|psycopg|analysis-python|localStorage|sessionStorage|writeFile/i); }
});

test("onboarding exposes multi-position, liability balance, constraint and CSV controls without a raw persistence claim", async () => {
  const [workspace, actions, commit] = await Promise.all([source("app/portfolio/onboarding-workspace.tsx"), source("app/portfolio/onboarding-actions.ts"), source("app/api/portfolio-onboarding/csv/commit/route.ts")]);
  for (const label of ["Create account", "Create portfolio", "Link accounts", "Manual complete snapshot", "Add position", "Create liability", "Record liability balance", "Portfolio constraints", "CSV snapshot", "Commit exact preview"]) assert.match(workspace, new RegExp(label));
  assert.match(workspace, /raw CSV bytes were not persisted/); assert.doesNotMatch(actions, /sourceReference|governance|TASK5:/); assert.match(commit, /\^\[0-9a-f\]\{64\}\$/);
});

test("simulation evaluation display reads only Spring and preserves the no-brokerage boundary", async () => {
  const [backend, workspace] = await Promise.all([source("lib/portfolio-decision/evaluations.ts"), source("app/portfolio/evaluation-workspace.tsx")]);
  assert.match(backend, /\/decision-scenarios`/); assert.match(backend, /\/evaluations\/latest/); assert.match(workspace, /simulation only/i); assert.match(workspace, /not a brokerage action/i); assert.doesNotMatch(backend + workspace, /analysis-python|postgres|brokerageExecution|place order/i);
});

test("browser cannot select entry sessions or inject portfolio observations", async () => {
  const [workflow, actions, backend] = await Promise.all([source("app/portfolio/decision-workflow.tsx"), source("app/portfolio/workflow-actions.ts"), source("lib/portfolio-decision/backend.ts")]);
  for (const value of [workflow, actions, backend]) assert.doesNotMatch(value, /entryCompletedSessionId|completedSessionId|benchmarkEvidenceId|tradedNotional|acceptedPositions|holdPositions/);
  assert.match(workflow, /Spring derives the first eligible completed entry session/);
  assert.doesNotMatch(backend, /portfolio-evaluations.*observations/);
});

test("exact-four and longitudinal workflow use atomic Spring commands", async () => {
  const [actions, backend, projection] = await Promise.all([source("app/portfolio/workflow-actions.ts"), source("lib/portfolio-decision/backend.ts"), source("app/portfolio/v32-workspace.tsx")]);
  assert.match(actions, /createExactFourScenarioComparison/);
  assert.doesNotMatch(actions, /for \(const scenarioType/);
  assert.match(backend, /decision-scenarios\/comparisons/);
  assert.match(backend, /longitudinal\/seal/);
  assert.match(backend, /thesis-reviews/);
  assert.match(projection, /browser never computes prices or returns/i);
});
