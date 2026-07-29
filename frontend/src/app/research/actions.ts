"use server";

import { redirect } from "next/navigation";
import {
  createScreeningRun,
  getResearchSnapshotId,
  getSnapshotAsOf,
  loadResearchFacets,
} from "@/lib/market-intelligence/backend";
import type {
  Horizon,
  RankMetric,
  SortDirection,
} from "@/lib/market-intelligence/contracts";

const horizons = new Set<Horizon>([
  "ONE_WEEK",
  "ONE_MONTH",
  "THREE_MONTHS",
  "TWELVE_MONTHS_PLUS",
]);
const rankMetrics = new Set<RankMetric>([
  "OBJECTIVE_QUALITY",
  "OBJECTIVE_VALUATION",
  "TACTICAL_ONE_WEEK",
  "TACTICAL_ONE_MONTH",
  "TACTICAL_THREE_MONTHS",
  "LONG_HORIZON",
  "BUYING_OPPORTUNITY",
]);
const directions = new Set<SortDirection>(["ASCENDING", "DESCENDING"]);

function field(formData: FormData, name: string): string {
  const value = formData.get(name);
  return typeof value === "string" ? value.trim() : "";
}

function failed(code: string): never {
  redirect(`/research?notice=${encodeURIComponent(code)}`);
}

export async function runScreening(formData: FormData): Promise<never> {
  const snapshot = getResearchSnapshotId();
  const asOf = getSnapshotAsOf();
  const facets = await loadResearchFacets();
  if (!snapshot.ok || !asOf.ok || !facets.ok) {
    failed("SCREENING_CONFIGURATION_UNAVAILABLE");
  }

  const horizon = field(formData, "horizon") as Horizon;
  const rankBy = field(formData, "rankBy") as RankMetric;
  const direction = field(formData, "direction") as SortDirection;
  const sector = field(formData, "sector");
  const industry = field(formData, "industry");
  const companyType = field(formData, "companyType");
  const eligibility = field(formData, "eligibility");

  if (
    !horizons.has(horizon) ||
    !rankMetrics.has(rankBy) ||
    !directions.has(direction)
  ) {
    failed("INVALID_SCREENING_CONFIGURATION");
  }
  if (
    (sector && !facets.data.sectors.includes(sector)) ||
    (industry && !facets.data.industries.includes(industry)) ||
    (companyType && !facets.data.companyTypes.includes(companyType))
  ) {
    failed("INVALID_SCREENING_FILTER");
  }

  const result = await createScreeningRun({
    dataSnapshotId: snapshot.data,
    universeVersion: facets.data.universeVersion,
    asOf: asOf.data,
    filters: {
      sectors: sector ? [sector] : [],
      industries: industry ? [industry] : [],
      companyTypes: companyType ? [companyType] : [],
      symbols: [],
      horizons: [horizon],
      requireRankingEligible: eligibility !== "INCLUDE_EXCLUDED",
    },
    rankBy,
    direction,
    limit: 100,
  });

  if (!result.ok) {
    failed(result.error.code);
  }
  redirect(`/research?run=${encodeURIComponent(result.data.runId)}`);
}
