"""add start_offset to proceso4_section_tracks

Revision ID: 4f6b0f8a9c1d
Revises: f1a2b3c4d5e6
Create Date: 2026-05-12 09:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "4f6b0f8a9c1d"
down_revision = "f1a2b3c4d5e6"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("proceso4_section_tracks", schema=None) as batch_op:
        batch_op.add_column(sa.Column("start_offset", sa.Float(), nullable=False, server_default="0"))


def downgrade():
    with op.batch_alter_table("proceso4_section_tracks", schema=None) as batch_op:
        batch_op.drop_column("start_offset")
