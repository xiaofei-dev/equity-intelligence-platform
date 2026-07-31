import { formatTimestamp, humanize } from "@/lib/format";
import type {
  EligibilityRecoveryStatusResponse,
  EligibilitySecurityDiagnostic,
} from "@/lib/market-intelligence/contracts";
import type { BackendResult } from "@/lib/market-intelligence/backend";
import {
  describeEligibilityEvidenceScope,
  describeEligibilityOperand,
} from "@/lib/market-intelligence/eligibility-recovery-presentation";
import { StatusPill } from "./status-pill";

function statusMessage(status: EligibilityRecoveryStatusResponse["status"]) {
  switch (status) {
    case "READY_FOR_CONFIRMATION":
      return "A bounded provider-recovery plan is pending explicit confirmation. No request has been executed.";
    case "NO_ACTIONABLE_REQUESTS":
      return "No provider-recovery request is currently actionable under the frozen policy.";
    case "BLOCKED_COHORT_UNREACHABLE":
      return "Provider recovery is blocked because the frozen eligibility minimum remains unreachable.";
    case "BLOCKED_EVIDENCE_SEMANTICS":
      return "Provider recovery is blocked because the required evidence semantics are not proven.";
    case "BLOCKED_BUDGET":
      return "Provider recovery is blocked by the bounded request budget.";
    case "BLOCKED_SNAPSHOT":
      return "Provider recovery is blocked because the snapshot boundary is not usable.";
  }
}

function diagnosticDescription(
  diagnostic: EligibilitySecurityDiagnostic,
): string {
  switch (diagnostic.state) {
    case "ALREADY_ELIGIBLE":
      return "Eligible under the frozen model contract.";
    case "RECOVERABLE":
      return "Insufficient data; bounded provider recovery is pending.";
    case "BLOCKED":
      return "Provider recovery is blocked.";
    case "NOT_APPLICABLE":
      return "Specialized or reference security; this model is not applicable.";
  }
}

export function EligibilityRecoveryPanel({
  result,
}: {
  result: BackendResult<EligibilityRecoveryStatusResponse | null>;
}) {
  if (!result.ok) {
    return (
      <section
        aria-labelledby="eligibility-recovery-title"
        className="rounded-3xl border border-rose-400/20 bg-rose-400/[0.045] p-5 sm:p-6"
      >
        <p className="text-xs font-semibold uppercase tracking-[0.16em] text-rose-300">
          Eligibility recovery
        </p>
        <h2
          id="eligibility-recovery-title"
          className="mt-2 text-xl font-semibold text-white"
        >
          Recovery status is unavailable
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
        aria-labelledby="eligibility-recovery-title"
        className="rounded-3xl border border-slate-800 bg-slate-900/45 p-5 sm:p-6"
      >
        <p className="text-xs font-semibold uppercase tracking-[0.16em] text-cyan-300">
          Eligibility recovery
        </p>
        <h2
          id="eligibility-recovery-title"
          className="mt-2 text-xl font-semibold text-white"
        >
          No recovery status yet
        </h2>
        <p className="mt-3 max-w-3xl text-sm leading-6 text-slate-400">
          No sealed eligibility-recovery preflight exists for this snapshot.
          No score, rank, provider request, or trade instruction is implied.
        </p>
      </section>
    );
  }

  const recovery = result.data;
  const staleCount = recovery.securityDiagnostics.filter((diagnostic) =>
    diagnostic.freshness.some((item) => item.state === "STALE"),
  ).length;
  const notApplicableCount = recovery.securityDiagnostics.filter(
    (diagnostic) => diagnostic.state === "NOT_APPLICABLE",
  ).length;
  const blockedCount = recovery.securityDiagnostics.filter(
    (diagnostic) => diagnostic.state === "BLOCKED",
  ).length;
  const insufficientCount = recovery.securityDiagnostics.filter(
    (diagnostic) => diagnostic.state === "RECOVERABLE",
  ).length;
  const isBlocked = recovery.status.startsWith("BLOCKED");
  const evidenceScope = describeEligibilityEvidenceScope(recovery);

  return (
    <section
      aria-labelledby="eligibility-recovery-title"
      className="overflow-hidden rounded-3xl border border-slate-700/80 bg-slate-900/45"
    >
      <div className="grid gap-6 p-5 sm:p-6 lg:grid-cols-[1fr_auto] lg:items-start">
        <div>
          <div className="flex flex-wrap items-center gap-3">
            <p className="text-xs font-semibold uppercase tracking-[0.16em] text-cyan-300">
              Eligibility recovery
            </p>
            <StatusPill state={recovery.status} />
            {recovery.confirmationRequired && (
              <StatusPill state="PROVIDER_RECOVERY_PENDING" />
            )}
          </div>
          <h2
            id="eligibility-recovery-title"
            className="mt-3 text-2xl font-semibold text-white"
          >
            Frozen-model eligibility status
          </h2>
          <p className="mt-3 max-w-3xl text-sm leading-6 text-slate-300">
            {statusMessage(recovery.status)}
          </p>
          <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-500">
            This is a read-only evidence preflight. It does not calculate a
            score, change a rank, execute a provider request, or instruct a
            trade.
          </p>
        </div>
        <div className="text-left text-xs text-slate-500 lg:text-right">
          <p>Last updated</p>
          <p className="mt-1 font-mono text-slate-300">
            {formatTimestamp(recovery.generatedAt)}
          </p>
          <p className="mt-2">
            Snapshot {formatTimestamp(recovery.snapshotAsOf)}
          </p>
        </div>
      </div>

      <div className="grid grid-cols-2 border-y border-slate-800/90 sm:grid-cols-4 xl:grid-cols-8">
        {[
          ["Profiles", recovery.profileCount],
          ["Sealed results", recovery.resultCount],
          ["Eligible", recovery.currentEligibleCount],
          ["Frozen minimum", recovery.frozenMinimumEligibleCount],
          ["Insufficient data", insufficientCount],
          ["Stale", staleCount],
          ["Specialized / N/A", notApplicableCount],
          ["Recovery blocked", blockedCount],
        ].map(([label, value]) => (
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
      <p className="border-b border-slate-800/90 px-5 py-3 text-xs leading-5 text-slate-600 sm:px-6">
        Profiles and sealed results are coverage totals. Eligible is the
        separate frozen-model eligibility count; none of these values is a
        score or trade signal.
      </p>
      <div className="border-b border-slate-800/90 bg-cyan-400/[0.025] px-5 py-4 sm:px-6">
        <p className="text-xs font-semibold uppercase tracking-[0.14em] text-cyan-200/80">
          {evidenceScope.heading}
        </p>
        <p className="mt-2 max-w-5xl text-xs leading-5 text-slate-400">
          {evidenceScope.persistedEvidenceSummary}
        </p>
        <p className="mt-1 max-w-5xl text-xs leading-5 text-slate-600">
          {evidenceScope.limitation}
        </p>
      </div>

      <div className="grid gap-6 p-5 sm:p-6 lg:grid-cols-[1.05fr_.95fr]">
        <div>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500">
                Provider recovery
              </p>
              <h3 className="mt-2 text-lg font-semibold text-white">
                Planned evidence requests
              </h3>
            </div>
            <StatusPill
              state={
                isBlocked
                  ? "PROVIDER_RECOVERY_BLOCKED"
                  : recovery.confirmationRequired
                    ? "PROVIDER_RECOVERY_PENDING"
                    : "NO_ACTIONABLE_REQUESTS"
              }
            />
          </div>
          <p className="mt-3 text-sm leading-6 text-slate-500">
            {recovery.dueSecurityCount} securities are due;{" "}
            {recovery.persistedEvidenceReuseCount} can reuse persisted
            evidence. Maximum eligible after the plan is{" "}
            {recovery.maximumEligibleAfterPlan}; this is a ceiling, not a
            score forecast.
          </p>
          {recovery.dueSymbols.length > 0 && (
            <p className="mt-3 text-xs leading-5 text-slate-500">
              Due symbols: {recovery.dueSymbols.join(", ")}
            </p>
          )}
          {recovery.requestPlan.length === 0 ? (
            <p className="mt-4 rounded-xl border border-slate-800 bg-slate-950/45 p-4 text-sm text-slate-400">
              No provider request plan is actionable.
            </p>
          ) : (
            <ul className="mt-4 space-y-3">
              {recovery.requestPlan.map((plan) => (
                <li
                  key={`${plan.provider}-${plan.endpointCode}-${plan.dataset}`}
                  className="rounded-xl border border-slate-800 bg-slate-950/45 p-4"
                >
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <p className="text-sm font-semibold text-slate-200">
                      {humanize(plan.provider)} - {humanize(plan.dataset)}
                    </p>
                    <span className="font-mono text-xs text-slate-500">
                      {plan.symbols.length} symbols
                    </span>
                  </div>
                  <p className="mt-2 font-mono text-xs text-cyan-200/70">
                    {plan.endpointCode}
                  </p>
                  <p className="mt-2 text-xs leading-5 text-slate-500">
                    Hard ceiling: {plan.physicalRequestHardCeiling} physical /{" "}
                    {plan.weightedCallHardCeiling} weighted calls; maximum{" "}
                    {plan.runnerMaximumAttempts} attempts. Planned only.
                  </p>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500">
            Freshness and blockers
          </p>
          <h3 className="mt-2 text-lg font-semibold text-white">
            Why eligibility is limited
          </h3>
          <ul className="mt-4 space-y-3">
            {recovery.freshness.map((item) => (
              <li
                key={`${item.datasetCode}-${item.state}`}
                className="rounded-xl border border-slate-800 bg-slate-950/45 p-4"
              >
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <p className="text-sm font-medium text-slate-200">
                    {humanize(item.datasetCode)}
                  </p>
                  <StatusPill state={item.state} />
                </div>
                <p className="mt-2 text-xs text-slate-500">
                  {item.affectedSecurityCount} affected - evaluated{" "}
                  {formatTimestamp(item.evaluatedAt)}
                </p>
                {item.reasonCode && (
                  <p className="mt-1 text-xs text-amber-200/70">
                    {humanize(item.reasonCode)}
                  </p>
                )}
              </li>
            ))}
            {recovery.blockerSummary.map((blocker) => (
              <li
                key={`${blocker.category}-${blocker.reasonCode}`}
                className="rounded-xl border border-amber-400/15 bg-amber-400/[0.035] p-4"
              >
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <p className="text-sm font-medium text-amber-100/80">
                    {humanize(blocker.category)}
                  </p>
                  <span className="font-mono text-xs text-amber-200/60">
                    {blocker.affectedSecurityCount} affected
                  </span>
                </div>
                <p className="mt-2 text-xs text-amber-100/60">
                  {humanize(blocker.reasonCode)}
                </p>
                <p className="mt-1 text-xs text-slate-600">
                  {humanize(blocker.actionability)}
                </p>
              </li>
            ))}
          </ul>
        </div>
      </div>

      <details className="group border-t border-slate-800/90">
        <summary className="cursor-pointer list-none px-5 py-4 text-sm font-semibold text-slate-300 transition hover:bg-slate-900/40 sm:px-6">
          Security eligibility diagnostics (
          {recovery.securityDiagnostics.length})
          <span className="ml-2 text-slate-600 group-open:hidden">
            Show
          </span>
          <span className="ml-2 hidden text-slate-600 group-open:inline">
            Hide
          </span>
        </summary>
        <ul className="divide-y divide-slate-800/80 border-t border-slate-800/90">
          {recovery.securityDiagnostics.map((diagnostic) => {
            const stale = diagnostic.freshness.some(
              (item) => item.state === "STALE",
            );
            return (
              <li
                key={diagnostic.securityId}
                className="grid gap-3 px-5 py-4 sm:grid-cols-[8rem_11rem_1fr] sm:px-6"
              >
                <p className="font-mono text-sm font-semibold text-cyan-300">
                  {diagnostic.symbol}
                </p>
                <div className="flex flex-wrap items-start gap-2">
                  <StatusPill state={diagnostic.state} />
                  {stale && <StatusPill state="STALE" />}
                </div>
                <div className="text-xs leading-5 text-slate-500">
                  <p>{diagnosticDescription(diagnostic)}</p>
                  {diagnostic.missingOperands.length > 0 && (
                    <ul className="mt-2 space-y-1 text-amber-100/65">
                      {diagnostic.missingOperands.map((operand) => (
                        <li
                          key={`${operand.factorCode}-${operand.operandCode}`}
                        >
                          {describeEligibilityOperand(operand)}
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
      </details>

      <div className="grid gap-3 border-t border-slate-800/90 px-5 py-4 text-xs text-slate-600 sm:grid-cols-3 sm:px-6">
        <p>
          Model:{" "}
          <span className="font-mono text-slate-400">
            {recovery.objectiveRatingVersion}
          </span>
        </p>
        <p>
          Recovery policy:{" "}
          <span className="font-mono text-slate-400">
            {recovery.recoveryPolicyVersion}
          </span>
        </p>
        <p>
          Contract:{" "}
          <span className="font-mono text-slate-400">
            {recovery.schemaVersion}
          </span>
        </p>
      </div>
    </section>
  );
}
