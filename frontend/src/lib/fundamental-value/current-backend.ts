import "server-only";

import { decodeCurrentFundamentalValueAssessment, type CurrentAssessment } from "./current-contracts";
import { currentFundamentalValueAssessmentPath, latestCurrentFundamentalValueAssessmentPath } from "./current-route";

export type CurrentAssessmentBackendResult =
  | { ok: true; data: CurrentAssessment }
  | { ok: false; error: { code: string; message: string; status?: number } };

export async function loadCurrentFundamentalValueAssessment(
  assessmentId: string,
): Promise<CurrentAssessmentBackendResult> {
  let path: string;
  try { path = currentFundamentalValueAssessmentPath(assessmentId); }
  catch { return { ok: false, error: { code: "CURRENT_FUNDAMENTAL_VALUE_INVALID_IDENTIFIER", message: "Enter a canonical current assessment identifier." } }; }
  const result = await loadPath(path);
  if (result.ok && result.data.assessmentId !== assessmentId) return { ok: false, error: { code: "CURRENT_FUNDAMENTAL_VALUE_CONTRACT_ERROR", message: "The Spring response was not bound to the requested assessment." } };
  return result;
}

export async function loadLatestCurrentFundamentalValueAssessment(
  symbol: string,
): Promise<CurrentAssessmentBackendResult> {
  let path: string;
  try { path = latestCurrentFundamentalValueAssessmentPath(symbol); }
  catch { return { ok: false, error: { code: "CURRENT_FUNDAMENTAL_VALUE_INVALID_SYMBOL", message: "Enter a supported uppercase ticker." } }; }
  const result = await loadPath(path);
  if (result.ok && result.data.identity.ticker !== symbol) return { ok: false, error: { code: "CURRENT_FUNDAMENTAL_VALUE_CONTRACT_ERROR", message: "The Spring response was not bound to the requested ticker." } };
  return result;
}

async function loadPath(path: string): Promise<CurrentAssessmentBackendResult> {
  const baseUrl = process.env.BACKEND_BASE_URL;
  const identity = process.env.CLOSED_TEST_IDENTITY;
  if (!baseUrl || !identity || !/^[A-Za-z0-9._:@+-]{1,128}$/.test(identity)) return { ok: false, error: { code: "CURRENT_FUNDAMENTAL_VALUE_CONFIGURATION_ERROR", message: "Current Fundamental Value is not configured for this environment." } };
  try {
    const origin = new URL(baseUrl);
    if (!["http:", "https:"].includes(origin.protocol) || origin.username || origin.password) throw new Error();
    const response = await fetch(new URL(path, baseUrl.endsWith("/") ? baseUrl : `${baseUrl}/`), { cache: "no-store", signal: AbortSignal.timeout(10_000), headers: { Accept: "application/json", "X-Test-Identity": identity } });
    const payload: unknown = await response.json();
    if (!response.ok) return { ok: false, error: { code: "CURRENT_FUNDAMENTAL_VALUE_BACKEND_ERROR", message: `The Spring API returned HTTP ${response.status}.`, status: response.status } };
    return { ok: true, data: decodeCurrentFundamentalValueAssessment(payload) };
  } catch { return { ok: false, error: { code: "CURRENT_FUNDAMENTAL_VALUE_BACKEND_UNAVAILABLE", message: "The Spring current Fundamental Value API is unavailable." } }; }
}
