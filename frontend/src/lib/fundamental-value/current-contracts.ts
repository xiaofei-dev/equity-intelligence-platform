import { createHash } from "node:crypto";

export const CURRENT_FUNDAMENTAL_VALUE_RESULT_VERSION =
  "internal-current-fundamental-value-result-v1.0.0" as const;

export type CurrentDimension = { state: "VALID"; score: string; reasonCodes: string[] };
export type CurrentRange = {
  state: "VALID"; low: string; central: string; high: string; reasonCodes: string[];
};
export type CurrentValuation = CurrentRange & {
  method: "FCFF_DCF" | "NORMALIZED_OWNER_EARNINGS" | "EARNINGS_POWER" | "COMPARABLE_CROSS_CHECK";
  terminalValueShare: string | null;
};
export type CurrentAssessment = {
  contractVersion: typeof CURRENT_FUNDAMENTAL_VALUE_RESULT_VERSION;
  assessmentId: string;
  assessmentContentHash: string;
  identity: {
    securityId: string; companyId: string; instrumentId: string; shareClassId: string;
    listingId: string; tickerAssignmentId: string; ticker: string; mic: string; currency: string;
  };
  decisionCutoff: string;
  priceSessionDate: string;
  latestFundamentalPeriodEnd: string;
  evidenceTrack: "EODHD_PROVIDER_NORMALIZED_CURRENT_REVISION_APPROXIMATION";
  claimCeiling: "DEVELOPMENT_OBSERVED_CURRENT_REVISION_APPROXIMATION";
  modelEvidenceLabel: "NOT_VALIDATED";
  versions: Record<string, string>;
  referencePrice: { state: "VALID"; value: string; reasonCode: null };
  companyQuality: CurrentDimension;
  financialResilience: CurrentDimension;
  earningsAndCashFlowQuality: CurrentDimension;
  capitalAllocationQuality: CurrentDimension;
  downsideRisk: CurrentDimension;
  valuations: CurrentValuation[];
  fairValue: CurrentRange;
  marginOfSafety: CurrentRange;
  expectedReturn: CurrentRange;
  riskCap: { ceiling: "0" | "0.01" | "0.02"; bindingReasons: string[] };
  investmentView: {
    state: "VALID";
    category: "ATTRACTIVE_FOR_FURTHER_RESEARCH" | "WATCHLIST_QUALITY_PRICE_NOT_ATTRACTIVE" |
      "HIGH_RISK_OR_WEAK_QUALITY" | "NEUTRAL_RESEARCH_REQUIRED" | "INSUFFICIENT_EVIDENCE";
    reasonCodes: string[];
  };
  deterministicActionAuthorized: false;
  deterministicRankingAuthorized: false;
  finalPortfolioWeightAuthorized: false;
  automaticBrokerageExecutionAuthorized: false;
};

export class CurrentFundamentalValueContractError extends Error {}

const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const hash = /^sha256:[0-9a-f]{64}$/;
const decimal = /^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$/;
const date = /^\d{4}-\d{2}-\d{2}$/;
const instant = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/;
const persistenceVersion = "FV-CURRENT-ASSESSMENT-PERSISTENCE-v1.0.0";
const namespace = Uint8Array.from([
  0x6b, 0xa7, 0xb8, 0x11, 0x9d, 0xad, 0x11, 0xd1,
  0x80, 0xb4, 0x00, 0xc0, 0x4f, 0xd4, 0x30, 0xc8,
]);

function fail(message: string): never { throw new CurrentFundamentalValueContractError(message); }

function object(value: unknown, fields: readonly string[], label: string): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) fail(`${label} must be an object.`);
  const result = value as Record<string, unknown>;
  if (Object.keys(result).sort().join("|") !== [...fields].sort().join("|")) fail(`${label} fields are invalid.`);
  return result;
}

function text(value: unknown, label: string): string {
  if (typeof value !== "string" || value.trim().length === 0) fail(`${label} must be non-blank text.`);
  return value;
}

function stringList(value: unknown, label: string, nonempty = false): string[] {
  if (!Array.isArray(value) || (nonempty && value.length === 0)
      || !value.every((item) => typeof item === "string" && item.trim().length > 0)) {
    fail(`${label} must be a non-blank text array.`);
  }
  return [...value] as string[];
}

function decimalText(value: unknown, label: string): string {
  const result = text(value, label);
  if (!decimal.test(result) || (/^-?0(?:\.0+)?$/.test(result) && result !== "0")) fail(`${label} is not canonical decimal text.`);
  return result;
}

function compare(left: string, right: string): number {
  const parse = (value: string) => {
    const negative = value.startsWith("-");
    const [whole, fraction = ""] = (negative ? value.slice(1) : value).split(".");
    return { negative, whole, fraction };
  };
  const a = parse(left); const b = parse(right);
  if (a.negative !== b.negative) return a.negative ? -1 : 1;
  const direction = a.negative ? -1 : 1;
  if (a.whole.length !== b.whole.length) return a.whole.length < b.whole.length ? -direction : direction;
  if (a.whole !== b.whole) return a.whole < b.whole ? -direction : direction;
  const width = Math.max(a.fraction.length, b.fraction.length);
  const af = a.fraction.padEnd(width, "0"); const bf = b.fraction.padEnd(width, "0");
  return af === bf ? 0 : af < bf ? -direction : direction;
}

function realDate(value: unknown, label: string): string {
  const result = text(value, label);
  const parsed = new Date(`${result}T00:00:00Z`);
  if (!date.test(result) || Number.isNaN(parsed.valueOf()) || parsed.toISOString().slice(0, 10) !== result) fail(`${label} is invalid.`);
  return result;
}

function utcInstant(value: unknown, label: string): string {
  const result = text(value, label);
  if (!instant.test(result) || Number.isNaN(Date.parse(result))) fail(`${label} is invalid.`);
  return result;
}

function dimension(value: unknown, label: string): CurrentDimension {
  const item = object(value, ["state", "score", "reasonCodes"], label);
  const score = decimalText(item.score, `${label}.score`);
  if (item.state !== "VALID" || compare(score, "0") < 0 || compare(score, "100") > 0) fail(`${label} is invalid.`);
  return { state: "VALID", score, reasonCodes: stringList(item.reasonCodes, `${label}.reasonCodes`) };
}

function range(value: unknown, label: string, positive = false): CurrentRange {
  const item = object(value, ["state", "low", "central", "high", "reasonCodes"], label);
  return rangeFields(item, label, positive);
}

function rangeFields(item: Record<string, unknown>, label: string, positive = false): CurrentRange {
  const low = decimalText(item.low, `${label}.low`); const central = decimalText(item.central, `${label}.central`); const high = decimalText(item.high, `${label}.high`);
  if (item.state !== "VALID" || compare(low, central) > 0 || compare(central, high) > 0 || (positive && compare(low, "0") <= 0)) fail(`${label} is invalid.`);
  return { state: "VALID", low, central, high, reasonCodes: stringList(item.reasonCodes, `${label}.reasonCodes`) };
}

function deterministicId(contentHash: string): string {
  const digest = createHash("sha1").update(namespace).update(`${persistenceVersion}:${contentHash}`, "utf8").digest();
  digest[6] = (digest[6] & 0x0f) | 0x50; digest[8] = (digest[8] & 0x3f) | 0x80;
  const hex = digest.subarray(0, 16).toString("hex");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

export function isCurrentAssessmentId(value: string): boolean { return uuid.test(value); }

export function decodeCurrentFundamentalValueAssessment(value: unknown): CurrentAssessment {
  const fields = ["contractVersion", "assessmentId", "assessmentContentHash", "identity", "decisionCutoff", "priceSessionDate", "latestFundamentalPeriodEnd", "evidenceTrack", "claimCeiling", "modelEvidenceLabel", "versions", "referencePrice", "companyQuality", "financialResilience", "earningsAndCashFlowQuality", "capitalAllocationQuality", "downsideRisk", "valuations", "fairValue", "marginOfSafety", "expectedReturn", "riskCap", "investmentView", "deterministicActionAuthorized", "deterministicRankingAuthorized", "finalPortfolioWeightAuthorized", "automaticBrokerageExecutionAuthorized"] as const;
  const root = object(value, fields, "currentAssessment");
  const assessmentId = text(root.assessmentId, "assessmentId");
  const contentHash = text(root.assessmentContentHash, "assessmentContentHash");
  if (root.contractVersion !== CURRENT_FUNDAMENTAL_VALUE_RESULT_VERSION || !uuid.test(assessmentId)
      || !hash.test(contentHash) || assessmentId !== deterministicId(contentHash)) fail("Current assessment identity is invalid.");
  const identityFields = ["securityId", "companyId", "instrumentId", "shareClassId", "listingId", "tickerAssignmentId", "ticker", "mic", "currency"] as const;
  const identity = object(root.identity, identityFields, "identity");
  for (const field of identityFields.slice(0, 6)) if (!uuid.test(text(identity[field], `identity.${field}`))) fail(`identity.${field} is invalid.`);
  if (!/^[A-Z0-9][A-Z0-9.\-]{0,31}$/.test(text(identity.ticker, "identity.ticker")) || !/^[A-Z0-9]{4}$/.test(text(identity.mic, "identity.mic")) || !/^[A-Z]{3}$/.test(text(identity.currency, "identity.currency"))) fail("Identity presentation is invalid.");
  const versionFields = ["producerVersion", "policyVersion", "modelVersion", "strategyVersion", "formulaVersion", "aggregationVersion", "riskPolicyVersion", "assumptionPolicyVersion"] as const;
  const versions = object(root.versions, versionFields, "versions");
  const expectedVersions = ["FV-CURRENT-REVISION-PRODUCER-v1.0.0", "FV-CURRENT-INVESTMENT-POLICY-v1.0.0", "FUNDAMENTAL-VALUE-v1.0.0", "LONG-TERM-CORE-v1.0.0", "fundamental-value-formulas-v1.1.0", "FUNDAMENTAL-VALUE-WEIGHTED-MEDIAN-QUANTILE-v1.0.0", "LONG-TERM-CORE-RISK-CAP-TIERS-v1.0.0", "fundamental-value-assumptions-v1.1.0"];
  if (!versionFields.every((field, index) => versions[field] === expectedVersions[index])) fail("Version set is unsupported.");
  const reference = object(root.referencePrice, ["state", "value", "reasonCode"], "referencePrice");
  const referenceValue = decimalText(reference.value, "referencePrice.value");
  if (reference.state !== "VALID" || reference.reasonCode !== null || compare(referenceValue, "0") <= 0) fail("Reference price is invalid.");
  if (!Array.isArray(root.valuations) || root.valuations.length !== 4) fail("Valuations are invalid.");
  const methods = ["FCFF_DCF", "NORMALIZED_OWNER_EARNINGS", "EARNINGS_POWER", "COMPARABLE_CROSS_CHECK"] as const;
  const valuations = root.valuations.map((raw, index) => {
    const item = object(raw, ["method", "state", "low", "central", "high", "reasonCodes", "terminalValueShare"], `valuations[${index}]`);
    const decoded = rangeFields(item, `valuations[${index}]`, true);
    const share = item.terminalValueShare === null ? null : decimalText(item.terminalValueShare, "terminalValueShare");
    if (item.method !== methods[index] || (index === 0 ? share === null || compare(share, "0.80") > 0 : share !== null)) fail("Valuation method contract is invalid.");
    return { ...decoded, method: methods[index], terminalValueShare: share };
  });
  const riskCap = object(root.riskCap, ["ceiling", "bindingReasons"], "riskCap");
  if (!new Set(["0", "0.01", "0.02"]).has(riskCap.ceiling as string)) fail("Risk cap is invalid.");
  const view = object(root.investmentView, ["state", "category", "reasonCodes"], "investmentView");
  const categories = new Set(["ATTRACTIVE_FOR_FURTHER_RESEARCH", "WATCHLIST_QUALITY_PRICE_NOT_ATTRACTIVE", "HIGH_RISK_OR_WEAK_QUALITY", "NEUTRAL_RESEARCH_REQUIRED", "INSUFFICIENT_EVIDENCE"]);
  if (view.state !== "VALID" || !categories.has(view.category as string)) fail("Investment view is invalid.");
  for (const flag of ["deterministicActionAuthorized", "deterministicRankingAuthorized", "finalPortfolioWeightAuthorized", "automaticBrokerageExecutionAuthorized"] as const) if (root[flag] !== false) fail("Investment authority is forbidden.");
  if (root.evidenceTrack !== "EODHD_PROVIDER_NORMALIZED_CURRENT_REVISION_APPROXIMATION" || root.claimCeiling !== "DEVELOPMENT_OBSERVED_CURRENT_REVISION_APPROXIMATION" || root.modelEvidenceLabel !== "NOT_VALIDATED") fail("Evidence claim boundary is invalid.");
  const decisionCutoff = utcInstant(root.decisionCutoff, "decisionCutoff"); const priceSessionDate = realDate(root.priceSessionDate, "priceSessionDate"); const latestFundamentalPeriodEnd = realDate(root.latestFundamentalPeriodEnd, "latestFundamentalPeriodEnd");
  if (latestFundamentalPeriodEnd > priceSessionDate || priceSessionDate > decisionCutoff.slice(0, 10)) fail("Current assessment chronology is invalid.");
  return {
    contractVersion: CURRENT_FUNDAMENTAL_VALUE_RESULT_VERSION, assessmentId, assessmentContentHash: contentHash,
    identity: identity as CurrentAssessment["identity"], decisionCutoff, priceSessionDate, latestFundamentalPeriodEnd,
    evidenceTrack: "EODHD_PROVIDER_NORMALIZED_CURRENT_REVISION_APPROXIMATION",
    claimCeiling: "DEVELOPMENT_OBSERVED_CURRENT_REVISION_APPROXIMATION",
    modelEvidenceLabel: "NOT_VALIDATED",
    versions: Object.fromEntries(versionFields.map((field) => [field, versions[field] as string])),
    referencePrice: { state: "VALID", value: referenceValue, reasonCode: null },
    companyQuality: dimension(root.companyQuality, "companyQuality"), financialResilience: dimension(root.financialResilience, "financialResilience"),
    earningsAndCashFlowQuality: dimension(root.earningsAndCashFlowQuality, "earningsAndCashFlowQuality"), capitalAllocationQuality: dimension(root.capitalAllocationQuality, "capitalAllocationQuality"), downsideRisk: dimension(root.downsideRisk, "downsideRisk"),
    valuations, fairValue: range(root.fairValue, "fairValue", true), marginOfSafety: range(root.marginOfSafety, "marginOfSafety"), expectedReturn: range(root.expectedReturn, "expectedReturn"),
    riskCap: { ceiling: riskCap.ceiling as "0" | "0.01" | "0.02", bindingReasons: stringList(riskCap.bindingReasons, "riskCap.bindingReasons", true) },
    investmentView: { state: "VALID", category: view.category as CurrentAssessment["investmentView"]["category"], reasonCodes: stringList(view.reasonCodes, "investmentView.reasonCodes", true) },
    deterministicActionAuthorized: false, deterministicRankingAuthorized: false, finalPortfolioWeightAuthorized: false, automaticBrokerageExecutionAuthorized: false,
  };
}
