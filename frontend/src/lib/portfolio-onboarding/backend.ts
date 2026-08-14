import "server-only";

export type AccountSummary = {
  id: string;
  name: string;
  accountType: "REAL" | "SIMULATED" | "RETIREMENT";
  baseCurrency: "USD";
  status: string;
  createdAt: string;
};

export type PortfolioSummary = {
  id: string;
  name: string;
  baseCurrency: "USD";
  status: string;
  accountIds: string[];
  createdAt: string;
};

export type OnboardingInventory = {
  ok: true;
  accounts: AccountSummary[];
  portfolios: PortfolioSummary[];
  liabilities: LiabilitySummary[];
} | { ok: false; error: string };

export type LiabilitySummary = { id: string; accountId: string; name: string; liabilityType: "MARGIN" | "LOAN" | "OTHER"; currency: "USD"; status: string; createdAt: string };

const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const identityPattern = /^[A-Za-z0-9._:@+-]{1,128}$/;

function configured(): { origin: URL; identity: string } | null {
  const baseUrl = process.env.BACKEND_BASE_URL;
  const identity = process.env.CLOSED_TEST_IDENTITY;
  if (!baseUrl || !identity || !identityPattern.test(identity)) return null;
  try {
    const origin = new URL(baseUrl);
    if (!["http:", "https:"].includes(origin.protocol) || origin.username || origin.password) return null;
    return { origin, identity };
  } catch { return null; }
}

export async function loadOnboardingInventory(): Promise<OnboardingInventory> {
  const config = configured();
  if (!config) return { ok: false, error: "Portfolio onboarding is not configured." };
  try {
    const headers = { Accept: "application/json", "X-Test-Identity": config.identity };
    const [accountsResponse, portfoliosResponse, liabilitiesResponse] = await Promise.all([
      fetch(new URL("/api/v1/me/accounts", config.origin), { cache: "no-store", headers, signal: AbortSignal.timeout(10_000) }),
      fetch(new URL("/api/v1/me/portfolios", config.origin), { cache: "no-store", headers, signal: AbortSignal.timeout(10_000) }),
      fetch(new URL("/api/v1/me/liabilities", config.origin), { cache: "no-store", headers, signal: AbortSignal.timeout(10_000) }),
    ]);
    if (!accountsResponse.ok || !portfoliosResponse.ok || !liabilitiesResponse.ok) return { ok: false, error: "Spring could not load the owner-isolated inventory." };
    const accounts: unknown = await accountsResponse.json(); const portfolios: unknown = await portfoliosResponse.json(); const liabilities: unknown = await liabilitiesResponse.json();
    if (!Array.isArray(accounts) || !Array.isArray(portfolios) || !Array.isArray(liabilities)) return { ok: false, error: "Spring returned an invalid onboarding inventory." };
    const validAccounts = accounts.filter((item): item is AccountSummary => validAccount(item));
    const validPortfolios = portfolios.filter((item): item is PortfolioSummary => validPortfolio(item));
    const validLiabilities = liabilities.filter((item): item is LiabilitySummary => validLiability(item));
    if (validAccounts.length !== accounts.length || validPortfolios.length !== portfolios.length || validLiabilities.length !== liabilities.length) return { ok: false, error: "Spring returned an invalid onboarding inventory." };
    return { ok: true, accounts: validAccounts, portfolios: validPortfolios, liabilities: validLiabilities };
  } catch { return { ok: false, error: "The Spring onboarding API is unavailable." }; }
}

function validAccount(value: unknown): value is AccountSummary {
  if (!value || typeof value !== "object") return false; const row = value as Record<string, unknown>;
  return typeof row.id === "string" && uuid.test(row.id) && typeof row.name === "string" && ["REAL", "SIMULATED", "RETIREMENT"].includes(String(row.accountType)) && row.baseCurrency === "USD" && typeof row.status === "string" && typeof row.createdAt === "string";
}

function validPortfolio(value: unknown): value is PortfolioSummary {
  if (!value || typeof value !== "object") return false; const row = value as Record<string, unknown>;
  return typeof row.id === "string" && uuid.test(row.id) && typeof row.name === "string" && row.baseCurrency === "USD" && typeof row.status === "string" && Array.isArray(row.accountIds) && row.accountIds.every((item) => typeof item === "string" && uuid.test(item)) && typeof row.createdAt === "string";
}

function validLiability(value: unknown): value is LiabilitySummary { if (!value || typeof value !== "object") return false; const row = value as Record<string, unknown>; return typeof row.id === "string" && uuid.test(row.id) && typeof row.accountId === "string" && uuid.test(row.accountId) && typeof row.name === "string" && ["MARGIN", "LOAN", "OTHER"].includes(String(row.liabilityType)) && row.currency === "USD" && typeof row.status === "string" && typeof row.createdAt === "string"; }
