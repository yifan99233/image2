from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Identity, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ImageResolutionSpec(Base):
    __tablename__ = "image_resolution_specs"
    __table_args__ = (
        UniqueConstraint("site_id", "code", name="uq_image_resolution_specs_site_code"),
        Index("ix_image_resolution_specs_site_active_sort", "site_id", "is_active", "sort_order"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    site_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1, server_default="1", index=True)
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    label: Mapped[str] = mapped_column(String(80), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=50, server_default="50")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class ImageAspectRatioSpec(Base):
    __tablename__ = "image_aspect_ratio_specs"
    __table_args__ = (
        UniqueConstraint("site_id", "code", name="uq_image_aspect_ratio_specs_site_code"),
        Index("ix_image_aspect_ratio_specs_site_active_sort", "site_id", "is_active", "sort_order"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    site_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1, server_default="1", index=True)
    code: Mapped[str] = mapped_column(String(32), nullable=False)
    label: Mapped[str] = mapped_column(String(80), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=50, server_default="50")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class ImageModelResolution(Base):
    __tablename__ = "image_model_resolutions"
    __table_args__ = (UniqueConstraint("model_id", "resolution_id", name="uq_image_model_resolution"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    model_id: Mapped[int] = mapped_column(ForeignKey("image_models.id"), nullable=False)
    resolution_id: Mapped[int] = mapped_column(ForeignKey("image_resolution_specs.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ImageModelAspectRatio(Base):
    __tablename__ = "image_model_aspect_ratios"
    __table_args__ = (UniqueConstraint("model_id", "aspect_ratio_id", name="uq_image_model_aspect_ratio"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    model_id: Mapped[int] = mapped_column(ForeignKey("image_models.id"), nullable=False)
    aspect_ratio_id: Mapped[int] = mapped_column(ForeignKey("image_aspect_ratio_specs.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class VideoDurationSpec(Base):
    __tablename__ = "video_duration_specs"
    __table_args__ = (
        UniqueConstraint("site_id", "code", name="uq_video_duration_specs_site_code"),
        Index("ix_video_duration_specs_site_active_sort", "site_id", "is_active", "sort_order"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    site_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1, server_default="1", index=True)
    code: Mapped[str] = mapped_column(String(32), nullable=False)
    label: Mapped[str] = mapped_column(String(80), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=50, server_default="50")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class ImageModelDuration(Base):
    __tablename__ = "image_model_durations"
    __table_args__ = (UniqueConstraint("model_id", "duration_id", name="uq_image_model_duration"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    model_id: Mapped[int] = mapped_column(ForeignKey("image_models.id"), nullable=False)
    duration_id: Mapped[int] = mapped_column(ForeignKey("video_duration_specs.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
