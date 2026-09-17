from __future__ import annotations

from sqlalchemy import inspect, text


def test_publication_schema_binds_decisions_and_versions_to_exact_submissions(
    auth_session_factory,
):
    inspector = inspect(auth_session_factory.kw["bind"])
    assert {"admin_decisions", "published_paper_versions"} <= set(
        inspector.get_table_names()
    )
    assert "current_published_version_id" in {
        column["name"] for column in inspector.get_columns("papers")
    }
    assert "paper_id" in {
        column["name"] for column in inspector.get_columns("admin_decisions")
    }
    assert "decision_action" in {
        column["name"]
        for column in inspector.get_columns("published_paper_versions")
    }

    submission_uniques = {
        (constraint["name"], tuple(constraint["column_names"]))
        for constraint in inspector.get_unique_constraints("paper_submissions")
    }
    assert (
        "uq_paper_submissions_id_paper_hash",
        ("id", "paper_id", "content_hash"),
    ) in submission_uniques

    decision_fks = {
        tuple(foreign_key["constrained_columns"])
        for foreign_key in inspector.get_foreign_keys("admin_decisions")
    }
    version_fks = {
        tuple(foreign_key["constrained_columns"])
        for foreign_key in inspector.get_foreign_keys("published_paper_versions")
    }
    assert ("submission_id", "paper_id", "content_hash") in decision_fks
    assert ("submission_id", "paper_id", "content_hash") in version_fks
    assert (
        "admin_decision_id",
        "paper_id",
        "submission_id",
        "content_hash",
        "decision_action",
    ) in version_fks
    version_checks = {
        constraint["name"]: constraint["sqltext"]
        for constraint in inspector.get_check_constraints(
            "published_paper_versions"
        )
    }
    assert "decision_action" in version_checks[
        "ck_published_versions_approved_decision"
    ]

    with auth_session_factory.begin() as session:
        triggers = set(
            session.scalars(
                text(
                    "SELECT tgname FROM pg_trigger "
                    "WHERE tgrelid IN "
                    "('admin_decisions'::regclass, "
                    "'published_paper_versions'::regclass) "
                    "AND NOT tgisinternal"
                )
            )
        )
    assert triggers == {
        "protect_admin_decision",
        "protect_published_paper_version",
    }
