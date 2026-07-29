import Link from "next/link";
import { loadLatestProfile } from "@/lib/market-intelligence/backend";
import { ErrorPanel } from "../../components/error-panel";
import { ProfileView } from "../../components/profile-view";

export const dynamic = "force-dynamic";

export default async function SecurityResearchPage({
  params,
}: {
  params: Promise<{ securityId: string }>;
}) {
  const { securityId } = await params;
  const result = await loadLatestProfile(securityId);

  return (
    <div>
      <Link
        href="/research"
        className="mb-6 inline-flex text-xs font-semibold text-slate-500 transition hover:text-cyan-200"
      >
        ← Research workspace
      </Link>
      {result.ok ? (
        <ProfileView envelope={result.data} />
      ) : (
        <ErrorPanel
          error={result.error}
          title="The latest security profile is unavailable"
        />
      )}
    </div>
  );
}
