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

export type UserRole = z.infer<typeof roleSchema>;
export type AuthUser = z.infer<typeof authUserSchema>;
export type AuthenticationResponse = z.infer<typeof authenticationResponseSchema>;
