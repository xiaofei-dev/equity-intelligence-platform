import "server-only";

import {
  ContractDecodeError,
  decodeEligibilityRecoveryStatus,
  decodeFacets,
  decodeProfileEnvelope,
  decodeScreeningResultPage,
  decodeScreeningRunMetadata,
  decodeSecuritySearchPage,
  isUuid,
  type MarketIntelligenceFacets,
  type EligibilityRecoveryStatusResponse,
  type ProfileEnvelope,
  type ScreeningResultPage,
  type SecuritySearchPage,
} from "./contracts";
import { buildEligibilityRecoveryStatusPath } from "./eligibility-recovery-route";

export type BackendError = {
  code:
    | "RESEARCH_CONFIGURATION_ERROR"
    | "RESEARCH_BACKEND_UNAVAILABLE"
    | "RESEARCH_BACKEND_ERROR"
    | "RESEARCH_CONTRACT_ERROR"
    | "RESEARCH_INVALID_IDENTIFIER";
  message: string;
  status?: number;
};

export type BackendResult<T> =
  | { ok: true; data: T }
  | { ok: false; error: BackendError };

type Decoder<T> = (value: unknown) => T;

const identityPattern = /^[A-Za-z0-9._:@+-]{1,128}$/;

function configuration():
  | { ok: true; baseUrl: string; identity: string; snapshotId: string }
  | { ok: false; error: BackendError } {
  const baseUrl = process.env.BACKEND_BASE_URL;
  const identity = process.env.CLOSED_TEST_IDENTITY;
  const snapshotId = process.env.RESEARCH_DATA_SNAPSHOT_ID;

  if (!baseUrl || !identity || !snapshotId) {
    return {
      ok: false,
      error: {
        code: "RESEARCH_CONFIGURATION_ERROR",
        message:
          "Research is not configured. Set BACKEND_BASE_URL, CLOSED_TEST_IDENTITY, and RESEARCH_DATA_SNAPSHOT_ID on the server.",
      },
    };
  }
  if (!identityPattern.test(identity) || !isUuid(snapshotId)) {
    return {
      ok: false,
      error: {
        code: "RESEARCH_CONFIGURATION_ERROR",
        message:
          "The server-side research identity or data snapshot identifier is invalid.",
      },
    };
  }

  try {
    const url = new URL(baseUrl);
    if (!["http:", "https:"].includes(url.protocol) || url.username || url.password) {
      throw new Error("Invalid backend URL");
    }
  } catch {
    return {
      ok: false,
      error: {
        code: "RESEARCH_CONFIGURATION_ERROR",
        message: "BACKEND_BASE_URL must be an HTTP(S) origin without credentials.",
      },
    };
  }

  return { ok: true, baseUrl, identity, snapshotId };
}

async function request<T>(
  path: string,
  decoder: Decoder<T>,
  init?: RequestInit,
): Promise<BackendResult<T>> {
  const config = configuration();
  if (!config.ok) {
    return config;
  }

  const url = new URL(path, config.baseUrl.endsWith("/") ? config.baseUrl : `${config.baseUrl}/`);

  try {
    const response = await fetch(url, {
      ...init,
      cache: "no-store",
      signal: AbortSignal.timeout(10_000),
      headers: {
        Accept: "application/json",
        "X-Test-Identity": config.identity,
        ...init?.headers,
      },
    });

    let payload: unknown;
    try {
      payload = await response.json();
    } catch {
      return {
        ok: false,
        error: {
          code: "RESEARCH_CONTRACT_ERROR",
          message: "The research API returned a non-JSON response.",
          status: response.status,
        },
      };
    }

    if (!response.ok) {
      const body =
        typeof payload === "object" && payload !== null
          ? (payload as Record<string, unknown>)
          : {};
      const detail =
        typeof body.detail === "object" && body.detail !== null
          ? (body.detail as Record<string, unknown>)
          : body;
      return {
        ok: false,
        error: {
          code: "RESEARCH_BACKEND_ERROR",
          message:
            typeof detail.message === "string"
              ? detail.message
              : `The research API returned HTTP ${response.status}.`,
          status: response.status,
        },
      };
    }

    try {
      return { ok: true, data: decoder(payload) };
    } catch (error) {
      return {
        ok: false,
        error: {
          code: "RESEARCH_CONTRACT_ERROR",
          message:
            error instanceof ContractDecodeError
              ? error.message
              : "The research API response did not match the supported contract.",
          status: response.status,
        },
      };
    }
  } catch {
    return {
      ok: false,
      error: {
        code: "RESEARCH_BACKEND_UNAVAILABLE",
        message: "The research API is currently unavailable.",
      },
    };
  }
}

export function getResearchSnapshotId(): BackendResult<string> {
  const config = configuration();
  return config.ok ? { ok: true, data: config.snapshotId } : config;
}

export function getDefaultScreeningRunId(): string | null {
  const runId = process.env.RESEARCH_SCREENING_RUN_ID;
  return runId && isUuid(runId) ? runId : null;
}

export function getSnapshotAsOf(): BackendResult<string> {
  const value = process.env.RESEARCH_SNAPSHOT_AS_OF;
  if (!value || Number.isNaN(Date.parse(value))) {
    return {
      ok: false,
      error: {
        code: "RESEARCH_CONFIGURATION_ERROR",
        message:
          "Screening execution requires a valid RESEARCH_SNAPSHOT_AS_OF server value.",
      },
    };
  }
  return { ok: true, data: value };
}

export async function loadResearchFacets(): Promise<
  BackendResult<MarketIntelligenceFacets>
> {
  const snapshot = getResearchSnapshotId();
  if (!snapshot.ok) return snapshot;
  const query = new URLSearchParams({ dataSnapshotId: snapshot.data });
  return request(
    `/api/v1/market-intelligence/facets?${query}`,
    decodeFacets,
  );
}

export async function loadLatestEligibilityRecoveryStatus(options: {
  dataSnapshotId: string;
  universeVersion: string;
  asOf: string;
}): Promise<BackendResult<EligibilityRecoveryStatusResponse | null>> {
  if (!isUuid(options.dataSnapshotId)) {
    return {
      ok: false,
      error: {
        code: "RESEARCH_INVALID_IDENTIFIER",
        message: "The eligibility-recovery snapshot identifier is invalid.",
      },
    };
  }
  if (
    !options.universeVersion.trim() ||
    Number.isNaN(Date.parse(options.asOf))
  ) {
    return {
      ok: false,
      error: {
        code: "RESEARCH_CONFIGURATION_ERROR",
        message:
          "Eligibility recovery requires a universe version and valid snapshot cutoff.",
      },
    };
  }
  const result = await request(
    buildEligibilityRecoveryStatusPath(options),
    decodeEligibilityRecoveryStatus,
  );
  if (!result.ok && result.error.status === 404) {
    return { ok: true, data: null };
  }
  return result;
}

export async function searchSecurities(options: {
  query?: string;
  cursor?: string;
  limit?: number;
}): Promise<BackendResult<SecuritySearchPage>> {
  const snapshot = getResearchSnapshotId();
  if (!snapshot.ok) return snapshot;
  const query = new URLSearchParams({
    dataSnapshotId: snapshot.data,
    limit: String(options.limit ?? 20),
  });
  if (options.query) query.set("query", options.query);
  if (options.cursor) query.set("cursor", options.cursor);
  return request(
    `/api/v1/market-intelligence/securities?${query}`,
    decodeSecuritySearchPage,
  );
}

export async function loadScreeningResults(
  runId: string,
  cursor?: string,
): Promise<BackendResult<ScreeningResultPage>> {
  if (!isUuid(runId)) {
    return {
      ok: false,
      error: {
        code: "RESEARCH_INVALID_IDENTIFIER",
        message: "The screening run identifier is invalid.",
      },
    };
  }
  const query = new URLSearchParams({ limit: "20" });
  if (cursor) query.set("cursor", cursor);
  return request(
    `/api/v1/market-intelligence/screening-runs/${encodeURIComponent(runId)}/results?${query}`,
    decodeScreeningResultPage,
  );
}

export async function loadLatestProfile(
  securityId: string,
): Promise<BackendResult<ProfileEnvelope>> {
  if (!isUuid(securityId)) {
    return {
      ok: false,
      error: {
        code: "RESEARCH_INVALID_IDENTIFIER",
        message: "The security identifier is invalid.",
      },
    };
  }
  return request(
    `/api/v1/market-intelligence/securities/${encodeURIComponent(securityId)}/profiles/latest`,
    decodeProfileEnvelope,
  );
}

export async function loadImmutableProfile(
  profileId: string,
): Promise<BackendResult<ProfileEnvelope>> {
  if (!isUuid(profileId)) {
    return {
      ok: false,
      error: {
        code: "RESEARCH_INVALID_IDENTIFIER",
        message: "The profile identifier is invalid.",
      },
    };
  }
  return request(
    `/api/v1/market-intelligence/profiles/${encodeURIComponent(profileId)}`,
    decodeProfileEnvelope,
  );
}

export async function createScreeningRun(payload: unknown): Promise<
  BackendResult<{
    runId: string;
  }>
> {
  const body = JSON.stringify(payload);
  const payloadHash = Array.from(
    new Uint8Array(
      await crypto.subtle.digest("SHA-256", new TextEncoder().encode(body)),
    ),
    (byte) => byte.toString(16).padStart(2, "0"),
  ).join("");
  return request(
    "/api/v1/market-intelligence/screening-runs",
    (value) => {
      const run = decodeScreeningRunMetadata(value);
      return { runId: run.runId };
    },
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Idempotency-Key": `research-ui-${payloadHash}`,
      },
      body,
    },
  );
}
