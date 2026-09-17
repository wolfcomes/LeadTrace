from __future__ import annotations

from io import BytesIO

from PIL import Image

from app.assets.models import (
    Asset,
    AssetAccessLevel,
    AssetCategory,
    AssetIntegrityState,
)
from app.assets.storage import LocalAssetStore
from app.compounds.models import Compound
from app.publications.models import AdminDecisionAction
from app.publications.service import PublicationService
from app.structures.models import Structure, StructureInputMethod, StructureStatus
from app.users.models import User


def _png_bytes(color: str = "white") -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (2, 2), color=color).save(buffer, format="PNG")
    return buffer.getvalue()


def test_published_asset_only_serves_current_snapshot_derivatives(
    publication_fixture,
):
    fixture = publication_fixture
    content = _png_bytes()
    store = LocalAssetStore(fixture.client.app.state.settings.asset_root)
    stored = store.put_bytes(content, suffix=".png", namespace="published-test")
    unreferenced_stored = store.put_bytes(
        _png_bytes("black"),
        suffix=".png",
        namespace="published-test",
    )

    with fixture.session_factory.begin() as session:
        allowed = Asset(
            storage_key=stored.storage_key,
            original_filename="structure.png",
            sha256=stored.sha256,
            byte_size=stored.byte_size,
            mime_type="image/png",
            width=2,
            height=2,
            category=AssetCategory.RDKIT_STRUCTURE,
            access_level=AssetAccessLevel.ADMIN,
            integrity_state=AssetIntegrityState.VERIFIED,
            derivation_metadata={},
            source_metadata={},
        )
        unreferenced = Asset(
            storage_key=unreferenced_stored.storage_key,
            original_filename="unreferenced.png",
            sha256=unreferenced_stored.sha256,
            byte_size=unreferenced_stored.byte_size,
            mime_type="image/png",
            width=2,
            height=2,
            category=AssetCategory.RDKIT_STRUCTURE,
            access_level=AssetAccessLevel.ADMIN,
            integrity_state=AssetIntegrityState.VERIFIED,
            derivation_metadata={"draft": True},
            source_metadata={},
        )
        session.add_all([allowed, unreferenced])
        session.flush()
        valid_compound = Compound(
            paper_id=fixture.paper_id,
            workspace_id=fixture.workspace_id,
            compound_label="PUB-1",
            sort_order=0,
            created_by_kind="reviewer",
        )
        malicious_compound = Compound(
            paper_id=fixture.paper_id,
            workspace_id=fixture.workspace_id,
            compound_label="PUB-2",
            sort_order=1,
            created_by_kind="reviewer",
        )
        session.add_all([valid_compound, malicious_compound])
        session.flush()
        session.add_all(
            [
                Structure(
                    paper_id=fixture.paper_id,
                    workspace_id=fixture.workspace_id,
                    compound_id=valid_compound.id,
                    smiles="CCO",
                    canonical_smiles="CCO",
                    depiction_asset_id=allowed.id,
                    status=StructureStatus.REVIEWER_CONFIRMED,
                    input_method=StructureInputMethod.MANUAL_SMILES,
                ),
                Structure(
                    paper_id=fixture.paper_id,
                    workspace_id=fixture.workspace_id,
                    compound_id=malicious_compound.id,
                    smiles="CCN",
                    canonical_smiles="CCN",
                    depiction_asset_id=fixture.source_asset_id,
                    status=StructureStatus.REVIEWER_CONFIRMED,
                    input_method=StructureInputMethod.MANUAL_SMILES,
                ),
            ]
        )
        allowed_id = allowed.id
        unreferenced_id = unreferenced.id

    submission = fixture.submit()
    with fixture.session_factory.begin() as session:
        admin = session.get(User, fixture.admin_id)
        assert admin is not None
        PublicationService().decide(
            session,
            submission_id=submission.id,
            content_hash=submission.content_hash,
            action=AdminDecisionAction.APPROVE,
            reason="Approved with publication-safe assets.",
            idempotency_key="publish-assets",
            actor=admin,
        )

    fixture.login("publication.visitor")
    allowed_response = fixture.client.get(
        f"/api/v2/papers/{fixture.paper_id}/assets/{allowed_id}"
    )
    source_response = fixture.client.get(
        f"/api/v2/papers/{fixture.paper_id}/assets/{fixture.source_asset_id}"
    )
    draft_response = fixture.client.get(
        f"/api/v2/papers/{fixture.paper_id}/assets/{unreferenced_id}"
    )
    detail_response = fixture.client.get(f"/api/v2/papers/{fixture.paper_id}")

    assert allowed_response.status_code == 200
    assert allowed_response.content == content
    assert allowed_response.headers["content-type"].startswith("image/png")
    assert source_response.status_code == 404
    assert draft_response.status_code == 404
    assert detail_response.status_code == 200
    assert "workspace_id" not in detail_response.text
