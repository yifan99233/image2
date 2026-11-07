from fastapi import APIRouter, Depends
from sqlalchemy import BigInteger, Column, Integer, MetaData, String, Table, desc, outerjoin, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.responses import StandardResponse, ok
from app.db.session import get_db
from app.models.credit import CreditLedger, UserCreditAccount
from app.models.user import User
from app.schemas.credits import CreditBalanceOut, CreditLedgerOut
from app.services.sub2_image_billing import authoritative_credit_balance

router = APIRouter(prefix="/credits", tags=["credits"])

shared_metadata = MetaData()
recharge_orders_table = Table(
    "recharge_orders",
    shared_metadata,
    Column("id", BigInteger),
    Column("order_no", String),
    Column("amount_cents", Integer),
)


async def ensure_credit_account(db: AsyncSession, user_id: int) -> UserCreditAccount:
    account = await db.scalar(select(UserCreditAccount).where(UserCreditAccount.user_id == user_id))
    if account is not None:
        return account

    account = UserCreditAccount(user_id=user_id)
    db.add(account)
    await db.commit()
    await db.refresh(account)
    return account


@router.get("/balance", response_model=StandardResponse[CreditBalanceOut])
async def balance(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StandardResponse[CreditBalanceOut]:
    account = await ensure_credit_account(db, current_user.id)
    live_balance = await authoritative_credit_balance(db, user_id=current_user.id)
    return ok(
        CreditBalanceOut(
            balance=account.balance if live_balance is None else live_balance,
            gift_balance=min(account.gift_balance, max(0, account.balance if live_balance is None else live_balance)),
            total_gifted=account.total_gifted,
            total_recharged=account.total_recharged,
            total_consumed=account.total_consumed,
        )
    )


@router.get("/ledger", response_model=StandardResponse[list[CreditLedgerOut]])
async def ledger(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StandardResponse[list[CreditLedgerOut]]:
    joined = outerjoin(
        CreditLedger,
        recharge_orders_table,
        (CreditLedger.biz_type == "recharge") & (CreditLedger.biz_id == recharge_orders_table.c.order_no),
    )
    rows = await db.execute(
        select(CreditLedger, recharge_orders_table.c.amount_cents.label("payment_amount_cents"))
        .select_from(joined)
        .where(CreditLedger.user_id == current_user.id)
        .order_by(desc(CreditLedger.created_at))
        .limit(100)
    )
    return ok(
        [
            CreditLedgerOut(
                id=ledger.id,
                gift_amount=ledger.gift_amount,
                direction=ledger.direction,
                amount=ledger.amount,
                balance_after=ledger.balance_after,
                biz_type=ledger.biz_type,
                description=ledger.description or "",
                payment_amount_cents=payment_amount_cents,
                created_at=ledger.created_at.isoformat() if ledger.created_at else "",
            )
            for ledger, payment_amount_cents in rows
        ]
    )
