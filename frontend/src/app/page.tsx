import Link from "next/link";

export default function Home() {
  const services = [
    {
      name: "Research workspace",
      description:
        "Review candidates, factor contributions, evidence, and unresolved risks in one place.",
      status: "Foundation",
    },
    {
      name: "Analytics service",
      description:
        "Run reproducible screening, backtesting, and structured AI-assisted research.",
      status: "Foundation",
    },
    {
      name: "Portfolio support",
      description:
        "Record human decisions and evaluate simulated portfolios against explicit constraints.",
      status: "Planned",
    },
  ];

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      <main className="mx-auto flex min-h-screen max-w-6xl flex-col px-6 py-12 sm:px-10 lg:py-20">
        <header className="flex items-center justify-between border-b border-slate-800 pb-6">
          <p className="text-sm font-semibold uppercase tracking-[0.24em] text-cyan-300">
            Equity Intelligence
          </p>
          <span className="rounded-full border border-emerald-400/30 bg-emerald-400/10 px-3 py-1 text-xs font-medium text-emerald-300">
            Phase 0
          </span>
        </header>

        <section className="grid flex-1 items-center gap-12 py-16 lg:grid-cols-[1.2fr_0.8fr]">
          <div>
            <p className="mb-5 text-sm font-medium text-slate-400">
              Explainable research. Reproducible decisions. Explicit risk.
            </p>
            <h1 className="max-w-3xl text-4xl font-semibold tracking-tight text-white sm:text-6xl">
              A disciplined foundation for equity research.
            </h1>
            <p className="mt-7 max-w-2xl text-lg leading-8 text-slate-300">
              The platform combines deterministic analysis, evidence-based AI
              review, and human-controlled portfolio decisions. It does not
              promise returns or execute real-money trades.
            </p>

            <div className="mt-9 flex flex-wrap items-center gap-3 text-sm">
              <Link
                href="/market-data"
                className="rounded-full border border-cyan-400/50 bg-cyan-400/10 px-4 py-2 font-medium text-cyan-200 transition hover:border-cyan-300 hover:bg-cyan-400/20 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-cyan-300"
              >
                View daily data →
              </Link>
              {[
                "Source citations",
                "Versioned strategies",
                "Simulated portfolios",
              ].map((item) => (
                <span
                  key={item}
                  className="rounded-full border border-slate-800 px-4 py-2 text-slate-500"
                >
                  {item} · Planned
                </span>
              ))}
            </div>
          </div>

          <aside className="rounded-3xl border border-slate-800 bg-slate-900/70 p-6 shadow-2xl shadow-cyan-950/20">
            <p className="text-xs font-semibold uppercase tracking-[0.2em] text-slate-500">
              Foundation status
            </p>
            <div className="mt-6 space-y-5">
              {services.map((service) => (
                <article
                  key={service.name}
                  className="border-b border-slate-800 pb-5 last:border-0 last:pb-0"
                >
                  <div className="flex items-center justify-between gap-4">
                    <h2 className="font-medium text-white">{service.name}</h2>
                    <span className="text-xs text-cyan-300">{service.status}</span>
                  </div>
                  <p className="mt-2 text-sm leading-6 text-slate-400">
                    {service.description}
                  </p>
                </article>
              ))}
            </div>
          </aside>
        </section>

        <footer className="border-t border-slate-800 pt-6 text-sm text-slate-500">
          Decision support only. All portfolio actions remain under human
          control.
        </footer>
      </main>
    </div>
  );
}
