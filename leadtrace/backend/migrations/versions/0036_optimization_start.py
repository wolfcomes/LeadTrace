"""Allow evidence-backed subsequent optimization starting-point annotations."""
from alembic import op

revision = '0036_optimization_start'
down_revision = '0035_article_metadata'
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint('ck_highlight_role', 'compound_highlights', type_='check')
    op.create_check_constraint('ck_highlight_role', 'compound_highlights',
                               "role IN ('study_start', 'paper_selected', 'optimization_start')")


def downgrade():
    # Fail transactionally if new annotations exist; never delete or relabel science.
    op.drop_constraint('ck_highlight_role', 'compound_highlights', type_='check')
    op.create_check_constraint('ck_highlight_role', 'compound_highlights',
                               "role IN ('study_start', 'paper_selected')")
