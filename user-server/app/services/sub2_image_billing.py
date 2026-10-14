from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_FLOOR, ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BusinessError
from app.models.agent import AgentConfig, Sub2BalanceOperation, UserAgentAccount
from app.models.user import User
from app.services.agent_openapi import AgentAPIError, AgentOpenAPIClient
from app.services.team_sharing import get_agent_billing_team


@dataclass(frozen=True)
class Sub2BalanceReceipt:
    site_id: int
    user_id: int
    agent_user_id: int
    amount: Decimal
    debit_idempotency_key: str
    refund_idempotency_key: str
    biz_id: str


@dataclass(frozen=True)
class _BillingContext:
    config: AgentConfig
    account: UserAgentAccount


async def _billing_context(
    db: AsyncSession,
    user_id: int,
    *,
    require_image_billing: bool = True,
) -> _BillingContext | None:
    user = await db.scalar(select(User).where(User.id == user_id))
    if user is None:
        raise BusinessError("用户不存在", code=40401, status_code=404)
    config = await db.scalar(select(AgentConfig).where(AgentConfig.site_id == user.site_id))
    if config is None:
        return None
    if require_image_billing and not config.image_billing_enabled:
        return None
    if not config.is_enabled:
        if require_image_billing and config.image_billing_enabled:
            raise BusinessError("账户计费服务尚未配置", code=50381, status_code=503)
        return None
    # The selected workspace determines the wallet owner.  Do not use the
    # requester's cached account row here: older team members may still have a
    # personal account row even while their active workspace is an external
    # team.  The team owner's account is the shared wallet for team mode; the
    # user's own workspace resolves to their own account.
    billing_team = await get_agent_billing_team(db, user)
    if billing_team is None:
        raise BusinessError("计费工作区尚未准备完成", code=50382, status_code=503)
    account = await db.scalar(
        select(UserAgentAccount).where(
            UserAgentAccount.user_id == int(billing_team.owner_user_id),
            UserAgentAccount.team_id == int(billing_team.id),
        )
    )
    if account is None:
        # Accounts created before team wallets were introduced have no
        # team_id. They are safe to reuse only when they belong to the
        # selected workspace owner; never fall back to the requester's row
        # while an external team is selected.
        account = await db.scalar(
            select(UserAgentAccount).where(
                UserAgentAccount.user_id == int(billing_team.owner_user_id),
                UserAgentAccount.team_id.is_(None),
            )
        )
    if account is None or not account.agent_user_id or account.status != "active":
        raise BusinessError("当前计费工作区账户尚未准备完成", code=50382, status_code=503)
    return _BillingContext(config=config, account=account)


def _to_sub2_amount(credit_amount: Decimal, config: AgentConfig) -> Decimal:
    rate = Decimal(str(config.credit_to_agent_rate))
    if rate <= 0:
        raise BusinessError("积分兑换比例配置错误", code=50383, status_code=503)
    amount = (Decimal(str(credit_amount)) / rate).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    if amount <= 0:
        raise BusinessError("图片扣费金额低于账户最小精度", code=50389, status_code=503)
    if amount * rate != Decimal(str(credit_amount)):
        raise BusinessError("当前积分兑换比例无法精确结算该价格，请调整兑换比例或模型价格", code=50389, status_code=503)
    return amount


def _to_display_credits(agent_balance: Decimal, config: AgentConfig) -> Decimal:
    rate = Decimal(str(config.credit_to_agent_rate))
    if rate <= 0:
        raise BusinessError("积分兑换比例配置错误", code=50383, status_code=503)
    return (agent_balance * rate).quantize(Decimal("0.01"), rounding=ROUND_FLOOR)


def _record_operation(
    db: AsyncSession,
    *,
    receipt: Sub2BalanceReceipt,
    operation: str,
    biz_type: str,
    idempotency_key: str,
    notes: str,
) -> None:
    db.add(
        Sub2BalanceOperation(
            site_id=receipt.site_id,
            user_id=receipt.user_id,
            agent_user_id=receipt.agent_user_id,
            operation=operation,
            amount=receipt.amount,
            biz_type=biz_type,
            biz_id=receipt.biz_id,
            idempotency_key=idempotency_key,
            notes=notes[:255],
        )
    )


async def debit_image_task_balance(
    db: AsyncSession,
    *,
    user_id: int,
    task_no: str,
    credit_amount: Decimal,
) -> Sub2BalanceReceipt | None:
    if credit_amount <= 0:
        return None
    context = await _billing_context(db, user_id)
    if context is None:
        return None
    amount = _to_sub2_amount(credit_amount, context.config)
    receipt = Sub2BalanceReceipt(
        site_id=int(context.config.site_id),
        user_id=user_id,
        agent_user_id=int(context.account.agent_user_id),
        amount=amount,
        debit_idempotency_key=f"image2-image-debit:{task_no}",
        refund_idempotency_key=f"image2-image-refund:{task_no}",
        biz_id=task_no,
    )
    notes = f"image2 图片任务 {task_no}"
    try:
        await asyncio.to_thread(
            AgentOpenAPIClient(context.config).subtract_balance,
            agent_user_id=receipt.agent_user_id,
            amount=receipt.amount,
            idempotency_key=receipt.debit_idempotency_key,
            notes=notes,
        )
    except AgentAPIError as error:
        raise BusinessError("余额不足或扣费失败", code=40281, status_code=402) from error
    _record_operation(
        db,
        receipt=receipt,
        operation="subtract",
        biz_type="image_task",
        idempotency_key=receipt.debit_idempotency_key,
        notes=notes,
    )
    return receipt


async def _receipt_from_debit_operation(db: AsyncSession, task_no: str) -> Sub2BalanceReceipt | None:
    operation = await db.scalar(
        select(Sub2BalanceOperation).where(
            Sub2BalanceOperation.idempotency_key == f"image2-image-debit:{task_no}",
            Sub2BalanceOperation.operation == "subtract",
        )
    )
    if operation is None:
        return None
    return Sub2BalanceReceipt(
        site_id=int(operation.site_id),
        user_id=int(operation.user_id),
        agent_user_id=int(operation.agent_user_id),
        amount=Decimal(str(operation.amount)),
        debit_idempotency_key=str(operation.idempotency_key),
        refund_idempotency_key=f"image2-image-refund:{task_no}",
        biz_id=task_no,
    )


async def refund_image_task_balance(
    db: AsyncSession,
    *,
    task_no: str,
    receipt: Sub2BalanceReceipt | None = None,
) -> bool:
    receipt = receipt or await _receipt_from_debit_operation(db, task_no)
    if receipt is None:
        return False
    config = await db.scalar(select(AgentConfig).where(AgentConfig.site_id == receipt.site_id))
    if config is None:
        raise BusinessError("账户计费服务尚未配置", code=50381, status_code=503)
    notes = f"image2 图片任务退款 {task_no}"
    try:
        await asyncio.to_thread(
            AgentOpenAPIClient(config).add_balance,
            agent_user_id=receipt.agent_user_id,
            amount=receipt.amount,
            idempotency_key=receipt.refund_idempotency_key,
            notes=notes,
        )
    except AgentAPIError as error:
        raise BusinessError("账户退款失败，请稍后重试", code=50384, status_code=503) from error
    _record_operation(
        db,
        receipt=receipt,
        operation="add",
        biz_type="image_task_refund",
        idempotency_key=receipt.refund_idempotency_key,
        notes=notes,
    )
    return True


async def credit_recharge_balance(
    db: AsyncSession,
    *,
    user_id: int,
    order_no: str,
    credit_amount: Decimal,
) -> bool:
    if credit_amount <= 0:
        return False
    context = await _billing_context(db, user_id, require_image_billing=False)
    if context is None:
        return False
    amount = _to_sub2_amount(credit_amount, context.config)
    idempotency_key = f"image2-recharge:{order_no}"
    receipt = Sub2BalanceReceipt(
        site_id=int(context.config.site_id),
        user_id=user_id,
        agent_user_id=int(context.account.agent_user_id),
        amount=amount,
        debit_idempotency_key=idempotency_key,
        refund_idempotency_key="",
        biz_id=order_no,
    )
    notes = f"image2 充值订单 {order_no}"
    try:
        await asyncio.to_thread(
            AgentOpenAPIClient(context.config).add_balance,
            agent_user_id=receipt.agent_user_id,
            amount=receipt.amount,
            idempotency_key=idempotency_key,
            notes=notes,
        )
    except AgentAPIError as error:
        raise BusinessError("充值到账处理失败，请稍后重试", code=50386, status_code=503) from error
    _record_operation(
        db,
        receipt=receipt,
        operation="add",
        biz_type="recharge",
        idempotency_key=idempotency_key,
        notes=notes,
    )
    return True


async def credit_signin_balance(
    db: AsyncSession,
    *,
    user_id: int,
    sign_date: date,
    credit_amount: Decimal,
) -> int | None:
    """Credit the authoritative Agent wallet for one daily sign-in."""
    if credit_amount <= 0:
        return None
    context = await _billing_context(db, user_id)
    if context is None:
        return None
    amount = _to_sub2_amount(credit_amount, context.config)
    idempotency_key = f"image2-signin:{user_id}:{sign_date.isoformat()}"
    receipt = Sub2BalanceReceipt(
        site_id=int(context.config.site_id),
        user_id=user_id,
        agent_user_id=int(context.account.agent_user_id),
        amount=amount,
        debit_idempotency_key=idempotency_key,
        refund_idempotency_key="",
        biz_id=f"signin:{sign_date.isoformat()}",
    )
    notes = f"image2 每日签到 {sign_date.isoformat()}"
    try:
        agent_user = await asyncio.to_thread(
            AgentOpenAPIClient(context.config).add_balance,
            agent_user_id=receipt.agent_user_id,
            amount=receipt.amount,
            idempotency_key=idempotency_key,
            notes=notes,
        )
    except AgentAPIError as error:
        raise BusinessError("签到积分到账失败，请稍后重试", code=50390, status_code=503) from error
    _record_operation(
        db,
        receipt=receipt,
        operation="add",
        biz_type="signin",
        idempotency_key=idempotency_key,
        notes=notes,
    )
    return _to_display_credits(agent_user.balance, context.config)


async def authoritative_credit_balance(db: AsyncSession, *, user_id: int) -> Decimal | None:
    context = await _billing_context(db, user_id)
    if context is None:
        return None
    try:
        agent_user = await asyncio.to_thread(
            AgentOpenAPIClient(context.config).get_user,
            int(context.account.agent_user_id),
        )
    except AgentAPIError as error:
        raise BusinessError("余额查询失败，请稍后重试", code=50387, status_code=502) from error
    return _to_display_credits(agent_user.balance, context.config)
