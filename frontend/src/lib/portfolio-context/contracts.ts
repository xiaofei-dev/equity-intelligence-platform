export type PortfolioPosition = {
  securityId: string; ticker: string; sleeve: "LONG_TERM_CORE" | "QUANT_TRADING" | "UNASSIGNED";
  sectorCode: string; dataState: "VALID" | "MISSING" | "STALE" | "INVALID";
  marketValue: string | null; assetWeight: string | null;
};
export type SleeveSummary = {
  sleeve: "LONG_TERM_CORE" | "QUANT_TRADING"; marketValue: string; assetWeight: string;
  positionCount: number; modelVersion: string; modelEvidenceLabel: string;
  researchUseAllowed: boolean; evidenceReferenceId: string; evidenceReferenceHash: string;
};
export type UnifiedPortfolioContext = {
  contextId: string; portfolioId: string; recordedAt: string;
  review: null | { reviewId: string; conclusion: "ACKNOWLEDGED" | "REVIEW_REQUIRED" | "NO_ACTION"; rationale: string; contentHash: string; reviewedAt: string };
  riskContext: {
    resultVersion: "unified-portfolio-risk-result-v1.0.0";
    calculationVersion: "UNIFIED-PORTFOLIO-RISK-CALCULATION-v1.0.0";
    asOfTime: string; baseCurrency: "USD"; state: "VALID" | "PARTIAL";
    totals: Record<"cashValue" | "investedValue" | "assetValue" | "liabilityValue" | "netPortfolioValue" | "cashWeight" | "leverageRatio", string>;
    positions: PortfolioPosition[]; sectors: { sectorCode: string; marketValue: string; assetWeight: string }[];
    sleeves: SleeveSummary[];
    constraints: Record<"maximumPositionWeight" | "maximumSectorWeight" | "minimumCashWeight" | "maximumLeverageRatio", string>;
    risk: { status: "PASSED" | "VIOLATED"; reasonCodes: string[]; constraintVersion: "UNIFIED-PORTFOLIO-CONSTRAINTS-v1.0.0" };
    authority: { finalWeightAuthority: false; orderAuthority: false; automaticBrokerageExecution: false; llmDecisionAuthority: false; humanDecisionRequired: true };
    contentHash: string;
  };
};

export class PortfolioContextContractError extends Error {}
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const hash = /^sha256:[0-9a-f]{64}$/;
const decimal = /^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$/;
const instant = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|\+00:00)$/;
function fail(message: string): never { throw new PortfolioContextContractError(message); }
function object(value: unknown, label: string): Record<string, unknown> { if (!value || typeof value !== "object" || Array.isArray(value)) fail(`${label} must be an object.`); return value as Record<string, unknown>; }
function exact(value: Record<string, unknown>, keys: string[], label: string) { const actual = Object.keys(value).sort(); const expected = [...keys].sort(); if (actual.length !== expected.length || actual.some((key, index) => key !== expected[index])) fail(`${label} fields are invalid.`); }
function text(value: unknown, label: string): string { if (typeof value !== "string" || !value || value !== value.trim()) fail(`${label} is invalid.`); return value; }
function dec(value: unknown, label: string): string { const parsed = text(value, label); if (!decimal.test(parsed)) fail(`${label} must be a canonical decimal string.`); return parsed; }
function array(value: unknown, label: string): unknown[] { if (!Array.isArray(value)) fail(`${label} must be an array.`); return value; }

export function isCanonicalPortfolioId(value: string): boolean { return uuid.test(value); }

export function decodeUnifiedPortfolioContext(value: unknown): UnifiedPortfolioContext {
  const root = object(value, "response"); exact(root, ["contextId", "portfolioId", "recordedAt", "review", "riskContext"], "response");
  const contextId = text(root.contextId, "contextId"); const portfolioId = text(root.portfolioId, "portfolioId");
  if (!uuid.test(contextId) || !uuid.test(portfolioId)) fail("Portfolio identifiers must be canonical UUIDs.");
  const recordedAt = text(root.recordedAt, "recordedAt"); if (!instant.test(recordedAt)) fail("recordedAt is invalid.");
  let review: UnifiedPortfolioContext["review"] = null; if (root.review !== null) { const row = object(root.review, "review"); exact(row, ["reviewId", "conclusion", "rationale", "contentHash", "reviewedAt"], "review"); const reviewId = text(row.reviewId, "reviewId"); const conclusion = text(row.conclusion, "conclusion") as NonNullable<UnifiedPortfolioContext["review"]>["conclusion"]; const contentHash = text(row.contentHash, "review.contentHash"); const reviewedAt = text(row.reviewedAt, "reviewedAt"); if (!uuid.test(reviewId) || !["ACKNOWLEDGED", "REVIEW_REQUIRED", "NO_ACTION"].includes(conclusion) || !hash.test(contentHash) || !instant.test(reviewedAt)) fail("Human review is invalid."); review = { reviewId, conclusion, rationale: text(row.rationale, "rationale"), contentHash, reviewedAt }; }
  const risk = object(root.riskContext, "riskContext"); exact(risk, ["resultVersion", "calculationVersion", "asOfTime", "baseCurrency", "state", "totals", "positions", "sectors", "sleeves", "constraints", "risk", "authority", "contentHash"], "riskContext");
  if (risk.resultVersion !== "unified-portfolio-risk-result-v1.0.0" || risk.calculationVersion !== "UNIFIED-PORTFOLIO-RISK-CALCULATION-v1.0.0" || risk.baseCurrency !== "USD" || !["VALID", "PARTIAL"].includes(String(risk.state))) fail("Portfolio result identity is unsupported.");
  const asOfTime = text(risk.asOfTime, "asOfTime"); if (!instant.test(asOfTime)) fail("asOfTime is invalid.");
  const totalsSource = object(risk.totals, "totals"); const totalKeys = ["cashValue", "investedValue", "assetValue", "liabilityValue", "netPortfolioValue", "cashWeight", "leverageRatio"] as const; exact(totalsSource, [...totalKeys], "totals");
  const totals = Object.fromEntries(totalKeys.map((key) => [key, dec(totalsSource[key], `totals.${key}`)])) as UnifiedPortfolioContext["riskContext"]["totals"];
  const positions = array(risk.positions, "positions").map((item): PortfolioPosition => { const row = object(item, "position"); exact(row, ["securityId", "ticker", "sleeve", "sectorCode", "dataState", "marketValue", "assetWeight"], "position"); const securityId = text(row.securityId, "securityId"); if (!uuid.test(securityId)) fail("securityId is invalid."); const dataState = text(row.dataState, "dataState") as PortfolioPosition["dataState"]; if (!["VALID", "MISSING", "STALE", "INVALID"].includes(dataState)) fail("dataState is invalid."); const marketValue = row.marketValue === null ? null : dec(row.marketValue, "marketValue"); const assetWeight = row.assetWeight === null ? null : dec(row.assetWeight, "assetWeight"); if ((dataState === "VALID") !== (marketValue !== null && assetWeight !== null)) fail("Position state/value parity failed."); const sleeve = text(row.sleeve, "sleeve") as PortfolioPosition["sleeve"]; if (!["LONG_TERM_CORE", "QUANT_TRADING", "UNASSIGNED"].includes(sleeve)) fail("Position sleeve is invalid."); return { securityId, ticker: text(row.ticker, "ticker"), sleeve, sectorCode: text(row.sectorCode, "sectorCode"), dataState, marketValue, assetWeight }; });
  if (new Set(positions.map((item) => item.securityId)).size !== positions.length) fail("Position security IDs must be unique.");
  const sectors = array(risk.sectors, "sectors").map((item) => { const row = object(item, "sector"); exact(row, ["sectorCode", "marketValue", "assetWeight"], "sector"); return { sectorCode: text(row.sectorCode, "sectorCode"), marketValue: dec(row.marketValue, "sector.marketValue"), assetWeight: dec(row.assetWeight, "sector.assetWeight") }; });
  const sleeves = array(risk.sleeves, "sleeves").map((item): SleeveSummary => { const row = object(item, "sleeve"); exact(row, ["sleeve", "marketValue", "assetWeight", "positionCount", "modelVersion", "modelEvidenceLabel", "researchUseAllowed", "evidenceReferenceId", "evidenceReferenceHash"], "sleeve"); const sleeve = text(row.sleeve, "sleeve") as SleeveSummary["sleeve"]; if (!["LONG_TERM_CORE", "QUANT_TRADING"].includes(sleeve) || !Number.isInteger(row.positionCount) || Number(row.positionCount) < 0 || typeof row.researchUseAllowed !== "boolean") fail("Sleeve fields are invalid."); const modelVersion = text(row.modelVersion, "modelVersion"); if (modelVersion === "QUANT-TRADING-v2.0.0" && row.researchUseAllowed) fail("Quant v2 cannot receive portfolio research authority."); const referenceHash = text(row.evidenceReferenceHash, "evidenceReferenceHash"); if (!hash.test(referenceHash)) fail("Evidence hash is invalid."); return { sleeve, marketValue: dec(row.marketValue, "sleeve.marketValue"), assetWeight: dec(row.assetWeight, "sleeve.assetWeight"), positionCount: Number(row.positionCount), modelVersion, modelEvidenceLabel: text(row.modelEvidenceLabel, "modelEvidenceLabel"), researchUseAllowed: row.researchUseAllowed, evidenceReferenceId: text(row.evidenceReferenceId, "evidenceReferenceId"), evidenceReferenceHash: referenceHash }; });
  if (sleeves.map((item) => item.sleeve).join("|") !== "LONG_TERM_CORE|QUANT_TRADING") fail("Exactly two ordered sleeves are required.");
  const constraintSource = object(risk.constraints, "constraints"); const constraintKeys = ["maximumPositionWeight", "maximumSectorWeight", "minimumCashWeight", "maximumLeverageRatio"] as const; exact(constraintSource, [...constraintKeys], "constraints"); const constraints = Object.fromEntries(constraintKeys.map((key) => [key, dec(constraintSource[key], `constraints.${key}`)])) as UnifiedPortfolioContext["riskContext"]["constraints"];
  const riskSummary = object(risk.risk, "risk"); exact(riskSummary, ["status", "reasonCodes", "constraintVersion"], "risk"); if (!["PASSED", "VIOLATED"].includes(String(riskSummary.status)) || riskSummary.constraintVersion !== "UNIFIED-PORTFOLIO-CONSTRAINTS-v1.0.0") fail("Risk summary is invalid."); const reasonCodes = array(riskSummary.reasonCodes, "reasonCodes").map((item) => text(item, "reasonCode")); if ((riskSummary.status === "PASSED") !== (reasonCodes.length === 0)) fail("Risk status/reason parity failed.");
  const authority = object(risk.authority, "authority"); exact(authority, ["finalWeightAuthority", "orderAuthority", "automaticBrokerageExecution", "llmDecisionAuthority", "humanDecisionRequired"], "authority"); if (authority.finalWeightAuthority !== false || authority.orderAuthority !== false || authority.automaticBrokerageExecution !== false || authority.llmDecisionAuthority !== false || authority.humanDecisionRequired !== true) fail("Unsafe portfolio authority was returned.");
  const contentHash = text(risk.contentHash, "contentHash"); if (!hash.test(contentHash)) fail("contentHash is invalid.");
  return { contextId, portfolioId, recordedAt, review, riskContext: { resultVersion: "unified-portfolio-risk-result-v1.0.0", calculationVersion: "UNIFIED-PORTFOLIO-RISK-CALCULATION-v1.0.0", asOfTime, baseCurrency: "USD", state: risk.state as "VALID" | "PARTIAL", totals, positions, sectors, sleeves, constraints, risk: { status: riskSummary.status as "PASSED" | "VIOLATED", reasonCodes, constraintVersion: "UNIFIED-PORTFOLIO-CONSTRAINTS-v1.0.0" }, authority: { finalWeightAuthority: false, orderAuthority: false, automaticBrokerageExecution: false, llmDecisionAuthority: false, humanDecisionRequired: true }, contentHash } };
}
