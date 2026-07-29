import Link from "next/link";
import { humanize, formatScore, formatTimestamp } from "@/lib/format";
import {
  getDefaultScreeningRunId,
  loadResearchFacets,
  loadScreeningResults,
  searchSecurities,
} from "@/lib/market-intelligence/backend";
import type {
  ProfileEnvelope,
  ScreeningResultPage,
  SecuritySearchPage,
  SecuritySearchItem,
} from "@/lib/market-intelligence/contracts";
import { runScreening } from "./actions";
import { ErrorPanel } from "./components/error-panel";
import { MarketDataBlock } from "./components/market-data-block";
import { StatusPill } from "./components/status-pill";

export const dynamic = "force-dynamic";

type Query = Record<string, string | string[] | undefined>;

function single(value: string | string[] | undefined): string {
  return typeof value === "string" ? value : "";
}

function isScreeningPage(
  value: ScreeningResultPage | SecuritySearchPage,
): value is ScreeningResultPage {
  return "run" in value;
}

const notices: Record<string, string> = {
  SCREENING_CONFIGURATION_UNAVAILABLE:
    "Screening execution is not configured for this environment.",
  INVALID_SCREENING_CONFIGURATION:
    "The requested screening configuration is invalid.",
  INVALID_SCREENING_FILTER:
    "One of the selected filters is outside the sealed snapshot facets.",
  RESEARCH_BACKEND_ERROR:
    "The research API rejected the screening request.",
  RESEARCH_BACKEND_UNAVAILABLE:
    "The research API was unavailable while creating the run.",
  RESEARCH_CONTRACT_ERROR:
    "The research API returned an unsupported response.",
};

function pageHref(options: {
  runId?: string;
  query?: string;
  cursor?: string;
}): string {
  const params = new URLSearchParams();
  if (options.runId) params.set("run", options.runId);
  if (options.query) params.set("query", options.query);
  if (options.cursor) params.set("cursor", options.cursor);
  const suffix = params.toString();
  return suffix ? `/research?${suffix}` : "/research";
}

function EmptyState({
  title,
  message,
}: {
  title: string;
  message: string;
}) {
  return (
    <section className="rounded-2xl border border-dashed border-slate-700 bg-slate-900/30 px-6 py-12 text-center">
      <p className="font-semibold text-slate-200">{title}</p>
      <p className="mx-auto mt-2 max-w-xl text-sm leading-6 text-slate-500">
        {message}
      </p>
    </section>
  );
}

function ResultCard({
  item,
  position,
}: {
  item: ProfileEnvelope;
  position: number;
}) {
  const longView = item.profile.horizons.find(
    (view) => view.horizon === "TWELVE_MONTHS_PLUS",
  )?.deterministicView;

  return (
    <article className="grid gap-5 rounded-2xl border border-slate-800 bg-slate-900/55 p-5 transition hover:border-slate-700 lg:grid-cols-[minmax(0,1.5fr)_minmax(170px,.65fr)_minmax(220px,.8fr)] lg:items-center">
      <div className="flex gap-4">
        <span className="mt-0.5 font-mono text-xs text-slate-600">
          {String(position).padStart(2, "0")}
        </span>
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <Link
              href={`/research/securities/${item.securityId}`}
              className="font-mono text-sm font-bold tracking-[0.08em] text-cyan-300 transition hover:text-cyan-200"
            >
              {item.profile.security.symbol}
            </Link>
            <StatusPill state={item.profile.rankingState} />
            <StatusPill state={item.profile.profileState} />
          </div>
          <p className="mt-2 truncate font-medium text-white">
            {item.profile.security.issuerName}
          </p>
          <p className="mt-1 truncate text-xs text-slate-500">
            {item.profile.classification
              ? `${item.profile.classification.sectorName} · ${item.profile.classification.industryName}`
              : "Classification missing"}
          </p>
        </div>
      </div>
      <div className="grid grid-cols-2 gap-4 border-y border-slate-800 py-4 lg:border-x lg:border-y-0 lg:px-5 lg:py-0">
        <div>
          <p className="text-[0.65rem] uppercase tracking-[0.13em] text-slate-600">
            Quality
          </p>
          <p className="mt-2 font-mono text-sm font-semibold text-slate-200">
            {formatScore(item.profile.objectiveQualityScore)}
          </p>
        </div>
        <div>
          <p className="text-[0.65rem] uppercase tracking-[0.13em] text-slate-600">
            12M+
          </p>
          <p className="mt-2 font-mono text-sm font-semibold text-slate-200">
            {formatScore(longView?.score ?? null)}
          </p>
        </div>
      </div>
      <MarketDataBlock
        market={item.currentMarketData}
        freshness={item.freshness}
        compact
      />
    </article>
  );
}

function SecurityCard({ item }: { item: SecuritySearchItem }) {
  const freshnessState =
    item.freshness.find((entry) => entry.state === "STALE")?.state ??
    item.currentMarketData.state;

  return (
    <article className="rounded-2xl border border-slate-800 bg-slate-900/50 p-5 transition hover:border-slate-700">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <Link
              href={`/research/securities/${item.securityId}`}
              className="font-mono text-base font-bold tracking-[0.08em] text-cyan-300 transition hover:text-cyan-200"
            >
              {item.symbol}
            </Link>
            <StatusPill state={item.membershipStatus} />
          </div>
          <p className="mt-2 truncate font-medium text-white">
            {item.issuerName}
          </p>
          <p className="mt-1 truncate text-xs text-slate-500">
            {item.exchangeMic} · {humanize(item.companyType)}
          </p>
        </div>
        <StatusPill state={freshnessState} />
      </div>
      <div className="mt-5 border-t border-slate-800 pt-4">
        <MarketDataBlock
          market={item.currentMarketData}
          freshness={item.freshness}
          compact
        />
      </div>
      <div className="mt-4 flex items-center justify-between gap-4 text-xs">
        <p className="truncate text-slate-500">
          {item.sector ?? "Sector missing"} ·{" "}
          {item.industry ?? "Industry missing"}
        </p>
        {item.latestProfileId ? (
          <Link
            href={`/research/profiles/${item.latestProfileId}`}
            className="shrink-0 font-semibold text-slate-300 hover:text-cyan-200"
          >
            Immutable profile
          </Link>
        ) : (
          <span className="shrink-0 text-amber-200/70">Profile missing</span>
        )}
      </div>
    </article>
  );
}

export default async function ResearchPage({
  searchParams,
}: {
  searchParams: Promise<Query>;
}) {
  const queryParams = await searchParams;
  const runId =
    single(queryParams.run) || getDefaultScreeningRunId() || undefined;
  const cursor = single(queryParams.cursor) || undefined;
  const query = single(queryParams.query).slice(0, 80);
  const notice = single(queryParams.notice);

  const [facetsResult, dataResult] = await Promise.all([
    loadResearchFacets(),
    runId
      ? loadScreeningResults(runId, cursor)
      : searchSecurities({ query, cursor, limit: 20 }),
  ]);

  return (
    <div className="space-y-8">
      <section className="grid gap-8 border-b border-slate-800 pb-8 lg:grid-cols-[1fr_auto] lg:items-end">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.2em] text-cyan-300">
            Explainable US equity research
          </p>
          <h1 className="mt-3 max-w-3xl text-3xl font-semibold tracking-tight text-white sm:text-5xl">
            Research evidence, without hidden judgment.
          </h1>
          <p className="mt-4 max-w-3xl text-base leading-7 text-slate-400">
            Screen a sealed daily snapshot, inspect deterministic horizon
            views, and trace every missing input. AI narrative stays separate
            and cannot affect rank.
          </p>
        </div>
        <div className="flex gap-6 text-right">
          <div>
            <p className="font-mono text-lg font-semibold text-white">
              Daily
            </p>
            <p className="text-xs text-slate-600">Data cadence</p>
          </div>
          <div>
            <p className="font-mono text-lg font-semibold text-white">Human</p>
            <p className="text-xs text-slate-600">Final decision</p>
          </div>
        </div>
      </section>

      {notice && notices[notice] && (
        <section
          role="status"
          className="rounded-2xl border border-amber-400/25 bg-amber-400/[0.07] px-5 py-4 text-sm text-amber-100/80"
        >
          {notices[notice]}
        </section>
      )}

      {facetsResult.ok ? (
        <section className="rounded-3xl border border-slate-800 bg-slate-900/50 p-5 shadow-2xl shadow-cyan-950/10 sm:p-6">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500">
                Screening configuration
              </p>
              <h2 className="mt-2 text-xl font-semibold text-white">
                Build an immutable research queue
              </h2>
            </div>
            <div className="text-right text-xs text-slate-600">
              <p>{facetsResult.data.universeVersion}</p>
              <p className="mt-1 font-mono">
                {facetsResult.data.dataSnapshotId}
              </p>
            </div>
          </div>
          <form action={runScreening} className="mt-6 grid gap-4 md:grid-cols-2 xl:grid-cols-7">
            <label className="grid gap-2 text-xs font-medium text-slate-400">
              Sector
              <select name="sector" className="research-control">
                <option value="">All sectors</option>
                {facetsResult.data.sectors.map((sector) => (
                  <option key={sector} value={sector}>
                    {humanize(sector)}
                  </option>
                ))}
              </select>
            </label>
            <label className="grid gap-2 text-xs font-medium text-slate-400">
              Industry
              <select name="industry" className="research-control">
                <option value="">All industries</option>
                {facetsResult.data.industries.map((industry) => (
                  <option key={industry} value={industry}>
                    {humanize(industry)}
                  </option>
                ))}
              </select>
            </label>
            <label className="grid gap-2 text-xs font-medium text-slate-400">
              Company type
              <select name="companyType" className="research-control">
                <option value="">All types</option>
                {facetsResult.data.companyTypes.map((type) => (
                  <option key={type} value={type}>
                    {humanize(type)}
                  </option>
                ))}
              </select>
            </label>
            <label className="grid gap-2 text-xs font-medium text-slate-400">
              Horizon
              <select
                name="horizon"
                defaultValue="TWELVE_MONTHS_PLUS"
                className="research-control"
              >
                <option value="ONE_WEEK">1 week</option>
                <option value="ONE_MONTH">1 month</option>
                <option value="THREE_MONTHS">3 months</option>
                <option value="TWELVE_MONTHS_PLUS">12 months+</option>
              </select>
            </label>
            <label className="grid gap-2 text-xs font-medium text-slate-400">
              Ranking status
              <select name="eligibility" className="research-control">
                <option value="ELIGIBLE_ONLY">Eligible only</option>
                <option value="INCLUDE_EXCLUDED">Include exclusions</option>
              </select>
            </label>
            <label className="grid gap-2 text-xs font-medium text-slate-400">
              Sort metric
              <select
                name="rankBy"
                defaultValue="BUYING_OPPORTUNITY"
                className="research-control"
              >
                <option value="BUYING_OPPORTUNITY">Buying opportunity</option>
                <option value="OBJECTIVE_QUALITY">Objective quality</option>
                <option value="OBJECTIVE_VALUATION">Objective valuation</option>
                <option value="TACTICAL_ONE_WEEK">Tactical 1W</option>
                <option value="TACTICAL_ONE_MONTH">Tactical 1M</option>
                <option value="TACTICAL_THREE_MONTHS">Tactical 3M</option>
                <option value="LONG_HORIZON">Long horizon</option>
              </select>
            </label>
            <div className="grid grid-cols-[1fr_auto] items-end gap-3">
              <label className="grid gap-2 text-xs font-medium text-slate-400">
                Order
                <select
                  name="direction"
                  defaultValue="DESCENDING"
                  className="research-control"
                >
                  <option value="DESCENDING">Highest first</option>
                  <option value="ASCENDING">Lowest first</option>
                </select>
              </label>
              <button
                type="submit"
                className="h-[42px] rounded-xl bg-cyan-300 px-4 text-xs font-bold text-slate-950 transition hover:bg-cyan-200 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-cyan-200"
              >
                Run
              </button>
            </div>
          </form>
          <p className="mt-4 text-xs leading-5 text-slate-600">
            A run is deterministic and sealed to the configured snapshot.
            Buying opportunity is a research ranking metric, not a trade
            instruction or expected return.
          </p>
        </section>
      ) : (
        <ErrorPanel
          error={facetsResult.error}
          title="Screening configuration is unavailable"
        />
      )}

      <section>
        <div className="mb-5 flex flex-wrap items-end justify-between gap-4">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500">
              {runId ? "Sealed screening run" : "Snapshot universe"}
            </p>
            <h2 className="mt-2 text-2xl font-semibold text-white">
              {runId ? "Ranked research queue" : "Security browser"}
            </h2>
          </div>
          {runId ? (
            <Link
              href="/research"
              className="rounded-full border border-slate-700 px-4 py-2 text-xs font-semibold text-slate-300 transition hover:border-slate-600 hover:bg-slate-900"
            >
              Browse full universe
            </Link>
          ) : (
            <form method="get" className="flex w-full max-w-md gap-2 sm:w-auto">
              <label className="sr-only" htmlFor="security-query">
                Search symbol or issuer
              </label>
              <input
                id="security-query"
                name="query"
                defaultValue={query}
                maxLength={80}
                placeholder="Search symbol or issuer"
                className="research-control min-w-0 flex-1 sm:w-72"
              />
              <button
                type="submit"
                className="rounded-xl border border-slate-700 px-4 text-xs font-semibold text-slate-200 transition hover:bg-slate-900"
              >
                Search
              </button>
            </form>
          )}
        </div>

        {!dataResult.ok ? (
          <ErrorPanel error={dataResult.error} />
        ) : isScreeningPage(dataResult.data) ? (
          <>
            <div className="mb-5 grid gap-3 rounded-2xl border border-slate-800 bg-slate-900/35 p-4 text-xs sm:grid-cols-2 lg:grid-cols-5">
              <div>
                <p className="text-slate-600">State</p>
                <div className="mt-2">
                  <StatusPill state={dataResult.data.run.state} />
                </div>
              </div>
              <div>
                <p className="text-slate-600">Rank metric</p>
                <p className="mt-2 text-slate-300">
                  {humanize(dataResult.data.run.rankBy)}
                </p>
              </div>
              <div>
                <p className="text-slate-600">Eligible</p>
                <p className="mt-2 font-mono text-slate-300">
                  {dataResult.data.run.eligibleCount}
                </p>
              </div>
              <div>
                <p className="text-slate-600">Excluded</p>
                <p className="mt-2 font-mono text-slate-300">
                  {dataResult.data.run.excludedCount}
                </p>
              </div>
              <div>
                <p className="text-slate-600">Sealed</p>
                <p className="mt-2 text-slate-300">
                  {formatTimestamp(dataResult.data.run.sealedAt)}
                </p>
              </div>
            </div>
            {dataResult.data.items.length === 0 ? (
              <EmptyState
                title="No ranking-eligible results"
                message="The sealed run retained explicit exclusions instead of fabricating neutral scores. Adjust the criteria only if a different research question is intended."
              />
            ) : (
              <div className="space-y-3">
                {dataResult.data.items.map((item, index) => (
                  <ResultCard
                    key={item.profileId}
                    item={item}
                    position={index + 1}
                  />
                ))}
              </div>
            )}
            <div className="mt-5 flex items-center justify-between gap-4">
              {cursor ? (
                <Link
                  href={pageHref({ runId })}
                  className="text-xs font-semibold text-slate-400 hover:text-cyan-200"
                >
                  First page
                </Link>
              ) : (
                <span />
              )}
              {dataResult.data.nextCursor && (
                <Link
                  href={pageHref({
                    runId,
                    cursor: dataResult.data.nextCursor,
                  })}
                  className="rounded-full border border-cyan-400/30 bg-cyan-400/10 px-4 py-2 text-xs font-semibold text-cyan-200 transition hover:bg-cyan-400/15"
                >
                  Next page
                </Link>
              )}
            </div>
          </>
        ) : (
          <>
            {dataResult.data.items.length === 0 ? (
              <EmptyState
                title="No securities found"
                message="No security in this sealed snapshot matched the query."
              />
            ) : (
              <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
                {dataResult.data.items.map((item) => (
                  <SecurityCard key={item.securityId} item={item} />
                ))}
              </div>
            )}
            <div className="mt-5 flex items-center justify-between gap-4">
              {cursor ? (
                <Link
                  href={pageHref({ query })}
                  className="text-xs font-semibold text-slate-400 hover:text-cyan-200"
                >
                  First page
                </Link>
              ) : (
                <span />
              )}
              {dataResult.data.nextCursor && (
                <Link
                  href={pageHref({
                    query,
                    cursor: dataResult.data.nextCursor,
                  })}
                  className="rounded-full border border-cyan-400/30 bg-cyan-400/10 px-4 py-2 text-xs font-semibold text-cyan-200 transition hover:bg-cyan-400/15"
                >
                  Next page
                </Link>
              )}
            </div>
          </>
        )}
      </section>
    </div>
  );
}
