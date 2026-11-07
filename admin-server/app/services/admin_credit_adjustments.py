from __future__ import annotations

import asyncio
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import BigInteger, Boolean, Column, DateTime, Integer, MetaData, Numeric, String, Table, Text, func, insert, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException
from app.models.admin_audit_log import AdminAuditLog
from app.models.admin_user import AdminUser
from app.services.admin_user_balances import display_credit_balance
from app.services.sub2_balance import Sub2BalanceError, Sub2BalanceTarget, change_sub2_balance, to_sub2_amount


PENDING = "pending"
REMOTE_APPLIED = "remote_applied"
COMPLETED = "completed"
CREDIT_ACCOUNT_CREATION_LOCK_ID = 2_026_072_102

metadata = MetaData()

users_table = Table(
    "users",
    metadata,
    Column("id", BigInteger),
    Column("site_id", BigInteger),
    Column("username", String),
    Column("deleted_at", DateTime(timezone=True)),
)
user_teams_table = Table(
    "user_teams",
    metadata,
    Column("id", BigInteger),
    Column("owner_user_id", BigInteger),
)
user_agent_accounts_table = Table(
    "user_agent_accounts",
    metadata,
    Column("user_id", BigInteger),
    Column("team_id", BigInteger),
    Column("agent_user_id", BigInteger),
    Column("status", String),
)
agent_configs_table = Table(
    "agent_configs",
    metadata,
    Column("site_id", BigInteger),
    Column("is_enabled", Boolean),
    Column("base_url", String),
    Column("admin_api_key", String),
    Column("credit_to_agent_rate", Numeric(12, 4)),
)
credit_accounts_table = Table(
    "user_credit_accounts",
    metadata,
    Column("id", BigInteger),
    Column("user_id", BigInteger),
    Column("balance", Numeric(20, 2)),
    Column("gift_balance", Numeric(20, 2)),
    Column("total_recharged", Numeric(20, 2)),
    Column("total_consumed", Numeric(20, 2)),
    Column("version", Integer),
)
credit_ledger_table = Table(
    "credit_ledger",
    metadata,
    Column("user_id", BigInteger),
    Column("account_id", BigInteger),
    Column("direction", String),
    Column("amount", Numeric(20, 2)),
    Column("gift_amount", Numeric(20, 2)),
    Column("balance_before", Numeric(20, 2)),
    Column("balance_after", Numeric(20, 2)),
    Column("biz_type", String),
    Column("biz_id", String),
    Column("idempotency_key", String),
    Column("description", Text),
    Column("operator_type", String),
    Column("operator_id", BigInteger),
)
sub2_balance_operations_table = Table(
    "sub2_balance_operations",
    metadata,
    Column("site_id", BigInteger),
    Column("user_id", BigInteger),
    Column("agent_user_id", BigInteger),
    Column("operation", String),
    Column("amount", Numeric(18, 4)),
    Column("biz_type", String),
    Column("biz_id", String),
    Column("idempotency_key", String),
    Column("notes", String),
)
admin_balance_adjustments_table = Table(
    "admin_balance_adjustments",
    metadata,
    Column("id", BigInteger),
    Column("site_id", BigInteger),
    Column("user_id", BigInteger),
    Column("admin_id", BigInteger),
    Column("agent_user_id", BigInteger),
    Column("delta", Integer),
    Column("agent_amount", Numeric(18, 4)),
    Column("credit_to_agent_rate", Numeric(18, 4)),
    Column("remote_balance", Numeric(18, 4)),
    Column("balance_before", Numeric(20, 2)),
    Column("balance_after", Numeric(20, 2)),
    Column("reason", String),
    Column("idempotency_key", String),
    Column("status", String),
    Column("failure_message", String),
    Column("created_at", DateTime(timezone=True)),
    Column("updated_at", DateTime(timezone=True)),
)


@dataclass(frozen=True)
class CreditAdjustmentResult:
    user_id: int
    delta: int
    balance_before: Decimal
    balance_after: Decimal

    def as_dict(self) -> dict:
        return {
            "id": self.user_id,
            "delta": self.delta,
            "amount": abs(self.delta),
            "balance_before": self.balance_before,
            "balance_after": self.balance_after,
        }


def _remote_idempotency_key(client_key: str) -> str:
    return f"image2-admin-adjustment:{client_key}"


def _result_from_row(row) -> CreditAdjustmentResult:
    return CreditAdjustmentResult(
        user_id=int(row.user_id),
        delta=int(row.delta),
        balance_before=Decimal(str(row.balance_before or 0)),
        balance_after=Decimal(str(row.balance_after or 0)),
    )


def _validate_existing_adjustment(row, *, site_id: int, user_id: int, admin_id: int, delta: int, reason: str) -> None:
    expected = (site_id, user_id, admin_id, delta, reason)
    actual = (int(row.site_id), int(row.user_id), int(row.admin_id or 0), int(row.delta), str(row.reason))
    if actual != expected:
        raise AppException(code=40901, message="该请求标识已用于其他额度调整，请刷新后重试", status_code=409)


async def _user_row(db: AsyncSession, *, user_id: int, admin: AdminUser):
    conditions = [users_table.c.id == user_id, users_table.c.deleted_at.is_(None)]
    if not admin.system_super_admin:
        conditions.append(users_table.c.site_id == int(admin.site_id or 1))
    row = (await db.execute(select(users_table.c.id, users_table.c.site_id).where(*conditions))).first()
    if row is None:
        raise AppException(code=40404, message="用户不存在", status_code=404)
    return row


async def _new_adjustment_target(db: AsyncSession, *, site_id: int, user_id: int) -> Sub2BalanceTarget | None:
    config = (
        await db.execute(
            select(
                agent_configs_table.c.is_enabled,
                agent_configs_table.c.base_url,
                agent_configs_table.c.admin_api_key,
                agent_configs_table.c.credit_to_agent_rate,
            ).where(agent_configs_table.c.site_id == site_id)
        )
    ).first()
    if config is None or not bool(config.is_enabled):
        return None
    if not str(config.base_url or "").strip() or not str(config.admin_api_key or "").strip():
        raise AppException(code=50381, message="账户计费服务尚未配置完整", status_code=503)

    account = (
        await db.execute(
            select(
                user_agent_accounts_table.c.team_id,
                user_agent_accounts_table.c.agent_user_id,
                user_agent_accounts_table.c.status,
            ).where(user_agent_accounts_table.c.user_id == user_id)
        )
    ).first()
    if account is None or not account.agent_user_id or account.status != "active":
        raise AppException(code=50382, message="账户尚未初始化，请先让用户登录并完成账户初始化", status_code=503)

    if account.team_id:
        owner = (
            await db.execute(
                select(user_teams_table.c.owner_user_id).where(user_teams_table.c.id == int(account.team_id))
            )
        ).first()
        if owner is None:
            raise AppException(code=50383, message="团队账户关系异常，请先修复团队账户", status_code=503)
        if int(owner.owner_user_id) != user_id:
            raise AppException(
                code=40012,
                message=f"该成员使用团队共享余额，请调整团队所有者（用户 ID {int(owner.owner_user_id)}）",
            )

    rate = Decimal(str(config.credit_to_agent_rate or 0))
    if rate <= 0:
        raise AppException(code=50384, message="积分兑换比例配置错误", status_code=503)
    return Sub2BalanceTarget(
        base_url=str(config.base_url).strip(),
        admin_api_key=str(config.admin_api_key).strip(),
        agent_user_id=int(account.agent_user_id),
        credit_to_agent_rate=rate,
    )


async def _retry_target(db: AsyncSession, row) -> Sub2BalanceTarget:
    config = (
        await db.execute(
            select(
                agent_configs_table.c.is_enabled,
                agent_configs_table.c.base_url,
                agent_configs_table.c.admin_api_key,
            ).where(agent_configs_table.c.site_id == int(row.site_id))
        )
    ).first()
    if config is None or not bool(config.is_enabled) or not str(config.base_url or "").strip() or not str(config.admin_api_key or "").strip():
        raise AppException(code=50381, message="账户计费服务尚未配置完整，无法继续待处理的额度调整", status_code=503)
    return Sub2BalanceTarget(
        base_url=str(config.base_url).strip(),
        admin_api_key=str(config.admin_api_key).strip(),
        agent_user_id=int(row.agent_user_id),
        credit_to_agent_rate=Decimal(str(row.credit_to_agent_rate)),
    )


async def _load_adjustment(db: AsyncSession, idempotency_key: str, *, for_update: bool = False):
    statement = select(admin_balance_adjustments_table).where(
        admin_balance_adjustments_table.c.idempotency_key == idempotency_key
    )
    if for_update:
        statement = statement.with_for_update()
    result = await db.execute(statement)
    return result.first()


async def _create_adjustment(
    db: AsyncSession,
    *,
    site_id: int,
    user_id: int,
    admin_id: int,
    delta: int,
    reason: str,
    idempotency_key: str,
    target: Sub2BalanceTarget | None,
):
    try:
        agent_amount = to_sub2_amount(abs(delta), target.credit_to_agent_rate) if target else Decimal("0")
    except ValueError as error:
        raise AppException(code=40013, message="调整金额低于账户最小精度") from error
    values = {
        "site_id": site_id,
        "user_id": user_id,
        "admin_id": admin_id,
        "agent_user_id": target.agent_user_id if target else None,
        "delta": delta,
        "agent_amount": agent_amount,
        "credit_to_agent_rate": target.credit_to_agent_rate if target else Decimal("1"),
        "reason": reason,
        "idempotency_key": idempotency_key,
        "status": PENDING,
        "updated_at": func.now(),
    }
    try:
        await db.execute(insert(admin_balance_adjustments_table).values(**values))
        await db.commit()
    except IntegrityError:
        await db.rollback()
    row = await _load_adjustment(db, idempotency_key)
    if row is None:
        raise AppException(code=50001, message="额度调整记录创建失败", status_code=500)
    return row


async def _credit_account_for_update(db: AsyncSession, user_id: int):
    account = (
        await db.execute(
            select(
                credit_accounts_table.c.id,
                credit_accounts_table.c.balance,
                credit_accounts_table.c.gift_balance,
                credit_accounts_table.c.total_recharged,
                credit_accounts_table.c.total_consumed,
            )
            .where(credit_accounts_table.c.user_id == user_id)
            .with_for_update()
        )
    ).first()
    if account is not None:
        return account

    await db.execute(select(func.pg_advisory_xact_lock(CREDIT_ACCOUNT_CREATION_LOCK_ID)))
    account = (
        await db.execute(
            select(
                credit_accounts_table.c.id,
                credit_accounts_table.c.balance,
                credit_accounts_table.c.gift_balance,
                credit_accounts_table.c.total_recharged,
                credit_accounts_table.c.total_consumed,
            )
            .where(credit_accounts_table.c.user_id == user_id)
            .with_for_update()
        )
    ).first()
    if account is not None:
        return account

    next_account_id = int(await db.scalar(select(func.coalesce(func.max(credit_accounts_table.c.id), 0) + 1)) or 1)
    await db.execute(
        insert(credit_accounts_table).values(
            id=next_account_id,
            user_id=user_id,
            balance=0,
            total_recharged=0,
            total_consumed=0,
            version=1,
        )
    )
    account = (
        await db.execute(
            select(
                credit_accounts_table.c.id,
                credit_accounts_table.c.balance,
                credit_accounts_table.c.gift_balance,
                credit_accounts_table.c.total_recharged,
                credit_accounts_table.c.total_consumed,
            )
            .where(credit_accounts_table.c.user_id == user_id)
            .with_for_update()
        )
    ).first()
    if account is None:
        raise AppException(code=50002, message="积分账户创建失败", status_code=500)
    return account


async def _finalize_adjustment(db: AsyncSession, *, adjustment_idempotency_key: str, admin: AdminUser) -> CreditAdjustmentResult:
    row = await _load_adjustment(db, adjustment_idempotency_key, for_update=True)
    if row is None:
        raise AppException(code=50001, message="额度调整记录不存在", status_code=500)
    if row.status == COMPLETED:
        return _result_from_row(row)

    delta = int(row.delta)
    account = await _credit_account_for_update(db, int(row.user_id))
    if row.agent_user_id:
        if row.status != REMOTE_APPLIED or row.remote_balance is None:
            raise AppException(code=50385, message="账户余额调整尚未完成，请重试", status_code=503)
        balance_after = display_credit_balance(
            Decimal(str(row.remote_balance)),
            Decimal(str(row.credit_to_agent_rate)),
        )
        balance_before = balance_after - delta
    else:
        balance_before = Decimal(str(account.balance or 0))
        balance_after = balance_before + delta
        if balance_after < 0:
            raise AppException(code=40002, message="人工扣减不能扣成负数")

    gift_before = Decimal(str(getattr(account, "gift_balance", 0) or 0))
    gift_consumed = min(gift_before, max(0, -delta))
    await db.execute(
        update(credit_accounts_table)
        .where(credit_accounts_table.c.id == int(account.id))
        .values(
            balance=balance_after,
            gift_balance=min(max(0, balance_after), gift_before - gift_consumed),
            total_recharged=Decimal(str(account.total_recharged or 0)) + (delta if delta > 0 else 0),
            total_consumed=Decimal(str(account.total_consumed or 0)) + (abs(delta) if delta < 0 else 0),
            version=credit_accounts_table.c.version + 1,
        )
    )
    await db.execute(
        insert(credit_ledger_table).values(
            user_id=int(row.user_id),
            account_id=int(account.id),
            direction="credit" if delta > 0 else "debit",
            amount=abs(delta),
            gift_amount=gift_consumed,
            balance_before=balance_before,
            balance_after=balance_after,
            biz_type="admin_adjustment",
            biz_id=f"admin-adjustment:{int(row.id)}",
            idempotency_key=adjustment_idempotency_key,
            description=str(row.reason),
            operator_type="admin",
            operator_id=int(row.admin_id),
        )
    )
    if row.agent_user_id:
        await db.execute(
            insert(sub2_balance_operations_table).values(
                site_id=int(row.site_id),
                user_id=int(row.user_id),
                agent_user_id=int(row.agent_user_id),
                operation="add" if delta > 0 else "subtract",
                amount=Decimal(str(row.agent_amount)),
                biz_type="admin_adjustment",
                biz_id=f"admin-adjustment:{int(row.id)}",
                idempotency_key=adjustment_idempotency_key,
                notes=f"image2 后台额度调整：{str(row.reason)}"[:255],
            )
        )
    await db.execute(
        update(admin_balance_adjustments_table)
        .where(admin_balance_adjustments_table.c.id == int(row.id))
        .values(
            status=COMPLETED,
            balance_before=balance_before,
            balance_after=balance_after,
            failure_message=None,
            updated_at=func.now(),
        )
    )
    db.add(
        AdminAuditLog(
            admin_id=admin.id,
            admin_username=admin.username,
            action="credit_adjustment",
            resource_type="users",
            resource_id=str(row.user_id),
            reason=str(row.reason),
        )
    )
    await db.commit()
    return CreditAdjustmentResult(
        user_id=int(row.user_id),
        delta=delta,
        balance_before=balance_before,
        balance_after=balance_after,
    )


async def adjust_user_credit(
    db: AsyncSession,
    *,
    user_id: int,
    delta: int,
    reason: str,
    client_idempotency_key: str,
    admin: AdminUser,
) -> CreditAdjustmentResult:
    user = await _user_row(db, user_id=user_id, admin=admin)
    site_id = int(user.site_id or 1)
    idempotency_key = _remote_idempotency_key(client_idempotency_key)
    row = await _load_adjustment(db, idempotency_key)
    if row is None:
        target = await _new_adjustment_target(db, site_id=site_id, user_id=user_id)
        row = await _create_adjustment(
            db,
            site_id=site_id,
            user_id=user_id,
            admin_id=int(admin.id),
            delta=delta,
            reason=reason,
            idempotency_key=idempotency_key,
            target=target,
        )
    _validate_existing_adjustment(
        row,
        site_id=site_id,
        user_id=user_id,
        admin_id=int(admin.id),
        delta=delta,
        reason=reason,
    )
    if row.status == COMPLETED:
        return _result_from_row(row)
    if not row.agent_user_id:
        return await _finalize_adjustment(db, adjustment_idempotency_key=idempotency_key, admin=admin)
    if row.status == PENDING:
        target = await _retry_target(db, row)
        operation = "add" if delta > 0 else "subtract"
        notes = f"image2 后台额度调整：{reason}"
        await db.commit()
        try:
            remote_balance = await asyncio.to_thread(
                change_sub2_balance,
                target,
                amount=Decimal(str(row.agent_amount)),
                operation=operation,
                idempotency_key=idempotency_key,
                notes=notes,
            )
        except Sub2BalanceError as error:
            await db.execute(
                update(admin_balance_adjustments_table)
                .where(admin_balance_adjustments_table.c.id == int(row.id))
                .values(failure_message=str(error)[:500], updated_at=func.now())
            )
            await db.commit()
            raise AppException(
                code=50281,
                message=f"账户余额调整失败：{error}",
                status_code=error.status_code,
            ) from error
        await db.execute(
            update(admin_balance_adjustments_table)
            .where(admin_balance_adjustments_table.c.id == int(row.id))
            .values(
                status=REMOTE_APPLIED,
                remote_balance=remote_balance,
                failure_message=None,
                updated_at=func.now(),
            )
        )
        await db.commit()
    return await _finalize_adjustment(db, adjustment_idempotency_key=idempotency_key, admin=admin)
