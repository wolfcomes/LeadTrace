"""Explicit visibility predicates. No global ORM filter: recovery/audit retain all rows."""
from sqlalchemy import String, cast, func, select, union
from sqlalchemy.dialects.postgresql import JSONPATH
from app.papers.models import Paper


def visible_paper_ids():
    return select(Paper.id).where(Paper.removed_at.is_(None))


def visible_asset(asset_id):
    """Hide assets owned by removed papers, including recursively derived files.

    Shared assets remain visible if another live paper explicitly references them.
    Unattached uploads remain available to their ordinary permission checks.
    """
    from app.assets.models import Asset
    from app.catalog.models import PaperSource
    from app.evidence.models import Evidence
    from app.structures.models import Structure
    from app.structure_images.models import StructureSourceImage
    from app.workspaces.models import ChangeEvent, PaperSubmission
    from app.publications.models import PublishedPaperVersion
    # Replaced/deleted depictions and crops may survive only in immutable JSON.
    # Extract text IDs without casting untrusted historical JSON to UUID.
    histories = union(
        select(ChangeEvent.paper_id, ChangeEvent.before_value.label('document')),
        select(ChangeEvent.paper_id, ChangeEvent.after_value),
        select(PaperSubmission.paper_id, PaperSubmission.snapshot),
        select(PublishedPaperVersion.paper_id, PublishedPaperVersion.snapshot),
    ).cte('paper_asset_history')
    historical_refs = []
    for field in ('depiction_asset_id', 'crop_asset_id'):
        values = func.jsonb_array_elements_text(
            func.jsonb_path_query_array(histories.c.document, cast('$.**.' + field, JSONPATH))
        ).table_valued('value', joins_implicitly=True)
        historical_refs.append(select(values.c.value.label('asset_id'), histories.c.paper_id)
                               .select_from(histories).select_from(values))
    refs = union(
        select(cast(PaperSource.asset_id, String).label('asset_id'), Paper.id.label('paper_id')).join(Paper, Paper.source_id == PaperSource.id),
        select(cast(Structure.depiction_asset_id, String), Structure.paper_id).where(Structure.depiction_asset_id.is_not(None)),
        select(cast(Evidence.crop_asset_id, String), Evidence.paper_id).where(Evidence.crop_asset_id.is_not(None)),
        select(cast(StructureSourceImage.crop_asset_id, String), StructureSourceImage.paper_id).where(StructureSourceImage.crop_asset_id.is_not(None)),
        *historical_refs,
    ).cte('paper_asset_refs')
    refs = select(refs.c.asset_id, refs.c.paper_id).where(refs.c.asset_id.is_not(None)).cte('paper_asset_tree', recursive=True)
    refs = refs.union(select(cast(Asset.id, String), refs.c.paper_id).join(refs, cast(Asset.source_asset_id, String) == refs.c.asset_id))
    removed = select(refs.c.asset_id).join(Paper, Paper.id == refs.c.paper_id).where(Paper.removed_at.is_not(None))
    live = select(refs.c.asset_id).join(Paper, Paper.id == refs.c.paper_id).where(Paper.removed_at.is_(None))
    return asset_id.is_(None) | cast(asset_id, String).not_in(removed) | cast(asset_id, String).in_(live)
