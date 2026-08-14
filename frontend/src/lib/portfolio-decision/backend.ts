import "server-only";
import { decodePortfolioDecisionScenario, decodePortfolioDecisionScenarios, humanConclusions, type HumanConclusion, type PortfolioDecisionScenario, PortfolioDecisionContractError } from "./contracts";
import { decodeComparison, type Comparison } from "./v32";

export type PortfolioDecisionBackendResult = { ok: true; data: PortfolioDecisionScenario[] } | { ok: false; error: { code: string; message: string; status?: number } };
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const keyPattern = /^[A-Za-z0-9._:@+-]{1,128}$/;

function configuration(): { origin: URL; identity: string } | null { const baseUrl = process.env.BACKEND_BASE_URL; const identity = process.env.CLOSED_TEST_IDENTITY; if (!baseUrl || !identity || !keyPattern.test(identity)) return null; try { const origin = new URL(baseUrl); if (!['http:', 'https:'].includes(origin.protocol) || origin.username || origin.password) return null; return { origin, identity }; } catch { return null; } }

export async function loadPortfolioDecisionScenarios(portfolioId: string): Promise<PortfolioDecisionBackendResult> {
  if (!uuid.test(portfolioId)) return { ok: false, error: { code: "INVALID_PORTFOLIO_ID", message: "Enter a canonical portfolio identifier." } };
  const config = configuration(); if (!config) return { ok: false, error: { code: "PORTFOLIO_DECISION_CONFIGURATION_ERROR", message: "Portfolio decision support is not configured." } };
  try { const response = await fetch(new URL(`/api/v1/me/portfolios/${portfolioId}/decision-scenarios`, config.origin), { cache: "no-store", signal: AbortSignal.timeout(10_000), headers: { Accept: "application/json", "X-Test-Identity": config.identity } }); const payload: unknown = await response.json(); if (!response.ok) return backendError(response.status, payload); try { const data = decodePortfolioDecisionScenarios(payload); if (data.some((item) => item.portfolioId !== portfolioId)) throw new PortfolioDecisionContractError("Portfolio identity drift."); return { ok: true, data }; } catch (error) { return { ok: false, error: { code: "PORTFOLIO_DECISION_CONTRACT_ERROR", message: error instanceof PortfolioDecisionContractError ? error.message : "The Spring scenario response is invalid.", status: response.status } }; } } catch { return { ok: false, error: { code: "PORTFOLIO_DECISION_BACKEND_UNAVAILABLE", message: "The Spring portfolio decision API is unavailable." } }; }
}

export async function submitPortfolioHumanDecision(input: { portfolioId: string; scenarioId: string; conclusion: HumanConclusion; rationale: string; idempotencyKey: string }): Promise<{ ok: true } | { ok: false; error: string }> {
  if (!uuid.test(input.portfolioId) || !uuid.test(input.scenarioId) || !humanConclusions.includes(input.conclusion) || input.rationale.trim() === "" || input.rationale.length > 4000 || !keyPattern.test(input.idempotencyKey)) return { ok: false, error: "The human decision request is invalid." };
  const config = configuration(); if (!config) return { ok: false, error: "Portfolio decision support is not configured." };
  try { const response = await fetch(new URL(`/api/v1/me/portfolios/${input.portfolioId}/decision-scenarios/${input.scenarioId}/decisions`, config.origin), { method: "POST", cache: "no-store", signal: AbortSignal.timeout(10_000), headers: { Accept: "application/json", "Content-Type": "application/json", "X-Test-Identity": config.identity, "Idempotency-Key": input.idempotencyKey }, body: JSON.stringify({ conclusion: input.conclusion, rationale: input.rationale, supersedesDecisionId: null }) }); if (!response.ok) return { ok: false, error: `Spring rejected the human decision (HTTP ${response.status}).` }; return { ok: true }; } catch { return { ok: false, error: "The Spring portfolio decision API is unavailable." }; }
}

export type WorkflowResult = { ok: true; data: Record<string, unknown> } | { ok: false; error: string };

export async function createCurrentEvidenceContext(input: { portfolioId: string; idempotencyKey: string; accountSnapshotIds: string[]; constraintPolicyVersionId: string; evidenceReferences: unknown[] }): Promise<WorkflowResult> {
  return springPost(input.portfolioId, "/contexts/current-evidence", input.idempotencyKey, { accountSnapshotIds: input.accountSnapshotIds, constraintPolicyVersionId: input.constraintPolicyVersionId, evidenceReferences: input.evidenceReferences });
}

export async function createPortfolioScenario(input: { portfolioId: string; idempotencyKey: string; body: Record<string, unknown> }): Promise<WorkflowResult> {
  const result = await springPost(input.portfolioId, "/decision-scenarios", input.idempotencyKey, input.body);
  if (!result.ok) return result;
  try { return { ok: true, data: decodePortfolioDecisionScenario(result.data) as unknown as Record<string, unknown> }; }
  catch { return { ok: false, error: "Spring returned an invalid scenario contract." }; }
}

export async function createExactFourScenarioComparison(input: { portfolioId: string; idempotencyKey: string; body: Record<string, unknown> }): Promise<{ ok: true; data: Comparison } | { ok: false; error: string }> {
  const result = await springPost(input.portfolioId, "/decision-scenarios/comparisons", input.idempotencyKey, input.body);
  if (!result.ok) return result;
  try { return { ok: true, data: decodeComparison(result.data, input.portfolioId) }; }
  catch { return { ok: false, error: "Spring returned an invalid exact-four comparison contract." }; }
}

export async function selectExactFourScenario(input:{portfolioId:string;comparisonId:string;selectedScenarioType:string;idempotencyKey:string}):Promise<{ok:true;data:Comparison}|{ok:false;error:string}>{if(!uuid.test(input.comparisonId))return{ok:false,error:"The comparison identifier is invalid."};const result=await springPost(input.portfolioId,`/decision-scenarios/comparisons/${input.comparisonId}/selection`,input.idempotencyKey,{selectedScenarioType:input.selectedScenarioType});if(!result.ok)return result;try{return{ok:true,data:decodeComparison(result.data,input.portfolioId)}}catch{return{ok:false,error:"Spring returned an invalid selected comparison."}}}

export async function createPortfolioEvaluation(input: { portfolioId: string; scenarioId: string; idempotencyKey: string; body: Record<string, unknown> }): Promise<WorkflowResult> {
  if (!uuid.test(input.scenarioId)) return { ok: false, error: "The scenario identifier is invalid." };
  return springPost(input.portfolioId, `/decision-scenarios/${input.scenarioId}/evaluations`, input.idempotencyKey, input.body);
}

export async function sealPortfolioLongitudinalHorizon(input: { portfolioId: string; scenarioId: string; evaluationId: string; idempotencyKey: string; horizonSessions: number }): Promise<WorkflowResult> {
  if (![input.scenarioId, input.evaluationId].every((value) => uuid.test(value)) || ![20, 60, 252, 504, 756].includes(input.horizonSessions)) return { ok: false, error: "The longitudinal sealing request is invalid." };
  return springPost(input.portfolioId, `/decision-scenarios/${input.scenarioId}/evaluations/${input.evaluationId}/longitudinal/seal`, input.idempotencyKey, { horizonSessions: input.horizonSessions });
}

export async function recordPortfolioThesisReview(input: { portfolioId: string; scenarioId: string; evaluationId: string; idempotencyKey: string; body: Record<string, unknown> }): Promise<WorkflowResult> {
  if (![input.scenarioId, input.evaluationId].every((value) => uuid.test(value))) return { ok: false, error: "The thesis review request is invalid." };
  return springPost(input.portfolioId, `/decision-scenarios/${input.scenarioId}/evaluations/${input.evaluationId}/thesis-reviews`, input.idempotencyKey, input.body);
}

async function springPost(portfolioId: string, suffix: string, idempotencyKey: string, body: unknown): Promise<WorkflowResult> {
  if (!uuid.test(portfolioId) || !keyPattern.test(idempotencyKey) || !suffix.startsWith("/")) return { ok: false, error: "The workflow request is invalid." };
  const config = configuration(); if (!config) return { ok: false, error: "Portfolio decision support is not configured." };
  try {
    const response = await fetch(new URL(`/api/v1/me/portfolios/${portfolioId}${suffix}`, config.origin), { method: "POST", cache: "no-store", signal: AbortSignal.timeout(20_000), headers: { Accept: "application/json", "Content-Type": "application/json", "X-Test-Identity": config.identity, "Idempotency-Key": idempotencyKey }, body: JSON.stringify(body) });
    const payload: unknown = await response.json();
    if (!response.ok) return { ok: false, error: `Spring rejected the workflow request (HTTP ${response.status}).` };
    if (!payload || typeof payload !== "object" || Array.isArray(payload)) return { ok: false, error: "Spring returned an invalid workflow response." };
    return { ok: true, data: payload as Record<string, unknown> };
  } catch { return { ok: false, error: "The Spring portfolio workflow API is unavailable." }; }
}

function backendError(status: number, payload: unknown): PortfolioDecisionBackendResult { const row = payload && typeof payload === "object" ? payload as Record<string, unknown> : {}; return { ok: false, error: { code: typeof row.code === "string" ? row.code : "PORTFOLIO_DECISION_BACKEND_ERROR", message: typeof row.message === "string" ? row.message : `Spring returned HTTP ${status}.`, status } }; }
