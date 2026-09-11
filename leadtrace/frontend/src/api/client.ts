import type { ZodType } from "zod";

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
  ) {
    super(`LeadTrace API request failed (${code})`);
    this.name = "ApiError";
  }
}

let unauthorizedHandler: (() => void) | undefined;

export function setUnauthorizedHandler(handler: (() => void) | undefined): void {
  unauthorizedHandler = handler;
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
  schema: ZodType<T>,
  options: ApiRequestOptions = {},
): Promise<T> {
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
    if (response.status === 401 && !suppressUnauthorizedHandler) {
      unauthorizedHandler?.();
    }
    throw new ApiError(response.status, code, requestId, failureKind(response.status));
  }
  if (response.status === 204) return schema.parse(undefined);
  return schema.parse(await response.json());
}
