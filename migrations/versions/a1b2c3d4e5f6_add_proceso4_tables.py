"""add proceso4 tables

Revision ID: a1b2c3d4e5f6
Revises: 79d947b8b59e
Create Date: 2026-02-17 22:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a1b2c3d4e5f6'
down_revision = '79d947b8b59e'
branch_labels = None
depends_on = None


def upgrade():
    # proceso4_jobs
    op.create_table('proceso4_jobs',
        sa.Column('proceso1_job_id', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['proceso1_job_id'], ['proceso1_jobs.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('proceso1_job_id')
    )

    # proceso4_subprocess_states
    op.create_table('proceso4_subprocess_states',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('proceso1_job_id', sa.Integer(), nullable=False),
        sa.Column('subprocess_key', sa.String(length=40), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('input_payload', sa.JSON(), nullable=True),
        sa.Column('output_payload', sa.JSON(), nullable=True),
        sa.Column('metadata_payload', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['proceso1_job_id'], ['proceso1_jobs.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('proceso1_job_id', 'subprocess_key', name='uq_proceso4_job_subprocess_key')
    )
    with op.batch_alter_table('proceso4_subprocess_states', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_proceso4_subprocess_states_proceso1_job_id'), ['proceso1_job_id'], unique=False)

    # proceso4_scene_media
    op.create_table('proceso4_scene_media',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('proceso1_job_id', sa.Integer(), nullable=False),
        sa.Column('scene_num', sa.Integer(), nullable=False),
        sa.Column('clip_index', sa.Integer(), nullable=False),
        sa.Column('media_type', sa.String(length=10), nullable=False),
        sa.Column('original_filename', sa.String(length=500), nullable=True),
        sa.Column('file_path', sa.String(length=500), nullable=False),
        sa.Column('duration', sa.Float(), nullable=True),
        sa.Column('trim_start', sa.Float(), nullable=False),
        sa.Column('trim_end', sa.Float(), nullable=True),
        sa.Column('transition_type', sa.String(length=30), nullable=False),
        sa.Column('transition_duration', sa.Float(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['proceso1_job_id'], ['proceso1_jobs.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('proceso1_job_id', 'scene_num', 'clip_index', name='uq_proceso4_scene_clip')
    )
    with op.batch_alter_table('proceso4_scene_media', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_proceso4_scene_media_proceso1_job_id'), ['proceso1_job_id'], unique=False)

    # proceso4_audio_tracks
    op.create_table('proceso4_audio_tracks',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('proceso1_job_id', sa.Integer(), nullable=False),
        sa.Column('track_type', sa.String(length=20), nullable=False),
        sa.Column('original_filename', sa.String(length=500), nullable=True),
        sa.Column('file_path', sa.String(length=500), nullable=False),
        sa.Column('start_time', sa.Float(), nullable=False),
        sa.Column('volume', sa.Float(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['proceso1_job_id'], ['proceso1_jobs.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('proceso4_audio_tracks', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_proceso4_audio_tracks_proceso1_job_id'), ['proceso1_job_id'], unique=False)


def downgrade():
    with op.batch_alter_table('proceso4_audio_tracks', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_proceso4_audio_tracks_proceso1_job_id'))
    op.drop_table('proceso4_audio_tracks')

    with op.batch_alter_table('proceso4_scene_media', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_proceso4_scene_media_proceso1_job_id'))
    op.drop_table('proceso4_scene_media')

    with op.batch_alter_table('proceso4_subprocess_states', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_proceso4_subprocess_states_proceso1_job_id'))
    op.drop_table('proceso4_subprocess_states')

    op.drop_table('proceso4_jobs')
