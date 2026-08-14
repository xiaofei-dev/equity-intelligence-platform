import Link from "next/link";
import { loadFundamentalValueDecision } from "@/lib/fundamental-value/backend";
import { isCanonicalUuid } from "@/lib/fundamental-value/contracts";
import { FundamentalValueWorkspace } from "../components/fundamental-value-workspace";

export const dynamic = "force-dynamic";

type Query = Record<string, string | string[] | undefined>;

export default async function FundamentalValuePage({ searchParams }: { searchParams: Promise<Query> }) {
  const query = await searchParams;
  const assemblyId = typeof query.assemblyId === "string" ? query.assemblyId : "";
  const result = assemblyId ? await loadFundamentalValueDecision(assemblyId) : null;
  return (
    <div className="space-y-7">
      <header className="flex flex-wrap items-end justify-between gap-5"><div><p className="text-xs font-semibold uppercase tracking-[0.2em] text-cyan-300/70">LONG_TERM_CORE</p><h1 className="mt-2 text-3xl font-semibold tracking-tight text-white">Fundamental Value workspace</h1><p className="mt-3 max-w-3xl text-sm leading-6 text-slate-400">Immutable deterministic decision readback through the Spring public API. Mature-company evidence gaps and specialized routing remain explicit.</p></div><div className="flex gap-4"><Link href="/research/fundamental-value/current" className="text-xs font-semibold text-cyan-200 hover:text-cyan-100">Current assessment</Link><Link href="/research" className="text-xs font-semibold text-slate-400 hover:text-cyan-200">Back to research</Link></div></header>
      <form method="get" className="rounded-2xl border border-slate-800 bg-slate-900/45 p-5"><label htmlFor="assemblyId" className="text-xs font-semibold text-slate-300">Immutable assembly ID</label><div className="mt-3 flex flex-col gap-3 sm:flex-row"><input id="assemblyId" name="assemblyId" defaultValue={assemblyId} placeholder="00000000-0000-4000-8000-000000000000" className="research-control font-mono" autoComplete="off" spellCheck={false} /><button type="submit" className="rounded-xl bg-cyan-300 px-5 py-2.5 text-xs font-bold text-slate-950 transition hover:bg-cyan-200">Load decision</button></div><p className="mt-3 text-xs text-slate-600">The browser never calls Python, PostgreSQL, or a market-data provider.</p></form>
      {!assemblyId && <section className="rounded-2xl border border-dashed border-slate-700 bg-slate-900/25 px-6 py-12 text-center"><p className="font-semibold text-slate-200">Enter a sealed assembly ID</p><p className="mt-2 text-sm text-slate-500">The workspace displays existing Spring-owned workflow output and does not calculate or manufacture an assessment.</p></section>}
      {assemblyId && !isCanonicalUuid(assemblyId) && <section className="rounded-2xl border border-rose-400/20 bg-rose-400/5 p-5 text-sm text-rose-100">The assembly ID must be a canonical lowercase hyphenated UUID.</section>}
      {result && !result.ok && isCanonicalUuid(assemblyId) && <section className="rounded-2xl border border-amber-300/20 bg-amber-300/5 p-5"><p className="font-semibold text-amber-100">Decision unavailable</p><p className="mt-2 text-sm text-slate-400">{result.error.message}</p><p className="mt-2 font-mono text-xs text-slate-600">{result.error.code}{result.error.status ? ` · HTTP ${result.error.status}` : ""}</p></section>}
      {result?.ok && <FundamentalValueWorkspace decision={result.data} />}
    </div>
  );
}
