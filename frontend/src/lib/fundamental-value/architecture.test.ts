import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import test from "node:test";

test("workspace transport targets Spring only and contains no alternate data path", () => {
  const backend = readFileSync(resolve("src", "lib", "fundamental-value", "backend.ts"), "utf8");
  const route = readFileSync(resolve("src", "lib", "fundamental-value", "route.ts"), "utf8");
  assert.match(route, /\/api\/v1\/fundamental-value\/decisions\//);
  assert.match(backend, /bindDecisionToRequestedAssembly/);
  for (const forbidden of [
    "/internal/v1/",
    "analytics.",
    "postgres",
    "yahoo",
    "eodhd",
    "providerPayload",
  ]) {
    assert.equal(`${backend}\n${route}`.toLowerCase().includes(forbidden.toLowerCase()), false);
  }
});

test("workspace UI keeps deterministic and AI authority boundaries visible", () => {
  const component = readFileSync(resolve("src", "app", "research", "components", "fundamental-value-workspace.tsx"), "utf8");
  assert.match(component, /No AI narrative is included/);
  assert.match(component, /Never a final portfolio weight/);
  assert.match(component, /does not guarantee returns/);
  assert.match(component, /decision\.identity\.securityId/);
  assert.match(component, /decision\.identity\.listingId/);
  assert.match(component, /decision\.identity\.currency/);
  assert.match(component, /Annualized expected return/);
  assert.match(component, /assessment\.projectionYears/);
  assert.doesNotMatch(component, /placeOrder|executeTrade|brokerageToken/);
});
