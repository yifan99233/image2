from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from sqlalchemy import desc, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.exceptions import BusinessError
from app.core.responses import StandardResponse, ok
from app.db.session import get_db
from app.models.credit import CreditLedger, UserCreditAccount
from app.models.reward import SigninRewardConfig, UserSigninRecord
from app.models.user import User
from app.schemas.rewards import SigninRecordOut, SigninResultOut, SigninStatusOut
from app.services.sub2_image_billing import credit_signin_balance

router = APIRouter(prefix="/rewards", tags=["rewards"])
BUSINESS_TIMEZONE = ZoneInfo("Asia/Shanghai")


def today_in_business_timezone() -> date:
    return datetime.now(BUSINESS_TIMEZONE).date()


def record_out(record: UserSigninRecord) -> SigninRecordOut:
    return SigninRecordOut(
        id=record.id,
        sign_date=record.sign_date,
        awarded_credits=record.awarded_credits,
        streak_days=record.streak_days,
        created_at=record.created_at.isoformat() if record.created_at else "",
    )


async def get_signin_config(db: AsyncSession, site_id: int) -> SigninRewardConfig:
    config = await db.scalar(select(SigninRewardConfig).where(SigninRewardConfig.site_id == site_id))
    if config is not None:
        return config
    next_id = (await db.scalar(select(func.coalesce(func.max(SigninRewardConfig.id), 0)))) + 1
    config = SigninRewardConfig(id=next_id, site_id=site_id, is_enabled=False, daily_credits=0)
    db.add(config)
    await db.flush()
    return config


async def get_or_create_credit_account_for_update(db: AsyncSession, user_id: int) -> UserCreditAccount:
    account = await db.scalar(
        select(UserCreditAccount)
        .where(UserCreditAccount.user_id == user_id)
        .with_for_update()
    )
    if account is not None:
        return account
    account = UserCreditAccount(user_id=user_id)
    db.add(account)
    await db.flush()
    return account


async def build_status(db: AsyncSession, user_id: int, site_id: int, config: SigninRewardConfig | None = None) -> SigninStatusOut:
    config = config or await get_signin_config(db, site_id)
    today = today_in_business_timezone()
    latest_record = await db.scalar(
        select(UserSigninRecord)
        .where(UserSigninRecord.user_id == user_id)
        .order_by(desc(UserSigninRecord.sign_date))
        .limit(1)
    )
    recent_records = await db.scalars(
        select(UserSigninRecord)
        .where(UserSigninRecord.user_id == user_id)
        .order_by(desc(UserSigninRecord.sign_date))
        .limit(10)
    )
    total_signins = await db.scalar(
        select(func.count()).select_from(UserSigninRecord).where(UserSigninRecord.user_id == user_id)
    )
    return SigninStatusOut(
        is_enabled=config.is_enabled,
        daily_credits=config.daily_credits,
        today_signed=latest_record is not None and latest_record.sign_date == today,
        current_streak=latest_record.streak_days if latest_record else 0,
        total_signins=total_signins or 0,
        last_sign_date=latest_record.sign_date if latest_record else None,
        recent_records=[record_out(record) for record in recent_records],
    )


@router.get("/signin/status", response_model=StandardResponse[SigninStatusOut])
async def signin_status(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StandardResponse[SigninStatusOut]:
    return ok(await build_status(db, current_user.id, current_user.site_id))


@router.post("/signin", response_model=StandardResponse[SigninResultOut])
async def signin(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StandardResponse[SigninResultOut]:
    config = await get_signin_config(db, current_user.site_id)
    if not config.is_enabled:
        raise BusinessError("签到功能暂未开启", code=40020)
    if config.daily_credits <= 0:
        raise BusinessError("签到积分配置无效", code=40021)

    today = today_in_business_timezone()
    yesterday = today - timedelta(days=1)
    previous_record = await db.scalar(
        select(UserSigninRecord)
        .where(UserSigninRecord.user_id == current_user.id, UserSigninRecord.sign_date < today)
        .order_by(desc(UserSigninRecord.sign_date))
        .limit(1)
    )
    streak_days = previous_record.streak_days + 1 if previous_record and previous_record.sign_date == yesterday else 1
    authoritative_balance_after = await credit_signin_balance(
        db,
        user_id=current_user.id,
        sign_date=today,
        credit_amount=config.daily_credits,
    )
    account = await get_or_create_credit_account_for_update(db, current_user.id)
    balance_before = account.balance
    balance_after = balance_before + config.daily_credits

    record = UserSigninRecord(
        user_id=current_user.id,
        sign_date=today,
        awarded_credits=config.daily_credits,
        streak_days=streak_days,
    )
    account.balance = balance_after
    account.version += 1
    ledger = CreditLedger(
        user_id=current_user.id,
        account_id=account.id,
        direction="credit",
        amount=config.daily_credits,
        balance_before=balance_before,
        balance_after=balance_after,
        biz_type="signin",
        biz_id=f"signin:{today.isoformat()}",
        idempotency_key=f"signin:{current_user.id}:{today.isoformat()}",
        description=f"每日签到奖励 {config.daily_credits} 积分",
        operator_type="user",
        operator_id=current_user.id,
        created_at=datetime.now(UTC),
    )
    db.add(record)
    db.add(ledger)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise BusinessError("今日已签到，请明天再来", code=40910, status_code=409) from exc
    await db.refresh(record)
    return ok(
        SigninResultOut(
            awarded_credits=config.daily_credits,
            balance_after=balance_after if authoritative_balance_after is None else authoritative_balance_after,
            sign_date=record.sign_date,
            current_streak=record.streak_days,
        )
    )
