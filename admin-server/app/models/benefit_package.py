from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class BenefitPackage(Base):
    __tablename__ = "benefit_packages"
    __table_args__ = (
        UniqueConstraint("site_id", "code", name="uq_benefit_packages_site_code"),
        Index("ix_benefit_packages_site_active_sort", "site_id", "is_active", "sort_order", "id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    site_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1, server_default="1", index=True)
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="CNY", server_default="CNY")
    purchase_mode: Mapped[str] = mapped_column(String(20), nullable=False, default="one_time", server_default="one_time")
    billing_interval: Mapped[str | None] = mapped_column(String(20), nullable=True)
    validity_mode: Mapped[str] = mapped_column(String(20), nullable=False, default="fixed_days", server_default="fixed_days")
    validity_value: Mapped[int | None] = mapped_column(Integer, nullable=True)
    activation_policy: Mapped[str] = mapped_column(String(24), nullable=False, default="payment_success", server_default="payment_success")
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="Asia/Shanghai", server_default="Asia/Shanghai")
    stacking_policy: Mapped[str] = mapped_column(String(20), nullable=False, default="reject", server_default="reject")
    badge: Mapped[str | None] = mapped_column(String(32), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=50, server_default="50")
    is_recommended: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    items: Mapped[list["BenefitPackageItem"]] = relationship(
        back_populates="package", cascade="all, delete-orphan", order_by="BenefitPackageItem.sort_order, BenefitPackageItem.id"
    )


class BenefitPackageItem(Base):
    __tablename__ = "benefit_package_items"
    __table_args__ = (Index("ix_benefit_package_items_package_sort", "package_id", "sort_order", "id"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    package_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("benefit_packages.id", ondelete="CASCADE"), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(32), nullable=False)
    value_type: Mapped[str] = mapped_column(String(16), nullable=False, default="numeric", server_default="numeric")
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    grant_mode: Mapped[str] = mapped_column(String(16), nullable=False, default="one_time", server_default="one_time")
    grant_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    scope: Mapped[str] = mapped_column(String(16), nullable=False, default="team", server_default="team")
    aggregation_mode: Mapped[str] = mapped_column(String(16), nullable=False, default="sum", server_default="sum")
    expiry_policy: Mapped[str] = mapped_column(String(20), nullable=False, default="package_end", server_default="package_end")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=50, server_default="50")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    package: Mapped[BenefitPackage] = relationship(back_populates="items")


class BenefitOrder(Base):
    __tablename__ = "benefit_orders"
    __table_args__ = (
        UniqueConstraint("order_no", name="uq_benefit_orders_order_no"),
        Index("ix_benefit_orders_payer_status", "site_id", "payer_user_id", "status", "expires_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    site_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1, server_default="1")
    order_no: Mapped[str] = mapped_column(String(120), nullable=False)
    package_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("benefit_packages.id"), nullable=False)
    package_version: Mapped[int] = mapped_column(Integer, nullable=False)
    payer_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    team_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="CNY", server_default="CNY")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", server_default="pending")
    payment_provider: Mapped[str | None] = mapped_column(String(32), nullable=True)
    payment_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    payment_trade_no: Mapped[str | None] = mapped_column(String(128), nullable=True)
    pay_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    qr_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    failure_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class BenefitGrant(Base):
    __tablename__ = "benefit_grants"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_benefit_grants_idempotency_key"),
        Index("ix_benefit_grants_scope_active_expiry", "site_id", "owner_user_id", "team_id", "status", "expires_at"),
        Index("ix_benefit_grants_due", "status", "grant_at", "expires_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    site_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1, server_default="1")
    order_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("benefit_orders.id", ondelete="SET NULL"), nullable=True)
    package_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("benefit_packages.id"), nullable=False)
    package_item_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("benefit_package_items.id"), nullable=False)
    package_version: Mapped[int] = mapped_column(Integer, nullable=False)
    owner_user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    team_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    resource_type: Mapped[str] = mapped_column(String(32), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    remaining_amount: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    grant_mode: Mapped[str] = mapped_column(String(16), nullable=False)
    grant_index: Mapped[int] = mapped_column(Integer, nullable=False)
    grant_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="scheduled", server_default="scheduled")
    idempotency_key: Mapped[str] = mapped_column(String(180), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class BenefitCreditAllocation(Base):
    __tablename__ = "benefit_credit_allocations"
    __table_args__ = (UniqueConstraint("grant_id", "task_no", name="uq_benefit_credit_allocations_grant_task"), Index("ix_benefit_credit_allocations_task", "task_no", "released_at"))

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    grant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("benefit_grants.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    team_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    task_no: Mapped[str] = mapped_column(String(120), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


__all__ = ["BenefitPackage", "BenefitPackageItem", "BenefitOrder", "BenefitGrant", "BenefitCreditAllocation"]
