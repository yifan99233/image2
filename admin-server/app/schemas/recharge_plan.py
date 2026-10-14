from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class RechargePlanBase(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    amount_cents: int = Field(gt=0)
    credit_amount: int = Field(gt=0)
    bonus_credit_amount: int = Field(default=0, ge=0)
    team_seat_count: int = Field(default=0, ge=0, le=1000)
    team_duration_days: int = Field(default=0, ge=0, le=3650)
    badge: str | None = Field(default=None, max_length=32)
    sort_order: int = Field(default=50, ge=0)
    is_recommended: bool = False
    is_active: bool = True


class RechargePlanCreate(RechargePlanBase):
    pass


class RechargePlanUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    amount_cents: int | None = Field(default=None, gt=0)
    credit_amount: int | None = Field(default=None, gt=0)
    bonus_credit_amount: int | None = Field(default=None, ge=0)
    team_seat_count: int | None = Field(default=None, ge=0, le=1000)
    team_duration_days: int | None = Field(default=None, ge=0, le=3650)
    badge: str | None = Field(default=None, max_length=32)
    sort_order: int | None = Field(default=None, ge=0)
    is_recommended: bool | None = None
    is_active: bool | None = None


class RechargePlanOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    site_id: int = 1
    name: str
    amount_cents: int
    credit_amount: int
    bonus_credit_amount: int
    team_seat_count: int
    team_duration_days: int
    badge: str | None
    sort_order: int
    is_recommended: bool
    is_active: bool
    created_at: datetime
    updated_at: datetime
