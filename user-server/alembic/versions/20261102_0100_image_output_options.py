"""Persist custom image size and output format."""
from alembic import op

revision = "20261102_0100"
down_revision = "20261030_0100"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE image_tasks ADD COLUMN IF NOT EXISTS size VARCHAR(32)")
    op.execute("ALTER TABLE image_tasks ADD COLUMN IF NOT EXISTS output_format VARCHAR(16)")


def downgrade():
    # Shared additive columns retained for rolling service rollback.
    pass
