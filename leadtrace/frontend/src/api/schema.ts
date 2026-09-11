import { z } from "zod";

export const roleSchema = z.enum(["visitor", "reviewer", "admin"]);

export const authUserSchema = z.object({
  username: z.string(),
  display_name: z.string(),
  role: roleSchema,
  must_change_password: z.boolean(),
});

export const authenticationResponseSchema = z.object({
  user: authUserSchema,
  csrf_token: z.string().min(1),
});

export const apiErrorSchema = z.object({
  code: z.string(),
  message: z.string(),
  details: z.record(z.string(), z.unknown()).default({}),
  request_id: z.string(),
});

export const releaseSchema = z.object({
  id: z.string().uuid(),
  key: z.string(),
  title: z.string(),
  published_at: z.string(),
});

export const metricSchema = z.object({
  numerator: z.number().int().nonnegative(),
  denominator: z.number().int().nonnegative(),
  unit: z.string(),
});

export const overviewSchema = z.object({
  request_id: z.string(),
  release: releaseSchema,
  metrics: z.object({
    corpus: metricSchema,
    lineage: metricSchema,
    relation: metricSchema,
    structure: metricSchema,
    pair: metricSchema,
    human_review: metricSchema,
  }),
});

export const paperSummarySchema = z.object({
  id: z.string().uuid(),
  revision_id: z.string().uuid(),
  paper_key: z.string(),
  doi: z.string().nullable(),
  title: z.string(),
  year: z.string().nullable(),
  target: z.string().nullable(),
  review_status: z.string().nullable(),
});

export const paperListSchema = z.object({
  request_id: z.string(),
  release: releaseSchema,
  pagination: z.object({
    page: z.number().int().positive(),
    page_size: z.number().int().positive(),
    total_items: z.number().int().nonnegative(),
    total_pages: z.number().int().nonnegative(),
  }),
  filters: z.record(z.string(), z.unknown()),
  items: z.array(paperSummarySchema),
});

export type UserRole = z.infer<typeof roleSchema>;
export type AuthUser = z.infer<typeof authUserSchema>;
export type AuthenticationResponse = z.infer<typeof authenticationResponseSchema>;
export type OverviewResponse = z.infer<typeof overviewSchema>;
export type PaperListResponse = z.infer<typeof paperListSchema>;
