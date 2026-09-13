"""allow only one active review task per Paper

Revision ID: 0017_unique_active_review_task
Revises: 0016_initial_baseline_release
"""

from collections.abc import Sequence

from alembic import op


revision: str = "0017_unique_active_review_task"
down_revision: str | None = "0016_initial_baseline_release"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM review_tasks
                WHERE status <> 'completed'
                GROUP BY paper_id
                HAVING count(*) > 1
            ) THEN
                RAISE EXCEPTION
                    'cannot enforce one active review task per Paper: duplicate active tasks exist';
            END IF;
        END;
        $$
        """
    )
    op.drop_index(
        "uq_review_tasks_active_assignment",
        table_name="review_tasks",
    )
    op.create_index(
        "uq_review_tasks_active_paper",
        "review_tasks",
        ["paper_id"],
        unique=True,
        postgresql_where="status <> 'completed'",
    )


def downgrade() -> None:
    op.drop_index(
        "uq_review_tasks_active_paper",
        table_name="review_tasks",
    )
    op.create_index(
        "uq_review_tasks_active_assignment",
        "review_tasks",
        ["paper_id", "assigned_reviewer_id"],
        unique=True,
        postgresql_where="status <> 'completed'",
    )
