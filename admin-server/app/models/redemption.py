from sqlalchemy import BigInteger, Column, DateTime, Index, Integer, Numeric, String, Text, func
from app.db.base import Base


class RedemptionCode(Base):
    __tablename__ = "redemption_codes"
    __table_args__ = (Index("ix_redemption_codes_site_created", "site_id", "created_at"),)
    id = Column(String(36), primary_key=True)
    site_id = Column(BigInteger, nullable=False)
    batch_id = Column(String(36), nullable=False, index=True)
    code_hash = Column(String(64), nullable=False, unique=True)
    code_hint = Column(String(12), nullable=False)
    amount = Column(Integer, nullable=False)
    status = Column(String(16), nullable=False, default="unused", server_default="unused")
    note = Column(String(200), nullable=False, default="", server_default="")
    created_by = Column(BigInteger, nullable=False)
    redeemed_by = Column(BigInteger)
    expires_at = Column(DateTime(timezone=True))
    claimed_at = Column(DateTime(timezone=True))
    redeemed_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    # Persist the destination before any remote credit, so retries cannot change wallets.
    agent_user_id = Column(BigInteger)
    agent_base_url = Column(Text)
    agent_amount = Column(Numeric(20, 4))


class RedemptionBatch(Base):
    __tablename__ = "redemption_batches"
    id = Column(String(36), primary_key=True)
    site_id = Column(BigInteger, nullable=False)
    created_by = Column(BigInteger, nullable=False)
