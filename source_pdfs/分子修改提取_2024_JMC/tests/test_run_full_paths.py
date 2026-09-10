import sys
from pathlib import Path


SCRIPTS_DIRECTORY = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIRECTORY))

from run_full_paths import paths_from_evidence


def _row(text: str) -> dict[str, object]:
    return {
        "paper_id": "paper-a",
        "doi": "10.1021/example",
        "source_pdf": "paper.pdf",
        "page": "4",
        "activity_mentions": "",
        "evidence_text": text,
    }


def test_paths_from_evidence_expands_replacement_of_label_with_multiple_products() -> None:
    paths = paths_from_evidence(
        _row(
            "Replacement of the 5-F group of 21 with 5-Cl (28) or "
            "5-Br (29) led to an increase of potency."
        ),
        1,
    )

    assert [(path["parent_compound"], path["derived_compound"]) for path in paths] == [
        ("21", "28"),
        ("21", "29"),
    ]
    assert all(path["relation_type"] == "explicit_directed_replacement" for path in paths)
    assert all(path["confidence"] == "explicit_text_pair" for path in paths)


def test_paths_from_evidence_expands_changed_label_to_multiple_products() -> None:
    paths = paths_from_evidence(
        _row(
            "When 5-Cl (28) was changed to 4-Cl (32), 6-Cl (33), or "
            "7-Cl (34), activity decreased."
        ),
        2,
    )

    assert [(path["parent_compound"], path["derived_compound"]) for path in paths] == [
        ("28", "32"),
        ("28", "33"),
        ("28", "34"),
    ]


def test_paths_from_evidence_uses_comparison_wording_only_when_subject_and_reference_are_explicit() -> None:
    paths = paths_from_evidence(
        _row(
            "The gem-dimethyl substitution resulted in compound 8s, "
            "with slightly reduced activity compared to 8r."
        ),
        3,
    )

    assert [(path["parent_compound"], path["derived_compound"]) for path in paths] == [
        ("8r", "8s"),
    ]
    assert paths[0]["relation_type"] == "explicit_directed_comparison"
    assert paths[0]["confidence"] == "explicit_text_pair"
