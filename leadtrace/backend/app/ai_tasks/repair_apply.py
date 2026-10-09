"""Explicit, version-bound scientific deltas for accepted AI repair proposals.

Caller holds paper/task/workspace locks and owns the transaction. No model or
network call occurs here. Existing rows are updated in place; unchanged rows,
reviewer notes and history remain untouched.
"""
from __future__ import annotations

from copy import deepcopy
from decimal import Decimal, ROUND_HALF_UP
from enum import Enum
import hashlib
from uuid import UUID, uuid4

from sqlalchemy import select

from app.activities.models import Activity
from app.ai_prefill.contracts import AiPrefillPayload
from app.ai_prefill.occurrences import occurrence_groups, occurrence_context
from app.ai_prefill.service import AiPrefillService
from app.compounds.models import Compound, CompoundHighlight
from app.evidence.models import Evidence, EdgeEvidenceLink
from app.lineages.models import Lineage, LineageEdge, LineageMember
from app.papers.models import Paper
from app.structure_images.models import StructureSourceImage, CropStatus
from app.structure_images.service import StructureSourceImageService
from app.structures.models import Structure, StructureStatus, StructureInputMethod
from app.structures.service import StructureDrawingService
from app.workspaces.models import ChangeEvent, ChangeActorKind, PaperSectionReview, PaperSectionState, WorkspaceState
from app.workspaces.snapshot import build_paper_snapshot, canonical_json, canonical_snapshot_hash


class RepairApplyConflict(ValueError):
    """Proposal cannot be applied without changing its reviewed meaning."""


MODELS = {'compounds':Compound, 'structures':Structure, 'lineages':Lineage,
          'members':LineageMember, 'edges':LineageEdge, 'evidence':Evidence,
          'locators':StructureSourceImage, 'activities':Activity,
          'links':EdgeEvidenceLink, 'highlights':CompoundHighlight}
SNAPSHOT_KEYS = {'members':'lineage_members', 'edges':'lineage_edges',
                 'locators':'structure_source_images', 'links':'edge_evidence_links',
                 'highlights':'compound_highlights'}
ENTITY_TYPES = {'members':'lineage_member', 'edges':'lineage_edge', 'locators':'structure_source_image',
                'links':'edge_evidence_link', 'highlights':'compound_highlight',
                'compounds':'compound', 'structures':'structure', 'lineages':'lineage',
                'activities':'activity', 'evidence':'evidence', 'bibliography':'paper'}


def _activity_pairs(before, after):
    """Keep exact records first, then pair changed records within their compound.

    Activities have no external ref. Export's original ordering binds the stable
    old index to the database row; matching exact records first avoids shifting
    untouched measurements when a new row is inserted.
    """
    unmatched=set(range(len(before))); pairs={}
    for j,item in enumerate(after):
        i=next((i for i in sorted(unmatched) if before[i]==item),None)
        if i is not None:pairs[j]=i; unmatched.remove(i)
    for j,item in enumerate(after):
        if j in pairs:continue
        candidates=[i for i in sorted(unmatched) if before[i]['compound_ref']==item['compound_ref']]
        exact=[i for i in candidates if all(before[i].get(k)==item.get(k) for k in ('assay_name','metric','context'))]
        if exact or candidates:
            i=(exact or candidates)[0]; pairs[j]=i; unmatched.remove(i)
    return {j:f'activity:{pairs[j]}' if j in pairs else f'activity:new:{j}' for j in range(len(after))}


def _flat(payload, activity_keys=None):
    data=payload.model_dump(mode='json')
    out={domain:{} for domain in (*MODELS,'bibliography')}
    out['bibliography']['paper']=data['bibliography']
    for item in data['compounds']:
        item=dict(item); ref=item.pop('ref'); out['structures'][ref]=item.pop('structure')
        item.setdefault('review_hint',None); out['compounds'][ref]=item
    for item in data['lineages']:
        item=dict(item); ref=item.pop('ref')
        for member in item.pop('members'):
            out['members'][canonical_json([ref,member['compound_ref']])]={'lineage_ref':ref,**member}
        for edge in item.pop('edges'):
            edge=dict(edge); eref=edge.pop('ref'); edge.setdefault('review_hint',None)
            out['edges'][eref]={'lineage_ref':ref,**edge}
        item.setdefault('lineage_type','unspecified'); out['lineages'][ref]=item
    for item in data['evidence']:
        item=dict(item); ref=item.pop('ref'); out['evidence'][ref]=item
    for group in occurrence_groups(payload.structure_locators):
        item=group[0].model_dump(mode='json'); ref=item.pop('ref')
        item['source_context']=occurrence_context(group); out['locators'][ref]=item
    for index,item in enumerate(data['activities']):
        item=dict(item);item.setdefault('review_hint',None)
        out['activities'][activity_keys[index] if activity_keys else f'activity:{index}']=item
    for item in data['edge_evidence_links']:
        key=canonical_json([item['edge_ref'],item['evidence_ref']])
        if key in out['links']:
            raise RepairApplyConflict('Duplicate Edge/Evidence link; repair must specify one role per pair')
        out['links'][key]=item
    for item in data.get('compound_highlights',[]):
        item=dict(item); ref=item.pop('ref'); item.setdefault('review_hint',None);out['highlights'][ref]=item
    for domain,items in out.items():
        for item in items.values():
            if domain=='activities':item['value']=format(Decimal(item['value']).normalize(),'f')
            if domain in {'evidence','locators'} and item.get('bbox'):
                item['bbox']={key:format(Decimal(value).quantize(Decimal('0.0000000001'),rounding=ROUND_HALF_UP).normalize(),'f') for key,value in item['bbox'].items()}
    return out


def _flats(before,after):
    old=_flat(before)
    old_activities=list(old['activities'].values())
    new_activities=list(_flat(after)['activities'].values())
    return old,_flat(after,_activity_pairs(old_activities,new_activities))


def design_diff(before: AiPrefillPayload, after: AiPrefillPayload) -> dict:
    old,new=_flats(before,after);changes=[];counts={}
    for domain in old:
        counts[domain]={'added':0,'updated':0,'removed':0}
        for ref in sorted(old[domain].keys() | new[domain].keys()):
            left=old[domain].get(ref);right=new[domain].get(ref)
            if left==right:continue
            action='create' if left is None else 'delete' if right is None else 'update'
            counts[domain][{'create':'added','delete':'removed','update':'updated'}[action]]+=1
            changes.append({'domain':domain,'ref':ref,'action':action,'before':left,'after':right})
    result={'changes':changes,'counts':counts,'total_changes':len(changes)}
    result['sha256']=hashlib.sha256(canonical_json(result).encode()).hexdigest()
    return result


def _snapshot_identity(snapshot):
    # Job/report provenance can be appended without changing scientific content.
    return {k:v for k,v in snapshot.items() if k!='ai_provenance'}


def _json_value(value):
    if isinstance(value,(UUID,Decimal)):return str(value)
    if isinstance(value,Enum):return value.value
    return value


def _row_snapshot(row):
    return {col.name:_json_value(getattr(row,col.name)) for col in row.__table__.columns
            if col.name not in {'created_at','updated_at'}}


def _apply_delta(session, *, settings, workspace, source, actor_id, before: AiPrefillPayload,
                after: AiPrefillPayload, baseline_snapshot: dict, entity_refs: dict[str,str], job_id) -> dict:
    """Apply a proposal atomically inside caller's transaction (never commit)."""
    current=build_paper_snapshot(session,workspace.id)
    if workspace.state != WorkspaceState.EDITING or canonical_snapshot_hash(_snapshot_identity(current)) != canonical_snapshot_hash(_snapshot_identity(baseline_snapshot)):
        raise RepairApplyConflict('Workspace changed after review; generate a new review before accepting repairs')
    if not AiPrefillService._source_is_valid(source,after) or current['source']['sha256']!=source.sha256:
        raise RepairApplyConflict('Repair source identity or page range is invalid')
    parsed=AiPrefillService._parse_structures(after)
    if parsed is None:raise RepairApplyConflict('Repair contains an invalid structure')
    old,new=_flats(before,after);diff=design_diff(before,after)
    rows={domain:{str(row.id):row for row in session.scalars(select(model).where(model.workspace_id==workspace.id))}
          for domain,model in MODELS.items()}
    bound={domain:{} for domain in MODELS}
    for domain in ('compounds','lineages','edges','evidence','locators','highlights'):
        for identifier,row in rows[domain].items():
            ref=entity_refs.get(identifier)
            if ref is None or ref not in old[domain] or ref in bound[domain]:
                raise RepairApplyConflict(f'Invalid baseline identity mapping for {domain}')
            bound[domain][ref]=row
    compound_refs={str(row.id):ref for ref,row in bound['compounds'].items()}
    lineage_refs={str(row.id):ref for ref,row in bound['lineages'].items()}
    edge_refs={str(row.id):ref for ref,row in bound['edges'].items()}
    evidence_refs={str(row.id):ref for ref,row in bound['evidence'].items()}
    for row in rows['structures'].values():bound['structures'][compound_refs[str(row.compound_id)]]=row
    for row in rows['members'].values():
        bound['members'][canonical_json([lineage_refs[str(row.lineage_id)],compound_refs[str(row.compound_id)]])]=row
    for row in rows['links'].values():
        bound['links'][canonical_json([edge_refs[str(row.edge_id)],evidence_refs[str(row.evidence_id)]])]=row
    activity_rows=sorted(baseline_snapshot['activities'],key=lambda row:(row.get('sort_order',0),row['id']))
    for index,snapshot in enumerate(activity_rows):bound['activities'][f'activity:{index}']=rows['activities'][snapshot['id']]
    for domain in bound:
        if set(bound[domain])!=set(old[domain]):raise RepairApplyConflict(f'Baseline {domain} no longer matches the frozen candidate')
    # Every editable baseline field must correspond to the frozen DB snapshot;
    # a valid ID map alone does not authorize accepting a different candidate.
    reverse_refs={'compounds':compound_refs,'lineages':lineage_refs,'edges':edge_refs,'evidence':evidence_refs}
    for domain,items in old.items():
        if domain=='bibliography':continue
        for ref,item in items.items():
            row=bound[domain][ref]
            for field,expected in item.items():
                if field=='bbox':
                    for coordinate in ('x0','y0','x1','y1'):
                        actual=getattr(row,coordinate)
                        wanted=Decimal(expected[coordinate]) if expected else None
                        if actual!=wanted:raise RepairApplyConflict(f'Baseline {domain} crop differs from workspace')
                    continue
                if domain=='structures' and expected is None:continue
                if field.endswith('_ref'):
                    target={'compound_ref':'compounds','parent_compound_ref':'compounds','child_compound_ref':'compounds',
                            'lineage_ref':'lineages','edge_ref':'edges','evidence_ref':'evidence'}[field]
                    identifier=getattr(row,field.replace('_ref','_id'))
                    actual=reverse_refs[target][str(identifier)] if identifier else None
                else:actual=getattr(row,field)
                if isinstance(actual,Decimal) and expected is not None:expected=Decimal(expected)
                if actual!=expected:raise RepairApplyConflict(f'Baseline {domain} field {field} differs from workspace')
    if not diff['total_changes']:
        return {**diff,'entity_map':{},'workspace_version':workspace.version}
    # These constraints are immediate, not deferrable. Reject key swaps rather
    # than delete/recreate rows or temporarily change scientifically visible keys.
    natural_keys={
        'compounds':lambda x:(x['compound_label'],),
        'edges':lambda x:(x['lineage_ref'],x['parent_compound_ref'],x['child_compound_ref']),
        'locators':lambda x:(x['compound_ref'],x['page_number'],*[Decimal(x['bbox'][k]).quantize(Decimal('0.0000000001'),rounding=ROUND_HALF_UP) for k in ('x0','y0','x1','y1')]),
        'highlights':lambda x:(x['compound_ref'],x['role'],x['scope']),
    }
    for domain,key in natural_keys.items():
        wanted=[key(item) for item in new[domain].values()]
        if len(wanted)!=len(set(wanted)):
            raise RepairApplyConflict(f'Repair contains duplicate {domain} identities')
        prior_keys={key(item):ref for ref,item in old[domain].items()}
        for ref,item in new[domain].items():
            other=prior_keys.get(key(item))
            if other is not None and other!=ref and (other in new[domain] or domain=='compounds'):
                raise RepairApplyConflict(f'Repair swaps existing {domain} identities; resolve these explicitly before acceptance')
    if set(old['bibliography']['paper'])-set(new['bibliography']['paper']):
        raise RepairApplyConflict('Repair omitted existing bibliography fields; preserve them or explicitly provide a supported empty value')
    paper=session.get(Paper,workspace.paper_id)
    for field,expected in old['bibliography']['paper'].items():
        if getattr(paper,field)!=expected:
            raise RepairApplyConflict('Bibliography baseline differs from workspace')
    changed={(change['domain'],change['ref']) for change in diff['changes']}
    removed={domain:set(old[domain])-set(new[domain]) for domain in MODELS}
    records=[]
    def record(domain,row,before_value,action):
        records.append((domain,row,before_value,action))
    def remove(domain):
        for ref in removed[domain]:
            row=bound[domain].pop(ref);record(domain,row,_row_snapshot(row),'delete');session.delete(row)
        session.flush()
    def values(domain,ref,item):
        data=deepcopy(item)
        for name,target in (('compound_ref','compounds'),('lineage_ref','lineages'),('parent_compound_ref','compounds'),('child_compound_ref','compounds'),('edge_ref','edges'),('evidence_ref','evidence')):
            if name in data:
                target_ref=data.pop(name);data[name.replace('_ref','_id')]=bound[target][target_ref].id if target_ref is not None else None
        if domain in {'evidence','locators'}:
            bbox=data.pop('bbox');data.update({key:Decimal(bbox[key]) if bbox else None for key in ('x0','y0','x1','y1')})
            data['source_sha256']=source.sha256
        if domain=='structures':
            structure=parsed[ref]
            data.update(compound_id=bound['compounds'][ref].id,canonical_smiles=structure.canonical_smiles,
                        inchi=structure.inchi,inchikey=structure.inchikey,status=StructureStatus.DRAFT,
                        input_method=StructureInputMethod.AI_PREFILL,
                        depiction_asset_id=StructureDrawingService(settings.asset_root).draw(session,smiles=structure.canonical_smiles,created_by_id=actor_id).asset.id)
        if domain in {'edges','highlights'}:data['review_status']='draft'
        return data
    def upsert(domain):
        for ref,item in new[domain].items():
            if (domain,ref) not in changed:continue
            row=bound[domain].get(ref);prior=_row_snapshot(row) if row else None
            data=values(domain,ref,item)
            if row is None:
                if domain in {'compounds','lineages','members','edges','activities'}:
                    data['sort_order']=max((r.sort_order for r in bound[domain].values()),default=-1)+1
                if domain=='locators':data.update(crop_status=CropStatus.PENDING,crop_asset_id=None,reviewer_note=None)
                if domain=='evidence':data.update(crop_asset_id=None,reviewer_note=None)
                row=MODELS[domain](id=uuid4(),paper_id=workspace.paper_id,workspace_id=workspace.id,created_by_kind=ChangeActorKind.AI,**data)
                session.add(row);bound[domain][ref]=row
            else:
                for key,value in data.items():setattr(row,key,value)
                if domain in {'locators','evidence'} and any(prior.get(k)!=_json_value(data.get(k)) for k in ('page_number','x0','y0','x1','y1')):
                    row.crop_asset_id=None
                    if domain=='locators':row.crop_status=CropStatus.PENDING
            record(domain,row,prior,'create' if prior is None else 'update')
        session.flush()
    # Child removals happen before FK parent removals. Existing edge endpoints
    # are updated only after all new members exist; old members are removed later.
    for domain in ('links','highlights','activities','edges','locators'):remove(domain)
    for domain in ('compounds','lineages','evidence','structures','members','edges','locators','links','highlights','activities'):upsert(domain)
    for domain in ('members','structures','evidence','lineages','compounds'):remove(domain)
    if old['bibliography']!=new['bibliography']:
        prior=_row_snapshot(paper)
        for key,value in new['bibliography']['paper'].items():
            if value!=old['bibliography']['paper'].get(key):
                if key=='pdb_references' and any(x.get('source_page',0)>source.page_count for x in value if x.get('source_page')):
                    raise RepairApplyConflict('PDB source page is outside article')
                setattr(paper,key,value)
        record('bibliography',paper,prior,'update')
    # Dependent confirmations no longer describe the same scientific claim.
    affected_compounds={ref for domain,ref in changed if domain in {'compounds','structures'}}
    affected_evidence={ref for domain,ref in changed if domain=='evidence'}
    affected_edges={ref for domain,ref in changed if domain=='edges'}
    affected_lineages={ref for domain,ref in changed if domain=='lineages'}
    for change in diff['changes']:
        if change['domain']=='links':
            for value in (change['before'],change['after']):
                if value:affected_edges.add(value['edge_ref'])
        if change['domain']=='members':
            for value in (change['before'],change['after']):
                if value:affected_lineages.add(value['lineage_ref'])
        if change['domain']=='locators':
            for value in (change['before'],change['after']):
                if value:affected_compounds.add(value['compound_ref'])
    for item in new['links'].values():
        if item['evidence_ref'] in affected_evidence:affected_edges.add(item['edge_ref'])
    edge_compounds=set(affected_compounds)
    for change in diff['changes']:
        if change['domain']=='activities':
            for value in (change['before'],change['after']):
                if value:edge_compounds.add(value['compound_ref'])
    for ref,row in bound['structures'].items():
        if ref in affected_compounds and row.status!=StructureStatus.DRAFT:
            prior=_row_snapshot(row);row.status=StructureStatus.DRAFT;record('structures',row,prior,'invalidate')
    for domain in ('edges','highlights'):
        for ref,item in new[domain].items():
            affected=(ref in affected_edges or item.get('lineage_ref') in affected_lineages or
                      item.get('compound_ref') in affected_compounds or item.get('parent_compound_ref') in edge_compounds or
                      item.get('child_compound_ref') in edge_compounds or item.get('evidence_ref') in affected_evidence)
            row=bound[domain][ref]
            if affected and row.review_status!='draft':
                prior=_row_snapshot(row);row.review_status='draft';record(domain,row,prior,'invalidate')
    image_service=StructureSourceImageService(settings.asset_root,source_roots=settings.source_roots)
    for domain,row,prior,action in records:
        if domain=='locators' and action!='delete' and row.crop_status==CropStatus.PENDING:
            image_service.render_source_image_crop(session,source_image=row,actor_id=actor_id)
    for domain,row,prior,action in records:
        metadata={'repair_job_id':str(job_id),'accepted_by_id':str(actor_id)}
        session.add(ChangeEvent(paper_id=workspace.paper_id,workspace_id=workspace.id,
            entity_type=ENTITY_TYPES[domain],entity_id=row.id,action=f'{ENTITY_TYPES[domain]}.repair_{action}',
            before_value={**prior,'_repair':metadata} if prior else None,
            after_value={**_row_snapshot(row),'_repair':metadata} if action!='delete' else None,
            actor_kind=ChangeActorKind.AI,actor_id=None))
    section_domains={'bibliography':{'bibliography'},'compounds':{'compounds','highlights'},'structures':{'structures','locators'},
                     'lineages':{'lineages','members','edges','compounds','structures','activities','evidence','links'},
                     'edge_evidence':{'evidence','links','edges'},'activities':{'activities','compounds','structures','evidence'}}
    # Confirmation invalidations are changes too: a locator-only proposal can
    # revoke a structure, its edges and article selections. Those sections must
    # become pending even when absent from the model's direct payload diff.
    changed_domains={domain for domain,_,_,_ in records}
    for section in session.scalars(select(PaperSectionReview).where(PaperSectionReview.workspace_id==workspace.id)):
        if section_domains.get(str(section.section_key),set()) & changed_domains and section.state!=PaperSectionState.PENDING:
            prior=_row_snapshot(section);section.state=PaperSectionState.PENDING
            session.add(ChangeEvent(paper_id=workspace.paper_id,workspace_id=workspace.id,entity_type='paper_section_review',
                entity_id=section.id,action='paper_section_review.repair_invalidate',before_value=prior,
                after_value={**_row_snapshot(section),'_repair':{'repair_job_id':str(job_id),'accepted_by_id':str(actor_id)}},actor_kind=ChangeActorKind.AI,actor_id=None))
    workspace.version+=1;session.flush()
    entity_map={}
    prefixes={'compounds':'compounds','structures':'compounds','lineages':'lineages','evidence':'evidence','locators':'structure_locators','highlights':'compound_highlights'}
    for domain,prefix in prefixes.items():
        for ref,row in bound[domain].items():entity_map[f'/{prefix}/{ref}'+('/structure' if domain=='structures' else '')]=str(row.id)
    for ref,row in bound['edges'].items():entity_map[f"/lineages/{new['edges'][ref]['lineage_ref']}/edges/{ref}"]=str(row.id)
    for group in occurrence_groups(after.structure_locators):
        for item in group:entity_map[f'/structure_locators/{item.ref}']=str(bound['locators'][group[0].ref].id)
    for index,ref in enumerate(new['activities']):entity_map[f'/activities/{index}']=str(bound['activities'][ref].id)
    for index,ref in enumerate(new['links']):entity_map[f'/edge_evidence_links/{index}']=str(bound['links'][ref].id)
    for lineage_index,lineage in enumerate(after.lineages):
        for member_index,member in enumerate(lineage.members):
            key=canonical_json([lineage.ref,member.compound_ref])
            entity_map[f'/lineages/{lineage_index}/members/{member_index}']=str(bound['members'][key].id)
    from app.ai_prefill.occurrences import occurrence_notes
    return {**diff,'entity_map':entity_map,'workspace_version':workspace.version,
            'delivery_notes':occurrence_notes(after.structure_locators)}


def apply_delta(session, *, settings, workspace, source, actor_id, before: AiPrefillPayload,
                after: AiPrefillPayload, baseline_snapshot: dict, entity_refs: dict[str,str], job_id) -> dict:
    from app.jobs.service import transaction_created_files, cleanup_transaction_created_files
    existing=transaction_created_files(session)
    try:
        with session.begin_nested():
            return _apply_delta(session,settings=settings,workspace=workspace,source=source,actor_id=actor_id,
                before=before,after=after,baseline_snapshot=baseline_snapshot,entity_refs=entity_refs,job_id=job_id)
    except Exception:
        cleanup_transaction_created_files(session,transaction_created_files(session)-existing)
        raise
