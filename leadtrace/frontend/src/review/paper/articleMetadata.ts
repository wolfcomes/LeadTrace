import { z } from 'zod';
export const articleEvidenceSchema = z.object({
  source_kind:z.enum(['main_pdf','supplement','external']),quoted_text:z.string().trim().min(1).max(6000),
  page_number:z.number().int().positive().nullable().optional(),locator:z.string().nullable().optional(),
  source_url:z.string().url().nullable().optional(),source_sha256:z.string().regex(/^[0-9a-f]{64}$/).nullable().optional(),
  bbox:z.object({x:z.number().min(0).max(1),y:z.number().min(0).max(1),width:z.number().positive().max(1),height:z.number().positive().max(1)}).strict().nullable().optional(),
}).strict();
export type ArticleEvidence=z.infer<typeof articleEvidenceSchema>;
export type ArticleSourceContext={paperId:string;pageCount:number;sha256:string};
export const sourcedTermSchema = z.object({label:z.string(),source:z.string(),review_hint:z.string().nullable().optional(),evidence:z.array(articleEvidenceSchema).optional()}).strict();
export const targetRoleLabels = {primary:'主要靶点',co_primary:'共同主要靶点',selectivity:'选择性对照',off_target:'脱靶检测',mechanistic:'机制相关',biomarker:'生物标志物',unknown:'角色待核对'} as const;
export const articleTargetSchema = z.object({
  name:z.string(), role:z.enum(['primary','co_primary','selectivity','off_target','mechanistic','biomarker','unknown']),
  organism:z.string().nullable().optional(),gene_symbol:z.string().nullable().optional(),
  uniprot_id:z.string().nullable().optional(),ncbi_gene_id:z.string().nullable().optional(),
  source:z.string(),review_hint:z.string().nullable().optional(),evidence:z.array(articleEvidenceSchema).optional(),
}).strict();
export const profileGroups = [
  {key:'modalities',label:'作用模态',suggestions:[]},
  {key:'mechanisms',label:'作用方式',suggestions:['Inhibitor','Agonist','Antagonist','Degrader','Covalent','Noncovalent','Reversible','Irreversible','Allosteric']},
  {key:'diseases',label:'疾病与应用方向',suggestions:[]},
  {key:'optimization_goals',label:'优化目标',suggestions:['Potency','Selectivity','Solubility','Metabolic stability','Exposure','Oral bioavailability','Brain penetration','Safety']},
] as const;
export const researchProfileSchema = z.object({
  molecular_forms:z.array(sourcedTermSchema).optional(),modalities:z.array(sourcedTermSchema).optional(),
  mechanisms:z.array(sourcedTermSchema).optional(),diseases:z.array(sourcedTermSchema).optional(),
  optimization_goals:z.array(sourcedTermSchema).optional(),targets:z.array(articleTargetSchema).optional(),
}).strict();
export type ResearchProfile=z.infer<typeof researchProfileSchema>;
export type ArticleTarget=z.infer<typeof articleTargetSchema>;
export const abstractStatusLabels={not_checked:'尚未检查',extracted:'已提取',not_found:'已检查，未找到',needs_review:'待核对'} as const;
export const researchMetadataFields = {
  pmid:z.string().nullable().optional(),pmcid:z.string().nullable().optional(),identifiers_source:z.string().nullable().optional(),
  abstract_status:z.enum(['not_checked','extracted','not_found','needs_review']).optional(),abstract_note:z.string().nullable().optional(),
  research_profile:researchProfileSchema.optional(),
};

export const modalityChoices = ['直接靶点调节','PROTAC','分子胶','前药','其他','待明确'] as const;
export type ModalityChoice = typeof modalityChoices[number];
// Display aliases only. Never rewrite a stored scientific statement during unrelated edits.
const modalityAliases: Record<string,ModalityChoice> = {
  'Direct target modulation':'直接靶点调节','Molecular glue':'分子胶','Prodrug':'前药',
  'Other':'其他','Unknown':'待明确','小分子抑制剂':'直接靶点调节',
  '选择性V1a受体拮抗剂':'直接靶点调节','CdSpoVD 小分子抑制剂':'直接靶点调节',
  '前药特征（43自身亦有活性）':'前药',
};
export function modalityLabel(label:string):ModalityChoice|null {
  return modalityChoices.includes(label as ModalityChoice) ? label as ModalityChoice : modalityAliases[label]??null;
}
export function revealInvalidField(event:Event) {
  const field=event.target as HTMLElement;
  let ancestor=field.parentElement;
  while(ancestor) {if(ancestor instanceof HTMLDetailsElement)ancestor.open=true;ancestor=ancestor.parentElement;}
}
