import Link from "next/link";
import { loadLatestPortfolioContext } from "@/lib/portfolio-context/backend";
import { isCanonicalPortfolioId } from "@/lib/portfolio-context/contracts";
import { PortfolioWorkspace } from "./portfolio-workspace";
import { loadOnboardingInventory } from "@/lib/portfolio-onboarding/backend";
import { OnboardingSummary } from "./onboarding-summary";
import { OnboardingWorkspace } from "./onboarding-workspace";
import { loadPortfolioDecisionScenarios } from "@/lib/portfolio-decision/backend";
import { DecisionScenarios } from "./decision-scenarios";
import { loadLatestPortfolioEvaluations } from "@/lib/portfolio-decision/evaluations";
import { EvaluationWorkspace } from "./evaluation-workspace";
import { DecisionWorkflow } from "./decision-workflow";
import { loadV32 } from "@/lib/portfolio-decision/v32";
import { V32Workspace } from "./v32-workspace";

export const dynamic = "force-dynamic";
type Query = Record<string, string | string[] | undefined>;

export default async function PortfolioPage({ searchParams }: { searchParams: Promise<Query> }) {
  const query = await searchParams; const portfolioId = typeof query.portfolioId === "string" ? query.portfolioId : ""; const workflowStatus = typeof query.workflowStatus === "string" ? query.workflowStatus : undefined; const contextId = typeof query.contextId === "string" ? query.contextId : undefined; const evidenceManifestId = typeof query.evidenceManifestId === "string" ? query.evidenceManifestId : undefined;
  const [result, inventory, scenarios, evaluations] = await Promise.all([portfolioId ? loadLatestPortfolioContext(portfolioId) : Promise.resolve(null), loadOnboardingInventory(), portfolioId && isCanonicalPortfolioId(portfolioId) ? loadPortfolioDecisionScenarios(portfolioId) : Promise.resolve(null), portfolioId && isCanonicalPortfolioId(portfolioId) ? loadLatestPortfolioEvaluations(portfolioId) : Promise.resolve(null)]);
  const v32 = portfolioId && isCanonicalPortfolioId(portfolioId) ? await loadV32(portfolioId, evaluations?.ok ? evaluations.data : []) : null;
  return <main className="min-h-screen bg-slate-950 px-5 py-8 text-slate-100 sm:px-8"><div className="mx-auto max-w-[1500px] space-y-7">
    <header className="flex flex-wrap items-end justify-between gap-5"><div><p className="text-xs font-semibold uppercase tracking-[0.2em] text-emerald-300/70">Unified Portfolio & Risk Context v1</p><h1 className="mt-2 text-3xl font-semibold tracking-tight text-white">Portfolio command center</h1><p className="mt-3 max-w-3xl text-sm leading-6 text-slate-400">One human-controlled view of holdings, cash, liabilities, concentration risk, and the two independent research sleeves.</p></div><nav className="flex gap-3 text-xs font-semibold"><Link href="/research/fundamental-value" className="text-cyan-200 hover:text-cyan-100">Fundamental value</Link><Link href="/research/quant-trading" className="text-violet-200 hover:text-violet-100">Quant research</Link></nav></header>
    <OnboardingSummary inventory={inventory}/>
    <OnboardingWorkspace inventory={inventory}/>
    <form method="get" className="rounded-2xl border border-slate-800 bg-slate-900/45 p-5"><label htmlFor="portfolioId" className="text-xs font-semibold text-slate-300">Portfolio ID</label><div className="mt-3 flex flex-col gap-3 sm:flex-row"><input id="portfolioId" name="portfolioId" defaultValue={portfolioId} placeholder="00000000-0000-4000-8000-000000000000" className="research-control font-mono" autoComplete="off" spellCheck={false}/><button type="submit" className="rounded-xl bg-emerald-300 px-5 py-2.5 text-xs font-bold text-slate-950 hover:bg-emerald-200">Load latest context</button></div></form>
    {!portfolioId && <section className="rounded-2xl border border-dashed border-slate-700 bg-slate-900/25 px-6 py-12 text-center"><p className="font-semibold text-slate-200">Enter a portfolio ID</p><p className="mt-2 text-sm text-slate-500">The page reads the latest sealed V28 context from Spring Boot.</p></section>}
    {portfolioId && !isCanonicalPortfolioId(portfolioId) && <section className="rounded-2xl border border-rose-400/20 bg-rose-400/5 p-5 text-sm text-rose-100">The portfolio ID must be a canonical lowercase UUID.</section>}
    {result && !result.ok && isCanonicalPortfolioId(portfolioId) && <section className="rounded-2xl border border-amber-300/20 bg-amber-300/5 p-5"><p className="font-semibold text-amber-100">Portfolio context unavailable</p><p className="mt-2 text-sm text-slate-400">{result.error.message}</p><p className="mt-2 font-mono text-xs text-slate-600">{result.error.code}</p></section>}
    {result?.ok && <PortfolioWorkspace context={result.data}/>}
    {isCanonicalPortfolioId(portfolioId) && <DecisionWorkflow portfolioId={portfolioId} context={result?.ok ? result.data : null} scenarios={scenarios} comparison={v32?.ok ? v32.comparison : null} workflowStatus={workflowStatus} contextId={contextId} evidenceManifestId={evidenceManifestId}/>}
    {result?.ok && <DecisionScenarios result={scenarios} portfolioId={portfolioId}/>}
    {isCanonicalPortfolioId(portfolioId) && <EvaluationWorkspace result={evaluations}/>}
    {isCanonicalPortfolioId(portfolioId) && <V32Workspace result={v32}/>}
    <footer className="border-t border-slate-800 pt-6 text-xs leading-5 text-slate-600">Decision support only. No final weights, order authority, brokerage execution, or autonomous AI decisions.</footer>
  </div></main>;
}
