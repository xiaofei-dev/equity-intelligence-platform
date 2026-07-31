export type ProspectiveEnrollmentStatus =
  | "ENROLLED"
  | "NO_ELIGIBLE_SIGNALS"
  | "BLOCKED";

export type ProspectiveDecisionState = "ELIGIBLE" | "EXCLUDED";
export type ProspectiveMaturityStatus = "NOT_MATURED" | "NOT_APPLICABLE";
export type ProspectiveHorizon = "ONE_WEEK" | "ONE_MONTH" | "THREE_MONTHS";

export type ProspectiveMaturitySchedule = {
  horizon: ProspectiveHorizon;
  tradingDays: 5 | 20 | 60;
  maturesOn: string;
  status: ProspectiveMaturityStatus;
};

export type ProspectiveSecurityDecision = {
  profileId: string;
  securityId: string;
  symbol: string;
  state: ProspectiveDecisionState;
  exclusionReasons: string[];
  longHorizonContextHash: string | null;
};

export type ProspectiveEnrollment = {
  attemptId: string;
  attemptHash: string;
  decisionSnapshotEventHash: string;
  status: ProspectiveEnrollmentStatus;
  dataSnapshotId: string;
  decisionAsOf: string;
  profileCount: number;
  eligibleCount: number;
  excludedCount: number;
  signalCount: number;
  forwardEnrollmentId: string | null;
  maturitySchedule: ProspectiveMaturitySchedule[];
  decisions: ProspectiveSecurityDecision[];
  blockedReasons: string[];
  longHorizonIsContextOnly: true;
};

export class ForwardValidationContractError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ForwardValidationContractError";
  }
}

const uuidPattern =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const sha256Pattern = /^sha256:[0-9a-f]{64}$/;
const horizonDays: Record<ProspectiveHorizon, 5 | 20 | 60> = {
  ONE_WEEK: 5,
  ONE_MONTH: 20,
  THREE_MONTHS: 60,
};
const horizonOrder: ProspectiveHorizon[] = [
  "ONE_WEEK",
  "ONE_MONTH",
  "THREE_MONTHS",
];

function fail(path: string, expectation: string): never {
  throw new ForwardValidationContractError(`${path} must be ${expectation}`);
}

function record(value: unknown, path: string): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    fail(path, "an object");
  }
  return value as Record<string, unknown>;
}

function string(value: unknown, path: string): string {
  if (typeof value !== "string" || value.length === 0) {
    fail(path, "a non-empty string");
  }
  return value;
}

function uuid(value: unknown, path: string): string {
  const parsed = string(value, path);
  return uuidPattern.test(parsed) ? parsed : fail(path, "a UUID");
}

function hash(value: unknown, path: string): string {
  const parsed = string(value, path);
  return sha256Pattern.test(parsed)
    ? parsed
    : fail(path, "a lowercase sha256 hash");
}

function timestamp(value: unknown, path: string): string {
  const parsed = string(value, path);
  return Number.isNaN(Date.parse(parsed))
    ? fail(path, "an ISO-8601 timestamp")
    : parsed;
}

function count(value: unknown, path: string): number {
  return Number.isInteger(value) && Number(value) >= 0
    ? Number(value)
    : fail(path, "a non-negative integer");
}

function strings(value: unknown, path: string): string[] {
  if (!Array.isArray(value)) fail(path, "an array");
  return value.map((item, index) => string(item, `${path}[${index}]`));
}

function oneOf<T extends string>(
  value: unknown,
  path: string,
  options: readonly T[],
): T {
  return typeof value === "string" && options.includes(value as T)
    ? (value as T)
    : fail(path, `one of ${options.join(", ")}`);
}

function nullableUuid(value: unknown, path: string): string | null {
  return value === null ? null : uuid(value, path);
}

function nullableHash(value: unknown, path: string): string | null {
  return value === null ? null : hash(value, path);
}

function decodeSchedule(
  value: unknown,
  path: string,
): ProspectiveMaturitySchedule {
  const source = record(value, path);
  const horizon = oneOf(source.horizon, `${path}.horizon`, horizonOrder);
  const tradingDays = count(source.tradingDays, `${path}.tradingDays`);
  if (tradingDays !== horizonDays[horizon]) {
    fail(`${path}.tradingDays`, `${horizonDays[horizon]} for ${horizon}`);
  }
  return {
    horizon,
    tradingDays: tradingDays as 5 | 20 | 60,
    maturesOn: timestamp(source.maturesOn, `${path}.maturesOn`),
    status: oneOf(
      source.status,
      `${path}.status`,
      ["NOT_MATURED", "NOT_APPLICABLE"] as const,
    ),
  };
}

function decodeDecision(
  value: unknown,
  path: string,
): ProspectiveSecurityDecision {
  const source = record(value, path);
  const state = oneOf(
    source.state,
    `${path}.state`,
    ["ELIGIBLE", "EXCLUDED"] as const,
  );
  const exclusionReasons = strings(
    source.exclusionReasons,
    `${path}.exclusionReasons`,
  );
  if (state === "ELIGIBLE" && exclusionReasons.length > 0) {
    fail(`${path}.exclusionReasons`, "empty for an eligible decision");
  }
  if (state === "EXCLUDED" && exclusionReasons.length === 0) {
    fail(`${path}.exclusionReasons`, "non-empty for an excluded decision");
  }
  return {
    profileId: uuid(source.profileId, `${path}.profileId`),
    securityId: uuid(source.securityId, `${path}.securityId`),
    symbol: string(source.symbol, `${path}.symbol`),
    state,
    exclusionReasons,
    longHorizonContextHash: nullableHash(
      source.longHorizonContextHash,
      `${path}.longHorizonContextHash`,
    ),
  };
}

export function decodeProspectiveEnrollment(
  value: unknown,
  path = "$",
): ProspectiveEnrollment {
  const source = record(value, path);
  const status = oneOf(
    source.status,
    `${path}.status`,
    ["ENROLLED", "NO_ELIGIBLE_SIGNALS", "BLOCKED"] as const,
  );
  if (!Array.isArray(source.maturitySchedule)) {
    fail(`${path}.maturitySchedule`, "an array");
  }
  const decodedSchedule = source.maturitySchedule.map((item, index) =>
    decodeSchedule(item, `${path}.maturitySchedule[${index}]`),
  );
  const byHorizon = new Map(
    decodedSchedule.map((item) => [item.horizon, item]),
  );
  if (
    decodedSchedule.length !== horizonOrder.length ||
    byHorizon.size !== horizonOrder.length
  ) {
    fail(
      `${path}.maturitySchedule`,
      "the unique ONE_WEEK, ONE_MONTH, and THREE_MONTHS schedule",
    );
  }
  const maturitySchedule = horizonOrder.map(
    (horizon) => byHorizon.get(horizon)!,
  );

  if (!Array.isArray(source.decisions)) {
    fail(`${path}.decisions`, "an array");
  }
  const decisions = source.decisions.map((item, index) =>
    decodeDecision(item, `${path}.decisions[${index}]`),
  );
  const profileCount = count(source.profileCount, `${path}.profileCount`);
  const eligibleCount = count(source.eligibleCount, `${path}.eligibleCount`);
  const excludedCount = count(source.excludedCount, `${path}.excludedCount`);
  const signalCount = count(source.signalCount, `${path}.signalCount`);
  const decisionEligibleCount = decisions.filter(
    (item) => item.state === "ELIGIBLE",
  ).length;

  if (
    profileCount !== decisions.length ||
    eligibleCount + excludedCount !== profileCount ||
    decisionEligibleCount !== eligibleCount
  ) {
    fail(
      path,
      "internally consistent profile, eligibility, exclusion, and decision counts",
    );
  }

  const blockedReasons = strings(
    source.blockedReasons,
    `${path}.blockedReasons`,
  );
  const forwardEnrollmentId = nullableUuid(
    source.forwardEnrollmentId,
    `${path}.forwardEnrollmentId`,
  );
  const expectedMaturity =
    status === "ENROLLED" ? "NOT_MATURED" : "NOT_APPLICABLE";
  if (maturitySchedule.some((item) => item.status !== expectedMaturity)) {
    fail(
      `${path}.maturitySchedule`,
      `${expectedMaturity} for ${status}`,
    );
  }
  if (
    (status === "ENROLLED" &&
      (forwardEnrollmentId === null || signalCount === 0)) ||
    (status !== "ENROLLED" &&
      (forwardEnrollmentId !== null || signalCount !== 0)) ||
    (status === "BLOCKED" && blockedReasons.length === 0)
  ) {
    fail(path, `a consistent ${status} prospective state`);
  }
  if (source.longHorizonIsContextOnly !== true) {
    fail(
      `${path}.longHorizonIsContextOnly`,
      "true because model horizons are context, not prospective outcomes",
    );
  }

  return {
    attemptId: uuid(source.attemptId, `${path}.attemptId`),
    attemptHash: hash(source.attemptHash, `${path}.attemptHash`),
    decisionSnapshotEventHash: hash(
      source.decisionSnapshotEventHash,
      `${path}.decisionSnapshotEventHash`,
    ),
    status,
    dataSnapshotId: uuid(source.dataSnapshotId, `${path}.dataSnapshotId`),
    decisionAsOf: timestamp(source.decisionAsOf, `${path}.decisionAsOf`),
    profileCount,
    eligibleCount,
    excludedCount,
    signalCount,
    forwardEnrollmentId,
    maturitySchedule,
    decisions,
    blockedReasons,
    longHorizonIsContextOnly: true,
  };
}
