from uuid import UUID
from app.compounds.models import Compound
from app.lineages.models import Lineage, LineageMember
from app.structure_images.models import StructureSourceImage
from tests.science_v2.test_edit_history import move, create
from tests.science_v2.test_structure_image_api import _create_image


def _graph(ctx):
    with ctx.session_factory.begin() as session:
        values = dict(paper_id=ctx.first.paper_id, workspace_id=ctx.first.workspace_id)
        compound = Compound(**values, compound_label='layout-compound', sort_order=0, created_by_kind='reviewer')
        first = Lineage(**values, lineage_label='Delete me', sort_order=0)
        second = Lineage(**values, lineage_label='Keep me', sort_order=1)
        session.add_all([compound, first, second]); session.flush()
        for lineage in (first, second):
            session.add(LineageMember(**values, lineage_id=lineage.id, compound_id=compound.id, role='root', sort_order=0))
        session.flush()
        return str(compound.id), str(first.id), str(second.id)


def _layout(ctx, csrf, lid, cid, revision, x):
    result = ctx.client.put(f'/api/v2/lineages/{lid}/layouts/points', headers={'X-CSRF-Token':csrf},
        json={'expected_revision':revision, 'positions':{cid:{'x':x,'y':10}},'edge_controls':{}})
    assert result.status_code == 200, result.text
    return result.json()


def test_lineage_delete_undo_restores_layout_and_preserves_other_layout_saves(science_api_context):
    c=science_api_context; csrf=c.login('science.api.reviewer'); cid,lid,other=_graph(c)
    saved=_layout(c,csrf,lid,cid,0,25)
    _layout(c,csrf,other,cid,0,30)
    removed=c.client.request('DELETE',f'/api/v2/lineages/{lid}',headers={'X-CSRF-Token':csrf},json={'expected_workspace_version':1})
    assert removed.status_code == 200,removed.text
    _layout(c,csrf,other,cid,1,99)
    undone=move(c,csrf,'undo',2)
    assert undone.status_code == 200,undone.text
    restored=c.client.get(f'/api/v2/lineages/{lid}/layouts/points').json()
    assert restored['positions']==saved['positions']
    assert restored['revision']>saved['revision']
    assert c.client.get(f'/api/v2/lineages/{other}/layouts/points').json()['positions'][cid]['x']==99
    stale=c.client.put(f'/api/v2/lineages/{lid}/layouts/points',headers={'X-CSRF-Token':csrf},json={'expected_revision':saved['revision'],'positions':{},'edge_controls':{}})
    assert stale.status_code==409
    edited=_layout(c,csrf,lid,cid,restored['revision'],77)
    assert move(c,csrf,'redo',3).status_code==200
    assert move(c,csrf,'undo',4).status_code==200
    again=c.client.get(f'/api/v2/lineages/{lid}/layouts/points').json()
    assert again['positions']==edited['positions']
    assert again['revision']>edited['revision']


def test_layout_save_does_not_block_scientific_undo_or_get_overwritten(science_api_context):
    c=science_api_context;csrf=c.login('science.api.reviewer');cid,lid,_=_graph(c)
    _layout(c,csrf,lid,cid,0,25)
    result=c.client.patch(f'/api/v2/lineages/{lid}',headers={'X-CSRF-Token':csrf},json={'expected_workspace_version':1,'description':'Edited'})
    assert result.status_code==200,result.text
    _layout(c,csrf,lid,cid,1,99)
    result=move(c,csrf,'undo',2)
    assert result.status_code==200,result.text
    current=c.client.get(f'/api/v2/lineages/{lid}/layouts/points').json()
    assert current['positions'][cid]['x']==99
    assert current['revision']==2


def test_crop_decimal_coordinates_allow_undo_redo_across_requests(science_api_context):
    c=science_api_context;csrf=c.login('science.api.reviewer');cid=create(c,csrf)
    created=_create_image(c,csrf,cid,version=2,bbox={'x0':0.1,'y0':0.2,'x1':0.7,'y1':0.8})
    assert created.status_code==201,created.text
    image=created.json()['source_image'];iid=UUID(image['id'])
    assert image['crop_status']=='ready'
    with c.session_factory() as session:
        row=session.get(StructureSourceImage,iid)
        assert str(row.x0)=='0.1000000000'
    undone=move(c,csrf,'undo',3)
    assert undone.status_code==200,undone.text
    with c.session_factory() as session: assert session.get(StructureSourceImage,iid) is None
    redone=move(c,csrf,'redo',4)
    assert redone.status_code==200,redone.text
    with c.session_factory() as session:
        row=session.get(StructureSourceImage,iid)
        assert str(row.x0)=='0.1000000000'
        assert str(row.crop_asset_id)==image['crop_asset_id']
    updated=c.client.patch(f'/api/v2/structure-source-images/{iid}',headers={'X-CSRF-Token':csrf},json={'expected_workspace_version':5,'bbox':{'x0':0.15,'y0':0.2,'x1':0.7,'y1':0.8}})
    assert updated.status_code==200,updated.text
    result=move(c,csrf,'undo',6)
    assert result.status_code==200,result.text
    with c.session_factory() as session: assert str(session.get(StructureSourceImage,iid).x0)=='0.1000000000'
