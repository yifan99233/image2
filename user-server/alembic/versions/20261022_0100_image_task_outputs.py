"""Persist every image returned by a single provider generation."""
from alembic import op
import sqlalchemy as sa

revision = "20261022_0100"
down_revision = "20261019_0300"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE image_tasks ADD COLUMN IF NOT EXISTS output_image_assets JSONB")
    # GIN supports bounded retention matching of any output URL, not only the cover.
    with op.get_context().autocommit_block():
        op.execute("CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_image_tasks_output_assets ON image_tasks USING gin (output_image_assets jsonb_path_ops)")
    # Include all outputs when the existing collection/gallery reference guard
    # locks generated assets. to_jsonb keeps the function compatible on rollback.
    connection = op.get_bind()
    guard = connection.execute(sa.text("SELECT pg_get_functiondef('image_retention_reference_guard()'::regprocedure)")).scalar_one()
    if "to_jsonb(NEW)->>'output_image_assets'" not in guard:
        guard = guard.replace("coalesce(NEW.output_image_r2_url, '')", "coalesce(NEW.output_image_r2_url, '') || ' ' || coalesce(to_jsonb(NEW)->>'output_image_assets', '')")
    op.execute(guard)


def downgrade():
    op.drop_index("ix_image_tasks_output_assets", table_name="image_tasks")
    op.drop_column("image_tasks", "output_image_assets")
