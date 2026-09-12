"""add semantic molecule objects and reusable bindings

Revision ID: 0012_molecule_objects
Revises: 0011_regions_jobs
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0012_molecule_objects"
down_revision: str | None = "0011_regions_jobs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "visual_objects",
        sa.Column(
            "object_type",
            sa.String(length=48),
            nullable=False,
            server_default="uncertain",
        ),
    )
    op.alter_column("visual_objects", "object_type", server_default=None)
    op.create_check_constraint(
        "ck_visual_objects_object_type",
        "visual_objects",
        "object_type IN ("
        "'complete_molecule', 'shared_scaffold', 'r_group', 'linker', "
        "'variable_site', 'replacement_fragment', 'multi_structure_region', "
        "'reaction_or_scheme_context', 'mixed_chemical_region', 'non_structure', "
        "'uncertain'"
        ")",
    )

    op.create_table(
        "visual_object_region_bindings",
        sa.Column("visual_object_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("region_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", sa.String(length=64), nullable=False, server_default="source"),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(["visual_object_id"], ["visual_objects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["region_id"], ["visual_regions.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("visual_object_id", "region_id", name="uq_visual_object_region_binding"),
    )
    op.create_index(
        "ix_visual_object_region_object",
        "visual_object_region_bindings",
        ["visual_object_id"],
    )
    op.create_index(
        "ix_visual_object_region_region",
        "visual_object_region_bindings",
        ["region_id"],
    )

    op.create_table(
        "visual_object_asset_bindings",
        sa.Column("visual_object_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("asset_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", sa.String(length=64), nullable=False, server_default="image"),
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(["visual_object_id"], ["visual_objects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("visual_object_id", "asset_id", name="uq_visual_object_asset_binding"),
    )
    op.create_index(
        "ix_visual_object_asset_object",
        "visual_object_asset_bindings",
        ["visual_object_id"],
    )
    op.create_index(
        "ix_visual_object_asset_asset",
        "visual_object_asset_bindings",
        ["asset_id"],
    )

    op.create_table(
        "visual_object_compound_bindings",
        sa.Column("visual_object_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("compound_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("label", sa.String(length=255), nullable=False),
        sa.Column("label_bbox", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("role", sa.String(length=64), nullable=False, server_default="label"),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_visual_object_compound_confidence",
        ),
        sa.ForeignKeyConstraint(["visual_object_id"], ["visual_objects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["compound_id"], ["compounds.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "visual_object_id",
            "compound_id",
            "label",
            name="uq_visual_object_compound_label",
        ),
    )
    op.create_index(
        "ix_visual_object_compound_object",
        "visual_object_compound_bindings",
        ["visual_object_id"],
    )
    op.create_index(
        "ix_visual_object_compound_compound",
        "visual_object_compound_bindings",
        ["compound_id"],
    )

    op.create_table(
        "visual_object_relations",
        sa.Column("source_object_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("target_object_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("relation_type", sa.String(length=64), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.CheckConstraint(
            "source_object_id <> target_object_id",
            name="ck_visual_object_relation_no_self_loop",
        ),
        sa.ForeignKeyConstraint(["source_object_id"], ["visual_objects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["target_object_id"], ["visual_objects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_object_id",
            "target_object_id",
            "relation_type",
            name="uq_visual_object_relation",
        ),
    )
    op.create_index(
        "ix_visual_object_relations_source",
        "visual_object_relations",
        ["source_object_id"],
    )
    op.create_index(
        "ix_visual_object_relations_target",
        "visual_object_relations",
        ["target_object_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_visual_object_relations_target", table_name="visual_object_relations")
    op.drop_index("ix_visual_object_relations_source", table_name="visual_object_relations")
    op.drop_table("visual_object_relations")
    op.drop_index("ix_visual_object_compound_compound", table_name="visual_object_compound_bindings")
    op.drop_index("ix_visual_object_compound_object", table_name="visual_object_compound_bindings")
    op.drop_table("visual_object_compound_bindings")
    op.drop_index("ix_visual_object_asset_asset", table_name="visual_object_asset_bindings")
    op.drop_index("ix_visual_object_asset_object", table_name="visual_object_asset_bindings")
    op.drop_table("visual_object_asset_bindings")
    op.drop_index("ix_visual_object_region_region", table_name="visual_object_region_bindings")
    op.drop_index("ix_visual_object_region_object", table_name="visual_object_region_bindings")
    op.drop_table("visual_object_region_bindings")
    op.drop_constraint(
        "ck_visual_objects_object_type",
        "visual_objects",
        type_="check",
    )
    op.drop_column("visual_objects", "object_type")
