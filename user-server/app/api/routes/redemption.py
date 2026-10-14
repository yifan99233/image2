import asyncio
import hashlib
import re
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.api.routes.rewards import get_or_create_credit_account_for_update
from app.core.exceptions import BusinessError
from app.core.responses import ok
from app.db.session import get_db
from app.models.agent import AgentConfig
from app.models.credit import CreditLedger
from app.models.redemption import RedemptionCode
from app.models.user import User
from app.services.agent_openapi import AgentAPIError, AgentOpenAPIClient
from app.services.rate_limit import login_rate_limit_key
from app.services.sub2_image_billing import _billing_context, _to_sub2_amount

router = APIRouter(prefix="/credits", tags=["credits"])


class RedeemRequest(BaseModel):
    code: str = Field(min_length=1, max_length=100)


def code_digest(code: str) -> str:
    normalized = re.sub(r"[\s-]", "", code).upper()
    if not re.fullmatch(r"[0-9A-F]{40}", normalized):
        raise BusinessError("兑换码无效", code=40060)
    return hashlib.sha256(normalized.encode()).hexdigest()


def result(row):
    return {"amount": row.amount, "balance_type": "gift", "redeemed_at": row.redeemed_at}


async def redeem_credit(db: AsyncSession, user: User, code: str):
    user_id, site_id = int(user.id), int(user.site_id)
    digest = code_digest(code)
    row = await db.scalar(select(RedemptionCode).where(
        RedemptionCode.code_hash == digest, RedemptionCode.site_id == site_id,
    ).with_for_update())
    if row is None:
        raise BusinessError("兑换码无效", code=40060)
    if row.status == "redeemed" and row.redeemed_by == user_id:
        return result(row)  # A lost response may safely be retried by its owner.
    if row.status == "disabled":
        raise BusinessError("兑换码已停用", code=40061)
    if row.status == "redeemed" or (row.status == "processing" and row.redeemed_by != user_id):
        raise BusinessError("兑换码已被使用", code=40062)
    if row.status == "unused":
        if row.expires_at and row.expires_at <= datetime.now(timezone.utc):
            raise BusinessError("兑换码已过期", code=40063)
        context = await _billing_context(db, user_id, require_image_billing=False)
        if context is not None:
            if int(context.account.user_id) != user_id:
                raise BusinessError("请切换到个人工作区兑换，赠送额度归个人账户", code=40064)
            row.agent_user_id = int(context.account.agent_user_id)
            row.agent_base_url = context.config.base_url.rstrip("/")
            row.agent_amount = _to_sub2_amount(row.amount, context.config)
        row.status = "processing"
        row.redeemed_by = user_id
        row.claimed_at = datetime.now(timezone.utc)
        # Durable ownership is essential: a remote timeout must not release the code
        # for another user, or permit a retry to credit a different upstream wallet.
        await db.commit()
        row = await db.scalar(select(RedemptionCode).where(
            RedemptionCode.code_hash == digest, RedemptionCode.site_id == site_id,
        ).with_for_update().execution_options(populate_existing=True))
        if row.status == "redeemed":
            return result(row)

    account = await get_or_create_credit_account_for_update(db, user_id)
    if account.balance + row.amount > 2_000_000_000 or account.gift_balance + row.amount > 2_000_000_000:
        raise BusinessError("余额超过账户上限，请联系管理员", code=40065)
    if row.agent_user_id is not None:
        config = await db.scalar(select(AgentConfig).where(AgentConfig.site_id == site_id))
        if config is None or not config.is_enabled or config.base_url.rstrip("/") != row.agent_base_url:
            raise BusinessError("兑换处理中，账户服务配置已变化，请联系管理员", code=50395, status_code=503)
        try:
            await asyncio.to_thread(
                AgentOpenAPIClient(config).add_balance,
                agent_user_id=row.agent_user_id, amount=row.agent_amount,
                idempotency_key=f"image2-redeem:{row.id}", notes=f"image2 兑换码赠送 {row.id}",
            )
        except AgentAPIError as error:
            # Do not expose upstream response bodies or secrets to users.
            raise BusinessError("到账处理中，请用同一兑换码重试，不会重复到账", code=50396, status_code=503) from error
    before = account.balance
    account.balance += row.amount
    account.gift_balance += row.amount
    account.total_gifted += row.amount
    account.version += 1
    db.add(CreditLedger(user_id=user_id, account_id=account.id, direction="credit", amount=row.amount,
                        gift_amount=row.amount, balance_before=before, balance_after=account.balance,
                        biz_type="redemption_gift", biz_id=row.id, idempotency_key=f"redemption:{row.id}",
                        description=f"兑换码赠送 {row.amount} 积分", operator_type="user", operator_id=user_id))
    row.status = "redeemed"
    row.redeemed_at = datetime.now(timezone.utc)
    await db.commit()
    return result(row)


@router.post("/redeem")
async def redeem(payload: RedeemRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if not await login_rate_limit_key(f"redemption:{user.site_id}:{user.id}"):
        raise BusinessError("兑换尝试过于频繁，请稍后再试", code=42960, status_code=429)
    return ok(await redeem_credit(db, user, payload.code), "兑换成功，已计入赠送余额")
