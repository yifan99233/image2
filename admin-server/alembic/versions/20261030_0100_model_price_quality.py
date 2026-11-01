"""Quality-specific image prices with backwards-compatible generic prices."""
from alembic import op
import sqlalchemy as sa
revision = "20261030_0100"
down_revision = "20261019_0200"
branch_labels = None
depends_on = None

def upgrade():
    columns = {c['name'] for c in sa.inspect(op.get_bind()).get_columns('image_model_prices')}
    if 'quality' not in columns:
        op.add_column('image_model_prices', sa.Column('quality', sa.String(16), nullable=False, server_default='any'))

def downgrade():
    # Shared by both services; retain prices and their meaning on rollback.
    pass
