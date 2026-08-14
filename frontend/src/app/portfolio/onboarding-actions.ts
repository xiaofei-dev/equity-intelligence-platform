"use server";

import { revalidatePath } from "next/cache";
import { randomUUID } from "node:crypto";
import { canonicalId, springJson } from "@/lib/portfolio-onboarding/mutations";

export type OnboardingActionState = { ok: boolean; code: string; message: string };
const invalid = (message: string): OnboardingActionState => ({ ok: false, code: "INVALID_ONBOARDING_INPUT", message });
const failed = (result: { code: string; message: string }): OnboardingActionState => ({ ok: false, code: result.code, message: result.message });
const completed = (message: string): OnboardingActionState => ({ ok: true, code: "COMPLETED", message });

export async function createAccount(_previous: OnboardingActionState, form: FormData): Promise<OnboardingActionState> {
  const name = String(form.get("name") ?? "").trim(); const accountType = String(form.get("accountType") ?? "");
  if (!name || name.length > 160 || !["REAL", "SIMULATED", "RETIREMENT"].includes(accountType)) return invalid("Enter a name and supported account type.");
  const result = await springJson("/api/v1/me/accounts", "POST", { name, accountType, baseCurrency: "USD" });
  if (!result.ok) return failed(result); revalidatePath("/portfolio"); return completed("Account created through Spring.");
}

export async function createPortfolio(_previous: OnboardingActionState, form: FormData): Promise<OnboardingActionState> {
  const name = String(form.get("name") ?? "").trim(); if (!name || name.length > 160) return invalid("Enter a portfolio name.");
  const result = await springJson("/api/v1/me/portfolios", "POST", { name, baseCurrency: "USD" });
  if (!result.ok) return failed(result); revalidatePath("/portfolio"); return completed("Portfolio created through Spring.");
}

export async function linkPortfolioAccounts(_previous: OnboardingActionState, form: FormData): Promise<OnboardingActionState> {
  const portfolioId = String(form.get("portfolioId") ?? ""); const accountIds = form.getAll("accountIds").map(String);
  if (!canonicalId(portfolioId) || accountIds.length === 0 || accountIds.some((item) => !canonicalId(item))) return invalid("Choose one portfolio and at least one account.");
  const result = await springJson(`/api/v1/me/portfolios/${portfolioId}/accounts`, "PUT", { accountIds });
  if (!result.ok) return failed(result); revalidatePath(`/portfolio?portfolioId=${portfolioId}`); return completed("Portfolio membership updated through Spring.");
}

export async function createManualSnapshot(_previous: OnboardingActionState, form: FormData): Promise<OnboardingActionState> {
  const accountId = String(form.get("accountId") ?? ""); const securityPublicIds = form.getAll("securityPublicId").map(String);
  const asOfTime = new Date(Math.floor(Date.now() / 1000) * 1000).toISOString(); const settledAmount = String(form.get("settledAmount") ?? "");
  const quantities = form.getAll("quantity").map(String); const averageCosts = form.getAll("averageCost").map(String); const idempotencyKey = randomUUID();
  if (!canonicalId(accountId) || !settledAmount || securityPublicIds.length === 0 || securityPublicIds.length > 500 || quantities.length !== securityPublicIds.length || averageCosts.length !== securityPublicIds.length || securityPublicIds.some((item) => !canonicalId(item)) || quantities.some((item) => !item) || averageCosts.some((item) => !item)) return invalid("Account, cash, and complete security, quantity, and cost rows are required.");
  const positions = securityPublicIds.map((securityPublicId, index) => ({ securityPublicId, quantity: quantities[index], averageCost: averageCosts[index], costCurrency: "USD" }));
  const result = await springJson(`/api/v1/me/accounts/${accountId}/snapshots/manual`, "POST", { asOfTime, completeness: "COMPLETE", cashBalances: [{ currency: "USD", settledAmount, unsettledAmount: "0", restrictedAmount: "0" }], positions }, idempotencyKey);
  if (!result.ok) return failed(result); revalidatePath("/portfolio"); return completed("Complete manual snapshot sealed through Spring.");
}

export async function createLiability(_previous: OnboardingActionState, form: FormData): Promise<OnboardingActionState> {
  const accountId = String(form.get("accountId") ?? ""); const name = String(form.get("name") ?? "").trim(); const liabilityType = String(form.get("liabilityType") ?? "");
  if (!canonicalId(accountId) || !name || name.length > 160 || !["MARGIN", "LOAN", "OTHER"].includes(liabilityType)) return invalid("Choose an account and enter a supported liability.");
  const result = await springJson("/api/v1/me/liabilities", "POST", { accountId, name, liabilityType, currency: "USD" });
  if (!result.ok) return failed(result); revalidatePath("/portfolio"); return completed("Liability created through Spring; record its balance before relying on leverage context.");
}

export async function recordLiabilityBalance(_previous: OnboardingActionState, form: FormData): Promise<OnboardingActionState> {
  const liabilityId = String(form.get("liabilityId") ?? ""); const balance = String(form.get("balance") ?? ""); const annualInterestRate = String(form.get("annualInterestRate") ?? "");
  if (!canonicalId(liabilityId) || !balance) return invalid("Choose a liability and enter its current balance.");
  const result = await springJson(`/api/v1/me/liabilities/${liabilityId}/balances`, "POST", { asOfTime: new Date(Math.floor(Date.now() / 1000) * 1000).toISOString(), balance, annualInterestRate: annualInterestRate || null, sourceType: "MANUAL" }, randomUUID());
  if (!result.ok) return failed(result); revalidatePath("/portfolio"); return completed("Liability balance recorded through Spring.");
}

export async function createPortfolioConstraints(_previous: OnboardingActionState, form: FormData): Promise<OnboardingActionState> {
  const portfolioId = String(form.get("portfolioId") ?? ""); if (!canonicalId(portfolioId)) return invalid("Choose a portfolio.");
  const optional = (name: string) => { const value = String(form.get(name) ?? "").trim(); return value === "" ? null : value; };
  const result = await springJson("/api/v1/me/constraints", "POST", { scopeType: "PORTFOLIO", portfolioId, accountId: null, maximumPositionCount: optional("maximumPositionCount") === null ? null : Number(optional("maximumPositionCount")), maximumPositionWeight: optional("maximumPositionWeight"), maximumSectorWeight: optional("maximumSectorWeight"), minimumCashWeight: optional("minimumCashWeight"), maximumLeverageRatio: optional("maximumLeverageRatio"), maximumSpeculativeWeight: optional("maximumSpeculativeWeight"), effectiveAt: new Date(Math.floor(Date.now() / 1000) * 1000).toISOString(), sectorConstraints: [] }, randomUUID());
  if (!result.ok) return failed(result); revalidatePath(`/portfolio?portfolioId=${portfolioId}`); return completed("Versioned portfolio constraints created through Spring.");
}
