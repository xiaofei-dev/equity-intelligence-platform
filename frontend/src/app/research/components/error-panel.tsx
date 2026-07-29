import type { BackendError } from "@/lib/market-intelligence/backend";

export function ErrorPanel({
  error,
  title = "Research data is unavailable",
}: {
  error: BackendError;
  title?: string;
}) {
  return (
    <section
      role="alert"
      className="rounded-2xl border border-rose-400/25 bg-rose-400/[0.07] p-6"
    >
      <p className="text-sm font-semibold text-rose-100">{title}</p>
      <p className="mt-2 max-w-3xl text-sm leading-6 text-rose-100/70">
        {error.message}
      </p>
      <p className="mt-4 font-mono text-[0.68rem] uppercase tracking-[0.12em] text-rose-300/70">
        {error.code}
        {error.status ? ` · HTTP ${error.status}` : ""}
      </p>
    </section>
  );
}
