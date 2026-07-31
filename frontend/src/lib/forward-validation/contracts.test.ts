import assert from "node:assert/strict";
import test from "node:test";
import {
  ForwardValidationContractError,
  decodeProspectiveEnrollment,
} from "./contracts.ts";

const attemptId = "00000000-0000-4000-8000-000000000031";
const dataSnapshotId = "00000000-0000-4000-8000-000000000032";
const profileId = "00000000-0000-4000-8000-000000000034";
const securityId = "00000000-0000-4000-8000-000000000035";
const enrollmentId = "00000000-0000-4000-8000-000000000036";
const hash = (digit: string) => `sha256:${digit.repeat(64)}`;

function fixture(
  status: "ENROLLED" | "NO_ELIGIBLE_SIGNALS" | "BLOCKED" = "ENROLLED",
): Record<string, unknown> {
  const eligible = status !== "NO_ELIGIBLE_SIGNALS";
  const applicable = status === "ENROLLED";
  return {
    attemptId,
    attemptHash: hash("b"),
    decisionSnapshotEventHash: hash("a"),
    status,
    dataSnapshotId,
    decisionAsOf: "2026-07-29T02:00:00Z",
    profileCount: 1,
    eligibleCount: eligible ? 1 : 0,
    excludedCount: eligible ? 0 : 1,
    signalCount: applicable ? 1 : 0,
    forwardEnrollmentId: applicable ? enrollmentId : null,
    maturitySchedule: [
      {
        horizon: "ONE_WEEK",
        tradingDays: 5,
        maturesOn: "2026-08-05T20:00:00Z",
        status: applicable ? "NOT_MATURED" : "NOT_APPLICABLE",
      },
      {
        horizon: "ONE_MONTH",
        tradingDays: 20,
        maturesOn: "2026-08-26T20:00:00Z",
        status: applicable ? "NOT_MATURED" : "NOT_APPLICABLE",
      },
      {
        horizon: "THREE_MONTHS",
        tradingDays: 60,
        maturesOn: "2026-10-22T20:00:00Z",
        status: applicable ? "NOT_MATURED" : "NOT_APPLICABLE",
      },
    ],
    decisions: [
      {
        profileId,
        securityId,
        symbol: "AAPL",
        state: eligible ? "ELIGIBLE" : "EXCLUDED",
        exclusionReasons: eligible ? [] : ["NOT_SELECTED_BY_SEALED_SCREEN"],
        longHorizonContextHash: hash("c"),
      },
    ],
    blockedReasons:
      status === "BLOCKED"
        ? ["COMPATIBLE_OBJECTIVE_SCREENING_RUN_REQUIRED"]
        : [],
    longHorizonIsContextOnly: true,
  };
}

test("decodes the exact prospective 5, 20, and 60 trading-day schedule", () => {
  const result = decodeProspectiveEnrollment(fixture());

  assert.equal(result.status, "ENROLLED");
  assert.deepEqual(
    result.maturitySchedule.map((item) => [
      item.horizon,
      item.tradingDays,
      item.status,
    ]),
    [
      ["ONE_WEEK", 5, "NOT_MATURED"],
      ["ONE_MONTH", 20, "NOT_MATURED"],
      ["THREE_MONTHS", 60, "NOT_MATURED"],
    ],
  );
  assert.equal(result.longHorizonIsContextOnly, true);
});

test("preserves explicit no-signal and blocked non-applicable states", () => {
  const noSignals = decodeProspectiveEnrollment(
    fixture("NO_ELIGIBLE_SIGNALS"),
  );
  const blocked = decodeProspectiveEnrollment(fixture("BLOCKED"));

  assert.equal(noSignals.status, "NO_ELIGIBLE_SIGNALS");
  assert.equal(noSignals.eligibleCount, 0);
  assert.ok(
    noSignals.maturitySchedule.every(
      (item) => item.status === "NOT_APPLICABLE",
    ),
  );
  assert.equal(blocked.status, "BLOCKED");
  assert.deepEqual(blocked.blockedReasons, [
    "COMPATIBLE_OBJECTIVE_SCREENING_RUN_REQUIRED",
  ]);
  assert.ok(
    blocked.maturitySchedule.every(
      (item) => item.status === "NOT_APPLICABLE",
    ),
  );
});

test("rejects a model label that changes the frozen prospective trading days", () => {
  const payload = fixture();
  const schedule = payload.maturitySchedule as Array<Record<string, unknown>>;
  schedule[0]!.tradingDays = 7;

  assert.throws(
    () => decodeProspectiveEnrollment(payload),
    (error) =>
      error instanceof ForwardValidationContractError &&
      error.message.includes("must be 5 for ONE_WEEK"),
  );
});

test("rejects counts that hide an excluded decision", () => {
  const payload = fixture("NO_ELIGIBLE_SIGNALS");
  payload.excludedCount = 0;

  assert.throws(
    () => decodeProspectiveEnrollment(payload),
    (error) =>
      error instanceof ForwardValidationContractError &&
      error.message.includes("internally consistent"),
  );
});

test("rejects model horizons presented as prospective outcomes", () => {
  const payload = fixture();
  payload.longHorizonIsContextOnly = false;

  assert.throws(
    () => decodeProspectiveEnrollment(payload),
    (error) =>
      error instanceof ForwardValidationContractError &&
      error.message.includes("context, not prospective outcomes"),
  );
});
