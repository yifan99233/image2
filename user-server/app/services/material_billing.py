from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BusinessError
from app.models.credit import CreditLedger, UserCreditAccount
from app.services.sub2_image_billing import (
    Sub2BalanceReceipt,
    debit_image_task_balance,
    refund_image_task_balance,
)


@dataclass(frozen=True)
class MaterialCdnChargeReceipt:
    charge_id: str
    credit_amount: int
    sub2_receipt: Sub2BalanceReceipt | None


async def _get_or_create_credit_account_for_update(db: AsyncSession, user_id: int) -> UserCreditAccount:
    account = await db.scalar(select(UserCreditAccount).where(UserCreditAccount.user_id == user_id).with_for_update())
    if account is not None:
        return account
    account = UserCreditAccount(user_id=user_id)
    db.add(account)
    await db.flush()
    return account


def _add_credit_ledger(
    *,
    db: AsyncSession,
    account: UserCreditAccount,
    user_id: int,
    direction: str,
    amount: int,
    balance_before: int,
    balance_after: int,
    biz_type: str,
    biz_id: str,
    idempotency_key: str,
    description: str,
    gift_amount: int = 0,
) -> None:
    db.add(
        CreditLedger(
            user_id=user_id,
            account_id=account.id,
            direction=direction,
            gift_amount=gift_amount,
            amount=amount,
            balance_before=balance_before,
            balance_after=balance_after,
            biz_type=biz_type,
            biz_id=biz_id,
            idempotency_key=idempotency_key,
            description=description,
            operator_type="user",
            operator_id=user_id,
            created_at=datetime.now(UTC),
        )
    )


def _sub2_charge_task_no(charge_id: str) -> str:
    return f"material-cdn-{charge_id}"


async def debit_material_cdn_upload(
    db: AsyncSession,
    *,
    user_id: int,
    credit_amount: int,
) -> MaterialCdnChargeReceipt:
    if credit_amount <= 0:
        return MaterialCdnChargeReceipt(charge_id=uuid4().hex, credit_amount=0, sub2_receipt=None)

    charge_id = uuid4().hex
    task_no = _sub2_charge_task_no(charge_id)
    sub2_receipt = await debit_image_task_balance(
        db,
        user_id=user_id,
        task_no=task_no,
        credit_amount=credit_amount,
    )
    try:
        account = await _get_or_create_credit_account_for_update(db, user_id)
        if sub2_receipt is None and account.balance < credit_amount:
            raise BusinessError("积分余额不足，无法使用 CDN 上传", code=40030)
        balance_before = account.balance
        balance_after = balance_before - credit_amount
        account.balance = balance_after
        gift_used = min(account.gift_balance, credit_amount)
        account.gift_balance -= gift_used
        account.total_consumed += credit_amount
        account.version += 1
        _add_credit_ledger(
            db=db,
            account=account,
            user_id=user_id,
            direction="debit",
            amount=credit_amount,
            balance_before=balance_before,
            balance_after=balance_after,
            biz_type="material_cdn_upload",
            biz_id=charge_id,
            idempotency_key=f"material-cdn:debit:{charge_id}",
            description=f"CDN 素材上传扣除 {credit_amount} 积分",
            gift_amount=gift_used,
        )
    except Exception:
        if sub2_receipt is not None:
            await refund_image_task_balance(db, task_no=task_no, receipt=sub2_receipt)
        raise
    return MaterialCdnChargeReceipt(
        charge_id=charge_id,
        credit_amount=credit_amount,
        sub2_receipt=sub2_receipt,
    )


async def refund_material_cdn_upload(
    db: AsyncSession,
    *,
    user_id: int,
    receipt: MaterialCdnChargeReceipt,
) -> None:
    if receipt.credit_amount <= 0:
        return
    refund_key = f"material-cdn:refund:{receipt.charge_id}"
    existing_refund = await db.scalar(select(CreditLedger.id).where(CreditLedger.idempotency_key == refund_key))
    if existing_refund is not None:
        return

    await refund_image_task_balance(
        db,
        task_no=_sub2_charge_task_no(receipt.charge_id),
        receipt=receipt.sub2_receipt,
    )
    account = await _get_or_create_credit_account_for_update(db, user_id)
    balance_before = account.balance
    balance_after = balance_before + receipt.credit_amount
    account.balance = balance_after
    debit_gift_amount = await db.scalar(
        select(CreditLedger.gift_amount).where(
            CreditLedger.idempotency_key == f"material-cdn:debit:{receipt.charge_id}"
        )
    ) or 0
    account.gift_balance += debit_gift_amount
    account.total_consumed = max(0, account.total_consumed - receipt.credit_amount)
    account.version += 1
    _add_credit_ledger(
        db=db,
        account=account,
        user_id=user_id,
        direction="credit",
        amount=receipt.credit_amount,
        balance_before=balance_before,
        balance_after=balance_after,
        biz_type="material_cdn_upload_refund",
        biz_id=receipt.charge_id,
        idempotency_key=refund_key,
        description=f"CDN 素材上传失败退回 {receipt.credit_amount} 积分",
        gift_amount=debit_gift_amount,
    )
