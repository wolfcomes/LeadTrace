import { expect, it } from 'vitest';
import * as comparison from '../src/review/paper/activityComparison';
import {activities, compounds} from './paper-science-v2-fixtures';

it('groups exact assay/metric/unit with distinct condition columns and unique Compound counts', () => {
  expect(comparison.measurementGroups).toBeTypeOf('function');
  const base={...activities[0]!,operator:'=' as const};
  const rows=[{...base,context:'Human'}, {...base,id:'duplicate',context:'Human'}, {...base,id:'mouse',context:'Mouse'}, {...base,id:'other',compound_id:compounds[1]!.id,context:'Mouse'}, {...base,id:'unit',unit:'μM',context:'Human'}, {...base,id:'assay',assay_name:base.assay_name+' ',context:'Human'}];
  const groups=comparison.measurementGroups(rows);
  expect(groups).toHaveLength(3);
  expect(groups[0]!.compoundCount).toBe(2);
  expect(groups[0]!.columns.map(c=>c.context)).toEqual(['Mouse','Human']);
  expect(groups[0]!.columns.map(c=>c.compoundCount)).toEqual([2,1]);
});

it('keeps identical measurement sets contiguous, similar sets adjacent and labels natural', () => {
  expect(comparison.orderByMeasurementSimilarity).toBeTypeOf('function');
  const labels=['C10','C1','C2','C4','C3','C5'];
  const rows=labels.map((compound_label,i)=>({...compounds[0]!,id:String(i),compound_label}));
  const profiles=[['A','B'],['D'],['A','B'],['C'],['A'],[]];
  const cells=new Map(rows.map((r,i)=>[r.id,new Map(profiles[i]!.map(k=>[k,[{...activities[0]!,operator:'=' as const}]]))]));
  const order=comparison.orderByMeasurementSimilarity(rows,cells,['A','B','C','D']).map(c=>c.compound_label);
  expect(order).toEqual(['C2','C10','C3','C1','C4','C5']);
  expect(comparison.orderByMeasurementSimilarity([...rows].reverse(),cells,['D','C','B','A']).map(c=>c.compound_label)).toEqual(order);
  expect(comparison.orderByMeasurementSimilarity(rows,cells,['D']).map(c=>c.compound_label)).toEqual(['C1','C2','C3','C4','C5','C10']);
});
