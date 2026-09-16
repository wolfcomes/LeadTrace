from __future__ import annotations

from rdkit import Chem
from sqlalchemy import func, select

from app.assets.models import Asset, AssetCategory, AssetIntegrityState
from app.structures.models import Structure
from app.workspaces.models import ChangeEvent, PaperWorkspace, WorkspaceState


def _create_compound(science_api_context, csrf: str) -> str:
    response = science_api_context.client.post(
        f"/api/v2/workspaces/{science_api_context.first.workspace_id}/compounds",
        headers={"X-CSRF-Token": csrf},
        json={
            "expected_workspace_version": 1,
            "compound_label": "26a",
            "display_name": "Lead 26a",
        },
    )
    assert response.status_code == 201
    return str(response.json()["compound"]["id"])


def _put_structure(
    science_api_context,
    csrf: str,
    compound_id: str,
    *,
    expected_version: int,
    status: str,
    input_method: str,
    smiles: str | None = None,
    molfile: str | None = None,
):
    payload = {
        "expected_workspace_version": expected_version,
        "status": status,
        "input_method": input_method,
    }
    if smiles is not None:
        payload["smiles"] = smiles
    if molfile is not None:
        payload["molfile"] = molfile
    return science_api_context.client.put(
        f"/api/v2/compounds/{compound_id}/structure",
        headers={"X-CSRF-Token": csrf},
        json=payload,
    )


def test_structure_methods_update_one_row_and_preserve_old_values(
    science_api_context,
) -> None:
    csrf = science_api_context.login("science.api.reviewer")
    compound_id = _create_compound(science_api_context, csrf)

    ai_prefill = _put_structure(
        science_api_context,
        csrf,
        compound_id,
        expected_version=2,
        status="draft",
        input_method="ai_prefill",
        smiles="C(C)O",
    )
    assert ai_prefill.status_code == 200
    ai_payload = ai_prefill.json()
    structure_id = ai_payload["structure"]["id"]
    assert ai_payload["workspace_version"] == 3
    assert ai_payload["structure"]["smiles"] == "C(C)O"
    assert ai_payload["structure"]["canonical_smiles"] == "CCO"
    assert ai_payload["structure"]["inchi"].startswith("InChI=1S/")
    assert ai_payload["structure"]["inchikey"] == "LFQSCWFLJHTTHZ-UHFFFAOYSA-N"
    assert ai_payload["structure"]["depiction_asset_id"] is not None

    manual = _put_structure(
        science_api_context,
        csrf,
        compound_id,
        expected_version=3,
        status="reviewer_confirmed",
        input_method="manual_smiles",
        smiles="CCN",
    )
    assert manual.status_code == 200
    assert manual.json()["workspace_version"] == 4
    assert manual.json()["structure"]["id"] == structure_id
    assert manual.json()["structure"]["canonical_smiles"] == "CCN"
    assert manual.json()["structure"]["status"] == "reviewer_confirmed"

    molecule = Chem.MolFromSmiles("c1ccccc1")
    assert molecule is not None
    molfile = Chem.MolToMolBlock(molecule)
    editor = _put_structure(
        science_api_context,
        csrf,
        compound_id,
        expected_version=4,
        status="draft",
        input_method="structure_editor",
        molfile=molfile,
    )
    assert editor.status_code == 200
    assert editor.json()["workspace_version"] == 5
    assert editor.json()["structure"]["id"] == structure_id
    assert editor.json()["structure"]["smiles"] is None
    assert editor.json()["structure"]["molfile"] == molfile
    assert editor.json()["structure"]["canonical_smiles"] == "c1ccccc1"

    forbidden_derived_fields = science_api_context.client.put(
        f"/api/v2/compounds/{compound_id}/structure",
        headers={"X-CSRF-Token": csrf},
        json={
            "expected_workspace_version": 5,
            "status": "draft",
            "input_method": "manual_smiles",
            "smiles": "CCO",
            "canonical_smiles": "client-controlled",
            "depiction_asset_id": str(science_api_context.first.asset_id),
        },
    )
    assert forbidden_derived_fields.status_code == 422

    with science_api_context.session_factory() as session:
        structures = list(session.scalars(select(Structure)))
        events = list(
            session.scalars(
                select(ChangeEvent)
                .where(
                    ChangeEvent.workspace_id
                    == science_api_context.first.workspace_id
                )
                .order_by(ChangeEvent.occurred_at, ChangeEvent.id)
            )
        )
        assets = list(
            session.scalars(
                select(Asset).where(Asset.category == AssetCategory.RDKIT_STRUCTURE)
            )
        )
        assert len(structures) == 1
        assert [event.action for event in events] == [
            "compound.create",
            "structure.create",
            "structure.update",
            "structure.update",
        ]
        assert events[2].before_value["smiles"] == "C(C)O"
        assert events[2].before_value["canonical_smiles"] == "CCO"
        assert events[2].after_value["smiles"] == "CCN"
        assert events[3].before_value["smiles"] == "CCN"
        assert events[3].after_value["molfile"] == molfile
        assert len(assets) == 3
        assert all(
            asset.integrity_state is AssetIntegrityState.VERIFIED
            and asset.mime_type == "image/png"
            and asset.storage_key.startswith("managed/")
            for asset in assets
        )


def test_invalid_draft_is_saved_without_derived_values_and_clear_statuses_are_explicit(
    science_api_context,
) -> None:
    csrf = science_api_context.login("science.api.reviewer")
    compound_id = _create_compound(science_api_context, csrf)

    invalid_draft = _put_structure(
        science_api_context,
        csrf,
        compound_id,
        expected_version=2,
        status="draft",
        input_method="manual_smiles",
        smiles="not-a-smiles",
    )
    assert invalid_draft.status_code == 200
    assert invalid_draft.json()["workspace_version"] == 3
    assert invalid_draft.json()["structure"] == {
        "id": invalid_draft.json()["structure"]["id"],
        "paper_id": str(science_api_context.first.paper_id),
        "workspace_id": str(science_api_context.first.workspace_id),
        "compound_id": compound_id,
        "smiles": "not-a-smiles",
        "molfile": None,
        "canonical_smiles": None,
        "inchi": None,
        "inchikey": None,
        "depiction_asset_id": None,
        "status": "draft",
        "input_method": "manual_smiles",
    }

    rejected_confirmation = _put_structure(
        science_api_context,
        csrf,
        compound_id,
        expected_version=3,
        status="reviewer_confirmed",
        input_method="manual_smiles",
        smiles="not-a-smiles",
    )
    assert rejected_confirmation.status_code == 422
    assert rejected_confirmation.json()["code"] == "STRUCTURE_INVALID"

    cleared = _put_structure(
        science_api_context,
        csrf,
        compound_id,
        expected_version=3,
        status="unresolved",
        input_method="manual_smiles",
    )
    assert cleared.status_code == 200
    assert cleared.json()["workspace_version"] == 4
    assert all(
        cleared.json()["structure"][field] is None
        for field in (
            "smiles",
            "molfile",
            "canonical_smiles",
            "inchi",
            "inchikey",
            "depiction_asset_id",
        )
    )

    not_reported = _put_structure(
        science_api_context,
        csrf,
        compound_id,
        expected_version=4,
        status="not_reported",
        input_method="manual_smiles",
    )
    assert not_reported.status_code == 200
    assert not_reported.json()["workspace_version"] == 5

    empty_draft = _put_structure(
        science_api_context,
        csrf,
        compound_id,
        expected_version=5,
        status="draft",
        input_method="manual_smiles",
    )
    assert empty_draft.status_code == 422
    assert empty_draft.json()["code"] == "STRUCTURE_INVALID"

    with science_api_context.session_factory() as session:
        workspace = session.get(
            PaperWorkspace, science_api_context.first.workspace_id
        )
        structure = session.scalar(
            select(Structure).where(Structure.compound_id == compound_id)
        )
        event_count = session.scalar(
            select(func.count())
            .select_from(ChangeEvent)
            .where(
                ChangeEvent.workspace_id == science_api_context.first.workspace_id
            )
        )
        assert workspace is not None
        assert structure is not None
        assert workspace.version == 5
        assert structure.status.value == "not_reported"
        assert event_count == 4


def test_structure_noop_version_assignment_state_and_role_boundaries(
    science_api_context,
) -> None:
    csrf = science_api_context.login("science.api.reviewer")
    aggregate = science_api_context.first
    compound_id = _create_compound(science_api_context, csrf)

    created = _put_structure(
        science_api_context,
        csrf,
        compound_id,
        expected_version=2,
        status="draft",
        input_method="manual_smiles",
        smiles="CCO",
    )
    assert created.status_code == 200
    structure_id = created.json()["structure"]["id"]
    depiction_id = created.json()["structure"]["depiction_asset_id"]

    identical = _put_structure(
        science_api_context,
        csrf,
        compound_id,
        expected_version=3,
        status="draft",
        input_method="manual_smiles",
        smiles="CCO",
    )
    assert identical.status_code == 200
    assert identical.json()["workspace_version"] == 3
    assert identical.json()["structure"]["id"] == structure_id
    assert identical.json()["structure"]["depiction_asset_id"] == depiction_id

    stale = _put_structure(
        science_api_context,
        csrf,
        compound_id,
        expected_version=2,
        status="draft",
        input_method="manual_smiles",
        smiles="CCN",
    )
    assert stale.status_code == 409
    assert stale.json()["code"] == "WORKSPACE_VERSION_CONFLICT"

    other_csrf = science_api_context.login("science.api.other")
    concealed = _put_structure(
        science_api_context,
        other_csrf,
        compound_id,
        expected_version=3,
        status="draft",
        input_method="manual_smiles",
        smiles="CCN",
    )
    assert concealed.status_code == 404

    admin_csrf = science_api_context.login("science.api.admin")
    admin_write = _put_structure(
        science_api_context,
        admin_csrf,
        compound_id,
        expected_version=3,
        status="draft",
        input_method="manual_smiles",
        smiles="CCN",
    )
    assert admin_write.status_code == 403

    with science_api_context.session_factory.begin() as session:
        workspace = session.get(PaperWorkspace, aggregate.workspace_id)
        assert workspace is not None
        workspace.state = WorkspaceState.SUBMITTED

    reviewer_csrf = science_api_context.login("science.api.reviewer")
    readonly = _put_structure(
        science_api_context,
        reviewer_csrf,
        compound_id,
        expected_version=3,
        status="draft",
        input_method="manual_smiles",
        smiles="CCN",
    )
    assert readonly.status_code == 409
    assert readonly.json()["code"] == "WORKSPACE_READ_ONLY"

    with science_api_context.session_factory() as session:
        workspace = session.get(PaperWorkspace, aggregate.workspace_id)
        event_count = session.scalar(
            select(func.count())
            .select_from(ChangeEvent)
            .where(ChangeEvent.workspace_id == aggregate.workspace_id)
        )
        asset_count = session.scalar(
            select(func.count())
            .select_from(Asset)
            .where(Asset.category == AssetCategory.RDKIT_STRUCTURE)
        )
        assert workspace is not None
        assert workspace.version == 3
        assert event_count == 2
        assert asset_count == 1
