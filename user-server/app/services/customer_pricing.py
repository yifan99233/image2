"""Server-owned prices. A task stores the result and its immutable calculation."""
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import BigInteger, Boolean, Column, DateTime, MetaData, Numeric, String, Table, select

from app.models.agent import AgentConfig
from app.services.team_sharing import get_agent_billing_team
from app.services.sub2_image_billing import _to_sub2_amount

metadata = MetaData()
vip_tiers = Table("customer_vip_tiers", metadata,
    Column("id", BigInteger, primary_key=True), Column("site_id", BigInteger),
    Column("name", String(64)), Column("discount_rate", Numeric(5, 4)), Column("is_active", Boolean))
vip_memberships = Table("customer_vip_memberships", metadata,
    Column("user_id", BigInteger, primary_key=True), Column("site_id", BigInteger),
    Column("tier_id", BigInteger), Column("expires_at", DateTime(timezone=True)))


def calculate_price(base_price, discount_rate=1, fixed_surcharge=0) -> Decimal:
    # Round once per output so batch totals and individual refunds agree exactly.
    return (Decimal(str(base_price)) * Decimal(str(discount_rate)) + Decimal(str(fixed_surcharge))).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP)


async def customer_price(db, user, price) -> dict:
    config = await db.scalar(select(AgentConfig).where(AgentConfig.site_id == user.site_id))
    payer_id = user.id
    if config and config.image_billing_enabled:
        team = await get_agent_billing_team(db, user)
        if team is not None:
            payer_id = team.owner_user_id
    membership = (await db.execute(select(vip_tiers.c.id, vip_tiers.c.name, vip_tiers.c.discount_rate)
        .join(vip_memberships, vip_memberships.c.tier_id == vip_tiers.c.id)
        .where(vip_memberships.c.user_id == payer_id, vip_memberships.c.site_id == user.site_id,
               vip_tiers.c.site_id == user.site_id, vip_tiers.c.is_active.is_(True),
               (vip_memberships.c.expires_at.is_(None)) | (vip_memberships.c.expires_at > datetime.now(timezone.utc))))).first()
    rate = membership.discount_rate if membership else Decimal("1")
    cost = calculate_price(price.credit_cost, rate, price.fixed_surcharge)
    if config and config.image_billing_enabled:
        # Reject an unrepresentable upstream amount before accepting any tasks.
        _to_sub2_amount(cost, config)
    snapshot = {"price_id": price.id, "price_version": price.version, "payer_user_id": payer_id,
                "base_price": str(price.credit_cost), "discount_rate": str(rate),
                "fixed_surcharge": str(price.fixed_surcharge), "credit_cost": str(cost),
                "vip_tier_id": membership.id if membership else None,
                "vip_tier_name": membership.name if membership else "普通客户"}
    return {"credit_cost": cost, "work_type": price.work_type, "pricing": snapshot}
