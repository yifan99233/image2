from sqlalchemy import BigInteger, Boolean, Column, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint, func

from app.db.base import Base
from app.db.encrypted_credentials import EncryptedCredential


class AgentConfig(Base):
    __tablename__ = "agent_configs"

    id = Column(BigInteger(), primary_key=True)
    site_id = Column(BigInteger(), nullable=False, default=1, server_default="1", index=True)
    is_enabled = Column(Boolean, nullable=False, default=False, server_default="false")
    image_billing_enabled = Column(Boolean, nullable=False, default=False, server_default="false")
    base_url = Column(String(512), nullable=False, default="", server_default="")
    admin_api_key = Column(String(512), nullable=False, default="", server_default="")
    credit_to_agent_rate = Column(Numeric(12, 4), nullable=False, default=1, server_default="1")
    text_group_id = Column(BigInteger())
    image_group_id = Column(BigInteger())
    create_api_key_path = Column(String(255), nullable=False, default="", server_default="")
    user_concurrency = Column(Integer, nullable=False, default=0, server_default="0")
    user_rpm_limit = Column(Integer, nullable=False, default=0, server_default="0")
    updated_by = Column(BigInteger())
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class UserAgentAccount(Base):
    __tablename__ = "user_agent_accounts"
    __table_args__ = (UniqueConstraint("user_id", name="uq_user_agent_accounts_user_id"),)

    id = Column(BigInteger(), primary_key=True)
    user_id = Column(BigInteger(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    team_id = Column(BigInteger(), index=True)
    agent_user_id = Column(BigInteger())
    agent_email = Column(String(255), nullable=False)
    agent_password = Column(EncryptedCredential())
    text_api_key_id = Column(BigInteger())
    text_api_key = Column(String(1024))
    image_api_key_id = Column(BigInteger())
    image_api_key = Column(String(1024))
    status = Column(String(32), nullable=False, default="pending", server_default="pending")
    failure_message = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class UserAgentApiKey(Base):
    __tablename__ = "user_agent_api_keys"
    __table_args__ = (
        UniqueConstraint("agent_user_id", "agent_key_id", name="uq_user_agent_api_keys_agent_key"),
        UniqueConstraint("team_id", "user_id", "agent_key_id", name="uq_user_agent_api_keys_team_user_key"),
    )

    id = Column(BigInteger(), primary_key=True)
    site_id = Column(BigInteger(), nullable=False, index=True)
    team_id = Column(BigInteger(), nullable=False, index=True)
    user_id = Column(BigInteger(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    agent_user_id = Column(BigInteger(), nullable=False, index=True)
    agent_key_id = Column(BigInteger(), nullable=False)
    api_key = Column(String(1024), nullable=False)
    name = Column(String(255), nullable=False, default="", server_default="")
    group_id = Column(BigInteger())
    is_deleted = Column(Boolean(), nullable=False, default=False, server_default="false")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class AgentTransferRecord(Base):
    __tablename__ = "agent_transfer_records"
    __table_args__ = (UniqueConstraint("idempotency_key", name="uq_agent_transfer_records_idempotency_key"),)

    id = Column(BigInteger(), primary_key=True)
    user_id = Column(BigInteger(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    credit_ledger_id = Column(BigInteger())
    credit_amount = Column(Integer, nullable=False)
    agent_amount = Column(Numeric(12, 4), nullable=False)
    agent_user_id = Column(BigInteger())
    idempotency_key = Column(String(160), nullable=False)
    status = Column(String(32), nullable=False, default="pending", server_default="pending")
    failure_message = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class Sub2BalanceOperation(Base):
    __tablename__ = "sub2_balance_operations"
    __table_args__ = (UniqueConstraint("idempotency_key", name="uq_sub2_balance_operations_idempotency_key"),)

    id = Column(BigInteger(), primary_key=True)
    site_id = Column(BigInteger(), nullable=False, index=True)
    user_id = Column(BigInteger(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    agent_user_id = Column(BigInteger(), nullable=False)
    operation = Column(String(16), nullable=False)
    amount = Column(Numeric(18, 4), nullable=False)
    biz_type = Column(String(40), nullable=False)
    biz_id = Column(String(120), nullable=False)
    idempotency_key = Column(String(160), nullable=False)
    notes = Column(String(255), nullable=False, default="", server_default="")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class TeamMemberUsageLimit(Base):
    __tablename__ = "team_member_usage_limits"
    __table_args__ = (
        UniqueConstraint("team_id", "user_id", name="uq_team_member_usage_limits_team_user"),
    )

    id = Column(BigInteger(), primary_key=True)
    site_id = Column(BigInteger(), nullable=False, index=True)
    team_id = Column(BigInteger(), nullable=False, index=True)
    user_id = Column(BigInteger(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    text_quota = Column(Numeric(18, 4), nullable=False, default=0, server_default="0")
    image_quota = Column(Numeric(18, 4), nullable=False, default=0, server_default="0")
    updated_by_user_id = Column(BigInteger(), ForeignKey("users.id", ondelete="SET NULL"))
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
