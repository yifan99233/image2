from sqlalchemy import BigInteger, Column, DateTime, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB

from app.db.base import Base


class ImageBatchUpload(Base):
    __tablename__ = "image_batch_uploads"
    __table_args__ = (
        UniqueConstraint("site_id", "user_id", "batch_id", name="uq_image_batch_upload_owner_batch"),
        Index("idx_image_batch_upload_work", "status", "next_attempt_at"),
        Index("idx_image_batch_upload_user_status", "user_id", "status"),
        Index("idx_image_batch_upload_owner_created", "site_id", "user_id", "created_at"),
    )

    id = Column(BigInteger, primary_key=True)
    site_id = Column(BigInteger, nullable=False)
    user_id = Column(BigInteger, nullable=False)
    team_id = Column(BigInteger, nullable=True)
    batch_id = Column(String(64), nullable=False)
    request_hash = Column(String(64), nullable=False)
    task_count = Column(Integer, nullable=False)
    payload = Column(JSONB, nullable=False)
    billing = Column(JSONB, nullable=True)
    status = Column(String(24), nullable=False, server_default="queued")
    recovery_phase = Column(String(24), nullable=True)
    attempts = Column(Integer, nullable=False, server_default="0")
    error = Column(Text, nullable=True)
    next_attempt_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
