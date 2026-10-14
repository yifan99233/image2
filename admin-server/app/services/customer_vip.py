from datetime import datetime, timezone
from typing import Literal

from sqlalchemy import BigInteger, Boolean, Column, DateTime, MetaData, Numeric, String, Table, select

metadata = MetaData()
tiers = Table("customer_vip_tiers", metadata,
    Column("id", BigInteger, primary_key=True), Column("site_id", BigInteger),
    Column("name", String(64)), Column("discount_rate", Numeric(5, 4)), Column("is_active", Boolean),
    Column("created_at", DateTime(timezone=True)), Column("updated_at", DateTime(timezone=True)))
memberships = Table("customer_vip_memberships", metadata,
    Column("user_id", BigInteger, primary_key=True), Column("site_id", BigInteger), Column("tier_id", BigInteger),
    Column("expires_at", DateTime(timezone=True)), Column("updated_at", DateTime(timezone=True)))


async def memberships_for_users(db, ids):
    if not ids:
        return {}
    rows = (await db.execute(select(memberships.c.user_id, memberships.c.tier_id, memberships.c.expires_at,
        tiers.c.name, tiers.c.discount_rate, tiers.c.is_active)
        .join(tiers, (tiers.c.id == memberships.c.tier_id) & (tiers.c.site_id == memberships.c.site_id))
        .where(memberships.c.user_id.in_(ids)))).mappings().all()
    return {row["user_id"]: dict(row) for row in rows}


VipStatus = Literal["all", "active", "expired", "disabled", "ordinary"]


def membership_status_condition(users, status: VipStatus):
    """Filter before pagination, with the same expiry/disabled precedence as pricing."""
    member = select(memberships.c.user_id).join(
        tiers, (tiers.c.id == memberships.c.tier_id) & (tiers.c.site_id == memberships.c.site_id)
    ).where(memberships.c.user_id == users.c.id, memberships.c.site_id == users.c.site_id)
    if status == "ordinary":
        return ~member.exists()
    now = datetime.now(timezone.utc)
    if status == "active":
        member = member.where(tiers.c.is_active.is_(True), (memberships.c.expires_at.is_(None)) | (memberships.c.expires_at > now))
    elif status == "expired":
        member = member.where(tiers.c.is_active.is_(True), memberships.c.expires_at <= now)
    elif status == "disabled":
        member = member.where(tiers.c.is_active.is_(False))
    else:
        raise ValueError("Unsupported VIP status filter")
    return member.exists()
