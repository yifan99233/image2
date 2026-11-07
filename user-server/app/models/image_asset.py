from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Index, Integer, String, func

from app.db.base import Base


class ImageAsset(Base):
    __tablename__ = "image_assets"
    __table_args__ = (
        Index("idx_image_assets_site_user_created", "site_id", "user_id", "created_at"),
        Index("idx_image_assets_user_created", "user_id", "created_at"),
        Index("idx_image_assets_sha256", "sha256"),
    )

    id = Column(BigInteger(), primary_key=True)
    site_id = Column(BigInteger(), nullable=False, default=1, server_default="1", index=True)
    user_id = Column(BigInteger(), ForeignKey("users.id"), nullable=False)
    storage_key = Column(String(1024), nullable=False, unique=True)
    url = Column(String(1024), nullable=False)
    local_url = Column(String(1024), nullable=True)
    r2_url = Column(String(1024), nullable=True)
    r2_expires_at = Column(DateTime(timezone=True), nullable=True)
    mime_type = Column(String(128), nullable=False)
    width = Column(Integer)
    height = Column(Integer)
    size_bytes = Column(BigInteger(), nullable=False)
    sha256 = Column(String(64), nullable=False)
    source = Column(String(32), nullable=False, default="upload", server_default="upload")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    retention_pending_at = Column(DateTime(timezone=True))
    storage_deleted_at = Column(DateTime(timezone=True))
    retention_error = Column(String(128))
