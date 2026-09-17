from __future__ import annotations

from sqlalchemy import text


def test_paper_submissions_are_immutable_at_database_boundary(auth_session_factory):
    with auth_session_factory.begin() as session:
        tables = session.execute(
            text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_name = 'paper_submissions'"
            )
        ).all()
        assert tables == [("paper_submissions",)]

        columns = {
            row[0]
            for row in session.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'paper_submissions'"
                )
            )
        }
        assert {
            "workspace_id",
            "paper_id",
            "submission_number",
            "idempotency_key",
            "snapshot",
            "content_hash",
            "workspace_version",
            "submitted_by_id",
            "reviewer_note",
            "submitted_at",
        } <= columns

        triggers = session.execute(
            text(
                "SELECT tgname FROM pg_trigger "
                "WHERE tgrelid = 'paper_submissions'::regclass "
                "AND NOT tgisinternal"
            )
        ).scalars().all()
        assert triggers == ["protect_paper_submission"]
