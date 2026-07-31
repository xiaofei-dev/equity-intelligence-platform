import { formatTimestamp, humanize } from "@/lib/format";
import type { ProspectiveEnrollment } from "@/lib/forward-validation/contracts";
import type { ForwardValidationResult } from "@/lib/forward-validation/transport";
import { StatusPill } from "./status-pill";

const horizonLabels = {
  ONE_WEEK: "1W model horizon",
  ONE_MONTH: "1M model horizon",
  THREE_MONTHS: "3M model horizon",
} as const;

function statusSummary(status: ProspectiveEnrollment["status"]): string {
  if (status === "ENROLLED") {
    return "Prospective shadow observation is sealed. No outcome yet.";
  }
  if (status === "NO_ELIGIBLE_SIGNALS") {
    return "No eligible signals were available. Prospective outcomes are not applicable.";
  }
  return "The prospective attempt is blocked. No outcome observation was started.";
}

function countCards(enrollment: ProspectiveEnrollment) {
  return [
    ["Profiles", enrollment.profileCount],
    ["Eligible", enrollment.eligibleCount],
    ["Excluded", enrollment.excludedCount],
    ["Signals", enrollment.signalCount],
  ] as const;
}

export function ProspectiveEnrollmentPanel({
  result,
}: {
  result: ForwardValidationResult<ProspectiveEnrollment | null>;
}) {
  if (!result.ok) {
    return (
      <section
        aria-labelledby="prospective-enrollment-title"
        className="rounded-3xl border border-rose-400/20 bg-rose-400/[0.045] p-5 sm:p-6"
      >
        <p className="text-xs font-semibold uppercase tracking-[0.16em] text-rose-300">
          Forward observation
        </p>
        <h2
          id="prospective-enrollment-title"
          className="mt-2 text-xl font-semibold text-white"
        >
          Prospective status is unavailable
        </h2>
        <p className="mt-3 max-w-3xl text-sm leading-6 text-rose-100/70">
          {result.error.message}
        </p>
        <p className="mt-4 font-mono text-[0.68rem] uppercase tracking-[0.12em] text-rose-300/70">
          {result.error.code}
          {result.error.status ? ` - HTTP ${result.error.status}` : ""}
        </p>
      </section>
    );
  }

  if (result.data === null) {
    return (
      <section
        aria-labelledby="prospective-enrollment-title"
        className="rounded-3xl border border-slate-800 bg-slate-900/45 p-5 sm:p-6"
      >
        <p className="text-xs font-semibold uppercase tracking-[0.16em] text-cyan-300">
          Forward observation
        </p>
        <h2
          id="prospective-enrollment-title"
          className="mt-2 text-xl font-semibold text-white"
        >
          No prospective attempt yet
        </h2>
        <p className="mt-3 max-w-3xl text-sm leading-6 text-slate-400">
          No sealed prospective shadow observation is available. There is no
          outcome to report and no trade instruction.
        </p>
      </section>
    );
  }

  const enrollment = result.data;

  return (
    <section
      aria-labelledby="prospective-enrollment-title"
      className="overflow-hidden rounded-3xl border border-cyan-400/20 bg-[linear-gradient(135deg,rgba(15,23,42,.92),rgba(8,47,73,.28))]"
    >
      <div className="grid gap-6 p-5 sm:p-6 lg:grid-cols-[1fr_auto] lg:items-start">
        <div>
          <div className="flex flex-wrap items-center gap-3">
            <p className="text-xs font-semibold uppercase tracking-[0.16em] text-cyan-300">
              Forward observation
            </p>
            <StatusPill state={enrollment.status} />
          </div>
          <h2
            id="prospective-enrollment-title"
            className="mt-3 text-2xl font-semibold text-white"
          >
            Prospective enrollment status
          </h2>
          <p className="mt-3 max-w-3xl text-sm leading-6 text-slate-300">
            {statusSummary(enrollment.status)}
          </p>
          <p className="mt-2 max-w-3xl text-sm leading-6 text-cyan-100/65">
            Prospective shadow observation. No outcome yet. Not a trade
            instruction.
          </p>
        </div>
        <div className="text-left text-xs text-slate-500 lg:text-right">
          <p>Decision as of</p>
          <p className="mt-1 font-mono text-slate-300">
            {formatTimestamp(enrollment.decisionAsOf)}
          </p>
          <p className="mt-2 font-mono text-[0.65rem] text-slate-600">
            Attempt {enrollment.attemptId}
          </p>
        </div>
      </div>

      <div className="grid grid-cols-2 border-y border-slate-800/90 sm:grid-cols-4">
        {countCards(enrollment).map(([label, value]) => (
          <div
            key={label}
            className="border-slate-800/90 p-4 even:border-l sm:border-l sm:first:border-l-0"
          >
            <p className="text-[0.68rem] uppercase tracking-[0.12em] text-slate-600">
              {label}
            </p>
            <p className="mt-2 font-mono text-xl font-semibold text-white">
              {value}
            </p>
          </div>
        ))}
      </div>

      {(enrollment.status === "BLOCKED" ||
        enrollment.status === "NO_ELIGIBLE_SIGNALS") && (
        <div className="border-b border-slate-800/90 bg-amber-400/[0.035] p-5 sm:p-6">
          <div className="flex flex-wrap items-center gap-3">
            <StatusPill state={enrollment.status} />
            <p className="text-sm font-semibold text-amber-100">
              {enrollment.status === "BLOCKED"
                ? "Observation blocked"
                : "No eligible signals"}
            </p>
          </div>
          {enrollment.blockedReasons.length > 0 ? (
            <ul className="mt-3 space-y-2 text-sm text-amber-100/70">
              {enrollment.blockedReasons.map((reason) => (
                <li key={reason}>- {humanize(reason)}</li>
              ))}
            </ul>
          ) : (
            <p className="mt-3 text-sm text-amber-100/70">
              The sealed decision contained no eligible signals.
            </p>
          )}
        </div>
      )}

      <div className="p-5 sm:p-6">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500">
              Prospective outcome schedule
            </p>
            <h3 className="mt-2 text-lg font-semibold text-white">
              Frozen 5, 20, and 60 trading-day checkpoints
            </h3>
          </div>
          <p className="text-xs text-slate-500">
            Model horizons are context, not realized outcomes
          </p>
        </div>
        <div className="mt-4 grid gap-3 md:grid-cols-3">
          {enrollment.maturitySchedule.map((item) => (
            <article
              key={item.horizon}
              className="rounded-xl border border-slate-800 bg-slate-950/45 p-4"
            >
              <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="font-mono text-sm font-semibold text-cyan-300">
                  {item.tradingDays} trading days
                </p>
                <StatusPill state={item.status} />
              </div>
              <p className="mt-3 text-xs font-medium text-slate-400">
                {horizonLabels[item.horizon]}
              </p>
              <p className="mt-2 text-xs leading-5 text-slate-600">
                Prospective checkpoint: {formatTimestamp(item.maturesOn)}
              </p>
              <p className="mt-2 text-xs leading-5 text-slate-500">
                {item.status === "NOT_MATURED"
                  ? "No prospective outcome yet."
                  : "Not applicable because no shadow outcome episode started."}
              </p>
            </article>
          ))}
        </div>
        <p className="mt-4 text-xs leading-5 text-slate-500">
          The 1W, 1M, and 3M labels identify frozen model horizons. The 5, 20,
          and 60 trading-day checkpoints identify when separate prospective
          observations can mature; they are not return forecasts. The
          long-horizon model is context only.
        </p>
      </div>

      <details className="group border-t border-slate-800/90">
        <summary className="cursor-pointer list-none px-5 py-4 text-sm font-semibold text-slate-300 transition hover:bg-slate-900/40 sm:px-6">
          Decision details and exclusions ({enrollment.decisions.length})
          <span className="ml-2 text-slate-600 group-open:hidden">
            Show
          </span>
          <span className="ml-2 hidden text-slate-600 group-open:inline">
            Hide
          </span>
        </summary>
        <ul className="divide-y divide-slate-800/80 border-t border-slate-800/90">
          {enrollment.decisions.map((decision) => (
            <li
              key={decision.profileId}
              className="grid gap-3 px-5 py-4 sm:grid-cols-[9rem_8rem_1fr] sm:px-6"
            >
              <p className="font-mono text-sm font-semibold text-cyan-300">
                {decision.symbol}
              </p>
              <div>
                <StatusPill state={decision.state} />
              </div>
              <div className="text-xs leading-5 text-slate-500">
                {decision.exclusionReasons.length > 0 ? (
                  <p>
                    Exclusions:{" "}
                    {decision.exclusionReasons.map(humanize).join(", ")}
                  </p>
                ) : (
                  <p>No exclusion reason was published.</p>
                )}
                <p className="mt-1">
                  {decision.longHorizonContextHash
                    ? "Long-horizon model context recorded; no prospective outcome is implied."
                    : "No long-horizon model context was recorded."}
                </p>
              </div>
            </li>
          ))}
        </ul>
      </details>
    </section>
  );
}
