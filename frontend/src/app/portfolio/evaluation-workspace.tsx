


import type { PortfolioEvaluationResult } from "@/lib/portfolio-decision/evaluations";

export function EvaluationWorkspace({ result }: { result: PortfolioEvaluationResult | null }) {
  if (!result) return null;
  if (!result.ok) return <section className="rounded-2xl border border-amber-300/20 bg-amber-300/5 p-5"><h2 className="font-semibold text-amber-100">Simulation evaluation unavailable</h2><p className="mt-2 text-sm text-slate-400">{result.error}</p></section>;
  return <section className="space-y-4">
    <div><p className="text-xs font-semibold uppercase tracking-[0.16em] text-cyan-300/70">Longitudinal evaluation v1</p><h2 className="mt-2 text-xl font-semibold text-white">Simulation only tracking</h2><p className="mt-2 text-sm text-slate-400">Human-accepted scenarios are compared with HOLD_CURRENT and SPY over server-controlled natural maturities. Results include costs and incomplete coverage; this is not a brokerage action, a guarantee, or proof of future returns.</p></div>
    {result.data.length === 0 ? <p className="rounded-xl border border-dashed border-slate-700 p-4 text-sm text-slate-500">No decision scenario is available for evaluation.</p> : <div className="space-y-4">{result.data.map((item) => <article key={item.scenarioId} className="rounded-xl border border-slate-800 bg-slate-900/40 p-4">
      <div className="flex flex-wrap items-start justify-between gap-3"><div><p className="text-xs font-semibold text-slate-400">{item.scenarioType}</p><p className="mt-2 font-semibold text-cyan-100">{item.evaluation?.state.replaceAll("_", " ") ?? "Not enrolled"}</p></div>{item.evaluation && <span className="rounded-full bg-cyan-300/10 px-3 py-1 text-xs font-semibold text-cyan-100">HOLD + SPY / SIMULATED</span>}</div>
      {item.evaluation ? <><div className="mt-4 grid gap-2 sm:grid-cols-5">{item.evaluation.maturities.map((maturity) => <div key={maturity.horizonSessions} className="rounded-lg border border-slate-800 p-3"><p className="text-xs font-semibold text-white">{maturity.horizonSessions} sessions</p><p className="mt-1 text-[0.65rem] text-slate-400">{maturity.state.replaceAll("_", " ")}</p>{maturity.terminalReason && <p className="mt-1 text-[0.65rem] text-amber-100">{maturity.terminalReason}</p>}</div>)}</div>
        {item.evaluation.summaries.length === 0 ? <p className="mt-4 text-sm text-slate-500">No matured period summary is available yet.</p> : <div className="mt-4 overflow-x-auto"><table className="w-full min-w-[1180px] text-left text-xs"><thead className="text-slate-500"><tr><th className="py-2">Period</th><th>Gross TWR</th><th>Net TWR</th><th>HOLD TWR</th><th>vs HOLD</th><th>SPY</th><th>vs SPY</th><th>Max drawdown</th><th>Turnover</th><th>Costs</th><th>Coverage</th></tr></thead><tbody>{item.evaluation.summaries.map((summary) => <tr key={`${summary.periodStart}-${summary.periodEnd}`} className="border-t border-slate-800"><td className="py-2">{summary.periodStart} to {summary.periodEnd}</td><td>{nullablePercentage(summary.grossReturn)}</td><td>{percentage(summary.netReturn)}</td><td>{percentage(summary.holdCurrentReturn)}</td><td>{percentage(summary.acceptedExcessVsHoldCurrent)}</td><td>{percentage(summary.benchmarkReturn)}</td><td>{percentage(summary.excessReturn)}</td><td>{nullablePercentage(summary.maximumDrawdown)}</td><td>{percentage(summary.totalTurnover)}</td><td>{money(summary.totalCost)}</td><td>{summary.observationCount}/{summary.expectedObservationCount} ({percentage(summary.coverageRate)})</td></tr>)}</tbody></table></div>}
        <p className="mt-3 break-all font-mono text-[0.65rem] text-slate-600">{item.evaluation.evaluationId}</p></> : <p className="mt-3 text-xs text-slate-500">A qualifying human decision and a server-derived completed entry session are required before Spring can create an evaluation.</p>}
    </article>)}</div>}
  </section>;
}

function nullablePercentage(value: string | null) { return value === null ? "NOT OBSERVED" : percentage(value); }
function percentage(value: string) { return `${(Number(value) * 100).toFixed(2)}%`; }
function money(value: string) { return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(Number(value)); }
