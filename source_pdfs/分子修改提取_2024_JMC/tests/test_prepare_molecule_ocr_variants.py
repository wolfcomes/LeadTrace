import csv

from PIL import Image, ImageDraw

from prepare_molecule_ocr_variants import (
    VARIANT_FIELDS,
    expanded_source_box,
    find_top_ink_bounds,
    select_molecule_objects,
    write_variant_snapshot,
)


def captioned_structure_image(path) -> None:
    image = Image.new("RGB", (240, 180), "white")
    draw = ImageDraw.Draw(image)
    # A deliberately disconnected mock molecular drawing in the upper region.
    draw.line((30, 48, 55, 34, 80, 48, 80, 78, 55, 92, 30, 78, 30, 48), fill="black", width=3)
    draw.line((80, 48, 125, 48), fill="black", width=3)
    draw.text((126, 37), "N", fill="black")
    draw.line((135, 50, 176, 72), fill="black", width=3)
    # The caption is separated from the drawing by an intentionally blank band.
    draw.text((54, 132), "2a in Example Patent", fill="black")
    image.save(path)


def molecule_object(object_id: str, crop_path: str, object_type: str = "molecule_series_member") -> dict[str, str]:
    return {
        "object_id": object_id,
        "paper_id": "paper-1",
        "paper_rank": "1",
        "candidate_id": "PAGE-test-CAND-001",
        "page": "2",
        "object_type": object_type,
        "compound_label": "2a",
        "crop_path": crop_path,
        "smiles_source": "isolated_object_pending_ocsr",
        "localization_status": "isolated_object_ready_for_ocsr",
        "review_status": "object_requires_human_review",
    }


def test_top_ink_bounds_exclude_separated_caption_without_changing_structure_pixels(tmp_path) -> None:
    source = tmp_path / "captioned.png"
    captioned_structure_image(source)

    bounds = find_top_ink_bounds(Image.open(source))

    assert bounds[0] < 30
    assert bounds[1] < 34
    assert bounds[2] > 180
    assert 95 < bounds[3] < 125


def test_selection_excludes_fragments_nonisolated_and_missing_crops() -> None:
    rows = [
        molecule_object("whole", "/tmp/whole.png"),
        molecule_object("fragment", "/tmp/fragment.png", "replacement_fragment"),
        molecule_object("not-ready", "/tmp/not-ready.png"),
        molecule_object("missing", "--"),
    ]
    rows[2]["smiles_source"] = "attachment_point_notation_only"

    assert [row["object_id"] for row in select_molecule_objects(rows)] == ["whole"]


def test_expanded_source_box_adds_limited_horizontal_safety_margin_for_grid_cells() -> None:
    row = molecule_object("OBJ-2a", "/tmp/object.png")
    row.update({
        "source_crop_path": "/tmp/source.png",
        "local_x0": "0.2500", "local_y0": "0.0000",
        "local_x1": "0.5000", "local_y1": "0.2500",
    })

    assert expanded_source_box(row, (400, 320)) == (85, 0, 215, 80)


def test_expanded_source_box_can_expand_only_the_clipped_edge() -> None:
    row = molecule_object("OBJ-2a", "/tmp/object.png")
    row.update({
        "source_crop_path": "/tmp/source.png",
        "local_x0": "0.2500", "local_y0": "0.0000",
        "local_x1": "0.5000", "local_y1": "0.2500",
    })

    assert expanded_source_box(row, (400, 320), expand_left=False, expand_right=True) == (100, 0, 215, 80)


def test_expanded_source_box_rejects_large_or_unlocalised_regions() -> None:
    row = molecule_object("OBJ-table", "/tmp/object.png")
    row.update({
        "source_crop_path": "/tmp/source.png",
        "local_x0": "0.1000", "local_y0": "0.0000",
        "local_x1": "0.9200", "local_y1": "1.0000",
    })

    assert expanded_source_box(row, (400, 320)) is None


def test_snapshot_writes_original_and_label_free_variants_with_parent_provenance(tmp_path) -> None:
    source = tmp_path / "captioned.png"
    captioned_structure_image(source)
    manifest = tmp_path / "variants.csv"
    output_dir = tmp_path / "variants"

    rows, summary = write_variant_snapshot(
        [molecule_object("OBJ-2a", str(source))],
        output_dir,
        manifest,
        tmp_path / "summary.json",
    )

    assert len(rows) == 4
    assert {row["variant_name"] for row in rows} == {
        "original_object_crop", "label_free", "label_free_grayscale", "label_free_thresholded",
    }
    assert set(rows[0]) == set(VARIANT_FIELDS)
    assert summary["objects_processed"] == 1
    assert summary["variant_rows"] == 4
    assert all(row["parent_crop_path"] == str(source) for row in rows)
    rendered_rows = [row for row in rows if row["variant_name"] != "original_object_crop"]
    assert all((output_dir / row["variant_filename"]).is_file() for row in rendered_rows)
    assert max(Image.open(output_dir / row["variant_filename"]).height for row in rendered_rows) < 125
    with manifest.open(encoding="utf-8-sig", newline="") as handle:
        assert len(list(csv.DictReader(handle))) == 4
