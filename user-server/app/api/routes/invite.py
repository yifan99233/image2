from fastapi import APIRouter, Depends, Request
from sqlalchemy import BigInteger, Boolean, Column, DateTime, Integer, MetaData, String, Table, desc, func, outerjoin, select
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.responses import StandardResponse, ok
from app.db.session import get_db
from app.models.credit import CreditLedger, UserCreditAccount
from app.models.user import User
from app.services.reward_invites import create_reward_invite_token

router = APIRouter(prefix="/invite", tags=["invite"])

shared_metadata = MetaData()
invite_reward_configs_table = Table(
    "invite_reward_configs",
    shared_metadata,
    Column("id", BigInteger),
    Column("site_id", BigInteger),
    Column("is_enabled", Boolean),
    Column("valid_user_reward_credits", Integer),
    Column("recharge_reward_percent", Integer),
    Column("valid_user_rule", String),
    Column("updated_at", DateTime(timezone=True)),
)


def default_config() -> dict:
    return {
        "is_enabled": False,
        "valid_user_reward_credits": 0,
        "recharge_reward_percent": 0,
        "valid_user_rule": "invited_user_first_paid_recharge",
        "valid_user_rule_label": "被邀请用户完成首次付费充值后成为有效用户",
    }


def public_invite_url(request: Request, user_id: int, site_id: int) -> str:
    origin = request.headers.get("origin") or str(request.base_url).rstrip("/")
    token = create_reward_invite_token(inviter_user_id=user_id, site_id=site_id)
    return f"{origin.rstrip('/')}/r/{token}"


@router.get("/reward-config", response_model=StandardResponse[dict])
async def invite_reward_config(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StandardResponse[dict]:
    try:
        result = await db.execute(select(invite_reward_configs_table).where(invite_reward_configs_table.c.site_id == current_user.site_id))
        row = result.mappings().first()
    except (OperationalError, ProgrammingError) as error:
        await db.rollback()
        if "invite_reward_configs" in str(error).lower():
            config = default_config()
            config.update(
                {
                    "invite_code": f"U{current_user.id}",
                    "invite_url": public_invite_url(request, current_user.id, current_user.site_id),
                }
            )
            return ok(config)
        raise

    config = default_config()
    if row:
        config.update(
            {
                "is_enabled": bool(row.is_enabled),
                "valid_user_reward_credits": int(row.valid_user_reward_credits or 0),
                "recharge_reward_percent": int(row.recharge_reward_percent or 0),
                "valid_user_rule": row.valid_user_rule or "invited_user_first_paid_recharge",
            }
        )
    config.update(
        {
            "invite_code": f"U{current_user.id}",
            "invite_url": public_invite_url(request, current_user.id, current_user.site_id),
        }
    )
    return ok(config)


@router.get("/summary", response_model=StandardResponse[dict])
async def invite_summary(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StandardResponse[dict]:
    invitee_join = outerjoin(User, UserCreditAccount, UserCreditAccount.user_id == User.id)
    invitee_rows = await db.execute(
        select(
            User.id,
            User.username,
            User.email,
            User.created_at,
            UserCreditAccount.total_recharged,
        )
        .select_from(invitee_join)
        .where(User.invited_by_user_id == current_user.id, User.site_id == current_user.site_id, User.deleted_at.is_(None))
        .order_by(desc(User.created_at))
        .limit(100)
    )
    reward_rows = await db.scalars(
        select(CreditLedger)
        .where(CreditLedger.user_id == current_user.id, CreditLedger.biz_type == "invite")
        .order_by(desc(CreditLedger.created_at))
        .limit(100)
    )
    total_invitees = await db.scalar(
        select(func.count()).select_from(User).where(User.invited_by_user_id == current_user.id, User.site_id == current_user.site_id, User.deleted_at.is_(None))
    )
    valid_invitees = await db.scalar(
        select(func.count())
        .select_from(invitee_join)
        .where(
            User.invited_by_user_id == current_user.id,
            User.site_id == current_user.site_id,
            User.deleted_at.is_(None),
            UserCreditAccount.total_recharged > 0,
        )
    )
    invitees = []
    for row in invitee_rows.mappings():
        total_recharged = int(row.total_recharged or 0)
        invitees.append(
            {
                "id": row.id,
                "username": row.username,
                "email": row.email,
                "registered_at": row.created_at.isoformat() if row.created_at else "",
                "total_recharged": total_recharged,
                "is_valid": total_recharged > 0,
            }
        )

    rewards = [
        {
            "id": row.id,
            "amount": row.amount,
            "balance_after": row.balance_after,
            "description": row.description or "",
            "biz_id": row.biz_id,
            "created_at": row.created_at.isoformat() if row.created_at else "",
        }
        for row in reward_rows
    ]
    return ok(
        {
            "total_invitees": total_invitees or 0,
            "valid_invitees": valid_invitees or 0,
            "total_reward_credits": sum(item["amount"] for item in rewards),
            "invitees": invitees,
            "rewards": rewards,
        }
    )
