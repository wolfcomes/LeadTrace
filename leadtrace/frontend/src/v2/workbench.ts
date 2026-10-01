import { z } from 'zod';
import { apiRequest } from '../api/client';
export const pdbReferenceSchema = z.object({
  pdb_id: z.string(), usage: z.enum(['this_work','cited_structure','unknown']),
  source_page: z.number().int().positive().nullable().optional(), source_context: z.string().nullable().optional(),
  compound_label: z.string().nullable().optional(), review_hint: z.string().nullable().optional(),
}).strict();
export type PdbReference = z.infer<typeof pdbReferenceSchema>;
export const articleMetadataFields = {
  abstract: z.string().nullable().optional(), abstract_source: z.string().nullable().optional(),
  pdb_references: z.array(pdbReferenceSchema).optional(),
};
export const viewItemSchema = z.object({kind: z.enum(['compound','lineage']),entity_id:z.string().uuid(),section_key:z.string(),label:z.string(),signature:z.string(),viewed:z.boolean()});
export type ViewItem = z.infer<typeof viewItemSchema>;
export const progressSchema = z.object({workspace_id:z.string().uuid(),workspace_version:z.number(),tracking_started:z.boolean(),items:z.array(viewItemSchema),sections:z.array(z.object({section_key:z.string(),total:z.number(),viewed:z.number(),complete:z.boolean(),state:z.string(),note:z.string().nullable()}))});
export type ReviewProgress = z.infer<typeof progressSchema>;
export const getReviewProgress = (id:string) => apiRequest(`/api/v2/workspaces/${id}/review-progress`,progressSchema);
export const recordView = (id:string,item:ViewItem,viewed:boolean,csrfToken:string|null) => apiRequest(`/api/v2/workspaces/${id}/views`,progressSchema,{method:'POST',csrfToken,body:{kind:item.kind,entity_id:item.entity_id,signature:item.signature,viewed}});
const pointSchema=z.object({x:z.number(),y:z.number()});
const controlSchema=z.object({distance:z.number(),weight:z.number()});
export const layoutSchema=z.object({revision:z.number(),mode:z.enum(['points','structures']),positions:z.record(pointSchema),edge_controls:z.record(controlSchema)});
export type GraphLayout=z.infer<typeof layoutSchema>;
export const getGraphLayout=(id:string,mode:string)=>apiRequest(`/api/v2/lineages/${id}/layouts/${mode}`,layoutSchema);
export const saveGraphLayout=(id:string,layout:GraphLayout,csrfToken:string|null)=>apiRequest(`/api/v2/lineages/${id}/layouts/${layout.mode}`,layoutSchema,{method:'PUT',csrfToken,body:{expected_revision:layout.revision,positions:layout.positions,edge_controls:layout.edge_controls}});
