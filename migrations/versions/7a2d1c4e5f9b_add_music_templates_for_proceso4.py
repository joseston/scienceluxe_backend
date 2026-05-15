"""add music templates for proceso4

Revision ID: 7a2d1c4e5f9b
Revises: 4f6b0f8a9c1d
Create Date: 2026-05-12 10:40:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "7a2d1c4e5f9b"
down_revision = "4f6b0f8a9c1d"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "proceso4_music_templates",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("proceso4_music_templates", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_proceso4_music_templates_name"), ["name"], unique=True)

    op.create_table(
        "proceso4_music_template_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("template_id", sa.Integer(), nullable=False),
        sa.Column("section", sa.String(length=30), nullable=False),
        sa.Column("pista_filename", sa.String(length=500), nullable=False),
        sa.Column("volume", sa.Float(), nullable=False),
        sa.Column("fade_in", sa.Float(), nullable=False),
        sa.Column("fade_out", sa.Float(), nullable=False),
        sa.Column("start_offset", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["template_id"], ["proceso4_music_templates.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("template_id", "section", name="uq_p4_music_template_item_section"),
    )
    with op.batch_alter_table("proceso4_music_template_items", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_proceso4_music_template_items_template_id"), ["template_id"], unique=False)


def downgrade():
    with op.batch_alter_table("proceso4_music_template_items", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_proceso4_music_template_items_template_id"))
    op.drop_table("proceso4_music_template_items")

    with op.batch_alter_table("proceso4_music_templates", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_proceso4_music_templates_name"))
    op.drop_table("proceso4_music_templates")
