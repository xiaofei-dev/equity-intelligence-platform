"use server";

import { revalidatePath } from "next/cache";
import { submitPortfolioHumanDecision } from "@/lib/portfolio-decision/backend";
import { humanConclusions, type HumanConclusion } from "@/lib/portfolio-decision/contracts";

export async function recordHumanDecision(formData: FormData): Promise<void> {
  const portfolioId = String(formData.get("portfolioId") ?? ""); const scenarioId = String(formData.get("scenarioId") ?? ""); const conclusion = String(formData.get("conclusion") ?? "") as HumanConclusion; const rationale = String(formData.get("rationale") ?? ""); const idempotencyKey = String(formData.get("idempotencyKey") ?? "");
  if (!humanConclusions.includes(conclusion)) return;
  const result = await submitPortfolioHumanDecision({ portfolioId, scenarioId, conclusion, rationale, idempotencyKey });
  if (result.ok) revalidatePath(`/portfolio?portfolioId=${portfolioId}`);
}
