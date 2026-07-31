import { humanize } from "../format.ts";
import type {
  EligibilityMissingOperand,
  EligibilityRecoveryStatusResponse,
} from "./contracts";

export type EligibilityEvidenceScope = {
  heading: string;
  persistedEvidenceSummary: string;
  limitation: string;
};

export function describeEligibilityEvidenceScope(
  response: EligibilityRecoveryStatusResponse,
): EligibilityEvidenceScope {
  const securityLabel =
    response.persistedEvidenceReuseCount === 1 ? "security has" : "securities have";

  return {
    heading: "Current-only evidence provenance",
    persistedEvidenceSummary:
      `${response.persistedEvidenceReuseCount} ${securityLabel} persisted ` +
      "evidence reusable within this sealed current-snapshot preflight. " +
      "Eligible names, when present, come from DB-backed profiles assembled " +
      "under the approved current-snapshot evidence path.",
    limitation:
      "The external Objective Algorithm Gate cohort is provenance only. It " +
      "does not establish historical PIT availability, backtest readiness, " +
      "or future performance.",
  };
}

export function describeEligibilityOperand(
  operand: EligibilityMissingOperand,
): string {
  return (
    `${humanize(operand.factorCode)} / ${humanize(operand.operandCode)}: ` +
    `${humanize(operand.reasonCode)} via ${humanize(operand.providerRoute)} - ` +
    humanize(operand.actionability)
  );
}
