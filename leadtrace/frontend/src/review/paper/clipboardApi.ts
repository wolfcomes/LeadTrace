import { z } from 'zod';
import { apiRequest } from '../../api/client';

export const pasteRecord = (workspaceId: string, kind: 'compound' | 'lineage', payload: { source_id: string; expected_workspace_version: number; label: string; display_name?: string | null }, csrfToken: string | null) => apiRequest(`/api/v2/workspaces/${workspaceId}/clipboard/${kind}`, z.object({ entity_id: z.string().uuid(), workspace_version: z.number() }), { method: 'POST', csrfToken, body: payload });
