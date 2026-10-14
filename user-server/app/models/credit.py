from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint, func

from app.db.base import Base


class UserCreditAccount(Base):
    __tablename__ = "user_credit_accounts"

    id = Column(BigInteger(), primary_key=True)
    user_id = Column(
        BigInteger(),
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    balance = Column(Numeric(20, 2), nullable=False, default=0, server_default="0")
    gift_balance = Column(Numeric(20, 2), nullable=False, default=0, server_default="0")
    total_gifted = Column(Numeric(20, 2), nullable=False, default=0, server_default="0")
    total_recharged = Column(Numeric(20, 2), nullable=False, default=0, server_default="0")
    total_consumed = Column(Numeric(20, 2), nullable=False, default=0, server_default="0")
    version = Column(Integer, nullable=False, default=1, server_default="1")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class CreditLedger(Base):
    __tablename__ = "credit_ledger"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_credit_ledger_idempotency_key"),
    )

    id = Column(BigInteger(), primary_key=True)
    user_id = Column(BigInteger(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    account_id = Column(BigInteger(), ForeignKey("user_credit_accounts.id", ondelete="CASCADE"), nullable=False)
    gift_amount = Column(Numeric(20, 2), nullable=False, default=0, server_default="0")
    direction = Column(String(16), nullable=False)
    amount = Column(Numeric(20, 2), nullable=False)
    balance_before = Column(Numeric(20, 2), nullable=False)
    balance_after = Column(Numeric(20, 2), nullable=False)
    biz_type = Column(String(40), nullable=False)
    biz_id = Column(String(120))
    idempotency_key = Column(String(160), nullable=False)
    description = Column(Text)
    operator_type = Column(String(20), nullable=False)
    operator_id = Column(BigInteger())
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
