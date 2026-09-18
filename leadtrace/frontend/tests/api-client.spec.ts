import { afterEach, describe, expect, it, vi } from "vitest";
import { z } from "zod";

import {
  apiRequest,
  setCsrfValidationFailedHandler,
  setUnauthorizedHandler,
} from "../src/api/client";

describe("API client error handlers", () => {
  afterEach(() => {
    setCsrfValidationFailedHandler(undefined);
    setUnauthorizedHandler(undefined);
    vi.unstubAllGlobals();
  });

  it("passes the failed request path to the unauthorized handler", async () => {
    const fetch = vi.fn(async () => new Response(JSON.stringify({
      code: "AUTHENTICATION_REQUIRED",
      message: "Authentication required",
      details: {},
      request_id: "unauthorized-context",
    }), {
      status: 401,
      headers: { "Content-Type": "application/json" },
    }));
    vi.stubGlobal("fetch", fetch);
    let handledError: unknown;
    setUnauthorizedHandler((error, context) => {
      handledError = error;
      expect(context).toEqual({ path: "/api/v2/unrelated-read" });
    });

    const thrown = await apiRequest(
      "/api/v2/unrelated-read",
      z.unknown(),
    ).catch((error: unknown) => error);

    expect(thrown).toBe(handledError);
    expect(thrown).toMatchObject({
      code: "AUTHENTICATION_REQUIRED",
      requestId: "unauthorized-context",
    });
    expect(fetch).toHaveBeenCalledOnce();
  });

  it("throws the original CSRF ApiError without replay when its handler rejects", async () => {
    const fetch = vi.fn(async () => new Response(JSON.stringify({
      code: "CSRF_VALIDATION_FAILED",
      message: "CSRF validation failed",
      details: {},
      request_id: "csrf-original",
    }), {
      status: 403,
      headers: { "Content-Type": "application/json" },
    }));
    vi.stubGlobal("fetch", fetch);
    let handledError: unknown;
    setCsrfValidationFailedHandler(async (error, context) => {
      handledError = error;
      expect(context).toEqual({ path: "/api/v2/test" });
      throw new Error("refresh failed");
    });

    const thrown = await apiRequest("/api/v2/test", z.unknown()).catch((error: unknown) => error);

    expect(thrown).toBe(handledError);
    expect(thrown).toMatchObject({
      code: "CSRF_VALIDATION_FAILED",
      requestId: "csrf-original",
    });
    expect(fetch).toHaveBeenCalledOnce();
  });
});
