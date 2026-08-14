import { isCurrentAssessmentId } from "./current-contracts.ts";

export function currentFundamentalValueAssessmentPath(assessmentId: string): string {
  if (!isCurrentAssessmentId(assessmentId)) throw new Error("The current assessment identifier is invalid.");
  return `/api/v1/fundamental-value/current-assessments/${assessmentId}`;
}

export function latestCurrentFundamentalValueAssessmentPath(symbol: string): string {
  if (!/^[A-Z][A-Z0-9.\-]{0,31}$/.test(symbol)) {
    throw new Error("The current assessment symbol is invalid.");
  }
  return `/api/v1/fundamental-value/current-assessments/latest/${symbol}`;
}
