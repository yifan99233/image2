from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Identity, Index, Integer, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.image_model import ImageModel


class ModelPrice(Base):
    __tablename__ = "image_model_prices"
    __table_args__ = (
        Index("ix_image_model_prices_site_model_active", "site_id", "model_id", "is_active"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    site_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1, server_default="1", index=True)
    model_id: Mapped[int] = mapped_column(ForeignKey("image_models.id"), nullable=False)
    work_type: Mapped[str] = mapped_column(String(80), nullable=False)
    resolution: Mapped[str] = mapped_column(String(64), nullable=False)
    aspect_ratio: Mapped[str] = mapped_column(String(32), nullable=False)
    output_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    credit_cost: Mapped[int] = mapped_column(Integer, nullable=False)
    fixed_surcharge: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0, server_default="0")
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    effective_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    change_reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    model: Mapped[ImageModel] = relationship()
