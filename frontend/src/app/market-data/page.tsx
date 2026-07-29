import Link from "next/link";

export const dynamic = "force-dynamic";

type MarketDataItem = {
  symbol: string;
  name: string;
  exchange: string;
  instrumentType: string;
  tradingDate: string | null;
  closePrice: number | null;
  volume: number | null;
  provider: string | null;
  ingestedAt: string | null;
};

type MarketDataResponse = {
  generatedAt: string;
  items: MarketDataItem[];
};

type MarketDataResult =
  | { state: "ready"; data: MarketDataResponse }
  | { state: "error"; message: string };

function decodeMarketData(value: unknown): MarketDataResponse {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error("Market data response must be an object.");
  }
  const source = value as Record<string, unknown>;
  if (
    typeof source.generatedAt !== "string" ||
    Number.isNaN(Date.parse(source.generatedAt)) ||
    !Array.isArray(source.items)
  ) {
    throw new Error("Market data response metadata is invalid.");
  }
  const items = source.items.map((item) => {
    if (typeof item !== "object" || item === null || Array.isArray(item)) {
      throw new Error("Market data item must be an object.");
    }
    const row = item as Record<string, unknown>;
    for (const key of ["symbol", "name", "exchange", "instrumentType"]) {
      if (typeof row[key] !== "string" || row[key].length === 0) {
        throw new Error(`Market data item ${key} is invalid.`);
      }
    }
    for (const key of ["closePrice", "volume"]) {
      if (
        row[key] !== null &&
        (typeof row[key] !== "number" || !Number.isFinite(row[key]))
      ) {
        throw new Error(`Market data item ${key} is invalid.`);
      }
    }
    for (const key of ["tradingDate", "provider", "ingestedAt"]) {
      if (row[key] !== null && typeof row[key] !== "string") {
        throw new Error(`Market data item ${key} is invalid.`);
      }
    }
    if (
      typeof row.ingestedAt === "string" &&
      Number.isNaN(Date.parse(row.ingestedAt))
    ) {
      throw new Error("Market data ingestion timestamp is invalid.");
    }
    return row as MarketDataItem;
  });
  return { generatedAt: source.generatedAt, items };
}

async function loadMarketData(): Promise<MarketDataResult> {
  const baseUrl = process.env.BACKEND_BASE_URL;
  if (!baseUrl) {
    return {
      state: "error",
      message: "BACKEND_BASE_URL is not configured on the server.",
    };
  }

  try {
    const url = new URL("/api/v1/market-data/latest", baseUrl);
    const response = await fetch(url, {
      cache: "no-store",
      signal: AbortSignal.timeout(10_000),
    });

    if (!response.ok) {
      return {
        state: "error",
        message: `Market data service returned HTTP ${response.status}.`,
      };
    }

    return {
      state: "ready",
      data: decodeMarketData(await response.json()),
    };
  } catch {
    return {
      state: "error",
      message: "The market data service is currently unavailable.",
    };
  }
}

const priceFormatter = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

const volumeFormatter = new Intl.NumberFormat("en-US");

const timestampFormatter = new Intl.DateTimeFormat("en-US", {
  dateStyle: "medium",
  timeStyle: "short",
  timeZone: "America/New_York",
});

export default async function MarketDataPage() {
  const result = await loadMarketData();

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      <main className="mx-auto min-h-screen max-w-6xl px-6 py-12 sm:px-10 lg:py-16">
        <header className="flex flex-wrap items-center justify-between gap-5 border-b border-slate-800 pb-6">
          <div>
            <Link
              href="/"
              className="text-sm text-slate-400 transition hover:text-cyan-300 focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-cyan-300"
            >
              ← Equity Intelligence
            </Link>
            <h1 className="mt-3 text-3xl font-semibold tracking-tight text-white sm:text-4xl">
              Daily market data
            </h1>
          </div>
          <span className="rounded-full border border-emerald-400/30 bg-emerald-400/10 px-3 py-1 text-xs font-medium text-emerald-300">
            Phase 1 · Live database
          </span>
        </header>

        <section className="py-10">
          <div className="mb-7 max-w-3xl">
            <p className="text-lg leading-8 text-slate-300">
              Latest stored daily observation for the initial engineering
              universe. This page reads PostgreSQL through the Java public API;
              it does not call the market data provider directly.
            </p>
          </div>

          {result.state === "error" ? (
            <div
              role="alert"
              className="rounded-2xl border border-rose-400/30 bg-rose-400/10 p-6"
            >
              <p className="font-medium text-rose-200">
                Market data is unavailable
              </p>
              <p className="mt-2 text-sm text-rose-100/70">{result.message}</p>
            </div>
          ) : result.data.items.length === 0 ? (
            <div className="rounded-2xl border border-amber-400/30 bg-amber-400/10 p-6">
              <p className="font-medium text-amber-200">
                No securities are configured
              </p>
              <p className="mt-2 text-sm text-amber-100/70">
                Run the database migrations and market data ingestion before
                returning to this page.
              </p>
            </div>
          ) : (
            <>
              <div className="overflow-hidden rounded-2xl border border-slate-800 bg-slate-900/60">
                <div className="overflow-x-auto">
                  <table className="w-full min-w-[850px] border-collapse text-left">
                    <thead className="bg-slate-900 text-xs uppercase tracking-[0.12em] text-slate-500">
                      <tr>
                        <th className="px-5 py-4 font-medium">Security</th>
                        <th className="px-5 py-4 font-medium">Trading date</th>
                        <th className="px-5 py-4 text-right font-medium">
                          Close
                        </th>
                        <th className="px-5 py-4 text-right font-medium">
                          Volume
                        </th>
                        <th className="px-5 py-4 font-medium">Source</th>
                        <th className="px-5 py-4 font-medium">Ingested</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-800">
                      {result.data.items.map((item) => (
                        <tr
                          key={item.symbol}
                          className="transition hover:bg-slate-800/40"
                        >
                          <td className="px-5 py-5">
                            <div className="font-semibold text-white">
                              {item.symbol}
                            </div>
                            <div className="mt-1 max-w-52 truncate text-xs text-slate-500">
                              {item.name} · {item.exchange}
                            </div>
                          </td>
                          {item.tradingDate !== null ? (
                            <>
                              <td className="px-5 py-5 text-sm text-slate-300">
                                {item.tradingDate}
                              </td>
                              <td className="px-5 py-5 text-right font-mono text-sm text-slate-100">
                                {item.closePrice === null
                                  ? "Missing"
                                  : priceFormatter.format(item.closePrice)}
                              </td>
                              <td className="px-5 py-5 text-right font-mono text-sm text-slate-300">
                                {item.volume === null
                                  ? "Missing"
                                  : volumeFormatter.format(item.volume)}
                              </td>
                              <td className="px-5 py-5 text-sm text-cyan-300">
                                {item.provider === null
                                  ? "Missing"
                                  : item.provider === "twelve_data"
                                  ? "Twelve Data"
                                  : item.provider}
                              </td>
                              <td className="px-5 py-5 text-sm text-slate-400">
                                {item.ingestedAt
                                  ? timestampFormatter.format(
                                      new Date(item.ingestedAt),
                                    )
                                  : "Not available"}
                              </td>
                            </>
                          ) : (
                            <td
                              colSpan={5}
                              className="px-5 py-5 text-sm text-amber-300"
                            >
                              No daily price has been ingested for this
                              security.
                            </td>
                          )}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>

              <div className="mt-5 flex flex-wrap justify-between gap-3 text-xs text-slate-500">
                <p>
                  {result.data.items.length} configured securities · Decision
                  support only
                </p>
                <p>
                  API response generated{" "}
                  {timestampFormatter.format(
                    new Date(result.data.generatedAt),
                  )}{" "}
                  ET
                </p>
              </div>
            </>
          )}
        </section>
      </main>
    </div>
  );
}
