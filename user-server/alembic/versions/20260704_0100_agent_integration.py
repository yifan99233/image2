"""agent integration

Revision ID: 20260704_0100
Revises: 20260622_0810
Create Date: 2026-07-04 01:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260704_0100"
down_revision: str | None = "20260622_0810"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_configs",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("base_url", sa.String(length=512), server_default="", nullable=False),
        sa.Column("admin_api_key", sa.String(length=512), server_default="", nullable=False),
        sa.Column("credit_to_agent_rate", sa.Numeric(12, 4), server_default="1", nullable=False),
        sa.Column("text_group_id", sa.BigInteger(), nullable=True),
        sa.Column("image_group_id", sa.BigInteger(), nullable=True),
        sa.Column("create_api_key_path", sa.String(length=255), server_default="", nullable=False),
        sa.Column("user_concurrency", sa.Integer(), server_default="0", nullable=False),
        sa.Column("user_rpm_limit", sa.Integer(), server_default="0", nullable=False),
        sa.Column("updated_by", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "user_agent_accounts",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("agent_user_id", sa.BigInteger(), nullable=True),
        sa.Column("agent_email", sa.String(length=255), nullable=False),
        sa.Column("text_api_key_id", sa.BigInteger(), nullable=True),
        sa.Column("text_api_key", sa.String(length=1024), nullable=True),
        sa.Column("image_api_key_id", sa.BigInteger(), nullable=True),
        sa.Column("image_api_key", sa.String(length=1024), nullable=True),
        sa.Column("status", sa.String(length=32), server_default="pending", nullable=False),
        sa.Column("failure_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", name="uq_user_agent_accounts_user_id"),
    )
    op.create_table(
        "agent_transfer_records",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("credit_ledger_id", sa.BigInteger(), nullable=True),
        sa.Column("credit_amount", sa.Integer(), nullable=False),
        sa.Column("agent_amount", sa.Numeric(12, 4), nullable=False),
        sa.Column("agent_user_id", sa.BigInteger(), nullable=True),
        sa.Column("idempotency_key", sa.String(length=160), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="pending", nullable=False),
        sa.Column("failure_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key", name="uq_agent_transfer_records_idempotency_key"),
    )
    op.create_index("idx_agent_transfer_records_user_created", "agent_transfer_records", ["user_id", "created_at"])


def downgrade() -> None:
    op.drop_index("idx_agent_transfer_records_user_created", table_name="agent_transfer_records")
    op.drop_table("agent_transfer_records")
    op.drop_table("user_agent_accounts")
    op.drop_table("agent_configs")
