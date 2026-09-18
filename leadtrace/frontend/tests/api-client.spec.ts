import { afterEach, describe, expect, it, vi } from "vitest";
import { z } from "zod";

import {
  apiRequest,
  setCsrfValidationFailedHandler,
} from "../src/api/client";

describe("API client error handlers", () => {
  afterEach(() => {
    setCsrfValidationFailedHandler(undefined);
    vi.unstubAllGlobals();
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
