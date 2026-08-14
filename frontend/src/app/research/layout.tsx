import Link from "next/link";

export default function ResearchLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      <header className="sticky top-0 z-20 border-b border-slate-800/90 bg-slate-950/88 backdrop-blur-xl">
        <div className="mx-auto flex h-16 max-w-[1500px] items-center justify-between gap-6 px-5 sm:px-8">
          <Link
            href="/research"
            className="flex items-center gap-3 focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-cyan-300"
          >
            <span className="grid h-8 w-8 place-items-center rounded-lg border border-cyan-300/25 bg-cyan-300/10 font-mono text-xs font-bold text-cyan-200">
              EI
            </span>
            <span>
              <span className="block text-sm font-semibold text-white">
                Equity Intelligence
              </span>
              <span className="block text-[0.62rem] uppercase tracking-[0.16em] text-slate-500">
                Research workspace
              </span>
            </span>
          </Link>
          <nav aria-label="Research navigation" className="flex items-center gap-2">
            <Link
              href="/portfolio"
              className="rounded-full px-3 py-1.5 text-xs font-semibold text-emerald-300 transition hover:bg-slate-900 hover:text-emerald-200"
            >
              Portfolio
            </Link>
            <Link
              href="/research/quant-trading"
              className="rounded-full px-3 py-1.5 text-xs font-semibold text-slate-500 transition hover:bg-slate-900 hover:text-violet-200"
            >
              Quant trading
            </Link>
            <Link
              href="/research/fundamental-value"
              className="rounded-full px-3 py-1.5 text-xs font-semibold text-slate-500 transition hover:bg-slate-900 hover:text-cyan-200"
            >
              Fundamental value
            </Link>
            <Link
              href="/research"
              className="rounded-full bg-slate-800 px-3 py-1.5 text-xs font-semibold text-slate-200 transition hover:bg-slate-700"
            >
              Screener
            </Link>
            <Link
              href="/market-data"
              className="hidden rounded-full px-3 py-1.5 text-xs font-semibold text-slate-500 transition hover:bg-slate-900 hover:text-slate-200 sm:block"
            >
              Market data
            </Link>
          </nav>
        </div>
      </header>
      <main className="mx-auto max-w-[1500px] px-5 py-8 sm:px-8 lg:py-10">
        {children}
      </main>
      <footer className="mx-auto max-w-[1500px] border-t border-slate-800 px-5 py-6 text-xs leading-5 text-slate-600 sm:px-8">
        Decision support only. No guaranteed returns, brokerage execution, or
        autonomous trade decisions. All portfolio actions remain under human
        control.
      </footer>
    </div>
  );
}
