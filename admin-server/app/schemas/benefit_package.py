from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


RESOURCE_TYPES = {
    "credits",
    "team_seats",
    "image_concurrency",
    "video_concurrency",
    "task_queue_limit",
    "api_quota",
    "storage_quota",
}
GRANT_MODES = {"one_time", "daily", "weekly"}
VALIDITY_MODES = {"fixed_days", "billing_period", "permanent"}


class BenefitPackageItemInput(BaseModel):
    resource_type: str
    amount: Decimal = Field(gt=0, max_digits=20, decimal_places=2)
    grant_mode: str = "one_time"
    grant_count: int | None = Field(default=None, gt=0, le=3660)
    scope: str = "team"
    aggregation_mode: str = "sum"
    expiry_policy: str = "package_end"
    sort_order: int = Field(default=50, ge=0)

    @field_validator("resource_type")
    @classmethod
    def validate_resource_type(cls, value: str) -> str:
        normalized = value.strip()
        if normalized not in RESOURCE_TYPES:
            raise ValueError(f"resource_type must be one of {sorted(RESOURCE_TYPES)}")
        return normalized

    @field_validator("grant_mode")
    @classmethod
    def validate_grant_mode(cls, value: str) -> str:
        if value not in GRANT_MODES:
            raise ValueError(f"grant_mode must be one of {sorted(GRANT_MODES)}")
        return value

    @field_validator("scope")
    @classmethod
    def validate_scope(cls, value: str) -> str:
        if value not in {"user", "team"}:
            raise ValueError("scope must be user or team")
        return value

    @field_validator("aggregation_mode")
    @classmethod
    def validate_aggregation_mode(cls, value: str) -> str:
        if value not in {"sum", "max", "replace"}:
            raise ValueError("aggregation_mode is invalid")
        return value

    @field_validator("expiry_policy")
    @classmethod
    def validate_expiry_policy(cls, value: str) -> str:
        if value not in {"grant_period", "package_end", "permanent"}:
            raise ValueError("expiry_policy is invalid")
        return value

    @model_validator(mode="after")
    def validate_grant_count(self):
        if self.grant_mode == "one_time" and self.grant_count is not None:
            raise ValueError("one_time grants cannot set grant_count")
        if self.grant_mode != "one_time" and self.grant_count is None:
            raise ValueError("daily and weekly grants require grant_count")
        return self


class BenefitPackageBase(BaseModel):
    code: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(default="", max_length=2000)
    amount_cents: int = Field(gt=0, le=100_000_000)
    currency: str = Field(default="CNY", min_length=3, max_length=8)
    purchase_mode: str = Field(default="one_time", pattern=r"^(one_time|subscription)$")
    billing_interval: str | None = Field(default=None, pattern=r"^(month|quarter|year)$")
    validity_mode: str = Field(default="fixed_days", pattern=r"^(fixed_days|billing_period|permanent)$")
    validity_value: int | None = Field(default=None, gt=0, le=36500)
    activation_policy: str = Field(default="payment_success", pattern=r"^payment_success$")
    timezone: str = Field(default="Asia/Shanghai", min_length=1, max_length=64)
    stacking_policy: str = Field(default="reject", pattern=r"^(reject|extend|stack)$")
    badge: str | None = Field(default=None, max_length=32)
    sort_order: int = Field(default=50, ge=0)
    is_recommended: bool = False
    is_active: bool = True
    items: list[BenefitPackageItemInput] = Field(min_length=1, max_length=32)

    @model_validator(mode="after")
    def validate_package(self):
        if self.purchase_mode == "subscription" and not self.billing_interval:
            raise ValueError("subscription packages require billing_interval")
        if self.purchase_mode == "one_time" and self.billing_interval:
            raise ValueError("one_time packages cannot set billing_interval")
        if self.validity_mode == "billing_period" and self.purchase_mode != "subscription":
            raise ValueError("billing_period packages require subscription purchase mode")
        if self.purchase_mode == "subscription" and self.validity_mode != "billing_period":
            raise ValueError("subscription packages must use billing_period validity")
        if self.validity_mode == "fixed_days" and self.validity_value is None:
            raise ValueError("fixed_days packages require validity_value")
        if self.validity_mode != "fixed_days" and self.validity_value is not None:
            raise ValueError("validity_value is only valid for fixed_days packages")
        try:
            ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError as error:
            raise ValueError("timezone is not a valid IANA timezone") from error
        for item in self.items:
            if item.resource_type in {"team_seats", "image_concurrency", "video_concurrency", "task_queue_limit"} and item.scope == "user":
                raise ValueError(f"{item.resource_type} must use team scope")
            if item.resource_type == "team_seats" and item.amount < 2:
                raise ValueError("team_seats must be at least 2, including the owner")
            if self.validity_mode == "fixed_days" and self.validity_value:
                max_grants = self.validity_value if item.grant_mode == "daily" else (self.validity_value + 6) // 7
                if item.grant_mode != "one_time" and (item.grant_count or 0) > max_grants:
                    raise ValueError("grant_count exceeds the package validity")
        return self


class BenefitPackageCreate(BenefitPackageBase):
    pass


class BenefitPackageUpdate(BenefitPackageBase):
    pass


class BenefitPackageItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    resource_type: str
    value_type: str
    amount: Decimal
    grant_mode: str
    grant_count: int | None
    scope: str
    aggregation_mode: str
    expiry_policy: str
    sort_order: int


class BenefitPackageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    site_id: int
    code: str
    name: str
    description: str
    amount_cents: int
    currency: str
    purchase_mode: str
    billing_interval: str | None
    validity_mode: str
    validity_value: int | None
    activation_policy: str
    timezone: str
    stacking_policy: str
    badge: str | None
    sort_order: int
    is_recommended: bool
    is_active: bool
    version: int
    created_at: datetime
    updated_at: datetime
    items: list[BenefitPackageItemOut]
