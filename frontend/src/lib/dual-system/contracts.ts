export const DUAL_SYSTEM_CONTRACT_VERSION =
  "dual-system-architecture-v1.0.0" as const;

export const sleeves = ["LONG_TERM_CORE", "QUANT_TRADING"] as const;
export type Sleeve = (typeof sleeves)[number];

export const dataStates = [
  "VALID",
  "MISSING",
  "STALE",
  "INVALID",
  "NOT_APPLICABLE",
  "EXCLUDED",
] as const;
export type DataState = (typeof dataStates)[number];

export const evidenceStrictnessClasses = [
  "STRICT_IDENTITY_AND_CHRONOLOGY",
  "DOMAIN_TOLERANT_NUMERIC",
  "APPROXIMATE_HISTORICAL_RESEARCH",
] as const;

export const evidenceClaimClasses = [
  "CURRENT_ONLY",
  "APPROXIMATE_HISTORICAL",
  "STRICT_PIT",
  "SEALED_PROSPECTIVE",
] as const;

export const modelApplicabilityStates = [
  "APPLICABLE",
  "SPECIALIZED_MODEL_REQUIRED",
  "NOT_APPLICABLE",
  "INSUFFICIENT_EVIDENCE",
] as const;

export const modelEvidenceLabels = [
  "NOT_VALIDATED",
  "DEVELOPMENT_OBSERVED",
  "BACKTEST_SUPPORTED",
  "PIT_SUPPORTED",
  "FORWARD_SUPPORTED",
] as const;

export class DualSystemContractError extends Error {}

export function decodeDualSystemDecisionContext(value: unknown) {
  const root = object(value, "decision context");
  if (root.contractVersion !== DUAL_SYSTEM_CONTRACT_VERSION) {
    throw new DualSystemContractError("Unsupported dual-system contract version");
  }
  const versions = object(root.versionSet, "version set");
  for (const field of [
    "evidenceSchemaVersion",
    "calendarVersion",
    "taxonomyVersion",
    "normalizationVersion",
    "benchmarkPolicyVersion",
    "riskPolicyVersion",
    "costPolicyVersion",
  ]) {
    nonblank(versions[field], field);
  }
  const timing = object(root.decisionTiming, "decision timing");
  const decisionCutoff = timestamp(timing.decisionCutoff, "decision cutoff");
  const ingestionCutoff = timestamp(
    timing.sealedIngestionCutoff,
    "sealed ingestion cutoff",
  );
  if (decisionCutoff > ingestionCutoff) {
    throw new DualSystemContractError(
      "Decision cutoff cannot exceed sealed ingestion cutoff",
    );
  }
  const security = object(root.security, "security");
  for (const field of [
    "securityId",
    "companyId",
    "instrumentId",
    "shareClassId",
    "listingId",
    "tickerAssignmentId",
    "ticker",
    "mic",
    "currency",
  ]) {
    nonblank(security[field], field);
  }
  const evidence = object(root.evidence, "evidence");
  const evidenceState = enumeration(evidence.state, dataStates, "evidence state");
  if (evidenceState !== "VALID") nonblank(evidence.reasonCode, "evidence reason");
  for (const field of [
    "providerCode",
    "providerSchemaVersion",
    "adapterVersion",
    "normalizationVersion",
    "sourceRecordId",
    "sourceContentHash",
    "normalizedRecordHash",
    "freshnessPolicyVersion",
  ]) {
    nonblank(evidence[field], field);
  }
  if (
    typeof evidence.sourceRevision !== "number" ||
    !Number.isInteger(evidence.sourceRevision) ||
    evidence.sourceRevision < 1
  ) {
    throw new DualSystemContractError(
      "sourceRevision must be a positive integer",
    );
  }
  const effectiveAt = timestamp(evidence.effectiveAt, "effectiveAt");
  const availableAt = timestamp(evidence.availableAt, "availableAt");
  const ingestedAt = timestamp(evidence.ingestedAt, "ingestedAt");
  if (!(effectiveAt <= availableAt && availableAt <= ingestedAt)) {
    throw new DualSystemContractError(
      "Evidence chronology must be effective <= available <= ingested",
    );
  }
  if (availableAt > decisionCutoff) {
    throw new DualSystemContractError("Evidence exceeds the decision cutoff");
  }
  if (ingestedAt > ingestionCutoff) {
    throw new DualSystemContractError("Evidence exceeds the sealed ingestion cutoff");
  }
  const retrievedAt = optionalTimestamp(evidence.retrievedAt, "retrievedAt");
  if (
    retrievedAt !== undefined &&
    !(availableAt <= retrievedAt && retrievedAt <= ingestedAt)
  ) {
    throw new DualSystemContractError(
      "Retrieved evidence chronology is invalid",
    );
  }
  optionalTimestamp(evidence.staleAfter, "staleAfter");
  const conflict = object(evidence.conflict, "evidence conflict");
  nonblank(conflict.status, "conflict status");
  nonblank(conflict.criticality, "conflict criticality");
  const strictness = enumeration(
    evidence.strictnessClass,
    evidenceStrictnessClasses,
    "evidence strictness",
  );
  const claim = enumeration(
    evidence.claimClass,
    evidenceClaimClasses,
    "evidence claim class",
  );
  if (
    strictness === "APPROXIMATE_HISTORICAL_RESEARCH" &&
    (claim === "STRICT_PIT" || claim === "SEALED_PROSPECTIVE")
  ) {
    throw new DualSystemContractError(
      "Approximate historical evidence cannot claim PIT or prospective status",
    );
  }
  if (strictness === "DOMAIN_TOLERANT_NUMERIC") {
    const tolerance = object(
      evidence.fieldTolerancePolicy,
      "field tolerance policy",
    );
    if (
      typeof tolerance.policyVersion !== "string" ||
      tolerance.policyVersion.trim() === "" ||
      typeof tolerance.fieldCode !== "string" ||
      tolerance.fieldCode.trim() === "" ||
      tolerance.alignmentSatisfied !== true
    ) {
      throw new DualSystemContractError(
        "Numeric tolerance must be aligned, field-specific, and versioned",
      );
    }
  }

  const fundamental = object(
    root.fundamentalValueOutput,
    "fundamental value output",
  );
  const quant = object(root.quantTradePlanOutput, "quant trade plan output");
  for (const output of [fundamental, quant]) {
    for (const field of [
      "outputId",
      "decisionContractVersion",
      "modelId",
      "modelVersion",
      "strategyVersion",
      "evidenceHash",
    ]) {
      nonblank(output[field], field);
    }
  }
  if (enumeration(fundamental.sleeve, sleeves, "fundamental sleeve") !== "LONG_TERM_CORE") {
    throw new DualSystemContractError(
      "Fundamental value output must use LONG_TERM_CORE",
    );
  }
  if (enumeration(quant.sleeve, sleeves, "quant sleeve") !== "QUANT_TRADING") {
    throw new DualSystemContractError("Quant trade plan must use QUANT_TRADING");
  }
  const fundamentalState = enumeration(
    fundamental.state,
    dataStates,
    "fundamental state",
  );
  const quantState = enumeration(quant.state, dataStates, "quant state");
  enumeration(
    fundamental.applicability,
    modelApplicabilityStates,
    "model applicability",
  );
  if (fundamental.automaticFinalWeight !== null) {
    throw new DualSystemContractError(
      "Value engine cannot set an automatic final portfolio weight",
    );
  }
  validateScoreState(fundamental, fundamentalState, "fundamental");
  validateScoreState(quant, quantState, "quant");
  const fairValue = object(fundamental.fairValue, "fair value");
  const central = decimal(fairValue.central, "central fair value");
  const low = decimal(fairValue.rangeLow, "fair value range low");
  const high = decimal(fairValue.rangeHigh, "fair value range high");
  if (
    compareDecimalStrings(low, central) > 0 ||
    compareDecimalStrings(central, high) > 0
  ) {
    throw new DualSystemContractError(
      "Fair-value range must contain the central estimate",
    );
  }
  nonblank(fairValue.currency, "fair value currency");
  nonblank(fairValue.methodVersion, "fair value method version");
  decimal(fundamental.marginOfSafety, "margin of safety");
  decimal(fundamental.maximumAllocationCap, "allocation cap");
  decimal(fundamental.referencePrice, "reference price");
  exactStrings(
    fundamental.benchmarkCodes,
    ["SPY", "DATED_SECTOR_BENCHMARK"],
    "fundamental benchmarks",
  );
  if (
    quant.market !== "US_EQUITIES" ||
    quant.cadence !== "DAILY" ||
    quant.direction !== "LONG_ONLY"
  ) {
    throw new DualSystemContractError(
      "Quant v1 market, cadence, and direction are fixed",
    );
  }
  for (const field of [
    "leverageAllowed",
    "shortingAllowed",
    "optionsAllowed",
    "brokerageExecutionAllowed",
  ]) {
    if (quant[field] !== false) {
      throw new DualSystemContractError(
        "Quant v1 cannot enable leverage, shorting, options, or execution",
      );
    }
  }
  nonblank(quant.entryRule, "entryRule");
  for (const field of ["entryRangeLow", "entryRangeHigh", "stop"]) {
    decimal(quant[field], field);
  }
  nonblank(quant.setup, "quant setup");
  if (
    !Array.isArray(quant.targets) ||
    quant.targets.length === 0 ||
    !quant.targets.every((item) => typeof item === "string" && item.trim() !== "")
  ) {
    throw new DualSystemContractError("Quant targets must be nonempty");
  }
  if (
    typeof quant.expiresAfterCompletedSessions !== "number" ||
    !Number.isInteger(quant.expiresAfterCompletedSessions) ||
    quant.expiresAfterCompletedSessions < 1
  ) {
    throw new DualSystemContractError("Quant expiry is invalid");
  }
  decimal(quant.maximumPositionRisk, "maximum position risk");
  exactStrings(
    quant.benchmarkCodes,
    ["SPY", "DATED_SECTOR_BENCHMARK", "CASH"],
    "quant benchmarks",
  );
  validateAssumptions(quant.liquidityAssumptions, "liquidity assumptions");
  validateAssumptions(quant.costAssumptions, "cost assumptions");

  const session = object(root.completedSession, "completed session");
  for (const field of [
    "calendarId",
    "calendarVersion",
    "mic",
    "timezone",
  ]) {
    nonblank(session[field], field);
  }
  isoDate(session.sessionDate, "sessionDate");
  for (const field of ["scheduledOpen", "scheduledClose", "completedAt"]) {
    timestamp(session[field], field);
  }
  const scheduledOpen = timestamp(session.scheduledOpen, "scheduledOpen");
  const scheduledClose = timestamp(session.scheduledClose, "scheduledClose");
  const completedAt = timestamp(session.completedAt, "completedAt");
  if (
    !(
      scheduledOpen < scheduledClose &&
      scheduledClose <= completedAt &&
      completedAt <= decisionCutoff &&
      decisionCutoff <= ingestionCutoff
    )
  ) {
    throw new DualSystemContractError("Completed-session chronology is invalid");
  }
  for (const target of quant.targets) decimal(target, "quant target");
  if (session.status !== "COMPLETED" || typeof session.earlyClose !== "boolean") {
    throw new DualSystemContractError("Completed session must be COMPLETED");
  }

  const portfolio = object(root.portfolioRiskView, "portfolio risk view");
  if (portfolio.scoreAggregationPolicy !== "PROHIBITED_ACROSS_ENGINES") {
    throw new DualSystemContractError("Cross-engine score averaging is prohibited");
  }
  if (portfolio.automaticCashTransfersAllowed !== false) {
    throw new DualSystemContractError(
      "Cash transfers require an explicit human decision",
    );
  }
  if (
    portfolio.sameSecurityAcrossSleevesAllowed !== true ||
    portfolio.cashTransferAuthority !== "EXPLICIT_HUMAN_DECISION_ONLY"
  ) {
    throw new DualSystemContractError("Portfolio sleeve policy is invalid");
  }
  if (!Array.isArray(portfolio.sleeves) || portfolio.sleeves.length !== 2) {
    throw new DualSystemContractError("Exactly two sleeve entries are required");
  }
  nonblank(portfolio.contractVersion, "portfolio contract version");
  const sleeveEntries = portfolio.sleeves.map((entry) =>
    object(entry, "sleeve entry"),
  );
  if (
    sleeveEntries[0]?.sleeve === sleeveEntries[1]?.sleeve ||
    !sleeveEntries.some((entry) => entry.sleeve === "LONG_TERM_CORE") ||
    !sleeveEntries.some((entry) => entry.sleeve === "QUANT_TRADING")
  ) {
    throw new DualSystemContractError("Distinct approved sleeves are required");
  }
  for (const entry of sleeveEntries) {
    exactStrings(
      entry.benchmarkCodes,
      entry.sleeve === "LONG_TERM_CORE"
        ? ["SPY", "DATED_SECTOR_BENCHMARK"]
        : ["SPY", "DATED_SECTOR_BENCHMARK", "CASH"],
      "sleeve benchmarks",
    );
    const expectedOutputId =
      entry.sleeve === "LONG_TERM_CORE"
        ? fundamental.outputId
        : quant.outputId;
    if (nonblank(entry.engineOutputId, "engine output ID") !== expectedOutputId) {
      throw new DualSystemContractError(
        "Sleeve engine-output binding is invalid",
      );
    }
  }

  const ai = object(root.aiNarrative, "AI narrative");
  if (
    ai.mayAffectDeterministicFields !== false ||
    ai.maySetWeightsOrTrades !== false
  ) {
    throw new DualSystemContractError("AI must remain narrative-only");
  }
  const human = object(root.humanControl, "human control");
  if (
    human.automaticBrokerageExecutionAllowed !== false ||
    human.decisionRequiredForFinalAllocation !== true ||
    human.decisionRequiredForCashTransfer !== true ||
    human.decisionRecordsAreImmutable !== true ||
    human.correctionsUseSupersession !== true
  ) {
    throw new DualSystemContractError(
      "Final allocation requires human control and no automatic execution",
    );
  }
  const compatibility = object(root.compatibility, "compatibility");
  if (
    compatibility.legacyBuyingOpportunityMeaning !==
      "LONG_TERM_VALUATION_EVIDENCE" ||
    compatibility.successorMetric !== "VALUATION_OPPORTUNITY" ||
    compatibility.legacyPublicMarketDataApiStatus !== "COMPATIBILITY_SURFACE"
  ) {
    throw new DualSystemContractError(
      "Compatibility tuple is invalid",
    );
  }
  const governance = object(root.validationGovernance, "validation governance");
  exactStrings(
    governance.internalApproximateHistoricalRepresentation,
    ["APPROXIMATE_HISTORICAL_RESEARCH", "APPROXIMATE_HISTORICAL"],
    "approximate historical representation",
  );
  if (
    governance.userFacingConcept !== "APPROXIMATE_HISTORICAL_BACKTEST" ||
    governance.mayUpgradeModelEvidenceLabel !== false
  ) {
    throw new DualSystemContractError(
      "Evidence usability cannot upgrade model evidence labels",
    );
  }
  nonblank(governance.modelEvidenceLabel, "model evidence label");
  enumeration(
    governance.modelEvidenceLabel,
    modelEvidenceLabels,
    "model evidence label",
  );
  return root;
}

function nonblank(value: unknown, label: string): string {
  if (typeof value !== "string" || value.trim() === "") {
    throw new DualSystemContractError(`${label} must be nonblank`);
  }
  return value;
}

function timestamp(value: unknown, label: string): number {
  const text = nonblank(value, label);
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d+)?(Z|[+-]\d{2}:\d{2})$/.exec(
    text,
  );
  if (
    match === null ||
    !validCalendarDate(Number(match[1]), Number(match[2]), Number(match[3])) ||
    Number(match[4]) > 23 ||
    Number(match[5]) > 59 ||
    Number(match[6]) > 59 ||
    (match[7] !== "Z" &&
      (Number(match[7]!.slice(1, 3)) > 23 ||
        Number(match[7]!.slice(4, 6)) > 59))
  ) {
    throw new DualSystemContractError(
      `${label} must be an RFC 3339 instant with timezone`,
    );
  }
  const parsed = Date.parse(text);
  if (Number.isNaN(parsed)) {
    throw new DualSystemContractError(`${label} must be a timestamp`);
  }
  return parsed;
}

function optionalTimestamp(value: unknown, label: string): number | undefined {
  if (value !== null && value !== undefined) return timestamp(value, label);
  return undefined;
}

function decimal(value: unknown, label: string): string {
  const text = nonblank(value, label);
  if (!/^-?(?:0|[1-9]\d*)(?:\.\d+)?$/.test(text)) {
    throw new DualSystemContractError(
      `${label} must be an ordinary base-10 decimal string`,
    );
  }
  return text;
}

function compareDecimalStrings(left: string, right: string): number {
  const leftParts = decimalParts(left);
  const rightParts = decimalParts(right);
  if (leftParts.negative !== rightParts.negative) {
    return leftParts.negative ? -1 : 1;
  }
  const magnitude = compareMagnitude(leftParts, rightParts);
  return leftParts.negative ? -magnitude : magnitude;
}

function decimalParts(value: string): {
  negative: boolean;
  integer: string;
  fraction: string;
} {
  const negative = value.startsWith("-") && value !== "-0";
  const unsigned = value.startsWith("-") ? value.slice(1) : value;
  const [integer, rawFraction = ""] = unsigned.split(".");
  const fraction = rawFraction.replace(/0+$/, "");
  const isZero = integer === "0" && fraction === "";
  return { negative: negative && !isZero, integer, fraction };
}

function compareMagnitude(
  left: { integer: string; fraction: string },
  right: { integer: string; fraction: string },
): number {
  if (left.integer.length !== right.integer.length) {
    return left.integer.length < right.integer.length ? -1 : 1;
  }
  if (left.integer !== right.integer) {
    return left.integer < right.integer ? -1 : 1;
  }
  const width = Math.max(left.fraction.length, right.fraction.length);
  const leftFraction = left.fraction.padEnd(width, "0");
  const rightFraction = right.fraction.padEnd(width, "0");
  if (leftFraction === rightFraction) return 0;
  return leftFraction < rightFraction ? -1 : 1;
}

function exactStrings(value: unknown, expected: string[], label: string): void {
  if (
    !Array.isArray(value) ||
    value.length !== expected.length ||
    !value.every((item, index) => item === expected[index])
  ) {
    throw new DualSystemContractError(`${label} must match the approved ordered set`);
  }
}

function validateScoreState(
  payload: Record<string, unknown>,
  state: DataState,
  label: string,
): void {
  if (state !== "VALID") {
    nonblank(payload.reasonCode, `${label} reason`);
    if (payload.deterministicScore !== null) {
      throw new DualSystemContractError(
        `Non-VALID ${label} output cannot carry a score`,
      );
    }
  }
}

function validateAssumptions(value: unknown, label: string): void {
  const assumptions = object(value, label);
  nonblank(assumptions.version, `${label} version`);
  const state = enumeration(assumptions.state, dataStates, `${label} state`);
  if (state !== "VALID") nonblank(assumptions.reasonCode, `${label} reason`);
  const fields =
    label === "liquidity assumptions"
      ? ["averageDailyDollarVolume", "maximumParticipationRate"]
      : ["transactionCostBps", "slippageBps"];
  for (const field of fields) decimal(assumptions[field], field);
}

function isoDate(value: unknown, label: string): void {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(nonblank(value, label));
  if (
    match === null ||
    !validCalendarDate(Number(match[1]), Number(match[2]), Number(match[3]))
  ) {
    throw new DualSystemContractError(`${label} must be a real ISO date`);
  }
}

function validCalendarDate(year: number, month: number, day: number): boolean {
  if (month < 1 || month > 12 || day < 1) return false;
  const daysInMonth = new Date(Date.UTC(year, month, 0)).getUTCDate();
  return day <= daysInMonth;
}

function object(value: unknown, label: string): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new DualSystemContractError(`${label} must be an object`);
  }
  return value as Record<string, unknown>;
}

function enumeration<const T extends readonly string[]>(
  value: unknown,
  allowed: T,
  label: string,
): T[number] {
  if (
    typeof value !== "string" ||
    !allowed.includes(value as T[number])
  ) {
    throw new DualSystemContractError(`${label} is unsupported`);
  }
  return value as T[number];
}
