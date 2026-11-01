"""Additional site-scoped groups available when users create API keys."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "20261019_0200"
down_revision = "20261012_0100"
branch_labels = None
depends_on = None


def upgrade():
    # Shared table: either service's migration may be applied first.
    columns = {column['name'] for column in sa.inspect(op.get_bind()).get_columns('agent_configs')}
    if 'key_group_whitelist' not in columns:
        op.add_column('agent_configs', sa.Column('key_group_whitelist', JSONB(), nullable=False, server_default='[]'))


def downgrade():
    # The other service also uses this shared column. Keep configuration on rollback.
    pass
