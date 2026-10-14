from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class RechargePlan(Base):
    __tablename__ = "recharge_plans"
    __table_args__ = (
        UniqueConstraint("site_id", "name", name="uq_recharge_plans_site_name"),
        Index("ix_recharge_plans_site_active_sort", "site_id", "is_active", "sort_order"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    site_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1, server_default="1", index=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    credit_amount: Mapped[int] = mapped_column(Integer, nullable=False)
    bonus_credit_amount: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    team_seat_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    team_duration_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    badge: Mapped[str] = mapped_column(String(32), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=50, server_default="50")
    is_recommended: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
