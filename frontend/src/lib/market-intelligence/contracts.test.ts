import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import test from "node:test";
import {
  ContractDecodeError,
  decodeProfileEnvelope,
  decodeScreeningResultPage,
  decodeScreeningRunMetadata,
  decodeSecuritySearchPage,
} from "./contracts.ts";

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
