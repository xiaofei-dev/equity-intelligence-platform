import { decodePortfolioDecisionScenarios, PortfolioDecisionContractError } from "./contracts.ts";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const DECIMAL = /^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$/;
const DATE = /^\d{4}-\d{2}-\d{2}$/;
const INSTANT = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/;
const IDENTITY = /^[A-Za-z0-9._:@+-]{1,128}$/;

export class PortfolioEvaluationContractError extends Error {}

export type EvaluationMaturity = {
  horizonSessions: 20 | 60 | 252 | 504 | 756;
  state: "AWAITING_NATURAL_MATURITY" | "AVAILABLE" | "TERMINAL_MISSING";
  terminalReason: string | null;
  observedAt: string | null;
};

export type EvaluationPeriodSummary = {
  horizonSessions: 20 | 60 | 252 | 504 | 756;
  periodStart: string;
  periodEnd: string;
  expectedObservationCount: number;
  observationCount: number;
  grossReturn: string | null;
  netReturn: string;
  benchmarkReturn: string;
  excessReturn: string;
  holdCurrentReturn: string;
  acceptedExcessVsHoldCurrent: string;
  maximumDrawdown: string | null;
  totalTurnover: string;
  totalCost: string;
  coverageRate: string;
};

export type SimulatedEvaluation = {
  evaluationId: string;
  portfolioId: string;
  humanDecisionId: string;
  startingContextId: string;
  acceptedScenarioId: string;
  holdCurrentScenarioId: string;
  state: "AWAITING_NATURAL_MATURITY" | "PARTIALLY_MATURED" | "MATURED";
  benchmarkCode: "SPY";
  simulatedOnly: true;
  maturities: EvaluationMaturity[];
  summaries: EvaluationPeriodSummary[];
  recordedAt: string;
};

export type PortfolioEvaluationResult = {
  ok: true;
  data: { scenarioId: string; scenarioType: string; evaluation: SimulatedEvaluation | null }[];
} | { ok: false; error: string };

export function decodeSimulatedEvaluation(value: unknown, portfolioId: string): SimulatedEvaluation {
  const row = object(value, "evaluation");
  exact(row, ["evaluationId", "portfolioId", "humanDecisionId", "startingContextId", "acceptedScenarioId", "holdCurrentScenarioId", "state", "benchmarkCode", "simulatedOnly", "maturities", "summaries", "recordedAt"], "evaluation");
  const evaluationId = id(row.evaluationId, "evaluationId");
  const decodedPortfolioId = id(row.portfolioId, "portfolioId");
  if (decodedPortfolioId !== portfolioId) fail("Evaluation portfolio identity drift.");
  const state = enumeration(row.state, ["AWAITING_NATURAL_MATURITY", "PARTIALLY_MATURED", "MATURED"] as const, "state");
  if (row.benchmarkCode !== "SPY" || row.simulatedOnly !== true) fail("Evaluation must remain SPY-benchmarked and simulation-only.");
  const maturities = array(row.maturities, "maturities").map(decodeMaturity);
  const horizons = maturities.map((item) => item.horizonSessions);
  if (horizons.join("|") !== "20|60|252|504|756") fail("Evaluation maturities must contain the five ordered horizons.");
  const awaiting = maturities.filter((item) => item.state === "AWAITING_NATURAL_MATURITY").length;
  if ((state === "AWAITING_NATURAL_MATURITY") !== (awaiting === 5)
      || (state === "MATURED") !== (awaiting === 0)) fail("Evaluation maturity state parity failed.");
  const summaries = array(row.summaries, "summaries").map(decodeSummary);
  if (summaries.some((item, index) => index > 0 && `${item.periodStart}|${item.periodEnd}` <= `${summaries[index - 1].periodStart}|${summaries[index - 1].periodEnd}`)) fail("Evaluation summaries must be strictly ordered.");
  const availableHorizons = maturities.filter((item) => item.state === "AVAILABLE").map((item) => item.horizonSessions);
  if (summaries.length !== availableHorizons.length
      || summaries.some((item, index) => item.horizonSessions !== availableHorizons[index])) fail("Every available maturity must have exactly one matching summary.");
  const acceptedScenarioId = id(row.acceptedScenarioId, "acceptedScenarioId");
  const holdCurrentScenarioId = id(row.holdCurrentScenarioId, "holdCurrentScenarioId");
  if (acceptedScenarioId === holdCurrentScenarioId) fail("Accepted and HOLD_CURRENT scenarios must be distinct.");
  return { evaluationId, portfolioId: decodedPortfolioId, humanDecisionId: id(row.humanDecisionId, "humanDecisionId"), startingContextId: id(row.startingContextId, "startingContextId"), acceptedScenarioId, holdCurrentScenarioId, state, benchmarkCode: "SPY", simulatedOnly: true, maturities, summaries, recordedAt: instant(row.recordedAt, "recordedAt") };
}

export async function loadLatestPortfolioEvaluations(portfolioId: string): Promise<PortfolioEvaluationResult> {
  if (!UUID.test(portfolioId)) return { ok: false, error: "The portfolio identifier is invalid." };
  const raw = process.env.BACKEND_BASE_URL; const identity = process.env.CLOSED_TEST_IDENTITY;
  if (!raw || !identity || !IDENTITY.test(identity)) return { ok: false, error: "Simulation evaluation is not configured." };
  let origin: URL;
  try { origin = new URL(raw); if (!["http:", "https:"].includes(origin.protocol) || origin.username || origin.password) throw new Error(); }
  catch { return { ok: false, error: "Simulation evaluation is not configured." }; }
  const headers = { Accept: "application/json", "X-Test-Identity": identity };
  try {
    const scenariosResponse = await fetch(new URL(`/api/v1/me/portfolios/${portfolioId}/decision-scenarios`, origin), { cache: "no-store", signal: AbortSignal.timeout(10_000), headers });
    if (!scenariosResponse.ok) return { ok: false, error: `Spring returned HTTP ${scenariosResponse.status}.` };
    const scenarios = decodePortfolioDecisionScenarios(await scenariosResponse.json());
    if (scenarios.some((scenario) => scenario.portfolioId !== portfolioId)) throw new PortfolioDecisionContractError("Portfolio identity drift.");
    const data = await Promise.all(scenarios.map(async (scenario) => {
      const response = await fetch(new URL(`/api/v1/me/portfolios/${portfolioId}/decision-scenarios/${scenario.scenarioId}/evaluations/latest`, origin), { cache: "no-store", signal: AbortSignal.timeout(10_000), headers });
      if (response.status === 404) return { scenarioId: scenario.scenarioId, scenarioType: scenario.scenarioType, evaluation: null };
      if (!response.ok) throw new Error();
      const evaluation = decodeSimulatedEvaluation(await response.json(), portfolioId);
      if (evaluation.acceptedScenarioId !== scenario.scenarioId) throw new PortfolioEvaluationContractError("Accepted scenario identity drift.");
      return { scenarioId: scenario.scenarioId, scenarioType: scenario.scenarioType, evaluation };
    }));
    return { ok: true, data };
  } catch { return { ok: false, error: "Spring returned an unavailable or invalid simulation evaluation." }; }
}

function decodeMaturity(value: unknown): EvaluationMaturity {
  const row = object(value, "maturity"); exact(row, ["horizonSessions", "state", "terminalReason", "observedAt"], "maturity");
  if (typeof row.horizonSessions !== "number" || ![20, 60, 252, 504, 756].includes(row.horizonSessions)) fail("Maturity horizon is unsupported.");
  const state = enumeration(row.state, ["AWAITING_NATURAL_MATURITY", "AVAILABLE", "TERMINAL_MISSING"] as const, "maturity.state");
  const terminalReason = row.terminalReason === null ? null : text(row.terminalReason, "terminalReason");
  const observedAt = row.observedAt === null ? null : instant(row.observedAt, "observedAt");
  if ((state === "AWAITING_NATURAL_MATURITY" && (terminalReason !== null || observedAt !== null))
      || (state === "AVAILABLE" && (terminalReason !== null || observedAt === null))
      || (state === "TERMINAL_MISSING" && (terminalReason === null || observedAt === null))) fail("Maturity state/value parity failed.");
  return { horizonSessions: row.horizonSessions as EvaluationMaturity["horizonSessions"], state, terminalReason, observedAt };
}

function decodeSummary(value: unknown): EvaluationPeriodSummary {
  const row = object(value, "summary"); const keys = ["horizonSessions", "periodStart", "periodEnd", "expectedObservationCount", "observationCount", "grossReturn", "netReturn", "benchmarkReturn", "excessReturn", "holdCurrentReturn", "acceptedExcessVsHoldCurrent", "maximumDrawdown", "totalTurnover", "totalCost", "coverageRate"];
  exact(row, keys, "summary");
  if (typeof row.horizonSessions !== "number" || ![20, 60, 252, 504, 756].includes(row.horizonSessions)) fail("Summary horizon is unsupported.");
  const periodStart = date(row.periodStart, "periodStart"); const periodEnd = date(row.periodEnd, "periodEnd"); if (periodEnd < periodStart) fail("Summary period is reversed.");
  if (!Number.isSafeInteger(row.expectedObservationCount) || !Number.isSafeInteger(row.observationCount)
      || Number(row.expectedObservationCount) !== Number(row.horizonSessions) + 1
      || Number(row.observationCount) !== Number(row.expectedObservationCount)) fail("Available summary observation counts must equal horizon plus entry.");
  const result = { horizonSessions: row.horizonSessions as EvaluationPeriodSummary["horizonSessions"], periodStart, periodEnd, expectedObservationCount: Number(row.expectedObservationCount), observationCount: Number(row.observationCount), grossReturn: nullableDec(row.grossReturn, "grossReturn"), netReturn: dec(row.netReturn, "netReturn"), benchmarkReturn: dec(row.benchmarkReturn, "benchmarkReturn"), excessReturn: dec(row.excessReturn, "excessReturn"), holdCurrentReturn: dec(row.holdCurrentReturn, "holdCurrentReturn"), acceptedExcessVsHoldCurrent: dec(row.acceptedExcessVsHoldCurrent, "acceptedExcessVsHoldCurrent"), maximumDrawdown: nullableDec(row.maximumDrawdown, "maximumDrawdown"), totalTurnover: dec(row.totalTurnover, "totalTurnover"), totalCost: dec(row.totalCost, "totalCost"), coverageRate: dec(row.coverageRate, "coverageRate") };
  for (const [name, value] of [["grossReturn", result.grossReturn], ["netReturn", result.netReturn], ["benchmarkReturn", result.benchmarkReturn], ["holdCurrentReturn", result.holdCurrentReturn]] as const) {
    if (value !== null && compareDecimal(value, "-1") < 0) fail(`${name} cannot be below total loss.`);
  }
  if (!equalDifference(result.netReturn, result.benchmarkReturn, result.excessReturn)) fail("Accepted excess versus benchmark arithmetic drifted.");
  if (!equalDifference(result.netReturn, result.holdCurrentReturn, result.acceptedExcessVsHoldCurrent)) fail("Accepted excess versus HOLD_CURRENT arithmetic drifted.");
  if (!equalRatio(result.coverageRate, result.observationCount, result.expectedObservationCount)) fail("Summary coverage does not match its counts.");
  if (result.coverageRate !== "1") fail("Available summary coverage must be complete.");
  if (result.maximumDrawdown !== null && (compareDecimal(result.maximumDrawdown, "-1") < 0 || compareDecimal(result.maximumDrawdown, "0") > 0)) fail("Maximum drawdown is outside [-1,0].");
  if (compareDecimal(result.totalTurnover, "0") < 0 || compareDecimal(result.totalCost, "0") < 0) fail("Turnover and cost must be nonnegative.");
  return result;
}

function object(value: unknown, name: string): Record<string, unknown> { if (!value || typeof value !== "object" || Array.isArray(value)) fail(`${name} must be an object.`); return value as Record<string, unknown>; }
function array(value: unknown, name: string): unknown[] { if (!Array.isArray(value)) fail(`${name} must be an array.`); return value; }
function exact(value: Record<string, unknown>, keys: string[], name: string) { if (Object.keys(value).sort().join("|") !== [...keys].sort().join("|")) fail(`${name} fields are invalid.`); }
function text(value: unknown, name: string): string { if (typeof value !== "string" || value.trim() === "") fail(`${name} must be nonblank.`); return value; }
function id(value: unknown, name: string): string { const result = text(value, name); if (!UUID.test(result)) fail(`${name} is invalid.`); return result; }
function dec(value: unknown, name: string): string { const result = text(value, name); if (!DECIMAL.test(result) || /^-0(?:\.0+)?$/.test(result)) fail(`${name} is not a canonical decimal.`); return result; }
function nullableDec(value: unknown, name: string): string | null { return value === null ? null : dec(value, name); }
function date(value: unknown, name: string): string { const result = text(value, name); if (!DATE.test(result)) fail(`${name} is invalid.`); const [year, month, day] = result.split("-").map(Number); const parsed = new Date(Date.UTC(year, month - 1, day)); if (parsed.getUTCFullYear() !== year || parsed.getUTCMonth() !== month - 1 || parsed.getUTCDate() !== day) fail(`${name} is invalid.`); return result; }
function instant(value: unknown, name: string): string { const result = text(value, name); if (!INSTANT.test(result)) fail(`${name} is not a whole-second instant.`); const [datePart, timePart] = result.slice(0, -1).split("T"); date(datePart, name); const [hour, minute, second] = timePart.split(":").map(Number); if (hour > 23 || minute > 59 || second > 59) fail(`${name} is not a whole-second instant.`); return result; }
function enumeration<const T extends readonly string[]>(value: unknown, values: T, name: string): T[number] { if (typeof value !== "string" || !values.includes(value)) fail(`${name} is unsupported.`); return value as T[number]; }
function decimalParts(value: string): { negative: boolean; coefficient: bigint; scale: number } { const negative = value.startsWith("-"); const unsigned = negative ? value.slice(1) : value; const [integer, fraction = ""] = unsigned.split("."); return { negative, coefficient: BigInt(`${integer}${fraction}`), scale: fraction.length }; }
function signedCoefficient(value: string, scale: number): bigint { const parts = decimalParts(value); const coefficient = parts.coefficient * (BigInt(10) ** BigInt(scale - parts.scale)); return parts.negative ? -coefficient : coefficient; }
function compareDecimal(left: string, right: string): number { const scale = Math.max(decimalParts(left).scale, decimalParts(right).scale); const delta = signedCoefficient(left, scale) - signedCoefficient(right, scale); return delta < BigInt(0) ? -1 : delta > BigInt(0) ? 1 : 0; }
function equalDifference(left: string, right: string, expected: string): boolean { const scale = Math.max(decimalParts(left).scale, decimalParts(right).scale, decimalParts(expected).scale); return signedCoefficient(left, scale) - signedCoefficient(right, scale) === signedCoefficient(expected, scale); }
function equalRatio(value: string, numerator: number, denominator: number): boolean { const parts = decimalParts(value); const signed = parts.negative ? -parts.coefficient : parts.coefficient; return signed * BigInt(denominator) === BigInt(numerator) * (BigInt(10) ** BigInt(parts.scale)); }
function fail(message: string): never { throw new PortfolioEvaluationContractError(message); }
