import Link from "next/link";
import { CurrentFundamentalValueWorkspace } from "@/app/research/components/current-fundamental-value-workspace";
import { loadLatestCurrentFundamentalValueAssessment } from "@/lib/fundamental-value/current-backend";

export const dynamic = "force-dynamic";
type Query = Record<string, string | string[] | undefined>;

export default async function CurrentFundamentalValuePage({ searchParams }: { searchParams: Promise<Query> }) {
  const query = await searchParams;
  const symbol = typeof query.symbol === "string" ? query.symbol : "GOOG";
  const validSymbol = /^[A-Z][A-Z0-9.\-]{0,31}$/.test(symbol);
  const result = validSymbol ? await loadLatestCurrentFundamentalValueAssessment(symbol) : null;
  return <div className="space-y-7">
    <header className="flex flex-wrap items-end justify-between gap-5"><div><p className="text-xs font-semibold uppercase tracking-[0.2em] text-cyan-300/70">LONG_TERM_CORE / CURRENT REVISION</p><h1 className="mt-2 text-3xl font-semibold tracking-tight text-white">Current Fundamental Value assessment</h1><p className="mt-3 max-w-3xl text-sm leading-6 text-slate-400">Read-only immutable assessment through Spring. The browser never reaches Python, PostgreSQL, or a data provider directly.</p></div><Link href="/research/fundamental-value" className="text-xs font-semibold text-slate-400 hover:text-cyan-200">Historical decision workspace</Link></header>
    <section className="rounded-2xl border border-slate-800 bg-slate-900/45 p-5"><div className="flex flex-wrap items-center gap-3">{["GOOG", "FOX", "MSFT"].map((item) => <Link key={item} href={`/research/fundamental-value/current?symbol=${item}`} className={`rounded-full px-4 py-2 font-mono text-xs font-semibold ${symbol === item ? "bg-cyan-300 text-slate-950" : "bg-slate-800 text-slate-300 hover:bg-slate-700"}`}>{item}</Link>)}</div><form method="get" className="mt-5"><label htmlFor="symbol" className="text-xs font-semibold text-slate-300">Ticker</label><div className="mt-3 flex flex-col gap-3 sm:flex-row"><input id="symbol" name="symbol" defaultValue={symbol} placeholder="GOOG" className="research-control font-mono uppercase" autoComplete="off" spellCheck={false} /><button type="submit" className="rounded-xl bg-cyan-300 px-5 py-2.5 text-xs font-bold text-slate-950 transition hover:bg-cyan-200">Load latest sealed assessment</button></div></form></section>
    {!validSymbol && <section className="rounded-2xl border border-rose-400/20 bg-rose-400/5 p-5 text-sm text-rose-100">Use an uppercase US-equity ticker such as GOOG, FOX, or MSFT.</section>}
    {result && !result.ok && validSymbol && <section className="rounded-2xl border border-amber-300/20 bg-amber-300/5 p-5"><p className="font-semibold text-amber-100">Assessment unavailable</p><p className="mt-2 text-sm text-slate-400">{result.error.message}</p><p className="mt-2 font-mono text-xs text-slate-600">{result.error.code}</p></section>}
    {result?.ok && <CurrentFundamentalValueWorkspace assessment={result.data} />}
  </div>;
}
