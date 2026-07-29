export type DecimalValue = string | number;

export type FactState = "VALID" | "MISSING" | "INVALID" | "NOT_APPLICABLE";
export type ProfileState = "COMPLETE" | "PARTIAL" | "INELIGIBLE";
export type RankingState = "ELIGIBLE" | "NOT_ELIGIBLE";
export type Horizon =
  | "ONE_WEEK"
  | "ONE_MONTH"
  | "THREE_MONTHS"
  | "TWELVE_MONTHS_PLUS";
export type RankMetric =
  | "OBJECTIVE_QUALITY"
  | "OBJECTIVE_VALUATION"
  | "TACTICAL_ONE_WEEK"
  | "TACTICAL_ONE_MONTH"
  | "TACTICAL_THREE_MONTHS"
  | "LONG_HORIZON"
  | "BUYING_OPPORTUNITY";
export type SortDirection = "ASCENDING" | "DESCENDING";

export type EvidenceLineage = {
  providerCode: string;
  providerSchemaVersion: string;
  parserVersion: string;
  sourceReference: string;
  contentHash: string;
  availableAt: string;
  retrievedAt: string;
  effectiveAt: string | null;
};

export type ProfileFact = {
  name: string;
  metricVersion: string;
  state: FactState;
  value: string | number | boolean | null;
  reason: string | null;
  lineage: EvidenceLineage[];
};

export type DeterministicView = {
  modelId: string;
  modelVersion: string;
  state: "ASSESSED" | "INSUFFICIENT_DATA" | "NOT_APPLICABLE";
  asOf: string;
  effectiveAt: string;
  expiresAt: string | null;
  score: DecimalValue | null;
  label: string;
  inputHash: string;
  evidenceHash: string;
  missingInputs: string[];
  explanation: string[];
};

export type SecurityProfile = {
  contractVersion: string;
  security: {
    securityId: string;
    symbol: string;
    issuerName: string;
    exchangeMic: string;
    currency: string;
    instrumentType: string;
    cik: string | null;
    durableProviderId: string | null;
  };
  classification: {
    taxonomyCode: string;
    taxonomyVersion: string;
    sectorCode: string;
    sectorName: string;
    industryCode: string;
    industryName: string;
    companyType: string;
    effectiveAt: string;
    lineage: EvidenceLineage[];
  } | null;
  comparableCohorts: Array<{
    cohortId: string;
    taxonomyVersion: string;
    sectorCode: string;
    industryCode: string | null;
    companyType: string;
    sizeBand: string | null;
    eligibleMemberCount: number;
    minimumMemberCount: number;
  }>;
  facts: ProfileFact[];
  objectiveQualityScore: DecimalValue | null;
  objectiveValuationScore: DecimalValue | null;
  objectiveRatingStatus: string;
  objectiveRatingVersion: string;
  horizons: Array<{
    horizon: Horizon;
    deterministicView: DeterministicView;
  }>;
  valuation: {
    state: FactState;
    asOf: string;
    objectiveValuationScore: DecimalValue | null;
    longHorizonValuationScore: DecimalValue | null;
    ownHistoryPercentile: DecimalValue | null;
    evidence: ProfileFact[];
    limitations: string[];
  };
  profileState: ProfileState;
  rankingState: RankingState;
  rankingExclusions: string[];
  explainability: string[];
  aiNarrative: {
    status: string;
    narrative: string | null;
    sourceReferences: string[];
    generatedAt: string | null;
    promptVersion: string | null;
    modelVersion: string | null;
    confidence: string | null;
    mayAffectDeterministicFields: false;
  };
};

export type CurrentMarketData = {
  state: FactState;
  price: DecimalValue | null;
  currency: string;
  tradingDate: string | null;
  providerCode: string | null;
  availableAt: string | null;
  ingestedAt: string | null;
  adjustmentMode: string | null;
  reason: string | null;
};

export type DatasetFreshness = {
  datasetCode: string;
  state: string;
  providerCode: string | null;
  effectiveAt: string | null;
  availableAt: string | null;
  ingestedAt: string | null;
  evaluatedAt: string;
  staleAfter: string | null;
  reasonCode: string | null;
};

export type ProfileEnvelope = {
  profileId: string;
  securityId: string;
  profile: SecurityProfile;
  currentMarketData: CurrentMarketData;
  freshness: DatasetFreshness[];
  modelVersions: Record<string, string>;
};

export type ScreeningRunMetadata = {
  runId: string;
  state: string;
  dataSnapshotId: string;
  universeVersion: string;
  asOf: string;
  rankBy: RankMetric;
  direction: SortDirection;
  eligibleCount: number;
  excludedCount: number;
  gateStatus: string;
  profileSetHash: string;
  resultHash: string;
  sealedAt: string;
};

export type ScreeningResultPage = {
  run: ScreeningRunMetadata;
  items: ProfileEnvelope[];
  nextCursor: string | null;
};

export type SecuritySearchItem = {
  securityId: string;
  symbol: string;
  issuerName: string;
  exchangeMic: string;
  membershipStatus: string;
  companyType: string;
  sector: string | null;
  industry: string | null;
  latestProfileId: string | null;
  currentMarketData: CurrentMarketData;
  freshness: DatasetFreshness[];
  modelVersions: Record<string, string>;
};

export type SecuritySearchPage = {
  dataSnapshotId: string;
  universeVersion: string;
  items: SecuritySearchItem[];
  nextCursor: string | null;
};

export type MarketIntelligenceFacets = {
  dataSnapshotId: string;
  universeVersion: string;
  sectors: string[];
  industries: string[];
  companyTypes: string[];
  membershipStatuses: string[];
};

export class ContractDecodeError extends Error {
  constructor(path: string, expectation: string) {
    super(`Invalid market-intelligence response at ${path}: ${expectation}.`);
    this.name = "ContractDecodeError";
  }
}

function record(value: unknown, path: string): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new ContractDecodeError(path, "expected an object");
  }
  return value as Record<string, unknown>;
}

function string(value: unknown, path: string): string {
  if (typeof value !== "string" || value.length === 0) {
    throw new ContractDecodeError(path, "expected a non-empty string");
  }
  return value;
}

function nullableString(value: unknown, path: string): string | null {
  return value === null ? null : string(value, path);
}

function boolean(value: unknown, path: string): boolean {
  if (typeof value !== "boolean") {
    throw new ContractDecodeError(path, "expected a boolean");
  }
  return value;
}

function integer(value: unknown, path: string): number {
  if (!Number.isInteger(value) || (value as number) < 0) {
    throw new ContractDecodeError(path, "expected a non-negative integer");
  }
  return value as number;
}

function decimal(value: unknown, path: string): DecimalValue {
  if (
    (typeof value === "number" && Number.isFinite(value)) ||
    (typeof value === "string" && /^-?\d+(?:\.\d+)?$/.test(value))
  ) {
    return value;
  }
  throw new ContractDecodeError(path, "expected a finite decimal");
}

function nullableDecimal(value: unknown, path: string): DecimalValue | null {
  return value === null ? null : decimal(value, path);
}

function isoTimestamp(value: unknown, path: string): string {
  const result = string(value, path);
  if (Number.isNaN(Date.parse(result))) {
    throw new ContractDecodeError(path, "expected an ISO timestamp");
  }
  return result;
}

function nullableTimestamp(value: unknown, path: string): string | null {
  return value === null ? null : isoTimestamp(value, path);
}

function date(value: unknown, path: string): string {
  const result = string(value, path);
  if (!/^\d{4}-\d{2}-\d{2}$/.test(result)) {
    throw new ContractDecodeError(path, "expected an ISO date");
  }
  return result;
}

function nullableDate(value: unknown, path: string): string | null {
  return value === null ? null : date(value, path);
}

function uuid(value: unknown, path: string): string {
  const result = string(value, path);
  if (
    !/^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(
      result,
    )
  ) {
    throw new ContractDecodeError(path, "expected a UUID");
  }
  return result;
}

function stringArray(value: unknown, path: string): string[] {
  if (!Array.isArray(value)) {
    throw new ContractDecodeError(path, "expected an array");
  }
  return value.map((item, index) => string(item, `${path}[${index}]`));
}

function array<T>(
  value: unknown,
  path: string,
  decoder: (item: unknown, itemPath: string) => T,
): T[] {
  if (!Array.isArray(value)) {
    throw new ContractDecodeError(path, "expected an array");
  }
  return value.map((item, index) => decoder(item, `${path}[${index}]`));
}

function oneOf<T extends string>(
  value: unknown,
  path: string,
  options: readonly T[],
): T {
  const result = string(value, path);
  if (!options.includes(result as T)) {
    throw new ContractDecodeError(path, `expected one of ${options.join(", ")}`);
  }
  return result as T;
}

function stringMap(value: unknown, path: string): Record<string, string> {
  const source = record(value, path);
  return Object.fromEntries(
    Object.entries(source).map(([key, item]) => [
      key,
      string(item, `${path}.${key}`),
    ]),
  );
}

const factStates = ["VALID", "MISSING", "INVALID", "NOT_APPLICABLE"] as const;
const profileStates = ["COMPLETE", "PARTIAL", "INELIGIBLE"] as const;
const rankingStates = ["ELIGIBLE", "NOT_ELIGIBLE"] as const;
const horizons = [
  "ONE_WEEK",
  "ONE_MONTH",
  "THREE_MONTHS",
  "TWELVE_MONTHS_PLUS",
] as const;
const rankMetrics = [
  "OBJECTIVE_QUALITY",
  "OBJECTIVE_VALUATION",
  "TACTICAL_ONE_WEEK",
  "TACTICAL_ONE_MONTH",
  "TACTICAL_THREE_MONTHS",
  "LONG_HORIZON",
  "BUYING_OPPORTUNITY",
] as const;
const directions = ["ASCENDING", "DESCENDING"] as const;

function decodeLineage(value: unknown, path: string): EvidenceLineage {
  const source = record(value, path);
  return {
    providerCode: string(source.providerCode, `${path}.providerCode`),
    providerSchemaVersion: string(
      source.providerSchemaVersion,
      `${path}.providerSchemaVersion`,
    ),
    parserVersion: string(source.parserVersion, `${path}.parserVersion`),
    sourceReference: string(
      source.sourceReference,
      `${path}.sourceReference`,
    ),
    contentHash: string(source.contentHash, `${path}.contentHash`),
    availableAt: isoTimestamp(source.availableAt, `${path}.availableAt`),
    retrievedAt: isoTimestamp(source.retrievedAt, `${path}.retrievedAt`),
    effectiveAt: nullableTimestamp(
      source.effectiveAt,
      `${path}.effectiveAt`,
    ),
  };
}

function decodeFact(value: unknown, path: string): ProfileFact {
  const source = record(value, path);
  const state = oneOf(source.state, `${path}.state`, factStates);
  const factValue = source.value;
  if (
    factValue !== null &&
    typeof factValue !== "string" &&
    typeof factValue !== "number" &&
    typeof factValue !== "boolean"
  ) {
    throw new ContractDecodeError(
      `${path}.value`,
      "expected a scalar value or null",
    );
  }
  if (state === "VALID" && factValue === null) {
    throw new ContractDecodeError(`${path}.value`, "VALID fact needs a value");
  }
  if (state !== "VALID" && factValue !== null) {
    throw new ContractDecodeError(
      `${path}.value`,
      "non-VALID fact must remain null",
    );
  }
  return {
    name: string(source.name, `${path}.name`),
    metricVersion: string(source.metricVersion, `${path}.metricVersion`),
    state,
    value: factValue,
    reason: nullableString(source.reason, `${path}.reason`),
    lineage: array(source.lineage, `${path}.lineage`, decodeLineage),
  };
}

function decodeDeterministicView(
  value: unknown,
  path: string,
): DeterministicView {
  const source = record(value, path);
  const state = oneOf(source.state, `${path}.state`, [
    "ASSESSED",
    "INSUFFICIENT_DATA",
    "NOT_APPLICABLE",
  ] as const);
  const score = nullableDecimal(source.score, `${path}.score`);
  if ((state === "ASSESSED") !== (score !== null)) {
    throw new ContractDecodeError(
      `${path}.score`,
      "only ASSESSED views may carry a score",
    );
  }
  return {
    modelId: string(source.modelId, `${path}.modelId`),
    modelVersion: string(source.modelVersion, `${path}.modelVersion`),
    state,
    asOf: isoTimestamp(source.asOf, `${path}.asOf`),
    effectiveAt: isoTimestamp(source.effectiveAt, `${path}.effectiveAt`),
    expiresAt: nullableTimestamp(source.expiresAt, `${path}.expiresAt`),
    score,
    label: string(source.label, `${path}.label`),
    inputHash: string(source.inputHash, `${path}.inputHash`),
    evidenceHash: string(source.evidenceHash, `${path}.evidenceHash`),
    missingInputs: stringArray(
      source.missingInputs,
      `${path}.missingInputs`,
    ),
    explanation: stringArray(source.explanation, `${path}.explanation`),
  };
}

function decodeSecurityProfile(value: unknown, path: string): SecurityProfile {
  const source = record(value, path);
  const security = record(source.security, `${path}.security`);
  const classificationSource =
    source.classification === null
      ? null
      : record(source.classification, `${path}.classification`);
  const valuation = record(source.valuation, `${path}.valuation`);
  const ai = record(source.aiNarrative, `${path}.aiNarrative`);
  const mayAffect = boolean(
    ai.mayAffectDeterministicFields,
    `${path}.aiNarrative.mayAffectDeterministicFields`,
  );
  if (mayAffect) {
    throw new ContractDecodeError(
      `${path}.aiNarrative.mayAffectDeterministicFields`,
      "AI narrative cannot affect deterministic fields",
    );
  }

  return {
    contractVersion: string(source.contractVersion, `${path}.contractVersion`),
    security: {
      securityId: uuid(
        security.securityId,
        `${path}.security.securityId`,
      ),
      symbol: string(security.symbol, `${path}.security.symbol`),
      issuerName: string(
        security.issuerName,
        `${path}.security.issuerName`,
      ),
      exchangeMic: string(
        security.exchangeMic,
        `${path}.security.exchangeMic`,
      ),
      currency: string(security.currency, `${path}.security.currency`),
      instrumentType: string(
        security.instrumentType,
        `${path}.security.instrumentType`,
      ),
      cik: nullableString(security.cik, `${path}.security.cik`),
      durableProviderId: nullableString(
        security.durableProviderId,
        `${path}.security.durableProviderId`,
      ),
    },
    classification:
      classificationSource === null
        ? null
        : {
            taxonomyCode: string(
              classificationSource.taxonomyCode,
              `${path}.classification.taxonomyCode`,
            ),
            taxonomyVersion: string(
              classificationSource.taxonomyVersion,
              `${path}.classification.taxonomyVersion`,
            ),
            sectorCode: string(
              classificationSource.sectorCode,
              `${path}.classification.sectorCode`,
            ),
            sectorName: string(
              classificationSource.sectorName,
              `${path}.classification.sectorName`,
            ),
            industryCode: string(
              classificationSource.industryCode,
              `${path}.classification.industryCode`,
            ),
            industryName: string(
              classificationSource.industryName,
              `${path}.classification.industryName`,
            ),
            companyType: string(
              classificationSource.companyType,
              `${path}.classification.companyType`,
            ),
            effectiveAt: isoTimestamp(
              classificationSource.effectiveAt,
              `${path}.classification.effectiveAt`,
            ),
            lineage: array(
              classificationSource.lineage,
              `${path}.classification.lineage`,
              decodeLineage,
            ),
          },
    comparableCohorts: array(
      source.comparableCohorts,
      `${path}.comparableCohorts`,
      (item, itemPath) => {
        const cohort = record(item, itemPath);
        return {
          cohortId: string(cohort.cohortId, `${itemPath}.cohortId`),
          taxonomyVersion: string(
            cohort.taxonomyVersion,
            `${itemPath}.taxonomyVersion`,
          ),
          sectorCode: string(cohort.sectorCode, `${itemPath}.sectorCode`),
          industryCode: nullableString(
            cohort.industryCode,
            `${itemPath}.industryCode`,
          ),
          companyType: string(cohort.companyType, `${itemPath}.companyType`),
          sizeBand: nullableString(cohort.sizeBand, `${itemPath}.sizeBand`),
          eligibleMemberCount: integer(
            cohort.eligibleMemberCount,
            `${itemPath}.eligibleMemberCount`,
          ),
          minimumMemberCount: integer(
            cohort.minimumMemberCount,
            `${itemPath}.minimumMemberCount`,
          ),
        };
      },
    ),
    facts: array(source.facts, `${path}.facts`, decodeFact),
    objectiveQualityScore: nullableDecimal(
      source.objectiveQualityScore,
      `${path}.objectiveQualityScore`,
    ),
    objectiveValuationScore: nullableDecimal(
      source.objectiveValuationScore,
      `${path}.objectiveValuationScore`,
    ),
    objectiveRatingStatus: string(
      source.objectiveRatingStatus,
      `${path}.objectiveRatingStatus`,
    ),
    objectiveRatingVersion: string(
      source.objectiveRatingVersion,
      `${path}.objectiveRatingVersion`,
    ),
    horizons: array(
      source.horizons,
      `${path}.horizons`,
      (item, itemPath) => {
        const horizon = record(item, itemPath);
        return {
          horizon: oneOf(
            horizon.horizon,
            `${itemPath}.horizon`,
            horizons,
          ),
          deterministicView: decodeDeterministicView(
            horizon.deterministicView,
            `${itemPath}.deterministicView`,
          ),
        };
      },
    ),
    valuation: {
      state: oneOf(valuation.state, `${path}.valuation.state`, factStates),
      asOf: isoTimestamp(valuation.asOf, `${path}.valuation.asOf`),
      objectiveValuationScore: nullableDecimal(
        valuation.objectiveValuationScore,
        `${path}.valuation.objectiveValuationScore`,
      ),
      longHorizonValuationScore: nullableDecimal(
        valuation.longHorizonValuationScore,
        `${path}.valuation.longHorizonValuationScore`,
      ),
      ownHistoryPercentile: nullableDecimal(
        valuation.ownHistoryPercentile,
        `${path}.valuation.ownHistoryPercentile`,
      ),
      evidence: array(
        valuation.evidence,
        `${path}.valuation.evidence`,
        decodeFact,
      ),
      limitations: stringArray(
        valuation.limitations,
        `${path}.valuation.limitations`,
      ),
    },
    profileState: oneOf(
      source.profileState,
      `${path}.profileState`,
      profileStates,
    ),
    rankingState: oneOf(
      source.rankingState,
      `${path}.rankingState`,
      rankingStates,
    ),
    rankingExclusions: stringArray(
      source.rankingExclusions,
      `${path}.rankingExclusions`,
    ),
    explainability: stringArray(
      source.explainability,
      `${path}.explainability`,
    ),
    aiNarrative: {
      status: string(ai.status, `${path}.aiNarrative.status`),
      narrative: nullableString(
        ai.narrative,
        `${path}.aiNarrative.narrative`,
      ),
      sourceReferences: stringArray(
        ai.sourceReferences,
        `${path}.aiNarrative.sourceReferences`,
      ),
      generatedAt: nullableTimestamp(
        ai.generatedAt,
        `${path}.aiNarrative.generatedAt`,
      ),
      promptVersion: nullableString(
        ai.promptVersion,
        `${path}.aiNarrative.promptVersion`,
      ),
      modelVersion: nullableString(
        ai.modelVersion,
        `${path}.aiNarrative.modelVersion`,
      ),
      confidence: nullableString(
        ai.confidence,
        `${path}.aiNarrative.confidence`,
      ),
      mayAffectDeterministicFields: false,
    },
  };
}

function decodeCurrentMarketData(
  value: unknown,
  path: string,
): CurrentMarketData {
  const source = record(value, path);
  const state = oneOf(source.state, `${path}.state`, factStates);
  const price = nullableDecimal(source.price, `${path}.price`);
  const tradingDate = nullableDate(
    source.tradingDate,
    `${path}.tradingDate`,
  );
  const providerCode = nullableString(
    source.providerCode,
    `${path}.providerCode`,
  );
  const availableAt = nullableTimestamp(
    source.availableAt,
    `${path}.availableAt`,
  );
  const ingestedAt = nullableTimestamp(
    source.ingestedAt,
    `${path}.ingestedAt`,
  );
  const reason = nullableString(source.reason, `${path}.reason`);

  if (
    state === "VALID" &&
    (price === null ||
      tradingDate === null ||
      providerCode === null ||
      availableAt === null ||
      ingestedAt === null)
  ) {
    throw new ContractDecodeError(
      path,
      "VALID market data needs price, date, provider, and timestamps",
    );
  }
  if (state !== "VALID" && price !== null) {
    throw new ContractDecodeError(
      `${path}.price`,
      "non-VALID market data must remain null",
    );
  }
  if (state !== "VALID" && reason === null) {
    throw new ContractDecodeError(
      `${path}.reason`,
      "non-VALID market data needs a reason",
    );
  }

  return {
    state,
    price,
    currency: string(source.currency, `${path}.currency`),
    tradingDate,
    providerCode,
    availableAt,
    ingestedAt,
    adjustmentMode: nullableString(
      source.adjustmentMode,
      `${path}.adjustmentMode`,
    ),
    reason,
  };
}

function decodeFreshness(value: unknown, path: string): DatasetFreshness {
  const source = record(value, path);
  return {
    datasetCode: string(source.datasetCode, `${path}.datasetCode`),
    state: string(source.state, `${path}.state`),
    providerCode: nullableString(
      source.providerCode,
      `${path}.providerCode`,
    ),
    effectiveAt: nullableTimestamp(
      source.effectiveAt,
      `${path}.effectiveAt`,
    ),
    availableAt: nullableTimestamp(
      source.availableAt,
      `${path}.availableAt`,
    ),
    ingestedAt: nullableTimestamp(
      source.ingestedAt,
      `${path}.ingestedAt`,
    ),
    evaluatedAt: isoTimestamp(source.evaluatedAt, `${path}.evaluatedAt`),
    staleAfter: nullableTimestamp(
      source.staleAfter,
      `${path}.staleAfter`,
    ),
    reasonCode: nullableString(
      source.reasonCode,
      `${path}.reasonCode`,
    ),
  };
}

export function decodeProfileEnvelope(
  value: unknown,
  path = "$",
): ProfileEnvelope {
  const source = record(value, path);
  const securityId = uuid(source.securityId, `${path}.securityId`);
  const profile = decodeSecurityProfile(source.profile, `${path}.profile`);
  if (
    profile.security.securityId.toLowerCase() !== securityId.toLowerCase()
  ) {
    throw new ContractDecodeError(
      `${path}.securityId`,
      "envelope and profile security IDs must match",
    );
  }
  return {
    profileId: uuid(source.profileId, `${path}.profileId`),
    securityId,
    profile,
    currentMarketData: decodeCurrentMarketData(
      source.currentMarketData,
      `${path}.currentMarketData`,
    ),
    freshness: array(
      source.freshness,
      `${path}.freshness`,
      decodeFreshness,
    ),
    modelVersions: stringMap(
      source.modelVersions,
      `${path}.modelVersions`,
    ),
  };
}

function decodeRun(value: unknown, path: string): ScreeningRunMetadata {
  const source = record(value, path);
  return {
    runId: uuid(source.runId, `${path}.runId`),
    state: string(source.state, `${path}.state`),
    dataSnapshotId: uuid(source.dataSnapshotId, `${path}.dataSnapshotId`),
    universeVersion: string(
      source.universeVersion,
      `${path}.universeVersion`,
    ),
    asOf: isoTimestamp(source.asOf, `${path}.asOf`),
    rankBy: oneOf(source.rankBy, `${path}.rankBy`, rankMetrics),
    direction: oneOf(source.direction, `${path}.direction`, directions),
    eligibleCount: integer(source.eligibleCount, `${path}.eligibleCount`),
    excludedCount: integer(source.excludedCount, `${path}.excludedCount`),
    gateStatus: string(source.gateStatus, `${path}.gateStatus`),
    profileSetHash: string(
      source.profileSetHash,
      `${path}.profileSetHash`,
    ),
    resultHash: string(source.resultHash, `${path}.resultHash`),
    sealedAt: isoTimestamp(source.sealedAt, `${path}.sealedAt`),
  };
}

export function decodeScreeningRunMetadata(
  value: unknown,
  path = "$",
): ScreeningRunMetadata {
  return decodeRun(value, path);
}

export function decodeScreeningResultPage(
  value: unknown,
  path = "$",
): ScreeningResultPage {
  const source = record(value, path);
  return {
    run: decodeRun(source.run, `${path}.run`),
    items: array(
      source.items,
      `${path}.items`,
      decodeProfileEnvelope,
    ),
    nextCursor: nullableString(source.nextCursor, `${path}.nextCursor`),
  };
}

export function decodeSecuritySearchPage(
  value: unknown,
  path = "$",
): SecuritySearchPage {
  const source = record(value, path);
  return {
    dataSnapshotId: uuid(
      source.dataSnapshotId,
      `${path}.dataSnapshotId`,
    ),
    universeVersion: string(
      source.universeVersion,
      `${path}.universeVersion`,
    ),
    items: array(source.items, `${path}.items`, (item, itemPath) => {
      const security = record(item, itemPath);
      return {
        securityId: uuid(security.securityId, `${itemPath}.securityId`),
        symbol: string(security.symbol, `${itemPath}.symbol`),
        issuerName: string(
          security.issuerName,
          `${itemPath}.issuerName`,
        ),
        exchangeMic: string(
          security.exchangeMic,
          `${itemPath}.exchangeMic`,
        ),
        membershipStatus: string(
          security.membershipStatus,
          `${itemPath}.membershipStatus`,
        ),
        companyType: string(
          security.companyType,
          `${itemPath}.companyType`,
        ),
        sector: nullableString(security.sector, `${itemPath}.sector`),
        industry: nullableString(
          security.industry,
          `${itemPath}.industry`,
        ),
        latestProfileId:
          security.latestProfileId === null
            ? null
            : uuid(
                security.latestProfileId,
                `${itemPath}.latestProfileId`,
              ),
        currentMarketData: decodeCurrentMarketData(
          security.currentMarketData,
          `${itemPath}.currentMarketData`,
        ),
        freshness: array(
          security.freshness,
          `${itemPath}.freshness`,
          decodeFreshness,
        ),
        modelVersions: stringMap(
          security.modelVersions,
          `${itemPath}.modelVersions`,
        ),
      };
    }),
    nextCursor: nullableString(source.nextCursor, `${path}.nextCursor`),
  };
}

export function decodeFacets(
  value: unknown,
  path = "$",
): MarketIntelligenceFacets {
  const source = record(value, path);
  return {
    dataSnapshotId: uuid(
      source.dataSnapshotId,
      `${path}.dataSnapshotId`,
    ),
    universeVersion: string(
      source.universeVersion,
      `${path}.universeVersion`,
    ),
    sectors: stringArray(source.sectors, `${path}.sectors`),
    industries: stringArray(source.industries, `${path}.industries`),
    companyTypes: stringArray(
      source.companyTypes,
      `${path}.companyTypes`,
    ),
    membershipStatuses: stringArray(
      source.membershipStatuses,
      `${path}.membershipStatuses`,
    ),
  };
}

export const isUuid = (value: string): boolean =>
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(
    value,
  );
