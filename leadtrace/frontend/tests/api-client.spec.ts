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

it('preserves the safe server explanation separately from the existing error message contract',async()=>{
  const original=globalThis.fetch;
  globalThis.fetch=async()=>new Response(JSON.stringify({code:'WORKSPACE_CHANGED',message:'The draft changed after generation started.',details:{workspace_version:5},request_id:'job-start'}),{status:409,headers:{'Content-Type':'application/json'}});
  try{const error=await apiRequest('/api/v2/admin/ai-tasks',z.unknown()).catch(value=>value);expect(error).toMatchObject({message:'LeadTrace API request failed (WORKSPACE_CHANGED)',serverMessage:'The draft changed after generation started.',code:'WORKSPACE_CHANGED',requestId:'job-start',details:{workspace_version:5}});}finally{globalThis.fetch=original;}
});
