import { formatCurrency, formatTimestamp, humanize } from "@/lib/format";
import type {
  CurrentMarketData,
  DatasetFreshness,
} from "@/lib/market-intelligence/contracts";
import { StatusPill } from "./status-pill";

export function MarketDataBlock({
  market,
  freshness,
  compact = false,
}: {
  market: CurrentMarketData;
  freshness: DatasetFreshness[];
  compact?: boolean;
}) {
  const stale = freshness.filter((item) => item.state === "STALE");

  if (compact) {
    return (
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="font-mono text-lg font-semibold text-white">
            {formatCurrency(market.price, market.currency)}
          </p>
          <p className="mt-1 text-xs text-slate-500">
            {market.tradingDate ?? humanize(market.reason ?? market.state)}
          </p>
        </div>
        <StatusPill state={stale.length > 0 ? "STALE" : market.state} />
      </div>
    );
  }

  return (
    <section className="rounded-2xl border border-slate-800 bg-slate-900/55 p-5">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500">
            Current market observation
          </p>
          <p className="mt-3 font-mono text-3xl font-semibold tracking-tight text-white">
            {formatCurrency(market.price, market.currency)}
          </p>
          <p className="mt-1 text-sm text-slate-400">
            {market.tradingDate
              ? `Trading session ${market.tradingDate}`
              : "Trading date unavailable"}
          </p>
        </div>
        <StatusPill state={market.state} />
      </div>

      {market.reason && (
        <p className="mt-5 rounded-xl border border-amber-400/20 bg-amber-400/[0.07] px-4 py-3 text-sm text-amber-100/80">
          {humanize(market.reason)}
        </p>
      )}

      <dl className="mt-5 grid gap-4 border-t border-slate-800 pt-5 text-sm sm:grid-cols-2">
        <div>
          <dt className="text-slate-500">Provider</dt>
          <dd className="mt-1 text-slate-200">
            {market.providerCode ?? "Not available"}
          </dd>
        </div>
        <div>
          <dt className="text-slate-500">Adjustment</dt>
          <dd className="mt-1 text-slate-200">
            {market.adjustmentMode
              ? humanize(market.adjustmentMode)
              : "Not available"}
          </dd>
        </div>
        <div>
          <dt className="text-slate-500">Available to the system</dt>
          <dd className="mt-1 text-slate-200">
            {formatTimestamp(market.availableAt)}
          </dd>
        </div>
        <div>
          <dt className="text-slate-500">Ingested</dt>
          <dd className="mt-1 text-slate-200">
            {formatTimestamp(market.ingestedAt)}
          </dd>
        </div>
      </dl>
    </section>
  );
}
