import { humanize } from "@/lib/format";

const positive = new Set([
  "VALID",
  "ASSESSED",
  "COMPLETE",
  "ELIGIBLE",
  "AVAILABLE",
  "SEALED",
  "CURRENT",
  "READY",
]);
const caution = new Set([
  "MISSING",
  "STALE",
  "PARTIAL",
  "INSUFFICIENT_DATA",
  "INSUFFICIENT_EVIDENCE",
  "NOT_EXECUTED",
]);
const negative = new Set(["INVALID", "FAILED", "INELIGIBLE"]);

export function StatusPill({
  state,
  className = "",
}: {
  state: string;
  className?: string;
}) {
  const tone = positive.has(state)
    ? "border-emerald-400/25 bg-emerald-400/10 text-emerald-200"
    : caution.has(state)
      ? "border-amber-400/25 bg-amber-400/10 text-amber-200"
      : negative.has(state)
        ? "border-rose-400/25 bg-rose-400/10 text-rose-200"
        : "border-slate-600/60 bg-slate-800/70 text-slate-300";

  return (
    <span
      className={`inline-flex rounded-full border px-2.5 py-1 text-[0.68rem] font-semibold uppercase tracking-[0.12em] ${tone} ${className}`}
    >
      {humanize(state)}
    </span>
  );
}
