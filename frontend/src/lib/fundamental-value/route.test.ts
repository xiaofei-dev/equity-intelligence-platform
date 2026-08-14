import assert from "node:assert/strict";
import test from "node:test";
import { fundamentalValueDecisionPath } from "./route.ts";

test("route targets only the Spring public Fundamental Value endpoint", () => {
  assert.equal(
    fundamentalValueDecisionPath("10000000-0000-4000-8000-000000000001"),
    "/api/v1/fundamental-value/decisions/10000000-0000-4000-8000-000000000001",
  );
});

test("route rejects noncanonical identifiers", () => {
  assert.throws(() => fundamentalValueDecisionPath("10000000-0000-4000-8000-00000000000A"));
  assert.throws(() => fundamentalValueDecisionPath("../internal/v1/fundamental-value/decisions"));
});
