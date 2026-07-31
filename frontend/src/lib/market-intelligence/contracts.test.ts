import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import test from "node:test";
import {
  ContractDecodeError,
  decodeEligibilityRecoveryStatus,
  decodeProfileEnvelope,
  decodeScreeningResultPage,
  decodeScreeningRunMetadata,
  decodeSecuritySearchPage,
} from "./contracts.ts";

function eligibilityRecoveryFixture(): Record<string, unknown> {
  const freshness = (state: string, reasonCode: string | null = null) => ({
    datasetCode: "FUNDAMENTALS",
    state,
    evaluatedAt: "2026-07-29T03:00:00Z",
    staleAfter: state === "STALE" ? "2026-07-28T03:00:00Z" : null,
    reasonCode,
  });
  const diagnostic = (
    ordinal: number,
    symbol: string,
    state: string,
    stateFreshness: Record<string, unknown>,
  ) => ({
    securityId: `00000000-0000-4000-8000-${String(ordinal).padStart(12, "0")}`,
    symbol,
    state,
    missingOperands:
      state === "RECOVERABLE" || state === "BLOCKED"
        ? [
            {
              factorCode: "interest_coverage",
              operandCode: "interest_expense_ttm",
              reasonCode: "MISSING_REQUIRED_EVIDENCE",
              providerRoute: "YAHOO",
              actionability: "ACTIONABLE_EVIDENCE_ACQUISITION",
            },
          ]
        : [],
    freshness: [stateFreshness],
  });
  return {
    schemaVersion:
      "market-intelligence-eligibility-recovery-status-v1.0.0",
    preflightId:
      "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    generatedAt: "2026-07-29T03:00:00Z",
    dataSnapshotId: "00000000-0000-4000-8000-000000000010",
    universeVersion: "market-intelligence-closed-test-us-v1.0.0",
    snapshotAsOf: "2026-07-29T02:57:08.988871Z",
    objectiveRatingVersion: "Objective-Rating-v1",
    recoveryPolicyVersion:
      "MARKET-INTELLIGENCE-ELIGIBILITY-RECOVERY-v1.0.0",
    status: "READY_FOR_CONFIRMATION",
    currentEligibleCount: 1,
    frozenMinimumEligibleCount: 20,
    maximumEligibleAfterPlan: 20,
    dueSecurityCount: 2,
    dueSymbols: ["TTC", "STALE"],
    persistedEvidenceReuseCount: 1,
    profileCount: 66,
    resultCount: 66,
    requestPlan: [
      {
        provider: "YAHOO",
        endpointCode: "FUNDAMENTALS_TIMESERIES",
        dataset: "FUNDAMENTALS",
        symbols: ["TTC"],
        physicalRequestHardCeiling: 1,
        weightedCallHardCeiling: 0,
        runnerMaximumAttempts: 1,
      },
    ],
    blockerSummary: [
      {
        category: "MISSING_REQUIRED_EVIDENCE",
        reasonCode: "OBJECTIVE_RATING_V1_NOT_AVAILABLE_FOR_SNAPSHOT",
        actionability: "ACTIONABLE_EVIDENCE_ACQUISITION",
        affectedSecurityCount: 49,
      },
    ],
    freshness: [
      {
        ...freshness("STALE", "LATE_DATA"),
        affectedSecurityCount: 1,
      },
    ],
    securityDiagnostics: [
      diagnostic(11, "ELIG", "ALREADY_ELIGIBLE", freshness("CURRENT")),
      diagnostic(12, "TTC", "RECOVERABLE", freshness("CURRENT")),
      diagnostic(13, "STALE", "BLOCKED", freshness("STALE", "LATE_DATA")),
      diagnostic(14, "SPY", "NOT_APPLICABLE", freshness("CURRENT")),
    ],
    confirmationRequired: true,
    networkRequestsExecuted: false,
    scoresOrRanksGenerated: false,
    artifactContentHash:
      "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
  };
}

function profileFixture(): unknown {
  return JSON.parse(
    readFileSync(
      resolve(
        process.cwd(),
        "../contracts/market-intelligence-v1/profile-envelope.example.json",
      ),
      "utf8",
    ),
  );
}

function jsonFixture(name: string): unknown {
  return JSON.parse(
    readFileSync(
      resolve(
        process.cwd(),
        `../contracts/market-intelligence-v1/${name}`,
      ),
      "utf8",
    ),
  );
}

test("decodes the canonical profile envelope without aliases", () => {
  const result = decodeProfileEnvelope(profileFixture());

  assert.equal(result.profile.security.symbol, "NBN");
  assert.equal(result.currentMarketData.state, "MISSING");
  assert.equal(result.currentMarketData.price, null);
  assert.equal(result.freshness[0]?.state, "MISSING");
  assert.equal(result.profile.aiNarrative.mayAffectDeterministicFields, false);
});

test("preserves the real partial and not-eligible profile states", () => {
  const result = decodeProfileEnvelope(profileFixture());

  assert.equal(result.profile.profileState, "PARTIAL");
  assert.equal(result.profile.rankingState, "NOT_ELIGIBLE");
  assert.equal(result.profile.objectiveQualityScore, null);
  assert.equal(result.profile.objectiveValuationScore, null);
  assert.equal(result.profile.horizons.length, 4);
  assert.ok(
    result.profile.horizons.every(
      ({ deterministicView }) =>
        deterministicView.state === "INSUFFICIENT_DATA" &&
        deterministicView.score === null,
    ),
  );
  assert.ok(result.profile.rankingExclusions.includes("CLASSIFICATION_MISSING"));
  assert.equal(result.currentMarketData.price, null);
});

test("rejects a missing price that is coerced to zero", () => {
  const payload = profileFixture() as Record<string, unknown>;
  const market = payload.currentMarketData as Record<string, unknown>;
  market.price = 0;

  assert.throws(
    () => decodeProfileEnvelope(payload),
    (error) =>
      error instanceof ContractDecodeError &&
      error.message.includes("non-VALID market data must remain null"),
  );
});

test("rejects AI narrative influence on deterministic fields", () => {
  const payload = profileFixture() as Record<string, unknown>;
  const profile = payload.profile as Record<string, unknown>;
  const narrative = profile.aiNarrative as Record<string, unknown>;
  narrative.mayAffectDeterministicFields = true;

  assert.throws(
    () => decodeProfileEnvelope(payload),
    (error) =>
      error instanceof ContractDecodeError &&
      error.message.includes(
        "AI narrative cannot affect deterministic fields",
      ),
  );
});

test("decodes canonical security search summaries with explicit missing state", () => {
  const envelope = decodeProfileEnvelope(profileFixture());
  const payload = {
    dataSnapshotId: "11111111-1111-4111-8111-111111111111",
    universeVersion: "market-intelligence-closed-test-us-v1.0.0",
    items: [
      {
        securityId: envelope.securityId,
        symbol: envelope.profile.security.symbol,
        issuerName: envelope.profile.security.issuerName,
        exchangeMic: envelope.profile.security.exchangeMic,
        membershipStatus: "ACTIVE",
        companyType: "SPECIALIZED",
        sector: null,
        industry: null,
        latestProfileId: envelope.profileId,
        currentMarketData: envelope.currentMarketData,
        freshness: envelope.freshness,
        modelVersions: envelope.modelVersions,
      },
    ],
    nextCursor: "opaque-cursor",
  };

  const result = decodeSecuritySearchPage(payload);

  assert.equal(result.items[0]?.latestProfileId, envelope.profileId);
  assert.equal(
    result.items[0]?.currentMarketData.reason,
    "PRICE_OBSERVATION_MISSING",
  );
  assert.equal(result.nextCursor, "opaque-cursor");
});

test("decodes sealed run metadata and result page contracts", () => {
  const run = decodeScreeningRunMetadata(
    jsonFixture("screening-run-metadata.example.json"),
  );
  const envelope = profileFixture();
  const page = decodeScreeningResultPage({
    run: jsonFixture("screening-run-metadata.example.json"),
    items: [envelope],
    nextCursor: null,
  });

  assert.equal(run.state, "SEALED");
  assert.equal(run.rankBy, "BUYING_OPPORTUNITY");
  assert.equal(page.run.runId, run.runId);
  assert.equal(page.items.length, 1);
  assert.equal(page.nextCursor, null);
});

test("accepts the canonical sealed no-eligible result page without fabricating items", () => {
  const metadata = jsonFixture(
    "screening-run-metadata.example.json",
  ) as Record<string, unknown>;
  const page = decodeScreeningResultPage({
    run: metadata,
    items: [],
    nextCursor: null,
  });

  assert.equal(page.run.gateStatus, "NO_ELIGIBLE_RESULTS");
  assert.equal(page.run.eligibleCount, 0);
  assert.equal(page.run.excludedCount, 66);
  assert.deepEqual(page.items, []);
  assert.equal(page.nextCursor, null);
});

test("decodes eligibility recovery without collapsing explicit security states", () => {
  const result = decodeEligibilityRecoveryStatus(
    eligibilityRecoveryFixture(),
  );

  assert.equal(result.status, "READY_FOR_CONFIRMATION");
  assert.equal(result.currentEligibleCount, 1);
  assert.equal(result.frozenMinimumEligibleCount, 20);
  assert.equal(result.profileCount, 66);
  assert.equal(result.resultCount, 66);
  assert.deepEqual(
    result.securityDiagnostics.map((item) => item.state),
    ["ALREADY_ELIGIBLE", "RECOVERABLE", "BLOCKED", "NOT_APPLICABLE"],
  );
  assert.equal(result.securityDiagnostics[1]?.missingOperands.length, 1);
  assert.equal(
    result.securityDiagnostics[2]?.freshness[0]?.state,
    "STALE",
  );
  assert.equal(result.freshness[0]?.reasonCode, "LATE_DATA");
  assert.equal(result.networkRequestsExecuted, false);
  assert.equal(result.scoresOrRanksGenerated, false);
});

test("accepts every frozen blocked or no-action eligibility status", () => {
  for (const status of [
    "NO_ACTIONABLE_REQUESTS",
    "BLOCKED_COHORT_UNREACHABLE",
    "BLOCKED_EVIDENCE_SEMANTICS",
    "BLOCKED_BUDGET",
    "BLOCKED_SNAPSHOT",
  ]) {
    const payload = eligibilityRecoveryFixture();
    payload.status = status;
    payload.confirmationRequired = false;
    payload.requestPlan = [];

    assert.equal(decodeEligibilityRecoveryStatus(payload).status, status);
  }
});

test("rejects eligibility recovery that claims requests or scores were generated", () => {
  for (const field of [
    "networkRequestsExecuted",
    "scoresOrRanksGenerated",
  ]) {
    const payload = eligibilityRecoveryFixture();
    payload[field] = true;

    assert.throws(
      () => decodeEligibilityRecoveryStatus(payload),
      (error) =>
        error instanceof ContractDecodeError &&
        error.message.includes(
          "must not execute requests or generate scores",
        ),
    );
  }
});
