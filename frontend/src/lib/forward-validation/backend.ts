import "server-only";

import { loadLatestProspectiveEnrollmentFromBackend } from "./transport.ts";

export async function loadLatestProspectiveEnrollment() {
  const baseUrl = process.env.BACKEND_BASE_URL;
  const identity = process.env.CLOSED_TEST_IDENTITY;
  if (!baseUrl || !identity) {
    return {
      ok: false as const,
      error: {
        code: "FORWARD_VALIDATION_CONFIGURATION_ERROR" as const,
        message:
          "Forward validation is not configured. Set BACKEND_BASE_URL and CLOSED_TEST_IDENTITY on the server.",
      },
    };
  }
  return loadLatestProspectiveEnrollmentFromBackend({ baseUrl, identity });
}
