"""admin openapi keys

Revision ID: 20260706_0220
Revises: 20260706_0210
Create Date: 2026-07-06 02:20:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260706_0220"
down_revision: str | None = "20260706_0210"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "admin_openapi_keys",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("site_id", sa.BigInteger(), nullable=False, server_default="1"),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("key_prefix", sa.String(length=32), nullable=False),
        sa.Column("key_hash", sa.String(length=128), nullable=False),
        sa.Column("scopes", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by_admin_id", sa.BigInteger(), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("key_hash", name="uq_admin_openapi_keys_key_hash"),
    )
    op.create_index("ix_admin_openapi_keys_site_active", "admin_openapi_keys", ["site_id", "is_active"])
    op.create_index("ix_admin_openapi_keys_key_prefix", "admin_openapi_keys", ["key_prefix"])


def downgrade() -> None:
    op.drop_index("ix_admin_openapi_keys_key_prefix", table_name="admin_openapi_keys")
    op.drop_index("ix_admin_openapi_keys_site_active", table_name="admin_openapi_keys")
    op.drop_table("admin_openapi_keys")
