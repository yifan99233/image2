"""Add configurable benefit packages and immutable grant records."""

from alembic import op

revision = "20261107_0100"
down_revision = "20261106_0100"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS benefit_packages (
            id BIGSERIAL PRIMARY KEY,
            site_id BIGINT NOT NULL DEFAULT 1,
            code VARCHAR(64) NOT NULL,
            name VARCHAR(80) NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            amount_cents INTEGER NOT NULL,
            currency VARCHAR(8) NOT NULL DEFAULT 'CNY',
            purchase_mode VARCHAR(20) NOT NULL DEFAULT 'one_time',
            billing_interval VARCHAR(20) NULL,
            validity_mode VARCHAR(20) NOT NULL DEFAULT 'fixed_days',
            validity_value INTEGER NULL,
            activation_policy VARCHAR(24) NOT NULL DEFAULT 'payment_success',
            timezone VARCHAR(64) NOT NULL DEFAULT 'Asia/Shanghai',
            stacking_policy VARCHAR(20) NOT NULL DEFAULT 'reject',
            badge VARCHAR(32) NULL,
            sort_order INTEGER NOT NULL DEFAULT 50,
            is_recommended BOOLEAN NOT NULL DEFAULT false,
            is_active BOOLEAN NOT NULL DEFAULT true,
            version INTEGER NOT NULL DEFAULT 1,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_benefit_packages_site_code UNIQUE (site_id, code),
            CONSTRAINT ck_benefit_packages_amount_positive CHECK (amount_cents > 0),
            CONSTRAINT ck_benefit_packages_purchase_mode CHECK (purchase_mode IN ('one_time', 'subscription')),
            CONSTRAINT ck_benefit_packages_validity_mode CHECK (validity_mode IN ('fixed_days', 'billing_period', 'permanent')),
            CONSTRAINT ck_benefit_packages_activation_policy CHECK (activation_policy IN ('payment_success', 'first_use', 'scheduled')),
            CONSTRAINT ck_benefit_packages_stacking_policy CHECK (stacking_policy IN ('reject', 'extend', 'stack')),
            CONSTRAINT ck_benefit_packages_validity_value CHECK (validity_value IS NULL OR validity_value > 0)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS benefit_package_items (
            id BIGSERIAL PRIMARY KEY,
            package_id BIGINT NOT NULL REFERENCES benefit_packages(id) ON DELETE CASCADE,
            resource_type VARCHAR(32) NOT NULL,
            value_type VARCHAR(16) NOT NULL DEFAULT 'numeric',
            amount NUMERIC(20, 2) NOT NULL,
            grant_mode VARCHAR(16) NOT NULL DEFAULT 'one_time',
            grant_count INTEGER NULL,
            scope VARCHAR(16) NOT NULL DEFAULT 'team',
            aggregation_mode VARCHAR(16) NOT NULL DEFAULT 'sum',
            expiry_policy VARCHAR(20) NOT NULL DEFAULT 'package_end',
            sort_order INTEGER NOT NULL DEFAULT 50,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_benefit_package_items_amount_positive CHECK (amount > 0),
            CONSTRAINT ck_benefit_package_items_value_type CHECK (value_type IN ('numeric')),
            CONSTRAINT ck_benefit_package_items_grant_mode CHECK (grant_mode IN ('one_time', 'daily', 'weekly')),
            CONSTRAINT ck_benefit_package_items_scope CHECK (scope IN ('user', 'team', 'api_key')),
            CONSTRAINT ck_benefit_package_items_aggregation CHECK (aggregation_mode IN ('sum', 'max', 'replace')),
            CONSTRAINT ck_benefit_package_items_expiry CHECK (expiry_policy IN ('grant_period', 'package_end', 'permanent')),
            CONSTRAINT ck_benefit_package_items_grant_count CHECK (grant_count IS NULL OR grant_count > 0)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS benefit_orders (
            id BIGSERIAL PRIMARY KEY,
            site_id BIGINT NOT NULL DEFAULT 1,
            order_no VARCHAR(120) NOT NULL,
            package_id BIGINT NOT NULL REFERENCES benefit_packages(id),
            package_version INTEGER NOT NULL,
            payer_user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            team_id BIGINT NULL,
            amount_cents INTEGER NOT NULL,
            currency VARCHAR(8) NOT NULL DEFAULT 'CNY',
            status VARCHAR(20) NOT NULL DEFAULT 'pending',
            payment_provider VARCHAR(32) NULL,
            payment_type VARCHAR(32) NULL,
            payment_trade_no VARCHAR(128) NULL,
            pay_url TEXT NULL,
            qr_code TEXT NULL,
            failure_message TEXT NULL,
            starts_at TIMESTAMPTZ NULL,
            expires_at TIMESTAMPTZ NULL,
            paid_at TIMESTAMPTZ NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_benefit_orders_order_no UNIQUE (order_no),
            CONSTRAINT ck_benefit_orders_status CHECK (status IN ('pending', 'paid', 'failed', 'expired', 'cancelled', 'refunded'))
        )
        """
    )
    op.execute("ALTER TABLE benefit_orders ADD COLUMN IF NOT EXISTS payment_type VARCHAR(32) NULL")
    op.execute("ALTER TABLE benefit_orders ADD COLUMN IF NOT EXISTS pay_url TEXT NULL")
    op.execute("ALTER TABLE benefit_orders ADD COLUMN IF NOT EXISTS qr_code TEXT NULL")
    op.execute("ALTER TABLE benefit_orders ADD COLUMN IF NOT EXISTS failure_message TEXT NULL")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS benefit_grants (
            id BIGSERIAL PRIMARY KEY,
            site_id BIGINT NOT NULL DEFAULT 1,
            order_id BIGINT NULL REFERENCES benefit_orders(id) ON DELETE SET NULL,
            package_id BIGINT NOT NULL REFERENCES benefit_packages(id),
            package_item_id BIGINT NOT NULL REFERENCES benefit_package_items(id),
            package_version INTEGER NOT NULL,
            owner_user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            team_id BIGINT NULL,
            resource_type VARCHAR(32) NOT NULL,
            amount NUMERIC(20, 2) NOT NULL,
            remaining_amount NUMERIC(20, 2) NOT NULL,
            grant_mode VARCHAR(16) NOT NULL,
            grant_index INTEGER NOT NULL,
            grant_at TIMESTAMPTZ NOT NULL,
            starts_at TIMESTAMPTZ NOT NULL,
            expires_at TIMESTAMPTZ NULL,
            status VARCHAR(20) NOT NULL DEFAULT 'scheduled',
            idempotency_key VARCHAR(180) NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_benefit_grants_idempotency_key UNIQUE (idempotency_key),
            CONSTRAINT ck_benefit_grants_amount_positive CHECK (amount > 0),
            CONSTRAINT ck_benefit_grants_remaining_nonnegative CHECK (remaining_amount >= 0),
            CONSTRAINT ck_benefit_grants_status CHECK (status IN ('scheduled', 'active', 'exhausted', 'expired', 'revoked'))
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS benefit_credit_allocations (
            id BIGSERIAL PRIMARY KEY,
            grant_id BIGINT NOT NULL REFERENCES benefit_grants(id) ON DELETE CASCADE,
            user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            team_id BIGINT NULL,
            task_no VARCHAR(120) NOT NULL,
            amount NUMERIC(20, 2) NOT NULL,
            released_at TIMESTAMPTZ NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_benefit_credit_allocations_amount_positive CHECK (amount > 0),
            CONSTRAINT uq_benefit_credit_allocations_grant_task UNIQUE (grant_id, task_no)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_benefit_packages_site_active_sort ON benefit_packages (site_id, is_active, sort_order, id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_benefit_package_items_package_sort ON benefit_package_items (package_id, sort_order, id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_benefit_orders_payer_status ON benefit_orders (site_id, payer_user_id, status, expires_at)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_benefit_grants_scope_active_expiry ON benefit_grants (site_id, owner_user_id, team_id, status, expires_at)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_benefit_grants_due ON benefit_grants (status, grant_at, expires_at)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_benefit_credit_allocations_task ON benefit_credit_allocations (task_no, released_at)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_benefit_grants_due")
    op.execute("DROP INDEX IF EXISTS ix_benefit_credit_allocations_task")
    op.execute("DROP INDEX IF EXISTS ix_benefit_grants_scope_active_expiry")
    op.execute("DROP INDEX IF EXISTS ix_benefit_orders_payer_status")
    op.execute("DROP INDEX IF EXISTS ix_benefit_package_items_package_sort")
    op.execute("DROP INDEX IF EXISTS ix_benefit_packages_site_active_sort")
    op.execute("DROP TABLE IF EXISTS benefit_credit_allocations")
    op.execute("DROP TABLE IF EXISTS benefit_grants")
    op.execute("DROP TABLE IF EXISTS benefit_orders")
    op.execute("DROP TABLE IF EXISTS benefit_package_items")
    op.execute("DROP TABLE IF EXISTS benefit_packages")
