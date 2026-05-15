"""add raw_idea and draft_id to proceso1_jobs

Revision ID: f1a2b3c4d5e6
Revises: 9b559f97e1d0
Create Date: 2026-03-30 13:20:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f1a2b3c4d5e6'
down_revision = '9b559f97e1d0'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('proceso1_jobs', schema=None) as batch_op:
        batch_op.add_column(sa.Column('raw_idea', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('draft_id', sa.String(length=8), nullable=True))
        batch_op.create_index(batch_op.f('ix_proceso1_jobs_draft_id'), ['draft_id'], unique=False)


def downgrade():
    with op.batch_alter_table('proceso1_jobs', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_proceso1_jobs_draft_id'))
        batch_op.drop_column('draft_id')
        batch_op.drop_column('raw_idea')
