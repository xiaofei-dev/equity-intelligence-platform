import Link from "next/link";
import {
  formatScore,
  formatTimestamp,
  humanize,
} from "@/lib/format";
import type {
  DecimalValue,
  ProfileEnvelope,
  ProfileFact,
} from "@/lib/market-intelligence/contracts";
import { MarketDataBlock } from "./market-data-block";
import { StatusPill } from "./status-pill";

function Metric({
  label,
  value,
  state,
  detail,
}: {
  label: string;
  value: DecimalValue | null;
  state: string;
  detail: string;
}) {
  return (
    <article className="rounded-2xl border border-slate-800 bg-slate-900/55 p-5">
      <div className="flex items-start justify-between gap-3">
        <p className="text-xs font-semibold uppercase tracking-[0.15em] text-slate-500">
          {label}
        </p>
        <StatusPill state={state} />
      </div>
      <p className="mt-5 font-mono text-3xl font-semibold text-white">
        {formatScore(value)}
        {value !== null && (
          <span className="ml-1 text-sm font-normal text-slate-500">/ 100</span>
        )}
      </p>
      <p className="mt-2 text-xs text-slate-500">{detail}</p>
    </article>
  );
}

function FactRow({ fact }: { fact: ProfileFact }) {
  return (
    <li className="grid gap-3 px-5 py-4 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center">
      <div>
        <div className="flex flex-wrap items-center gap-2">
          <p className="font-medium text-slate-200">{humanize(fact.name)}</p>
          <StatusPill state={fact.state} />
        </div>
        <p className="mt-1 text-xs text-slate-500">
          {fact.reason
            ? humanize(fact.reason)
            : `${fact.lineage.length} provenance record${fact.lineage.length === 1 ? "" : "s"}`}
        </p>
      </div>
      <p className="font-mono text-sm text-slate-200">
        {fact.value === null ? "Not available" : String(fact.value)}
      </p>
    </li>
  );
}

export function ProfileView({
  envelope,
  immutable = false,
}: {
  envelope: ProfileEnvelope;
  immutable?: boolean;
}) {
  const { profile, currentMarketData, freshness } = envelope;
  const classification = profile.classification;
  const riskReasons = Array.from(
    new Set([
      ...profile.rankingExclusions,
      ...profile.valuation.limitations,
      ...profile.horizons.flatMap(
        (item) => item.deterministicView.missingInputs,
      ),
      ...freshness
        .filter((item) => item.state !== "CURRENT" && item.state !== "VALID")
        .map(
          (item) =>
            item.reasonCode ?? `${item.datasetCode}_${item.state}`,
        ),
    ]),
  );

  return (
    <div className="space-y-6">
      <section className="relative overflow-hidden rounded-3xl border border-slate-800 bg-[linear-gradient(135deg,rgba(15,23,42,.96),rgba(8,47,73,.42))] p-6 sm:p-8">
        <div className="absolute -right-16 -top-24 h-64 w-64 rounded-full bg-cyan-400/10 blur-3xl" />
        <div className="relative flex flex-wrap items-start justify-between gap-6">
          <div>
            <div className="flex flex-wrap items-center gap-3">
              <span className="font-mono text-sm font-semibold tracking-[0.18em] text-cyan-300">
                {profile.security.symbol}
              </span>
              <StatusPill state={profile.profileState} />
              <StatusPill state={profile.rankingState} />
            </div>
            <h1 className="mt-4 text-3xl font-semibold tracking-tight text-white sm:text-4xl">
              {profile.security.issuerName}
            </h1>
            <p className="mt-3 text-sm text-slate-400">
              {profile.security.exchangeMic} · {profile.security.instrumentType}
              {classification
                ? ` · ${classification.sectorName} · ${classification.industryName}`
                : " · Classification missing"}
            </p>
          </div>
          <div className="text-right text-xs text-slate-500">
            <p>{immutable ? "Immutable profile" : "Latest profile"}</p>
            <p className="mt-1 font-mono text-slate-400">
              {envelope.profileId}
            </p>
            {!immutable && (
              <Link
                href={`/research/profiles/${envelope.profileId}`}
                className="mt-3 inline-flex rounded-full border border-cyan-400/30 bg-cyan-400/10 px-3 py-1.5 font-semibold text-cyan-200 transition hover:bg-cyan-400/15"
              >
                Open immutable version
              </Link>
            )}
          </div>
        </div>
      </section>

      <div className="grid gap-6 lg:grid-cols-[1.08fr_.92fr]">
        <MarketDataBlock market={currentMarketData} freshness={freshness} />
        <section className="rounded-2xl border border-slate-800 bg-slate-900/55 p-5">
          <div className="flex items-start justify-between gap-4">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500">
                Data freshness
              </p>
              <p className="mt-2 text-sm leading-6 text-slate-400">
                Effective, available, and ingestion times remain distinct.
              </p>
            </div>
            <span className="font-mono text-xs text-slate-500">
              {freshness.length} datasets
            </span>
          </div>
          {freshness.length === 0 ? (
            <p className="mt-5 text-sm text-amber-200">
              No freshness records were published.
            </p>
          ) : (
            <ul className="mt-5 space-y-3">
              {freshness.map((item) => (
                <li
                  key={`${item.datasetCode}-${item.evaluatedAt}`}
                  className="rounded-xl border border-slate-800 bg-slate-950/45 p-4"
                >
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <p className="text-sm font-medium text-slate-200">
                      {humanize(item.datasetCode)}
                    </p>
                    <StatusPill state={item.state} />
                  </div>
                  <p className="mt-2 text-xs text-slate-500">
                    Evaluated {formatTimestamp(item.evaluatedAt)}
                  </p>
                  {item.reasonCode && (
                    <p className="mt-1 text-xs text-amber-200/70">
                      {humanize(item.reasonCode)}
                    </p>
                  )}
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>

      <section>
        <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.16em] text-cyan-300">
              Deterministic assessment
            </p>
            <h2 className="mt-2 text-xl font-semibold text-white">
              Objective rating and valuation
            </h2>
          </div>
          <p className="text-xs text-slate-500">
            Version {profile.objectiveRatingVersion}
          </p>
        </div>
        <div className="grid gap-4 md:grid-cols-3">
          <Metric
            label="Objective quality"
            value={profile.objectiveQualityScore}
            state={profile.objectiveRatingStatus}
            detail="Deterministic quality evidence"
          />
          <Metric
            label="Objective valuation"
            value={profile.objectiveValuationScore}
            state={profile.valuation.state}
            detail="Cross-sectional valuation evidence"
          />
          <Metric
            label="Long-horizon valuation"
            value={profile.valuation.longHorizonValuationScore}
            state={profile.valuation.state}
            detail={
              profile.valuation.ownHistoryPercentile === null
                ? "Own-history percentile unavailable"
                : `Own-history percentile ${formatScore(profile.valuation.ownHistoryPercentile)}`
            }
          />
        </div>
      </section>

      <section className="rounded-2xl border border-slate-800 bg-slate-900/45 p-5 sm:p-6">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.16em] text-cyan-300">
              Horizon views
            </p>
            <h2 className="mt-2 text-xl font-semibold text-white">
              1W, 1M, 3M, and 12M+
            </h2>
          </div>
          <p className="text-xs text-slate-500">
            Scores are not return forecasts
          </p>
        </div>
        <div className="mt-5 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {profile.horizons.map(({ horizon, deterministicView }) => (
            <article
              key={horizon}
              className="rounded-xl border border-slate-800 bg-slate-950/55 p-4"
            >
              <div className="flex items-center justify-between gap-3">
                <p className="font-mono text-xs font-semibold text-cyan-300">
                  {horizon === "ONE_WEEK"
                    ? "1W"
                    : horizon === "ONE_MONTH"
                      ? "1M"
                      : horizon === "THREE_MONTHS"
                        ? "3M"
                        : "12M+"}
                </p>
                <StatusPill state={deterministicView.state} />
              </div>
              <p className="mt-5 font-mono text-2xl font-semibold text-white">
                {formatScore(deterministicView.score)}
              </p>
              <p className="mt-2 text-sm font-medium text-slate-300">
                {humanize(deterministicView.label)}
              </p>
              <p className="mt-3 text-xs leading-5 text-slate-500">
                As of {formatTimestamp(deterministicView.asOf)}
              </p>
              {deterministicView.missingInputs.length > 0 && (
                <p className="mt-2 text-xs leading-5 text-amber-200/75">
                  {deterministicView.missingInputs
                    .map(humanize)
                    .join(", ")}
                </p>
              )}
            </article>
          ))}
        </div>
      </section>

      <div className="grid gap-6 lg:grid-cols-[1.15fr_.85fr]">
        <section className="overflow-hidden rounded-2xl border border-slate-800 bg-slate-900/45">
          <div className="border-b border-slate-800 p-5">
            <p className="text-xs font-semibold uppercase tracking-[0.16em] text-cyan-300">
              Factor contributions and evidence
            </p>
            <h2 className="mt-2 text-xl font-semibold text-white">
              Published deterministic inputs
            </h2>
            <p className="mt-2 text-sm leading-6 text-slate-500">
              Values are shown exactly as published. Missing inputs are not
              treated as zero or neutral contributions.
            </p>
          </div>
          {profile.facts.length === 0 ? (
            <p className="p-5 text-sm text-amber-200">
              No factor evidence was published.
            </p>
          ) : (
            <ul className="divide-y divide-slate-800">
              {profile.facts.map((fact) => (
                <FactRow key={`${fact.name}-${fact.metricVersion}`} fact={fact} />
              ))}
            </ul>
          )}
        </section>

        <section className="rounded-2xl border border-rose-400/20 bg-rose-400/[0.045] p-5">
          <p className="text-xs font-semibold uppercase tracking-[0.16em] text-rose-300">
            Risks and exclusions
          </p>
          <h2 className="mt-2 text-xl font-semibold text-white">
            What prevents a stronger conclusion
          </h2>
          {riskReasons.length === 0 ? (
            <p className="mt-5 text-sm leading-6 text-slate-400">
              No explicit exclusion or freshness risk was published. This does
              not imply an absence of investment risk.
            </p>
          ) : (
            <ul className="mt-5 space-y-3">
              {riskReasons.map((reason) => (
                <li
                  key={reason}
                  className="flex gap-3 text-sm leading-6 text-rose-100/75"
                >
                  <span aria-hidden className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-rose-300" />
                  {humanize(reason)}
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>

      <section className="rounded-2xl border border-violet-400/25 bg-violet-400/[0.06] p-5 sm:p-6">
        <div className="grid gap-6 lg:grid-cols-[.78fr_1.22fr]">
          <div>
            <div className="flex flex-wrap items-center gap-3">
              <p className="text-xs font-semibold uppercase tracking-[0.16em] text-violet-300">
                AI narrative
              </p>
              <StatusPill state={profile.aiNarrative.status} />
            </div>
            <h2 className="mt-3 text-xl font-semibold text-white">
              Explanatory layer only
            </h2>
            <p className="mt-3 text-sm leading-6 text-violet-100/60">
              AI output is visibly separate from deterministic analysis. It
              cannot set scores, change rank, select trades, or determine
              portfolio weights.
            </p>
          </div>
          <div className="rounded-xl border border-violet-400/15 bg-slate-950/40 p-4">
            {profile.aiNarrative.narrative ? (
              <>
                <p className="text-sm leading-7 text-slate-300">
                  {profile.aiNarrative.narrative}
                </p>
                <p className="mt-4 text-xs text-slate-500">
                  Generated {formatTimestamp(profile.aiNarrative.generatedAt)} ·
                  Confidence {profile.aiNarrative.confidence ?? "not stated"}
                </p>
                <ul className="mt-3 space-y-1 text-xs text-violet-200/70">
                  {profile.aiNarrative.sourceReferences.map((source) => (
                    <li key={source}>{source}</li>
                  ))}
                </ul>
              </>
            ) : (
              <p className="text-sm leading-6 text-slate-400">
                No AI narrative was published for this profile. Deterministic
                evidence remains available independently.
              </p>
            )}
          </div>
        </div>
      </section>

      <section className="rounded-2xl border border-slate-800 bg-slate-900/45 p-5">
        <p className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500">
          Reproducibility
        </p>
        <dl className="mt-4 grid gap-4 text-sm sm:grid-cols-2 lg:grid-cols-3">
          {Object.entries(envelope.modelVersions).map(([name, version]) => (
            <div key={name}>
              <dt className="text-slate-500">{humanize(name)}</dt>
              <dd className="mt-1 break-all font-mono text-xs text-slate-300">
                {version}
              </dd>
            </div>
          ))}
        </dl>
      </section>
    </div>
  );
}
