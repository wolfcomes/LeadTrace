from __future__ import annotations

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
import pytest

from app.compounds.models import Compound, normalize_local_label
from app.papers.models import Paper


@pytest.mark.parametrize(
    "label",
    ["26a", "26a′", "26a'", "(R)-26a", "(S)-26a", "26b"],
)
def test_paper_local_labels_preserve_scientific_identity(label: str) -> None:
    assert normalize_local_label(f"  {label}  ") == label


def test_prime_and_stereochemical_labels_remain_distinct_in_one_paper(
    auth_session_factory: sessionmaker[Session],
) -> None:
    with auth_session_factory.begin() as session:
        paper = Paper(paper_key="label-paper", doi="10.1000/labels")
        session.add(paper)
        session.flush()
        labels = ["26a", "26a′", "26a'", "(R)-26a", "(S)-26a", "26b"]
        compounds = [
            Compound(
                paper_id=paper.id,
                local_identity=normalize_local_label(label),
                display_label=label,
                normalized_label=normalize_local_label(label),
            )
            for label in labels
        ]
        session.add_all(compounds)
        session.flush()

        assert [compound.display_label for compound in compounds] == labels
        assert len({compound.id for compound in compounds}) == len(labels)


def test_duplicate_exact_paper_local_identity_is_rejected(
    auth_session_factory: sessionmaker[Session],
) -> None:
    with pytest.raises(IntegrityError):
        with auth_session_factory.begin() as session:
            paper = Paper(paper_key="duplicate-label-paper")
            session.add(paper)
            session.flush()
            session.add_all(
                [
                    Compound(
                        paper_id=paper.id,
                        local_identity="26a′",
                        display_label="26a′",
                        normalized_label="26a′",
                    ),
                    Compound(
                        paper_id=paper.id,
                        local_identity="26a′",
                        display_label="26a′ duplicate",
                        normalized_label="26a′",
                    ),
                ]
            )
