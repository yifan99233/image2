from sqlalchemy import BigInteger, Boolean, Column, Date, DateTime, ForeignKey, Integer, String, UniqueConstraint, func

from app.db.base import Base


class SigninRewardConfig(Base):
    __tablename__ = "signin_reward_configs"

    id = Column(BigInteger(), primary_key=True)
    site_id = Column(BigInteger(), nullable=False, default=1, server_default="1", index=True)
    is_enabled = Column(Boolean, nullable=False, default=False, server_default="false")
    daily_credits = Column(Integer, nullable=False, default=0, server_default="0")
    updated_by = Column(BigInteger())
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class UserSigninRecord(Base):
    __tablename__ = "user_signin_records"
    __table_args__ = (
        UniqueConstraint("user_id", "sign_date", name="uq_user_signin_records_user_date"),
    )

    id = Column(BigInteger(), primary_key=True)
    user_id = Column(BigInteger(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    sign_date = Column(Date, nullable=False)
    awarded_credits = Column(Integer, nullable=False)
    streak_days = Column(Integer, nullable=False, default=1, server_default="1")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
