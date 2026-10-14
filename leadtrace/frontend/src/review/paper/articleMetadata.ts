import { z } from 'zod';
export const sourcedTermSchema = z.object({label:z.string(),source:z.string(),review_hint:z.string().nullable().optional()}).strict();
export const targetRoleLabels = {primary:'主要靶点',co_primary:'共同主要靶点',selectivity:'选择性对照',off_target:'脱靶检测',mechanistic:'机制相关',biomarker:'生物标志物',unknown:'角色待核对'} as const;
export const articleTargetSchema = z.object({
  name:z.string(), role:z.enum(['primary','co_primary','selectivity','off_target','mechanistic','biomarker','unknown']),
  organism:z.string().nullable().optional(),gene_symbol:z.string().nullable().optional(),
  uniprot_id:z.string().nullable().optional(),ncbi_gene_id:z.string().nullable().optional(),
  source:z.string(),review_hint:z.string().nullable().optional(),
}).strict();
export const profileGroups = [
  {key:'molecular_forms',label:'分子形式',suggestions:['Small molecule','Macrocycle','Peptide','Peptidomimetic']},
  {key:'modalities',label:'作用模态',suggestions:['Direct target modulation','PROTAC','Molecular glue']},
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
