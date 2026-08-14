"use server";

import { randomUUID } from "node:crypto";
import { redirect } from "next/navigation";
import { createCurrentEvidenceContext, createExactFourScenarioComparison, createPortfolioEvaluation, recordPortfolioThesisReview, sealPortfolioLongitudinalHorizon, selectExactFourScenario } from "@/lib/portfolio-decision/backend";

const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const decimal = /^(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$/;

function text(form: FormData, name: string): string { return String(form.get(name) ?? "").trim(); }
function ids(value: string): string[] { const result = value.split(/[\s,]+/).filter(Boolean); if (result.length === 0 || result.some((item) => !uuid.test(item))) throw new Error("INVALID_UUID_LIST"); return result; }
function jsonArray(value: string): unknown[] { const parsed: unknown = JSON.parse(value); if (!Array.isArray(parsed) || parsed.length === 0) throw new Error("INVALID_JSON_ARRAY"); return parsed; }
function target(portfolioId: string, status: string, extra: Record<string, string> = {}) { const query = new URLSearchParams({ portfolioId, workflowStatus: status, ...extra }); redirect(`/portfolio?${query}`); }

export async function assembleCurrentEvidence(form: FormData): Promise<void> {
  const portfolioId = text(form, "portfolioId");
  let status = "CURRENT_EVIDENCE_INVALID"; let extra: Record<string, string> = {};
  try {
    const result = await createCurrentEvidenceContext({ portfolioId, idempotencyKey: randomUUID(), accountSnapshotIds: ids(text(form, "accountSnapshotIds")), constraintPolicyVersionId: text(form, "constraintPolicyVersionId"), evidenceReferences: jsonArray(text(form, "evidenceReferences")) });
    if (!result.ok) status = "CURRENT_EVIDENCE_FAILED";
    else { const context = result.data.context as Record<string, unknown> | undefined; const contextId = typeof context?.contextId === "string" ? context.contextId : ""; const evidenceManifestId = typeof result.data.evidenceManifestId === "string" ? result.data.evidenceManifestId : ""; if (uuid.test(contextId) && uuid.test(evidenceManifestId)) { status = "CURRENT_EVIDENCE_CREATED"; extra = { contextId, evidenceManifestId }; } else status = "CURRENT_EVIDENCE_CONTRACT_ERROR"; }
  } catch { status = "CURRENT_EVIDENCE_INVALID"; }
  target(portfolioId, status, extra);
}

export async function createFourDecisionScenarios(form: FormData): Promise<void> {
  const portfolioId = text(form, "portfolioId");
  let status = "SCENARIO_REQUEST_INVALID"; let extra: Record<string, string> = {};
  try {
    const contextId = text(form, "contextId"); const evidenceManifestId = text(form, "evidenceManifestId"); const constraintPolicyVersionId = text(form, "constraintPolicyVersionId");
    if (![portfolioId, contextId, evidenceManifestId, constraintPolicyVersionId].every((item) => uuid.test(item))) throw new Error("INVALID_UUID");
    const candidates = jsonArray(text(form, "candidates")); const newMoneyAmount = text(form, "newMoneyAmount"); const coreBudget = text(form, "coreBudget"); const quantBudget = text(form, "quantBudget");
    if (![newMoneyAmount, coreBudget, quantBudget].every((item) => decimal.test(item))) throw new Error("INVALID_DECIMAL");
    const sleeveBudgets = [{ sleeve: "LONG_TERM_CORE", maximumWeight: coreBudget }, { sleeve: "QUANT_TRADING", maximumWeight: quantBudget }];
    const result = await createExactFourScenarioComparison({ portfolioId, idempotencyKey: randomUUID(), body: { contextId, evidenceManifestId, constraintPolicyVersionId, newMoneyAmount, sleeveBudgets, candidates } });
    if (!result.ok) status = "FOUR_SCENARIO_COMPARISON_FAILED";
    else { status = "FOUR_SCENARIO_COMPARISON_CREATED"; extra = { contextId, evidenceManifestId, comparisonId: result.data.comparisonId }; }
  } catch { status = "SCENARIO_REQUEST_INVALID"; }
  target(portfolioId, status, extra);
}

export async function selectComparisonScenario(form:FormData):Promise<void>{const portfolioId=text(form,"portfolioId"),comparisonId=text(form,"comparisonId"),selectedScenarioType=text(form,"selectedScenarioType");let status="COMPARISON_SELECTION_INVALID";try{if(!uuid.test(portfolioId)||!uuid.test(comparisonId)||!["HOLD_CURRENT","NEW_MONEY_ONLY","CONSTRAINED_REBALANCE","TARGET_PORTFOLIO"].includes(selectedScenarioType))throw new Error("INVALID_SELECTION");const result=await selectExactFourScenario({portfolioId,comparisonId,selectedScenarioType,idempotencyKey:randomUUID()});status=result.ok?"COMPARISON_RECOMMENDATION_BOUND":"COMPARISON_SELECTION_FAILED";}catch{status="COMPARISON_SELECTION_INVALID";}target(portfolioId,status);}

export async function sealLongitudinalHorizon(form: FormData): Promise<void> {
  const portfolioId=text(form,"portfolioId"),scenarioId=text(form,"scenarioId"),evaluationId=text(form,"evaluationId"); let status="LONGITUDINAL_SEAL_INVALID";
  try { const horizonSessions=Number(text(form,"horizonSessions")); if(![portfolioId,scenarioId,evaluationId].every(value=>uuid.test(value))||![20,60,252,504,756].includes(horizonSessions))throw new Error("INVALID_LONGITUDINAL_SEAL"); const result=await sealPortfolioLongitudinalHorizon({portfolioId,scenarioId,evaluationId,idempotencyKey:randomUUID(),horizonSessions}); status=result.ok?"LONGITUDINAL_HORIZON_SEALED":"LONGITUDINAL_HORIZON_NOT_READY"; } catch { status="LONGITUDINAL_SEAL_INVALID"; } target(portfolioId,status);
}

export async function recordThesisReview(form: FormData): Promise<void> {
  const portfolioId=text(form,"portfolioId"),scenarioId=text(form,"scenarioId"),evaluationId=text(form,"evaluationId"),state=text(form,"state"),rationale=text(form,"rationale"),supersedes=text(form,"supersedesReviewId"); let status="THESIS_REVIEW_INVALID";
  try { const horizonSessions=Number(text(form,"horizonSessions")); if(![portfolioId,scenarioId,evaluationId].every(value=>uuid.test(value))||supersedes!==""&&!uuid.test(supersedes)||![20,60,252,504,756].includes(horizonSessions)||!["CONFIRMED","WEAKENED","INVALIDATED","INSUFFICIENT_EVIDENCE"].includes(state)||!rationale||rationale.length>4000)throw new Error("INVALID_THESIS_REVIEW"); const result=await recordPortfolioThesisReview({portfolioId,scenarioId,evaluationId,idempotencyKey:randomUUID(),body:{horizonSessions,state,rationale,supersedesReviewId:supersedes||null}}); status=result.ok?"THESIS_REVIEW_RECORDED":"THESIS_REVIEW_FAILED"; } catch { status="THESIS_REVIEW_INVALID"; } target(portfolioId,status);
}

export async function createSimulationEvaluation(form: FormData): Promise<void> {
  const portfolioId = text(form, "portfolioId"); const scenarioId = text(form, "scenarioId");
  let status = "EVALUATION_REQUEST_INVALID";
  try {
    const body = { humanDecisionId: text(form, "humanDecisionId"), startingContextId: text(form, "startingContextId"), holdCurrentScenarioId: text(form, "holdCurrentScenarioId") };
    if (![portfolioId, scenarioId, ...Object.values(body)].every((item) => uuid.test(item))) throw new Error("INVALID_UUID");
    const result = await createPortfolioEvaluation({ portfolioId, scenarioId, idempotencyKey: randomUUID(), body });
    status = result.ok ? "EVALUATION_CREATED" : "EVALUATION_FAILED";
  } catch { status = "EVALUATION_REQUEST_INVALID"; }
  target(portfolioId, status);
}
