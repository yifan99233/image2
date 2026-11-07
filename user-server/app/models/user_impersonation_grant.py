from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, String, func

from app.db.base import Base


class UserImpersonationGrant(Base):
    __tablename__ = "user_impersonation_grants"

    token_hash = Column(String(64), primary_key=True)
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    site_id = Column(BigInteger, nullable=False, index=True)
    admin_id = Column(BigInteger, nullable=False)
    admin_username = Column(String(80), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)
    consumed_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
