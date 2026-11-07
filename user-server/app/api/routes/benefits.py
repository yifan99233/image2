from __future__ import annotations

import asyncio
import urllib.parse
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi import APIRouter, Depends, Request
from fastapi.responses import PlainTextResponse, RedirectResponse
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_current_user
from app.core.config import settings
from app.core.exceptions import BusinessError
from app.core.responses import StandardResponse, ok
from app.db.session import get_db
from app.models.benefit_package import BenefitGrant, BenefitOrder, BenefitPackage
from app.models.user import User
from app.services.benefit_packages import apply_due_benefit_grants, materialize_paid_order_grants
from app.services.zpay import ZPayError

router = APIRouter(prefix="/benefits", tags=["benefits"])


def benefit_order_no() -> str:
    return f"BP{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}{uuid4().hex[:8].upper()}"


def benefit_order_out(order: BenefitOrder) -> dict:
    return {
        "id": order.id,
        "order_no": order.order_no,
        "package_id": order.package_id,
        "amount_cents": order.amount_cents,
        "currency": order.currency,
        "status": order.status,
        "payment_provider": order.payment_provider,
        "payment_type": order.payment_type,
        "payment_trade_no": order.payment_trade_no,
        "pay_url": order.pay_url,
        "qr_code": order.qr_code,
        "qr_code_url": order.qr_code,
        "failure_message": order.failure_message,
        "starts_at": order.starts_at.isoformat() if order.starts_at else None,
        "expires_at": order.expires_at.isoformat() if order.expires_at else None,
        "paid_at": order.paid_at.isoformat() if order.paid_at else None,
        "created_at": order.created_at.isoformat() if order.created_at else None,
    }


def package_out(package: BenefitPackage) -> dict:
    return {
        "id": package.id,
        "code": package.code,
        "name": package.name,
        "description": package.description,
        "amount_cents": package.amount_cents,
        "currency": package.currency,
        "purchase_mode": package.purchase_mode,
        "billing_interval": package.billing_interval,
        "validity_mode": package.validity_mode,
        "validity_value": package.validity_value,
        "activation_policy": package.activation_policy,
        "timezone": package.timezone,
        "stacking_policy": package.stacking_policy,
        "badge": package.badge,
        "is_recommended": package.is_recommended,
        "version": package.version,
        "items": [
            {
                "id": item.id,
                "resource_type": item.resource_type,
                "amount": item.amount,
                "grant_mode": item.grant_mode,
                "grant_count": item.grant_count,
                "scope": item.scope,
                "aggregation_mode": item.aggregation_mode,
                "expiry_policy": item.expiry_policy,
            }
            for item in package.items
        ],
    }


async def active_package_orders(
    db: AsyncSession,
    *,
    package_id: int,
    payer_user_id: int,
    team_id: int | None,
    now: datetime,
    exclude_order_id: int | None = None,
) -> list[BenefitOrder]:
    conditions = [
        BenefitOrder.package_id == package_id,
        BenefitOrder.payer_user_id == payer_user_id,
        BenefitOrder.status == "paid",
        or_(BenefitOrder.expires_at.is_(None), BenefitOrder.expires_at > now),
    ]
    conditions.append(BenefitOrder.team_id.is_(None) if team_id is None else BenefitOrder.team_id == team_id)
    if exclude_order_id is not None:
        conditions.append(BenefitOrder.id != exclude_order_id)
    return (
        await db.execute(
            select(BenefitOrder)
            .where(*conditions)
            .order_by(BenefitOrder.expires_at.desc().nullslast(), BenefitOrder.id.desc())
        )
    ).scalars().all()


@router.get("/packages", response_model=StandardResponse[list])
async def active_benefit_packages(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StandardResponse[list]:
    result = await db.execute(
        select(BenefitPackage)
        .options(selectinload(BenefitPackage.items))
        .where(BenefitPackage.site_id == current_user.site_id, BenefitPackage.is_active.is_(True))
        .order_by(BenefitPackage.sort_order.asc(), BenefitPackage.id.desc())
    )
    return ok([package_out(package) for package in result.scalars().unique()])


@router.post("/orders", response_model=StandardResponse[dict])
async def create_benefit_order(
    payload: dict,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StandardResponse[dict]:
    package_id = int(payload.get("package_id") or 0)
    package = await db.scalar(
        select(BenefitPackage)
        .options(selectinload(BenefitPackage.items))
        .where(
            BenefitPackage.id == package_id,
            BenefitPackage.site_id == current_user.site_id,
            BenefitPackage.is_active.is_(True),
        )
    )
    if package is None:
        raise BusinessError("权益套餐不存在或已下架", code=40481, status_code=404)
    if package.purchase_mode == "subscription":
        raise BusinessError("自动订阅支付暂未接入当前支付渠道，请先配置一次性套餐", code=50181, status_code=501)

    team_id = None
    if any(item.scope == "team" for item in package.items):
        from app.services.team_sharing import get_agent_billing_team

        team = await get_agent_billing_team(db, current_user)
        if team is None or str(team.current_role) != "owner":
            raise BusinessError("团队权益只能由团队所有者购买", code=40382, status_code=403)
        team_id = int(team.id)
    now = datetime.now(UTC)
    if package.stacking_policy == "reject":
        active_orders = await active_package_orders(
            db,
            package_id=package.id,
            payer_user_id=current_user.id,
            team_id=team_id,
            now=now,
        )
        if active_orders:
            raise BusinessError("当前套餐仍在有效期内，不能重复购买", code=40983, status_code=409)

    from app.api.routes.recharge import amount_cents_to_yuan, zpay_client_from_config

    client, zpay_values = await zpay_client_from_config(db, current_user.site_id)
    order = BenefitOrder(
        site_id=current_user.site_id,
        order_no=benefit_order_no(),
        package_id=package.id,
        package_version=package.version,
        payer_user_id=current_user.id,
        team_id=team_id,
        amount_cents=package.amount_cents,
        currency=package.currency,
        status="pending",
        payment_provider="zpay",
        payment_type=zpay_values["payment_type"],
        expires_at=now + timedelta(minutes=max(1, int(zpay_values["order_expire_minutes"]))),
        created_at=now,
        updated_at=now,
    )
    db.add(order)
    await db.flush()
    await db.commit()

    try:
        payment = await asyncio.to_thread(
            client.create_payment,
            order_no=order.order_no,
            amount_yuan=amount_cents_to_yuan(package.amount_cents),
            subject=f"权益套餐-{package.name}",
            client_ip=request.client.host if request.client else "",
        )
    except ZPayError as error:
        await db.execute(
            BenefitOrder.__table__.update()
            .where(BenefitOrder.id == order.id)
            .values(status="failed", failure_message=str(error), updated_at=datetime.now(UTC))
        )
        await db.commit()
        raise BusinessError(f"创建支付订单失败：{error}", code=50221, status_code=502) from error

    await db.execute(
        BenefitOrder.__table__.update()
        .where(BenefitOrder.id == order.id)
        .values(pay_url=payment.pay_url, qr_code=payment.qr_code, updated_at=datetime.now(UTC))
    )
    await db.commit()
    refreshed = await db.scalar(select(BenefitOrder).where(BenefitOrder.id == order.id))
    return ok(benefit_order_out(refreshed))


@router.get("/orders/{order_id}", response_model=StandardResponse[dict])
async def benefit_order(
    order_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StandardResponse[dict]:
    order = await db.scalar(select(BenefitOrder).where(BenefitOrder.id == order_id, BenefitOrder.payer_user_id == current_user.id, BenefitOrder.site_id == current_user.site_id))
    if order is None:
        raise BusinessError("权益订单不存在", code=40482, status_code=404)
    if order.status == "pending" and order.expires_at and order.expires_at <= datetime.now(UTC):
        order.status = "expired"
        order.updated_at = datetime.now(UTC)
        await db.commit()
    return ok(benefit_order_out(order))


async def complete_benefit_order(
    db: AsyncSession,
    *,
    order_no: str,
    payment_trade_no: str,
    paid_amount_yuan,
) -> bool:
    order = await db.scalar(
        select(BenefitOrder)
        .options(selectinload(BenefitOrder.package).selectinload(BenefitPackage.items))
        .where(BenefitOrder.order_no == order_no)
        .with_for_update()
    )
    if order is None:
        raise BusinessError("权益订单不存在", code=40483, status_code=404)
    if order.status == "paid":
        return False
    if order.status not in {"pending", "failed"}:
        raise BusinessError("权益订单状态不可到账", code=42081)
    from decimal import Decimal

    expected = Decimal(order.amount_cents) / Decimal(100)
    if paid_amount_yuan != expected:
        order.status = "failed"
        order.failure_message = f"支付金额不匹配：应付 {expected}，实付 {paid_amount_yuan}"
        order.updated_at = datetime.now(UTC)
        await db.commit()
        raise BusinessError("支付金额不匹配", code=42082)
    now = datetime.now(UTC)
    order.status = "paid"
    order.payment_trade_no = payment_trade_no
    order.paid_at = now
    order.updated_at = now
    starts_at = now
    if order.package.stacking_policy == "extend":
        active_orders = await active_package_orders(
            db,
            package_id=order.package_id,
            payer_user_id=order.payer_user_id,
            team_id=order.team_id,
            now=now,
            exclude_order_id=order.id,
        )
        latest_expiry = next((item.expires_at for item in active_orders if item.expires_at is not None), None)
        if latest_expiry is not None and latest_expiry > now:
            starts_at = latest_expiry
    await materialize_paid_order_grants(db, order=order, package=order.package, starts_at=starts_at)
    await apply_due_benefit_grants(db, order=order, now=now)
    await db.commit()
    return True


@router.api_route("/zpay/notify", methods=["GET", "POST"], response_class=PlainTextResponse)
async def benefit_zpay_notify(request: Request, db: AsyncSession = Depends(get_db)) -> PlainTextResponse:
    raw = request.url.query if request.method == "GET" else (await request.body()).decode("utf-8")
    try:
        params = dict(urllib.parse.parse_qsl(raw, keep_blank_values=True))
        order_no = params.get("out_trade_no", "")
        site_id = await db.scalar(select(BenefitOrder.site_id).where(BenefitOrder.order_no == order_no))
        if not site_id:
            return PlainTextResponse("fail", status_code=404)
        from app.api.routes.recharge import zpay_client_from_config

        client, _ = await zpay_client_from_config(db, int(site_id))
        notification = client.parse_notification(raw)
        if notification.trade_status == "TRADE_SUCCESS":
            await complete_benefit_order(db, order_no=notification.out_trade_no, payment_trade_no=notification.trade_no, paid_amount_yuan=notification.money)
    except (BusinessError, ZPayError):
        return PlainTextResponse("fail", status_code=400)
    return PlainTextResponse("success")


@router.get("/zpay/return")
async def benefit_zpay_return() -> RedirectResponse:
    return RedirectResponse(settings.zpay_return_url or "/billing/recharge")


@router.get("/grants", response_model=StandardResponse[list])
async def current_benefit_grants(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StandardResponse[list]:
    now = datetime.now(UTC)
    from app.services.team_sharing import get_agent_billing_team

    active_team = await get_agent_billing_team(db, current_user)
    scope_condition = BenefitGrant.owner_user_id == current_user.id
    if active_team is not None:
        scope_condition = or_(scope_condition, BenefitGrant.team_id == int(active_team.id))
    result = await db.execute(
        select(BenefitGrant)
        .where(
            BenefitGrant.site_id == current_user.site_id,
            scope_condition,
            BenefitGrant.status.in_(["scheduled", "active"]),
            (BenefitGrant.expires_at.is_(None)) | (BenefitGrant.expires_at > now),
        )
        .order_by(BenefitGrant.expires_at.asc().nullslast(), BenefitGrant.grant_at.asc(), BenefitGrant.id.asc())
    )
    return ok(
        [
            {
                "id": grant.id,
                "resource_type": grant.resource_type,
                "amount": grant.amount,
                "remaining_amount": grant.remaining_amount,
                "grant_at": grant.grant_at,
                "starts_at": grant.starts_at,
                "expires_at": grant.expires_at,
                "status": grant.status,
            }
            for grant in result.scalars()
        ]
    )
