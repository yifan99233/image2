from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class ImageModelProvider(Base):
    __tablename__ = "image_model_providers"
    __table_args__ = (
        UniqueConstraint("site_id", "code", name="uq_image_model_providers_site_code"),
        Index("ix_image_model_providers_site_active", "site_id", "is_active"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    site_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1, server_default="1", index=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    code: Mapped[str] = mapped_column(String(80), nullable=False)
    base_url: Mapped[str] = mapped_column(String(512), nullable=False)
    access_mode: Mapped[str] = mapped_column(String(32), nullable=False, default="api", server_default="api")
    auth_type: Mapped[str] = mapped_column(String(32), nullable=False, default="bearer", server_default="bearer")
    encrypted_api_key: Mapped[str] = mapped_column(String(1024), nullable=True)
    timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=30, server_default="30")
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    models: Mapped[list["ImageModel"]] = relationship(back_populates="provider")


class ImageModel(Base):
    __tablename__ = "image_models"
    __table_args__ = (
        UniqueConstraint("site_id", "code", name="uq_image_models_site_code"),
        Index("ix_image_models_site_active_sort", "site_id", "is_active", "sort_order"),
        Index("ix_image_models_site_public_active_sort", "site_id", "is_public", "is_active", "sort_order"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    site_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1, server_default="1", index=True)
    provider_id: Mapped[int] = mapped_column(ForeignKey("image_model_providers.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    code: Mapped[str] = mapped_column(String(120), nullable=False)
    vendor_model: Mapped[str] = mapped_column(String(160), nullable=False)
    work_type: Mapped[str] = mapped_column(String(80), nullable=False)
    capability_type: Mapped[str] = mapped_column(String(32), nullable=False, default="image", server_default="image")
    supports_image_edit: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    is_recommended: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    is_stable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    is_new: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    speed_hint: Mapped[str] = mapped_column(String(80), nullable=True)
    risk_hint: Mapped[str] = mapped_column(String(160), nullable=True)
    max_input_images: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    max_output_images: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    concurrency_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=50, server_default="50")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    is_public: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    storage_mode: Mapped[str] = mapped_column(String(32), nullable=False, default="local", server_default="local")
    timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=120, server_default="120")
    disable_retry: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    provider: Mapped[ImageModelProvider] = relationship(back_populates="models")
