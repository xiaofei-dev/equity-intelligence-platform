import assert from "node:assert/strict";
import test from "node:test";
import {
  latestProspectiveEnrollmentPath,
  loadLatestProspectiveEnrollmentFromBackend,
} from "./transport.ts";

const hash = (digit: string) => `sha256:${digit.repeat(64)}`;

function fixture(): Record<string, unknown> {
  return {
    attemptId: "00000000-0000-4000-8000-000000000031",
    attemptHash: hash("b"),
    decisionSnapshotEventHash: hash("a"),
    status: "NO_ELIGIBLE_SIGNALS",
    dataSnapshotId: "00000000-0000-4000-8000-000000000032",
    decisionAsOf: "2026-07-29T02:00:00Z",
    profileCount: 1,
    eligibleCount: 0,
    excludedCount: 1,
    signalCount: 0,
    forwardEnrollmentId: null,
    maturitySchedule: [
      {
        horizon: "ONE_WEEK",
        tradingDays: 5,
        maturesOn: "2026-08-05T20:00:00Z",
        status: "NOT_APPLICABLE",
      },
      {
        horizon: "ONE_MONTH",
        tradingDays: 20,
        maturesOn: "2026-08-26T20:00:00Z",
        status: "NOT_APPLICABLE",
      },
      {
        horizon: "THREE_MONTHS",
        tradingDays: 60,
        maturesOn: "2026-10-22T20:00:00Z",
        status: "NOT_APPLICABLE",
      },
    ],
    decisions: [
      {
        profileId: "00000000-0000-4000-8000-000000000034",
        securityId: "00000000-0000-4000-8000-000000000035",
        symbol: "NBN",
        state: "EXCLUDED",
        exclusionReasons: ["NOT_SELECTED_BY_SEALED_SCREEN"],
        longHorizonContextHash: null,
      },
    ],
    blockedReasons: [],
    longHorizonIsContextOnly: true,
  };
}

test("calls only the public latest GET route with the server identity", async () => {
  let requestedUrl = "";
  let requestedInit: RequestInit | undefined;
  const fetcher = (async (input: URL | RequestInfo, init?: RequestInit) => {
    requestedUrl = String(input);
    requestedInit = init;
    return Response.json(fixture());
  }) as typeof fetch;

  const result = await loadLatestProspectiveEnrollmentFromBackend({
    baseUrl: "http://spring.test:8080",
    identity: "tester-one",
    fetcher,
  });

  assert.equal(result.ok, true);
  assert.equal(requestedUrl, `http://spring.test:8080${latestProspectiveEnrollmentPath}`);
  assert.equal(requestedInit?.method, "GET");
  assert.deepEqual(requestedInit?.headers, {
    Accept: "application/json",
    "X-Test-Identity": "tester-one",
  });
  assert.equal(requestedInit?.body, undefined);
  if (result.ok) {
    assert.equal(result.data?.status, "NO_ELIGIBLE_SIGNALS");
  }
});

test("treats latest-route 404 as no prospective attempt", async () => {
  const result = await loadLatestProspectiveEnrollmentFromBackend({
    baseUrl: "http://spring.test:8080",
    identity: "tester-one",
    fetcher: (async () =>
      new Response("not found", { status: 404 })) as typeof fetch,
  });

  assert.deepEqual(result, { ok: true, data: null });
});

test("reports a typed contract error for an unsupported successful payload", async () => {
  const result = await loadLatestProspectiveEnrollmentFromBackend({
    baseUrl: "http://spring.test:8080",
    identity: "tester-one",
    fetcher: (async () =>
      Response.json({ status: "ENROLLED" })) as typeof fetch,
  });

  assert.equal(result.ok, false);
  if (!result.ok) {
    assert.equal(result.error.code, "FORWARD_VALIDATION_CONTRACT_ERROR");
  }
});
