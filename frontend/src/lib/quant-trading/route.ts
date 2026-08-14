import { isCanonicalQuantDecisionId } from "./contracts.ts";

export function quantResearchDecisionPath(decisionId: string): string {
  if (!isCanonicalQuantDecisionId(decisionId)) throw new Error("Invalid Quant decision ID.");
	return `/api/v1/quant-trading/research-decisions/${decisionId}`;
}
