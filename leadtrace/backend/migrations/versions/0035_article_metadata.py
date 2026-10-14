"""Source-backed article identifiers, research profile, and abstract completeness."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0035_article_metadata'
down_revision = '0034_paper_removal'
branch_labels = None
depends_on = None


def upgrade():
    for name, type_ in [('pmid', sa.String(20)), ('pmcid', sa.String(23)),
                        ('identifiers_source', sa.Text()), ('abstract_note', sa.Text())]:
        op.add_column('papers', sa.Column(name, type_, nullable=True))
    op.add_column('papers', sa.Column('abstract_status', sa.String(16), nullable=False, server_default='not_checked'))
    op.add_column('papers', sa.Column('research_profile', postgresql.JSONB(), nullable=False, server_default='{}'))


def downgrade():
    for name in ('research_profile', 'abstract_status', 'abstract_note', 'identifiers_source', 'pmcid', 'pmid'):
        op.drop_column('papers', name)
