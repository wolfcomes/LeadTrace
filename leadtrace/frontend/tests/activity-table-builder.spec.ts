import {expect,it} from 'vitest';
import * as builder from '../src/review/paper/activityTableBuilder';
import type {Activity,Compound} from '../src/v2/types';
const compounds=[{id:'c1',compound_label:'C10'},{id:'c2',compound_label:'C2'},{id:'c3',compound_label:'C3'}] as Compound[];
const base={assay_name:'Assay A',metric:'IC50',unit:'nM',operator:'=',context:'100 nM',value:'0.123456789012345678901'};
const activities=[{...base,id:'a1',compound_id:'c1'},{...base,id:'a2',compound_id:'c1',operator:'<'},{...base,id:'a3',compound_id:'c2',context:'1000 nM'},{...base,id:'b1',compound_id:'c1',assay_name:'Assay B',unit:'μM'},{...base,id:'b2',compound_id:'c3',assay_name:'Assay B',unit:'μM'}] as Activity[];
const col=(id='colA')=>({id,label:'Custom title',assay:'Assay A',metric:'IC50',unit:'nM',activityIds:null});
it('binds exact measurement identity independently of the editable label, without averaging',()=>{
 expect(builder.matchingActivities).toBeTypeOf('function');
 const matched=builder.matchingActivities(col(),activities);
 expect(matched.map(a=>a.id)).toEqual(['a1','a2','a3']);
 expect(matched[0]!.value).toBe('0.123456789012345678901');
 expect(matched[1]!.operator).toBe('<');
 expect(builder.matchingActivities({...col(),label:'1000 nM'},activities)).toEqual(matched);
 expect(builder.matchingActivities({...col(),activityIds:['a2','b1']},activities).map(a=>a.id)).toEqual(['a2']);
});
it('keeps explicit selection stable across condition edits and excludes newly added records',()=>{
 const updated=activities.map(a=>({...a,context:'edited',value:'99'}));updated.push({...updated[0]!,id:'a4'});
 expect(builder.matchingActivities({...col(),activityIds:['a1']},updated).map(a=>[a.id,a.value])).toEqual([['a1','99']]);
 expect(builder.matchingActivities({...col(),activityIds:['deleted']},updated)).toEqual([]);
});
it('creates union and intersection rows based on each chosen column and preserves column order',()=>{
 expect(builder.buildComparisonTable).toBeTypeOf('function');
 const columns=[{...col('B'),assay:'Assay B',unit:'μM'},col()];
 const any=builder.buildComparisonTable(compounds,activities,columns,'any','label');
 expect(any.rows.map(c=>c.id)).toEqual(['c2','c3','c1']);
 expect([...any.cells.get('c1')!.keys()]).toEqual(['B','colA']);
 expect(any.cells.get('c1')!.get('colA')!.map(a=>a.id)).toEqual(['a1','a2']);
 expect(builder.buildComparisonTable(compounds,activities,columns,'all','label').rows.map(c=>c.id)).toEqual(['c1']);
 expect(builder.buildComparisonTable(compounds,activities,[],'all','label').rows).toEqual([]);
 expect(builder.buildComparisonTable(compounds,activities,[...columns,{...col('empty'),activityIds:[]}],'all','label').rows).toEqual([]);
});
it('validates saved configurations and isolates browser keys by user and workspace',()=>{
 expect(builder.parseSavedTables).toBeTypeOf('function');
 const saved={version:1,activeId:'t',tables:[{id:'t',name:'My comparison',columns:[col()],mode:'any',sort:'label'}]};
 expect(builder.parseSavedTables(JSON.stringify(saved))).toEqual(saved);
 expect(builder.parseSavedTables('{broken')).toBeNull();
 expect(builder.parseSavedTables(JSON.stringify({...saved,version:2}))).toBeNull();
 expect(builder.parseSavedTables(JSON.stringify({...saved,tables:[{...saved.tables[0],columns:[col(),col()]}]}))).toBeNull();
 expect(builder.tableStorageKey('a:b','c')).not.toBe(builder.tableStorageKey('a','b:c'));
 expect(builder.tableStorageKey('a','c')).not.toBe(builder.tableStorageKey('b','c'));
});
it('recommends measurements sharing Compound coverage while leaving selection to the reviewer',()=>{
 expect(builder.recommendMeasurements).toBeTypeOf('function');
 const list=builder.recommendMeasurements(activities,[col()]);
 expect(list.find(g=>g.assay==='Assay B')?.sharedCompounds).toBe(1);
 expect(list.find(g=>g.assay==='Assay A')?.sharedCompounds).toBe(2);
 expect(col().activityIds).toBeNull();
});
