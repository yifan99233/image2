"""restore global user email uniqueness

Revision ID: 20260706_0230
Revises: 20260706_0220
Create Date: 2026-07-06 02:30:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260706_0230"
down_revision: str | None = "20260706_0220"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        DECLARE
            duplicate_email TEXT;
        BEGIN
            SELECT email INTO duplicate_email
            FROM users
            GROUP BY email
            HAVING count(*) > 1
            LIMIT 1;

            IF duplicate_email IS NOT NULL THEN
                RAISE EXCEPTION 'cannot add uq_users_email; duplicate email exists: %', duplicate_email;
            END IF;
        END
        $$;
        """
    )
    op.execute("ALTER TABLE IF EXISTS users DROP CONSTRAINT IF EXISTS uq_users_site_email")
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'uq_users_email'
                  AND conrelid = 'users'::regclass
            ) THEN
                ALTER TABLE users ADD CONSTRAINT uq_users_email UNIQUE (email);
            END IF;
        END
        $$;
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE IF EXISTS users DROP CONSTRAINT IF EXISTS uq_users_email")
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'uq_users_site_email'
                  AND conrelid = 'users'::regclass
            ) THEN
                ALTER TABLE users ADD CONSTRAINT uq_users_site_email UNIQUE (site_id, email);
            END IF;
        END
        $$;
        """
    )
