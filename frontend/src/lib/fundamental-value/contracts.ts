import { createHash } from "node:crypto";

export const FUNDAMENTAL_VALUE_RESULT_VERSION =
  "internal-fundamental-value-result-v1.1.0" as const;

export type DecisionIdentity = {
  securityId: string; companyId: string; instrumentId: string;
  shareClassId: string; listingId: string; tickerAssignmentId: string;
  ticker: string; mic: string; currency: string; completedSessionDate: string;
};

export type EvidenceState =
  | "VALID"
  | "MISSING"
  | "STALE"
  | "INVALID"
  | "NOT_APPLICABLE"
  | "EXCLUDED";
export type Applicability =
  | "APPLICABLE"
  | "SPECIALIZED_MODEL_REQUIRED"
  | "NOT_APPLICABLE"
  | "INSUFFICIENT_EVIDENCE";

export type ValueRange = {
  state: EvidenceState;
  low: string | null;
  central: string | null;
  high: string | null;
  reasonCodes: string[];
};

export type Dimension = {
  state: EvidenceState;
  score: string | null;
  reasonCodes: string[];
};

export type ValuationMethod = ValueRange & {
  method:
    | "FCFF_DCF"
    | "NORMALIZED_OWNER_EARNINGS"
    | "EARNINGS_POWER"
    | "COMPARABLE_CROSS_CHECK";
  terminalValueShare: string | null;
};

export type Condition = {
  code: string;
  state: EvidenceState;
  observedValue: string | null;
  threshold: string;
  satisfied: boolean | null;
  reasonCodes: string[];
};

export type FundamentalValueAssessment = {
  companyType: string;
  applicability: "APPLICABLE";
  referencePrice: {
    state: EvidenceState;
    value: string | null;
    reasonCode: string | null;
  };
  currency: string;
  projectionYears: number;
  companyQuality: Dimension;
  financialResilience: Dimension;
  earningsAndCashFlowQuality: Dimension;
  capitalAllocationQuality: Dimension;
  valuations: ValuationMethod[];
  fairValue: ValueRange;
  marginOfSafety: ValueRange;
  expectedReturn: ValueRange;
  downsideRisk: Dimension;
  claimCeiling: string;
  thesisEvidence: Condition[];
  counterThesisEvidence: Condition[];
  invalidationConditions: Condition[];
  riskCap: { ceiling: string; bindingReasons: string[] };
  modelEvidenceLabel: "NOT_VALIDATED";
  modelVersion: string;
  strategyVersion: string;
  formulaVersion: string;
  aggregationVersion: string;
  riskPolicyVersion: string;
  assumptionPolicyVersion: string;
  inputHash: string;
  contentHash: string;
  deterministicRankingAuthorized: false;
  finalPortfolioWeightAuthorized: false;
  automaticBrokerageExecutionAuthorized: false;
};

export type FundamentalValueDecision = {
  contractVersion: typeof FUNDAMENTAL_VALUE_RESULT_VERSION;
  assemblyId: string;
  assessmentId: string | null;
  identity: DecisionIdentity;
  state: EvidenceState;
  applicability: Applicability;
  companyType: string;
  reasonCodes: string[];
  coreInvocationAuthorized: boolean;
  manifestContentHash: string;
  inputSealContentHash: string;
  decisionCutoff: string;
  sealedIngestionCutoff: string;
  modelEvidenceLabel: "NOT_VALIDATED" | null;
  claimCeiling: string | null;
  riskCapCeiling: string | null;
  deterministicAssessment: FundamentalValueAssessment | null;
  finalPortfolioWeightAuthorized: false;
  automaticBrokerageExecutionAuthorized: false;
};

export class FundamentalValueContractError extends Error {}

const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const hash = /^sha256:[0-9a-f]{64}$/;
const decimal = /^(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$|^-(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$/;
const utcInstant = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,9}))?Z$/;
const assessmentPersistenceVersion = "fundamental-value-assessment-persistence-v1.0.0";
const urlNamespace = Uint8Array.from([
  0x6b, 0xa7, 0xb8, 0x11, 0x9d, 0xad, 0x11, 0xd1,
  0x80, 0xb4, 0x00, 0xc0, 0x4f, 0xd4, 0x30, 0xc8,
]);
const claimCeilings = new Set([
  "FULL_CURRENT_DECISION",
  "LIMITED_MISSING_ADVANCED_EVIDENCE",
  "BLOCKED_MATERIAL_REFINANCING_UNCERTAINTY",
]);
const riskCaps = new Set(["0", "0.01", "0.02"]);
const versions = {
  modelVersion: "FUNDAMENTAL-VALUE-v1.0.0",
  strategyVersion: "LONG-TERM-CORE-v1.0.0",
  formulaVersion: "fundamental-value-formulas-v1.1.0",
  aggregationVersion: "FUNDAMENTAL-VALUE-WEIGHTED-MEDIAN-QUANTILE-v1.0.0",
  riskPolicyVersion: "LONG-TERM-CORE-RISK-CAP-TIERS-v1.0.0",
  assumptionPolicyVersion: "fundamental-value-assumptions-v1.1.0",
} as const;
const states = new Set<EvidenceState>([
  "VALID", "MISSING", "STALE", "INVALID", "NOT_APPLICABLE", "EXCLUDED",
]);
const applicability = new Set<Applicability>([
  "APPLICABLE", "SPECIALIZED_MODEL_REQUIRED", "NOT_APPLICABLE", "INSUFFICIENT_EVIDENCE",
]);

function fail(message: string): never {
  throw new FundamentalValueContractError(message);
}

function record(value: unknown, fields: readonly string[], label: string): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) fail(`${label} must be an object.`);
  const result = value as Record<string, unknown>;
  if (Object.keys(result).sort().join("|") !== [...fields].sort().join("|")) fail(`${label} fields are invalid.`);
  return result;
}

function text(value: unknown, label: string): string {
  if (typeof value !== "string" || value.trim().length === 0) fail(`${label} must be non-blank text.`);
  return value;
}

function optionalText(value: unknown, label: string): string | null {
  return value === null ? null : text(value, label);
}

function stringList(value: unknown, label: string): string[] {
  if (!Array.isArray(value) || !value.every((item) => typeof item === "string" && item.trim().length > 0)) fail(`${label} must be a non-blank text array.`);
  return [...value];
}

function state(value: unknown): EvidenceState {
  if (typeof value !== "string" || !states.has(value as EvidenceState)) fail("Evidence state is unsupported.");
  return value as EvidenceState;
}

function decimalText(value: unknown, label: string): string {
  const result = text(value, label);
  if (!decimal.test(result) || (/^-?0(?:\.0+)?$/.test(result) && result !== "0")) fail(`${label} is not canonical decimal text.`);
  return result;
}

function optionalDecimal(value: unknown, label: string): string | null {
  return value === null ? null : decimalText(value, label);
}

function compareDecimal(left: string, right: string): number {
  const split = (value: string) => {
    const negative = value.startsWith("-");
    const [integer, fraction = ""] = (negative ? value.slice(1) : value).split(".");
    return { negative, integer, fraction };
  };
  const a = split(left);
  const b = split(right);
  if (a.negative !== b.negative) return a.negative ? -1 : 1;
  const direction = a.negative ? -1 : 1;
  if (a.integer.length !== b.integer.length) return a.integer.length < b.integer.length ? -direction : direction;
  if (a.integer !== b.integer) return a.integer < b.integer ? -direction : direction;
  const width = Math.max(a.fraction.length, b.fraction.length);
  const af = a.fraction.padEnd(width, "0");
  const bf = b.fraction.padEnd(width, "0");
  return af === bf ? 0 : af < bf ? -direction : direction;
}

function snakeCase(value: string): string {
  return value.replace(/([a-z0-9])([A-Z])/g, "$1_$2").toLowerCase();
}

function canonicalValue(value: unknown, root = false): unknown {
  if (Array.isArray(value)) return value.map((item) => canonicalValue(item));
  if (typeof value === "object" && value !== null) {
    const source = value as Record<string, unknown>;
    const result: Record<string, unknown> = {};
    for (const key of Object.keys(source).sort((left, right) => {
      const a = snakeCase(left);
      const b = snakeCase(right);
      return a < b ? -1 : a > b ? 1 : 0;
    })) {
      if (root && key === "contentHash") continue;
      result[snakeCase(key)] = canonicalValue(source[key]);
    }
    return result;
  }
  if (value === null || typeof value === "string" || typeof value === "boolean" || Number.isInteger(value)) return value;
  fail("Assessment contains a non-canonical scalar.");
}

export function canonicalAssessmentContentHash(value: Record<string, unknown>): string {
  const payload = JSON.stringify(canonicalValue(value, true));
  return `sha256:${createHash("sha256").update(payload, "utf8").digest("hex")}`;
}

export function deterministicAssessmentId(
  assemblyId: string,
  contentHash: string,
): string {
  const name = `${assessmentPersistenceVersion}:${assemblyId}:${contentHash}`;
  const digest = createHash("sha1").update(urlNamespace).update(name, "utf8").digest();
  digest[6] = (digest[6] & 0x0f) | 0x50;
  digest[8] = (digest[8] & 0x3f) | 0x80;
  const hex = Array.from(digest.subarray(0, 16), (byte) =>
    byte.toString(16).padStart(2, "0"),
  ).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

function instant(value: unknown, label: string): string {
  const result = text(value, label);
  const match = utcInstant.exec(result);
  if (!match) fail(`${label} is not a canonical UTC instant.`);
  const [, year, month, day, hour, minute, second] = match;
  const observed = new Date(`${year}-${month}-${day}T${hour}:${minute}:${second}Z`);
  if (Number.isNaN(observed.valueOf()) || observed.toISOString().slice(0, 19) !== `${year}-${month}-${day}T${hour}:${minute}:${second}`) fail(`${label} is not a real UTC instant.`);
  return result;
}

function instantNanoseconds(value: string): bigint {
  const match = utcInstant.exec(value);
  if (!match) fail("UTC instant is invalid.");
  const [, year, month, day, hour, minute, second, fraction = ""] = match;
  const seconds = BigInt(Date.parse(`${year}-${month}-${day}T${hour}:${minute}:${second}Z`) / 1000);
  return seconds * BigInt("1000000000") + BigInt(fraction.padEnd(9, "0"));
}

function calendarDate(value: unknown, label: string): string {
  const result = text(value, label);
  if (!/^\d{4}-\d{2}-\d{2}$/.test(result)) fail(`${label} is not a canonical calendar date.`);
  const observed = new Date(`${result}T00:00:00Z`);
  if (Number.isNaN(observed.valueOf()) || observed.toISOString().slice(0, 10) !== result) fail(`${label} is not a real calendar date.`);
  return result;
}

function decodeIdentity(value: unknown): DecisionIdentity {
  const fields = ["securityId", "companyId", "instrumentId", "shareClassId", "listingId", "tickerAssignmentId", "ticker", "mic", "currency", "completedSessionDate"] as const;
  const item = record(value, fields, "identity");
  for (const field of fields.slice(0, 6)) if (typeof item[field] !== "string" || !uuid.test(item[field] as string)) fail(`identity.${field} is not canonical.`);
  if (typeof item.ticker !== "string" || !/^[A-Z0-9][A-Z0-9.\-]{0,31}$/.test(item.ticker)) fail("identity.ticker is invalid.");
  if (typeof item.mic !== "string" || !/^[A-Z0-9]{4}$/.test(item.mic)) fail("identity.mic is invalid.");
  if (typeof item.currency !== "string" || !/^[A-Z]{3}$/.test(item.currency)) fail("identity.currency is invalid.");
  return { securityId: item.securityId as string, companyId: item.companyId as string, instrumentId: item.instrumentId as string, shareClassId: item.shareClassId as string, listingId: item.listingId as string, tickerAssignmentId: item.tickerAssignmentId as string, ticker: item.ticker, mic: item.mic, currency: item.currency, completedSessionDate: calendarDate(item.completedSessionDate, "identity.completedSessionDate") } as DecisionIdentity;
}

function decodeDimension(value: unknown, label: string): Dimension {
  const item = record(value, ["state", "score", "reasonCodes"], label);
  const itemState = state(item.state);
  const reasons = stringList(item.reasonCodes, `${label}.reasonCodes`);
  const score = optionalDecimal(item.score, `${label}.score`);
  if (itemState === "VALID" ? score === null || reasons.length !== 0 : score !== null || reasons.length === 0) fail(`${label} state/value parity is invalid.`);
  if (score !== null && (compareDecimal(score, "0") < 0 || compareDecimal(score, "100") > 0)) fail(`${label}.score is outside 0 through 100.`);
  return { state: itemState, score, reasonCodes: reasons };
}

function decodeRange(value: unknown, label: string, positive = false): ValueRange {
  const item = record(value, ["state", "low", "central", "high", "reasonCodes"], label);
  const itemState = state(item.state);
  const low = optionalDecimal(item.low, `${label}.low`);
  const central = optionalDecimal(item.central, `${label}.central`);
  const high = optionalDecimal(item.high, `${label}.high`);
  const reasons = stringList(item.reasonCodes, `${label}.reasonCodes`);
  const complete = low !== null && central !== null && high !== null;
  if (itemState === "VALID" ? !complete || reasons.length !== 0 : complete || low !== null || central !== null || high !== null || reasons.length === 0) fail(`${label} state/range parity is invalid.`);
  if (complete && !(compareDecimal(low, central) <= 0 && compareDecimal(central, high) <= 0)) fail(`${label} ordering is invalid.`);
  if (complete && positive && compareDecimal(low, "0") <= 0) fail(`${label} must be positive.`);
  return { state: itemState, low, central, high, reasonCodes: reasons };
}

type Comparison = "AT_LEAST" | "ABOVE" | "BELOW";
type ConditionSpec = { code: string; threshold: string; comparison: Comparison };

function decodeCondition(value: unknown, label: string, spec: ConditionSpec): Condition {
  const item = record(value, ["code", "state", "observedValue", "threshold", "satisfied", "reasonCodes"], label);
  const itemState = state(item.state);
  const observedValue = optionalDecimal(item.observedValue, `${label}.observedValue`);
  if (item.satisfied !== null && typeof item.satisfied !== "boolean") fail(`${label}.satisfied is invalid.`);
  const reasons = stringList(item.reasonCodes, `${label}.reasonCodes`);
  if (itemState === "VALID" ? observedValue === null || typeof item.satisfied !== "boolean" || reasons.length !== 0 : observedValue !== null || item.satisfied !== null || reasons.length === 0) fail(`${label} state parity is invalid.`);
  if (item.code !== spec.code || item.threshold !== spec.threshold) fail(`${label} frozen condition contract is invalid.`);
  if (itemState === "VALID" && observedValue !== null) {
    const comparison = compareDecimal(observedValue, spec.threshold);
    const expected = spec.comparison === "AT_LEAST" ? comparison >= 0 : spec.comparison === "ABOVE" ? comparison > 0 : comparison < 0;
    if (item.satisfied !== expected) fail(`${label}.satisfied is inconsistent with the frozen comparison.`);
  }
  return { code: spec.code, state: itemState, observedValue, threshold: spec.threshold, satisfied: item.satisfied as boolean | null, reasonCodes: reasons };
}

function bindConditionSource(
  condition: Condition,
  source: Dimension | ValueRange,
  sourceValue: string | null,
  label: string,
): void {
  const reasonsMatch = condition.reasonCodes.length === source.reasonCodes.length
    && condition.reasonCodes.every((reason, index) => reason === source.reasonCodes[index]);
  if (condition.state !== source.state || condition.observedValue !== sourceValue || !reasonsMatch) {
    fail(`${label} is not bound to its exposed source value.`);
  }
}

function decodeAssessment(value: unknown): FundamentalValueAssessment {
  const fields = ["companyType", "applicability", "referencePrice", "currency", "projectionYears", "companyQuality", "financialResilience", "earningsAndCashFlowQuality", "capitalAllocationQuality", "valuations", "fairValue", "marginOfSafety", "expectedReturn", "downsideRisk", "claimCeiling", "thesisEvidence", "counterThesisEvidence", "invalidationConditions", "riskCap", "modelEvidenceLabel", "modelVersion", "strategyVersion", "formulaVersion", "aggregationVersion", "riskPolicyVersion", "assumptionPolicyVersion", "inputHash", "contentHash", "deterministicRankingAuthorized", "finalPortfolioWeightAuthorized", "automaticBrokerageExecutionAuthorized"] as const;
  const item = record(value, fields, "deterministicAssessment");
  if (item.companyType !== "MATURE_OPERATING_COMPANY" || item.applicability !== "APPLICABLE" || item.modelEvidenceLabel !== "NOT_VALIDATED") fail("Assessment applicability or evidence label is invalid.");
  if (!Number.isInteger(item.projectionYears) || (item.projectionYears as number) < 3 || (item.projectionYears as number) > 10) fail("Assessment projectionYears is invalid.");
  if (typeof item.currency !== "string" || !/^[A-Z]{3}$/.test(item.currency)) fail("Assessment currency is invalid.");
  const reference = record(item.referencePrice, ["state", "value", "reasonCode"], "referencePrice");
  const referenceState = state(reference.state);
  const referenceValue = optionalDecimal(reference.value, "referencePrice.value");
  const referenceReason = optionalText(reference.reasonCode, "referencePrice.reasonCode");
  if (referenceState !== "VALID" || referenceValue === null || referenceReason !== null || compareDecimal(referenceValue, "0") <= 0) fail("A valid assessment requires a positive valid reference price.");
  if (!Array.isArray(item.valuations) || item.valuations.length !== 4) fail("Valuation method cardinality is invalid.");
  const methods = ["FCFF_DCF", "NORMALIZED_OWNER_EARNINGS", "EARNINGS_POWER", "COMPARABLE_CROSS_CHECK"] as const;
  const valuations = item.valuations.map((raw, index) => {
    const method = record(raw, ["method", "state", "low", "central", "high", "reasonCodes", "terminalValueShare"], `valuations[${index}]`);
    if (method.method !== methods[index]) fail("Valuation method ordering is invalid.");
    const range = decodeRange({ state: method.state, low: method.low, central: method.central, high: method.high, reasonCodes: method.reasonCodes }, `valuations[${index}]`, true);
    const share = optionalDecimal(method.terminalValueShare, `valuations[${index}].terminalValueShare`);
    if ((index === 0 && range.state === "VALID") !== (share !== null)) fail("Terminal value share parity is invalid.");
    if (share !== null && (compareDecimal(share, "0") < 0 || compareDecimal(share, "0.80") > 0)) fail("FCFF terminal value share exceeds the frozen bound.");
    return { ...range, method: methods[index], terminalValueShare: share };
  });
  const companyQuality = decodeDimension(item.companyQuality, "companyQuality");
  const financialResilience = decodeDimension(item.financialResilience, "financialResilience");
  const earningsAndCashFlowQuality = decodeDimension(item.earningsAndCashFlowQuality, "earningsAndCashFlowQuality");
  const capitalAllocationQuality = decodeDimension(item.capitalAllocationQuality, "capitalAllocationQuality");
  const fairValue = decodeRange(item.fairValue, "fairValue", true);
  const marginOfSafety = decodeRange(item.marginOfSafety, "marginOfSafety");
  const expectedReturn = decodeRange(item.expectedReturn, "expectedReturn");
  const downsideRisk = decodeDimension(item.downsideRisk, "downsideRisk");
  const conditionArray = (raw: unknown, label: string, specs: ConditionSpec[]) => {
    if (!Array.isArray(raw) || raw.length !== specs.length) fail(`${label} cardinality is invalid.`);
    return raw.map((entry, index) => decodeCondition(entry, `${label}[${index}]`, specs[index]));
  };
  const risk = record(item.riskCap, ["ceiling", "bindingReasons"], "riskCap");
  const riskReasons = stringList(risk.bindingReasons, "riskCap.bindingReasons");
  if (riskReasons.length === 0) fail("riskCap.bindingReasons must be non-empty.");
  for (const field of ["deterministicRankingAuthorized", "finalPortfolioWeightAuthorized", "automaticBrokerageExecutionAuthorized"] as const) if (item[field] !== false) fail(`${field} must remain false.`);
  for (const field of ["inputHash", "contentHash"] as const) if (typeof item[field] !== "string" || !hash.test(item[field] as string)) fail(`${field} is invalid.`);
  for (const [field, expected] of Object.entries(versions)) if (item[field] !== expected) fail(`${field} is unsupported.`);
  const claimCeiling = text(item.claimCeiling, "claimCeiling");
  if (!claimCeilings.has(claimCeiling)) fail("claimCeiling is unsupported.");
  const riskCeiling = decimalText(risk.ceiling, "riskCap.ceiling");
  if (!riskCaps.has(riskCeiling)) fail("riskCap.ceiling is unsupported.");
  if (claimCeiling === "LIMITED_MISSING_ADVANCED_EVIDENCE" && compareDecimal(riskCeiling, "0.01") > 0) fail("Limited claim ceiling cannot carry this risk cap.");
  if (claimCeiling === "BLOCKED_MATERIAL_REFINANCING_UNCERTAINTY" && riskCeiling !== "0") fail("Blocked refinancing uncertainty requires a zero cap.");
  const observedHash = canonicalAssessmentContentHash(item);
  if (observedHash !== item.contentHash) fail("Assessment content hash is invalid.");
  const thesisEvidence = conditionArray(item.thesisEvidence, "thesisEvidence", [
    { code: "QUALITY_AT_LEAST_65", threshold: "65", comparison: "AT_LEAST" },
    { code: "RESILIENCE_AT_LEAST_60", threshold: "60", comparison: "AT_LEAST" },
    { code: "CONSERVATIVE_MARGIN_OF_SAFETY_AT_LEAST_15_PERCENT", threshold: "0.15", comparison: "AT_LEAST" },
  ]);
  const counterThesisEvidence = conditionArray(item.counterThesisEvidence, "counterThesisEvidence", [
    { code: "DOWNSIDE_RISK_AT_LEAST_60", threshold: "60", comparison: "AT_LEAST" },
    { code: "NET_DEBT_TO_EBITDA_ABOVE_3", threshold: "3", comparison: "ABOVE" },
  ]);
  const invalidationConditions = conditionArray(item.invalidationConditions, "invalidationConditions", [
    { code: "ROIC_BELOW_8_PERCENT", threshold: "0.08", comparison: "BELOW" },
    { code: "INTEREST_COVERAGE_BELOW_3", threshold: "3", comparison: "BELOW" },
    { code: "CENTRAL_MARGIN_OF_SAFETY_BELOW_ZERO", threshold: "0", comparison: "BELOW" },
  ]);
  bindConditionSource(thesisEvidence[0], companyQuality, companyQuality.score, "QUALITY_AT_LEAST_65");
  bindConditionSource(thesisEvidence[1], financialResilience, financialResilience.score, "RESILIENCE_AT_LEAST_60");
  bindConditionSource(thesisEvidence[2], marginOfSafety, marginOfSafety.low, "CONSERVATIVE_MARGIN_OF_SAFETY_AT_LEAST_15_PERCENT");
  bindConditionSource(counterThesisEvidence[0], downsideRisk, downsideRisk.score, "DOWNSIDE_RISK_AT_LEAST_60");
  bindConditionSource(invalidationConditions[2], marginOfSafety, marginOfSafety.central, "CENTRAL_MARGIN_OF_SAFETY_BELOW_ZERO");
  return {
    companyType: text(item.companyType, "companyType"), applicability: "APPLICABLE",
    referencePrice: { state: referenceState, value: referenceValue, reasonCode: referenceReason },
    currency: text(item.currency, "currency"), projectionYears: item.projectionYears as number,
    companyQuality, financialResilience, earningsAndCashFlowQuality,
    capitalAllocationQuality, valuations, fairValue, marginOfSafety,
    expectedReturn, downsideRisk,
    claimCeiling,
    thesisEvidence, counterThesisEvidence, invalidationConditions,
    riskCap: { ceiling: riskCeiling, bindingReasons: riskReasons }, modelEvidenceLabel: "NOT_VALIDATED",
    modelVersion: text(item.modelVersion, "modelVersion"), strategyVersion: text(item.strategyVersion, "strategyVersion"), formulaVersion: text(item.formulaVersion, "formulaVersion"), aggregationVersion: text(item.aggregationVersion, "aggregationVersion"), riskPolicyVersion: text(item.riskPolicyVersion, "riskPolicyVersion"), assumptionPolicyVersion: text(item.assumptionPolicyVersion, "assumptionPolicyVersion"), inputHash: item.inputHash as string, contentHash: item.contentHash as string,
    deterministicRankingAuthorized: false, finalPortfolioWeightAuthorized: false, automaticBrokerageExecutionAuthorized: false,
  };
}

export function isCanonicalUuid(value: string): boolean {
  return uuid.test(value);
}

export function bindDecisionToRequestedAssembly(
  decision: FundamentalValueDecision,
  requestedAssemblyId: string,
): FundamentalValueDecision {
  if (decision.assemblyId !== requestedAssemblyId) fail("The response assembly does not match the requested assembly.");
  return decision;
}

export function decodeFundamentalValueDecision(value: unknown): FundamentalValueDecision {
  const fields = ["contractVersion", "assemblyId", "assessmentId", "identity", "state", "applicability", "companyType", "reasonCodes", "coreInvocationAuthorized", "manifestContentHash", "inputSealContentHash", "decisionCutoff", "sealedIngestionCutoff", "modelEvidenceLabel", "claimCeiling", "riskCapCeiling", "deterministicAssessment", "finalPortfolioWeightAuthorized", "automaticBrokerageExecutionAuthorized"] as const;
  const item = record(value, fields, "Fundamental Value decision");
  if (item.contractVersion !== FUNDAMENTAL_VALUE_RESULT_VERSION) fail("Fundamental Value result version is unsupported.");
  const assemblyId = text(item.assemblyId, "assemblyId");
  const assessmentId = optionalText(item.assessmentId, "assessmentId");
  const identity = decodeIdentity(item.identity);
  if (!uuid.test(assemblyId) || (assessmentId !== null && !uuid.test(assessmentId))) fail("Decision identifier is not canonical.");
  const rootState = state(item.state);
  if (typeof item.applicability !== "string" || !applicability.has(item.applicability as Applicability)) fail("Applicability is unsupported.");
  const reasons = stringList(item.reasonCodes, "reasonCodes");
  const assessment = item.deterministicAssessment === null ? null : decodeAssessment(item.deterministicAssessment);
  if (typeof item.coreInvocationAuthorized !== "boolean") fail("coreInvocationAuthorized must be Boolean.");
  const validRoot = assessment !== null && assessmentId !== null && reasons.length === 0 && item.coreInvocationAuthorized === true;
  if ((rootState === "VALID") !== validRoot) fail("Root state/assessment parity is invalid.");
  if (rootState !== "VALID" && (assessment !== null || assessmentId !== null || item.coreInvocationAuthorized !== false)) fail("Non-valid decision authority is invalid.");
  if (rootState !== "VALID" && reasons.length === 0) fail("Non-valid decisions require reasons.");
  if (assessment !== null && assessmentId !== deterministicAssessmentId(assemblyId, assessment.contentHash)) fail("Assessment identity does not match immutable content.");
  for (const field of ["manifestContentHash", "inputSealContentHash"] as const) if (typeof item[field] !== "string" || !hash.test(item[field] as string)) fail(`${field} is invalid.`);
  if (item.finalPortfolioWeightAuthorized !== false || item.automaticBrokerageExecutionAuthorized !== false) fail("Portfolio or brokerage authority is forbidden.");
  const label = item.modelEvidenceLabel === null ? null : text(item.modelEvidenceLabel, "modelEvidenceLabel");
  if (label !== null && label !== "NOT_VALIDATED") fail("Model evidence label is unsupported.");
  const rootApplicability = item.applicability as Applicability;
  const companyType = text(item.companyType, "companyType");
  if (companyType === "MATURE_OPERATING_COMPANY" && rootApplicability !== "APPLICABLE") fail("Mature-company routing outcome is invalid.");
  if (["BANK", "INSURER", "REIT", "RESOURCE", "BIOTECHNOLOGY", "FINANCIAL", "INCOMPATIBLE_CONGLOMERATE"].includes(companyType) && rootApplicability !== "SPECIALIZED_MODEL_REQUIRED") fail("Specialized company routing outcome is invalid.");
  if (companyType === "BENCHMARK" && rootApplicability !== "NOT_APPLICABLE") fail("Benchmark routing outcome is invalid.");
  if (companyType === "INSUFFICIENT_PUBLIC_HISTORY" && rootApplicability !== "INSUFFICIENT_EVIDENCE") fail("Insufficient-history routing outcome is invalid.");
  if (!["MATURE_OPERATING_COMPANY", "BANK", "INSURER", "REIT", "RESOURCE", "BIOTECHNOLOGY", "FINANCIAL", "INCOMPATIBLE_CONGLOMERATE", "BENCHMARK", "INSUFFICIENT_PUBLIC_HISTORY"].includes(companyType)) fail("Company type is unsupported.");
  if (rootApplicability === "SPECIALIZED_MODEL_REQUIRED" && (rootState !== "NOT_APPLICABLE" || reasons.join("|") !== "APPLICABILITY_SPECIALIZED_MODEL_REQUIRED")) fail("Specialized routing outcome is invalid.");
  if (rootApplicability === "NOT_APPLICABLE" && (rootState !== "NOT_APPLICABLE" || reasons.join("|") !== "APPLICABILITY_NOT_APPLICABLE")) fail("Not-applicable routing outcome is invalid.");
  if (rootApplicability === "INSUFFICIENT_EVIDENCE" && (rootState !== "MISSING" || reasons.join("|") !== "APPLICABILITY_INSUFFICIENT_EVIDENCE")) fail("Insufficient-evidence routing outcome is invalid.");
  if (assessment && (assessment.companyType !== companyType || assessment.currency !== identity.currency || assessment.modelEvidenceLabel !== label || assessment.claimCeiling !== item.claimCeiling || assessment.riskCap.ceiling !== item.riskCapCeiling)) fail("Assessment/root binding is invalid.");
  if (!assessment && (label !== null || item.claimCeiling !== null || item.riskCapCeiling !== null)) fail("Non-usable decisions cannot expose model outputs.");
  const decisionCutoff = instant(item.decisionCutoff, "decisionCutoff");
  const sealedIngestionCutoff = instant(item.sealedIngestionCutoff, "sealedIngestionCutoff");
  if (instantNanoseconds(decisionCutoff) > instantNanoseconds(sealedIngestionCutoff)) fail("Decision cutoff exceeds the sealed ingestion cutoff.");
  if (identity.completedSessionDate > decisionCutoff.slice(0, 10)) fail("Completed session exceeds the decision cutoff.");
  return {
    contractVersion: FUNDAMENTAL_VALUE_RESULT_VERSION, assemblyId, assessmentId, identity,
    state: rootState, applicability: rootApplicability, companyType, reasonCodes: reasons, coreInvocationAuthorized: item.coreInvocationAuthorized === true,
    manifestContentHash: item.manifestContentHash as string, inputSealContentHash: item.inputSealContentHash as string, decisionCutoff, sealedIngestionCutoff, modelEvidenceLabel: label, claimCeiling: optionalText(item.claimCeiling, "claimCeiling"), riskCapCeiling: optionalDecimal(item.riskCapCeiling, "riskCapCeiling"), deterministicAssessment: assessment, finalPortfolioWeightAuthorized: false, automaticBrokerageExecutionAuthorized: false,
  };
}
