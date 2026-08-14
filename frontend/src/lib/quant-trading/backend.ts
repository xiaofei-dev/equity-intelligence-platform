import "server-only";

import { bindDecisionToRequestedId, decodeQuantResearchDecision, QuantResearchContractError, type QuantResearchDecision } from "./contracts";
import { quantResearchDecisionPath } from "./route";

export type QuantResearchBackendResult =
  | { ok: true; data: QuantResearchDecision }
  | { ok: false; error: { code: string; message: string; status?: number } };

export async function loadQuantResearchDecision(decisionId: string): Promise<QuantResearchBackendResult> {
  let path: string;
  try { path = quantResearchDecisionPath(decisionId); }
  catch { return { ok: false, error: { code: "QUANT_RESEARCH_INVALID_IDENTIFIER", message: "Enter a canonical Quant research decision identifier." } }; }
  const baseUrl = process.env.BACKEND_BASE_URL; const identity = process.env.CLOSED_TEST_IDENTITY;
  if (!baseUrl || !identity || !/^[A-Za-z0-9._:@+-]{1,128}$/.test(identity)) return { ok: false, error: { code: "QUANT_RESEARCH_CONFIGURATION_ERROR", message: "Quant research is not configured for this environment." } };
  try {
    const response = await fetch(new URL(path, baseUrl.endsWith("/") ? baseUrl : `${baseUrl}/`), { cache: "no-store", signal: AbortSignal.timeout(10_000), headers: { Accept: "application/json", "X-Test-Identity": identity } });
    let payload: unknown; try { payload = await response.json(); } catch { return { ok: false, error: { code: "QUANT_RESEARCH_CONTRACT_ERROR", message: "The Spring API returned a non-JSON response.", status: response.status } }; }
    if (!response.ok) { const body = typeof payload === "object" && payload !== null ? payload as Record<string, unknown> : {}; return { ok: false, error: { code: "QUANT_RESEARCH_BACKEND_ERROR", message: typeof body.message === "string" ? body.message : `The Spring API returned HTTP ${response.status}.`, status: response.status } }; }
    try { return { ok: true, data: bindDecisionToRequestedId(decodeQuantResearchDecision(payload), decisionId) }; }
    catch (error) { return { ok: false, error: { code: "QUANT_RESEARCH_CONTRACT_ERROR", message: error instanceof QuantResearchContractError ? error.message : "The Spring response did not match the Quant contract.", status: response.status } }; }
	} catch { return { ok: false, error: { code: "QUANT_RESEARCH_BACKEND_UNAVAILABLE", message: "The Spring Quant research API is currently unavailable." } }; }
}
