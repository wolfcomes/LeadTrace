import type { ArticleTarget, ResearchProfile } from '../review/paper/articleMetadata';
type Term = NonNullable<ResearchProfile['modalities']>[number];
export type ProfileEntry = Term | ArticleTarget;
export type ProfilePair = { before?: ProfileEntry; after?: ProfileEntry };
const equal = (a: ProfileEntry, b: ProfileEntry) => [...new Set([...Object.keys(a), ...Object.keys(b)])].every(key => (a as Record<string, unknown>)[key] === (b as Record<string, unknown>)[key]);
const identity = (entry: ProfileEntry, includeRole: boolean) => 'name' in entry
  ? JSON.stringify([entry.name, entry.organism ?? null, ...(includeRole ? [entry.role] : [])])
  : entry.label;
/** Pair records by content/identity, never by their shifted array position. */
export function pairProfileEntries(before: ProfileEntry[], after: ProfileEntry[]): ProfilePair[] {
  const unmatched = new Set(before.map((_, index) => index));
  const matches = new Map<number, number>();
  // Identical duplicates are interchangeable: consume each exact match once.
  after.forEach((entry, index) => {
    const match = [...unmatched].find(i => equal(before[i]!, entry));
    if (match !== undefined) {matches.set(index, match); unmatched.delete(match);}
  });
  for (const predicate of [ (a: ProfileEntry, b: ProfileEntry) => identity(a, true) === identity(b, true), (a: ProfileEntry, b: ProfileEntry) => identity(a, false) === identity(b, false)]) {
    after.forEach((entry, index) => {
      if (matches.has(index)) return;
      const candidates = [...unmatched].filter(i => predicate(before[i]!, entry));
      const reverse = after.filter((other, i) => !matches.has(i) && predicate(other, entry));
      if (candidates.length === 1 && reverse.length === 1) {matches.set(index, candidates[0]!); unmatched.delete(candidates[0]!);}
    });
  }
  return [...after.map((entry, index) => ({ before: matches.has(index) ? before[matches.get(index)!] : undefined, after: entry })), ...[...unmatched].map(index => ({before: before[index]}))];
}
export function profileEvidenceChanged(pair: ProfilePair): boolean {
  if (!pair.before || !pair.after) return false;
  return ['source', 'review_hint', 'uniprot_id', 'ncbi_gene_id'].some(key =>
    ((pair.before as Record<string, unknown>)[key] ?? null) !== ((pair.after as Record<string, unknown>)[key] ?? null));
}
