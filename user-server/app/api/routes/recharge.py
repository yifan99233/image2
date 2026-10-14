import asyncio
import urllib.parse
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from fastapi import APIRouter, Depends, Request
from fastapi.responses import PlainTextResponse, RedirectResponse
from sqlalchemy import BigInteger, Boolean, Column, DateTime, Integer, MetaData, String, Table, Text, insert, select, update
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.config import settings
from app.core.exceptions import BusinessError
from app.core.responses import StandardResponse, ok
from app.db.session import get_db
from app.models.credit import CreditLedger, UserCreditAccount
from app.models.user import User
from app.services.team_sharing import grant_team_entitlement
from app.services.sub2_image_billing import credit_recharge_balance
from app.services.zpay import ZPayClient, ZPayConfig, ZPayError

router = APIRouter(tags=["recharge"])

shared_metadata = MetaData()
recharge_plans_table = Table(
    "recharge_plans",
    shared_metadata,
    Column("id", BigInteger),
    Column("site_id", BigInteger),
    Column("name", String),
    Column("amount_cents", Integer),
    Column("credit_amount", Integer),
    Column("bonus_credit_amount", Integer),
    Column("team_seat_count", Integer),
    Column("team_duration_days", Integer),
    Column("badge", String),
    Column("sort_order", Integer),
    Column("is_recommended", Boolean),
    Column("is_active", Boolean),
)
recharge_orders_table = Table(
    "recharge_orders",
    shared_metadata,
    Column("id", BigInteger),
    Column("site_id", BigInteger),
    Column("order_no", String),
    Column("user_id", BigInteger),
    Column("plan_id", BigInteger),
    Column("amount_cents", Integer),
    Column("credit_amount", Integer),
    Column("bonus_credit_amount", Integer),
    Column("team_seat_count", Integer),
    Column("team_duration_days", Integer),
    Column("status", String),
    Column("payment_provider", String),
    Column("payment_type", String),
    Column("payment_trade_no", String),
    Column("pay_url", Text),
    Column("qr_code", Text),
    Column("failure_message", Text),
    Column("expires_at", DateTime(timezone=True)),
    Column("paid_at", DateTime(timezone=True)),
    Column("created_at", DateTime(timezone=True)),
    Column("updated_at", DateTime(timezone=True)),
)
payment_configs_table = Table(
    "payment_configs",
    shared_metadata,
    Column("id", BigInteger),
    Column("site_id", BigInteger),
    Column("provider", String),
    Column("is_enabled", Boolean),
    Column("pid", String),
    Column("pkey", Text),
    Column("api_base", Text),
    Column("notify_url", Text),
    Column("return_url", Text),
    Column("payment_type", String),
    Column("payment_mode", String),
    Column("timeout_seconds", Integer),
    Column("order_expire_minutes", Integer),
    Column("updated_at", DateTime(timezone=True)),
)


async def get_or_create_credit_account_for_update(db: AsyncSession, user_id: int) -> UserCreditAccount:
    account = await db.scalar(select(UserCreditAccount).where(UserCreditAccount.user_id == user_id).with_for_update())
    if account:
        return account
    account = UserCreditAccount(user_id=user_id, balance=0, total_recharged=0, total_consumed=0)
    db.add(account)
    await db.flush()
    return account


def add_credit_ledger(
    db: AsyncSession,
    *,
    user_id: int,
    account_id: int,
    direction: str,
    amount: int,
    balance_before: int,
    balance_after: int,
    biz_type: str,
    biz_id: str,
    idempotency_key: str,
    description: str,
) -> None:
    db.add(
        CreditLedger(
            user_id=user_id,
            account_id=account_id,
            direction=direction,
            amount=amount,
            balance_before=balance_before,
            balance_after=balance_after,
            biz_type=biz_type,
            biz_id=biz_id,
            idempotency_key=idempotency_key,
            description=description,
            operator_type="system",
        )
    )


def amount_cents_to_yuan(amount_cents: int) -> str:
    return f"{Decimal(amount_cents) / Decimal(100):.2f}"


def zpay_client_from_values(values: dict) -> ZPayClient:
    if not values["is_enabled"]:
        raise BusinessError("支付功能暂未开启", code=41002)
    try:
        return ZPayClient(
            ZPayConfig(
                pid=str(values["pid"] or ""),
                pkey=str(values["pkey"] or ""),
                api_base=str(values["api_base"] or ""),
                notify_url=str(values["notify_url"] or ""),
                return_url=str(values["return_url"] or ""),
                payment_type=str(values["payment_type"] or "alipay"),
                payment_mode=str(values["payment_mode"] or "qrcode"),
                timeout_seconds=int(values["timeout_seconds"] or settings.zpay_timeout_seconds),
            )
        )
    except ZPayError as error:
        raise BusinessError(f"支付配置错误：{error}", code=41003) from error


def zpay_settings_values() -> dict:
    return {
        "is_enabled": settings.zpay_enabled,
        "pid": settings.zpay_pid,
        "pkey": settings.zpay_pkey,
        "api_base": settings.zpay_api_base,
        "notify_url": settings.zpay_notify_url,
        "return_url": settings.zpay_return_url,
        "payment_type": settings.zpay_payment_type,
        "payment_mode": settings.zpay_payment_mode,
        "timeout_seconds": settings.zpay_timeout_seconds,
        "order_expire_minutes": settings.recharge_order_expire_minutes,
    }


async def zpay_config_values(db: AsyncSession, site_id: int) -> dict:
    try:
        result = await db.execute(select(payment_configs_table).where(payment_configs_table.c.site_id == site_id, payment_configs_table.c.provider == "zpay"))
        row = result.mappings().first()
        if row:
            return {
                key: row[key] if row[key] is not None else zpay_settings_values()[key]
                for key in zpay_settings_values()
            }
    except (OperationalError, ProgrammingError) as error:
        await db.rollback()
        if "payment_configs" not in str(error).lower():
            raise
        return zpay_settings_values()
    return zpay_settings_values()


async def zpay_client_from_config(db: AsyncSession, site_id: int) -> tuple[ZPayClient, dict]:
    values = await zpay_config_values(db, site_id)
    return zpay_client_from_values(values), values


def recharge_order_no() -> str:
    return f"RC{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}{uuid4().hex[:8].upper()}"


def row_value(row, key: str, default=None):
    if row is None:
        return default
    if isinstance(row, dict):
        return row.get(key, default)
    return getattr(row, key, default)


def recharge_order_out(row) -> dict:
    credit_amount = row_value(row, "credit_amount", 0) or 0
    bonus_credit_amount = row_value(row, "bonus_credit_amount", 0) or 0
    expires_at = row_value(row, "expires_at")
    paid_at = row_value(row, "paid_at")
    created_at = row_value(row, "created_at")
    return {
        "id": row_value(row, "id"),
        "order_no": row_value(row, "order_no"),
        "plan_id": row_value(row, "plan_id"),
        "amount_cents": row_value(row, "amount_cents"),
        "credit_amount": credit_amount,
        "bonus_credit_amount": bonus_credit_amount,
        "total_credit_amount": credit_amount + bonus_credit_amount,
        "team_seat_count": int(row_value(row, "team_seat_count", 0) or 0),
        "team_duration_days": int(row_value(row, "team_duration_days", 0) or 0),
        "status": row_value(row, "status"),
        "payment_provider": row_value(row, "payment_provider"),
        "payment_type": row_value(row, "payment_type"),
        "payment_trade_no": row_value(row, "payment_trade_no"),
        "pay_url": row_value(row, "pay_url"),
        "qr_code": row_value(row, "qr_code"),
        "qr_code_url": row_value(row, "qr_code"),
        "failure_message": row_value(row, "failure_message"),
        "expires_at": expires_at.isoformat() if expires_at else None,
        "paid_at": paid_at.isoformat() if paid_at else None,
        "created_at": created_at.isoformat() if created_at else None,
    }


async def get_recharge_order(db: AsyncSession, order_id: int, user_id: int, site_id: int):
    result = await db.execute(
        select(recharge_orders_table)
        .where(recharge_orders_table.c.id == order_id, recharge_orders_table.c.user_id == user_id, recharge_orders_table.c.site_id == site_id)
    )
    row = result.mappings().first()
    if not row:
        raise BusinessError("充值订单不存在", code=40430, status_code=404)
    return row


async def complete_recharge_order(
    db: AsyncSession,
    *,
    order_no: str,
    payment_trade_no: str,
    paid_amount_yuan: Decimal,
) -> bool:
    result = await db.execute(
        select(recharge_orders_table)
        .where(recharge_orders_table.c.order_no == order_no)
        .with_for_update()
    )
    order = result.mappings().first()
    if not order:
        raise BusinessError("充值订单不存在", code=40430, status_code=404)
    order_status = row_value(order, "status")
    order_id = row_value(order, "id")
    order_user_id = int(row_value(order, "user_id"))
    order_no_value = str(row_value(order, "order_no"))
    if order_status == "paid":
        return False
    if order_status not in {"pending", "failed"}:
        raise BusinessError("充值订单状态不可到账", code=42005)

    expected_yuan = Decimal(row_value(order, "amount_cents")) / Decimal(100)
    if paid_amount_yuan != expected_yuan:
        await db.execute(
            update(recharge_orders_table)
            .where(recharge_orders_table.c.id == order_id)
            .values(status="failed", failure_message=f"支付金额不匹配：应付 {expected_yuan}，实付 {paid_amount_yuan}", updated_at=datetime.now(UTC))
        )
        await db.commit()
        raise BusinessError("支付金额不匹配", code=42006)

    total_credits = int(row_value(order, "credit_amount", 0) or 0) + int(row_value(order, "bonus_credit_amount", 0) or 0)
    await credit_recharge_balance(
        db,
        user_id=order_user_id,
        order_no=order_no_value,
        credit_amount=total_credits,
    )
    account = await get_or_create_credit_account_for_update(db, order_user_id)
    balance_before = account.balance
    account.balance += total_credits
    account.total_recharged += total_credits
    account.version += 1
    add_credit_ledger(
        db,
        user_id=order_user_id,
        account_id=account.id,
        direction="credit",
        amount=total_credits,
        balance_before=balance_before,
        balance_after=account.balance,
        biz_type="recharge",
        biz_id=order_no_value,
        idempotency_key=f"recharge:{order_no_value}",
        description=f"充值到账 {total_credits} 积分",
    )
    team_seat_count = int(row_value(order, "team_seat_count", 0) or 0)
    if team_seat_count > 0:
        await grant_team_entitlement(
            db,
            site_id=int(row_value(order, "site_id") or 1),
            owner_user_id=order_user_id,
            seat_count=team_seat_count,
            source="recharge_plan",
            source_reference=order_no_value,
            duration_days=int(row_value(order, "team_duration_days", 0) or 0),
            note=f"充值档位订单 {order_no_value}",
        )
    await db.execute(
        update(recharge_orders_table)
        .where(recharge_orders_table.c.id == order_id)
        .values(status="paid", payment_trade_no=payment_trade_no, paid_at=datetime.now(UTC), updated_at=datetime.now(UTC), failure_message=None)
    )
    await db.commit()
    return True


@router.get("/recharge/plans", response_model=StandardResponse[list])
async def recharge_plans(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StandardResponse[list]:
    result = await db.execute(
        select(
            recharge_plans_table.c.id,
            recharge_plans_table.c.name,
            recharge_plans_table.c.amount_cents,
            recharge_plans_table.c.credit_amount,
            recharge_plans_table.c.bonus_credit_amount,
            recharge_plans_table.c.team_seat_count,
            recharge_plans_table.c.team_duration_days,
            recharge_plans_table.c.badge,
            recharge_plans_table.c.is_recommended,
        )
        .where(recharge_plans_table.c.site_id == current_user.site_id, recharge_plans_table.c.is_active.is_(True))
        .order_by(recharge_plans_table.c.sort_order.asc(), recharge_plans_table.c.id.desc())
    )
    return ok(
        [
            {
                "id": row.id,
                "name": row.name,
                "amount_cents": row.amount_cents,
                "credit_amount": row.credit_amount,
                "bonus_credit_amount": row.bonus_credit_amount,
                "total_credit_amount": row.credit_amount + row.bonus_credit_amount,
                "team_seat_count": int(row.team_seat_count or 0),
                "team_duration_days": int(row.team_duration_days or 0),
                "badge": row.badge,
                "is_recommended": row.is_recommended,
            }
            for row in result
        ]
    )


@router.post("/recharge/orders", response_model=StandardResponse[dict])
async def create_recharge_order(
    payload: dict,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StandardResponse[dict]:
    plan_id = int(payload.get("plan_id") or 0)
    plan = (
        await db.execute(
            select(recharge_plans_table)
            .where(recharge_plans_table.c.id == plan_id, recharge_plans_table.c.site_id == current_user.site_id, recharge_plans_table.c.is_active.is_(True))
        )
    ).mappings().first()
    if not plan:
        raise BusinessError("充值套餐不存在或已下架", code=40431, status_code=404)

    client, zpay_values = await zpay_client_from_config(db, current_user.site_id)
    order_no = recharge_order_no()
    now = datetime.now(UTC)
    expires_at = now + timedelta(minutes=max(1, int(zpay_values["order_expire_minutes"])))
    result = await db.execute(
        recharge_orders_table.insert()
        .values(
            order_no=order_no,
            site_id=current_user.site_id,
            user_id=current_user.id,
            plan_id=plan.id,
            amount_cents=plan.amount_cents,
            credit_amount=plan.credit_amount,
            bonus_credit_amount=plan.bonus_credit_amount,
            team_seat_count=int(plan.team_seat_count or 0),
            team_duration_days=int(plan.team_duration_days or 0),
            status="pending",
            payment_provider="zpay",
            payment_type=zpay_values["payment_type"],
            expires_at=expires_at,
            created_at=now,
            updated_at=now,
        )
        .returning(recharge_orders_table)
    )
    order = result.mappings().first()
    await db.commit()

    try:
        payment = await asyncio.to_thread(
            client.create_payment,
            order_no=order_no,
            amount_yuan=amount_cents_to_yuan(int(plan.amount_cents)),
            subject=f"积分充值-{plan.name}",
            client_ip=request.client.host if request.client else "",
        )
    except ZPayError as error:
        await db.execute(
            update(recharge_orders_table)
            .where(recharge_orders_table.c.order_no == order_no)
            .values(status="failed", failure_message=str(error), updated_at=datetime.now(UTC))
        )
        await db.commit()
        raise BusinessError(f"创建支付订单失败：{error}", code=50220, status_code=502) from error

    updated = await db.execute(
        update(recharge_orders_table)
        .where(recharge_orders_table.c.order_no == order_no)
        .values(pay_url=payment.pay_url, qr_code=payment.qr_code, updated_at=datetime.now(UTC))
        .returning(recharge_orders_table)
    )
    updated_order = updated.mappings().first()
    await db.commit()
    return ok(recharge_order_out(updated_order))


@router.get("/recharge/orders/{order_id}", response_model=StandardResponse[dict])
async def recharge_order(
    order_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StandardResponse[dict]:
    row = await get_recharge_order(db, order_id, current_user.id, current_user.site_id)
    expires_at = row_value(row, "expires_at")
    if row_value(row, "status") == "pending" and expires_at and expires_at < datetime.now(UTC):
        updated = await db.execute(
            update(recharge_orders_table)
            .where(recharge_orders_table.c.id == row_value(row, "id"), recharge_orders_table.c.status == "pending")
            .values(status="expired", updated_at=datetime.now(UTC))
            .returning(recharge_orders_table)
        )
        await db.commit()
        row = updated.mappings().first()
    return ok(recharge_order_out(row))


@router.api_route("/recharge/zpay/notify", methods=["GET", "POST"], response_class=PlainTextResponse)
async def zpay_notify(request: Request, db: AsyncSession = Depends(get_db)) -> PlainTextResponse:
    raw = request.url.query if request.method == "GET" else (await request.body()).decode("utf-8")
    try:
        params = dict(urllib.parse.parse_qsl(raw, keep_blank_values=True))
        order_no = params.get("out_trade_no", "")
        order_site_id = await db.scalar(select(recharge_orders_table.c.site_id).where(recharge_orders_table.c.order_no == order_no))
        client, _ = await zpay_client_from_config(db, int(order_site_id or 1))
        notification = client.parse_notification(raw)
        if notification.trade_status == "TRADE_SUCCESS":
            await complete_recharge_order(
                db,
                order_no=notification.out_trade_no,
                payment_trade_no=notification.trade_no,
                paid_amount_yuan=notification.money,
            )
    except (BusinessError, ZPayError):
        return PlainTextResponse("fail", status_code=400)
    return PlainTextResponse("success")


@router.get("/recharge/zpay/return")
async def zpay_return() -> RedirectResponse:
    return RedirectResponse(settings.zpay_return_url or "/billing/recharge")
