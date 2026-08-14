import { isCanonicalUuid } from "./contracts.ts";

export function fundamentalValueDecisionPath(assemblyId: string): string {
  if (!isCanonicalUuid(assemblyId)) {
    throw new Error("The Fundamental Value assembly identifier is invalid.");
  }
  return `/api/v1/fundamental-value/decisions/${assemblyId}`;
}
