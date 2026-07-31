import assert from "node:assert/strict";
import test from "node:test";
import type { EligibilityRecoveryStatusResponse } from "./contracts.ts";
import {
  describeEligibilityEvidenceScope,
  describeEligibilityOperand,
} from "./eligibility-recovery-presentation.ts";

test("describes approved current-only evidence without a historical PIT claim", () => {
  const response = {
    persistedEvidenceReuseCount: 32,
  } as EligibilityRecoveryStatusResponse;

  const scope = describeEligibilityEvidenceScope(response);

  assert.equal(scope.heading, "Current-only evidence provenance");
  assert.match(scope.persistedEvidenceSummary, /^32 securities have persisted/);
  assert.match(scope.persistedEvidenceSummary, /DB-backed profiles/);
  assert.match(scope.persistedEvidenceSummary, /approved current-snapshot/);
  assert.match(scope.limitation, /provenance only/);
  assert.match(scope.limitation, /does not establish historical PIT/);
  assert.doesNotMatch(scope.limitation, /historically eligible/i);
});

test("uses a singular evidence-reuse label without changing the limitation", () => {
  const response = {
    persistedEvidenceReuseCount: 1,
  } as EligibilityRecoveryStatusResponse;

  const scope = describeEligibilityEvidenceScope(response);

  assert.match(scope.persistedEvidenceSummary, /^1 security has persisted/);
  assert.match(scope.limitation, /backtest readiness/);
});

test("keeps provider conflict and source-review actionability explicit", () => {
  const description = describeEligibilityOperand({
    factorCode: "interest_coverage",
    operandCode: "TTM:interest_expense",
    reasonCode: "PROVIDER_CONFLICT",
    providerRoute: "PERSISTED_EVIDENCE_REVIEW_REQUIRED",
    actionability: "INSUFFICIENT_GATE_IMPACT",
  });

  assert.match(description, /Provider Conflict/);
  assert.match(description, /Persisted Evidence Review Required/);
  assert.match(description, /Insufficient Gate Impact/);
});

test("keeps historical PIT unavailability visibly non-actionable", () => {
  const description = describeEligibilityOperand({
    factorCode: "historical_fcf_yield_percentile",
    operandCode: "HISTORICAL_PIT_FCF_YIELD_SERIES",
    reasonCode: "HISTORICAL_PIT_FCF_YIELD_SERIES_NOT_PERSISTED",
    providerRoute: "NONE_APPROVED",
    actionability: "NON_ACTIONABLE_WITHIN_FROZEN_V1",
  });

  assert.match(description, /Historical Pit Fcf Yield Series Not Persisted/);
  assert.match(description, /None Approved/);
  assert.match(description, /Non Actionable Within Frozen V1/);
});
