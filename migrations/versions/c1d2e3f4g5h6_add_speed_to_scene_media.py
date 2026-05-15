"""add speed to scene media

Revision ID: c1d2e3f4g5h6
Revises: b2c3d4e5f6a7
Create Date: 2026-03-05 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = 'c1d2e3f4g5h6'
down_revision = 'a3990a644f1f'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('proceso4_scene_media', sa.Column('speed', sa.Float(), nullable=False, server_default='1.0'))


def downgrade():
    op.drop_column('proceso4_scene_media', 'speed')
