import { z } from "zod";


const checkSchema = z.object({
  status: z.enum(["ok", "unavailable"]),
});

const readinessSchema = z.object({
  status: z.enum(["ready", "unavailable"]),
  checks: z.object({
    asset_root: checkSchema,
    database: checkSchema,
  }),
});

export type Readiness = z.infer<typeof readinessSchema>;

export class ApiRequestError extends Error {
  constructor(readonly status: number) {
    super(`LeadTrace API request failed with status ${status}`);
    this.name = "ApiRequestError";
  }
}
export async function fetchReadiness(signal?: AbortSignal): Promise<Readiness> {
  const response = await fetch("/health/ready", {
    headers: { Accept: "application/json" },
    signal,
  });
  if (response.status !== 200 && response.status !== 503) {
    throw new ApiRequestError(response.status);
  }
  return readinessSchema.parse(await response.json());
}
