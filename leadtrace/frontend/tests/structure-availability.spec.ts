import { describe, expect, it } from 'vitest';
import { availabilityOf, structureCounts, unavailableDetailsValid } from '../src/review/paper/structureAvailability';

describe('compound identity and structure availability', () => {
 it('counts a sourced entry without counting a resolved molecular structure', () => {
  const rows = [{ compound_id:'a', canonical_smiles:'CC', status:'draft' },
   { compound_id:'b', availability:'not_reported', status:'draft' },
   { compound_id:'c', availability:'not_checked', status:'reviewer_confirmed' }];
  expect(structureCounts(['a','b','c','d'], rows)).toEqual({ total:4, available:1, not_reported:1, not_checked:2, unresolved:0, confirmed:1 });
 });
 it('preserves legacy absence without inventing checked-source metadata', () => {
  expect(availabilityOf({ status:'not_reported' })).toBe('not_reported');
  expect(availabilityOf({ status:'unresolved' })).toBe('unresolved');
  expect(unavailableDetailsValid({ availability:'not_reported' })).toBe(false);
 });
 it('does not describe an invalid available draft as usable chemistry', () => {
  expect(availabilityOf({availability:'available',smiles:'invalid',canonical_smiles:null})).toBe('unresolved');
  expect(availabilityOf({smiles:'invalid',canonical_smiles:null})).toBe('unresolved');
 });
 it('requires all three explanations for a new absence assertion', () => {
  expect(unavailableDetailsValid({ availability:'not_checked',availability_note:'SI unavailable; main text has no diagram',identity_source:'Table 2, row 32a',checked_sources:'Main text; SI unavailable' })).toBe(true);
  expect(unavailableDetailsValid({ availability:'not_checked',availability_note:' ',identity_source:'Table 2',checked_sources:'Main text' })).toBe(false);
 });
});
