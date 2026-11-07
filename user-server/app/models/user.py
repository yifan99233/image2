from datetime import datetime

from sqlalchemy import BigInteger, Boolean, Column, DateTime, Index, Integer, String, func

from app.db.base import Base


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        Index("idx_users_active_created", "is_active", "created_at"),
        Index("idx_users_site_active_created", "site_id", "is_active", "created_at"),
    )

    id = Column(BigInteger(), primary_key=True)
    site_id = Column(BigInteger(), nullable=False, default=1, server_default="1", index=True)
    username = Column(String(64), nullable=False)
    email = Column(String(255), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    nickname = Column(String(128))
    avatar_url = Column(String(1024))
    invited_by_user_id = Column(BigInteger)
    customer_owner_admin_id = Column(BigInteger, index=True)
    active_team_id = Column(BigInteger)
    is_active = Column(Boolean, default=True, server_default="true", nullable=False)
    is_internal = Column(Boolean, default=False, server_default="false", nullable=False)
    image_concurrency_limit = Column(Integer, default=1, server_default="1", nullable=False)
    last_login_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    deleted_at = Column(DateTime(timezone=True))
