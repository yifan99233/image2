"""Persist user canvas projects with optimistic concurrency control."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260916_0100"
down_revision = "20260913_0100"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "canvas_projects",
        sa.Column("site_id", sa.BigInteger(), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id"), primary_key=True),
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("node_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("connection_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("document", postgresql.JSONB(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("mutation_id", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("revision > 0", name="ck_canvas_projects_revision"),
    )
    op.create_index("idx_canvas_projects_owner_created", "canvas_projects", ["site_id", "user_id", "created_at", "id"])


def downgrade() -> None:
    op.drop_table("canvas_projects")
