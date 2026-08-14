import type { FundamentalValueDecision, ValueRange } from "./contracts";

export type WorkspaceMode = "USABLE" | "NON_USABLE" | "SPECIALIZED" | "NOT_APPLICABLE";

export type FundamentalValuePresentation = {
  mode: WorkspaceMode;
  title: string;
  summary: string;
  reasons: string[];
  decision: FundamentalValueDecision;
};

export function presentFundamentalValueDecision(
  decision: FundamentalValueDecision,
): FundamentalValuePresentation {
  if (decision.state === "VALID" && decision.deterministicAssessment) {
    return { mode: "USABLE", title: "Deterministic assessment available", summary: "The sealed evidence set authorized the generic mature-company model. This is decision support, not a recommendation or final portfolio weight.", reasons: [], decision };
  }
  if (decision.applicability === "SPECIALIZED_MODEL_REQUIRED") {
    return { mode: "SPECIALIZED", title: "Specialized model required", summary: "This company type is outside the mature nonfinancial generic model. No generic valuation was produced.", reasons: decision.reasonCodes, decision };
  }
  if (decision.applicability === "NOT_APPLICABLE") {
    return { mode: "NOT_APPLICABLE", title: "Fundamental Value is not applicable", summary: "The sealed applicability route prohibits a generic company assessment.", reasons: decision.reasonCodes, decision };
  }
  return { mode: "NON_USABLE", title: "Assessment is not usable", summary: "Required sealed evidence is missing, stale, invalid, excluded, or otherwise insufficient. Missing evidence is never treated as zero.", reasons: decision.reasonCodes, decision };
}

export function rangeText(range: ValueRange, options?: { percent?: boolean; currency?: string }): string {
  if (range.state !== "VALID" || range.low === null || range.central === null || range.high === null) return range.state;
  const render = (value: string) => {
    if (options?.percent) return formatPercentDecimal(value, 1);
    return options?.currency ? `${options.currency} ${value}` : value;
  };
  return `${render(range.low)} – ${render(range.central)} – ${render(range.high)}`;
}

export function formatPercentDecimal(value: string, fractionalDigits: number): string {
  if (!Number.isInteger(fractionalDigits) || fractionalDigits < 0 || fractionalDigits > 6) {
    throw new Error("Percent precision is outside the UI policy.");
  }
  const match = /^(-?)(\d+)(?:\.(\d+))?$/.exec(value);
  if (!match || /^-0(?:\.0+)?$/.test(value)) throw new Error("Percent input is not canonical decimal text.");
  const [, sign, integer, fraction = ""] = match;
  const digits = `${integer}${fraction}`.replace(/^0+(?=\d)/, "");
  const shift = 2 + fractionalDigits - fraction.length;
  let magnitude: bigint;
  if (shift >= 0) {
    magnitude = BigInt(`${digits}${"0".repeat(shift)}`);
  } else {
    const cut = digits.length + shift;
    const kept = cut > 0 ? digits.slice(0, cut) : "0";
    const discarded = `${cut < 0 ? "0".repeat(-cut) : ""}${digits.slice(Math.max(cut, 0))}`;
    magnitude = BigInt(kept);
    if ((discarded[0] ?? "0") >= "5") magnitude += BigInt(1);
  }
  const raw = magnitude.toString().padStart(fractionalDigits + 1, "0");
  const rendered = fractionalDigits === 0
    ? raw
    : `${raw.slice(0, -fractionalDigits)}.${raw.slice(-fractionalDigits)}`;
  return `${sign && magnitude !== BigInt(0) ? "-" : ""}${rendered}%`;
}
