"""add proceso5 tables

Revision ID: d1e2f3a4b5c6
Revises: c1d2e3f4g5h6
Create Date: 2026-03-06 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd1e2f3a4b5c6'
down_revision = 'c1d2e3f4g5h6'
branch_labels = None
depends_on = None


def upgrade():
    # proceso5_jobs
    op.create_table('proceso5_jobs',
        sa.Column('proceso1_job_id', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(length=50), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['proceso1_job_id'], ['proceso1_jobs.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('proceso1_job_id')
    )

    # proceso5_subprocess_states
    op.create_table('proceso5_subprocess_states',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('proceso1_job_id', sa.Integer(), nullable=False),
        sa.Column('subprocess_key', sa.String(length=50), nullable=False),
        sa.Column('status', sa.String(length=50), nullable=False),
        sa.Column('input_payload', sa.JSON(), nullable=True),
        sa.Column('output_payload', sa.JSON(), nullable=True),
        sa.Column('metadata_payload', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['proceso1_job_id'], ['proceso1_jobs.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('proceso1_job_id', 'subprocess_key', name='uq_proceso5_job_subprocess_key')
    )
    with op.batch_alter_table('proceso5_subprocess_states', schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f('ix_proceso5_subprocess_states_proceso1_job_id'),
            ['proceso1_job_id'],
            unique=False,
        )


def downgrade():
    with op.batch_alter_table('proceso5_subprocess_states', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_proceso5_subprocess_states_proceso1_job_id'))
    op.drop_table('proceso5_subprocess_states')
    op.drop_table('proceso5_jobs')
