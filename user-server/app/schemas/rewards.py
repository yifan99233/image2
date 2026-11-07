from datetime import date

from decimal import Decimal
from pydantic import BaseModel


class SigninRecordOut(BaseModel):
    id: int
    sign_date: date
    awarded_credits: int
    streak_days: int
    created_at: str


class SigninStatusOut(BaseModel):
    is_enabled: bool
    daily_credits: int
    today_signed: bool
    current_streak: int
    total_signins: int
    last_sign_date: date | None
    recent_records: list[SigninRecordOut]


class SigninResultOut(BaseModel):
    awarded_credits: int
    balance_after: Decimal
    sign_date: date
    current_streak: int
