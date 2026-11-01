from datetime import UTC, datetime, time
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import BigInteger, Boolean, Column, DateTime, Integer, MetaData, Numeric, String, Table, and_, case, desc, func, select
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_admin, get_db
from app.models.admin_user import AdminUser
from app.schemas.response import ApiResponse

router = APIRouter()

shared_metadata = MetaData()
users_table = Table(
    "users",
    shared_metadata,
    Column("id", BigInteger),
    Column("site_id", BigInteger),
    Column("username", String),
    Column("customer_owner_admin_id", BigInteger),
    Column("is_active", Boolean),
    Column("created_at", DateTime(timezone=True)),
    Column("deleted_at", DateTime(timezone=True)),
)
image_models_table = Table(
    "image_models",
    shared_metadata,
    Column("id", BigInteger),
    Column("name", String),
)
image_tasks_table = Table(
    "image_tasks",
    shared_metadata,
    Column("id", BigInteger),
    Column("task_no", String),
    Column("site_id", BigInteger),
    Column("user_id", BigInteger),
    Column("model_id", BigInteger),
    Column("status", String),
    Column("failure_message", String),
    Column("created_at", DateTime(timezone=True)),
    Column("finished_at", DateTime(timezone=True)),
)
credit_ledger_table = Table(
    "credit_ledger",
    shared_metadata,
    Column("id", BigInteger),
    Column("user_id", BigInteger),
    Column("direction", String),
    Column("amount", Numeric(20, 2)),
    Column("biz_type", String),
    Column("biz_id", String),
    Column("idempotency_key", String),
    Column("description", String),
    Column("is_flagged", Boolean),
    Column("flag_reason", String),
    Column("created_at", DateTime(timezone=True)),
)
recharge_orders_table = Table(
    "recharge_orders",
    shared_metadata,
    Column("id", BigInteger),
    Column("order_no", String),
    Column("site_id", BigInteger),
    Column("user_id", BigInteger),
    Column("amount_cents", Integer),
    Column("credit_amount", Integer),
    Column("bonus_credit_amount", Integer),
    Column("status", String),
    Column("created_at", DateTime(timezone=True)),
    Column("paid_at", DateTime(timezone=True)),
)


def start_of_today_utc() -> datetime:
    shanghai_today = datetime.now(ZoneInfo("Asia/Shanghai")).date()
    return datetime.combine(shanghai_today, time.min, tzinfo=ZoneInfo("Asia/Shanghai")).astimezone(UTC)


def percent(numerator: int, denominator: int) -> str:
    if denominator <= 0:
        return "0%"
    return f"{round((numerator / denominator) * 100)}%"


def iso(value) -> str:
    return value.isoformat() if value else ""


def admin_site_filters(current_admin: AdminUser, site_column) -> list:
    if current_admin.system_super_admin:
        return []
    return [site_column == int(current_admin.site_id or 1)]


@router.get("/metrics", response_model=ApiResponse[dict])
async def metrics(
    current_admin: AdminUser = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[dict]:
    today = start_of_today_utc()
    user_site_filters = admin_site_filters(current_admin, users_table.c.site_id)
    task_site_filters = admin_site_filters(current_admin, image_tasks_table.c.site_id)
    recharge_site_filters = admin_site_filters(current_admin, recharge_orders_table.c.site_id)
    customer_site_filters = admin_site_filters(current_admin, users_table.c.site_id)

    try:
        new_users = int(
            await db.scalar(
                select(func.count())
                .select_from(users_table)
                .where(users_table.c.created_at >= today, users_table.c.deleted_at.is_(None), *user_site_filters)
            )
            or 0
        )
        total_customers = int(
            await db.scalar(
                select(func.count())
                .select_from(users_table)
                .where(users_table.c.deleted_at.is_(None), *customer_site_filters)
            )
            or 0
        )
        unassigned_customers = int(
            await db.scalar(
                select(func.count())
                .select_from(users_table)
                .where(
                    users_table.c.deleted_at.is_(None),
                    users_table.c.customer_owner_admin_id.is_(None),
                    *customer_site_filters,
                )
            )
            or 0
        )
        active_customer_ids = (
            select(image_tasks_table.c.user_id.label("user_id"))
            .select_from(image_tasks_table)
            .where(image_tasks_table.c.created_at >= today, image_tasks_table.c.user_id.is_not(None), *task_site_filters)
            .union(
                select(recharge_orders_table.c.user_id.label("user_id"))
                .select_from(recharge_orders_table)
                .where(
                    recharge_orders_table.c.status == "paid",
                    func.coalesce(recharge_orders_table.c.paid_at, recharge_orders_table.c.created_at) >= today,
                    recharge_orders_table.c.user_id.is_not(None),
                    *recharge_site_filters,
                )
            )
            .subquery()
        )
        active_customers = int(
            await db.scalar(
                select(func.count())
                .select_from(active_customer_ids.join(users_table, active_customer_ids.c.user_id == users_table.c.id))
                .where(users_table.c.deleted_at.is_(None), *customer_site_filters)
            )
            or 0
        )
        paid_customer_count = int(
            await db.scalar(
                select(func.count(func.distinct(recharge_orders_table.c.user_id))).where(
                    recharge_orders_table.c.status == "paid",
                    func.coalesce(recharge_orders_table.c.paid_at, recharge_orders_table.c.created_at) >= today,
                    *recharge_site_filters,
                )
            )
            or 0
        )
        paid_order_count = int(
            await db.scalar(
                select(func.count()).select_from(recharge_orders_table).where(
                    recharge_orders_table.c.status == "paid",
                    func.coalesce(recharge_orders_table.c.paid_at, recharge_orders_table.c.created_at) >= today,
                    *recharge_site_filters,
                )
            )
            or 0
        )
        consumed_credits = int(
            await db.scalar(
                select(func.coalesce(func.sum(credit_ledger_table.c.amount), 0))
                .select_from(credit_ledger_table.outerjoin(users_table, credit_ledger_table.c.user_id == users_table.c.id))
                .where(
                    credit_ledger_table.c.created_at >= today,
                    credit_ledger_table.c.direction == "debit",
                    credit_ledger_table.c.biz_type == "image_task",
                    *user_site_filters,
                )
            )
            or 0
        )
        recharge_credits = int(
            await db.scalar(
                select(func.coalesce(func.sum(credit_ledger_table.c.amount), 0))
                .select_from(credit_ledger_table.outerjoin(users_table, credit_ledger_table.c.user_id == users_table.c.id))
                .where(
                    credit_ledger_table.c.created_at >= today,
                    credit_ledger_table.c.direction == "credit",
                    credit_ledger_table.c.biz_type == "recharge",
                    *user_site_filters,
                )
            )
            or 0
        )
        recharge_amount_cents = int(
            await db.scalar(
                select(func.coalesce(func.sum(recharge_orders_table.c.amount_cents), 0)).where(
                    recharge_orders_table.c.status == "paid",
                    func.coalesce(recharge_orders_table.c.paid_at, recharge_orders_table.c.created_at) >= today,
                    *recharge_site_filters,
                )
            )
            or 0
        )

        task_counts = (
            await db.execute(
                select(
                    func.count().label("total"),
                    func.coalesce(func.sum(case((image_tasks_table.c.status == "succeeded", 1), else_=0)), 0).label("succeeded"),
                    func.coalesce(
                        func.sum(case((image_tasks_table.c.status.in_(["failed", "refunded"]), 1), else_=0)),
                        0,
                    ).label("failed"),
                ).where(image_tasks_table.c.created_at >= today, *task_site_filters)
            )
        ).one()
        total_tasks = int(task_counts.total or 0)
        succeeded_tasks = int(task_counts.succeeded or 0)
        failed_tasks = int(task_counts.failed or 0)

        owner_rows = (
            await db.execute(
                select(
                    AdminUser.username.label("owner_name"),
                    users_table.c.customer_owner_admin_id.label("owner_id"),
                    func.count(func.distinct(users_table.c.id)).label("customer_count"),
                    func.count(func.distinct(recharge_orders_table.c.user_id)).label("paid_customer_count"),
                    func.count(recharge_orders_table.c.id).label("paid_order_count"),
                    func.coalesce(func.sum(recharge_orders_table.c.amount_cents), 0).label("revenue_cents"),
                )
                .select_from(
                    users_table.outerjoin(AdminUser, users_table.c.customer_owner_admin_id == AdminUser.id).outerjoin(
                        recharge_orders_table,
                        and_(
                            recharge_orders_table.c.user_id == users_table.c.id,
                            recharge_orders_table.c.status == "paid",
                            func.coalesce(recharge_orders_table.c.paid_at, recharge_orders_table.c.created_at) >= today,
                            *recharge_site_filters,
                        ),
                    )
                )
                .where(users_table.c.deleted_at.is_(None), *customer_site_filters)
                .group_by(AdminUser.id, AdminUser.username, users_table.c.customer_owner_admin_id)
                .order_by(desc(func.coalesce(func.sum(recharge_orders_table.c.amount_cents), 0)), desc(func.count(func.distinct(users_table.c.id))), AdminUser.username.asc())
                .limit(20)
            )
        ).mappings()
        customer_owner_stats = [
            {
                "owner_id": row.owner_id,
                "owner_name": row.owner_name or "未分配",
                "customer_count": int(row.customer_count or 0),
                "paid_customer_count": int(row.paid_customer_count or 0),
                "paid_order_count": int(row.paid_order_count or 0),
                "revenue_cents": int(row.revenue_cents or 0),
            }
            for row in owner_rows
        ]

        failed_rows = (
            await db.execute(
                select(
                    image_tasks_table.c.task_no,
                    image_tasks_table.c.failure_message,
                    image_tasks_table.c.created_at,
                    image_tasks_table.c.finished_at,
                    image_models_table.c.name.label("model_name"),
                    users_table.c.username,
                )
                .select_from(
                    image_tasks_table.outerjoin(users_table, image_tasks_table.c.user_id == users_table.c.id).outerjoin(
                        image_models_table,
                        image_tasks_table.c.model_id == image_models_table.c.id,
                    )
                )
                .where(image_tasks_table.c.status.in_(["failed", "refunded"]), *task_site_filters)
                .order_by(desc(image_tasks_table.c.created_at))
                .limit(8)
            )
        ).mappings()
        recent_failed_model_calls = [
            {
                "task_no": row.task_no,
                "model_name": row.model_name or "-",
                "username": row.username or "-",
                "latency_ms": int(((row.finished_at - row.created_at).total_seconds() * 1000) if row.finished_at and row.created_at else 0),
                "error_message": row.failure_message or "未记录失败原因",
                "created_at": iso(row.created_at),
            }
            for row in failed_rows
        ]

        alert_rows = (
            await db.execute(
                select(
                    credit_ledger_table.c.id,
                    credit_ledger_table.c.amount,
                    credit_ledger_table.c.biz_type,
                    credit_ledger_table.c.biz_id,
                    credit_ledger_table.c.description,
                    credit_ledger_table.c.flag_reason,
                    credit_ledger_table.c.created_at,
                    users_table.c.username,
                )
                .select_from(credit_ledger_table.outerjoin(users_table, credit_ledger_table.c.user_id == users_table.c.id))
                .where(credit_ledger_table.c.is_flagged.is_(True), *user_site_filters)
                .order_by(desc(credit_ledger_table.c.created_at))
                .limit(8)
            )
        ).mappings()
        credit_alerts = [
            {
                "id": row.id,
                "title": f"{row.username or '未知用户'} 积分异常",
                "detail": row.flag_reason or row.description or f"{row.biz_type or '-'} #{row.biz_id or '-'} 变动 {row.amount}",
                "severity": "danger",
                "created_at": iso(row.created_at),
            }
            for row in alert_rows
        ]

        recharge_rows = (
            await db.execute(
                select(
                    recharge_orders_table.c.order_no,
                    recharge_orders_table.c.amount_cents,
                    (
                        recharge_orders_table.c.credit_amount
                        + func.coalesce(recharge_orders_table.c.bonus_credit_amount, 0)
                    ).label("credit_amount"),
                    recharge_orders_table.c.status,
                    recharge_orders_table.c.created_at,
                    users_table.c.username,
                )
                .select_from(recharge_orders_table.outerjoin(users_table, recharge_orders_table.c.user_id == users_table.c.id))
                .where(*recharge_site_filters)
                .order_by(desc(recharge_orders_table.c.created_at), desc(recharge_orders_table.c.id))
                .limit(8)
            )
        ).mappings()
        recent_recharge_orders = [
            {
                "order_no": row.order_no,
                "username": row.username or "-",
                "amount_cents": int(row.amount_cents or 0),
                "credit_amount": int(row.credit_amount or 0),
                "status": row.status or "pending",
                "created_at": iso(row.created_at),
            }
            for row in recharge_rows
        ]

        return ApiResponse.ok(
            {
                "metrics": [
                    {"key": "new_users", "label": "今日新增用户", "value": str(new_users), "trend": str(new_users), "tone": "neutral"},
                    {"key": "total_customers", "label": "客户总数", "value": str(total_customers), "trend": f"未分配 {unassigned_customers}", "tone": "neutral"},
                    {"key": "active_customers", "label": "今日活跃客户", "value": str(active_customers), "trend": "今日有任务或充值", "tone": "neutral"},
                    {"key": "paid_customers", "label": "今日付费客户", "value": str(paid_customer_count), "trend": f"{paid_order_count} 笔已支付", "tone": "good"},
                    {"key": "recharge_amount", "label": "今日实收金额", "value": f"¥{recharge_amount_cents / 100:.2f}", "trend": f"{paid_order_count} 笔已支付", "tone": "good"},
                    {"key": "paid_orders", "label": "今日支付订单", "value": str(paid_order_count), "trend": "按支付时间统计", "tone": "good"},
                    {"key": "recharge", "label": "今日充值积分", "value": str(recharge_credits), "trend": str(recharge_credits), "tone": "good"},
                    {"key": "credits", "label": "今日消耗积分", "value": str(consumed_credits), "trend": str(consumed_credits), "tone": "neutral"},
                    {"key": "success_rate", "label": "任务成功率", "value": percent(succeeded_tasks, total_tasks), "trend": f"{succeeded_tasks}/{total_tasks}", "tone": "good" if total_tasks and failed_tasks == 0 else "neutral"},
                    {"key": "failed_tasks", "label": "失败任务数", "value": str(failed_tasks), "trend": str(failed_tasks), "tone": "danger" if failed_tasks else "neutral"},
                ],
                "recent_recharge_orders": recent_recharge_orders,
                "recent_failed_model_calls": recent_failed_model_calls,
                "credit_alerts": credit_alerts,
                "customer_owner_stats": customer_owner_stats,
            }
        )
    except (OperationalError, ProgrammingError):
        await db.rollback()
        return ApiResponse.ok(
            {
                "metrics": [
                    {"key": "new_users", "label": "今日新增用户", "value": "0", "trend": "0", "tone": "neutral"},
                    {"key": "total_customers", "label": "客户总数", "value": "0", "trend": "未分配 0", "tone": "neutral"},
                    {"key": "active_customers", "label": "今日活跃客户", "value": "0", "trend": "今日有任务或充值", "tone": "neutral"},
                    {"key": "paid_customers", "label": "今日付费客户", "value": "0", "trend": "0 笔已支付", "tone": "neutral"},
                    {"key": "recharge_amount", "label": "今日实收金额", "value": "¥0.00", "trend": "0 笔已支付", "tone": "neutral"},
                    {"key": "paid_orders", "label": "今日支付订单", "value": "0", "trend": "按支付时间统计", "tone": "neutral"},
                    {"key": "recharge", "label": "今日充值积分", "value": "0", "trend": "0", "tone": "neutral"},
                    {"key": "credits", "label": "今日消耗积分", "value": "0", "trend": "0", "tone": "neutral"},
                    {"key": "success_rate", "label": "任务成功率", "value": "0%", "trend": "0/0", "tone": "neutral"},
                    {"key": "failed_tasks", "label": "失败任务数", "value": "0", "trend": "0", "tone": "neutral"},
                ],
                "recent_recharge_orders": [],
                "recent_failed_model_calls": [],
                "credit_alerts": [],
                "customer_owner_stats": [],
            }
        )


@router.get("/analytics", response_model=ApiResponse[dict])
async def analytics(
    days: int = 7,
    day_offset: int = 0,
    current_admin: AdminUser = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[dict]:
    from app.services.dashboard_analytics import load_analytics
    if days not in (1, 7, 15, 30) or day_offset not in (0, 1) or (day_offset == 1 and days != 1):
        raise HTTPException(status_code=422, detail="统计周期仅支持当天、昨天、7、15、30 天")
    return ApiResponse.ok(await load_analytics(db, current_admin, days, day_offset=day_offset))
