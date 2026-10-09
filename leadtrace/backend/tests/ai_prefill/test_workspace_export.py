from datetime import UTC, datetime

import pytest

from app.ai_prefill.assistance_contracts import (
    CandidateEnvelope,
    CandidateRecipe,
    ProducerProvenance,
    SourceIdentity,
    with_computed_hashes,
)
from app.ai_prefill.contracts import AiPrefillPayload
from app.ai_prefill.workspace_export import (
    WorkspaceExportConflictError,
    export_candidate_revision,
)


def original() -> CandidateEnvelope:
    return with_computed_hashes(
        CandidateEnvelope(
            envelope_version=1,
            candidate_id="candidate:v1",
            experiment_id="experiment:test",
            source=SourceIdentity(paper_key="paper-1", source_sha256="a" * 64, byte_size=10, page_count=2),
            producer=ProducerProvenance(kind="local", engine="test", engine_version="1", generated_at=datetime(2026, 1, 1, tzinfo=UTC)),
            recipe=CandidateRecipe(guide_version="guide-v1"),
            payload=AiPrefillPayload.model_validate({"schema_version": 1}),
        )
    )


def test_export_candidate_creates_human_assisted_child_without_mutating_parent() -> None:
    parent = original()

    child = export_candidate_revision(
        parent,
        payload=AiPrefillPayload.model_validate({"schema_version": 1, "bibliography": {"title": "edited"}}),
        candidate_id="candidate:v2",
        evaluation_id="evaluation:1",
        reviewer="reviewer@example.test",
    )

    assert child.parent_candidate_id == parent.candidate_id
    assert child.producer.kind == "human-assisted"
    assert child.payload.bibliography.title == "edited"
    assert child.hashes is not None
    assert parent.candidate_id == "candidate:v1"


def test_export_candidate_rejects_concurrent_workspace_version() -> None:
    with pytest.raises(WorkspaceExportConflictError, match="version"):
        export_candidate_revision(
            original(),
            payload=AiPrefillPayload.model_validate({"schema_version": 1}),
            candidate_id="candidate:v2",
            evaluation_id="evaluation:1",
            reviewer="reviewer@example.test",
            expected_workspace_version=2,
            current_workspace_version=3,
        )


def alias_export_fixture():
    from uuid import uuid4
    compound_id,structure_id,image_id=(str(uuid4()) for _ in range(3))
    locator={'ref':'first-location','compound_ref':'c1','page_number':1,
             'bbox':{'x0':'0.1','y0':'0.2','x1':'0.3','y1':'0.4'},'source_context':'First context','label':'First label'}
    payload=AiPrefillPayload.model_validate({'schema_version':1,'compounds':[{'ref':'c1','compound_label':'1','structure':{'smiles':'C'}}],
        'structure_locators':[locator,{**locator,'ref':'alias-location','source_context':'Second context','label':'Second label',
            'bbox':{**locator['bbox'],'x0':'0.10000000001'}}]})
    parent=original().model_copy(update={'payload':payload,'hashes':None})
    paper={key:None for key in ('title','journal','publication_year','volume','issue','doi')}
    snapshot={'paper':paper,'compounds':[{'id':compound_id,'compound_label':'1','display_name':None,'description':None}],
        'structures':[{'id':structure_id,'compound_id':compound_id,'smiles':'C','molfile':None,'input_method':'smiles','status':'resolved'}],
        'structure_source_images':[{'id':image_id,'compound_id':compound_id,'source_sha256':'a'*64,'page_number':1,
            'x0':'0.1','y0':'0.2','x1':'0.3','y1':'0.4','source_context':'First context\nSecond context','label':'First label','reviewer_note':None}],
        **{key:[] for key in ('lineages','evidence','lineage_members','lineage_edges','edge_evidence_links','activities','sections')}}
    mapping={'/compounds/c1':compound_id,'/structure_locators/first-location':image_id,'/structure_locators/alias-location':image_id}
    return parent,snapshot,mapping


def test_export_accepts_same_occurrence_aliases_with_stable_ref_and_metadata():
    from app.ai_prefill.workspace_export import _payload_from_snapshot
    parent,snapshot,mapping=alias_export_fixture()
    payload,refs,metadata=_payload_from_snapshot(parent,snapshot,mapping,snapshot['paper'])
    assert len(payload.structure_locators)==1
    assert payload.structure_locators[0].ref=='first-location'
    assert refs[snapshot['structure_source_images'][0]['id']]=='first-location'
    item=next(m for m in metadata if m.get('locator_aliases'))
    assert item['path']=='structure_locators/first-location'
    assert item['locator_aliases']==['first-location','alias-location']
    assert item['original_annotations']==[
        {'ref':'first-location','label':'First label','source_context':'First context'},
        {'ref':'alias-location','label':'Second label','source_context':'Second context'}]


@pytest.mark.parametrize('field,value',[('page_number',2),('compound_ref','c2'),('bbox',{'x0':'0.11','y0':'0.2','x1':'0.3','y1':'0.4'})])
def test_export_rejects_unrelated_locator_aliases(field,value):
    from app.ai_prefill.workspace_export import _payload_from_snapshot,WorkspaceExportUnrepresentableError
    parent,snapshot,mapping=alias_export_fixture()
    alias=parent.payload.structure_locators[1]
    if field=='bbox':value=type(alias.bbox).model_validate(value)
    parent.payload.structure_locators[1]=alias.model_copy(update={field:value})
    with pytest.raises(WorkspaceExportUnrepresentableError,match='multiple refs'):
        _payload_from_snapshot(parent,snapshot,mapping,snapshot['paper'])


def test_export_still_rejects_multiple_compound_refs_to_one_row():
    from app.ai_prefill.workspace_export import _payload_from_snapshot,WorkspaceExportUnrepresentableError
    parent,snapshot,mapping=alias_export_fixture()
    parent.payload.compounds.append(parent.payload.compounds[0].model_copy(update={'ref':'c2','compound_label':'2'}))
    mapping['/compounds/c2']=mapping['/compounds/c1']
    with pytest.raises(WorkspaceExportUnrepresentableError,match='multiple refs'):
        _payload_from_snapshot(parent,snapshot,mapping,snapshot['paper'])
