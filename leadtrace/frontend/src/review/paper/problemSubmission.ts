import { z } from 'zod';
import { apiRequest } from '../../api/client';
import { locale } from '../../i18n';

export function problemText(zh: string, en: string): string {
  return locale.value === 'en' ? en : zh;
}

export function submitProblem(workspaceId: string, version: number, reason: string, csrfToken: string | null, idempotencyKey: string) {
  return apiRequest('/api/v2/workspaces/' + encodeURIComponent(workspaceId) + '/submit-problem',
    z.object({workspace_version: z.number().int().positive()}), {
      method: 'POST', csrfToken,
      headers: {'Idempotency-Key': idempotencyKey},
      body: {expected_workspace_version: version, reason},
    });
}
