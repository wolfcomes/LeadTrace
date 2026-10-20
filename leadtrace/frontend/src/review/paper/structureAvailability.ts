export type Availability = 'available' | 'not_reported' | 'not_checked' | 'unresolved';
export type AvailabilityRecord = {
 availability?: string | null; availability_note?: string | null;
 identity_source?: string | null; checked_sources?: string | null;
 status?: string | null; canonical_smiles?: string | null; smiles?: string | null; molfile?: string | null;
};
export const availabilityLabels: Record<Availability,string> = {
 available:'有可用结构',not_reported:'已检查来源中未报告结构',
 not_checked:'来源检查未完成',unresolved:'结构无法判定',
};
export function availabilityOf(row?: AvailabilityRecord | null): Availability {
 if (row?.availability === 'available') return row.canonical_smiles?.trim() ? 'available' : 'unresolved';
 if (row?.availability) return row.availability as Availability;
 if (row?.status === 'not_reported' || row?.status === 'unresolved') return row.status;
 return row?.canonical_smiles?.trim() ? 'available' : row?.smiles || row?.molfile ? 'unresolved' : 'not_checked';
}
export function unavailableDetailsValid(row: AvailabilityRecord): boolean {
 return row.availability !== 'available' && !!row.availability &&
  [row.availability_note,row.identity_source,row.checked_sources].every(v => !!v?.trim());
}
export function structureCounts(compoundIds: string[], rows: (AvailabilityRecord & {compound_id:string})[]) {
 const byId = new Map(rows.map(row => [row.compound_id,row]));
 const counts = {total:compoundIds.length,available:0,not_reported:0,not_checked:0,unresolved:0,confirmed:0};
 for (const id of compoundIds) {
  const row = byId.get(id);
  const availability = availabilityOf(row);
  // A malformed or unparsed available assertion is not a usable molecular graph.
  if (availability === 'available' && !row?.canonical_smiles) counts.unresolved++;
  else counts[availability]++;
  if (row?.status === 'reviewer_confirmed') counts.confirmed++;
 }
 return counts;
}
