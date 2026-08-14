import "server-only";
import { decodeUnifiedPortfolioContext, isCanonicalPortfolioId, PortfolioContextContractError, type UnifiedPortfolioContext } from "./contracts";

export type PortfolioContextBackendResult = { ok: true; data: UnifiedPortfolioContext } | { ok: false; error: { code: string; message: string; status?: number } };
const identityPattern = /^[A-Za-z0-9._:@+-]{1,128}$/;

export async function loadLatestPortfolioContext(portfolioId: string): Promise<PortfolioContextBackendResult> {
  if (!isCanonicalPortfolioId(portfolioId)) return { ok: false, error: { code: "INVALID_PORTFOLIO_ID", message: "Enter a canonical portfolio identifier." } };
  const baseUrl = process.env.BACKEND_BASE_URL; const identity = process.env.CLOSED_TEST_IDENTITY;
  if (!baseUrl || !identity || !identityPattern.test(identity)) return { ok: false, error: { code: "PORTFOLIO_CONFIGURATION_ERROR", message: "Portfolio context is not configured for this environment." } };
  try {
    const origin = new URL(baseUrl); if (!["http:", "https:"].includes(origin.protocol) || origin.username || origin.password) throw new Error();
    const response = await fetch(new URL(`/api/v1/me/portfolios/${portfolioId}/contexts/latest`, origin), { cache: "no-store", signal: AbortSignal.timeout(10_000), headers: { Accept: "application/json", "X-Test-Identity": identity } });
    const payload: unknown = await response.json();
    if (!response.ok) { const body = typeof payload === "object" && payload ? payload as Record<string, unknown> : {}; return { ok: false, error: { code: typeof body.code === "string" ? body.code : "PORTFOLIO_BACKEND_ERROR", message: typeof body.message === "string" ? body.message : `Spring returned HTTP ${response.status}.`, status: response.status } }; }
    try { const decoded = decodeUnifiedPortfolioContext(payload); if (decoded.portfolioId !== portfolioId) throw new PortfolioContextContractError("Portfolio response identity drift."); return { ok: true, data: decoded }; }
    catch (error) { return { ok: false, error: { code: "PORTFOLIO_CONTRACT_ERROR", message: error instanceof PortfolioContextContractError ? error.message : "The portfolio response is invalid.", status: response.status } }; }
  } catch { return { ok: false, error: { code: "PORTFOLIO_BACKEND_UNAVAILABLE", message: "The Spring portfolio API is unavailable." } }; }
}
