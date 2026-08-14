import { createHash } from "node:crypto";

export const QUANT_RESEARCH_CONTRACT_VERSION =
  "quant-trading-research-decision-v1.1.0" as const;
export const QUANT_RESEARCH_PROJECTION_VERSION =
  "quant-trading-public-projection-v1.1.0" as const;

export type QuantResearchClassification =
  | "ENTRY_CANDIDATE"
  | "HOLD_REVIEW"
  | "EXIT_REVIEW"
  | "NO_SIGNAL"
  | "NOT_APPLICABLE"
  | "INSUFFICIENT_EVIDENCE";

export type QuantResearchSignal = {
  securityId: string;
  assemblyState: "VALID" | "MISSING" | "STALE" | "INVALID" | "NOT_APPLICABLE" | "EXCLUDED";
  applicability: "APPLICABLE" | "NOT_APPLICABLE" | "INSUFFICIENT_EVIDENCE";
  assemblyReasonCodes: string[];
  rawSignal: {
    state: "ELIGIBLE" | "INELIGIBLE" | "MISSING" | "INVALID";
    reasonCodes: string[];
    inputHash: string;
    contentHash: string;
    signalClose: string | null;
    features: null | {
      atr14: string; sma100: string; sma200: string; marketSma200: string;
      momentum252Skip20: string; momentum126Skip20: string;
      marketMomentum252Skip20: string; marketMomentum126Skip20: string;
      relative252Skip20: string; relative126Skip20: string;
      medianAdtv20: string; atrPercent: string;
    };
  };
  ranking: {
    state: "ENTRY_ELIGIBLE" | "HOLD_ELIGIBLE" | "EXIT_ELIGIBLE" | "NOT_RANKED";
    rank: number | null;
    crossSectionCount: number;
    momentum252Percentile: string | null;
    momentum126Percentile: string | null;
    compositeScore: string | null;
    crossSectionHash: string;
    contentHash: string;
  };
  entryPlan: null | {
    signalClose: string;
    initialStop: string;
    maximumEntryPrice: string;
    atr14: string;
    maximumHoldingSessions: 126;
  };
  researchClassification: QuantResearchClassification;
};

export type QuantResearchDecision = {
  decisionId: string;
  contractVersion: typeof QUANT_RESEARCH_CONTRACT_VERSION;
  projectionVersion: typeof QUANT_RESEARCH_PROJECTION_VERSION;
  assemblyVersion: "quant-trading-v22-assembly-v1.1.0";
  modelVersion: "QUANT-TRADING-v1.1.0";
  strategyVersion: "DUAL-MOMENTUM-TREND-v1.1.0";
  formulaVersion: "DUAL-MOMENTUM-TREND-FORMULAS-v1.1.0";
  entryExitPolicyVersion: "DUAL-MOMENTUM-TREND-ENTRY-EXIT-v1.1.0";
  modelEvidenceLabel: "NOT_VALIDATED";
  decisionDate: string;
  rebalanceOrdinal: number;
  expectedSecurityCount: number;
  assemblyManifestHash: string;
  signals: QuantResearchSignal[];
  authority: {
    deterministicResearchSignal: true;
    deterministicFinalPortfolioWeight: false;
    automaticBrokerageExecution: false;
    llmSignalOrWeightAuthority: false;
    futureReturnGuaranteed: false;
  };
  contentHash: string;
};

export class QuantResearchContractError extends Error {}

const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const hash = /^sha256:[0-9a-f]{64}$/;
const decimal = /^-?(?:0|[1-9][0-9]*)(?:\.\d+)?$/;
const persistenceVersion = "quant-trading-research-persistence-v1.1.0";
const urlNamespace = Buffer.from("6ba7b8119dad11d180b400c04fd430c8", "hex");

function fail(message: string): never { throw new QuantResearchContractError(message); }
function object(value: unknown, label: string): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) fail(`${label} must be an object.`);
  return value as Record<string, unknown>;
}
function exact(value: Record<string, unknown>, fields: string[], label: string) {
  const actual = Object.keys(value).sort(); const expected = [...fields].sort();
  if (JSON.stringify(actual) !== JSON.stringify(expected)) fail(`${label} fields are invalid.`);
}
function text(value: unknown, label: string): string {
  if (typeof value !== "string" || value.length === 0) fail(`${label} must be text.`); return value;
}
function strings(value: unknown, label: string): string[] {
  if (!Array.isArray(value) || value.some((item) => typeof item !== "string" || item.trim() === "")) fail(`${label} must be a string array.`);
  return [...value] as string[];
}
function canonicalDecimal(value: unknown, label: string): string {
  const result = text(value, label);
  if (!decimal.test(result) || (/^-?0(?:\.0+)?$/.test(result) && result !== "0") || result.includes(".") && result.endsWith("0")) fail(`${label} is not canonical decimal text.`);
  return result;
}
function optionalDecimal(value: unknown, label: string): string | null { return value === null ? null : canonicalDecimal(value, label); }
function digest(value: unknown): string {
  const canonical = JSON.stringify(canonicalValue(value));
  return `sha256:${createHash("sha256").update(canonical, "utf8").digest("hex")}`;
}
function canonicalValue(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(canonicalValue);
  if (typeof value === "object" && value !== null) {
    const source = value as Record<string, unknown>; const result: Record<string, unknown> = {};
    for (const key of Object.keys(source).sort()) result[key] = canonicalValue(source[key]);
    return result;
  }
  if (value === null || typeof value === "string" || typeof value === "number" || typeof value === "boolean") return value;
  fail("Projection contains a non-canonical scalar.");
}

export function deterministicQuantDecisionId(contentHash: string): string {
  if (!hash.test(contentHash)) fail("Content hash is invalid.");
  const digestBytes = createHash("sha1").update(urlNamespace).update(`${persistenceVersion}:${contentHash}`, "utf8").digest();
  digestBytes[6] = (digestBytes[6] & 0x0f) | 0x50; digestBytes[8] = (digestBytes[8] & 0x3f) | 0x80;
  const hex = digestBytes.subarray(0, 16).toString("hex");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

export function quantResearchContentHash(value: Record<string, unknown>): string {
  const body = { ...value }; delete body.decisionId; delete body.contentHash; return digest(body);
}

function decodeSignal(value: unknown): QuantResearchSignal {
  const item = object(value, "signal");
  exact(item, ["securityId", "assemblyState", "applicability", "assemblyReasonCodes", "rawSignal", "ranking", "entryPlan", "researchClassification"], "signal");
  const securityId = text(item.securityId, "securityId"); if (!uuid.test(securityId)) fail("securityId is invalid.");
  const assemblyStates = new Set(["VALID", "MISSING", "STALE", "INVALID", "NOT_APPLICABLE", "EXCLUDED"]);
  const assemblyState = text(item.assemblyState, "assemblyState"); if (!assemblyStates.has(assemblyState)) fail("assemblyState is invalid.");
  const applicability = text(item.applicability, "applicability"); if (!["APPLICABLE", "NOT_APPLICABLE", "INSUFFICIENT_EVIDENCE"].includes(applicability)) fail("applicability is invalid.");
  const assemblyReasonCodes = strings(item.assemblyReasonCodes, "assemblyReasonCodes");
  if ((assemblyState === "VALID") !== (assemblyReasonCodes.length === 0)) fail("Assembly state and reasons disagree.");
  const raw = object(item.rawSignal, "rawSignal"); exact(raw, ["state", "reasonCodes", "inputHash", "contentHash", "signalClose", "features"], "rawSignal");
  const rawState = text(raw.state, "rawSignal.state"); if (!["ELIGIBLE", "INELIGIBLE", "MISSING", "INVALID"].includes(rawState)) fail("rawSignal.state is invalid.");
  const rawReasons = strings(raw.reasonCodes, "rawSignal.reasonCodes");
  if (!hash.test(text(raw.inputHash, "rawSignal.inputHash")) || !hash.test(text(raw.contentHash, "rawSignal.contentHash"))) fail("Raw signal hash is invalid.");
  const featureNames = ["atr14", "sma100", "sma200", "marketSma200", "momentum252Skip20", "momentum126Skip20", "marketMomentum252Skip20", "marketMomentum126Skip20", "relative252Skip20", "relative126Skip20", "medianAdtv20", "atrPercent"];
  let features: QuantResearchSignal["rawSignal"]["features"] = null; let signalClose: string | null = null;
  if (rawState === "ELIGIBLE") {
    if (rawReasons.length !== 0) fail("Eligible raw signal cannot carry reasons.");
    signalClose = canonicalDecimal(raw.signalClose, "rawSignal.signalClose");
    const source = object(raw.features, "rawSignal.features"); exact(source, featureNames, "features");
    features = Object.fromEntries(featureNames.map((name) => [name, canonicalDecimal(source[name], `features.${name}`)])) as QuantResearchSignal["rawSignal"]["features"];
  } else if (raw.signalClose !== null || raw.features !== null || rawReasons.length === 0) fail("Non-eligible raw signal shape is invalid.");
  const rankingSource = object(item.ranking, "ranking"); exact(rankingSource, ["state", "rank", "crossSectionCount", "momentum252Percentile", "momentum126Percentile", "compositeScore", "crossSectionHash", "contentHash"], "ranking");
  const rankingState = text(rankingSource.state, "ranking.state"); if (!["ENTRY_ELIGIBLE", "HOLD_ELIGIBLE", "EXIT_ELIGIBLE", "NOT_RANKED"].includes(rankingState)) fail("ranking.state is invalid.");
  if (!Number.isInteger(rankingSource.crossSectionCount) || (rankingSource.crossSectionCount as number) < 0 || !hash.test(text(rankingSource.crossSectionHash, "ranking.crossSectionHash")) || !hash.test(text(rankingSource.contentHash, "ranking.contentHash"))) fail("Ranking contract is invalid.");
  const rank = rankingSource.rank; const p252 = optionalDecimal(rankingSource.momentum252Percentile, "ranking.momentum252Percentile"); const p126 = optionalDecimal(rankingSource.momentum126Percentile, "ranking.momentum126Percentile"); const composite = optionalDecimal(rankingSource.compositeScore, "ranking.compositeScore");
  if (rankingState === "NOT_RANKED" ? rank !== null || p252 !== null || p126 !== null || composite !== null : !Number.isInteger(rank) || (rank as number) < 1 || (rank as number) > (rankingSource.crossSectionCount as number) || p252 === null || p126 === null || composite === null) fail("Ranking values are invalid.");
  const expected = assemblyState === "NOT_APPLICABLE" ? "NOT_APPLICABLE" : assemblyState !== "VALID" || ["MISSING", "INVALID"].includes(rawState) ? "INSUFFICIENT_EVIDENCE" : rawState === "INELIGIBLE" ? "NO_SIGNAL" : rankingState === "ENTRY_ELIGIBLE" ? "ENTRY_CANDIDATE" : rankingState === "HOLD_ELIGIBLE" ? "HOLD_REVIEW" : rankingState === "EXIT_ELIGIBLE" ? "EXIT_REVIEW" : "NO_SIGNAL";
  if (item.researchClassification !== expected) fail("Research classification is inconsistent.");
  let entryPlan: QuantResearchSignal["entryPlan"] = null;
  if (rankingState === "ENTRY_ELIGIBLE") {
    const entry = object(item.entryPlan, "entryPlan"); exact(entry, ["signalClose", "initialStop", "maximumEntryPrice", "atr14", "maximumHoldingSessions"], "entryPlan");
    if (entry.maximumHoldingSessions !== 126) fail("Entry holding policy drifted.");
    entryPlan = { signalClose: canonicalDecimal(entry.signalClose, "entryPlan.signalClose"), initialStop: canonicalDecimal(entry.initialStop, "entryPlan.initialStop"), maximumEntryPrice: canonicalDecimal(entry.maximumEntryPrice, "entryPlan.maximumEntryPrice"), atr14: canonicalDecimal(entry.atr14, "entryPlan.atr14"), maximumHoldingSessions: 126 };
  } else if (item.entryPlan !== null) fail("Only entry candidates may carry an entry plan.");
  return { securityId, assemblyState: assemblyState as QuantResearchSignal["assemblyState"], applicability: applicability as QuantResearchSignal["applicability"], assemblyReasonCodes, rawSignal: { state: rawState as QuantResearchSignal["rawSignal"]["state"], reasonCodes: rawReasons, inputHash: raw.inputHash as string, contentHash: raw.contentHash as string, signalClose, features }, ranking: { state: rankingState as QuantResearchSignal["ranking"]["state"], rank: rank as number | null, crossSectionCount: rankingSource.crossSectionCount as number, momentum252Percentile: p252, momentum126Percentile: p126, compositeScore: composite, crossSectionHash: rankingSource.crossSectionHash as string, contentHash: rankingSource.contentHash as string }, entryPlan, researchClassification: expected as QuantResearchClassification };
}

export function decodeQuantResearchDecision(value: unknown): QuantResearchDecision {
  const item = object(value, "decision");
  exact(item, ["decisionId", "contractVersion", "projectionVersion", "assemblyVersion", "modelVersion", "strategyVersion", "formulaVersion", "entryExitPolicyVersion", "modelEvidenceLabel", "decisionDate", "rebalanceOrdinal", "expectedSecurityCount", "assemblyManifestHash", "signals", "authority", "contentHash"], "decision");
  const versions = { contractVersion: QUANT_RESEARCH_CONTRACT_VERSION, projectionVersion: QUANT_RESEARCH_PROJECTION_VERSION, assemblyVersion: "quant-trading-v22-assembly-v1.1.0", modelVersion: "QUANT-TRADING-v1.1.0", strategyVersion: "DUAL-MOMENTUM-TREND-v1.1.0", formulaVersion: "DUAL-MOMENTUM-TREND-FORMULAS-v1.1.0", entryExitPolicyVersion: "DUAL-MOMENTUM-TREND-ENTRY-EXIT-v1.1.0", modelEvidenceLabel: "NOT_VALIDATED" } as const;
  for (const [name, expected] of Object.entries(versions)) if (item[name] !== expected) fail(`${name} drifted.`);
  const decisionId = text(item.decisionId, "decisionId"); const contentHash = text(item.contentHash, "contentHash");
  if (!uuid.test(decisionId) || !hash.test(contentHash) || !hash.test(text(item.assemblyManifestHash, "assemblyManifestHash"))) fail("Decision identity or hash is invalid.");
  if (!/^\d{4}-\d{2}-\d{2}$/.test(text(item.decisionDate, "decisionDate")) || Number.isNaN(Date.parse(`${item.decisionDate}T00:00:00Z`))) fail("decisionDate is invalid.");
  if (!Number.isInteger(item.rebalanceOrdinal) || (item.rebalanceOrdinal as number) < 0 || (item.rebalanceOrdinal as number) % 5 !== 0 || !Number.isInteger(item.expectedSecurityCount) || (item.expectedSecurityCount as number) < 20) fail("Decision schedule or denominator is invalid.");
  if (!Array.isArray(item.signals) || item.signals.length !== item.expectedSecurityCount) fail("Signal denominator is invalid.");
  const signals = item.signals.map(decodeSignal); const ids = signals.map((signal) => signal.securityId);
  if (JSON.stringify(ids) !== JSON.stringify([...new Set(ids)].sort())) fail("Signals are not sorted and unique.");
  const authority = object(item.authority, "authority"); exact(authority, ["deterministicResearchSignal", "deterministicFinalPortfolioWeight", "automaticBrokerageExecution", "llmSignalOrWeightAuthority", "futureReturnGuaranteed"], "authority");
  if (authority.deterministicResearchSignal !== true || authority.deterministicFinalPortfolioWeight !== false || authority.automaticBrokerageExecution !== false || authority.llmSignalOrWeightAuthority !== false || authority.futureReturnGuaranteed !== false) fail("Decision authority is invalid.");
  if (quantResearchContentHash(item) !== contentHash || deterministicQuantDecisionId(contentHash) !== decisionId) fail("Decision content identity is invalid.");
  const forbidden = JSON.stringify(item); if (/"(?:finalWeight|orderQuantity|brokerageInstruction)"\s*:/.test(forbidden)) fail("Forbidden trade authority is present.");
  return { ...(structuredClone(item) as QuantResearchDecision), signals };
}

export function bindDecisionToRequestedId(decision: QuantResearchDecision, decisionId: string): QuantResearchDecision {
  if (!uuid.test(decisionId) || decision.decisionId !== decisionId) fail("Decision does not match the requested identifier.");
  return decision;
}

export function isCanonicalQuantDecisionId(value: string): boolean { return uuid.test(value); }
