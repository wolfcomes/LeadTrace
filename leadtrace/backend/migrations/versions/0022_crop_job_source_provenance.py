"""scope crop job identity to its registered source asset

Revision ID: 0022_crop_job_source_provenance
Revises: 0021_structure_source_image_occurrence_unique
Create Date: 2026-09-16
"""

import sqlalchemy as sa
from alembic import op


revision = "0022_crop_job_source_provenance"
down_revision = "0021_structure_source_image_occurrence_unique"
branch_labels = None
depends_on = None

OLD_CONSTRAINT = "uq_crop_jobs_input_hash"
NEW_CONSTRAINT = "uq_crop_jobs_input_source_asset"


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE crop_jobs AS job
            SET source_asset_id = crop_asset.source_asset_id
            FROM assets AS crop_asset
            JOIN assets AS source_asset
              ON source_asset.id = crop_asset.source_asset_id
            WHERE job.source_asset_id IS NULL
              AND job.status = 'completed'
              AND job.asset_id = crop_asset.id
              AND crop_asset.category = 'evidence_crop'
              AND source_asset.sha256 = job.source_pdf_sha256
              AND source_asset.category IN ('article_pdf', 'si_pdf')
              AND source_asset.mime_type = 'application/pdf'
            """
        )
    )
    op.drop_constraint(
        OLD_CONSTRAINT,
        "crop_jobs",
        type_="unique",
    )
    op.create_unique_constraint(
        NEW_CONSTRAINT,
        "crop_jobs",
        ["input_hash", "source_asset_id"],
        postgresql_nulls_not_distinct=True,
    )


def downgrade() -> None:
    duplicate_hash = op.get_bind().execute(
        sa.text(
            """
            SELECT input_hash
            FROM crop_jobs
            GROUP BY input_hash
            HAVING count(*) > 1
            LIMIT 1
            """
        )
    ).scalar_one_or_none()
    if duplicate_hash is not None:
        raise RuntimeError(
            "crop job provenance downgrade would collapse source-specific "
            "duplicate input hashes; restore the pre-migration backup"
        )
    op.drop_constraint(
        NEW_CONSTRAINT,
        "crop_jobs",
        type_="unique",
    )
    op.create_unique_constraint(
        OLD_CONSTRAINT,
        "crop_jobs",
        ["input_hash"],
    )
