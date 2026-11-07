"""Bounded operational analytics from platform records, never upstream API balances."""
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import and_, case, func, select

SHANGHAI = ZoneInfo("Asia/Shanghai")


def analytics_window(days: int, now: datetime | None = None, *, day_offset: int = 0):
    end = now or datetime.now(UTC)
    if day_offset:
        end = datetime.combine(end.astimezone(SHANGHAI).date(), time.min, SHANGHAI).astimezone(UTC)
    first_day = end.astimezone(SHANGHAI).date() - timedelta(days=days - 1 + day_offset)
    return datetime.combine(first_day, time.min, SHANGHAI).astimezone(UTC), end


async def load_analytics(db, admin, days: int, *, now: datetime | None = None, day_offset: int = 0):
    # Reuse the dashboard's established schema and system-admin/site scope.
    from app.api.endpoints.dashboard import (
        users_table as u, image_tasks_table as t, credit_ledger_table as l,
        recharge_orders_table as r, admin_site_filters,
    )
    generated_at = now or datetime.now(UTC)
    start, end = analytics_window(days, generated_at, day_offset=day_offset)
    scope = [u.c.deleted_at.is_(None), *admin_site_filters(admin, u.c.site_id)]
    day = lambda column: func.date(func.timezone("Asia/Shanghai", column))
    window = lambda column: and_(column >= start, column < end)
    async def rows(query):
        return (await db.execute(query)).mappings().all()

    new_rows = await rows(select(day(u.c.created_at).label("day"), func.count().label("new_users"))
                          .where(*scope, window(u.c.created_at)).group_by("day"))
    tasks = t.join(u, and_(t.c.user_id == u.c.id, t.c.site_id == u.c.site_id))
    task_rows = await rows(select(day(t.c.created_at).label("day"), func.count().label("tasks"),
                                 func.count(func.distinct(t.c.user_id)).label("active_users"))
                           .select_from(tasks).where(*scope, window(t.c.created_at)).group_by("day"))
    active_users = await db.scalar(select(func.count(func.distinct(t.c.user_id)))
                                  .select_from(tasks).where(*scope, window(t.c.created_at)))
    paid_at = func.coalesce(r.c.paid_at, r.c.created_at)
    paid_scope = [*scope, r.c.status == "paid", window(paid_at)]
    orders = r.join(u, and_(r.c.user_id == u.c.id, r.c.site_id == u.c.site_id))
    paid_rows = await rows(select(day(paid_at).label("day"), func.sum(r.c.amount_cents).label("revenue_cents"),
                                 func.count().label("paid_orders"))
                           .select_from(orders).where(*paid_scope).group_by("day"))
    paid_users = await db.scalar(select(func.count(func.distinct(r.c.user_id))).select_from(orders).where(*paid_scope))

    # Ledger amounts use platform credits. Upstream direct API usage is not stored here.
    debit = and_(l.c.direction == "debit", l.c.biz_type == "image_task")
    refund = and_(l.c.direction == "credit", l.c.biz_type == "refund", l.c.idempotency_key.like("image-task:refund:%"))
    charged = case((debit, l.c.amount), else_=0)
    refunded = case((refund, l.c.amount), else_=0)
    net = charged - refunded
    ledger_scope = [*scope, window(l.c.created_at), debit | refund]
    ledger = l.join(u, l.c.user_id == u.c.id)
    usage_rows = await rows(select(day(l.c.created_at).label("day"), func.sum(charged).label("charged_credits"),
                                  func.sum(refunded).label("refunded_credits"), func.sum(net).label("net_credits"))
                            .select_from(ledger).where(*ledger_scope).group_by("day"))
    ranking = await rows(select(u.c.id.label("user_id"), u.c.site_id, u.c.username,
                               func.sum(charged).label("charged_credits"), func.sum(refunded).label("refunded_credits"),
                               func.sum(net).label("net_credits"))
                         .select_from(ledger).where(*ledger_scope)
                         .group_by(u.c.id, u.c.site_id, u.c.username).having(func.sum(net) > 0)
                         .order_by(func.sum(net).desc(), u.c.id.asc()).limit(10))
    daily = {}
    for offset in range(days):
        date = (start.astimezone(SHANGHAI).date() + timedelta(days=offset)).isoformat()
        daily[date] = dict(date=date, new_users=0, active_users=0, tasks=0, revenue_cents=0, paid_orders=0,
                           charged_credits=0, refunded_credits=0, net_credits=0)
    for batch in (new_rows, task_rows, paid_rows, usage_rows):
        for row in batch:
            daily[row["day"].isoformat()].update({key: value or 0 for key, value in row.items() if key != "day"})
    totals = {key: sum(row[key] for row in daily.values()) for key in (
        "new_users", "tasks", "revenue_cents", "paid_orders", "charged_credits", "refunded_credits", "net_credits")}
    totals.update(active_users=active_users or 0, paid_users=paid_users or 0)
    return dict(days=days, day_offset=day_offset, generated_at=generated_at.isoformat(), start_at=start.isoformat(), end_at=end.isoformat(), timezone="Asia/Shanghai",
                scope="全部站点" if admin.system_super_admin else "当前站点", totals=totals,
                daily=list(daily.values()), consumption_ranking=[dict(row) for row in ranking])
