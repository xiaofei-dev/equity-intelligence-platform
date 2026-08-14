import Link from "next/link";
import { loadQuantResearchDecision } from "@/lib/quant-trading/backend";
import { isCanonicalQuantDecisionId } from "@/lib/quant-trading/contracts";
import { QuantResearchWorkspace } from "../components/quant-research-workspace";

export const dynamic = "force-dynamic";
type Query = Record<string, string | string[] | undefined>;

export default async function QuantTradingPage({ searchParams }: { searchParams: Promise<Query> }) {
  const query = await searchParams; const decisionId = typeof query.decisionId === "string" ? query.decisionId : "";
  const result = decisionId ? await loadQuantResearchDecision(decisionId) : null;
  return <div className="space-y-7">
    <header className="flex flex-wrap items-end justify-between gap-5"><div><p className="text-xs font-semibold uppercase tracking-[0.2em] text-violet-300/70">QUANT_TRADING</p><h1 className="mt-2 text-3xl font-semibold tracking-tight text-white">Quant research workspace</h1><p className="mt-3 max-w-3xl text-sm leading-6 text-slate-400">Immutable Quant v1.1 research signals with entry-price and exit-review context. This is a separate trading sleeve, not Fundamental Value analysis.</p></div><Link href="/research" className="text-xs font-semibold text-slate-400 hover:text-violet-200">Back to research</Link></header>
    <form method="get" className="rounded-2xl border border-slate-800 bg-slate-900/45 p-5"><label htmlFor="decisionId" className="text-xs font-semibold text-slate-300">Immutable decision ID</label><div className="mt-3 flex flex-col gap-3 sm:flex-row"><input id="decisionId" name="decisionId" defaultValue={decisionId} placeholder="00000000-0000-4000-8000-000000000000" className="research-control font-mono" autoComplete="off" spellCheck={false} /><button type="submit" className="rounded-xl bg-violet-300 px-5 py-2.5 text-xs font-bold text-slate-950 transition hover:bg-violet-200">Load signal snapshot</button></div><p className="mt-3 text-xs text-slate-600">The browser reads Spring only. It cannot place orders or choose final portfolio weights.</p></form>
    {!decisionId && <section className="rounded-2xl border border-dashed border-slate-700 bg-slate-900/25 px-6 py-12 text-center"><p className="font-semibold text-slate-200">Enter a sealed Quant decision ID</p><p className="mt-2 text-sm text-slate-500">Signals are calculated and persisted by the analytics workflow before this page can display them.</p></section>}
    {decisionId && !isCanonicalQuantDecisionId(decisionId) && <section className="rounded-2xl border border-rose-400/20 bg-rose-400/5 p-5 text-sm text-rose-100">The decision ID must be a canonical lowercase UUID.</section>}
    {result && !result.ok && isCanonicalQuantDecisionId(decisionId) && <section className="rounded-2xl border border-amber-300/20 bg-amber-300/5 p-5"><p className="font-semibold text-amber-100">Signal snapshot unavailable</p><p className="mt-2 text-sm text-slate-400">{result.error.message}</p><p className="mt-2 font-mono text-xs text-slate-600">{result.error.code}{result.error.status ? ` / HTTP ${result.error.status}` : ""}</p></section>}
    {result?.ok && <QuantResearchWorkspace decision={result.data} />}
	</div>;
}
