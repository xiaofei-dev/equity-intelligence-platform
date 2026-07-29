export default function ResearchLoading() {
  return (
    <div aria-busy="true" aria-label="Loading research workspace" className="space-y-8">
      <div className="h-44 animate-pulse rounded-3xl bg-slate-900/70" />
      <div className="h-56 animate-pulse rounded-3xl bg-slate-900/70" />
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {[0, 1, 2, 3, 4, 5].map((item) => (
          <div
            key={item}
            className="h-48 animate-pulse rounded-2xl bg-slate-900/60"
          />
        ))}
      </div>
    </div>
  );
}
