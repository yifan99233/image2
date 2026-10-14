"""allow duplicate display usernames"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260704_0220"
down_revision: str | None = "20260704_0210"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE users DROP CONSTRAINT IF EXISTS uq_users_username")


def downgrade() -> None:
    op.create_unique_constraint("uq_users_username", "users", ["username"])
