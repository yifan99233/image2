"""Allow encrypted upstream credentials, including maximum-length passwords."""

from alembic import op
import sqlalchemy as sa

revision = "20260924_0100"
down_revision = "20260802_0100"
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column("user_agent_accounts", "agent_password", type_=sa.Text(), existing_type=sa.String(255))


def downgrade():
    # Keep the wider type: truncating encrypted credentials would destroy them.
    pass
