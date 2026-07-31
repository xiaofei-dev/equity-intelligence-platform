import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import test from "node:test";
import {
  decodeDualSystemDecisionContext,
  DualSystemContractError,
} from "./contracts.ts";

function fixture(): Record<string, unknown> {
  return JSON.parse(
    readFileSync(
      resolve(
        process.cwd(),
        "../contracts/dual-system-architecture-v1/decision-context.example.json",
      ),
      "utf8",
    ),
  );
}

function changed(
  objectName: string,
  fieldName: string,
  value: unknown,
): Record<string, unknown> {
  const payload = structuredClone(fixture());
  (payload[objectName] as Record<string, unknown>)[fieldName] = value;
  return payload;
}

test("accepts the canonical engine and sleeve-separated fixture", () => {
  const result = decodeDualSystemDecisionContext(fixture());
  assert.equal(
    (result.fundamentalValueOutput as Record<string, unknown>).sleeve,
    "LONG_TERM_CORE",
  );
  assert.equal(
    (result.quantTradePlanOutput as Record<string, unknown>).sleeve,
    "QUANT_TRADING",
  );
});

test("fails closed for unknown state and contract version", () => {
  assert.throws(
    () => decodeDualSystemDecisionContext(changed("evidence", "state", "UNKNOWN")),
    DualSystemContractError,
  );
  const payload = fixture();
  payload.contractVersion = "dual-system-architecture-v2";
  assert.throws(() => decodeDualSystemDecisionContext(payload), /Unsupported/);
});

test("prohibits score averaging, AI control, and automatic execution", () => {
  assert.throws(
    () =>
      decodeDualSystemDecisionContext(
        changed("portfolioRiskView", "scoreAggregationPolicy", "AVERAGE"),
      ),
    /averaging/,
  );
  assert.throws(
    () =>
      decodeDualSystemDecisionContext(
        changed("aiNarrative", "maySetWeightsOrTrades", true),
      ),
    /narrative-only/,
  );
  assert.throws(
    () =>
      decodeDualSystemDecisionContext(
        changed("humanControl", "automaticBrokerageExecutionAllowed", true),
      ),
    /human control/,
  );
});

test("preserves evidence claim ceilings and field-specific tolerances", () => {
  const approximate = changed(
    "evidence",
    "strictnessClass",
    "APPROXIMATE_HISTORICAL_RESEARCH",
  );
  (approximate.evidence as Record<string, unknown>).claimClass = "STRICT_PIT";
  assert.throws(
    () => decodeDualSystemDecisionContext(approximate),
    /cannot claim PIT/,
  );

  const unaligned = fixture();
  const evidence = unaligned.evidence as Record<string, unknown>;
  (evidence.fieldTolerancePolicy as Record<string, unknown>).alignmentSatisfied =
    false;
  assert.throws(
    () => decodeDualSystemDecisionContext(unaligned),
    /aligned/,
  );
});

test("rejects null or unknown required engine enums", () => {
  for (const [objectName, fieldName] of [
    ["fundamentalValueOutput", "state"],
    ["quantTradePlanOutput", "state"],
    ["fundamentalValueOutput", "applicability"],
  ]) {
    assert.throws(
      () =>
        decodeDualSystemDecisionContext(changed(objectName, fieldName, null)),
      DualSystemContractError,
    );
    assert.throws(
      () =>
        decodeDualSystemDecisionContext(
          changed(objectName, fieldName, "UNKNOWN"),
        ),
      DualSystemContractError,
    );
  }
});

test("requires completed session identity and sealed cutoffs", () => {
  assert.throws(
    () =>
      decodeDualSystemDecisionContext(
        changed("completedSession", "status", "SCHEDULED"),
      ),
    /COMPLETED/,
  );
  assert.throws(
    () =>
      decodeDualSystemDecisionContext(
        changed("completedSession", "calendarVersion", null),
      ),
    /nonblank/,
  );
  assert.throws(
    () =>
      decodeDualSystemDecisionContext(
        changed("decisionTiming", "decisionCutoff", "2026-07-29T20:04:59Z"),
      ),
    /decision cutoff/,
  );
  assert.throws(
    () =>
      decodeDualSystemDecisionContext(
        changed(
          "decisionTiming",
          "sealedIngestionCutoff",
          "2026-07-29T20:06:59Z",
        ),
      ),
    /ingestion cutoff/,
  );
});

test("requires fundamental and quant output structures", () => {
  const fundamental = fixture();
  (
    (fundamental.fundamentalValueOutput as Record<string, unknown>)
      .fairValue as Record<string, unknown>
  ).rangeHigh = null;
  assert.throws(
    () => decodeDualSystemDecisionContext(fundamental),
    DualSystemContractError,
  );
  for (const [field, value] of [
    ["market", null],
    ["cadence", "INTRADAY"],
    ["direction", "SHORT"],
    ["leverageAllowed", null],
    ["stop", null],
    ["targets", []],
    ["expiresAfterCompletedSessions", null],
  ]) {
    assert.throws(
      () =>
        decodeDualSystemDecisionContext(
          changed("quantTradePlanOutput", field, value),
        ),
      DualSystemContractError,
    );
  }
  const costs = fixture();
  (
    (costs.quantTradePlanOutput as Record<string, unknown>)
      .costAssumptions as Record<string, unknown>
  ).version = "";
  assert.throws(() => decodeDualSystemDecisionContext(costs), /nonblank/);

  const longBenchmarks = fixture();
  (
    longBenchmarks.fundamentalValueOutput as Record<string, unknown>
  ).benchmarkCodes = ["DATED_SECTOR_BENCHMARK", "SPY"];
  assert.throws(
    () => decodeDualSystemDecisionContext(longBenchmarks),
    /approved ordered set/,
  );
  const quantBenchmarks = fixture();
  (
    quantBenchmarks.quantTradePlanOutput as Record<string, unknown>
  ).benchmarkCodes = ["SPY", "CASH", "DATED_SECTOR_BENCHMARK"];
  assert.throws(
    () => decodeDualSystemDecisionContext(quantBenchmarks),
    /approved ordered set/,
  );
});

test("requires portfolio sleeve and all human-control invariants", () => {
  for (const [objectName, fieldName, value] of [
    ["portfolioRiskView", "sameSecurityAcrossSleevesAllowed", null],
    ["portfolioRiskView", "cashTransferAuthority", null],
    ["humanControl", "decisionRequiredForCashTransfer", null],
    ["humanControl", "decisionRecordsAreImmutable", false],
    ["humanControl", "correctionsUseSupersession", false],
  ]) {
    assert.throws(
      () =>
        decodeDualSystemDecisionContext(
          changed(objectName as string, fieldName as string, value),
        ),
      DualSystemContractError,
    );
  }
  const duplicate = fixture();
  const entries = (
    duplicate.portfolioRiskView as Record<string, unknown>
  ).sleeves as Array<Record<string, unknown>>;
  entries[1]!.sleeve = "LONG_TERM_CORE";
  assert.throws(() => decodeDualSystemDecisionContext(duplicate), /Distinct/);
});

test("rejects blank tolerances, missing versions, scores on nonvalid states, and claim upgrades", () => {
  const tolerance = fixture();
  (
    (tolerance.evidence as Record<string, unknown>)
      .fieldTolerancePolicy as Record<string, unknown>
  ).fieldCode = " ";
  assert.throws(() => decodeDualSystemDecisionContext(tolerance), /versioned/);
  assert.throws(
    () =>
      decodeDualSystemDecisionContext(
        changed("versionSet", "costPolicyVersion", null),
      ),
    /nonblank/,
  );
  const nonvalid = changed("fundamentalValueOutput", "state", "MISSING");
  (nonvalid.fundamentalValueOutput as Record<string, unknown>).reasonCode =
    "REQUIRED_INPUT_MISSING";
  assert.throws(() => decodeDualSystemDecisionContext(nonvalid), /cannot carry/);
  assert.throws(
    () =>
      decodeDualSystemDecisionContext(
        changed("validationGovernance", "mayUpgradeModelEvidenceLabel", true),
      ),
    /cannot upgrade/,
  );
});

test("rejects missing and null provider lineage declarations", () => {
  for (const field of [
    "providerCode",
    "providerSchemaVersion",
    "adapterVersion",
    "normalizationVersion",
    "sourceRecordId",
    "sourceContentHash",
    "normalizedRecordHash",
    "effectiveAt",
    "availableAt",
    "ingestedAt",
    "freshnessPolicyVersion",
    "sourceRevision",
    "conflict",
  ]) {
    const missing = fixture();
    delete (missing.evidence as Record<string, unknown>)[field];
    assert.throws(
      () => decodeDualSystemDecisionContext(missing),
      DualSystemContractError,
    );
    assert.throws(
      () =>
        decodeDualSystemDecisionContext(changed("evidence", field, null)),
      DualSystemContractError,
    );
  }
});

test("validates conflict shape and optional lineage timestamp semantics", () => {
  for (const field of ["status", "criticality"]) {
    const candidate = fixture();
    (
      (candidate.evidence as Record<string, unknown>).conflict as Record<
        string,
        unknown
      >
    )[field] = null;
    assert.throws(
      () => decodeDualSystemDecisionContext(candidate),
      DualSystemContractError,
    );
  }
  for (const field of ["retrievedAt", "staleAfter"]) {
    decodeDualSystemDecisionContext(changed("evidence", field, null));
    assert.throws(
      () =>
        decodeDualSystemDecisionContext(
          changed("evidence", field, "not-a-timestamp"),
        ),
      /RFC 3339 instant/,
    );
  }
});

test("requires tolerance policy only for domain-tolerant numeric evidence", () => {
  const domain = fixture();
  delete (domain.evidence as Record<string, unknown>).fieldTolerancePolicy;
  assert.throws(() => decodeDualSystemDecisionContext(domain), /object/);

  for (const [strictness, claim] of [
    ["STRICT_IDENTITY_AND_CHRONOLOGY", "CURRENT_ONLY"],
    ["APPROXIMATE_HISTORICAL_RESEARCH", "APPROXIMATE_HISTORICAL"],
  ]) {
    const candidate = fixture();
    const evidence = candidate.evidence as Record<string, unknown>;
    evidence.strictnessClass = strictness;
    evidence.claimClass = claim;
    delete evidence.fieldTolerancePolicy;
    decodeDualSystemDecisionContext(candidate);
  }
});

test("rejects missing and null durable identity and output references", () => {
  const fields: Array<[string, string]> = [
    ...[
      "securityId",
      "companyId",
      "instrumentId",
      "shareClassId",
      "listingId",
      "tickerAssignmentId",
      "ticker",
      "mic",
      "currency",
    ].map((field): [string, string] => ["security", field]),
    ...["fundamentalValueOutput", "quantTradePlanOutput"].flatMap((output) =>
      [
        "outputId",
        "decisionContractVersion",
        "modelId",
        "modelVersion",
        "strategyVersion",
        "evidenceHash",
      ].map((field): [string, string] => [output, field]),
    ),
    ["fundamentalValueOutput", "referencePrice"],
    ["quantTradePlanOutput", "setup"],
    ["portfolioRiskView", "contractVersion"],
  ];
  for (const [objectName, field] of fields) {
    const missing = fixture();
    delete (missing[objectName] as Record<string, unknown>)[field];
    assert.throws(
      () => decodeDualSystemDecisionContext(missing),
      DualSystemContractError,
    );
    assert.throws(
      () =>
        decodeDualSystemDecisionContext(changed(objectName, field, null)),
      DualSystemContractError,
    );
  }
});

test("rejects cross-binding and incomplete compatibility or governance values", () => {
  for (const index of [0, 1]) {
    const candidate = fixture();
    const entries = (
      candidate.portfolioRiskView as Record<string, unknown>
    ).sleeves as Array<Record<string, unknown>>;
    entries[index]!.engineOutputId =
      "00000000-0000-4000-8000-000000000000";
    assert.throws(() => decodeDualSystemDecisionContext(candidate), /binding/);
  }
  for (const field of [
    "legacyBuyingOpportunityMeaning",
    "successorMetric",
    "legacyPublicMarketDataApiStatus",
  ]) {
    assert.throws(
      () =>
        decodeDualSystemDecisionContext(
          changed("compatibility", field, "UNKNOWN"),
        ),
      /Compatibility/,
    );
  }
  assert.throws(
    () =>
      decodeDualSystemDecisionContext(
        changed("validationGovernance", "modelEvidenceLabel", "UNKNOWN"),
      ),
    /unsupported/,
  );
});

test("rejects every expressible canonical chronology violation", () => {
  for (const [objectName, field, value] of [
    ["completedSession", "scheduledOpen", "2026-07-29T20:00:00Z"],
    ["completedSession", "scheduledClose", "2026-07-29T20:00:02Z"],
    ["completedSession", "completedAt", "2026-07-29T20:05:01Z"],
    ["decisionTiming", "decisionCutoff", "2026-07-29T20:07:01Z"],
    ["evidence", "effectiveAt", "2026-07-29T20:05:01Z"],
    ["evidence", "availableAt", "2026-07-29T20:07:01Z"],
    ["evidence", "retrievedAt", "2026-07-29T20:04:59Z"],
    ["evidence", "retrievedAt", "2026-07-29T20:07:01Z"],
  ]) {
    assert.throws(
      () =>
        decodeDualSystemDecisionContext(
          changed(objectName, field, value),
        ),
      DualSystemContractError,
    );
  }
});

test("rejects special, exponent, and wrong-type canonical decimal values", () => {
  for (const badValue of [
    "NaN",
    "Infinity",
    "-Infinity",
    "1e3",
    "0x10",
    12.5,
    true,
  ]) {
    const mutations: Array<[string, string | null, string]> = [
      ["fundamentalValueOutput", "fairValue", "central"],
      ["fundamentalValueOutput", "fairValue", "rangeLow"],
      ["fundamentalValueOutput", "fairValue", "rangeHigh"],
      ["fundamentalValueOutput", null, "referencePrice"],
      ["fundamentalValueOutput", null, "marginOfSafety"],
      ["fundamentalValueOutput", null, "maximumAllocationCap"],
      ["quantTradePlanOutput", null, "entryRangeLow"],
      ["quantTradePlanOutput", null, "entryRangeHigh"],
      ["quantTradePlanOutput", null, "stop"],
      ["quantTradePlanOutput", null, "maximumPositionRisk"],
      [
        "quantTradePlanOutput",
        "liquidityAssumptions",
        "averageDailyDollarVolume",
      ],
      [
        "quantTradePlanOutput",
        "liquidityAssumptions",
        "maximumParticipationRate",
      ],
      ["quantTradePlanOutput", "costAssumptions", "transactionCostBps"],
      ["quantTradePlanOutput", "costAssumptions", "slippageBps"],
    ];
    for (const [rootName, nestedName, field] of mutations) {
      const candidate = fixture();
      const root = candidate[rootName] as Record<string, unknown>;
      const target =
        nestedName === null
          ? root
          : (root[nestedName] as Record<string, unknown>);
      target[field] = badValue;
      assert.throws(
        () => decodeDualSystemDecisionContext(candidate),
        DualSystemContractError,
      );
    }
    const targetCandidate = fixture();
    (
      (targetCandidate.quantTradePlanOutput as Record<string, unknown>)
        .targets as unknown[]
    )[0] = badValue;
    assert.throws(
      () => decodeDualSystemDecisionContext(targetCandidate),
      DualSystemContractError,
    );
  }
});

test("rejects impossible ISO dates and non-RFC3339 timestamp forms", () => {
  for (const badDate of ["2026-99-99", "2026-02-30", "2026-04-31"]) {
    assert.throws(
      () =>
        decodeDualSystemDecisionContext(
          changed("completedSession", "sessionDate", badDate),
        ),
      /real ISO date/,
    );
  }
  for (const badTimestamp of [
    "",
    "2026-07-29",
    "July 29 2026",
    "2026-07-29T20:00:00",
    123,
    true,
  ]) {
    for (const [objectName, field] of [
      ["decisionTiming", "decisionCutoff"],
      ["completedSession", "scheduledOpen"],
      ["evidence", "availableAt"],
      ["evidence", "retrievedAt"],
      ["evidence", "staleAfter"],
    ]) {
      assert.throws(
        () =>
          decodeDualSystemDecisionContext(
            changed(objectName, field, badTimestamp),
          ),
        DualSystemContractError,
      );
    }
  }
});

test("rejects wrong-type structured evidence fields and boolean coercion", () => {
  for (const field of ["conflict", "fieldTolerancePolicy"]) {
    for (const badValue of ["text", 1, true, []]) {
      assert.throws(
        () =>
          decodeDualSystemDecisionContext(
            changed("evidence", field, badValue),
          ),
        DualSystemContractError,
      );
    }
  }
  for (const badValue of ["true", 1, null]) {
    const tolerance = fixture();
    (
      (tolerance.evidence as Record<string, unknown>)
        .fieldTolerancePolicy as Record<string, unknown>
    ).alignmentSatisfied = badValue;
    assert.throws(
      () => decodeDualSystemDecisionContext(tolerance),
      DualSystemContractError,
    );
    assert.throws(
      () =>
        decodeDualSystemDecisionContext(
          changed("completedSession", "earlyClose", badValue),
        ),
      DualSystemContractError,
    );
  }
});

test("rejects non-string canonical identity and reference fields", () => {
  for (const [objectName, field] of [
    ["security", "securityId"],
    ["completedSession", "calendarId"],
    ["fundamentalValueOutput", "modelVersion"],
    ["versionSet", "calendarVersion"],
  ]) {
    assert.throws(
      () =>
        decodeDualSystemDecisionContext(changed(objectName, field, 123)),
      DualSystemContractError,
    );
  }
  const binding = fixture();
  const sleeves = (
    binding.portfolioRiskView as Record<string, unknown>
  ).sleeves as Array<Record<string, unknown>>;
  sleeves[0]!.engineOutputId = true;
  assert.throws(
    () => decodeDualSystemDecisionContext(binding),
    DualSystemContractError,
  );
  for (const outputName of [
    "fundamentalValueOutput",
    "quantTradePlanOutput",
  ]) {
    const candidate = fixture();
    (
      (candidate[outputName] as Record<string, unknown>)
        .benchmarkCodes as unknown[]
    )[0] = 123;
    assert.throws(
      () => decodeDualSystemDecisionContext(candidate),
      DualSystemContractError,
    );
  }
});

test("rejects an oversized distinct reversed fair-value range exactly", () => {
  const candidate = fixture();
  const fairValue = (
    candidate.fundamentalValueOutput as Record<string, unknown>
  ).fairValue as Record<string, unknown>;
  fairValue.rangeLow = "7".repeat(401);
  fairValue.central = "8".repeat(401);
  fairValue.rangeHigh = "9".repeat(401);
  decodeDualSystemDecisionContext(candidate);
  fairValue.rangeLow = "9".repeat(401);
  fairValue.central = "8".repeat(401);
  fairValue.rangeHigh = "7".repeat(401);
  assert.throws(
    () => decodeDualSystemDecisionContext(candidate),
    /range must contain/,
  );
});
