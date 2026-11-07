from sqlalchemy import BigInteger, Boolean, Column, DateTime, ForeignKey, String, Text, func

from app.db.base import Base


class UserLeadModule(Base):
    __tablename__ = "user_lead_modules"

    id = Column(BigInteger(), primary_key=True)
    user_id = Column(
        BigInteger(),
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    enterprise_id = Column(String(128), nullable=False)
    enterprise_account = Column(String(128), nullable=False)
    enterprise_password_secret = Column(String(255), nullable=False)
    is_enabled = Column(Boolean, default=True, server_default="true", nullable=False)
    opened_by_admin_id = Column(BigInteger())
    credentials_revealed_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class LeadTrialApplication(Base):
    __tablename__ = "lead_trial_applications"

    id = Column(BigInteger(), primary_key=True)
    site_id = Column(BigInteger(), nullable=False, default=1, server_default="1", index=True)
    user_id = Column(
        BigInteger(),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    business_scope = Column(Text(), nullable=False)
    keywords = Column(Text(), nullable=False)
    competitor_accounts = Column(Text(), nullable=False, default="", server_default="")
    contact_info = Column(String(255), nullable=False, default="", server_default="")
    status = Column(String(32), nullable=False, default="pending", server_default="pending")
    admin_remark = Column(Text(), nullable=False, default="", server_default="")
    handled_by_admin_id = Column(BigInteger())
    handled_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
