from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Identity, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class OpenAgentRelease(Base):
    __tablename__ = "openagent_releases"
    __table_args__ = (
        Index("ix_openagent_releases_site_lookup", "site_id", "channel", "platform", "arch", "is_active"),
    )

    id: Mapped[int] = mapped_column(BigInteger(), Identity(), primary_key=True)
    site_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1, server_default="1", index=True)
    channel: Mapped[str] = mapped_column(String(24), nullable=False, default="prod", server_default="prod")
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    platform: Mapped[str] = mapped_column(String(32), nullable=False, default="mac", server_default="mac")
    arch: Mapped[str] = mapped_column(String(32), nullable=False, default="universal", server_default="universal")
    file_url: Mapped[str] = mapped_column(Text, nullable=False)
    file_sha512: Mapped[str] = mapped_column(String(256), nullable=False)
    file_size: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    release_notes: Mapped[str] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    is_mandatory: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[int] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
