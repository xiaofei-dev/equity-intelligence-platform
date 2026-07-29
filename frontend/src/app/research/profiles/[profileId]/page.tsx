import Link from "next/link";
import { loadImmutableProfile } from "@/lib/market-intelligence/backend";
import { ErrorPanel } from "../../components/error-panel";
import { ProfileView } from "../../components/profile-view";

export const dynamic = "force-dynamic";

export default async function ImmutableProfilePage({
  params,
}: {
  params: Promise<{ profileId: string }>;
}) {
  const { profileId } = await params;
  const result = await loadImmutableProfile(profileId);

  return (
    <div>
      <Link
        href="/research"
        className="mb-6 inline-flex text-xs font-semibold text-slate-500 transition hover:text-cyan-200"
      >
        ← Research workspace
      </Link>
      {result.ok ? (
        <ProfileView envelope={result.data} immutable />
      ) : (
        <ErrorPanel
          error={result.error}
          title="The immutable profile is unavailable"
        />
      )}
    </div>
  );
}
