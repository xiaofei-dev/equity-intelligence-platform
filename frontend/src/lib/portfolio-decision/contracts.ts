export const scenarioTypes = ["HOLD_CURRENT", "NEW_MONEY_ONLY", "CONSTRAINED_REBALANCE", "TARGET_PORTFOLIO"] as const;
export const humanConclusions = ["ACCEPTED", "REJECTED", "DEFERRED", "NO_ACTION"] as const;
export type ScenarioType = typeof scenarioTypes[number];
export type HumanConclusion = typeof humanConclusions[number];

const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const hash = /^sha256:[0-9a-f]{64}$/;
const decimal = /^(?:0|-[1-9][0-9]*|[1-9][0-9]*)(?:\.[0-9]+)?$/;
const instant = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:Z|[+-]\d{2}:\d{2})$/;

export class PortfolioDecisionContractError extends Error {}

export type DecisionEvidence = {
  securityId: string;
  dataState: "VALID" | "MISSING" | "STALE" | "INVALID";
  fundamentalEvidenceLabel: ModelEvidenceLabel | null;
  quantEvidenceLabel: ModelEvidenceLabel | null;
};
type ModelEvidenceLabel = "NOT_VALIDATED" | "DEVELOPMENT_OBSERVED" | "BACKTEST_SUPPORTED" | "PIT_SUPPORTED" | "FORWARD_SUPPORTED";

export type DecisionPosition = {
  securityId: string;
  ticker: string;
  sleeve: "LONG_TERM_CORE" | "QUANT_TRADING" | "UNASSIGNED";
  currentValue: string;
  targetValue: string;
  valueDelta: string;
  targetWeight: string;
  permission: "LOCKED" | "BUY_ONLY" | "SELL_ONLY" | "BUY_AND_SELL";
  estimatedCost: string;
  estimatedTax: string | null;
};

export type PortfolioDecisionScenario = {
  scenarioId: string;
  portfolioId: string;
  contextId: string;
  scenarioType: ScenarioType;
  scenarioState: "VALID" | "PARTIAL" | "INFEASIBLE";
  decisionCutoff: string;
  economicPolicyVersion: "PORTFOLIO-SCENARIO-ECONOMICS-v1.0.0";
  candidateState: "CANDIDATE_FOR_HUMAN_REVIEW" | "NO_FEASIBLE_CANDIDATE";
  evidence: DecisionEvidence[];
  positions: DecisionPosition[];
  economics: {
    newMoneyAmount: string;
    transactionCostBps: string;
    slippageBps: string;
    grossBuyNotional: string;
    grossSellNotional: string;
    grossTradedNotional: string;
    estimatedTransactionAndSlippageCost: string;
    impactState: "NOT_ESTIMATED" | "AVAILABLE";
    taxEstimateState: "NOT_ESTIMATED" | "AVAILABLE_NOT_APPLIED" | "AVAILABLE_APPLIED";
    taxEstimateAmount: string | null;
    appliedTaxAmount: string;
    oneWayWeightTurnover: string;
    grossTradedNotionalRate: string;
    finalCash: string | null;
    finalAssetValue: string | null;
  } | null;
  reasonCodes: string[];
  recommendation: {
    recommendationId: string;
    state: "RECOMMENDATION_AVAILABLE" | "NO_FEASIBLE_ACTION" | "REVIEW_REQUIRED";
    reasonCodes: string[];
    contentHash: string;
  };
  humanDecision: null | {
    decisionId: string;
    conclusion: HumanConclusion;
    rationale: string;
    decidedAt: string;
    contentHash: string;
  };
  authority: {
    candidateForHumanReviewOnly: true;
    finalWeightAuthority: false;
    orderAuthority: false;
    automaticBrokerageExecution: false;
    llmDecisionAuthority: false;
    humanDecisionRequired: true;
  };
  contentHash: string;
};

export function decodePortfolioDecisionScenario(value: unknown): PortfolioDecisionScenario {
  const root = object(value, "scenario");
  exact(root, ["scenarioId", "portfolioId", "contextId", "scenarioType", "scenarioState", "decisionCutoff", "economicPolicyVersion", "candidateState", "evidence", "positions", "economics", "reasonCodes", "recommendation", "humanDecision", "authority", "contentHash"], "scenario");
  const scenarioId = id(root.scenarioId, "scenarioId"); const portfolioId = id(root.portfolioId, "portfolioId"); const contextId = id(root.contextId, "contextId");
  const scenarioType = enumeration(root.scenarioType, scenarioTypes, "scenarioType");
  const scenarioState = enumeration(root.scenarioState, ["VALID", "PARTIAL", "INFEASIBLE"] as const, "scenarioState");
  const decisionCutoff = timestamp(root.decisionCutoff, "decisionCutoff");
  if (root.economicPolicyVersion !== "PORTFOLIO-SCENARIO-ECONOMICS-v1.0.0") fail("Economic policy version is unsupported.");
  const candidateState = enumeration(root.candidateState, ["CANDIDATE_FOR_HUMAN_REVIEW", "NO_FEASIBLE_CANDIDATE"] as const, "candidateState");
  const evidence = array(root.evidence, "evidence").map(decodeEvidence); uniqueOrdered(evidence.map((item) => item.securityId), "evidence");
  const positions = array(root.positions, "positions").map(decodePosition); uniqueOrdered(positions.map((item) => item.securityId), "positions");
  const reasonCodes = reasons(root.reasonCodes, "reasonCodes");
  const economics = root.economics === null ? null : decodeEconomics(root.economics);
  if ((candidateState === "CANDIDATE_FOR_HUMAN_REVIEW") !== (economics !== null && scenarioState !== "INFEASIBLE")) fail("Candidate/economics state parity failed.");
  const recommendation = decodeRecommendation(root.recommendation);
  if ((candidateState === "NO_FEASIBLE_CANDIDATE") !== (recommendation.state === "NO_FEASIBLE_ACTION")) fail("Candidate/recommendation state parity failed.");
  const humanDecision = root.humanDecision === null ? null : decodeHumanDecision(root.humanDecision);
  const authority = object(root.authority, "authority"); exact(authority, ["candidateForHumanReviewOnly", "finalWeightAuthority", "orderAuthority", "automaticBrokerageExecution", "llmDecisionAuthority", "humanDecisionRequired"], "authority");
  if (authority.candidateForHumanReviewOnly !== true || authority.finalWeightAuthority !== false || authority.orderAuthority !== false || authority.automaticBrokerageExecution !== false || authority.llmDecisionAuthority !== false || authority.humanDecisionRequired !== true) fail("Unsafe scenario authority was returned.");
  const contentHash = digest(root.contentHash, "contentHash");
  return { scenarioId, portfolioId, contextId, scenarioType, scenarioState, decisionCutoff, economicPolicyVersion: "PORTFOLIO-SCENARIO-ECONOMICS-v1.0.0", candidateState, evidence, positions, economics, reasonCodes, recommendation, humanDecision, authority: { candidateForHumanReviewOnly: true, finalWeightAuthority: false, orderAuthority: false, automaticBrokerageExecution: false, llmDecisionAuthority: false, humanDecisionRequired: true }, contentHash };
}

export function decodePortfolioDecisionScenarios(value: unknown): PortfolioDecisionScenario[] {
  const values = array(value, "scenarios").map(decodePortfolioDecisionScenario);
  if (values.length > 4 || new Set(values.map((item) => item.scenarioType)).size !== values.length) fail("At most one latest scenario per type is allowed.");
  return values;
}

function decodeEvidence(value: unknown): DecisionEvidence { const row = object(value, "evidence"); exact(row, ["securityId", "dataState", "fundamentalEvidenceLabel", "quantEvidenceLabel"], "evidence"); const label = (value: unknown, name: string): ModelEvidenceLabel | null => value === null ? null : enumeration(value, ["NOT_VALIDATED", "DEVELOPMENT_OBSERVED", "BACKTEST_SUPPORTED", "PIT_SUPPORTED", "FORWARD_SUPPORTED"] as const, name); return { securityId: id(row.securityId, "evidence.securityId"), dataState: enumeration(row.dataState, ["VALID", "MISSING", "STALE", "INVALID"] as const, "evidence.dataState"), fundamentalEvidenceLabel: label(row.fundamentalEvidenceLabel, "fundamentalEvidenceLabel"), quantEvidenceLabel: label(row.quantEvidenceLabel, "quantEvidenceLabel") }; }
function decodePosition(value: unknown): DecisionPosition { const row = object(value, "position"); exact(row, ["securityId", "ticker", "sleeve", "currentValue", "targetValue", "valueDelta", "targetWeight", "permission", "estimatedCost", "estimatedTax"], "position"); const currentValue = dec(row.currentValue, "currentValue"); const targetValue = dec(row.targetValue, "targetValue"); const valueDelta = dec(row.valueDelta, "valueDelta"); if (subtract(targetValue, currentValue) !== canonical(valueDelta)) fail("Position delta parity failed."); return { securityId: id(row.securityId, "position.securityId"), ticker: text(row.ticker, "ticker"), sleeve: enumeration(row.sleeve, ["LONG_TERM_CORE", "QUANT_TRADING", "UNASSIGNED"] as const, "sleeve"), currentValue, targetValue, valueDelta, targetWeight: dec(row.targetWeight, "targetWeight"), permission: enumeration(row.permission, ["LOCKED", "BUY_ONLY", "SELL_ONLY", "BUY_AND_SELL"] as const, "permission"), estimatedCost: dec(row.estimatedCost, "estimatedCost"), estimatedTax: row.estimatedTax === null ? null : dec(row.estimatedTax, "estimatedTax") }; }
function decodeEconomics(value: unknown): NonNullable<PortfolioDecisionScenario["economics"]> { const row = object(value, "economics"); const keys = ["newMoneyAmount", "transactionCostBps", "slippageBps", "grossBuyNotional", "grossSellNotional", "grossTradedNotional", "estimatedTransactionAndSlippageCost", "impactState", "taxEstimateState", "taxEstimateAmount", "appliedTaxAmount", "oneWayWeightTurnover", "grossTradedNotionalRate", "finalCash", "finalAssetValue"] as const; exact(row, [...keys], "economics"); const result = Object.fromEntries(keys.slice(0, 7).map((key) => [key, dec(row[key], key)])) as Record<string, string>; return { newMoneyAmount: result.newMoneyAmount, transactionCostBps: result.transactionCostBps, slippageBps: result.slippageBps, grossBuyNotional: result.grossBuyNotional, grossSellNotional: result.grossSellNotional, grossTradedNotional: result.grossTradedNotional, estimatedTransactionAndSlippageCost: result.estimatedTransactionAndSlippageCost, impactState: enumeration(row.impactState, ["NOT_ESTIMATED", "AVAILABLE"] as const, "impactState"), taxEstimateState: enumeration(row.taxEstimateState, ["NOT_ESTIMATED", "AVAILABLE_NOT_APPLIED", "AVAILABLE_APPLIED"] as const, "taxEstimateState"), taxEstimateAmount: row.taxEstimateAmount === null ? null : dec(row.taxEstimateAmount, "taxEstimateAmount"), appliedTaxAmount: dec(row.appliedTaxAmount, "appliedTaxAmount"), oneWayWeightTurnover: dec(row.oneWayWeightTurnover, "oneWayWeightTurnover"), grossTradedNotionalRate: dec(row.grossTradedNotionalRate, "grossTradedNotionalRate"), finalCash: row.finalCash === null ? null : dec(row.finalCash, "finalCash"), finalAssetValue: row.finalAssetValue === null ? null : dec(row.finalAssetValue, "finalAssetValue") }; }
function decodeRecommendation(value: unknown): PortfolioDecisionScenario["recommendation"] { const row = object(value, "recommendation"); exact(row, ["recommendationId", "state", "reasonCodes", "contentHash"], "recommendation"); return { recommendationId: id(row.recommendationId, "recommendationId"), state: enumeration(row.state, ["RECOMMENDATION_AVAILABLE", "NO_FEASIBLE_ACTION", "REVIEW_REQUIRED"] as const, "recommendation.state"), reasonCodes: reasons(row.reasonCodes, "recommendation.reasonCodes"), contentHash: digest(row.contentHash, "recommendation.contentHash") }; }
function decodeHumanDecision(value: unknown): NonNullable<PortfolioDecisionScenario["humanDecision"]> { const row = object(value, "humanDecision"); exact(row, ["decisionId", "conclusion", "rationale", "decidedAt", "contentHash"], "humanDecision"); return { decisionId: id(row.decisionId, "decisionId"), conclusion: enumeration(row.conclusion, humanConclusions, "conclusion"), rationale: text(row.rationale, "rationale"), decidedAt: timestamp(row.decidedAt, "decidedAt"), contentHash: digest(row.contentHash, "humanDecision.contentHash") }; }
function object(value: unknown, name: string): Record<string, unknown> { if (!value || typeof value !== "object" || Array.isArray(value)) fail(`${name} must be an object.`); return value as Record<string, unknown>; }
function array(value: unknown, name: string): unknown[] { if (!Array.isArray(value)) fail(`${name} must be an array.`); return value; }
function exact(value: Record<string, unknown>, keys: string[], name: string) { const actual = Object.keys(value).sort(); const expected = [...keys].sort(); if (actual.join("|") !== expected.join("|")) fail(`${name} fields are invalid.`); }
function text(value: unknown, name: string): string { if (typeof value !== "string" || value.trim() === "") fail(`${name} must be nonblank.`); return value; }
function id(value: unknown, name: string): string { const result = text(value, name); if (!uuid.test(result)) fail(`${name} is invalid.`); return result; }
function digest(value: unknown, name: string): string { const result = text(value, name); if (!hash.test(result)) fail(`${name} is invalid.`); return result; }
function dec(value: unknown, name: string): string { const result = text(value, name); if (!decimal.test(result)) fail(`${name} is not a canonical decimal.`); return result; }
function subtract(left: string, right: string): string { const [leftScale, leftInt] = scaled(left); const [rightScale, rightInt] = scaled(right); const scale = Math.max(leftScale, rightScale); const value = leftInt * BigInt(10) ** BigInt(scale - leftScale) - rightInt * BigInt(10) ** BigInt(scale - rightScale); const negative = value < BigInt(0); const absolute = negative ? -value : value; return canonical(`${negative ? "-" : ""}${absolute.toString().padStart(scale + 1, "0").slice(0, -scale || undefined)}${scale ? `.${absolute.toString().padStart(scale + 1, "0").slice(-scale)}` : ""}`); }
function scaled(value: string): [number, bigint] { const negative = value.startsWith("-"); const [whole, fraction = ""] = (negative ? value.slice(1) : value).split("."); const integer = BigInt(`${whole}${fraction}`); return [fraction.length, negative ? -integer : integer]; }
function canonical(value: string): string { const negative = value.startsWith("-"); const [whole, fraction = ""] = (negative ? value.slice(1) : value).split("."); const cleanWhole = whole.replace(/^0+(?=\d)/, ""); const cleanFraction = fraction.replace(/0+$/, ""); const body = cleanFraction ? `${cleanWhole}.${cleanFraction}` : cleanWhole; return /^0(?:\.0*)?$/.test(body) ? "0" : `${negative ? "-" : ""}${body}`; }
function timestamp(value: unknown, name: string): string { const result = text(value, name); if (!instant.test(result) || Number.isNaN(Date.parse(result))) fail(`${name} is not a whole-second instant.`); return result; }
function enumeration<const T extends readonly string[]>(value: unknown, values: T, name: string): T[number] { if (typeof value !== "string" || !values.includes(value)) fail(`${name} is unsupported.`); return value as T[number]; }
function reasons(value: unknown, name: string): string[] { const values = array(value, name).map((item) => text(item, name)); if (new Set(values).size !== values.length || values.join("|") !== [...values].sort().join("|")) fail(`${name} must be unique and sorted.`); return values; }
function uniqueOrdered(values: string[], name: string) { if (new Set(values).size !== values.length || values.join("|") !== [...values].sort().join("|")) fail(`${name} must be unique and ordered.`); }
function fail(message: string): never { throw new PortfolioDecisionContractError(message); }
