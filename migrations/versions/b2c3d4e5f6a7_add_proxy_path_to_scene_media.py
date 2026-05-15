"""add proxy_path to proceso4_scene_media

Revision ID: b2c3d4e5f6a7
Revises: 07c4c10b7600
Create Date: 2026-02-28 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b2c3d4e5f6a7'
down_revision = '2dcb9fca82ef'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('proceso4_scene_media', schema=None) as batch_op:
        batch_op.add_column(sa.Column('proxy_path', sa.String(length=500), nullable=True))


def downgrade():
    with op.batch_alter_table('proceso4_scene_media', schema=None) as batch_op:
        batch_op.drop_column('proxy_path')
