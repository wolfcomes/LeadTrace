import { z } from 'zod';
import { apiRequest } from '../api/client';
export const highlightFields = {
  id:z.string().uuid(), compound_id:z.string().uuid(), evidence_id:z.string().uuid(),
  role:z.enum(['study_start','paper_selected']),scope:z.string(),rationale:z.string(),
  review_hint:z.string().nullable().optional(),review_status:z.enum(['draft','reviewer_confirmed','unresolved']),
};
export const publishedHighlightSchema=z.object(highlightFields);
export const highlightSchema=publishedHighlightSchema.extend({paper_id:z.string().uuid(),workspace_id:z.string().uuid(),created_by_kind:z.string()});
export type Highlight=z.infer<typeof highlightSchema>;
export type DisplayHighlight=z.infer<typeof publishedHighlightSchema>;
export type HighlightInput=Pick<Highlight,'compound_id'|'evidence_id'|'role'|'scope'|'rationale'|'review_hint'|'review_status'>;
export const highlightListSchema=z.object({workspace_id:z.string().uuid(),workspace_version:z.number(),items:z.array(highlightSchema),total:z.number()});
const mutationSchema=z.object({highlight:highlightSchema,workspace_version:z.number()});
export const listHighlights=(id:string)=>apiRequest(`/api/v2/workspaces/${id}/compound-highlights`,highlightListSchema);
export const saveHighlight=(workspaceId:string,id:string|undefined,body:HighlightInput,version:number,csrfToken:string|null)=>apiRequest(id?`/api/v2/compound-highlights/${id}`:`/api/v2/workspaces/${workspaceId}/compound-highlights`,mutationSchema,{method:id?'PATCH':'POST',csrfToken,body:{...body,expected_workspace_version:version}});
export const deleteHighlight=(id:string,version:number,csrfToken:string|null)=>apiRequest(`/api/v2/compound-highlights/${id}`,z.object({deleted_highlight_id:z.string().uuid(),workspace_version:z.number()}),{method:'DELETE',csrfToken,body:{expected_workspace_version:version}});
export const highlightRole=(role:DisplayHighlight['role'])=>role==='study_start'?'研究起点':'论文优选';
export const highlightStatus=(status:DisplayHighlight['review_status'])=>({draft:'标注待审核',reviewer_confirmed:'标注已确认',unresolved:'标注待解决'}[status]);
