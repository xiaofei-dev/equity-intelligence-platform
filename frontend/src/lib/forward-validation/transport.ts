import {
  ForwardValidationContractError,
  decodeProspectiveEnrollment,
  type ProspectiveEnrollment,
} from "./contracts.ts";

export type ForwardValidationError = {
  code:
    | "FORWARD_VALIDATION_CONFIGURATION_ERROR"
    | "FORWARD_VALIDATION_BACKEND_UNAVAILABLE"
    | "FORWARD_VALIDATION_BACKEND_ERROR"
    | "FORWARD_VALIDATION_CONTRACT_ERROR";
  message: string;
  status?: number;
};

export type ForwardValidationResult<T> =
  | { ok: true; data: T }
  | { ok: false; error: ForwardValidationError };

export type ForwardValidationBackendOptions = {
  baseUrl: string;
  identity: string;
  fetcher?: typeof fetch;
  timeoutMs?: number;
};

const identityPattern = /^[A-Za-z0-9._:@+-]{1,128}$/;
export const latestProspectiveEnrollmentPath =
  "/api/v1/forward-validation/prospective-enrollments/latest";

function backendUrl(baseUrl: string): URL | null {
  try {
    const url = new URL(baseUrl);
    if (
      !["http:", "https:"].includes(url.protocol) ||
      url.username ||
      url.password
    ) {
      return null;
    }
    return new URL(
      latestProspectiveEnrollmentPath,
      baseUrl.endsWith("/") ? baseUrl : `${baseUrl}/`,
    );
  } catch {
    return null;
  }
}

function errorMessage(payload: unknown, status: number): string {
  const body =
    typeof payload === "object" && payload !== null
      ? (payload as Record<string, unknown>)
      : {};
  const detail =
    typeof body.detail === "object" && body.detail !== null
      ? (body.detail as Record<string, unknown>)
      : body;
  return typeof detail.message === "string"
    ? detail.message
    : `The forward-validation API returned HTTP ${status}.`;
}

export async function loadLatestProspectiveEnrollmentFromBackend(
  options: ForwardValidationBackendOptions,
): Promise<ForwardValidationResult<ProspectiveEnrollment | null>> {
  const url = backendUrl(options.baseUrl);
  if (!url || !identityPattern.test(options.identity)) {
    return {
      ok: false,
      error: {
        code: "FORWARD_VALIDATION_CONFIGURATION_ERROR",
        message:
          "The server-side forward-validation backend or research identity is invalid.",
      },
    };
  }

  try {
    const response = await (options.fetcher ?? fetch)(url, {
      method: "GET",
      cache: "no-store",
      signal: AbortSignal.timeout(options.timeoutMs ?? 10_000),
      headers: {
        Accept: "application/json",
        "X-Test-Identity": options.identity,
      },
    });

    if (response.status === 404) {
      return { ok: true, data: null };
    }

    let payload: unknown;
    try {
      payload = await response.json();
    } catch {
      return {
        ok: false,
        error: {
          code: "FORWARD_VALIDATION_CONTRACT_ERROR",
          message: "The forward-validation API returned a non-JSON response.",
          status: response.status,
        },
      };
    }

    if (!response.ok) {
      return {
        ok: false,
        error: {
          code: "FORWARD_VALIDATION_BACKEND_ERROR",
          message: errorMessage(payload, response.status),
          status: response.status,
        },
      };
    }

    try {
      return { ok: true, data: decodeProspectiveEnrollment(payload) };
    } catch (error) {
      return {
        ok: false,
        error: {
          code: "FORWARD_VALIDATION_CONTRACT_ERROR",
          message:
            error instanceof ForwardValidationContractError
              ? error.message
              : "The prospective-enrollment response did not match the supported contract.",
          status: response.status,
        },
      };
    }
  } catch {
    return {
      ok: false,
      error: {
        code: "FORWARD_VALIDATION_BACKEND_UNAVAILABLE",
        message: "The forward-validation API is currently unavailable.",
      },
    };
  }
}
