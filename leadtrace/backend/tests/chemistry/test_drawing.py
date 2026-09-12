from __future__ import annotations

from app.chemistry.drawing import DrawingOptions, drawing_key, render_structure_png


def test_drawing_key_is_canonical_and_versions_every_render_input() -> None:
    options = DrawingOptions(width=420, height=280, atom_indices=False)

    first = drawing_key("C1=CC=CC=C1", options=options, rdkit_version="2025.09.1", render_version="v1")
    canonical = drawing_key("c1ccccc1", options=options, rdkit_version="2025.09.1", render_version="v1")
    resized = drawing_key(
        "c1ccccc1",
        options=DrawingOptions(width=421, height=280, atom_indices=False),
        rdkit_version="2025.09.1",
        render_version="v1",
    )
    upgraded = drawing_key("c1ccccc1", options=options, rdkit_version="2025.09.2", render_version="v1")

    assert first == canonical
    assert first != resized
    assert first != upgraded


def test_rdkit_drawing_is_a_nonempty_png() -> None:
    content = render_structure_png("F[C@H](Cl)Br", options=DrawingOptions(width=320, height=240))

    assert content.startswith(b"\x89PNG\r\n\x1a\n")
    assert len(content) > 500
