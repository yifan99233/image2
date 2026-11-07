"""openagent desktop releases

Revision ID: 20260704_0300
Revises: 20260703_0330
Create Date: 2026-07-04 03:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260704_0300"
down_revision = "20260703_0330"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "openagent_releases",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("channel", sa.String(length=24), nullable=False, server_default="prod"),
        sa.Column("version", sa.String(length=64), nullable=False),
        sa.Column("platform", sa.String(length=32), nullable=False, server_default="mac"),
        sa.Column("arch", sa.String(length=32), nullable=False, server_default="universal"),
        sa.Column("file_url", sa.Text(), nullable=False),
        sa.Column("file_sha512", sa.String(length=256), nullable=False),
        sa.Column("file_size", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("release_notes", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("is_mandatory", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("channel", "version", "platform", "arch", name="uq_openagent_releases_target"),
    )
    op.create_index("ix_openagent_releases_lookup", "openagent_releases", ["channel", "platform", "arch", "is_active"])
    op.create_index("ix_openagent_releases_published", "openagent_releases", ["published_at"])


def downgrade() -> None:
    op.drop_index("ix_openagent_releases_published", table_name="openagent_releases")
    op.drop_index("ix_openagent_releases_lookup", table_name="openagent_releases")
    op.drop_table("openagent_releases")
