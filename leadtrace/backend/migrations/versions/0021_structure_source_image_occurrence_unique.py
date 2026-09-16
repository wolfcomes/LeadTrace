"""make structure source image occurrences unique

Revision ID: 0021_structure_source_image_occurrence_unique
Revises: 0020_paper_science_records
Create Date: 2026-09-16
"""

from alembic import op

revision = "0021_structure_source_image_occurrence_unique"
down_revision = "0020_paper_science_records"
branch_labels = None
depends_on = None

CONSTRAINT_NAME = "uq_structure_source_images_compound_occurrence"
COLUMNS = [
    "compound_id",
    "source_sha256",
    "page_number",
    "x0",
    "y0",
    "x1",
    "y1",
]


def upgrade() -> None:
    op.create_unique_constraint(
        CONSTRAINT_NAME,
        "structure_source_images",
        COLUMNS,
    )


def downgrade() -> None:
    op.drop_constraint(
        CONSTRAINT_NAME,
        "structure_source_images",
        type_="unique",
    )
