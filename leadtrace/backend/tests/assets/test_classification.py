from __future__ import annotations

from pathlib import PurePosixPath

import pytest

from app.assets.models import AssetCategory
from app.assets.scanner import classify_source_asset


@pytest.mark.parametrize(
    ("source_key", "expected"),
    [
        ("papers/article.pdf", AssetCategory.ARTICLE_PDF),
        ("papers/jm4c01234_si_001.pdf", AssetCategory.SI_PDF),
        ("supporting/SI table 1.xlsx", AssetCategory.SI_TABLE),
        ("supporting/supplementary-data.zip", AssetCategory.SI_ARCHIVE),
        ("external/pubchem/source.json", AssetCategory.EXTERNAL_SOURCE),
        ("05_visual_review/explicit_path_pages/page-1.png", AssetCategory.PAGE_RENDER),
        ("renders/thumbnails/page-1.png", AssetCategory.PAGE_THUMBNAIL),
        ("evidence/crops/EVID-1.png", AssetCategory.EVIDENCE_CROP),
        ("08_ocsr_benchmark/crops/CROP-1.png", AssetCategory.OCSR_INPUT),
        ("08_ocsr_benchmark/ocsr_proposals.csv", AssetCategory.OCSR_PROPOSAL),
        ("reviewed/molecule_objects/object-1.png", AssetCategory.REVIEWED_CROP),
        (
            "09_structure_confirmation/generated_structures/CMP-1.png",
            AssetCategory.RDKIT_STRUCTURE,
        ),
        ("molecule_pair_structures/PAIR-1.png", AssetCategory.PAIR_PANEL),
        ("01_manifest/all_volume67_papers.csv", AssetCategory.IMPORT_MANIFEST),
        ("reports/validation_report.json", AssetCategory.VALIDATION_REPORT),
        ("exports/release-1.tar.gz", AssetCategory.RELEASE_EXPORT),
        ("staging/upload-1.bin", AssetCategory.UPLOAD_STAGING),
        ("render_cache/page-1.png", AssetCategory.RENDER_CACHE),
        ("quarantine/rejected.bin", AssetCategory.QUARANTINE),
    ],
)
def test_source_assets_are_classified_into_controlled_categories(
    source_key: str,
    expected: AssetCategory,
) -> None:
    assert classify_source_asset(PurePosixPath(source_key)) is expected


def test_unclassifiable_source_is_rejected() -> None:
    with pytest.raises(ValueError, match="classify"):
        classify_source_asset(PurePosixPath("misc/readme.unknown"))
