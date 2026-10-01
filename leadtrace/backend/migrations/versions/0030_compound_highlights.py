"""Article-level Compound selections with explicit evidence and review state."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
revision = "0030_compound_highlights"
down_revision = "0029_reviewer_workbench"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table("compound_highlights",
        *[sa.Column(name, postgresql.UUID(as_uuid=True), nullable=False) for name in
          ("id", "paper_id", "workspace_id", "compound_id", "evidence_id")],
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("scope", sa.String(512), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("review_hint", sa.Text(), nullable=True),
        sa.Column("review_status", sa.String(32), nullable=False),
        sa.Column("created_by_kind", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["compound_id","paper_id","workspace_id"], ["compounds.id","compounds.paper_id","compounds.workspace_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["evidence_id","paper_id","workspace_id"], ["evidence.id","evidence.paper_id","evidence.workspace_id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("workspace_id","compound_id","role","scope", name="uq_compound_highlights_identity"),
        sa.CheckConstraint("role IN ('study_start','paper_selected')", name="ck_highlight_role"),
        sa.CheckConstraint("review_status IN ('draft','reviewer_confirmed','unresolved')", name="ck_highlight_review"),
        sa.CheckConstraint("btrim(scope) <> '' AND btrim(rationale) <> ''", name="ck_highlight_required"),
        sa.CheckConstraint("created_by_kind IN ('reviewer','admin','ai','system')", name="ck_highlight_creator"))
    op.create_index("ix_compound_highlights_workspace", "compound_highlights", ["workspace_id"])

def downgrade():
    op.drop_table("compound_highlights")
