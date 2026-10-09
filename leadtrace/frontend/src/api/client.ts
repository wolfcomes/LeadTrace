import type { ZodType, ZodTypeDef } from "zod";

import { apiErrorSchema } from "./schema";

export type ApiFailureKind =
  | "authentication"
  | "permission"
  | "conflict"
  | "validation"
  | "unavailable"
  | "unexpected";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    readonly requestId: string | undefined,
    readonly kind: ApiFailureKind,
    readonly details: Record<string, unknown> = {},
    readonly serverMessage: string | undefined = undefined,
  ) {
    super(`LeadTrace API request failed (${code})`);
    this.name = "ApiError";
  }
}

export interface ApiFailureContext {
  path: string;
  sessionGeneration?: number;
}

let unauthorizedHandler:
  ((error: ApiError, context: ApiFailureContext) => void)
  | undefined;
let unauthorizedSessionGeneration:
  (() => number)
  | undefined;
let csrfValidationFailedHandler:
  ((error: ApiError, context: ApiFailureContext) => void | Promise<void>)
  | undefined;

export function setUnauthorizedHandler(
  handler:
    ((error: ApiError, context: ApiFailureContext) => void)
    | undefined,
  getSessionGeneration?: () => number,
): void {
  unauthorizedHandler = handler;
  unauthorizedSessionGeneration = handler ? getSessionGeneration : undefined;
}

export function setCsrfValidationFailedHandler(
  handler:
    ((error: ApiError, context: ApiFailureContext) => void | Promise<void>)
    | undefined,
): void {
  csrfValidationFailedHandler = handler;
}

function failureKind(status: number): ApiFailureKind {
  if (status === 401) return "authentication";
  if (status === 403) return "permission";
  if (status === 409) return "conflict";
  if (status === 422) return "validation";
  if (status === 503) return "unavailable";
  return "unexpected";
}

export interface ApiRequestOptions extends Omit<RequestInit, "body"> {
  body?: unknown;
  csrfToken?: string | null;
  suppressUnauthorizedHandler?: boolean;
}

export async function apiRequest<T>(
  path: string,
  schema: ZodType<T, ZodTypeDef, unknown>,
  options: ApiRequestOptions = {},
): Promise<T> {
  const requestSessionGeneration = unauthorizedSessionGeneration?.();
  const {
    body,
    csrfToken,
    suppressUnauthorizedHandler,
    ...requestOptions
  } = options;
  const headers = new Headers(requestOptions.headers);
  headers.set("Accept", "application/json");
  if (body !== undefined) headers.set("Content-Type", "application/json");
  if (csrfToken) headers.set("X-CSRF-Token", csrfToken);
  const response = await fetch(path, {
    ...requestOptions,
    body: body === undefined ? undefined : JSON.stringify(body),
    credentials: "same-origin",
    headers,
  });
  if (!response.ok) {
    const parsed = apiErrorSchema.safeParse(await response.json().catch(() => ({})));
    const code = parsed.success ? parsed.data.code : `HTTP_${response.status}`;
    const requestId = parsed.success
      ? parsed.data.request_id
      : response.headers.get("X-Request-ID") ?? undefined;
    const details = parsed.success ? parsed.data.details : {};
    const error = new ApiError(
      response.status,
      code,
      requestId,
      failureKind(response.status),
      details,
      parsed.success ? parsed.data.message : undefined,
    );
    if (response.status === 401 && !suppressUnauthorizedHandler) {
      unauthorizedHandler?.(error, {
        path,
        sessionGeneration: requestSessionGeneration,
      });
    }
    if (code === "CSRF_VALIDATION_FAILED") {
      try {
        await csrfValidationFailedHandler?.(error, { path });
      } finally {
        throw error;
      }
    }
    throw error;
  }
  if (response.status === 204) return schema.parse(undefined);
  return schema.parse(await response.json());
}
