from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Identity, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AdminOpenAPIKey(Base):
    __tablename__ = "admin_openapi_keys"
    __table_args__ = (
        Index("ix_admin_openapi_keys_site_active", "site_id", "is_active"),
        Index("ix_admin_openapi_keys_key_prefix", "key_prefix"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    site_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1, server_default="1", index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    key_prefix: Mapped[str] = mapped_column(String(32), nullable=False)
    key_hash: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    scopes: Mapped[str] = mapped_column(Text, nullable=False, default="[]", server_default="[]")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    created_by_admin_id: Mapped[int] = mapped_column(BigInteger, nullable=True)
    last_used_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
