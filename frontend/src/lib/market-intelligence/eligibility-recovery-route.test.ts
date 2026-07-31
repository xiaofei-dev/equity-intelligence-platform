import assert from "node:assert/strict";
import test from "node:test";
import { buildEligibilityRecoveryStatusPath } from "./eligibility-recovery-route.ts";

test("builds only the Spring public eligibility-recovery GET path", () => {
  const path = buildEligibilityRecoveryStatusPath({
    dataSnapshotId: "00000000-0000-4000-8000-000000000010",
    universeVersion: "market-intelligence-closed-test-us-v1.0.0",
    asOf: "2026-07-29T02:57:08.988871Z",
  });

  const url = new URL(path, "http://spring.test");
  assert.equal(
    url.pathname,
    "/api/v1/market-intelligence/eligibility-recovery/status/latest",
  );
  assert.deepEqual(Object.fromEntries(url.searchParams), {
    dataSnapshotId: "00000000-0000-4000-8000-000000000010",
    universeVersion: "market-intelligence-closed-test-us-v1.0.0",
    asOf: "2026-07-29T02:57:08.988871Z",
  });
});
