import "server-only";

import {
  decodeFundamentalValueDecision,
  bindDecisionToRequestedAssembly,
  FundamentalValueContractError,
  type FundamentalValueDecision,
} from "./contracts";
import { fundamentalValueDecisionPath } from "./route";

export type FundamentalValueBackendError = {
  code:
    | "FUNDAMENTAL_VALUE_CONFIGURATION_ERROR"
    | "FUNDAMENTAL_VALUE_BACKEND_UNAVAILABLE"
    | "FUNDAMENTAL_VALUE_BACKEND_ERROR"
    | "FUNDAMENTAL_VALUE_CONTRACT_ERROR"
    | "FUNDAMENTAL_VALUE_INVALID_IDENTIFIER";
  message: string;
  status?: number;
};

export type FundamentalValueBackendResult =
  | { ok: true; data: FundamentalValueDecision }
  | { ok: false; error: FundamentalValueBackendError };

const identityPattern = /^[A-Za-z0-9._:@+-]{1,128}$/;

function configuration():
  | { ok: true; baseUrl: string; identity: string }
  | { ok: false; error: FundamentalValueBackendError } {
  const baseUrl = process.env.BACKEND_BASE_URL;
  const identity = process.env.CLOSED_TEST_IDENTITY;
  if (!baseUrl || !identity || !identityPattern.test(identity)) {
    return { ok: false, error: { code: "FUNDAMENTAL_VALUE_CONFIGURATION_ERROR", message: "Fundamental Value is not configured for this environment." } };
  }
  try {
    const url = new URL(baseUrl);
    if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password) throw new Error();
  } catch {
    return { ok: false, error: { code: "FUNDAMENTAL_VALUE_CONFIGURATION_ERROR", message: "The configured Spring API origin is invalid." } };
  }
  return { ok: true, baseUrl, identity };
}

export async function loadFundamentalValueDecision(
  assemblyId: string,
): Promise<FundamentalValueBackendResult> {
  let path: string;
  try {
    path = fundamentalValueDecisionPath(assemblyId);
  } catch {
    return { ok: false, error: { code: "FUNDAMENTAL_VALUE_INVALID_IDENTIFIER", message: "Enter a canonical Fundamental Value assembly identifier." } };
  }
  const config = configuration();
  if (!config.ok) return config;
  try {
    const response = await fetch(new URL(path, config.baseUrl.endsWith('/') ? config.baseUrl : `${config.baseUrl}/`), {
      cache: "no-store",
      signal: AbortSignal.timeout(10_000),
      headers: { Accept: "application/json", "X-Test-Identity": config.identity },
    });
    let payload: unknown;
    try { payload = await response.json(); }
    catch { return { ok: false, error: { code: "FUNDAMENTAL_VALUE_CONTRACT_ERROR", message: "The Spring API returned a non-JSON response.", status: response.status } }; }
    if (!response.ok) {
      const body = typeof payload === "object" && payload !== null ? payload as Record<string, unknown> : {};
      return { ok: false, error: { code: "FUNDAMENTAL_VALUE_BACKEND_ERROR", message: typeof body.message === "string" ? body.message : `The Spring API returned HTTP ${response.status}.`, status: response.status } };
    }
    try {
      const decoded = decodeFundamentalValueDecision(payload);
      return { ok: true, data: bindDecisionToRequestedAssembly(decoded, assemblyId) };
    }
    catch (error) {
      return { ok: false, error: { code: "FUNDAMENTAL_VALUE_CONTRACT_ERROR", message: error instanceof FundamentalValueContractError ? error.message : "The Spring response did not match the supported Fundamental Value contract.", status: response.status } };
    }
  } catch {
    return { ok: false, error: { code: "FUNDAMENTAL_VALUE_BACKEND_UNAVAILABLE", message: "The Spring Fundamental Value API is currently unavailable." } };
  }
}
