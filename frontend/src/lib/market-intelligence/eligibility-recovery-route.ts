export type EligibilityRecoveryRouteInput = {
  dataSnapshotId: string;
  universeVersion: string;
  asOf: string;
};

export function buildEligibilityRecoveryStatusPath(
  input: EligibilityRecoveryRouteInput,
): string {
  const query = new URLSearchParams({
    dataSnapshotId: input.dataSnapshotId,
    universeVersion: input.universeVersion,
    asOf: input.asOf,
  });
  return `/api/v1/market-intelligence/eligibility-recovery/status/latest?${query}`;
}
