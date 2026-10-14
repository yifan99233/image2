import asyncio
import base64
import hashlib
import hmac
import json
import secrets
import time
import urllib.parse
import urllib.error
import urllib.request
from io import BytesIO
from pathlib import Path
from uuid import uuid4
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, File, Query, Request, UploadFile
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy import BigInteger, Boolean, Column, Date, DateTime, Integer, MetaData, Numeric, String, Table, Text, and_, delete, desc, func, insert, or_, outerjoin, select, text, update
from sqlalchemy.exc import IntegrityError, OperationalError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_admin, get_db, require_admin_roles, require_system_super_admin
from app.core.config import settings
from app.core.exceptions import AppException
from app.models.admin_audit_log import AdminAuditLog
from app.models.admin_openapi_key import AdminOpenAPIKey
from app.models.admin_user import AdminRole, AdminUser
from app.models.image_model import ImageModel, ImageModelProvider
from app.models.image_spec import (
    ImageAspectRatioSpec,
    ImageModelAspectRatio,
    ImageModelDuration,
    ImageModelResolution,
    ImageResolutionSpec,
    VideoDurationSpec,
)
from app.models.model_price import ModelPrice
from app.models.openagent_release import OpenAgentRelease
from app.models.recharge_plan import RechargePlan
from app.schemas.image_model import AdminImageModelCreate, AdminImageModelOut
from app.schemas.recharge_plan import RechargePlanCreate, RechargePlanOut, RechargePlanUpdate
from app.schemas.response import ApiResponse
from app.services.customer_vip import VipStatus, membership_status_condition, memberships_for_users
from app.services.admin_credit_adjustments import adjust_user_credit
from app.services.admin_user_balances import UserBalanceLookup, resolve_user_credit_balances
from app.services.security import hash_password, hash_user_password
from app.services.admin_openapi import generate_openapi_key, normalize_scopes, openapi_key_out
from app.services.site_bootstrap import clone_site_bootstrap
from app.services.site_scope import request_host, site_host_aliases
from app.services.sub2_balance import Sub2BalanceTarget

router = APIRouter()

DEFAULT_MODEL_TASK_TIMEOUT_SECONDS = 120
MAX_MODEL_TASK_TIMEOUT_SECONDS = 3600
DEFAULT_SITE_ICON_URL = "/image2ai-icon.svg"
ANNOUNCEMENT_IMAGE_MAX_BYTES = 10 * 1024 * 1024
ANNOUNCEMENT_IMAGE_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}


def model_task_timeout_seconds(model: ImageModel) -> int:
    """Use the model's task budget for a generation connectivity check.

    Provider timeout remains only for provider-level discovery requests; it must
    not override a model's runtime task contract.
    """
    try:
        value = int(getattr(model, "timeout_seconds", DEFAULT_MODEL_TASK_TIMEOUT_SECONDS) or DEFAULT_MODEL_TASK_TIMEOUT_SECONDS)
    except (TypeError, ValueError):
        value = DEFAULT_MODEL_TASK_TIMEOUT_SECONDS
    return max(3, min(value, MAX_MODEL_TASK_TIMEOUT_SECONDS))


class AdminAccountCreateRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    role: AdminRole = AdminRole.operator
    system_super_admin: bool = False
    site_id: int | None = Field(default=None, ge=1)
    is_active: bool = True
    create_openapi_key: bool = False
    openapi_key_name: str = Field(default="", max_length=120)
    openapi_scopes: list[str] = Field(default_factory=list)


class AdminAccountStatusRequest(BaseModel):
    is_active: bool


class AdminAccountUpdateRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    email: EmailStr
    role: AdminRole = AdminRole.operator
    system_super_admin: bool | None = None
    site_id: int | None = Field(default=None, ge=1)
    is_active: bool = True
    password: str = Field(default="", max_length=128)


class TeamEntitlementGrantRequest(BaseModel):
    seat_count: int = Field(ge=2, le=1000)
    duration_days: int = Field(default=0, ge=0, le=3650)
    reason: str = Field(min_length=1, max_length=255)


class UserPasswordResetRequest(BaseModel):
    new_password: str = Field(min_length=8, max_length=128)


class UserCustomerOwnershipRequest(BaseModel):
    owner_admin_id: int | None = Field(default=None, ge=1)


class CreditAdjustmentRequest(BaseModel):
    delta: int = Field(ge=-1_000_000_000, le=1_000_000_000)
    reason: str = Field(min_length=1, max_length=255)
    idempotency_key: str = Field(
        default_factory=lambda: uuid4().hex,
        min_length=8,
        max_length=120,
        pattern=r"^[A-Za-z0-9_-]+$",
    )


class AgentGroupsRequest(BaseModel):
    base_url: str = ""
    admin_api_key: str = ""


class OpenAgentReleaseRequest(BaseModel):
    channel: str = Field(default="prod", pattern="^(prod|beta)$")
    version: str = Field(min_length=1, max_length=64)
    platform: str = Field(default="mac", pattern="^(mac|windows|linux)$")
    arch: str = Field(default="arm64", pattern="^[a-z0-9-]{2,64}$")
    file_url: str = Field(min_length=1, max_length=2048)
    file_sha512: str = Field(min_length=16, max_length=256)
    file_size: int = Field(ge=1)
    release_notes: str = ""
    is_active: bool = True
    is_mandatory: bool = False


class OpenAgentUploadTokenRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=255)


class AdminOpenAPIKeyCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    site_id: int | None = Field(default=None, ge=1)
    scopes: list[str] = Field(default_factory=list)
    is_active: bool = True


class AdminOpenAPIKeyStatusRequest(BaseModel):
    is_active: bool


class MaterialUploadTokenRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    asset_type: str = Field(default="video", pattern="^(video|image|file)$")


class MaterialAssetRequest(BaseModel):
    asset_type: str = Field(default="video", pattern="^(video|image|file)$")
    title: str = Field(min_length=1, max_length=255)
    description: str = Field(default="", max_length=2000)
    file_url: str = Field(min_length=1, max_length=2048)
    cover_url: str = Field(default="", max_length=2048)
    mime_type: str = Field(default="", max_length=128)
    file_size: int = Field(default=0, ge=0)
    sort_order: int = Field(default=50, ge=0, le=999999)
    is_active: bool = True


class ZPayConfigRequest(BaseModel):
    is_enabled: bool = False
    pid: str = Field(default="", max_length=128)
    pkey: str = Field(default="", max_length=2048)
    api_base: str = Field(default="", max_length=2048)
    notify_url: str = Field(default="", max_length=2048)
    return_url: str = Field(default="", max_length=2048)
    payment_type: str = Field(default="alipay", pattern="^(alipay|wxpay|qqpay|bank|jdpay)$")
    payment_mode: str = Field(default="qrcode", pattern="^(qrcode|popup)$")
    timeout_seconds: int = Field(default=10, ge=3, le=60)
    order_expire_minutes: int = Field(default=30, ge=1, le=1440)


class FeedbackStatusRequest(BaseModel):
    status: str = Field(pattern="^(pending|processing|resolved|closed)$")
    admin_remark: str = Field(default="", max_length=2000)


class LeadTrialApplicationStatusRequest(BaseModel):
    status: str = Field(pattern="^(pending|processing|approved|rejected)$")
    admin_remark: str = Field(default="", max_length=2000)


class HomepageCaseCarouselItemRequest(BaseModel):
    title: str = Field(default="", max_length=80)
    subtitle: str = Field(default="", max_length=160)
    image_url: str = Field(default="", max_length=2048)
    file_url: str = Field(default="", max_length=2048)
    link_url: str = Field(default="", max_length=2048)
    tone: str = Field(default="blue", pattern="^(blue|orange|cyan|green)$")


class SiteContentMaterialRequest(BaseModel):
    title: str = Field(default="", max_length=80)
    subtitle: str = Field(default="", max_length=200)
    file_url: str = Field(default="", max_length=2048)
    cover_url: str = Field(default="", max_length=2048)
    link_url: str = Field(default="", max_length=2048)
    tags: list[str] = Field(default_factory=list)
    tone: str = Field(default="blue", pattern="^(blue|orange|cyan|green)$")


class SystemAnnouncementRequest(BaseModel):
    is_enabled: bool = False
    title: str = Field(default="", max_length=80)
    content: str = Field(default="", max_length=2000)
    image_url: str = Field(default="", max_length=2048)


class SiteIconRequest(BaseModel):
    site_icon_url: str = Field(default=DEFAULT_SITE_ICON_URL, max_length=2048)

    @field_validator("site_icon_url")
    @classmethod
    def validate_site_icon_url(cls, value: str) -> str:
        normalized = value.strip() or DEFAULT_SITE_ICON_URL
        if normalized.startswith("/") and not normalized.startswith("//"):
            return normalized
        parsed = urllib.parse.urlparse(normalized)
        if parsed.scheme in {"http", "https"} and parsed.netloc:
            return normalized
        raise ValueError("网站图标必须是站内路径或 HTTP(S) URL")


class SiteConfigRequest(SiteIconRequest):
    site_key: str = Field(default="main", min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")
    site_name: str = Field(default="艺源", min_length=1, max_length=128)
    frontend_url: str = Field(default="", max_length=2048)
    admin_url: str = Field(default="", max_length=2048)
    is_default: bool = False
    is_enabled: bool = True
    enabled_modules: list[str] = Field(default_factory=list)
    support_qq: str = Field(default="", max_length=64)
    support_wechat: str = Field(default="", max_length=128)
    support_wechat_qrcode_url: str = Field(default="", max_length=2048)
    support_email: str = Field(default="", max_length=255)
    homepage_case_carousels: list[list[HomepageCaseCarouselItemRequest]] = Field(default_factory=list)
    homepage_batch_banners: list[SiteContentMaterialRequest] = Field(default_factory=list)
    lead_case_materials: list[SiteContentMaterialRequest] = Field(default_factory=list)
    opencode_install_video: SiteContentMaterialRequest = Field(default_factory=SiteContentMaterialRequest)
    system_announcement: SystemAnnouncementRequest = Field(default_factory=SystemAnnouncementRequest)
    template_site_id: int | None = Field(default=None, ge=1)


class SiteContentConfigRequest(SiteIconRequest):
    support_qq: str = Field(default="", max_length=64)
    support_wechat: str = Field(default="", max_length=128)
    support_wechat_qrcode_url: str = Field(default="", max_length=2048)
    support_email: str = Field(default="", max_length=255)
    homepage_case_carousels: list[list[HomepageCaseCarouselItemRequest]] = Field(default_factory=list)
    homepage_batch_banners: list[SiteContentMaterialRequest] = Field(default_factory=list)
    lead_case_materials: list[SiteContentMaterialRequest] = Field(default_factory=list)
    opencode_install_video: SiteContentMaterialRequest = Field(default_factory=SiteContentMaterialRequest)
    system_announcement: SystemAnnouncementRequest | None = None


shared_metadata = MetaData()
users_table = Table(
    "users",
    shared_metadata,
    Column("id", BigInteger),
    Column("site_id", BigInteger),
    Column("username", String),
    Column("email", String),
    Column("nickname", String),
    Column("password_hash", String),
    Column("customer_owner_admin_id", BigInteger),
    Column("is_active", Boolean),
    Column("is_internal", Boolean),
    Column("image_concurrency_limit", Integer),
    Column("last_login_at", DateTime(timezone=True)),
    Column("created_at", DateTime(timezone=True)),
    Column("deleted_at", DateTime(timezone=True)),
)
customer_owner_admin_table = AdminUser.__table__.alias("customer_owner_admin")
user_lead_modules_table = Table(
    "user_lead_modules",
    shared_metadata,
    Column("id", BigInteger),
    Column("user_id", BigInteger),
    Column("enterprise_id", String),
    Column("enterprise_account", String),
    Column("enterprise_password_secret", String),
    Column("is_enabled", Boolean),
    Column("opened_by_admin_id", BigInteger),
    Column("credentials_revealed_at", DateTime(timezone=True)),
    Column("created_at", DateTime(timezone=True)),
    Column("updated_at", DateTime(timezone=True)),
)
credit_accounts_table = Table(
    "user_credit_accounts",
    shared_metadata,
    Column("id", BigInteger),
    Column("user_id", BigInteger),
    Column("balance", Numeric(20, 2)),
    Column("total_recharged", Numeric(20, 2)),
    Column("total_consumed", Numeric(20, 2)),
    Column("version", Integer),
)
credit_ledger_table = Table(
    "credit_ledger",
    shared_metadata,
    Column("id", BigInteger),
    Column("user_id", BigInteger),
    Column("account_id", BigInteger),
    Column("direction", String),
    Column("amount", Numeric(20, 2)),
    Column("balance_before", Numeric(20, 2)),
    Column("balance_after", Numeric(20, 2)),
    Column("biz_type", String),
    Column("biz_id", String),
    Column("idempotency_key", String),
    Column("description", String),
    Column("operator_type", String),
    Column("operator_id", BigInteger),
    Column("is_flagged", Boolean),
    Column("flag_reason", String),
    Column("flagged_by", BigInteger),
    Column("flagged_at", DateTime(timezone=True)),
    Column("created_at", DateTime(timezone=True)),
)
image_tasks_table = Table(
    "image_tasks",
    shared_metadata,
    Column("id", BigInteger),
    Column("task_no", String),
    Column("site_id", BigInteger),
    Column("user_id", BigInteger),
    Column("model_id", BigInteger),
    Column("work_type", String),
    Column("prompt", String),
    Column("resolution", String),
    Column("aspect_ratio", String),
    Column("quality", String),
    Column("credit_cost", Numeric(20, 2)),
    Column("status", String),
    Column("failure_message", String),
    Column("input_image_url", String),
    Column("input_image_urls", Text),
    Column("output_image_url", String),
    Column("is_gallery_featured", Boolean),
    Column("gallery_title", String),
    Column("gallery_sort_order", Integer),
    Column("gallery_featured_by", BigInteger),
    Column("gallery_featured_at", DateTime(timezone=True)),
    Column("deleted_at", DateTime(timezone=True)),
    Column("created_at", DateTime(timezone=True)),
    Column("finished_at", DateTime(timezone=True)),
    Column("worker_started_at", DateTime(timezone=True)),
    Column("worker_heartbeat_at", DateTime(timezone=True)),
)
invite_reward_configs_table = Table(
    "invite_reward_configs",
    shared_metadata,
    Column("id", BigInteger),
    Column("site_id", BigInteger),
    Column("is_enabled", Boolean),
    Column("valid_user_reward_credits", Integer),
    Column("recharge_reward_percent", Integer),
    Column("valid_user_rule", String),
    Column("updated_by", BigInteger),
    Column("created_at", DateTime(timezone=True)),
    Column("updated_at", DateTime(timezone=True)),
)
signin_reward_configs_table = Table(
    "signin_reward_configs",
    shared_metadata,
    Column("id", BigInteger),
    Column("site_id", BigInteger),
    Column("is_enabled", Boolean),
    Column("daily_credits", Integer),
    Column("updated_by", BigInteger),
    Column("created_at", DateTime(timezone=True)),
    Column("updated_at", DateTime(timezone=True)),
)
user_experience_configs_table = Table(
    "user_experience_configs",
    shared_metadata,
    Column("id", BigInteger),
    Column("site_id", BigInteger),
    Column("max_batch_tasks", Integer),
    Column("qiniu_storage_enabled", Boolean),
    Column("updated_by", BigInteger),
    Column("created_at", DateTime(timezone=True)),
    Column("updated_at", DateTime(timezone=True)),
)
signin_records_table = Table(
    "user_signin_records",
    shared_metadata,
    Column("id", BigInteger),
    Column("user_id", BigInteger),
    Column("sign_date", Date),
    Column("awarded_credits", Integer),
    Column("streak_days", Integer),
    Column("created_at", DateTime(timezone=True)),
)
payment_configs_table = Table(
    "payment_configs",
    shared_metadata,
    Column("id", BigInteger),
    Column("site_id", BigInteger),
    Column("provider", String),
    Column("is_enabled", Boolean),
    Column("pid", String),
    Column("pkey", Text),
    Column("api_base", Text),
    Column("notify_url", Text),
    Column("return_url", Text),
    Column("payment_type", String),
    Column("payment_mode", String),
    Column("timeout_seconds", Integer),
    Column("order_expire_minutes", Integer),
    Column("updated_by", BigInteger),
    Column("created_at", DateTime(timezone=True)),
    Column("updated_at", DateTime(timezone=True)),
)
recharge_orders_table = Table(
    "recharge_orders",
    shared_metadata,
    Column("id", BigInteger),
    Column("order_no", String),
    Column("site_id", BigInteger),
    Column("user_id", BigInteger),
    Column("plan_id", BigInteger),
    Column("amount_cents", Integer),
    Column("credit_amount", Integer),
    Column("bonus_credit_amount", Integer),
    Column("team_seat_count", Integer),
    Column("team_duration_days", Integer),
    Column("status", String),
    Column("payment_provider", String),
    Column("payment_type", String),
    Column("payment_trade_no", String),
    Column("pay_url", Text),
    Column("qr_code", Text),
    Column("failure_message", Text),
    Column("expires_at", DateTime(timezone=True)),
    Column("paid_at", DateTime(timezone=True)),
    Column("created_at", DateTime(timezone=True)),
    Column("updated_at", DateTime(timezone=True)),
)
team_entitlements_table = Table(
    "team_entitlements",
    shared_metadata,
    Column("id", BigInteger),
    Column("site_id", BigInteger),
    Column("owner_user_id", BigInteger),
    Column("seat_count", Integer),
    Column("source", String),
    Column("source_reference", String),
    Column("status", String),
    Column("starts_at", DateTime(timezone=True)),
    Column("expires_at", DateTime(timezone=True)),
    Column("note", String),
    Column("created_by_admin_id", BigInteger),
    Column("created_at", DateTime(timezone=True)),
    Column("updated_at", DateTime(timezone=True)),
)
agent_configs_table = Table(
    "agent_configs",
    shared_metadata,
    Column("id", BigInteger),
    Column("site_id", BigInteger),
    Column("is_enabled", Boolean),
    Column("image_billing_enabled", Boolean),
    Column("base_url", String),
    Column("admin_api_key", String),
    Column("credit_to_agent_rate", Numeric(12, 4)),
    Column("text_group_id", BigInteger),
    Column("image_group_id", BigInteger),
    Column("create_api_key_path", String),
    Column("user_concurrency", Integer),
    Column("user_rpm_limit", Integer),
    Column("updated_by", BigInteger),
    Column("created_at", DateTime(timezone=True)),
    Column("updated_at", DateTime(timezone=True)),
)
site_configs_table = Table(
    "site_configs",
    shared_metadata,
    Column("id", BigInteger),
    Column("site_key", String),
    Column("site_name", String),
    Column("site_icon_url", Text),
    Column("frontend_url", Text),
    Column("admin_url", Text),
    Column("is_default", Boolean),
    Column("is_enabled", Boolean),
    Column("enabled_modules", Text),
    Column("support_qq", String),
    Column("support_wechat", String),
    Column("support_wechat_qrcode_url", Text),
    Column("support_email", String),
    Column("homepage_case_carousels", Text),
    Column("homepage_batch_banners", Text),
    Column("lead_case_materials", Text),
    Column("opencode_install_video", Text),
    Column("system_announcement", Text),
    Column("updated_by", BigInteger),
    Column("created_at", DateTime(timezone=True)),
    Column("updated_at", DateTime(timezone=True)),
)
user_impersonation_grants_table = Table(
    "user_impersonation_grants",
    shared_metadata,
    Column("token_hash", String(64), primary_key=True),
    Column("user_id", BigInteger),
    Column("site_id", BigInteger),
    Column("admin_id", BigInteger),
    Column("admin_username", String(80)),
    Column("expires_at", DateTime(timezone=True)),
    Column("consumed_at", DateTime(timezone=True)),
    Column("created_at", DateTime(timezone=True)),
)
user_agent_accounts_table = Table(
    "user_agent_accounts",
    shared_metadata,
    Column("id", BigInteger),
    Column("user_id", BigInteger),
    Column("agent_user_id", BigInteger),
    Column("agent_email", String),
    Column("text_api_key", String),
    Column("image_api_key", String),
    Column("status", String),
    Column("failure_message", String),
    Column("created_at", DateTime(timezone=True)),
    Column("updated_at", DateTime(timezone=True)),
)
agent_transfer_records_table = Table(
    "agent_transfer_records",
    shared_metadata,
    Column("id", BigInteger),
    Column("user_id", BigInteger),
    Column("credit_amount", Integer),
    Column("agent_amount", Numeric(12, 4)),
    Column("agent_user_id", BigInteger),
    Column("status", String),
    Column("failure_message", String),
    Column("created_at", DateTime(timezone=True)),
)
feedbacks_table = Table(
    "user_feedbacks",
    shared_metadata,
    Column("id", BigInteger),
    Column("site_id", BigInteger),
    Column("user_id", BigInteger),
    Column("description", Text),
    Column("image_urls", Text),
    Column("status", String),
    Column("admin_remark", Text),
    Column("handled_by", BigInteger),
    Column("handled_at", DateTime(timezone=True)),
    Column("created_at", DateTime(timezone=True)),
    Column("updated_at", DateTime(timezone=True)),
)
lead_trial_applications_table = Table(
    "lead_trial_applications",
    shared_metadata,
    Column("id", BigInteger),
    Column("site_id", BigInteger),
    Column("user_id", BigInteger),
    Column("business_scope", Text),
    Column("keywords", Text),
    Column("competitor_accounts", Text),
    Column("contact_info", String),
    Column("status", String),
    Column("admin_remark", Text),
    Column("handled_by_admin_id", BigInteger),
    Column("handled_at", DateTime(timezone=True)),
    Column("created_at", DateTime(timezone=True)),
    Column("updated_at", DateTime(timezone=True)),
)
material_assets_table = Table(
    "material_assets",
    shared_metadata,
    Column("id", BigInteger),
    Column("site_id", BigInteger),
    Column("asset_type", String),
    Column("title", String),
    Column("description", Text),
    Column("file_url", Text),
    Column("cover_url", Text),
    Column("mime_type", String),
    Column("file_size", BigInteger),
    Column("sort_order", Integer),
    Column("is_active", Boolean),
    Column("created_by", BigInteger),
    Column("updated_by", BigInteger),
    Column("created_at", DateTime(timezone=True)),
    Column("updated_at", DateTime(timezone=True)),
)


def page(items: list, page_no: int = 1, page_size: int = 20) -> dict:
    return {"items": items, "total": len(items), "page": page_no, "page_size": page_size}


def iso(value) -> str | None:
    return value.isoformat() if value else None


def duration_seconds(start, end) -> int | None:
    if not start or not end or end < start:
        return None
    return max(0, int(round((end - start).total_seconds())))


def add_audit(
    db: AsyncSession,
    admin: AdminUser | None,
    action: str,
    resource_type: str,
    resource_id: str | int,
    reason: str | None = None,
) -> None:
    db.add(
        AdminAuditLog(
            admin_id=admin.id if admin else None,
            admin_username=admin.username if admin else "system",
            action=action,
            resource_type=resource_type,
            resource_id=str(resource_id),
            reason=reason,
        )
    )


def is_missing_shared_table_error(error: Exception, table_name: str) -> bool:
    return table_name in str(error).lower()


def default_invite_reward_config() -> dict:
    return {
        "is_enabled": False,
        "valid_user_reward_credits": 0,
        "recharge_reward_percent": 0,
        "valid_user_rule": "invited_user_first_paid_recharge",
        "valid_user_rule_label": "被邀请用户完成首次付费充值后成为有效用户",
        "updated_at": None,
    }


def invite_reward_config_out(row) -> dict:
    if row is None:
        return default_invite_reward_config()
    get_value = row.get if hasattr(row, "get") else lambda key, default=None: getattr(row, key, default)
    return {
        "is_enabled": bool(get_value("is_enabled")),
        "valid_user_reward_credits": int(get_value("valid_user_reward_credits", 0) or 0),
        "recharge_reward_percent": int(get_value("recharge_reward_percent", 0) or 0),
        "valid_user_rule": get_value("valid_user_rule") or "invited_user_first_paid_recharge",
        "valid_user_rule_label": "被邀请用户完成首次付费充值后成为有效用户",
        "updated_at": iso(get_value("updated_at")),
    }


def openagent_release_out(release: OpenAgentRelease) -> dict:
    return {
        "id": release.id,
        "site_id": release.site_id,
        "channel": release.channel,
        "version": release.version,
        "platform": release.platform,
        "arch": release.arch,
        "file_url": release.file_url,
        "file_sha512": release.file_sha512,
        "file_size": release.file_size,
        "release_notes": release.release_notes or "",
        "is_active": release.is_active,
        "is_mandatory": release.is_mandatory,
        "published_at": iso(release.published_at),
        "created_at": iso(release.created_at),
        "updated_at": iso(release.updated_at),
    }


def default_signin_reward_config() -> dict:
    return {
        "is_enabled": False,
        "daily_credits": 0,
        "updated_at": None,
    }


DEFAULT_MAX_BATCH_TASKS = 20000


def default_user_experience_config() -> dict:
    return {
        "max_batch_tasks": DEFAULT_MAX_BATCH_TASKS,
        "qiniu_storage_enabled": False,
        "updated_at": None,
    }


def default_agent_config() -> dict:
    return {
        "is_enabled": False,
        "image_billing_enabled": False,
        "base_url": "",
        "admin_api_key_masked": "",
        "credit_to_agent_rate": 1,
        "text_group_id": None,
        "image_group_id": None,
        "create_api_key_path": "",
        "user_concurrency": 5,
        "user_rpm_limit": 0,
        "updated_at": None,
    }


def default_site_config() -> dict:
    return {
        "id": 1,
        "site_key": "main",
        "site_name": "艺源",
        "site_icon_url": DEFAULT_SITE_ICON_URL,
        "frontend_url": "",
        "admin_url": "",
        "is_default": True,
        "is_enabled": True,
        "enabled_modules": default_site_modules(),
        "support_qq": "1223362085",
        "support_wechat": "YiTiao1024L",
        "support_wechat_qrcode_url": "/wechat-qrcode.png",
        "support_email": "support@example.com",
        "homepage_case_carousels": [
            [
                {"title": "电商套图", "subtitle": "主图、场景图、详情页素材统一生成", "image_url": "", "file_url": "", "link_url": "", "tone": "blue"},
                {"title": "产品效果图", "subtitle": "上传商品图后快速延展应用场景", "image_url": "", "file_url": "", "link_url": "", "tone": "orange"},
            ],
            [
                {"title": "图片二次优化", "subtitle": "改背景、换氛围、补细节", "image_url": "", "file_url": "", "link_url": "", "tone": "cyan"},
                {"title": "案例展示", "subtitle": "生成前后效果直接对比", "image_url": "", "file_url": "", "link_url": "", "tone": "green"},
            ],
        ],
        "homepage_batch_banners": [],
        "lead_case_materials": default_lead_case_materials(),
        "opencode_install_video": default_opencode_install_video(),
        "system_announcement": default_system_announcement(),
        "updated_at": None,
    }


def default_lead_case_materials() -> list[dict]:
    return [
        {"title": "家具", "subtitle": "家居门店获客案例", "file_url": "", "cover_url": "", "link_url": "", "tags": [], "tone": "blue"},
        {"title": "大健康", "subtitle": "养生门店转化案例", "file_url": "", "cover_url": "", "link_url": "", "tags": [], "tone": "green"},
        {"title": "珠宝", "subtitle": "高客单私域案例", "file_url": "", "cover_url": "", "link_url": "", "tags": [], "tone": "orange"},
        {"title": "考公", "subtitle": "课程线索转化案例", "file_url": "", "cover_url": "", "link_url": "", "tags": [], "tone": "cyan"},
    ]


def default_opencode_install_video() -> dict:
    return {
        "title": "从需求到交付的自动化流程",
        "subtitle": "演示 Codex定制版如何读取需求、修改文件、运行验证并输出结果。",
        "file_url": "",
        "cover_url": "",
        "link_url": "",
        "tags": ["写代码", "做文件", "查资料"],
        "tone": "blue",
    }


def default_system_announcement() -> dict:
    return {"is_enabled": False, "title": "", "content": "", "image_url": ""}


def default_site_modules() -> list[str]:
    return [
        "dashboard",
        "gallery",
        "image_edit",
        "text_to_image",
        "text_to_video",
        "image_to_video",
        "batch_generate",
        "batch_edit",
        "works",
        "leads",
        "opencode",
        "feedback",
        "support",
        "signin",
        "invite",
        "recharge",
    ]


def normalize_site_modules(value) -> list[str]:
    allowed = set(default_site_modules())
    if isinstance(value, str):
        try:
            value = json.loads(value) if value else default_site_modules()
        except json.JSONDecodeError:
            return default_site_modules()
    if not isinstance(value, list):
        return default_site_modules()
    modules = [str(module).strip() for module in value if str(module).strip() in allowed]
    return modules or default_site_modules()


def normalize_homepage_case_carousels(value) -> list[list[dict]]:
    defaults = default_site_config()["homepage_case_carousels"]
    if isinstance(value, str):
        try:
            value = json.loads(value) if value else defaults
        except json.JSONDecodeError:
            return defaults
    if not isinstance(value, list):
        return defaults
    normalized_groups: list[list[dict]] = []
    for group in value[:2]:
        if not isinstance(group, list):
            normalized_groups.append([])
            continue
        normalized_items: list[dict] = []
        for item in group[:4]:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or "").strip()
            subtitle = str(item.get("subtitle") or "").strip()
            if not title:
                continue
            tone = str(item.get("tone") or "blue").strip()
            normalized_items.append(
                {
                    "title": title[:80],
                    "subtitle": subtitle[:160],
                    "image_url": str(item.get("image_url") or "").strip()[:2048],
                    "file_url": str(item.get("file_url") or "").strip()[:2048],
                    "link_url": str(item.get("link_url") or "").strip()[:2048],
                    "tone": tone if tone in {"blue", "orange", "cyan", "green"} else "blue",
                }
            )
        normalized_groups.append(normalized_items)
    while len(normalized_groups) < 2:
        normalized_groups.append([])
    return [group or defaults[index] for index, group in enumerate(normalized_groups[:2])]


def normalize_content_materials(value, defaults: list[dict], *, limit: int = 4) -> list[dict]:
    if isinstance(value, str):
        try:
            value = json.loads(value) if value else defaults
        except json.JSONDecodeError:
            return defaults
    if not isinstance(value, list):
        return defaults
    normalized: list[dict] = []
    for item in value[:limit]:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        if not title:
            continue
        tone = str(item.get("tone") or "blue").strip()
        tags = item.get("tags") if isinstance(item.get("tags"), list) else []
        normalized.append(
            {
                "title": title[:80],
                "subtitle": str(item.get("subtitle") or "").strip()[:200],
                "file_url": str(item.get("file_url") or "").strip()[:2048],
                "cover_url": str(item.get("cover_url") or "").strip()[:2048],
                "link_url": str(item.get("link_url") or "").strip()[:2048],
                "tags": [str(tag).strip()[:24] for tag in tags if str(tag).strip()][:6],
                "tone": tone if tone in {"blue", "orange", "cyan", "green"} else "blue",
            }
        )
    return normalized or defaults


def normalize_content_material(value, default: dict) -> dict:
    if isinstance(value, str):
        try:
            value = json.loads(value) if value else default
        except json.JSONDecodeError:
            return default
    if not isinstance(value, dict):
        return default
    return normalize_content_materials([value], [default], limit=1)[0]


def normalize_system_announcement(value) -> dict:
    default = default_system_announcement()
    if isinstance(value, str):
        try:
            value = json.loads(value) if value else default
        except json.JSONDecodeError:
            return default
    if not isinstance(value, dict):
        return default
    content = str(value.get("content") or "").strip()[:2000]
    return {
        "is_enabled": bool(value.get("is_enabled")) and bool(content),
        "title": str(value.get("title") or "").strip()[:80],
        "content": content,
        "image_url": str(value.get("image_url") or "").strip()[:2048],
    }


def site_config_out(row) -> dict:
    if not row:
        return default_site_config()
    get_value = row.get if hasattr(row, "get") else lambda key, default=None: getattr(row, key, default)
    defaults = default_site_config()
    return {
        "id": get_value("id") or defaults["id"],
        "site_key": get_value("site_key") or defaults["site_key"],
        "site_name": get_value("site_name") or defaults["site_name"],
        "site_icon_url": get_value("site_icon_url") or defaults["site_icon_url"],
        "frontend_url": get_value("frontend_url") or "",
        "admin_url": get_value("admin_url") or "",
        "is_default": bool(get_value("is_default")),
        "is_enabled": bool(get_value("is_enabled", True)),
        "enabled_modules": normalize_site_modules(get_value("enabled_modules")),
        "support_qq": get_value("support_qq") or "",
        "support_wechat": get_value("support_wechat") or "",
        "support_wechat_qrcode_url": get_value("support_wechat_qrcode_url") or "",
        "support_email": get_value("support_email") or "",
        "homepage_case_carousels": normalize_homepage_case_carousels(get_value("homepage_case_carousels")),
        "homepage_batch_banners": normalize_content_materials(get_value("homepage_batch_banners"), [], limit=8),
        "lead_case_materials": normalize_content_materials(get_value("lead_case_materials"), defaults["lead_case_materials"]),
        "opencode_install_video": normalize_content_material(get_value("opencode_install_video"), defaults["opencode_install_video"]),
        "system_announcement": normalize_system_announcement(get_value("system_announcement")),
        "created_at": iso(get_value("created_at")),
        "updated_at": iso(get_value("updated_at")),
    }


async def current_site_config_row(db: AsyncSession, request: Request):
    host = request_host(request)
    if host:
        host_conditions = [
            condition
            for alias_host in site_host_aliases(host)
            for condition in (
                site_configs_table.c.admin_url.ilike(f"%{alias_host}%"),
                site_configs_table.c.frontend_url.ilike(f"%{alias_host}%"),
            )
        ]
        matched = await db.execute(
            select(site_configs_table)
            .where(
                site_configs_table.c.is_enabled.is_(True),
                or_(*host_conditions),
            )
            .order_by(desc(site_configs_table.c.is_default), site_configs_table.c.id)
            .limit(1)
        )
        row = matched.mappings().first()
        if row:
            return row
    fallback = await db.execute(select(site_configs_table).where(site_configs_table.c.is_default.is_(True)).limit(1))
    row = fallback.mappings().first()
    if row:
        return row
    yiyuan = await db.execute(
        select(site_configs_table)
        .where(or_(site_configs_table.c.site_key == "main", site_configs_table.c.site_name == "艺源"))
        .order_by(site_configs_table.c.id)
        .limit(1)
    )
    row = yiyuan.mappings().first()
    if row:
        return row
    fallback = await db.execute(select(site_configs_table).order_by(site_configs_table.c.id).limit(1))
    return fallback.mappings().first()


async def public_site_config(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[dict]:
    try:
        return ApiResponse.ok(site_config_out(await current_site_config_row(db, request)))
    except (OperationalError, ProgrammingError) as error:
        if is_missing_shared_table_error(error, "site_configs"):
            return ApiResponse.ok(default_site_config())
        raise


def agent_config_out(row) -> dict:
    if row is None:
        return default_agent_config()
    get_value = row.get if hasattr(row, "get") else lambda key, default=None: getattr(row, key, default)
    defaults = default_agent_config()
    return {
        "is_enabled": bool(get_value("is_enabled")),
        "image_billing_enabled": bool(get_value("image_billing_enabled")),
        "base_url": get_value("base_url") or defaults["base_url"],
        "admin_api_key_masked": mask_secret(get_value("admin_api_key")),
        "credit_to_agent_rate": float(get_value("credit_to_agent_rate") or 1),
        "text_group_id": get_value("text_group_id"),
        "image_group_id": get_value("image_group_id"),
        "create_api_key_path": get_value("create_api_key_path") or "",
        "user_concurrency": int(get_value("user_concurrency") or defaults["user_concurrency"]),
        "user_rpm_limit": int(get_value("user_rpm_limit") or 0),
        "updated_at": iso(get_value("updated_at")),
    }


def default_zpay_config() -> dict:
    frontend_url = settings.resolved_site_frontend_url
    return {
        "is_enabled": False,
        "pid": "",
        "pkey_masked": "",
        "api_base": "https://pay.example.com",
        "notify_url": f"{frontend_url}/api/recharge/zpay/notify" if frontend_url else "",
        "return_url": f"{frontend_url}/billing/recharge" if frontend_url else "",
        "payment_type": "alipay",
        "payment_mode": "qrcode",
        "timeout_seconds": 10,
        "order_expire_minutes": 30,
        "updated_at": None,
    }


def zpay_config_out(row) -> dict:
    if row is None:
        return default_zpay_config()
    get_value = row.get if hasattr(row, "get") else lambda key, default=None: getattr(row, key, default)
    defaults = default_zpay_config()
    return {
        "is_enabled": bool(get_value("is_enabled")),
        "pid": get_value("pid") or "",
        "pkey_masked": mask_secret(get_value("pkey")),
        "api_base": get_value("api_base") or "",
        "notify_url": get_value("notify_url") or "",
        "return_url": get_value("return_url") or "",
        "payment_type": get_value("payment_type") or defaults["payment_type"],
        "payment_mode": get_value("payment_mode") or defaults["payment_mode"],
        "timeout_seconds": int(get_value("timeout_seconds") or defaults["timeout_seconds"]),
        "order_expire_minutes": int(get_value("order_expire_minutes") or defaults["order_expire_minutes"]),
        "updated_at": iso(get_value("updated_at")),
    }


def recharge_order_out(row) -> dict:
    total_credits = int(row.credit_amount or 0) + int(row.bonus_credit_amount or 0)
    return {
        "id": row.id,
        "order_no": row.order_no,
        "user_id": row.user_id,
        "username": row.username or "-",
        "email": row.email or "",
        "amount_cents": int(row.amount_cents or 0),
        "credit_amount": int(row.credit_amount or 0),
        "bonus_credit_amount": int(row.bonus_credit_amount or 0),
        "total_credit_amount": total_credits,
        "team_seat_count": int(row.team_seat_count or 0),
        "team_duration_days": int(row.team_duration_days or 0),
        "status": row.status or "pending",
        "payment_provider": row.payment_provider or "",
        "payment_type": row.payment_type or "",
        "payment_trade_no": row.payment_trade_no or "",
        "pay_url": row.pay_url or "",
        "qr_code": row.qr_code or "",
        "failure_message": row.failure_message or "",
        "expires_at": iso(row.expires_at),
        "paid_at": iso(row.paid_at),
        "created_at": iso(row.created_at),
        "updated_at": iso(row.updated_at),
    }


def fetch_agent_groups(base_url: str, admin_api_key: str) -> list[dict]:
    normalized_base_url = base_url.strip().rstrip("/")
    normalized_key = admin_api_key.strip()
    if not normalized_base_url or not normalized_key:
        raise AppException(code=40001, message="请先填写 Base URL 和管理员 Key")
    url = f"{normalized_base_url}/api/v1/admin/groups/all?{urllib.parse.urlencode({'include_inactive': 'true'})}"
    request = urllib.request.Request(
        url,
        method="GET",
        headers={
            "Accept": "application/json",
            "x-api-key": normalized_key,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="ignore")
        raise AppException(code=40001, message=f"分组查询失败：HTTP {error.code} {detail[:200]}") from None
    except urllib.error.URLError as error:
        raise AppException(code=40001, message=f"分组查询失败：{error.reason}") from None

    try:
        payload = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        raise AppException(code=40001, message="分组查询失败：Agent 服务返回了非 JSON 响应") from None

    if isinstance(payload, dict) and int(payload.get("code", 0) or 0) != 0:
        raise AppException(code=40001, message=str(payload.get("message") or payload.get("reason") or "分组查询失败"))
    data = payload.get("data") if isinstance(payload, dict) and "data" in payload else payload
    if not isinstance(data, list):
        raise AppException(code=40001, message="分组查询失败：Agent 服务返回的分组格式不正确")
    groups: list[dict] = []
    for item in data:
        if not isinstance(item, dict) or item.get("id") is None:
            continue
        groups.append(
            {
                "id": int(item["id"]),
                "name": str(item.get("name") or f"Group {item['id']}"),
                "platform": str(item.get("platform") or ""),
                "is_active": bool(item.get("is_active", item.get("enabled", True))),
            }
        )
    return groups


def resolve_agent_group_credentials(
    requested_base_url: str,
    requested_admin_api_key: str,
    stored_config,
) -> tuple[str, str]:
    base_url = requested_base_url.strip().rstrip("/")
    admin_api_key = requested_admin_api_key.strip()
    if admin_api_key:
        return base_url, admin_api_key

    get_value = (
        stored_config.get
        if hasattr(stored_config, "get")
        else lambda key, default=None: getattr(stored_config, key, default)
    )
    stored_base_url = str(get_value("base_url") or "").strip().rstrip("/")
    stored_admin_api_key = str(get_value("admin_api_key") or "").strip()
    if base_url != stored_base_url:
        raise AppException(code=40001, message="Base URL 已变更，请填写该 Agent 服务对应的管理员 Key")
    return base_url, stored_admin_api_key


def signin_reward_config_out(row) -> dict:
    if row is None:
        return default_signin_reward_config()
    return {
        "is_enabled": bool(row.is_enabled),
        "daily_credits": int(row.daily_credits or 0),
        "updated_at": iso(row.updated_at),
    }


def user_experience_config_out(row) -> dict:
    if row is None:
        return default_user_experience_config()
    get_value = row.get if hasattr(row, "get") else lambda key, default=None: getattr(row, key, default)
    max_batch_tasks = int(get_value("max_batch_tasks") or DEFAULT_MAX_BATCH_TASKS)
    if max_batch_tasks < 1:
        max_batch_tasks = DEFAULT_MAX_BATCH_TASKS
    return {
        "max_batch_tasks": max_batch_tasks,
        "qiniu_storage_enabled": bool(get_value("qiniu_storage_enabled") or False),
        "updated_at": iso(get_value("updated_at")),
    }


def feedback_out(row) -> dict:
    try:
        image_urls = json.loads(row.image_urls or "[]")
    except json.JSONDecodeError:
        image_urls = []
    return {
        "id": row.id,
        "user_id": row.user_id,
        "username": row.username or "-",
        "email": row.email or "",
        "description": row.description or "",
        "image_urls": image_urls if isinstance(image_urls, list) else [],
        "status": row.status or "pending",
        "admin_remark": row.admin_remark or "",
        "handled_by": row.handled_by,
        "handled_at": iso(row.handled_at),
        "created_at": iso(row.created_at),
        "updated_at": iso(row.updated_at),
    }


def lead_trial_application_out(row) -> dict:
    return {
        "id": row.id,
        "user_id": row.user_id,
        "username": row.username or "-",
        "email": row.email or "",
        "is_active": bool(row.is_active) if row.is_active is not None else True,
        "is_internal": bool(row.is_internal),
        "credit_balance": Decimal(str(row.credit_balance or 0)),
        "lead_module_enabled": bool(row.lead_module_enabled),
        "business_scope": row.business_scope or "",
        "keywords": row.keywords or "",
        "competitor_accounts": row.competitor_accounts or "",
        "contact_info": row.contact_info or "",
        "status": row.status or "pending",
        "admin_remark": row.admin_remark or "",
        "handled_by_admin_id": row.handled_by_admin_id,
        "handled_at": iso(row.handled_at),
        "created_at": iso(row.created_at),
        "updated_at": iso(row.updated_at),
    }


def material_asset_out(row) -> dict:
    return {
        "id": row.id,
        "asset_type": row.asset_type or "video",
        "title": row.title or "",
        "description": row.description or "",
        "file_url": row.file_url or "",
        "cover_url": row.cover_url or "",
        "mime_type": row.mime_type or "",
        "file_size": int(row.file_size or 0),
        "sort_order": int(row.sort_order or 0),
        "is_active": bool(row.is_active),
        "created_at": iso(row.created_at),
        "updated_at": iso(row.updated_at),
    }


async def site_name_map(db: AsyncSession, site_ids: set[int]) -> dict[int, str]:
    if not site_ids:
        return {}
    try:
        rows = await db.execute(select(site_configs_table.c.id, site_configs_table.c.site_name).where(site_configs_table.c.id.in_(site_ids)))
    except (OperationalError, ProgrammingError) as error:
        if is_missing_shared_table_error(error, "site_configs"):
            return {}
        raise
    return {int(row.id): row.site_name or f"站点 {row.id}" for row in rows}


async def current_site_id(db: AsyncSession, request: Request) -> int:
    try:
        row = await current_site_config_row(db, request)
    except (OperationalError, ProgrammingError) as error:
        if is_missing_shared_table_error(error, "site_configs"):
            return 1
        raise
    return int(row["id"]) if row and row.get("id") else 1


def admin_scope_site_id(current_admin: AdminUser) -> int:
    return int(current_admin.site_id or 1)


def scoped_condition(current_admin: AdminUser, site_column):
    if current_admin.system_super_admin:
        return True
    return site_column == admin_scope_site_id(current_admin)


def scoped_user_condition(current_admin: AdminUser):
    return scoped_condition(current_admin, users_table.c.site_id)


def ensure_can_impersonate_users(current_admin: AdminUser) -> None:
    if (
        current_admin.username.strip().lower() == "yifan"
        and current_admin.role == AdminRole.super_admin
        and current_admin.system_super_admin
    ):
        return
    raise AppException(code=40320, message="仅 yifan 系统超级管理员可使用代登录", status_code=403)


def normalize_impersonation_frontend_url(frontend_url: str) -> str:
    normalized = frontend_url.strip().rstrip("/")
    parsed = urllib.parse.urlsplit(normalized)
    hostname = (parsed.hostname or "").lower()
    is_local_http = parsed.scheme == "http" and hostname in {"localhost", "127.0.0.1", "::1"}
    if not parsed.netloc or (parsed.scheme != "https" and not is_local_http):
        raise AppException(code=40020, message="子站前台地址未配置为有效的 HTTPS 地址", status_code=400)
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", ""))


def scoped_model_condition(current_admin: AdminUser):
    return scoped_condition(current_admin, ImageModel.site_id)


async def scoped_model_by_id(db: AsyncSession, current_admin: AdminUser, model_id: int) -> ImageModel | None:
    return await db.scalar(select(ImageModel).where(ImageModel.id == model_id, scoped_model_condition(current_admin)))


async def current_admin_config_site_id(db: AsyncSession, request: Request, current_admin: AdminUser) -> int:
    if current_admin.system_super_admin:
        return await current_site_id(db, request)
    return admin_scope_site_id(current_admin)


def admin_account_condition(current_admin: AdminUser, keyword: str):
    condition = True
    if not current_admin.system_super_admin:
        condition = AdminUser.site_id == admin_scope_site_id(current_admin)
        condition = and_(condition, AdminUser.system_super_admin.is_(False))
    if keyword:
        like = f"%{keyword.strip()}%"
        keyword_condition = or_(
            AdminUser.username.ilike(like),
            AdminUser.email.ilike(like),
            AdminUser.id.cast(String).ilike(like),
        )
        condition = keyword_condition if condition is True else and_(condition, keyword_condition)
    return condition


def ensure_can_manage_admin_account(current_admin: AdminUser, admin: AdminUser) -> None:
    if current_admin.system_super_admin:
        return
    if admin.system_super_admin or admin_scope_site_id(admin) != admin_scope_site_id(current_admin):
        raise AppException(code=404, message="管理员账号不存在")


async def admin_account_out(db: AsyncSession, admin: AdminUser, site_names: dict[int, str] | None = None) -> dict:
    site_id = admin_scope_site_id(admin)
    names = site_names if site_names is not None else await site_name_map(db, {site_id})
    return {
        "id": admin.id,
        "username": admin.username,
        "email": admin.email,
        "role": admin.role.value,
        "system_super_admin": admin.system_super_admin,
        "site_id": site_id,
        "site_name": names.get(site_id, f"站点 {site_id}"),
        "is_active": admin.is_active,
        "last_login_at": iso(admin.last_login_at),
        "created_at": iso(admin.created_at),
        "updated_at": iso(admin.updated_at),
    }


async def create_admin_openapi_key_record(
    db: AsyncSession,
    current_admin: AdminUser,
    *,
    name: str,
    site_id: int,
    scopes: list[str] | None,
    is_active: bool = True,
) -> tuple[AdminOpenAPIKey, str]:
    if not current_admin.system_super_admin and site_id != admin_scope_site_id(current_admin):
        raise AppException(code=40300, message="无权限为其他站点创建 OpenAPI Key", status_code=403)
    normalized_scopes = normalize_scopes(scopes)
    plain_key, key_prefix, key_hash = generate_openapi_key()
    api_key = AdminOpenAPIKey(
        site_id=site_id,
        name=name.strip(),
        key_prefix=key_prefix,
        key_hash=key_hash,
        scopes=json.dumps(normalized_scopes, ensure_ascii=False),
        is_active=is_active,
        created_by_admin_id=current_admin.id,
    )
    db.add(api_key)
    await db.flush()
    return api_key, plain_key


@router.get("/site/config", response_model=ApiResponse[dict])
async def site_config(
    db: AsyncSession = Depends(get_db),
    _: AdminUser = Depends(require_system_super_admin),
):
    try:
        row = await db.execute(select(site_configs_table).where(site_configs_table.c.id == 1))
        return ApiResponse.ok(site_config_out(row.mappings().first()))
    except (OperationalError, ProgrammingError) as error:
        if is_missing_shared_table_error(error, "site_configs"):
            return ApiResponse.ok(default_site_config())
        raise


@router.get("/site/configs", response_model=ApiResponse[dict])
async def site_configs(
    db: AsyncSession = Depends(get_db),
    _: AdminUser = Depends(require_system_super_admin),
):
    try:
        result = await db.execute(select(site_configs_table).order_by(desc(site_configs_table.c.is_default), site_configs_table.c.id))
        items = [site_config_out(row) for row in result.mappings().all()]
        if not items:
            items = [default_site_config()]
        return ApiResponse.ok({"items": items, "total": len(items), "page": 1, "page_size": len(items)})
    except (OperationalError, ProgrammingError) as error:
        if is_missing_shared_table_error(error, "site_configs"):
            return ApiResponse.ok({"items": [default_site_config()], "total": 1, "page": 1, "page_size": 1})
        raise


@router.get("/site/content-configs", response_model=ApiResponse[dict])
async def site_content_configs(
    db: AsyncSession = Depends(get_db),
    current_admin: AdminUser = Depends(require_admin_roles(AdminRole.super_admin, AdminRole.operator, AdminRole.finance, AdminRole.model_admin)),
):
    try:
        condition = True if current_admin.system_super_admin else site_configs_table.c.id == admin_scope_site_id(current_admin)
        result = await db.execute(select(site_configs_table).where(condition).order_by(desc(site_configs_table.c.is_default), site_configs_table.c.id))
        items = [site_config_out(row) for row in result.mappings().all()]
        if not items:
            items = [default_site_config()]
        return ApiResponse.ok({"items": items, "total": len(items), "page": 1, "page_size": len(items)})
    except (OperationalError, ProgrammingError) as error:
        if is_missing_shared_table_error(error, "site_configs"):
            return ApiResponse.ok({"items": [default_site_config()], "total": 1, "page": 1, "page_size": 1})
        raise


@router.get("/site/content-config", response_model=ApiResponse[dict])
async def site_content_config(
    request: Request,
    db: AsyncSession = Depends(get_db),
    _: AdminUser = Depends(require_admin_roles(AdminRole.super_admin, AdminRole.operator, AdminRole.finance, AdminRole.model_admin)),
):
    try:
        return ApiResponse.ok(site_config_out(await current_site_config_row(db, request)))
    except (OperationalError, ProgrammingError) as error:
        if is_missing_shared_table_error(error, "site_configs"):
            return ApiResponse.ok(default_site_config())
        raise


def site_base_config_values(payload: SiteConfigRequest, current_admin: AdminUser, *, site_id: int | None = None) -> dict:
    return {
        **({"id": site_id} if site_id is not None else {}),
        "site_key": payload.site_key.strip(),
        "site_name": payload.site_name.strip(),
        "frontend_url": payload.frontend_url.strip(),
        "admin_url": payload.admin_url.strip(),
        "is_default": payload.is_default,
        "is_enabled": payload.is_enabled,
        "enabled_modules": json.dumps(normalize_site_modules(payload.enabled_modules), ensure_ascii=False),
        "system_announcement": json.dumps(normalize_system_announcement(payload.system_announcement.model_dump()), ensure_ascii=False),
        "updated_by": current_admin.id,
        "updated_at": datetime.now(timezone.utc),
    }


def site_domain_key(site_key: str) -> str:
    normalized = "".join(char.lower() if char.isalnum() else "-" for char in site_key.strip())
    return "-".join(part for part in normalized.split("-") if part) or "site"


def generated_site_urls(site_key: str) -> dict[str, str]:
    domain_key = site_domain_key(site_key)
    frontend_root = settings.site_frontend_root_domain.strip().strip(".")
    admin_root = settings.site_admin_root_domain.strip().strip(".")
    frontend_base = settings.site_frontend_base_subdomain.strip().strip(".") or "magic"
    admin_base = settings.site_admin_base_subdomain.strip().strip(".") or "magic-admin"
    return {
        "frontend_url": f"https://{frontend_base}-{domain_key}.{frontend_root}" if frontend_root else "",
        "admin_url": f"https://{admin_base}-{domain_key}.{admin_root}" if admin_root else "",
    }


def apply_generated_site_urls(values: dict) -> dict:
    if values.get("site_key") == "main":
        return values
    generated = generated_site_urls(str(values.get("site_key") or "site"))
    if not values.get("frontend_url"):
        values["frontend_url"] = generated["frontend_url"]
    if not values.get("admin_url"):
        values["admin_url"] = generated["admin_url"]
    return values


def default_site_content_values() -> dict:
    defaults = default_site_config()
    return {
        "site_icon_url": defaults["site_icon_url"],
        "support_qq": defaults["support_qq"],
        "support_wechat": defaults["support_wechat"],
        "support_wechat_qrcode_url": defaults["support_wechat_qrcode_url"],
        "support_email": defaults["support_email"],
        "homepage_case_carousels": json.dumps(defaults["homepage_case_carousels"], ensure_ascii=False),
        "homepage_batch_banners": json.dumps(defaults["homepage_batch_banners"], ensure_ascii=False),
        "lead_case_materials": json.dumps(defaults["lead_case_materials"], ensure_ascii=False),
        "opencode_install_video": json.dumps(defaults["opencode_install_video"], ensure_ascii=False),
    }


def template_site_content_values(row) -> dict:
    defaults = default_site_content_values()
    if row is None:
        return defaults
    get_value = row.get if hasattr(row, "get") else lambda key, default=None: getattr(row, key, default)
    return {
        key: get_value(key) if get_value(key) not in (None, "") else default_value
        for key, default_value in defaults.items()
    }


async def resolve_site_template_row(db: AsyncSession, template_site_id: int | None):
    if template_site_id is not None:
        result = await db.execute(select(site_configs_table).where(site_configs_table.c.id == template_site_id).limit(1))
        row = result.mappings().first()
        if row is None:
            raise AppException(code=40421, message="初始化模板站点不存在", status_code=404)
        return row

    result = await db.execute(
        select(site_configs_table)
        .where(site_configs_table.c.site_key == "art")
        .limit(1)
    )
    row = result.mappings().first()
    if row:
        return row

    result = await db.execute(
        select(site_configs_table)
        .order_by(desc(site_configs_table.c.is_default), site_configs_table.c.id)
        .limit(1)
    )
    return result.mappings().first()


def site_content_config_values(payload: SiteContentConfigRequest, current_admin: AdminUser) -> dict:
    values = {
        "site_icon_url": payload.site_icon_url.strip() or default_site_config()["site_icon_url"],
        "support_qq": payload.support_qq.strip(),
        "support_wechat": payload.support_wechat.strip(),
        "support_wechat_qrcode_url": payload.support_wechat_qrcode_url.strip(),
        "support_email": payload.support_email.strip(),
        "homepage_case_carousels": json.dumps(
            normalize_homepage_case_carousels([[item.model_dump() for item in group] for group in payload.homepage_case_carousels]),
            ensure_ascii=False,
        ),
        "homepage_batch_banners": json.dumps(
            normalize_content_materials([item.model_dump() for item in payload.homepage_batch_banners], [], limit=8),
            ensure_ascii=False,
        ),
        "lead_case_materials": json.dumps(
            normalize_content_materials([item.model_dump() for item in payload.lead_case_materials], default_lead_case_materials()),
            ensure_ascii=False,
        ),
        "opencode_install_video": json.dumps(
            normalize_content_material(payload.opencode_install_video.model_dump(), default_opencode_install_video()),
            ensure_ascii=False,
        ),
        "updated_by": current_admin.id,
        "updated_at": datetime.now(timezone.utc),
    }
    if payload.system_announcement is not None:
        values["system_announcement"] = json.dumps(
            normalize_system_announcement(payload.system_announcement.model_dump()),
            ensure_ascii=False,
        )
    return values


async def apply_default_site(db: AsyncSession, site_id: int, is_default: bool) -> None:
    if is_default:
        await db.execute(update(site_configs_table).where(site_configs_table.c.id != site_id).values(is_default=False))
    else:
        has_default = await db.scalar(select(site_configs_table.c.id).where(site_configs_table.c.is_default.is_(True), site_configs_table.c.id != site_id))
        if has_default is None:
            raise AppException(code=40050, message="至少需要保留一个默认总站点", status_code=400)


@router.post("/site/configs", response_model=ApiResponse[dict])
async def create_site_config(
    payload: SiteConfigRequest,
    db: AsyncSession = Depends(get_db),
    current_admin: AdminUser = Depends(require_system_super_admin),
):
    try:
        # site_configs uses an application-assigned bigint key, so serialize creation
        # to prevent two simultaneous requests from selecting the same next id.
        await db.execute(text("LOCK TABLE site_configs IN SHARE ROW EXCLUSIVE MODE"))
        duplicate = await db.scalar(select(site_configs_table.c.id).where(site_configs_table.c.site_key == payload.site_key.strip()))
        if duplicate is not None:
            raise AppException(code=40051, message="站点标识已存在", status_code=400)

        template_row = await resolve_site_template_row(db, payload.template_site_id)
        if template_row is None:
            raise AppException(code=40052, message="没有可用的初始化模板站点", status_code=400)

        next_id = int((await db.scalar(select(func.coalesce(func.max(site_configs_table.c.id), 0) + 1))) or 1)
        values = {
            **template_site_content_values(template_row),
            **apply_generated_site_urls(site_base_config_values(payload, current_admin, site_id=next_id)),
            "created_at": datetime.now(timezone.utc),
        }
        await apply_default_site(db, next_id, payload.is_default)
        await db.execute(insert(site_configs_table).values(**values))
        bootstrap = await clone_site_bootstrap(
            db,
            source_site_id=int(template_row["id"]),
            target_site_id=next_id,
            updated_by=current_admin.id,
            module_config_tables=(
                invite_reward_configs_table,
                signin_reward_configs_table,
                user_experience_configs_table,
                agent_configs_table,
            ),
            payment_config_table=payment_configs_table,
            frontend_url=str(values["frontend_url"] or ""),
        )
        add_audit(
            db,
            current_admin,
            "create_site_config",
            "site_configs",
            next_id,
            f"创建子站点 {payload.site_key}; 模板={template_row['site_key']}; 复制配置={bootstrap.total}",
        )
        await db.commit()
    except AppException:
        await db.rollback()
        raise
    except IntegrityError as error:
        await db.rollback()
        raise AppException(code=40053, message="子站初始化数据存在冲突，请检查站点标识后重试", status_code=400) from error
    except (OperationalError, ProgrammingError) as error:
        await db.rollback()
        if is_missing_shared_table_error(error, "site_configs"):
            raise AppException(code=50020, message="站点配置表不存在，请先执行数据库迁移", status_code=500) from error
        raise
    row = await db.execute(select(site_configs_table).where(site_configs_table.c.id == next_id))
    return ApiResponse.ok(site_config_out(row.mappings().first()), "子站点已创建")


@router.patch("/site/configs/{site_id}", response_model=ApiResponse[dict])
async def update_site_config_by_id(
    site_id: int,
    payload: SiteConfigRequest,
    db: AsyncSession = Depends(get_db),
    current_admin: AdminUser = Depends(require_system_super_admin),
):
    try:
        existing_id = await db.scalar(select(site_configs_table.c.id).where(site_configs_table.c.id == site_id))
        if existing_id is None:
            raise AppException(code=40420, message="子站点不存在", status_code=404)
        await apply_default_site(db, site_id, payload.is_default)
        await db.execute(update(site_configs_table).where(site_configs_table.c.id == site_id).values(**site_base_config_values(payload, current_admin)))
        add_audit(db, current_admin, "update_site_config", "site_configs", site_id, f"更新子站点 {payload.site_key}")
        await db.commit()
    except (OperationalError, ProgrammingError) as error:
        await db.rollback()
        if is_missing_shared_table_error(error, "site_configs"):
            raise AppException(code=50020, message="站点配置表不存在，请先执行数据库迁移", status_code=500) from error
        raise
    row = await db.execute(select(site_configs_table).where(site_configs_table.c.id == site_id))
    return ApiResponse.ok(site_config_out(row.mappings().first()), "子站点配置已保存")


@router.patch("/site/content-configs/{site_id}", response_model=ApiResponse[dict])
async def update_site_content_config(
    site_id: int,
    payload: SiteContentConfigRequest,
    db: AsyncSession = Depends(get_db),
    current_admin: AdminUser = Depends(require_admin_roles(AdminRole.super_admin, AdminRole.operator, AdminRole.finance, AdminRole.model_admin)),
):
    if not current_admin.system_super_admin and site_id != admin_scope_site_id(current_admin):
        raise AppException(code=40300, message="无权限修改其他站点配置", status_code=403)
    values = site_content_config_values(payload, current_admin)
    try:
        existing_id = await db.scalar(select(site_configs_table.c.id).where(site_configs_table.c.id == site_id))
        if existing_id is None:
            if site_id != 1:
                raise AppException(code=40420, message="当前站点不存在", status_code=404)
            defaults = default_site_config()
            await db.execute(
                insert(site_configs_table).values(
                    id=1,
                    site_key=defaults["site_key"],
                    site_name=defaults["site_name"],
                    frontend_url=defaults["frontend_url"],
                    admin_url=defaults["admin_url"],
                    is_default=True,
                    is_enabled=True,
                    enabled_modules=json.dumps(defaults["enabled_modules"], ensure_ascii=False),
                    created_at=datetime.now(timezone.utc),
                    **values,
                )
            )
        else:
            await db.execute(update(site_configs_table).where(site_configs_table.c.id == site_id).values(**values))
        add_audit(db, current_admin, "update_site_content", "site_configs", site_id, "更新素材修改配置")
        await db.commit()
    except (OperationalError, ProgrammingError) as error:
        await db.rollback()
        if is_missing_shared_table_error(error, "site_configs"):
            raise AppException(code=50020, message="站点配置表不存在，请先执行数据库迁移", status_code=500) from error
        raise
    row = await db.execute(select(site_configs_table).where(site_configs_table.c.id == site_id))
    return ApiResponse.ok(site_config_out(row.mappings().first()), "素材修改配置已保存")


@router.patch("/site/content-config", response_model=ApiResponse[dict])
async def update_current_site_content_config(
    request: Request,
    payload: SiteContentConfigRequest,
    db: AsyncSession = Depends(get_db),
    current_admin: AdminUser = Depends(require_admin_roles(AdminRole.super_admin, AdminRole.operator, AdminRole.finance, AdminRole.model_admin)),
):
    row = await current_site_config_row(db, request)
    site_id = int(row["id"]) if row and row.get("id") else 1
    return await update_site_content_config(site_id, payload, db, current_admin)


@router.patch("/site/config", response_model=ApiResponse[dict])
async def update_site_config(
    payload: SiteConfigRequest,
    db: AsyncSession = Depends(get_db),
    current_admin: AdminUser = Depends(require_system_super_admin),
):
    values = site_base_config_values(payload, current_admin, site_id=1)
    values["is_default"] = True
    try:
        existing_id = await db.scalar(select(site_configs_table.c.id).where(site_configs_table.c.id == 1))
        if existing_id:
            await db.execute(update(site_configs_table).where(site_configs_table.c.id == 1).values(**{k: v for k, v in values.items() if k != "id"}))
        else:
            values["created_at"] = datetime.now(timezone.utc)
            await db.execute(insert(site_configs_table).values(**values))
        await db.execute(update(site_configs_table).where(site_configs_table.c.id != 1).values(is_default=False))
        add_audit(db, current_admin, "update_site_config", "site_configs", 1, "更新总后台站点与模块配置")
        await db.commit()
    except (OperationalError, ProgrammingError) as error:
        await db.rollback()
        if is_missing_shared_table_error(error, "site_configs"):
            raise AppException(code=50020, message="站点配置表不存在，请先执行数据库迁移", status_code=500) from error
        raise
    row = await db.execute(select(site_configs_table).where(site_configs_table.c.id == 1))
    return ApiResponse.ok(site_config_out(row.mappings().first()), "站点配置已保存")


@router.get("/admin-accounts", response_model=ApiResponse[dict])
async def admin_accounts(
    keyword: str = "",
    page_no: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_admin: AdminUser = Depends(require_admin_roles(AdminRole.super_admin)),
) -> ApiResponse[dict]:
    condition = admin_account_condition(current_admin, keyword)

    total = await db.scalar(select(func.count()).select_from(AdminUser).where(condition))
    result = await db.execute(
        select(AdminUser)
        .where(condition)
        .order_by(desc(AdminUser.created_at), desc(AdminUser.id))
        .offset((page_no - 1) * page_size)
        .limit(page_size)
    )
    admins = result.scalars().all()
    names = await site_name_map(db, {admin_scope_site_id(admin) for admin in admins})
    items = [await admin_account_out(db, admin, names) for admin in admins]
    return ApiResponse.ok({"items": items, "total": total or 0, "page": page_no, "page_size": page_size})


@router.post("/admin-accounts", response_model=ApiResponse[dict])
async def create_admin_account(
    payload: AdminAccountCreateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_admin: AdminUser = Depends(require_admin_roles(AdminRole.super_admin)),
) -> ApiResponse[dict]:
    username = payload.username.strip()
    email = str(payload.email).strip().lower()
    exists = await db.scalar(select(AdminUser).where(or_(AdminUser.username == username, AdminUser.email == email)))
    if exists:
        raise AppException(code=409, message="管理员账号或邮箱已存在")
    if not current_admin.system_super_admin and payload.system_super_admin:
        raise AppException(code=40300, message="无权限创建系统超级管理员", status_code=403)
    site_id = payload.site_id or (await current_site_id(db, request) if current_admin.system_super_admin else admin_scope_site_id(current_admin))

    admin = AdminUser(
        username=username,
        email=email,
        password_hash=hash_password(payload.password),
        role=payload.role,
        system_super_admin=payload.system_super_admin if current_admin.system_super_admin else False,
        site_id=site_id,
        is_active=payload.is_active,
    )
    db.add(admin)
    await db.flush()
    created_openapi_key = None
    plain_openapi_key = None
    if payload.create_openapi_key:
        key_name = payload.openapi_key_name.strip() or f"{admin.username} OpenAPI"
        created_openapi_key, plain_openapi_key = await create_admin_openapi_key_record(
            db,
            current_admin,
            name=key_name,
            site_id=site_id,
            scopes=payload.openapi_scopes,
            is_active=payload.is_active,
        )
    add_audit(
        db,
        current_admin,
        "create_admin_account",
        "admin_users",
        admin.id,
        f"role={admin.role.value}; system_super_admin={admin.system_super_admin}",
    )
    if created_openapi_key is not None:
        add_audit(db, current_admin, "create_admin_openapi_key_for_admin", "admin_openapi_keys", created_openapi_key.id, f"admin_id={admin.id}")
    await db.commit()
    await db.refresh(admin)
    data = await admin_account_out(db, admin)
    if created_openapi_key is not None:
        await db.refresh(created_openapi_key)
        data["openapi_key"] = openapi_key_out(created_openapi_key, plain_key=plain_openapi_key)
    return ApiResponse.ok(data)


@router.patch("/admin-accounts/{admin_id}", response_model=ApiResponse[dict])
async def update_admin_account(
    admin_id: int,
    payload: AdminAccountUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_admin: AdminUser = Depends(require_admin_roles(AdminRole.super_admin)),
) -> ApiResponse[dict]:
    admin = await db.get(AdminUser, admin_id)
    if admin is None:
        raise AppException(code=404, message="管理员账号不存在")
    ensure_can_manage_admin_account(current_admin, admin)

    username = payload.username.strip()
    email = str(payload.email).strip().lower()
    password = payload.password.strip()
    if password and len(password) < 8:
        raise AppException(code=400, message="重置密码至少 8 个字符")
    if admin.id == current_admin.id and not payload.is_active:
        raise AppException(code=400, message="不能禁用当前登录账号")
    if admin.id == current_admin.id and payload.system_super_admin is False:
        raise AppException(code=400, message="不能移除当前登录账号的系统超级管理员权限")
    if not current_admin.system_super_admin and payload.system_super_admin:
        raise AppException(code=40300, message="无权限设置系统超级管理员", status_code=403)

    exists = await db.scalar(
        select(AdminUser).where(
            AdminUser.id != admin_id,
            or_(AdminUser.username == username, AdminUser.email == email),
        )
    )
    if exists:
        raise AppException(code=409, message="管理员账号或邮箱已存在")

    admin.username = username
    admin.email = email
    admin.role = payload.role
    if current_admin.system_super_admin and payload.site_id is not None:
        admin.site_id = payload.site_id
    if current_admin.system_super_admin and payload.system_super_admin is not None:
        admin.system_super_admin = payload.system_super_admin
    admin.is_active = payload.is_active
    if password:
        admin.password_hash = hash_password(password)
    add_audit(
        db,
        current_admin,
        "update_admin_account",
        "admin_users",
        admin.id,
        f"role={admin.role.value}; system_super_admin={admin.system_super_admin}; is_active={admin.is_active}",
    )
    await db.commit()
    await db.refresh(admin)
    return ApiResponse.ok(await admin_account_out(db, admin), "管理员账号已更新")


@router.patch("/admin-accounts/{admin_id}/status", response_model=ApiResponse[dict])
async def update_admin_account_status(
    admin_id: int,
    payload: AdminAccountStatusRequest,
    db: AsyncSession = Depends(get_db),
    current_admin: AdminUser = Depends(require_admin_roles(AdminRole.super_admin)),
) -> ApiResponse[dict]:
    admin = await db.get(AdminUser, admin_id)
    if admin is None:
        raise AppException(code=404, message="管理员账号不存在")
    ensure_can_manage_admin_account(current_admin, admin)
    if admin.id == current_admin.id and not payload.is_active:
        raise AppException(code=400, message="不能禁用当前登录账号")

    admin.is_active = payload.is_active
    add_audit(db, current_admin, "update_admin_account_status", "admin_users", admin.id, f"is_active={payload.is_active}")
    await db.commit()
    await db.refresh(admin)
    return ApiResponse.ok(await admin_account_out(db, admin))


@router.get("/openapi/keys", response_model=ApiResponse[dict])
async def admin_openapi_keys(
    keyword: str = "",
    page_no: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_admin: AdminUser = Depends(require_admin_roles(AdminRole.super_admin)),
) -> ApiResponse[dict]:
    condition = scoped_condition(current_admin, AdminOpenAPIKey.site_id)
    if keyword.strip():
        like = f"%{keyword.strip()}%"
        condition = and_(condition, or_(AdminOpenAPIKey.name.ilike(like), AdminOpenAPIKey.key_prefix.ilike(like)))
    total = await db.scalar(select(func.count()).select_from(AdminOpenAPIKey).where(condition))
    result = await db.scalars(
        select(AdminOpenAPIKey)
        .where(condition)
        .order_by(desc(AdminOpenAPIKey.created_at), desc(AdminOpenAPIKey.id))
        .offset((page_no - 1) * page_size)
        .limit(page_size)
    )
    return ApiResponse.ok({"items": [openapi_key_out(api_key) for api_key in result], "total": total or 0, "page": page_no, "page_size": page_size})


@router.post("/openapi/keys", response_model=ApiResponse[dict])
async def create_admin_openapi_key(
    payload: AdminOpenAPIKeyCreateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_admin: AdminUser = Depends(require_admin_roles(AdminRole.super_admin)),
) -> ApiResponse[dict]:
    site_id = payload.site_id or (await current_site_id(db, request) if current_admin.system_super_admin else admin_scope_site_id(current_admin))
    api_key, plain_key = await create_admin_openapi_key_record(
        db,
        current_admin,
        name=payload.name,
        site_id=site_id,
        scopes=payload.scopes,
        is_active=payload.is_active,
    )
    add_audit(db, current_admin, "create_admin_openapi_key", "admin_openapi_keys", api_key.id, f"site_id={site_id}; scopes={','.join(normalize_scopes(payload.scopes))}")
    await db.commit()
    await db.refresh(api_key)
    return ApiResponse.ok(openapi_key_out(api_key, plain_key=plain_key), "OpenAPI Key 已创建，请立即保存明文 Key")


@router.patch("/openapi/keys/{key_id}/status", response_model=ApiResponse[dict])
async def update_admin_openapi_key_status(
    key_id: int,
    payload: AdminOpenAPIKeyStatusRequest,
    db: AsyncSession = Depends(get_db),
    current_admin: AdminUser = Depends(require_admin_roles(AdminRole.super_admin)),
) -> ApiResponse[dict]:
    api_key = await db.scalar(select(AdminOpenAPIKey).where(AdminOpenAPIKey.id == key_id, scoped_condition(current_admin, AdminOpenAPIKey.site_id)))
    if api_key is None:
        raise AppException(code=404, message="OpenAPI Key 不存在", status_code=404)
    api_key.is_active = payload.is_active
    add_audit(db, current_admin, "update_admin_openapi_key_status", "admin_openapi_keys", api_key.id, f"is_active={payload.is_active}")
    await db.commit()
    await db.refresh(api_key)
    return ApiResponse.ok(openapi_key_out(api_key), "OpenAPI Key 状态已更新")


@router.get("/users", response_model=ApiResponse[dict])
async def users(
    keyword: str = "",
    vip_status: VipStatus = "all",
    page_no: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_admin: AdminUser = Depends(require_admin_roles(AdminRole.super_admin, AdminRole.operator, AdminRole.finance)),
) -> ApiResponse[dict]:
    condition = and_(users_table.c.deleted_at.is_(None), scoped_user_condition(current_admin))
    if keyword:
        like = f"%{keyword.strip()}%"
        condition = condition & or_(
            users_table.c.username.ilike(like),
            users_table.c.email.ilike(like),
            users_table.c.id.cast(String).ilike(like),
        )

    if vip_status != "all":
        condition = condition & membership_status_condition(users_table, vip_status)

    total = await db.scalar(select(func.count()).select_from(users_table).where(condition))
    entitlement_now = datetime.now(timezone.utc)
    active_team_entitlements = (
        select(
            team_entitlements_table.c.owner_user_id.label("owner_user_id"),
            team_entitlements_table.c.site_id.label("site_id"),
            func.coalesce(func.sum(team_entitlements_table.c.seat_count), 0).label("team_seat_limit"),
        )
        .where(
            team_entitlements_table.c.status == "active",
            team_entitlements_table.c.starts_at <= entitlement_now,
            or_(team_entitlements_table.c.expires_at.is_(None), team_entitlements_table.c.expires_at > entitlement_now),
        )
        .group_by(team_entitlements_table.c.owner_user_id, team_entitlements_table.c.site_id)
        .subquery()
    )
    joined = outerjoin(users_table, credit_accounts_table, users_table.c.id == credit_accounts_table.c.user_id)
    joined = outerjoin(joined, user_lead_modules_table, users_table.c.id == user_lead_modules_table.c.user_id)
    joined = outerjoin(joined, user_agent_accounts_table, users_table.c.id == user_agent_accounts_table.c.user_id)
    joined = outerjoin(joined, agent_configs_table, users_table.c.site_id == agent_configs_table.c.site_id)
    joined = outerjoin(joined, customer_owner_admin_table, users_table.c.customer_owner_admin_id == customer_owner_admin_table.c.id)
    joined = outerjoin(
        joined,
        active_team_entitlements,
        and_(
            users_table.c.id == active_team_entitlements.c.owner_user_id,
            users_table.c.site_id == active_team_entitlements.c.site_id,
        ),
    )
    result = await db.execute(
        select(
            users_table.c.id,
            users_table.c.site_id,
            users_table.c.username,
            users_table.c.email,
            users_table.c.nickname,
            users_table.c.customer_owner_admin_id,
            customer_owner_admin_table.c.username.label("customer_owner_admin_name"),
            users_table.c.is_active,
            users_table.c.is_internal,
            users_table.c.image_concurrency_limit,
            users_table.c.created_at,
            users_table.c.last_login_at,
            func.coalesce(credit_accounts_table.c.balance, 0).label("credit_balance"),
            user_lead_modules_table.c.is_enabled.label("lead_module_enabled"),
            func.coalesce(active_team_entitlements.c.team_seat_limit, 0).label("team_seat_limit"),
            user_agent_accounts_table.c.agent_user_id,
            user_agent_accounts_table.c.status.label("agent_account_status"),
            agent_configs_table.c.is_enabled.label("agent_billing_enabled"),
            agent_configs_table.c.base_url.label("agent_base_url"),
            agent_configs_table.c.admin_api_key.label("agent_admin_api_key"),
            agent_configs_table.c.credit_to_agent_rate,
        )
        .select_from(joined)
        .where(condition)
        .order_by(desc(users_table.c.created_at))
        .limit(page_size)
        .offset((page_no - 1) * page_size)
    )
    rows = result.all()
    vip_by_user = await memberships_for_users(db, [row.id for row in rows])
    balance_lookups = [managed_user_balance_lookup(row) for row in rows]
    resolved_balances = await resolve_user_credit_balances(balance_lookups)
    fetched_at = datetime.now(timezone.utc).isoformat()
    items = []
    for row in rows:
        resolved_balance = resolved_balances[row.id]
        items.append({
            "id": row.id,
            "site_id": row.site_id,
            "username": row.username,
            "email": row.email,
            "nickname": row.nickname,
            "customer_owner_admin_id": row.customer_owner_admin_id,
            "customer_owner_admin_name": row.customer_owner_admin_name,
            "vip": vip_by_user.get(row.id),
            "is_active": row.is_active,
            "is_internal": bool(row.is_internal),
            "image_concurrency_limit": max(1, int(row.image_concurrency_limit or 1)),
            "credit_balance": resolved_balance.balance,
            "credit_balance_source": resolved_balance.source,
            "credit_balance_fetched_at": fetched_at if resolved_balance.source == "authoritative" else None,
            "lead_module_enabled": bool(row.lead_module_enabled),
            "team_seat_limit": int(row.team_seat_limit or 0),
            "created_at": row.created_at.isoformat() if row.created_at else "",
            "last_login_at": row.last_login_at.isoformat() if row.last_login_at else None,
        })
    return ApiResponse.ok({"items": items, "total": total or 0, "page": page_no, "page_size": page_size})


@router.get("/customer-owners", response_model=ApiResponse[list])
async def customer_owners(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_admin: AdminUser = Depends(require_admin_roles(AdminRole.super_admin, AdminRole.operator)),
) -> ApiResponse[list]:
    site_id = await current_admin_config_site_id(db, request, current_admin)
    rows = await db.execute(
        select(
            AdminUser.id,
            AdminUser.username,
            AdminUser.email,
            AdminUser.role,
        )
        .where(
            AdminUser.is_active.is_(True),
            or_(AdminUser.site_id == site_id, AdminUser.system_super_admin.is_(True)),
        )
        .order_by(AdminUser.username.asc(), AdminUser.id.asc())
    )
    return ApiResponse.ok(
        [
            {
                "id": int(row.id),
                "username": row.username,
                "email": row.email,
                "role": row.role.value if isinstance(row.role, AdminRole) else str(row.role),
            }
            for row in rows
        ]
    )


@router.patch("/users/{user_id}/customer-owner", response_model=ApiResponse[dict])
async def update_user_customer_owner(
    user_id: int,
    payload: UserCustomerOwnershipRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_admin: AdminUser = Depends(require_admin_roles(AdminRole.super_admin, AdminRole.operator)),
) -> ApiResponse[dict]:
    site_id = await current_admin_config_site_id(db, request, current_admin)
    user = await db.execute(
        select(users_table.c.customer_owner_admin_id).where(
            users_table.c.id == user_id,
            users_table.c.deleted_at.is_(None),
            scoped_user_condition(current_admin),
        )
    )
    user_row = user.first()
    if user_row is None:
        raise AppException(code=40404, message="用户不存在", status_code=404)

    owner_admin = None
    if payload.owner_admin_id is not None:
        owner_admin = await db.scalar(
            select(AdminUser).where(
                AdminUser.id == payload.owner_admin_id,
                AdminUser.is_active.is_(True),
                or_(AdminUser.site_id == site_id, AdminUser.system_super_admin.is_(True)),
            )
        )
        if owner_admin is None:
            raise AppException(code=40405, message="客户归属管理员不存在或已停用", status_code=404)

    previous_owner_admin_id = user_row.customer_owner_admin_id
    await db.execute(
        update(users_table)
        .where(
            users_table.c.id == user_id,
            users_table.c.deleted_at.is_(None),
            scoped_user_condition(current_admin),
        )
        .values(customer_owner_admin_id=payload.owner_admin_id)
    )
    add_audit(
        db,
        current_admin,
        "update_user_customer_owner",
        "users",
        user_id,
        f"客户归属管理员 {previous_owner_admin_id or 'none'} -> {payload.owner_admin_id or 'none'}",
    )
    await db.commit()
    return ApiResponse.ok(
        {
            "id": user_id,
            "customer_owner_admin_id": payload.owner_admin_id,
            "customer_owner_admin_name": owner_admin.username if owner_admin else None,
        },
        "客户归属已更新",
    )


def managed_user_balance_lookup(row) -> UserBalanceLookup:
    local_balance = Decimal(str(row.credit_balance or 0))
    base_url = str(row.agent_base_url or "").strip()
    admin_api_key = str(row.agent_admin_api_key or "").strip()
    try:
        rate = Decimal(str(row.credit_to_agent_rate or 0))
    except (InvalidOperation, ValueError):
        rate = Decimal("0")
    if not (
        bool(row.agent_billing_enabled)
        and row.agent_account_status == "active"
        and row.agent_user_id
        and base_url
        and admin_api_key
        and rate > 0
    ):
        return UserBalanceLookup(user_id=int(row.id), local_balance=local_balance)
    return UserBalanceLookup(
        user_id=int(row.id),
        local_balance=local_balance,
        target=Sub2BalanceTarget(
            base_url=base_url,
            admin_api_key=admin_api_key,
            agent_user_id=int(row.agent_user_id),
            credit_to_agent_rate=rate,
        ),
    )


@router.get("/users/{user_id}/credit-balance", response_model=ApiResponse[dict])
async def user_credit_balance(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_admin: AdminUser = Depends(require_admin_roles(AdminRole.super_admin, AdminRole.operator, AdminRole.finance)),
) -> ApiResponse[dict]:
    joined = outerjoin(users_table, credit_accounts_table, users_table.c.id == credit_accounts_table.c.user_id)
    joined = outerjoin(joined, user_agent_accounts_table, users_table.c.id == user_agent_accounts_table.c.user_id)
    joined = outerjoin(joined, agent_configs_table, users_table.c.site_id == agent_configs_table.c.site_id)
    row = (
        await db.execute(
            select(
                users_table.c.id,
                func.coalesce(credit_accounts_table.c.balance, 0).label("credit_balance"),
                user_agent_accounts_table.c.agent_user_id,
                user_agent_accounts_table.c.status.label("agent_account_status"),
                agent_configs_table.c.is_enabled.label("agent_billing_enabled"),
                agent_configs_table.c.base_url.label("agent_base_url"),
                agent_configs_table.c.admin_api_key.label("agent_admin_api_key"),
                agent_configs_table.c.credit_to_agent_rate,
            )
            .select_from(joined)
            .where(
                users_table.c.id == user_id,
                users_table.c.deleted_at.is_(None),
                scoped_user_condition(current_admin),
            )
        )
    ).first()
    if row is None:
        raise AppException(code=40404, message="用户不存在", status_code=404)
    resolved = (await resolve_user_credit_balances([managed_user_balance_lookup(row)]))[user_id]
    return ApiResponse.ok(
        {
            "user_id": user_id,
            "balance": resolved.balance,
            "source": resolved.source,
            "fetched_at": datetime.now(timezone.utc).isoformat() if resolved.source == "authoritative" else None,
        }
    )


@router.patch("/users/{user_id}/status", response_model=ApiResponse[dict])
async def user_status(
    user_id: int,
    payload: dict,
    db: AsyncSession = Depends(get_db),
    current_admin: AdminUser = Depends(require_admin_roles(AdminRole.super_admin, AdminRole.operator)),
) -> ApiResponse[dict]:
    is_active = bool(payload.get("is_active"))
    result = await db.execute(update(users_table).where(users_table.c.id == user_id, scoped_user_condition(current_admin)).values(is_active=is_active))
    if result.rowcount == 0:
        raise AppException(code=40404, message="用户不存在", status_code=404)
    add_audit(db, current_admin, "update_user_status", "users", user_id, f"is_active={is_active}")
    await db.commit()
    return ApiResponse.ok({"id": user_id, "is_active": is_active})


@router.patch("/users/{user_id}/tags", response_model=ApiResponse[dict])
async def user_tags(
    user_id: int,
    payload: dict,
    db: AsyncSession = Depends(get_db),
    current_admin: AdminUser = Depends(require_admin_roles(AdminRole.super_admin, AdminRole.operator)),
) -> ApiResponse[dict]:
    is_internal = bool(payload.get("is_internal"))
    result = await db.execute(update(users_table).where(users_table.c.id == user_id, scoped_user_condition(current_admin)).values(is_internal=is_internal))
    if result.rowcount == 0:
        raise AppException(code=40404, message="用户不存在", status_code=404)
    add_audit(db, current_admin, "update_user_tags", "users", user_id, f"is_internal={is_internal}")
    await db.commit()
    return ApiResponse.ok({"id": user_id, "is_internal": is_internal})


@router.patch("/users/{user_id}/image-concurrency", response_model=ApiResponse[dict])
async def user_image_concurrency(
    user_id: int,
    payload: dict,
    db: AsyncSession = Depends(get_db),
    current_admin: AdminUser = Depends(require_admin_roles(AdminRole.super_admin, AdminRole.operator)),
) -> ApiResponse[dict]:
    limit = max(1, int(payload.get("image_concurrency_limit") or 1))
    result = await db.execute(update(users_table).where(users_table.c.id == user_id, scoped_user_condition(current_admin)).values(image_concurrency_limit=limit))
    if result.rowcount == 0:
        raise AppException(code=40404, message="用户不存在", status_code=404)
    add_audit(db, current_admin, "update_user_image_concurrency", "users", user_id, f"image_concurrency_limit={limit}")
    await db.commit()
    return ApiResponse.ok({"id": user_id, "image_concurrency_limit": limit})


@router.patch("/users/{user_id}/password", response_model=ApiResponse[dict])
async def reset_user_password(
    user_id: int,
    payload: UserPasswordResetRequest,
    db: AsyncSession = Depends(get_db),
    current_admin: AdminUser = Depends(require_admin_roles(AdminRole.super_admin, AdminRole.operator)),
) -> ApiResponse[dict]:
    password_hash = hash_user_password(payload.new_password)
    result = await db.execute(
        update(users_table)
        .where(
            users_table.c.id == user_id,
            users_table.c.deleted_at.is_(None),
            scoped_user_condition(current_admin),
        )
        .values(password_hash=password_hash)
    )
    if result.rowcount == 0:
        raise AppException(code=40404, message="用户不存在", status_code=404)
    add_audit(db, current_admin, "reset_user_password", "users", user_id, "管理员重置前台用户密码")
    await db.commit()
    return ApiResponse.ok({"id": user_id, "changed": True}, "用户密码已重置")


@router.post("/users/{user_id}/impersonation", response_model=ApiResponse[dict])
async def create_user_impersonation(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_admin: AdminUser = Depends(get_current_admin),
) -> ApiResponse[dict]:
    ensure_can_impersonate_users(current_admin)
    user = (
        await db.execute(
            select(
                users_table.c.id,
                users_table.c.site_id,
                users_table.c.username,
                users_table.c.is_active,
            ).where(
                users_table.c.id == user_id,
                users_table.c.deleted_at.is_(None),
            )
        )
    ).one_or_none()
    if user is None:
        raise AppException(code=40404, message="用户不存在", status_code=404)
    if not user.is_active:
        raise AppException(code=40021, message="用户已被禁用，不能代登录", status_code=400)

    frontend_url = await db.scalar(
        select(site_configs_table.c.frontend_url).where(
            site_configs_table.c.id == user.site_id,
            site_configs_table.c.is_enabled.is_(True),
        )
    )
    if not frontend_url:
        raise AppException(code=40022, message="子站公开地址尚未配置", status_code=400)
    normalized_frontend_url = normalize_impersonation_frontend_url(str(frontend_url))

    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(seconds=60)
    code = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(code.encode("utf-8")).hexdigest()
    await db.execute(
        delete(user_impersonation_grants_table).where(
            user_impersonation_grants_table.c.expires_at < now - timedelta(days=1)
        )
    )
    await db.execute(
        insert(user_impersonation_grants_table).values(
            token_hash=token_hash,
            user_id=user.id,
            site_id=user.site_id,
            admin_id=current_admin.id,
            admin_username=current_admin.username,
            expires_at=expires_at,
            consumed_at=None,
            created_at=now,
        )
    )
    add_audit(
        db,
        current_admin,
        "create_user_impersonation",
        "users",
        user.id,
        f"代登录用户 {user.username}；site_id={user.site_id}；链接 60 秒内有效且仅可使用一次",
    )
    await db.commit()
    login_url = f"{normalized_frontend_url}/admin-login#code={urllib.parse.quote(code, safe='')}"
    return ApiResponse.ok(
        {"login_url": login_url, "expires_in_seconds": 60},
        "代登录链接已创建",
    )


@router.get("/users/{user_id}/lead-module", response_model=ApiResponse[dict])
async def user_lead_module(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_admin: AdminUser = Depends(require_admin_roles(AdminRole.super_admin, AdminRole.operator)),
) -> ApiResponse[dict]:
    user_exists = await db.scalar(select(users_table.c.id).where(users_table.c.id == user_id, users_table.c.deleted_at.is_(None), scoped_user_condition(current_admin)))
    if user_exists is None:
        raise AppException(code=40404, message="用户不存在", status_code=404)
    try:
        row = await db.execute(select(user_lead_modules_table).where(user_lead_modules_table.c.user_id == user_id))
    except (OperationalError, ProgrammingError) as error:
        await db.rollback()
        if is_missing_shared_table_error(error, "user_lead_modules"):
            return ApiResponse.ok({"is_enabled": False})
        raise
    return ApiResponse.ok(lead_module_out(row.mappings().first()))


@router.patch("/users/{user_id}/lead-module", response_model=ApiResponse[dict])
async def save_user_lead_module(
    user_id: int,
    payload: dict,
    db: AsyncSession = Depends(get_db),
    current_admin: AdminUser = Depends(require_admin_roles(AdminRole.super_admin, AdminRole.operator)),
) -> ApiResponse[dict]:
    is_enabled = bool(payload.get("is_enabled", True))
    enterprise_id = str(payload.get("enterprise_id") or "").strip()
    enterprise_account = str(payload.get("enterprise_account") or "").strip()
    enterprise_password = str(payload.get("enterprise_password") or "").strip()

    user_exists = await db.scalar(select(users_table.c.id).where(users_table.c.id == user_id, users_table.c.deleted_at.is_(None), scoped_user_condition(current_admin)))
    if user_exists is None:
        raise AppException(code=40404, message="用户不存在", status_code=404)

    try:
        existing_result = await db.execute(select(user_lead_modules_table).where(user_lead_modules_table.c.user_id == user_id))
    except (OperationalError, ProgrammingError) as error:
        await db.rollback()
        if is_missing_shared_table_error(error, "user_lead_modules"):
            raise AppException(code=50001, message="客资模块表未迁移", status_code=500) from None
        raise
    existing = existing_result.mappings().first()

    if is_enabled:
        if not enterprise_id:
            raise AppException(code=40001, message="企业 ID 不能为空")
        if not enterprise_account:
            raise AppException(code=40001, message="企业账号不能为空")
        if existing is None and not enterprise_password:
            raise AppException(code=40001, message="首次开通必须填写企业密码")

    values = {
        "user_id": user_id,
        "enterprise_id": enterprise_id or (existing or {}).get("enterprise_id") or "",
        "enterprise_account": enterprise_account or (existing or {}).get("enterprise_account") or "",
        "is_enabled": is_enabled,
        "opened_by_admin_id": current_admin.id,
        "updated_at": func.now(),
    }
    if enterprise_password:
        values["enterprise_password_secret"] = enterprise_password
    elif existing is None:
        values["enterprise_password_secret"] = ""
    if existing is None or enterprise_password or enterprise_account != ((existing or {}).get("enterprise_account") or ""):
        values["credentials_revealed_at"] = None

    if existing:
        await db.execute(update(user_lead_modules_table).where(user_lead_modules_table.c.user_id == user_id).values(**values))
    else:
        await db.execute(insert(user_lead_modules_table).values(**values))

    add_audit(db, current_admin, "save_lead_module", "user_lead_modules", user_id, f"is_enabled={is_enabled}")
    await db.commit()
    row = await db.execute(select(user_lead_modules_table).where(user_lead_modules_table.c.user_id == user_id))
    return ApiResponse.ok(lead_module_out(row.mappings().first()))


@router.post("/users/{user_id}/credit-adjustments", response_model=ApiResponse[dict])
async def credit_adjustment(
    user_id: int,
    payload: CreditAdjustmentRequest,
    db: AsyncSession = Depends(get_db),
    current_admin: AdminUser = Depends(require_admin_roles(AdminRole.super_admin, AdminRole.finance)),
) -> ApiResponse[dict]:
    reason = payload.reason.strip()
    if not reason:
        raise AppException(code=40001, message="人工调整必须填写原因")
    delta = payload.delta
    if delta == 0:
        raise AppException(code=40001, message="调整积分不能为 0")
    result = await adjust_user_credit(
        db,
        user_id=user_id,
        delta=delta,
        reason=reason,
        client_idempotency_key=payload.idempotency_key,
        admin=current_admin,
    )
    return ApiResponse.ok(result.as_dict())


@router.post("/users/{user_id}/team-entitlements", response_model=ApiResponse[dict])
async def grant_team_entitlement(
    user_id: int,
    payload: TeamEntitlementGrantRequest,
    db: AsyncSession = Depends(get_db),
    current_admin: AdminUser = Depends(require_admin_roles(AdminRole.super_admin, AdminRole.operator)),
) -> ApiResponse[dict]:
    user = (
        await db.execute(
            select(users_table.c.id, users_table.c.site_id).where(
                users_table.c.id == user_id,
                users_table.c.deleted_at.is_(None),
                scoped_user_condition(current_admin),
            )
        )
    ).first()
    if user is None:
        raise AppException(code=40404, message="用户不存在", status_code=404)

    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(days=payload.duration_days) if payload.duration_days else None
    source_reference = f"admin-grant:{current_admin.id}:{user_id}:{uuid4().hex}"
    result = await db.execute(
        insert(team_entitlements_table)
        .values(
            site_id=int(user.site_id or 1),
            owner_user_id=user_id,
            seat_count=payload.seat_count,
            source="admin_grant",
            source_reference=source_reference,
            status="active",
            starts_at=now,
            expires_at=expires_at,
            note=payload.reason.strip(),
            created_by_admin_id=current_admin.id,
        )
        .returning(
            team_entitlements_table.c.id,
            team_entitlements_table.c.seat_count,
            team_entitlements_table.c.expires_at,
            team_entitlements_table.c.created_at,
        )
    )
    entitlement = result.first()
    add_audit(
        db,
        current_admin,
        "grant_team_entitlement",
        "team_entitlements",
        entitlement.id if entitlement else "pending",
        f"user_id={user_id}; seats={payload.seat_count}; duration_days={payload.duration_days}; reason={payload.reason.strip()}",
    )
    await db.commit()
    return ApiResponse.ok(
        {
            "id": entitlement.id if entitlement else None,
            "user_id": user_id,
            "seat_count": entitlement.seat_count if entitlement else payload.seat_count,
            "expires_at": iso(entitlement.expires_at) if entitlement else iso(expires_at),
            "created_at": iso(entitlement.created_at) if entitlement else iso(now),
        },
        "团队权益已开通",
    )


@router.get("/credits/ledger", response_model=ApiResponse[dict])
async def credit_ledger(
    keyword: str = "",
    page_no: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_admin: AdminUser = Depends(require_admin_roles(AdminRole.super_admin, AdminRole.finance)),
) -> ApiResponse[dict]:
    joined = outerjoin(credit_ledger_table, users_table, credit_ledger_table.c.user_id == users_table.c.id)
    condition = scoped_user_condition(current_admin)
    if keyword:
        like = f"%{keyword.strip()}%"
        condition = and_(
            condition,
            or_(
                users_table.c.username.ilike(like),
                credit_ledger_table.c.biz_type.ilike(like),
                credit_ledger_table.c.biz_id.cast(String).ilike(like),
            ),
        )
    try:
        total = await db.scalar(select(func.count()).select_from(joined).where(condition))
        result = await db.execute(
            select(
                credit_ledger_table.c.id,
                users_table.c.username,
                credit_ledger_table.c.direction,
                credit_ledger_table.c.amount,
                credit_ledger_table.c.balance_after,
                credit_ledger_table.c.biz_type,
                credit_ledger_table.c.biz_id,
                credit_ledger_table.c.description,
                credit_ledger_table.c.is_flagged,
                credit_ledger_table.c.flag_reason,
                credit_ledger_table.c.created_at,
            )
            .select_from(joined)
            .where(condition)
            .order_by(desc(credit_ledger_table.c.created_at))
            .limit(page_size)
            .offset((page_no - 1) * page_size)
        )
    except (OperationalError, ProgrammingError) as error:
        await db.rollback()
        if is_missing_shared_table_error(error, "credit_ledger"):
            return ApiResponse.ok(page([], page_no, page_size))
        raise
    items = [
        {
            "id": row.id,
            "username": row.username or "-",
            "biz_type": row.biz_type,
            "change_amount": row.amount if row.direction == "credit" else -row.amount,
            "balance_after": row.balance_after,
            "related_no": row.biz_id,
            "reason": row.description,
            "flag_reason": row.flag_reason,
            "is_flagged": bool(row.is_flagged),
            "created_at": iso(row.created_at),
        }
        for row in result
    ]
    return ApiResponse.ok({"items": items, "total": total or 0, "page": page_no, "page_size": page_size})


@router.post("/credits/ledger/{ledger_id}/mark", response_model=ApiResponse[dict])
async def mark_ledger(
    ledger_id: int,
    payload: dict,
    db: AsyncSession = Depends(get_db),
    current_admin: AdminUser = Depends(require_admin_roles(AdminRole.super_admin, AdminRole.finance)),
) -> ApiResponse[dict]:
    reason = str(payload.get("reason") or "").strip()
    if not reason:
        raise AppException(code=40001, message="标记异常必须填写原因")
    result = await db.execute(
        update(credit_ledger_table)
        .where(
            credit_ledger_table.c.id == ledger_id,
            credit_ledger_table.c.user_id.in_(select(users_table.c.id).where(scoped_user_condition(current_admin))),
        )
        .values(
            is_flagged=True,
            flag_reason=reason,
            flagged_by=current_admin.id,
            flagged_at=datetime.now(timezone.utc),
        )
    )
    if result.rowcount == 0:
        raise AppException(code=40401, message="积分流水不存在")
    add_audit(db, current_admin, "mark_credit_ledger", "credit_ledger", ledger_id, reason)
    await db.commit()
    return ApiResponse.ok({"id": ledger_id, "marked": True, **payload})


@router.get("/invite/reward-config", response_model=ApiResponse[dict])
async def invite_reward_config(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_admin: AdminUser = Depends(require_admin_roles(AdminRole.super_admin, AdminRole.operator, AdminRole.finance)),
) -> ApiResponse[dict]:
    site_id = await current_admin_config_site_id(db, request, current_admin)
    try:
        row = await db.execute(select(invite_reward_configs_table).where(invite_reward_configs_table.c.site_id == site_id))
        return ApiResponse.ok(invite_reward_config_out(row.mappings().first()))
    except (OperationalError, ProgrammingError) as error:
        await db.rollback()
        if is_missing_shared_table_error(error, "invite_reward_configs"):
            return ApiResponse.ok(default_invite_reward_config())
        raise


@router.patch("/invite/reward-config", response_model=ApiResponse[dict])
async def update_invite_reward_config(
    payload: dict,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_admin: AdminUser = Depends(require_admin_roles(AdminRole.super_admin, AdminRole.operator, AdminRole.finance)),
) -> ApiResponse[dict]:
    site_id = await current_admin_config_site_id(db, request, current_admin)
    valid_user_reward_credits = int(payload.get("valid_user_reward_credits") or 0)
    recharge_reward_percent = int(payload.get("recharge_reward_percent") or 0)
    if valid_user_reward_credits < 0:
        raise AppException(code=40001, message="有效用户奖励积分不能小于 0")
    if recharge_reward_percent < 0 or recharge_reward_percent > 100:
        raise AppException(code=40001, message="后续充值奖励比例必须在 0 到 100 之间")

    values = {
        "id": 1,
        "site_id": site_id,
        "is_enabled": bool(payload.get("is_enabled")),
        "valid_user_reward_credits": valid_user_reward_credits,
        "recharge_reward_percent": recharge_reward_percent,
        "valid_user_rule": "invited_user_first_paid_recharge",
        "updated_by": current_admin.id,
        "updated_at": func.now(),
    }
    try:
        existing_id = await db.scalar(select(invite_reward_configs_table.c.id).where(invite_reward_configs_table.c.site_id == site_id))
        if existing_id:
            await db.execute(
                update(invite_reward_configs_table)
                .where(invite_reward_configs_table.c.site_id == site_id)
                .values(
                    is_enabled=values["is_enabled"],
                    valid_user_reward_credits=values["valid_user_reward_credits"],
                    recharge_reward_percent=values["recharge_reward_percent"],
                    valid_user_rule=values["valid_user_rule"],
                    updated_by=values["updated_by"],
                    updated_at=values["updated_at"],
                )
            )
        else:
            next_id = await db.scalar(select(func.coalesce(func.max(invite_reward_configs_table.c.id), 0) + 1))
            values["id"] = int(next_id or 1)
            await db.execute(insert(invite_reward_configs_table).values(**values))
    except (OperationalError, ProgrammingError) as error:
        await db.rollback()
        if is_missing_shared_table_error(error, "invite_reward_configs"):
            raise AppException(code=50001, message="邀请奖励配置表未迁移", status_code=500) from None
        raise
    add_audit(db, current_admin, "update_invite_reward_config", "invite_reward_configs", site_id, "更新邀请奖励配置")
    await db.commit()
    row = await db.execute(select(invite_reward_configs_table).where(invite_reward_configs_table.c.site_id == site_id))
    return ApiResponse.ok(invite_reward_config_out(row.mappings().first()))


@router.get("/rewards/signin-config", response_model=ApiResponse[dict])
async def signin_reward_config(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_admin: AdminUser = Depends(require_admin_roles(AdminRole.super_admin, AdminRole.operator, AdminRole.finance)),
) -> ApiResponse[dict]:
    site_id = await current_admin_config_site_id(db, request, current_admin)
    try:
        row = await db.execute(select(signin_reward_configs_table).where(signin_reward_configs_table.c.site_id == site_id))
        return ApiResponse.ok(signin_reward_config_out(row.mappings().first()))
    except (OperationalError, ProgrammingError) as error:
        await db.rollback()
        if is_missing_shared_table_error(error, "signin_reward_configs"):
            return ApiResponse.ok(default_signin_reward_config())
        raise


@router.patch("/rewards/signin-config", response_model=ApiResponse[dict])
async def update_signin_reward_config(
    payload: dict,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_admin: AdminUser = Depends(require_admin_roles(AdminRole.super_admin, AdminRole.operator, AdminRole.finance)),
) -> ApiResponse[dict]:
    site_id = await current_admin_config_site_id(db, request, current_admin)
    daily_credits = int(payload.get("daily_credits") or 0)
    if daily_credits < 0:
        raise AppException(code=40001, message="每日签到积分不能小于 0")
    if bool(payload.get("is_enabled")) and daily_credits <= 0:
        raise AppException(code=40001, message="开启签到前必须配置大于 0 的每日积分")

    values = {
        "id": 1,
        "site_id": site_id,
        "is_enabled": bool(payload.get("is_enabled")),
        "daily_credits": daily_credits,
        "updated_by": current_admin.id,
        "updated_at": func.now(),
    }
    try:
        existing_id = await db.scalar(select(signin_reward_configs_table.c.id).where(signin_reward_configs_table.c.site_id == site_id))
        if existing_id:
            await db.execute(
                update(signin_reward_configs_table)
                .where(signin_reward_configs_table.c.site_id == site_id)
                .values(
                    is_enabled=values["is_enabled"],
                    daily_credits=values["daily_credits"],
                    updated_by=values["updated_by"],
                    updated_at=values["updated_at"],
                )
            )
        else:
            next_id = await db.scalar(select(func.coalesce(func.max(signin_reward_configs_table.c.id), 0) + 1))
            values["id"] = int(next_id or 1)
            await db.execute(insert(signin_reward_configs_table).values(**values))
    except (OperationalError, ProgrammingError) as error:
        await db.rollback()
        if is_missing_shared_table_error(error, "signin_reward_configs"):
            raise AppException(code=50001, message="签到奖励配置表未迁移", status_code=500) from None
        raise
    add_audit(db, current_admin, "update_signin_reward_config", "signin_reward_configs", site_id, "更新签到奖励配置")
    await db.commit()
    row = await db.execute(select(signin_reward_configs_table).where(signin_reward_configs_table.c.site_id == site_id))
    return ApiResponse.ok(signin_reward_config_out(row.mappings().first()))


@router.get("/user-experience/config", response_model=ApiResponse[dict])
async def user_experience_config(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_admin: AdminUser = Depends(require_admin_roles(AdminRole.super_admin, AdminRole.operator, AdminRole.model_admin)),
) -> ApiResponse[dict]:
    site_id = await current_admin_config_site_id(db, request, current_admin)
    try:
        row = await db.execute(select(user_experience_configs_table).where(user_experience_configs_table.c.site_id == site_id))
        return ApiResponse.ok(user_experience_config_out(row.mappings().first()))
    except (OperationalError, ProgrammingError) as error:
        await db.rollback()
        if is_missing_shared_table_error(error, "user_experience_configs"):
            return ApiResponse.ok(default_user_experience_config())
        raise


@router.patch("/user-experience/config", response_model=ApiResponse[dict])
async def update_user_experience_config(
    payload: dict,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_admin: AdminUser = Depends(require_admin_roles(AdminRole.super_admin, AdminRole.operator, AdminRole.model_admin)),
) -> ApiResponse[dict]:
    site_id = await current_admin_config_site_id(db, request, current_admin)
    max_batch_tasks = int(payload.get("max_batch_tasks") or 0)
    if max_batch_tasks < 1:
        raise AppException(code=40001, message="单次批量任务上限至少为 1")
    if max_batch_tasks > 20000:
        raise AppException(code=40001, message="单次批量任务上限不能超过 20000")
    qiniu_storage_enabled = bool(payload.get("qiniu_storage_enabled") or False)

    values = {
        "id": 1,
        "site_id": site_id,
        "max_batch_tasks": max_batch_tasks,
        "qiniu_storage_enabled": qiniu_storage_enabled,
        "updated_by": current_admin.id,
        "updated_at": func.now(),
    }
    try:
        existing_id = await db.scalar(
            select(user_experience_configs_table.c.id).where(user_experience_configs_table.c.site_id == site_id)
        )
        if existing_id:
            await db.execute(
                update(user_experience_configs_table)
                .where(user_experience_configs_table.c.site_id == site_id)
                .values(
                    max_batch_tasks=values["max_batch_tasks"],
                    qiniu_storage_enabled=values["qiniu_storage_enabled"],
                    updated_by=values["updated_by"],
                    updated_at=values["updated_at"],
                )
            )
        else:
            next_id = await db.scalar(select(func.coalesce(func.max(user_experience_configs_table.c.id), 0) + 1))
            values["id"] = int(next_id or 1)
            await db.execute(insert(user_experience_configs_table).values(**values))
    except (OperationalError, ProgrammingError) as error:
        await db.rollback()
        if is_missing_shared_table_error(error, "user_experience_configs"):
            raise AppException(code=50001, message="用户体验配置表未迁移", status_code=500) from None
        raise
    add_audit(db, current_admin, "update_user_experience_config", "user_experience_configs", site_id, "更新用户体验配置")
    await db.commit()
    row = await db.execute(select(user_experience_configs_table).where(user_experience_configs_table.c.site_id == site_id))
    return ApiResponse.ok(user_experience_config_out(row.mappings().first()))


@router.get("/feedbacks", response_model=ApiResponse[dict])
async def feedbacks(
    keyword: str = "",
    status: str = "all",
    page_no: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_admin: AdminUser = Depends(require_admin_roles(AdminRole.super_admin, AdminRole.operator)),
) -> ApiResponse[dict]:
    joined = outerjoin(feedbacks_table, users_table, feedbacks_table.c.user_id == users_table.c.id)
    condition = scoped_user_condition(current_admin)
    if status != "all":
        condition = and_(condition, feedbacks_table.c.status == status)
    if keyword.strip():
        like = f"%{keyword.strip()}%"
        condition = and_(
            condition,
            or_(
                feedbacks_table.c.description.ilike(like),
                users_table.c.username.ilike(like),
                users_table.c.email.ilike(like),
                feedbacks_table.c.id.cast(String).ilike(like),
            ),
        )
    total = await db.scalar(select(func.count()).select_from(joined).where(condition))
    result = await db.execute(
        select(
            feedbacks_table.c.id,
            feedbacks_table.c.user_id,
            users_table.c.username,
            users_table.c.email,
            feedbacks_table.c.description,
            feedbacks_table.c.image_urls,
            feedbacks_table.c.status,
            feedbacks_table.c.admin_remark,
            feedbacks_table.c.handled_by,
            feedbacks_table.c.handled_at,
            feedbacks_table.c.created_at,
            feedbacks_table.c.updated_at,
        )
        .select_from(joined)
        .where(condition)
        .order_by(desc(feedbacks_table.c.created_at), desc(feedbacks_table.c.id))
        .offset((page_no - 1) * page_size)
        .limit(page_size)
    )
    return ApiResponse.ok({"items": [feedback_out(row) for row in result], "total": total or 0, "page": page_no, "page_size": page_size})


@router.patch("/feedbacks/{feedback_id}", response_model=ApiResponse[dict])
async def update_feedback(
    feedback_id: int,
    payload: FeedbackStatusRequest,
    db: AsyncSession = Depends(get_db),
    current_admin: AdminUser = Depends(require_admin_roles(AdminRole.super_admin, AdminRole.operator)),
) -> ApiResponse[dict]:
    existing_id = await db.scalar(
        select(feedbacks_table.c.id)
        .select_from(outerjoin(feedbacks_table, users_table, feedbacks_table.c.user_id == users_table.c.id))
        .where(feedbacks_table.c.id == feedback_id, scoped_user_condition(current_admin))
    )
    if existing_id is None:
        raise AppException(code=404, message="用户反馈不存在", status_code=404)
    now = datetime.now(timezone.utc)
    await db.execute(
        update(feedbacks_table)
        .where(feedbacks_table.c.id == feedback_id, scoped_condition(current_admin, feedbacks_table.c.site_id))
        .values(
            status=payload.status,
            admin_remark=payload.admin_remark.strip(),
            handled_by=current_admin.id,
            handled_at=now,
            updated_at=now,
        )
    )
    add_audit(db, current_admin, "update_user_feedback", "user_feedbacks", feedback_id, f"status={payload.status}")
    await db.commit()
    joined = outerjoin(feedbacks_table, users_table, feedbacks_table.c.user_id == users_table.c.id)
    row = (
        await db.execute(
            select(
                feedbacks_table.c.id,
                feedbacks_table.c.user_id,
                users_table.c.username,
                users_table.c.email,
                feedbacks_table.c.description,
                feedbacks_table.c.image_urls,
                feedbacks_table.c.status,
                feedbacks_table.c.admin_remark,
                feedbacks_table.c.handled_by,
                feedbacks_table.c.handled_at,
                feedbacks_table.c.created_at,
                feedbacks_table.c.updated_at,
            )
            .select_from(joined)
            .where(feedbacks_table.c.id == feedback_id, scoped_user_condition(current_admin))
        )
    ).first()
    return ApiResponse.ok(feedback_out(row), "用户反馈已更新")


@router.get("/lead-trial-applications", response_model=ApiResponse[dict])
async def lead_trial_applications(
    keyword: str = "",
    status: str = "all",
    page_no: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_admin: AdminUser = Depends(require_admin_roles(AdminRole.super_admin, AdminRole.operator)),
) -> ApiResponse[dict]:
    joined = outerjoin(lead_trial_applications_table, users_table, lead_trial_applications_table.c.user_id == users_table.c.id)
    joined = outerjoin(joined, credit_accounts_table, users_table.c.id == credit_accounts_table.c.user_id)
    joined = outerjoin(joined, user_lead_modules_table, users_table.c.id == user_lead_modules_table.c.user_id)
    condition = scoped_user_condition(current_admin)
    if status != "all":
        condition = and_(condition, lead_trial_applications_table.c.status == status)
    if keyword.strip():
        like = f"%{keyword.strip()}%"
        condition = and_(
            condition,
            or_(
                lead_trial_applications_table.c.business_scope.ilike(like),
                lead_trial_applications_table.c.keywords.ilike(like),
                lead_trial_applications_table.c.competitor_accounts.ilike(like),
                lead_trial_applications_table.c.contact_info.ilike(like),
                users_table.c.username.ilike(like),
                users_table.c.email.ilike(like),
                lead_trial_applications_table.c.id.cast(String).ilike(like),
            ),
        )
    try:
        total = await db.scalar(select(func.count()).select_from(joined).where(condition))
        result = await db.execute(
            select(
                lead_trial_applications_table.c.id,
                lead_trial_applications_table.c.user_id,
                users_table.c.username,
                users_table.c.email,
                users_table.c.is_active,
                users_table.c.is_internal,
                func.coalesce(credit_accounts_table.c.balance, 0).label("credit_balance"),
                user_lead_modules_table.c.is_enabled.label("lead_module_enabled"),
                lead_trial_applications_table.c.business_scope,
                lead_trial_applications_table.c.keywords,
                lead_trial_applications_table.c.competitor_accounts,
                lead_trial_applications_table.c.contact_info,
                lead_trial_applications_table.c.status,
                lead_trial_applications_table.c.admin_remark,
                lead_trial_applications_table.c.handled_by_admin_id,
                lead_trial_applications_table.c.handled_at,
                lead_trial_applications_table.c.created_at,
                lead_trial_applications_table.c.updated_at,
            )
            .select_from(joined)
            .where(condition)
            .order_by(desc(lead_trial_applications_table.c.created_at), desc(lead_trial_applications_table.c.id))
            .offset((page_no - 1) * page_size)
            .limit(page_size)
        )
    except (OperationalError, ProgrammingError) as error:
        await db.rollback()
        if is_missing_shared_table_error(error, "lead_trial_applications"):
            raise AppException(code=50001, message="客资申请表未迁移", status_code=500) from None
        raise
    return ApiResponse.ok({"items": [lead_trial_application_out(row) for row in result], "total": total or 0, "page": page_no, "page_size": page_size})


@router.patch("/lead-trial-applications/{application_id}", response_model=ApiResponse[dict])
async def update_lead_trial_application(
    application_id: int,
    payload: LeadTrialApplicationStatusRequest,
    db: AsyncSession = Depends(get_db),
    current_admin: AdminUser = Depends(require_admin_roles(AdminRole.super_admin, AdminRole.operator)),
) -> ApiResponse[dict]:
    existing_id = await db.scalar(
        select(lead_trial_applications_table.c.id)
        .select_from(outerjoin(lead_trial_applications_table, users_table, lead_trial_applications_table.c.user_id == users_table.c.id))
        .where(lead_trial_applications_table.c.id == application_id, scoped_user_condition(current_admin))
    )
    if existing_id is None:
        raise AppException(code=404, message="客资申请不存在", status_code=404)
    now = datetime.now(timezone.utc)
    await db.execute(
        update(lead_trial_applications_table)
        .where(lead_trial_applications_table.c.id == application_id, scoped_condition(current_admin, lead_trial_applications_table.c.site_id))
        .values(
            status=payload.status,
            admin_remark=payload.admin_remark.strip(),
            handled_by_admin_id=current_admin.id,
            handled_at=now,
            updated_at=now,
        )
    )
    add_audit(db, current_admin, "update_lead_trial_application", "lead_trial_applications", application_id, f"status={payload.status}")
    await db.commit()

    joined = outerjoin(lead_trial_applications_table, users_table, lead_trial_applications_table.c.user_id == users_table.c.id)
    joined = outerjoin(joined, credit_accounts_table, users_table.c.id == credit_accounts_table.c.user_id)
    joined = outerjoin(joined, user_lead_modules_table, users_table.c.id == user_lead_modules_table.c.user_id)
    row = (
        await db.execute(
            select(
                lead_trial_applications_table.c.id,
                lead_trial_applications_table.c.user_id,
                users_table.c.username,
                users_table.c.email,
                users_table.c.is_active,
                users_table.c.is_internal,
                func.coalesce(credit_accounts_table.c.balance, 0).label("credit_balance"),
                user_lead_modules_table.c.is_enabled.label("lead_module_enabled"),
                lead_trial_applications_table.c.business_scope,
                lead_trial_applications_table.c.keywords,
                lead_trial_applications_table.c.competitor_accounts,
                lead_trial_applications_table.c.contact_info,
                lead_trial_applications_table.c.status,
                lead_trial_applications_table.c.admin_remark,
                lead_trial_applications_table.c.handled_by_admin_id,
                lead_trial_applications_table.c.handled_at,
                lead_trial_applications_table.c.created_at,
                lead_trial_applications_table.c.updated_at,
            )
            .select_from(joined)
            .where(lead_trial_applications_table.c.id == application_id, scoped_user_condition(current_admin))
        )
    ).first()
    return ApiResponse.ok(lead_trial_application_out(row), "客资申请已更新")


@router.get("/rewards/signin-records", response_model=ApiResponse[dict])
async def signin_records(
    keyword: str = "",
    page_no: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_admin: AdminUser = Depends(require_admin_roles(AdminRole.super_admin, AdminRole.operator, AdminRole.finance)),
) -> ApiResponse[dict]:
    joined = outerjoin(signin_records_table, users_table, signin_records_table.c.user_id == users_table.c.id)
    condition = scoped_user_condition(current_admin)
    if keyword:
        like = f"%{keyword.strip()}%"
        condition = or_(users_table.c.username.ilike(like), users_table.c.email.ilike(like))
    try:
        total = await db.scalar(select(func.count()).select_from(joined).where(condition))
        rows = await db.execute(
            select(
                signin_records_table.c.id,
                signin_records_table.c.user_id,
                users_table.c.username,
                users_table.c.email,
                signin_records_table.c.sign_date,
                signin_records_table.c.awarded_credits,
                signin_records_table.c.streak_days,
                signin_records_table.c.created_at,
            )
            .select_from(joined)
            .where(condition)
            .order_by(desc(signin_records_table.c.created_at))
            .limit(page_size)
            .offset((page_no - 1) * page_size)
        )
    except (OperationalError, ProgrammingError) as error:
        await db.rollback()
        if is_missing_shared_table_error(error, "user_signin_records"):
            return ApiResponse.ok({"items": [], "total": 0, "page": page_no, "page_size": page_size})
        raise

    items = [
        {
            "id": row.id,
            "user_id": row.user_id,
            "username": row.username or "-",
            "email": row.email or "-",
            "sign_date": row.sign_date.isoformat() if row.sign_date else "",
            "awarded_credits": row.awarded_credits,
            "streak_days": row.streak_days,
            "created_at": iso(row.created_at),
        }
        for row in rows.mappings()
    ]
    return ApiResponse.ok({"items": items, "total": total or 0, "page": page_no, "page_size": page_size})


@router.get("/agent/config", response_model=ApiResponse[dict])
async def agent_config(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_admin: AdminUser = Depends(require_admin_roles(AdminRole.super_admin, AdminRole.operator, AdminRole.finance)),
) -> ApiResponse[dict]:
    site_id = await current_admin_config_site_id(db, request, current_admin)
    try:
        row = await db.execute(select(agent_configs_table).where(agent_configs_table.c.site_id == site_id))
        return ApiResponse.ok(agent_config_out(row.mappings().first()))
    except (OperationalError, ProgrammingError) as error:
        await db.rollback()
        if is_missing_shared_table_error(error, "agent_configs"):
            return ApiResponse.ok(default_agent_config())
        raise


@router.get("/payment/zpay-config", response_model=ApiResponse[dict])
async def zpay_config(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_admin: AdminUser = Depends(require_admin_roles(AdminRole.super_admin, AdminRole.finance)),
) -> ApiResponse[dict]:
    site_id = await current_admin_config_site_id(db, request, current_admin)
    try:
        row = await db.execute(select(payment_configs_table).where(payment_configs_table.c.site_id == site_id, payment_configs_table.c.provider == "zpay"))
        return ApiResponse.ok(zpay_config_out(row.mappings().first()))
    except (OperationalError, ProgrammingError) as error:
        await db.rollback()
        if is_missing_shared_table_error(error, "payment_configs"):
            return ApiResponse.ok(default_zpay_config())
        raise


@router.patch("/payment/zpay-config", response_model=ApiResponse[dict])
async def update_zpay_config(
    payload: ZPayConfigRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_admin: AdminUser = Depends(require_admin_roles(AdminRole.super_admin, AdminRole.finance)),
) -> ApiResponse[dict]:
    site_id = await current_admin_config_site_id(db, request, current_admin)
    existing = None
    try:
        result = await db.execute(select(payment_configs_table).where(payment_configs_table.c.site_id == site_id, payment_configs_table.c.provider == "zpay"))
        existing = result.mappings().first()
        existing_pkey = existing.get("pkey") if existing else ""
        pkey = payload.pkey.strip()
        pid = payload.pid.strip()
        api_base = payload.api_base.strip().rstrip("/")
        notify_url = payload.notify_url.strip()
        return_url = payload.return_url.strip()
        if payload.is_enabled and (not pid or not (pkey or existing_pkey) or not api_base or not notify_url or not return_url):
            raise AppException(code=40001, message="开启 ZPay 前必须填写商户 ID、商户密钥、网关地址、异步通知地址和同步返回地址")

        values = {
            "id": 1,
            "site_id": site_id,
            "provider": "zpay",
            "is_enabled": payload.is_enabled,
            "pid": pid,
            "api_base": api_base,
            "notify_url": notify_url,
            "return_url": return_url,
            "payment_type": payload.payment_type,
            "payment_mode": payload.payment_mode,
            "timeout_seconds": payload.timeout_seconds,
            "order_expire_minutes": payload.order_expire_minutes,
            "updated_by": current_admin.id,
            "updated_at": func.now(),
        }
        if pkey:
            values["pkey"] = pkey
        elif existing is None:
            values["pkey"] = ""

        if existing:
            await db.execute(update(payment_configs_table).where(payment_configs_table.c.site_id == site_id, payment_configs_table.c.provider == "zpay").values(**{k: v for k, v in values.items() if k != "id"}))
        else:
            next_id = await db.scalar(select(func.coalesce(func.max(payment_configs_table.c.id), 0) + 1))
            values["id"] = int(next_id or 1)
            await db.execute(insert(payment_configs_table).values(**values))
    except (OperationalError, ProgrammingError) as error:
        await db.rollback()
        if is_missing_shared_table_error(error, "payment_configs"):
            raise AppException(code=50001, message="支付配置表未迁移", status_code=500) from None
        raise
    add_audit(db, current_admin, "update_zpay_config", "payment_configs", "zpay", "更新 ZPay 支付配置")
    await db.commit()
    row = await db.execute(select(payment_configs_table).where(payment_configs_table.c.site_id == site_id, payment_configs_table.c.provider == "zpay"))
    return ApiResponse.ok(zpay_config_out(row.mappings().first()))


@router.patch("/agent/config", response_model=ApiResponse[dict])
async def update_agent_config(
    payload: dict,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_admin: AdminUser = Depends(require_admin_roles(AdminRole.super_admin, AdminRole.operator, AdminRole.finance)),
) -> ApiResponse[dict]:
    site_id = await current_admin_config_site_id(db, request, current_admin)
    base_url = str(payload.get("base_url") or "").strip().rstrip("/")
    admin_api_key = str(payload.get("admin_api_key") or "").strip()
    credit_to_agent_rate = float(payload.get("credit_to_agent_rate") or 0)
    if credit_to_agent_rate <= 0:
        raise AppException(code=40001, message="积分兑换比例必须大于 0")
    if not credit_to_agent_rate.is_integer():
        raise AppException(code=40001, message="积分兑换比例必须是正整数")
    if bool(payload.get("image_billing_enabled")) and not bool(payload.get("is_enabled")):
        raise AppException(code=40001, message="开启统一余额计费前必须先开启 Agent 功能")

    existing = None
    try:
        row = await db.execute(select(agent_configs_table).where(agent_configs_table.c.site_id == site_id))
        existing = row.mappings().first()
        existing_admin_api_key = (existing or {}).get("admin_api_key") if existing else ""
        if bool(payload.get("is_enabled")) and (not base_url or (not admin_api_key and not existing_admin_api_key)):
            raise AppException(code=40001, message="开启 Agent 前必须配置 Base URL 和管理员 Key")
        values = {
            "id": 1,
            "site_id": site_id,
            "is_enabled": bool(payload.get("is_enabled")),
            "image_billing_enabled": bool(payload.get("image_billing_enabled")),
            "base_url": base_url,
            "credit_to_agent_rate": int(credit_to_agent_rate),
            "text_group_id": int(payload["text_group_id"]) if payload.get("text_group_id") not in (None, "") else None,
            "image_group_id": int(payload["image_group_id"]) if payload.get("image_group_id") not in (None, "") else None,
            "create_api_key_path": "",
            "user_concurrency": int(payload.get("user_concurrency") if payload.get("user_concurrency") not in (None, "") else 5),
            "user_rpm_limit": int(payload.get("user_rpm_limit") or 0),
            "updated_by": current_admin.id,
            "updated_at": func.now(),
        }
        if admin_api_key:
            values["admin_api_key"] = admin_api_key
        elif existing is None:
            values["admin_api_key"] = ""

        if existing:
            await db.execute(update(agent_configs_table).where(agent_configs_table.c.site_id == site_id).values(**{k: v for k, v in values.items() if k != "id"}))
        else:
            next_id = await db.scalar(select(func.coalesce(func.max(agent_configs_table.c.id), 0) + 1))
            values["id"] = int(next_id or 1)
            await db.execute(insert(agent_configs_table).values(**values))
    except (OperationalError, ProgrammingError) as error:
        await db.rollback()
        if is_missing_shared_table_error(error, "agent_configs"):
            raise AppException(code=50001, message="Agent 配置表未迁移", status_code=500) from None
        raise
    add_audit(db, current_admin, "update_agent_config", "agent_configs", site_id, "更新 Agent 配置")
    await db.commit()
    row = await db.execute(select(agent_configs_table).where(agent_configs_table.c.site_id == site_id))
    return ApiResponse.ok(agent_config_out(row.mappings().first()))


@router.post("/agent/groups", response_model=ApiResponse[list[dict]])
async def agent_groups(
    payload: AgentGroupsRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_admin: AdminUser = Depends(require_admin_roles(AdminRole.super_admin, AdminRole.operator, AdminRole.finance)),
) -> ApiResponse[list[dict]]:
    base_url = payload.base_url.strip().rstrip("/")
    admin_api_key = payload.admin_api_key.strip()
    stored_config = None
    if not admin_api_key:
        try:
            site_id = await current_admin_config_site_id(db, request, current_admin)
            row = await db.execute(select(agent_configs_table).where(agent_configs_table.c.site_id == site_id))
            stored_config = row.mappings().first()
        except (OperationalError, ProgrammingError) as error:
            await db.rollback()
            if not is_missing_shared_table_error(error, "agent_configs"):
                raise
    base_url, admin_api_key = resolve_agent_group_credentials(base_url, admin_api_key, stored_config)
    groups = await asyncio.to_thread(fetch_agent_groups, base_url, admin_api_key)
    return ApiResponse.ok(groups)


@router.get("/agent/accounts", response_model=ApiResponse[dict])
async def agent_accounts(
    keyword: str = "",
    page_no: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_admin: AdminUser = Depends(require_admin_roles(AdminRole.super_admin, AdminRole.operator, AdminRole.finance)),
) -> ApiResponse[dict]:
    joined = outerjoin(user_agent_accounts_table, users_table, user_agent_accounts_table.c.user_id == users_table.c.id)
    condition = scoped_user_condition(current_admin)
    if keyword:
        like = f"%{keyword.strip()}%"
        condition = and_(
            condition,
            or_(
                users_table.c.username.ilike(like),
                users_table.c.email.ilike(like),
                user_agent_accounts_table.c.agent_email.ilike(like),
                user_agent_accounts_table.c.agent_user_id.cast(String).ilike(like),
            ),
        )
    try:
        total = await db.scalar(select(func.count()).select_from(joined).where(condition))
        rows = await db.execute(
            select(
                user_agent_accounts_table.c.id,
                user_agent_accounts_table.c.user_id,
                users_table.c.username,
                users_table.c.email,
                user_agent_accounts_table.c.agent_user_id,
                user_agent_accounts_table.c.agent_email,
                user_agent_accounts_table.c.status,
                user_agent_accounts_table.c.failure_message,
                user_agent_accounts_table.c.text_api_key,
                user_agent_accounts_table.c.image_api_key,
                user_agent_accounts_table.c.created_at,
            )
            .select_from(joined)
            .where(condition)
            .order_by(desc(user_agent_accounts_table.c.created_at))
            .limit(page_size)
            .offset((page_no - 1) * page_size)
        )
    except (OperationalError, ProgrammingError) as error:
        await db.rollback()
        if is_missing_shared_table_error(error, "user_agent_accounts"):
            return ApiResponse.ok(page([], page_no, page_size))
        raise
    return ApiResponse.ok(
        {
            "items": [
                {
                    "id": row.id,
                    "user_id": row.user_id,
                    "username": row.username or "-",
                    "email": row.email or "-",
                    "agent_user_id": row.agent_user_id,
                    "agent_email": row.agent_email or "-",
                    "status": row.status,
                    "failure_message": row.failure_message,
                    "text_api_key_masked": mask_secret(row.text_api_key),
                    "image_api_key_masked": mask_secret(row.image_api_key),
                    "created_at": iso(row.created_at),
                }
                for row in rows
            ],
            "total": total or 0,
            "page": page_no,
            "page_size": page_size,
        }
    )


@router.get("/agent/transfers", response_model=ApiResponse[dict])
async def agent_transfers(
    keyword: str = "",
    page_no: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_admin: AdminUser = Depends(require_admin_roles(AdminRole.super_admin, AdminRole.operator, AdminRole.finance)),
) -> ApiResponse[dict]:
    joined = outerjoin(agent_transfer_records_table, users_table, agent_transfer_records_table.c.user_id == users_table.c.id)
    condition = scoped_user_condition(current_admin)
    if keyword:
        like = f"%{keyword.strip()}%"
        condition = and_(condition, or_(users_table.c.username.ilike(like), users_table.c.email.ilike(like), agent_transfer_records_table.c.status.ilike(like)))
    try:
        total = await db.scalar(select(func.count()).select_from(joined).where(condition))
        rows = await db.execute(
            select(
                agent_transfer_records_table.c.id,
                users_table.c.username,
                users_table.c.email,
                agent_transfer_records_table.c.credit_amount,
                agent_transfer_records_table.c.agent_amount,
                agent_transfer_records_table.c.agent_user_id,
                agent_transfer_records_table.c.status,
                agent_transfer_records_table.c.failure_message,
                agent_transfer_records_table.c.created_at,
            )
            .select_from(joined)
            .where(condition)
            .order_by(desc(agent_transfer_records_table.c.created_at))
            .limit(page_size)
            .offset((page_no - 1) * page_size)
        )
    except (OperationalError, ProgrammingError) as error:
        await db.rollback()
        if is_missing_shared_table_error(error, "agent_transfer_records"):
            return ApiResponse.ok(page([], page_no, page_size))
        raise
    return ApiResponse.ok(
        {
            "items": [
                {
                    "id": row.id,
                    "username": row.username or "-",
                    "email": row.email or "-",
                    "credit_amount": row.credit_amount,
                    "agent_amount": float(row.agent_amount or 0),
                    "agent_user_id": row.agent_user_id,
                    "status": row.status,
                    "failure_message": row.failure_message,
                    "created_at": iso(row.created_at),
                }
                for row in rows
            ],
            "total": total or 0,
            "page": page_no,
            "page_size": page_size,
        }
    )


def recharge_plan_out(plan: RechargePlan) -> RechargePlanOut:
    return RechargePlanOut.model_validate(plan)


def mask_secret(value: str | None) -> str:
    if not value:
        return ""
    if len(value) <= 6:
        return "***"
    return f"{value[:2]}***{value[-2:]}"


def lead_module_out(row) -> dict:
    if row is None:
        return {"is_enabled": False}
    get_value = row.get if hasattr(row, "get") else lambda key, default=None: getattr(row, key, default)
    data = {
        "id": get_value("id"),
        "user_id": get_value("user_id"),
        "is_enabled": bool(get_value("is_enabled")),
        "enterprise_id": get_value("enterprise_id") or "",
        "enterprise_account": get_value("enterprise_account") or "",
        "credentials_revealed_at": iso(get_value("credentials_revealed_at")),
        "created_at": iso(get_value("created_at")),
        "updated_at": iso(get_value("updated_at")),
    }
    return data


def qiniu_urlsafe_base64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("utf-8")


def qiniu_upload_token(key: str) -> str:
    if not settings.qiniu_access_key or not settings.qiniu_secret_key or not settings.qiniu_bucket or not settings.qiniu_cdn_base_url:
        raise AppException(code=50040, message="七牛云上传配置未完成", status_code=500)
    deadline = int(time.time()) + 3600
    policy = {
        "scope": f"{settings.qiniu_bucket}:{key}",
        "deadline": deadline,
        "returnBody": json.dumps({"key": "$(key)", "hash": "$(etag)", "size": "$(fsize)", "name": "$(fname)"}, separators=(",", ":")),
    }
    encoded_policy = qiniu_urlsafe_base64(json.dumps(policy, separators=(",", ":")).encode("utf-8"))
    digest = hmac.new(settings.qiniu_secret_key.encode("utf-8"), encoded_policy.encode("utf-8"), hashlib.sha1).digest()
    encoded_sign = qiniu_urlsafe_base64(digest)
    return f"{settings.qiniu_access_key}:{encoded_sign}:{encoded_policy}"


def normalize_openagent_filename(filename: str) -> str:
    name = filename.strip().split("/")[-1].split("\\")[-1]
    safe = "".join(char if char.isalnum() or char in "._-" else "-" for char in name)
    if not safe or safe in {".", ".."}:
        raise AppException(code=40040, message="文件名无效")
    return safe


def normalize_material_filename(filename: str) -> str:
    return f"{int(time.time())}-{uuid4().hex[:10]}-{normalize_openagent_filename(filename)}"


def mask_url(value: str) -> str:
    return value.rstrip("/") + "/***"


def model_test_endpoints(base_url: str) -> list[str]:
    normalized = base_url.rstrip("/")
    endpoints = [f"{normalized}/images/generations"]
    if not normalized.endswith("/v1"):
        endpoints.append(f"{normalized}/v1/images/generations")
    return list(dict.fromkeys(endpoints))


def model_response_endpoint(base_url: str) -> str:
    normalized = base_url.rstrip("/")
    if normalized.endswith("/v1"):
        return f"{normalized}/responses"
    return f"{normalized}/v1/responses"


def model_chat_completions_endpoint(base_url: str) -> str:
    normalized = base_url.rstrip("/")
    if normalized.endswith("/v1"):
        return f"{normalized}/chat/completions"
    return f"{normalized}/v1/chat/completions"


def model_provider_kind(provider: ImageModelProvider) -> str:
    if (getattr(provider, "access_mode", "api") or "api") == "sdk":
        return "openai_chat_completions"
    provider_code = (provider.code or "").lower()
    provider_name = (provider.name or "").lower()
    base_url = (provider.base_url or "").lower()
    if "gemini" in provider_code or "google" in provider_code or "gemini" in provider_name or "generativelanguage.googleapis.com" in base_url:
        return "gemini"
    return "openai"



def resolve_provider_kind_from_config(
    *,
    provider_code: str = "",
    provider_name: str = "",
    base_url: str = "",
    access_mode: str = "api",
) -> str:
    if (access_mode or "api") == "sdk":
        return "openai"
    code = (provider_code or "").lower()
    name = (provider_name or "").lower()
    url = (base_url or "").lower()
    if (
        "gemini" in code
        or "google" in code
        or "gemini" in name
        or "generativelanguage.googleapis.com" in url
    ):
        return "gemini"
    return "openai"


def openai_models_endpoints(base_url: str) -> list[str]:
    normalized = (base_url or "").rstrip("/")
    if not normalized:
        return []
    endpoints = [f"{normalized}/models"]
    if not normalized.endswith("/v1"):
        endpoints.append(f"{normalized}/v1/models")
    return list(dict.fromkeys(endpoints))


def gemini_models_endpoint(base_url: str, api_key: str) -> str:
    normalized = (base_url or "").rstrip("/")
    if not normalized.endswith("/v1") and not normalized.endswith("/v1beta"):
        normalized = f"{normalized}/v1beta"
    return f"{normalized}/models?{urllib.parse.urlencode({'key': api_key, 'pageSize': 1000})}"


def normalize_discovered_model_id(value: str) -> str:
    raw = (value or "").strip()
    if raw.startswith("models/"):
        return raw[len("models/"):]
    return raw


def parse_openai_models_payload(payload: dict | list) -> list[dict]:
    rows = payload.get("data") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        return []
    items: list[dict] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        model_id = normalize_discovered_model_id(str(row.get("id") or row.get("model") or "").strip())
        if not model_id or model_id in seen:
            continue
        seen.add(model_id)
        label = str(row.get("name") or model_id).strip() or model_id
        items.append({"id": model_id, "name": label})
    items.sort(key=lambda item: item["id"])
    return items


def parse_gemini_models_payload(payload: dict) -> list[dict]:
    rows = payload.get("models") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return []
    items: list[dict] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        model_id = normalize_discovered_model_id(str(row.get("name") or row.get("id") or "").strip())
        if not model_id or model_id in seen:
            continue
        seen.add(model_id)
        label = str(row.get("displayName") or row.get("description") or model_id).strip() or model_id
        items.append({"id": model_id, "name": label})
    items.sort(key=lambda item: item["id"])
    return items


def list_provider_models(
    *,
    base_url: str,
    api_key: str,
    provider_code: str = "",
    provider_name: str = "",
    access_mode: str = "api",
    auth_type: str = "bearer",
    timeout_seconds: int = 30,
) -> dict:
    if not (base_url or "").strip():
        return {"status": "failed", "summary": "Base URL 不能为空", "items": [], "endpoint": ""}
    if not (api_key or "").strip():
        return {"status": "failed", "summary": "API Key 为空，无法查询供应商模型", "items": [], "endpoint": ""}

    kind = resolve_provider_kind_from_config(
        provider_code=provider_code,
        provider_name=provider_name,
        base_url=base_url,
        access_mode=access_mode,
    )
    timeout = max(3, min(int(timeout_seconds or 30), 60))

    if kind == "gemini":
        endpoint = gemini_models_endpoint(base_url, api_key.strip())
        request = urllib.request.Request(endpoint, method="GET")
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                body = response.read().decode("utf-8", errors="replace")
                payload = json.loads(body) if body else {}
                items = parse_gemini_models_payload(payload if isinstance(payload, dict) else {})
                if not items:
                    return {
                        "status": "failed",
                        "summary": f"已调用 {endpoint.split('?', 1)[0]}，但未解析到模型列表",
                        "items": [],
                        "endpoint": endpoint.split("?", 1)[0],
                        "provider_kind": kind,
                    }
                return {
                    "status": "succeeded",
                    "summary": f"已从 Gemini 拉取 {len(items)} 个模型",
                    "items": items,
                    "endpoint": endpoint.split("?", 1)[0],
                    "provider_kind": kind,
                }
        except urllib.error.HTTPError as error:
            error_body = error.read(1024).decode("utf-8", errors="replace")
            return {
                "status": "failed",
                "summary": f"Gemini 模型列表返回 HTTP {error.code}: {error_body[:300]}",
                "items": [],
                "endpoint": endpoint.split("?", 1)[0],
                "provider_kind": kind,
            }
        except Exception as error:
            return {
                "status": "failed",
                "summary": f"Gemini 模型列表调用失败: {error}",
                "items": [],
                "endpoint": endpoint.split("?", 1)[0],
                "provider_kind": kind,
            }

    headers = {"Accept": "application/json"}
    if (auth_type or "bearer") == "bearer":
        headers["Authorization"] = f"Bearer {api_key.strip()}"
    else:
        headers["Authorization"] = api_key.strip()

    last_error = ""
    last_endpoint = ""
    for endpoint in openai_models_endpoints(base_url):
        last_endpoint = endpoint
        request = urllib.request.Request(endpoint, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                body = response.read().decode("utf-8", errors="replace")
                payload = json.loads(body) if body else {}
                items = parse_openai_models_payload(payload)
                if not items:
                    last_error = f"{endpoint} 返回成功，但未解析到模型列表"
                    continue
                return {
                    "status": "succeeded",
                    "summary": f"已从供应商拉取 {len(items)} 个模型",
                    "items": items,
                    "endpoint": endpoint,
                    "provider_kind": kind,
                }
        except urllib.error.HTTPError as error:
            error_body = error.read(1024).decode("utf-8", errors="replace")
            last_error = f"{endpoint} 返回 HTTP {error.code}: {error_body[:300]}"
            if error.code not in {404, 405}:
                break
        except Exception as error:
            last_error = f"{endpoint} 调用失败: {error}"
            break
    return {
        "status": "failed",
        "summary": last_error or "供应商模型列表查询失败",
        "items": [],
        "endpoint": last_endpoint,
        "provider_kind": kind,
    }



def call_openai_image_generation_test(model: ImageModel, provider: ImageModelProvider, prompt: str) -> dict:
    api_key = (provider.encrypted_api_key or "").strip()
    if not api_key:
        return {"status": "failed", "summary": "供应商 API Key 为空，无法测试"}

    body = json.dumps(
        {
            "model": model.vendor_model,
            "prompt": prompt or "生成一张用于接口连通性测试的简单商品主图",
            "n": 1,
            "size": "1024x1024",
        }
    ).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if provider.auth_type == "bearer":
        headers["Authorization"] = f"Bearer {api_key}"
    else:
        headers["Authorization"] = api_key

    last_error = ""
    timeout = model_task_timeout_seconds(model)
    for endpoint in model_test_endpoints(provider.base_url):
        request = urllib.request.Request(endpoint, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                response_body = response.read(2048).decode("utf-8", errors="replace")
                return {
                    "status": "succeeded",
                    "summary": f"已实际调用 {endpoint}，HTTP {response.status}，返回 {len(response_body)} 字符",
                }
        except urllib.error.HTTPError as error:
            error_body = error.read(1024).decode("utf-8", errors="replace")
            last_error = f"{endpoint} 返回 HTTP {error.code}: {error_body[:300]}"
            if error.code not in {404, 405}:
                break
        except Exception as error:
            last_error = f"{endpoint} 调用失败: {error}"
            break
    return {"status": "failed", "summary": last_error or "模型测试调用失败"}


def call_openai_responses_image_test(model: ImageModel, provider: ImageModelProvider, prompt: str) -> dict:
    api_key = (provider.encrypted_api_key or "").strip()
    if not api_key:
        return {"status": "failed", "summary": "供应商 API Key 为空，无法测试"}

    endpoint = model_response_endpoint(provider.base_url)
    body = json.dumps(
        {
            "model": model.vendor_model,
            "input": prompt or "生成一张用于接口连通性测试的简单商品主图",
            "tools": [{"type": "image_generation"}],
        }
    ).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if provider.auth_type == "bearer":
        headers["Authorization"] = f"Bearer {api_key}"
    else:
        headers["Authorization"] = api_key

    request = urllib.request.Request(endpoint, data=body, headers=headers, method="POST")
    timeout = model_task_timeout_seconds(model)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            response_body = response.read().decode("utf-8", errors="replace")
            response_payload = json.loads(response_body)
            has_image = any(item.get("type") == "image_generation_call" and (item.get("result") or item.get("url")) for item in response_payload.get("output") or [])
            if not has_image:
                return {
                    "status": "failed",
                    "summary": f"已实际调用 {endpoint} image_generation，HTTP {response.status}，但模型未返回图片结果",
                }
            return {
                "status": "succeeded",
                "summary": f"已实际调用 {endpoint} image_generation，HTTP {response.status}，返回 {len(response_body)} 字符",
            }
    except urllib.error.HTTPError as error:
        error_body = error.read(1024).decode("utf-8", errors="replace")
        return {"status": "failed", "summary": f"{endpoint} image_generation 返回 HTTP {error.code}: {error_body[:300]}"}
    except Exception as error:
        return {"status": "failed", "summary": f"{endpoint} image_generation 调用失败: {error}"}


def call_openai_chat_completions_test(model: ImageModel, provider: ImageModelProvider, prompt: str) -> dict:
    api_key = (provider.encrypted_api_key or "").strip()
    if not api_key:
        return {"status": "failed", "summary": "供应商 API Key 为空，无法测试"}

    text_model = is_text_model(model)
    if text_model:
        user_content = prompt or "请回复：ok。仅用于接口连通性测试。"
    else:
        user_content = f"{prompt or 'Hello'}\n\n生成参数：分辨率 1k，比例 1:1。"

    endpoint = model_chat_completions_endpoint(provider.base_url)
    body = json.dumps(
        {
            "model": model.vendor_model,
            "messages": [
                {
                    "role": "user",
                    "content": user_content,
                }
            ],
        }
    ).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if provider.auth_type == "bearer":
        headers["Authorization"] = f"Bearer {api_key}"
    else:
        headers["Authorization"] = api_key
    request = urllib.request.Request(endpoint, data=body, headers=headers, method="POST")
    timeout = model_task_timeout_seconds(model)
    mode_label = "文本 chat.completions" if text_model else "SDK chat.completions"
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            response_body = response.read(2048).decode("utf-8", errors="replace")
            return {
                "status": "succeeded",
                "summary": f"已按 {mode_label} 调用 {endpoint}，HTTP {response.status}，返回 {len(response_body)} 字符",
            }
    except urllib.error.HTTPError as error:
        error_body = error.read(1024).decode("utf-8", errors="replace")
        return {"status": "failed", "summary": f"{endpoint} chat.completions 返回 HTTP {error.code}: {error_body[:300]}"}
    except Exception as error:
        return {"status": "failed", "summary": f"{endpoint} chat.completions 调用失败: {error}"}


def gemini_generate_content_endpoint(base_url: str, model_name: str, api_key: str) -> str:
    normalized = base_url.rstrip("/")
    if not normalized.endswith("/v1") and not normalized.endswith("/v1beta"):
        normalized = f"{normalized}/v1beta"
    safe_model = urllib.parse.quote(model_name.strip(), safe="")
    return f"{normalized}/models/{safe_model}:generateContent?key={urllib.parse.quote(api_key, safe='')}"


def call_gemini_image_generation_test(model: ImageModel, provider: ImageModelProvider, prompt: str) -> dict:
    api_key = (provider.encrypted_api_key or "").strip()
    if not api_key:
        return {"status": "failed", "summary": "Gemini API Key 为空，无法测试"}

    endpoint = gemini_generate_content_endpoint(provider.base_url, model.vendor_model, api_key)
    body = json.dumps(
        {
            "contents": [
                {
                    "parts": [
                        {"text": prompt or "生成一张用于接口连通性测试的简单商品主图"}
                    ]
                }
            ],
            "generationConfig": {"responseModalities": ["TEXT", "IMAGE"]},
        }
    ).encode("utf-8")
    request = urllib.request.Request(endpoint, data=body, headers={"Content-Type": "application/json"}, method="POST")
    timeout = model_task_timeout_seconds(model)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            response_body = response.read(2048).decode("utf-8", errors="replace")
            return {
                "status": "succeeded",
                "summary": f"已实际调用 Gemini generateContent，HTTP {response.status}，返回 {len(response_body)} 字符",
            }
    except urllib.error.HTTPError as error:
        error_body = error.read(1024).decode("utf-8", errors="replace")
        return {"status": "failed", "summary": f"Gemini generateContent 返回 HTTP {error.code}: {error_body[:300]}"}
    except Exception as error:
        return {"status": "failed", "summary": f"Gemini generateContent 调用失败: {error}"}


def uses_openai_images_api(vendor_model: str) -> bool:
    model = (vendor_model or "").strip().lower()
    if model.startswith("gpt-image"):
        return True
    if model.startswith("grok-imagine-image"):
        return True
    return False


def call_image_generation_test(model: ImageModel, provider: ImageModelProvider, prompt: str) -> dict:
    # 文本模型（提示词优化等）一律走 chat.completions，不走图片 / responses image_generation。
    if is_text_model(model):
        return call_openai_chat_completions_test(model, provider, prompt)
    provider_kind = model_provider_kind(provider)
    if provider_kind == "openai_chat_completions":
        return call_openai_chat_completions_test(model, provider, prompt)
    if provider_kind == "gemini":
        return call_gemini_image_generation_test(model, provider, prompt)
    if not uses_openai_images_api(model.vendor_model):
        return call_openai_responses_image_test(model, provider, prompt)
    return call_openai_image_generation_test(model, provider, prompt)


def spec_out(spec) -> dict:
    return {
        "id": spec.id,
        "code": spec.code,
        "label": spec.label,
        "sort_order": spec.sort_order,
        "is_active": spec.is_active,
    }


async def model_supported_specs(db: AsyncSession, model_id: int) -> tuple[list[dict], list[dict], list[dict]]:
    resolution_result = await db.execute(
        select(ImageResolutionSpec)
        .join(ImageModelResolution, ImageModelResolution.resolution_id == ImageResolutionSpec.id)
        .where(ImageModelResolution.model_id == model_id)
        .order_by(ImageResolutionSpec.sort_order.asc(), ImageResolutionSpec.id.asc())
    )
    aspect_ratio_result = await db.execute(
        select(ImageAspectRatioSpec)
        .join(ImageModelAspectRatio, ImageModelAspectRatio.aspect_ratio_id == ImageAspectRatioSpec.id)
        .where(ImageModelAspectRatio.model_id == model_id)
        .order_by(ImageAspectRatioSpec.sort_order.asc(), ImageAspectRatioSpec.id.asc())
    )
    duration_result = await db.execute(
        select(VideoDurationSpec)
        .join(ImageModelDuration, ImageModelDuration.duration_id == VideoDurationSpec.id)
        .where(ImageModelDuration.model_id == model_id)
        .order_by(VideoDurationSpec.sort_order.asc(), VideoDurationSpec.id.asc())
    )
    return (
        [spec_out(spec) for spec in resolution_result.scalars()],
        [spec_out(spec) for spec in aspect_ratio_result.scalars()],
        [spec_out(spec) for spec in duration_result.scalars()],
    )


async def sync_model_specs(
    db: AsyncSession,
    model_id: int,
    site_id: int,
    resolution_ids: list[int],
    aspect_ratio_ids: list[int],
    duration_ids: list[int] | None = None,
) -> None:
    unique_resolution_ids = list(dict.fromkeys(resolution_ids))
    unique_aspect_ratio_ids = list(dict.fromkeys(aspect_ratio_ids))
    unique_duration_ids = list(dict.fromkeys(duration_ids or []))
    if unique_resolution_ids:
        found = await db.scalars(
            select(ImageResolutionSpec.id).where(
                ImageResolutionSpec.site_id == site_id,
                ImageResolutionSpec.id.in_(unique_resolution_ids),
                ImageResolutionSpec.is_active.is_(True),
            )
        )
        if set(found) != set(unique_resolution_ids):
            raise AppException(code=40001, message="包含不存在或已停用的分辨率规范")
    if unique_aspect_ratio_ids:
        found = await db.scalars(
            select(ImageAspectRatioSpec.id).where(
                ImageAspectRatioSpec.site_id == site_id,
                ImageAspectRatioSpec.id.in_(unique_aspect_ratio_ids),
                ImageAspectRatioSpec.is_active.is_(True),
            )
        )
        if set(found) != set(unique_aspect_ratio_ids):
            raise AppException(code=40001, message="包含不存在或已停用的尺寸规范")
    if unique_duration_ids:
        found = await db.scalars(
            select(VideoDurationSpec.id).where(
                VideoDurationSpec.site_id == site_id,
                VideoDurationSpec.id.in_(unique_duration_ids),
                VideoDurationSpec.is_active.is_(True),
            )
        )
        if set(found) != set(unique_duration_ids):
            raise AppException(code=40001, message="包含不存在或已停用的时长规范")
    await db.execute(delete(ImageModelResolution).where(ImageModelResolution.model_id == model_id))
    await db.execute(delete(ImageModelAspectRatio).where(ImageModelAspectRatio.model_id == model_id))
    await db.execute(delete(ImageModelDuration).where(ImageModelDuration.model_id == model_id))
    for resolution_id in unique_resolution_ids:
        db.add(ImageModelResolution(model_id=model_id, resolution_id=resolution_id))
    for aspect_ratio_id in unique_aspect_ratio_ids:
        db.add(ImageModelAspectRatio(model_id=model_id, aspect_ratio_id=aspect_ratio_id))
    for duration_id in unique_duration_ids:
        db.add(ImageModelDuration(model_id=model_id, duration_id=duration_id))


def model_work_types(model: ImageModel) -> list[str]:
    return [part.strip() for part in model.work_type.split(",") if part.strip()]


def missing_price_message(missing: list[dict]) -> str:
    if missing and "reason" in missing[0]:
        return str(missing[0]["reason"])
    preview = "；".join(
        f"{item['work_type']} / {item['resolution']} / {item['aspect_ratio']}"
        for item in missing[:12]
    )
    suffix = f" 等 {len(missing)} 个组合" if len(missing) > 12 else ""
    return f"模型缺少价格配置：{preview}{suffix}"


def is_text_model(model: ImageModel) -> bool:
    if (model.capability_type or "").strip() == "text":
        return True
    work_types = model_work_types(model)
    return work_types == ["text"] or (len(work_types) == 1 and work_types[0] in {"text", "text_generation"})


def is_video_model(model: ImageModel) -> bool:
    if (model.capability_type or "").strip() == "video":
        return True
    work_types = model_work_types(model)
    return bool(work_types) and all(item in {"text_to_video", "image_to_video"} for item in work_types)


async def missing_price_combinations(db: AsyncSession, model: ImageModel) -> list[dict]:
    # 文本模型不依赖分辨率/尺寸，只需一条 work_type=text 的启用价格。
    if is_text_model(model):
        price_id = await db.scalar(
            select(ModelPrice.id)
            .where(
                ModelPrice.site_id == model.site_id,
                ModelPrice.model_id == model.id,
                ModelPrice.work_type.in_(("text", "text_generation")),
                ModelPrice.is_active.is_(True),
            )
            .limit(1)
        )
        if price_id is None:
            return [{"work_type": "text", "resolution": "default", "aspect_ratio": "default", "output_count": 1}]
        return []

    resolutions, aspect_ratios, durations = await model_supported_specs(db, model.id)
    # 视频模型按 分辨率 × 时长 计费；时长写入价格表的 aspect_ratio 字段，与图片矩阵结构保持一致。
    if is_video_model(model):
        if not resolutions or not durations:
            return [{"reason": "视频模型必须至少配置一个分辨率和一个时长"}]
        missing: list[dict] = []
        for work_type in model_work_types(model):
            for resolution in resolutions:
                for duration in durations:
                    price_id = await db.scalar(
                        select(ModelPrice.id).where(
                            ModelPrice.site_id == model.site_id,
                            ModelPrice.model_id == model.id,
                            ModelPrice.work_type == work_type,
                            ModelPrice.resolution == resolution["code"],
                            ModelPrice.aspect_ratio == duration["code"],
                            ModelPrice.output_count == 1,
                            ModelPrice.is_active.is_(True),
                        )
                    )
                    if price_id is None:
                        missing.append(
                            {
                                "work_type": work_type,
                                "resolution": resolution["code"],
                                "aspect_ratio": duration["code"],
                                "output_count": 1,
                            }
                        )
        return missing

    if not resolutions or not aspect_ratios:
        return [{"reason": "模型必须至少配置一个分辨率和一个尺寸"}]
    missing = []
    for work_type in model_work_types(model):
        for resolution in resolutions:
            for aspect_ratio in aspect_ratios:
                price_id = await db.scalar(
                    select(ModelPrice.id).where(
                        ModelPrice.site_id == model.site_id,
                        ModelPrice.model_id == model.id,
                        ModelPrice.work_type == work_type,
                        ModelPrice.resolution == resolution["code"],
                        ModelPrice.aspect_ratio == aspect_ratio["code"],
                        ModelPrice.output_count == 1,
                        ModelPrice.is_active.is_(True),
                    )
                )
                if price_id is None:
                    missing.append(
                        {
                            "work_type": work_type,
                            "resolution": resolution["code"],
                            "aspect_ratio": aspect_ratio["code"],
                            "output_count": 1,
                        }
                    )
    return missing


async def model_out(db: AsyncSession, model: ImageModel, provider: ImageModelProvider) -> AdminImageModelOut:
    resolutions, aspect_ratios, durations = await model_supported_specs(db, model.id)
    return AdminImageModelOut(
        id=model.id,
        provider_id=provider.id,
        provider_name=provider.name,
        provider_code=provider.code,
        name=model.name,
        code=model.code,
        vendor_model=model.vendor_model,
        work_type=model.work_type,
        capability_type=model.capability_type,
        supports_image_edit=model.supports_image_edit,
        description=model.description,
        base_url=provider.base_url,
        access_mode=getattr(provider, "access_mode", "api") or "api",
        base_url_masked=mask_url(provider.base_url),
        api_key_masked=mask_secret(provider.encrypted_api_key),
        is_recommended=model.is_recommended,
        is_stable=model.is_stable,
        is_new=model.is_new,
        max_input_images=model.max_input_images,
        max_output_images=model.max_output_images,
        concurrency_limit=getattr(model, "concurrency_limit", 1),
        is_active=model.is_active,
        is_public=getattr(model, "is_public", True),
        storage_mode=getattr(model, "storage_mode", None) or "local",
        sort_order=model.sort_order,
        timeout_seconds=getattr(model, "timeout_seconds", None),
        disable_retry=bool(getattr(model, "disable_retry", False)),
        supported_resolutions=resolutions,
        supported_aspect_ratios=aspect_ratios,
        supported_durations=durations,
    )


@router.get("/recharge/plans", response_model=ApiResponse[dict])
async def recharge_plans(
    request: Request,
    keyword: str = "",
    status: str = Query("all", pattern="^(all|active|inactive)$"),
    page_no: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_admin: AdminUser = Depends(require_admin_roles(AdminRole.super_admin, AdminRole.finance)),
) -> ApiResponse[dict]:
    site_id = await current_admin_config_site_id(db, request, current_admin)
    condition = RechargePlan.site_id == site_id
    if keyword:
        like = f"%{keyword.strip()}%"
        condition = and_(condition, or_(RechargePlan.name.ilike(like), RechargePlan.badge.ilike(like)))
    if status == "active":
        condition = and_(condition, RechargePlan.is_active.is_(True))
    if status == "inactive":
        condition = and_(condition, RechargePlan.is_active.is_(False))

    total = await db.scalar(select(func.count()).select_from(RechargePlan).where(condition))
    result = await db.scalars(
        select(RechargePlan)
        .where(condition)
        .order_by(RechargePlan.sort_order.asc(), RechargePlan.id.desc())
        .limit(page_size)
        .offset((page_no - 1) * page_size)
    )
    return ApiResponse.ok(
        {
            "items": [recharge_plan_out(plan) for plan in result],
            "total": total or 0,
            "page": page_no,
            "page_size": page_size,
        }
    )


@router.get("/recharge/orders", response_model=ApiResponse[dict])
async def recharge_orders(
    keyword: str = "",
    status: str = Query("all", pattern="^(all|pending|paid|expired|cancelled|failed)$"),
    page_no: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_admin: AdminUser = Depends(require_admin_roles(AdminRole.super_admin, AdminRole.finance)),
) -> ApiResponse[dict]:
    condition = scoped_user_condition(current_admin)
    if keyword:
        like = f"%{keyword.strip()}%"
        condition = and_(
            condition,
            or_(
                recharge_orders_table.c.order_no.ilike(like),
                recharge_orders_table.c.payment_trade_no.ilike(like),
                users_table.c.username.ilike(like),
                users_table.c.email.ilike(like),
                users_table.c.id.cast(String).ilike(like),
            ),
        )
    if status != "all":
        condition = and_(condition, recharge_orders_table.c.status == status)

    joined = outerjoin(recharge_orders_table, users_table, recharge_orders_table.c.user_id == users_table.c.id)
    total = await db.scalar(select(func.count()).select_from(joined).where(condition))
    result = await db.execute(
        select(
            recharge_orders_table.c.id,
            recharge_orders_table.c.order_no,
            recharge_orders_table.c.user_id,
            recharge_orders_table.c.amount_cents,
            recharge_orders_table.c.credit_amount,
            recharge_orders_table.c.bonus_credit_amount,
            recharge_orders_table.c.team_seat_count,
            recharge_orders_table.c.team_duration_days,
            recharge_orders_table.c.status,
            recharge_orders_table.c.payment_provider,
            recharge_orders_table.c.payment_type,
            recharge_orders_table.c.payment_trade_no,
            recharge_orders_table.c.pay_url,
            recharge_orders_table.c.qr_code,
            recharge_orders_table.c.failure_message,
            recharge_orders_table.c.expires_at,
            recharge_orders_table.c.paid_at,
            recharge_orders_table.c.created_at,
            recharge_orders_table.c.updated_at,
            users_table.c.username,
            users_table.c.email,
        )
        .select_from(joined)
        .where(condition)
        .order_by(desc(recharge_orders_table.c.created_at), desc(recharge_orders_table.c.id))
        .limit(page_size)
        .offset((page_no - 1) * page_size)
    )
    items = [recharge_order_out(row) for row in result.mappings()]
    return ApiResponse.ok({"items": items, "total": total or 0, "page": page_no, "page_size": page_size})


@router.post("/recharge/plans", response_model=ApiResponse[RechargePlanOut])
async def create_recharge_plan(
    request: Request,
    payload: RechargePlanCreate,
    db: AsyncSession = Depends(get_db),
    current_admin: AdminUser = Depends(require_admin_roles(AdminRole.super_admin, AdminRole.finance)),
) -> ApiResponse[RechargePlanOut]:
    name = payload.name.strip()
    if not name:
        raise AppException(code=40001, message="档位名称不能为空")
    if payload.team_seat_count == 1:
        raise AppException(code=40001, message="团队席位至少为 2（含所有者）")
    if payload.team_seat_count == 0 and payload.team_duration_days > 0:
        raise AppException(code=40001, message="未配置团队席位时不能设置团队有效期")
    plan = RechargePlan(
        site_id=await current_admin_config_site_id(db, request, current_admin),
        name=name,
        amount_cents=payload.amount_cents,
        credit_amount=payload.credit_amount,
        bonus_credit_amount=payload.bonus_credit_amount,
        team_seat_count=payload.team_seat_count,
        team_duration_days=payload.team_duration_days,
        badge=payload.badge.strip() if payload.badge else None,
        sort_order=payload.sort_order,
        is_recommended=payload.is_recommended,
        is_active=payload.is_active,
    )
    db.add(plan)
    add_audit(db, current_admin, "create_recharge_plan", "recharge_plans", "pending", name)
    await db.commit()
    await db.refresh(plan)
    return ApiResponse.ok(recharge_plan_out(plan))


@router.patch("/recharge/plans/{plan_id}", response_model=ApiResponse[RechargePlanOut])
async def update_recharge_plan(
    plan_id: int,
    request: Request,
    payload: RechargePlanUpdate,
    db: AsyncSession = Depends(get_db),
    current_admin: AdminUser = Depends(require_admin_roles(AdminRole.super_admin, AdminRole.finance)),
) -> ApiResponse[RechargePlanOut]:
    site_id = await current_admin_config_site_id(db, request, current_admin)
    plan = await db.scalar(select(RechargePlan).where(RechargePlan.id == plan_id, RechargePlan.site_id == site_id))
    if plan is None:
        raise AppException(code=40404, message="充值档位不存在", status_code=404)

    update_data = payload.model_dump(exclude_unset=True)
    if "name" in update_data and update_data["name"] is not None:
        update_data["name"] = update_data["name"].strip()
        if not update_data["name"]:
            raise AppException(code=40001, message="档位名称不能为空")
    if "badge" in update_data and update_data["badge"] is not None:
        update_data["badge"] = update_data["badge"].strip() or None
    next_team_seat_count = int(update_data.get("team_seat_count", plan.team_seat_count) or 0)
    next_team_duration_days = int(update_data.get("team_duration_days", plan.team_duration_days) or 0)
    if next_team_seat_count == 1:
        raise AppException(code=40001, message="团队席位至少为 2（含所有者）")
    if next_team_seat_count == 0 and next_team_duration_days > 0:
        raise AppException(code=40001, message="未配置团队席位时不能设置团队有效期")
    for key, value in update_data.items():
        setattr(plan, key, value)

    add_audit(db, current_admin, "update_recharge_plan", "recharge_plans", plan_id, "更新充值档位配置")
    await db.commit()
    await db.refresh(plan)
    return ApiResponse.ok(recharge_plan_out(plan))


@router.patch("/recharge/plans/{plan_id}/status", response_model=ApiResponse[RechargePlanOut])
async def recharge_plan_status(
    plan_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_admin: AdminUser = Depends(require_admin_roles(AdminRole.super_admin, AdminRole.finance)),
) -> ApiResponse[RechargePlanOut]:
    site_id = await current_admin_config_site_id(db, request, current_admin)
    plan = await db.scalar(select(RechargePlan).where(RechargePlan.id == plan_id, RechargePlan.site_id == site_id))
    if plan is None:
        raise AppException(code=40404, message="充值档位不存在", status_code=404)
    plan.is_active = not plan.is_active
    add_audit(db, current_admin, "toggle_recharge_plan", "recharge_plans", plan_id, f"is_active={plan.is_active}")
    await db.commit()
    await db.refresh(plan)
    return ApiResponse.ok(recharge_plan_out(plan))


@router.delete("/recharge/plans/{plan_id}", response_model=ApiResponse[None])
async def delete_recharge_plan(
    plan_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_admin: AdminUser = Depends(require_admin_roles(AdminRole.super_admin, AdminRole.finance)),
) -> ApiResponse[None]:
    site_id = await current_admin_config_site_id(db, request, current_admin)
    plan = await db.scalar(select(RechargePlan).where(RechargePlan.id == plan_id, RechargePlan.site_id == site_id))
    if plan is None:
        raise AppException(code=40404, message="充值档位不存在", status_code=404)
    await db.delete(plan)
    await db.commit()
    return ApiResponse.ok(None)


@router.get("/image-specs", response_model=ApiResponse[dict])
async def image_specs(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_admin: AdminUser = Depends(require_admin_roles(AdminRole.super_admin, AdminRole.model_admin)),
) -> ApiResponse[dict]:
    site_id = await current_admin_config_site_id(db, request, current_admin)
    resolutions = await db.scalars(
        select(ImageResolutionSpec)
        .where(ImageResolutionSpec.site_id == site_id)
        .order_by(ImageResolutionSpec.sort_order.asc(), ImageResolutionSpec.id.asc())
    )
    aspect_ratios = await db.scalars(
        select(ImageAspectRatioSpec)
        .where(ImageAspectRatioSpec.site_id == site_id)
        .order_by(ImageAspectRatioSpec.sort_order.asc(), ImageAspectRatioSpec.id.asc())
    )
    durations = await db.scalars(
        select(VideoDurationSpec)
        .where(VideoDurationSpec.site_id == site_id)
        .order_by(VideoDurationSpec.sort_order.asc(), VideoDurationSpec.id.asc())
    )
    return ApiResponse.ok(
        {
            "resolutions": [spec_out(spec) for spec in resolutions],
            "aspect_ratios": [spec_out(spec) for spec in aspect_ratios],
            "durations": [spec_out(spec) for spec in durations],
        }
    )


async def save_spec(db: AsyncSession, model_cls, payload: dict, site_id: int):
    code = str(payload.get("code") or "").strip()
    label = str(payload.get("label") or "").strip()
    if not code or not label:
        raise AppException(code=40001, message="规范编码和名称不能为空")
    spec = model_cls(
        site_id=site_id,
        code=code,
        label=label,
        sort_order=int(payload.get("sort_order") or 50),
        is_active=bool(payload.get("is_active", True)),
    )
    db.add(spec)
    await db.commit()
    await db.refresh(spec)
    return spec


async def update_spec(db: AsyncSession, model_cls, spec_id: int, payload: dict, site_id: int):
    spec = await db.scalar(select(model_cls).where(model_cls.id == spec_id, model_cls.site_id == site_id))
    if spec is None:
        raise AppException(code=40404, message="图片规范不存在", status_code=404)
    if "code" in payload:
        spec.code = str(payload.get("code") or "").strip()
    if "label" in payload:
        spec.label = str(payload.get("label") or "").strip()
    if not spec.code or not spec.label:
        raise AppException(code=40001, message="规范编码和名称不能为空")
    if "sort_order" in payload:
        spec.sort_order = int(payload.get("sort_order") or 50)
    if "is_active" in payload:
        spec.is_active = bool(payload.get("is_active"))
    await db.commit()
    await db.refresh(spec)
    return spec


@router.post("/image-specs/resolutions", response_model=ApiResponse[dict])
async def create_resolution_spec(
    request: Request,
    payload: dict,
    db: AsyncSession = Depends(get_db),
    current_admin: AdminUser = Depends(require_admin_roles(AdminRole.super_admin, AdminRole.model_admin)),
) -> ApiResponse[dict]:
    site_id = await current_admin_config_site_id(db, request, current_admin)
    spec = await save_spec(db, ImageResolutionSpec, payload, site_id)
    add_audit(db, current_admin, "create_image_resolution_spec", "image_resolution_specs", spec.id, spec.code)
    await db.commit()
    return ApiResponse.ok(spec_out(spec))


@router.patch("/image-specs/resolutions/{spec_id}", response_model=ApiResponse[dict])
async def update_resolution_spec(
    spec_id: int,
    request: Request,
    payload: dict,
    db: AsyncSession = Depends(get_db),
    current_admin: AdminUser = Depends(require_admin_roles(AdminRole.super_admin, AdminRole.model_admin)),
) -> ApiResponse[dict]:
    site_id = await current_admin_config_site_id(db, request, current_admin)
    spec = await update_spec(db, ImageResolutionSpec, spec_id, payload, site_id)
    add_audit(db, current_admin, "update_image_resolution_spec", "image_resolution_specs", spec.id, spec.code)
    await db.commit()
    return ApiResponse.ok(spec_out(spec))


@router.post("/image-specs/aspect-ratios", response_model=ApiResponse[dict])
async def create_aspect_ratio_spec(
    request: Request,
    payload: dict,
    db: AsyncSession = Depends(get_db),
    current_admin: AdminUser = Depends(require_admin_roles(AdminRole.super_admin, AdminRole.model_admin)),
) -> ApiResponse[dict]:
    site_id = await current_admin_config_site_id(db, request, current_admin)
    spec = await save_spec(db, ImageAspectRatioSpec, payload, site_id)
    add_audit(db, current_admin, "create_image_aspect_ratio_spec", "image_aspect_ratio_specs", spec.id, spec.code)
    await db.commit()
    return ApiResponse.ok(spec_out(spec))


@router.patch("/image-specs/aspect-ratios/{spec_id}", response_model=ApiResponse[dict])
async def update_aspect_ratio_spec(
    spec_id: int,
    request: Request,
    payload: dict,
    db: AsyncSession = Depends(get_db),
    current_admin: AdminUser = Depends(require_admin_roles(AdminRole.super_admin, AdminRole.model_admin)),
) -> ApiResponse[dict]:
    site_id = await current_admin_config_site_id(db, request, current_admin)
    spec = await update_spec(db, ImageAspectRatioSpec, spec_id, payload, site_id)
    add_audit(db, current_admin, "update_image_aspect_ratio_spec", "image_aspect_ratio_specs", spec.id, spec.code)
    await db.commit()
    return ApiResponse.ok(spec_out(spec))


@router.post("/image-specs/durations", response_model=ApiResponse[dict])
async def create_duration_spec(
    request: Request,
    payload: dict,
    db: AsyncSession = Depends(get_db),
    current_admin: AdminUser = Depends(require_admin_roles(AdminRole.super_admin, AdminRole.model_admin)),
) -> ApiResponse[dict]:
    site_id = await current_admin_config_site_id(db, request, current_admin)
    spec = await save_spec(db, VideoDurationSpec, payload, site_id)
    add_audit(db, current_admin, "create_video_duration_spec", "video_duration_specs", spec.id, spec.code)
    await db.commit()
    return ApiResponse.ok(spec_out(spec))


@router.patch("/image-specs/durations/{spec_id}", response_model=ApiResponse[dict])
async def update_duration_spec(
    spec_id: int,
    request: Request,
    payload: dict,
    db: AsyncSession = Depends(get_db),
    current_admin: AdminUser = Depends(require_admin_roles(AdminRole.super_admin, AdminRole.model_admin)),
) -> ApiResponse[dict]:
    site_id = await current_admin_config_site_id(db, request, current_admin)
    spec = await update_spec(db, VideoDurationSpec, spec_id, payload, site_id)
    add_audit(db, current_admin, "update_video_duration_spec", "video_duration_specs", spec.id, spec.code)
    await db.commit()
    return ApiResponse.ok(spec_out(spec))


@router.get("/models", response_model=ApiResponse[dict])
async def models(
    request: Request,
    keyword: str = "",
    provider: str = "",
    status: str = Query("all", pattern="^(all|active|inactive)$"),
    capability_type: str = "",
    work_type: str = "",
    tag: str = Query("all", pattern="^(all|recommended|stable|new)$"),
    page_no: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_admin: AdminUser = Depends(require_admin_roles(AdminRole.super_admin, AdminRole.model_admin)),
) -> ApiResponse[dict]:
    site_id = await current_admin_config_site_id(db, request, current_admin)
    condition = and_(ImageModel.site_id == site_id, ImageModelProvider.site_id == site_id)
    if keyword:
        like = f"%{keyword.strip()}%"
        condition = and_(
            condition,
            or_(
                ImageModel.name.ilike(like),
                ImageModel.code.ilike(like),
                ImageModel.vendor_model.ilike(like),
                ImageModelProvider.name.ilike(like),
            ),
        )
    if provider:
        provider_like = f"%{provider.strip()}%"
        condition = and_(condition, ImageModelProvider.name.ilike(provider_like))
    if status == "active":
        condition = and_(condition, ImageModel.is_active.is_(True))
    if status == "inactive":
        condition = and_(condition, ImageModel.is_active.is_(False))
    if capability_type:
        condition = and_(condition, ImageModel.capability_type == capability_type.strip())
    if work_type:
        condition = and_(condition, ImageModel.work_type.ilike(f"%{work_type.strip()}%"))
    if tag == "recommended":
        condition = and_(condition, ImageModel.is_recommended.is_(True))
    if tag == "stable":
        condition = and_(condition, ImageModel.is_stable.is_(True))
    if tag == "new":
        condition = and_(condition, ImageModel.is_new.is_(True))

    joined = ImageModel.__table__.join(ImageModelProvider.__table__, ImageModel.provider_id == ImageModelProvider.id)
    total = await db.scalar(select(func.count()).select_from(joined).where(condition))
    result = await db.execute(
        select(ImageModel, ImageModelProvider)
        .join(ImageModelProvider, ImageModel.provider_id == ImageModelProvider.id)
        .where(condition)
        .order_by(ImageModel.sort_order.asc(), ImageModel.id.desc())
        .limit(page_size)
        .offset((page_no - 1) * page_size)
    )
    items = [((await model_out(db, model, provider)).model_dump()) for model, provider in result]
    return ApiResponse.ok({"items": items, "total": total or 0, "page": page_no, "page_size": page_size})


async def allocate_unique_provider_code(db: AsyncSession, site_id: int, preferred_code: str) -> str:
    """Ensure provider codes stay unique per site when forking credentials."""
    preferred_code = (preferred_code or "provider").strip() or "provider"
    existing = await db.scalar(
        select(ImageModelProvider.id).where(
            ImageModelProvider.site_id == site_id,
            ImageModelProvider.code == preferred_code,
        )
    )
    if existing is None:
        return preferred_code
    suffix = 2
    while True:
        candidate = f"{preferred_code}-{suffix}"
        hit = await db.scalar(
            select(ImageModelProvider.id).where(
                ImageModelProvider.site_id == site_id,
                ImageModelProvider.code == candidate,
            )
        )
        if hit is None:
            return candidate
        suffix += 1


async def create_image_model_provider(
    db: AsyncSession,
    *,
    site_id: int,
    name: str,
    code: str,
    base_url: str,
    access_mode: str,
    api_key: str,
    timeout_seconds: int | None = None,
) -> ImageModelProvider:
    next_id = (await db.scalar(select(func.coalesce(func.max(ImageModelProvider.id), 0)))) + 1
    provider = ImageModelProvider(
        id=next_id,
        site_id=site_id,
        name=name,
        code=code,
        base_url=base_url,
        access_mode=access_mode,
        encrypted_api_key=api_key,
        auth_type="bearer",
        is_active=True,
    )
    if timeout_seconds is not None:
        provider.timeout_seconds = timeout_seconds
    db.add(provider)
    await db.flush()
    return provider


async def provider_from_model_payload(
    db: AsyncSession,
    payload: AdminImageModelCreate,
    current_admin: AdminUser,
    site_id: int,
    *,
    require_api_key: bool,
    exclude_model_id: int | None = None,
) -> ImageModelProvider:
    """Resolve provider for a model without clobbering shared credentials.

    Historical bug: lookup by provider_code alone reused the first OpenAI row and
    overwrote its API key, so adding a text model broke every image model that
    shared the same provider_code.
    """
    provider = (
        await db.scalar(
            select(ImageModelProvider).where(
                ImageModelProvider.id == payload.provider_id,
                ImageModelProvider.site_id == site_id,
            )
        )
        if payload.provider_id
        else None
    )
    provider_name = (payload.provider_name or "").strip()
    provider_code = (payload.provider_code or provider_name.lower().replace(" ", "-")).strip()
    base_url = (payload.base_url or "").strip()
    access_mode = (payload.access_mode or "api").strip()
    api_key = (payload.api_key or "").strip()
    if not provider_name or not provider_code or not base_url:
        raise AppException(code=40001, message="供应商名称、编码和 Base URL 不能为空")
    if access_mode not in {"api", "sdk"}:
        raise AppException(code=40001, message="接入方式只能选择 API 或 SDK")
    if require_api_key and not api_key:
        raise AppException(code=40001, message="新增供应商必须填写 API Key")

    if provider is None and api_key:
        # Prefer exact credential match so the same vendor+key reuses one row.
        provider = await db.scalar(
            select(ImageModelProvider).where(
                ImageModelProvider.site_id == site_id,
                ImageModelProvider.code == provider_code,
                ImageModelProvider.base_url == base_url,
                ImageModelProvider.encrypted_api_key == api_key,
            )
        )
    if provider is None and not api_key:
        # Edit without rotating key: reuse same code + base_url.
        provider = await db.scalar(
            select(ImageModelProvider).where(
                ImageModelProvider.site_id == site_id,
                ImageModelProvider.code == provider_code,
                ImageModelProvider.base_url == base_url,
            )
        )
    if provider is None:
        # Fallback: same code only when credentials are still compatible.
        candidate = await db.scalar(
            select(ImageModelProvider).where(
                ImageModelProvider.site_id == site_id,
                ImageModelProvider.code == provider_code,
            )
        )
        if candidate is not None:
            same_base = (candidate.base_url or "").strip() == base_url
            same_key = (not api_key) or ((candidate.encrypted_api_key or "").strip() == api_key)
            if same_base and same_key:
                provider = candidate

    if provider is None:
        if not api_key:
            raise AppException(code=40001, message="新供应商必须填写 API Key")
        return await create_image_model_provider(
            db,
            site_id=site_id,
            name=provider_name,
            code=await allocate_unique_provider_code(db, site_id, provider_code),
            base_url=base_url,
            access_mode=access_mode,
            api_key=api_key,
        )

    existing_key = (provider.encrypted_api_key or "").strip()
    credential_change = ((provider.base_url or "").strip() != base_url) or (bool(api_key) and api_key != existing_key)
    other_models_q = select(func.count()).select_from(ImageModel).where(ImageModel.provider_id == provider.id)
    if exclude_model_id is not None:
        other_models_q = other_models_q.where(ImageModel.id != exclude_model_id)
    other_models = int(await db.scalar(other_models_q) or 0)

    if credential_change and other_models > 0:
        # Shared provider: never overwrite credentials used by other models.
        # Fork a dedicated provider for this model instead.
        fork_key = api_key or existing_key
        if not fork_key:
            raise AppException(code=40001, message="变更共用供应商连接信息时必须填写 API Key")
        return await create_image_model_provider(
            db,
            site_id=site_id,
            name=provider_name,
            code=await allocate_unique_provider_code(db, site_id, provider_code),
            base_url=base_url,
            access_mode=access_mode,
            api_key=fork_key,
        )

    if other_models > 0 and not credential_change:
        # Soft metadata on a shared provider is still global; only attach this model
        # to the existing row without rewriting name/code that other models display.
        return provider

    provider.name = provider_name
    provider.code = provider_code
    provider.base_url = base_url
    provider.access_mode = access_mode
    if api_key:
        provider.encrypted_api_key = api_key
    return provider


def normalized_image_model_payload(payload: AdminImageModelCreate) -> dict:
    capability_type = payload.capability_type.strip()
    if capability_type not in {"image", "text", "video"}:
        raise AppException(code=40001, message="当前只开放图片、文本和视频模型接入")
    storage_mode = (payload.storage_mode or "local").strip().lower()
    if storage_mode not in {"local", "third_party", "native"}:
        raise AppException(code=40001, message="存储类型仅支持 local / third_party / native")
    image_capabilities = [item for item in payload.image_capabilities if item in {"text_to_image", "image_to_image"}]
    video_capabilities = [item for item in payload.video_capabilities if item in {"text_to_video", "image_to_video"}]
    if capability_type == "image" and not image_capabilities:
        raise AppException(code=40001, message="图片模型至少要选择一个二级能力")
    if capability_type == "video" and not video_capabilities:
        raise AppException(code=40001, message="视频模型至少要选择一个二级能力")

    model_data = payload.model_dump(
        exclude={
            "provider_id",
            "provider_name",
            "provider_code",
            "base_url",
            "access_mode",
            "api_key",
            "image_capabilities",
            "video_capabilities",
            "supported_resolution_ids",
            "supported_aspect_ratio_ids",
            "supported_duration_ids",
        }
    )
    model_data["timeout_seconds"] = int(payload.timeout_seconds or DEFAULT_MODEL_TASK_TIMEOUT_SECONDS)
    model_data["capability_type"] = capability_type
    model_data["storage_mode"] = storage_mode
    model_data["supports_image_edit"] = capability_type == "image" and "image_to_image" in image_capabilities
    if capability_type == "text":
        model_data["work_type"] = "text"
    elif capability_type == "video":
        model_data["work_type"] = ",".join(dict.fromkeys(video_capabilities))
    else:
        model_data["work_type"] = ",".join(dict.fromkeys(image_capabilities))
    return model_data




class DiscoverProviderModelsRequest(BaseModel):
    base_url: str = Field(default="", max_length=512)
    api_key: str | None = Field(default=None, max_length=1024)
    provider_code: str | None = Field(default=None, max_length=80)
    provider_name: str | None = Field(default=None, max_length=80)
    access_mode: str = Field(default="api", max_length=32)
    provider_id: int | None = None


@router.post("/models/discover", response_model=ApiResponse[dict])
async def discover_provider_models(
    request: Request,
    payload: DiscoverProviderModelsRequest,
    db: AsyncSession = Depends(get_db),
    current_admin: AdminUser = Depends(require_admin_roles(AdminRole.super_admin, AdminRole.model_admin)),
) -> ApiResponse[dict]:
    """Query upstream provider for available model IDs using the connection config above the form."""
    site_id = await current_admin_config_site_id(db, request, current_admin)
    base_url = (payload.base_url or "").strip()
    api_key = (payload.api_key or "").strip()
    provider_code = (payload.provider_code or "").strip()
    provider_name = (payload.provider_name or "").strip()
    access_mode = (payload.access_mode or "api").strip() or "api"
    auth_type = "bearer"
    timeout_seconds = 30

    if payload.provider_id is not None:
        provider = await db.scalar(
            select(ImageModelProvider).where(
                ImageModelProvider.id == payload.provider_id,
                ImageModelProvider.site_id == site_id,
            )
        )
        if provider is None:
            raise AppException(code=40404, message="供应商不存在", status_code=404)
        base_url = base_url or (provider.base_url or "").strip()
        provider_code = provider_code or (provider.code or "").strip()
        provider_name = provider_name or (provider.name or "").strip()
        access_mode = access_mode or (provider.access_mode or "api")
        auth_type = provider.auth_type or "bearer"
        timeout_seconds = int(provider.timeout_seconds or 30)
        if not api_key:
            api_key = (provider.encrypted_api_key or "").strip()

    if not base_url:
        raise AppException(code=40001, message="Base URL 不能为空")
    if not api_key:
        raise AppException(code=40001, message="请先填写 API Key（编辑时留空将使用已保存密钥）")

    result = await asyncio.to_thread(
        list_provider_models,
        base_url=base_url,
        api_key=api_key,
        provider_code=provider_code,
        provider_name=provider_name,
        access_mode=access_mode,
        auth_type=auth_type,
        timeout_seconds=timeout_seconds,
    )
    return ApiResponse.ok(result)


@router.post("/models", response_model=ApiResponse[AdminImageModelOut])
async def create_model(
    request: Request,
    payload: AdminImageModelCreate,
    db: AsyncSession = Depends(get_db),
    current_admin: AdminUser = Depends(require_admin_roles(AdminRole.super_admin, AdminRole.model_admin)),
) -> ApiResponse[AdminImageModelOut]:
    site_id = await current_admin_config_site_id(db, request, current_admin)
    model_data = normalized_image_model_payload(payload)
    model_data["site_id"] = site_id
    model_data["is_active"] = False
    # Resolve existing model first so shared-provider protection can exclude it
    # when POST is used as upsert-by-code (same path as PATCH update).
    model = await db.scalar(select(ImageModel).where(ImageModel.code == model_data["code"], ImageModel.site_id == site_id))
    provider = await provider_from_model_payload(
        db,
        payload,
        current_admin,
        site_id,
        require_api_key=True,
        exclude_model_id=model.id if model is not None else None,
    )
    model_data["provider_id"] = provider.id
    if model is None:
        model = ImageModel(**model_data)
        db.add(model)
        audit_action = "create_model"
        audit_resource_id = "pending"
    else:
        for key, value in model_data.items():
            setattr(model, key, value)
        audit_action = "update_model_by_code"
        audit_resource_id = model.id
    await db.flush()
    await sync_model_specs(
        db,
        model.id,
        model.site_id,
        payload.supported_resolution_ids,
        payload.supported_aspect_ratio_ids,
        payload.supported_duration_ids,
    )
    add_audit(db, current_admin, audit_action, "image_models", audit_resource_id, model.name)
    await db.commit()
    await db.refresh(model)
    return ApiResponse.ok(await model_out(db, model, provider))


@router.patch("/models/{model_id}", response_model=ApiResponse[AdminImageModelOut])
async def update_model(
    model_id: int,
    request: Request,
    payload: AdminImageModelCreate,
    db: AsyncSession = Depends(get_db),
    current_admin: AdminUser = Depends(require_admin_roles(AdminRole.super_admin, AdminRole.model_admin)),
) -> ApiResponse[AdminImageModelOut]:
    site_id = await current_admin_config_site_id(db, request, current_admin)
    result = await db.execute(
        select(ImageModel, ImageModelProvider)
        .join(ImageModelProvider, ImageModel.provider_id == ImageModelProvider.id)
        .where(ImageModel.id == model_id, ImageModel.site_id == site_id, ImageModelProvider.site_id == site_id)
    )
    row = result.first()
    if row is None:
        raise AppException(code=40404, message="模型不存在", status_code=404)
    model, _current_provider = row
    provider = await provider_from_model_payload(
        db,
        payload,
        current_admin,
        site_id,
        require_api_key=False,
        exclude_model_id=model.id,
    )
    model_data = normalized_image_model_payload(payload)
    model.provider_id = provider.id
    for key, value in model_data.items():
        if key != "is_active":
            setattr(model, key, value)
    await sync_model_specs(
        db,
        model.id,
        model.site_id,
        payload.supported_resolution_ids,
        payload.supported_aspect_ratio_ids,
        payload.supported_duration_ids,
    )
    add_audit(db, current_admin, "update_model", "image_models", model_id, model.name)
    await db.commit()
    await db.refresh(model)
    return ApiResponse.ok(await model_out(db, model, provider))


@router.delete("/models/{model_id}", response_model=ApiResponse[dict])
async def delete_model(
    model_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_admin: AdminUser = Depends(require_admin_roles(AdminRole.super_admin, AdminRole.model_admin)),
) -> ApiResponse[dict]:
    site_id = await current_admin_config_site_id(db, request, current_admin)
    model = await db.scalar(select(ImageModel).where(ImageModel.id == model_id, ImageModel.site_id == site_id))
    if model is None:
        raise AppException(code=40404, message="模型不存在", status_code=404)

    price_count = await db.scalar(
        select(func.count()).select_from(ModelPrice).where(ModelPrice.site_id == site_id, ModelPrice.model_id == model_id)
    )
    await db.execute(delete(ModelPrice).where(ModelPrice.site_id == site_id, ModelPrice.model_id == model_id))
    await db.execute(delete(ImageModelResolution).where(ImageModelResolution.model_id == model_id))
    await db.execute(delete(ImageModelAspectRatio).where(ImageModelAspectRatio.model_id == model_id))
    await db.execute(delete(ImageModelDuration).where(ImageModelDuration.model_id == model_id))
    model_name = model.name
    await db.delete(model)
    add_audit(db, current_admin, "delete_model", "image_models", model_id, f"{model_name}；删除价格 {price_count or 0} 条")
    await db.commit()
    return ApiResponse.ok({"id": model_id, "deleted_price_count": price_count or 0})


@router.patch("/models/{model_id}/specs", response_model=ApiResponse[AdminImageModelOut])
async def update_model_specs(
    model_id: int,
    request: Request,
    payload: dict,
    db: AsyncSession = Depends(get_db),
    current_admin: AdminUser = Depends(require_admin_roles(AdminRole.super_admin, AdminRole.model_admin)),
) -> ApiResponse[AdminImageModelOut]:
    site_id = await current_admin_config_site_id(db, request, current_admin)
    result = await db.execute(
        select(ImageModel, ImageModelProvider)
        .join(ImageModelProvider, ImageModel.provider_id == ImageModelProvider.id)
        .where(ImageModel.id == model_id, ImageModel.site_id == site_id, ImageModelProvider.site_id == site_id)
    )
    row = result.first()
    if row is None:
        raise AppException(code=40404, message="模型不存在", status_code=404)
    model, provider = row
    if model.is_active:
        raise AppException(code=40001, message="已启用模型不能直接修改支持规格，请先停用模型")
    resolution_ids = [int(value) for value in payload.get("supported_resolution_ids", [])]
    aspect_ratio_ids = [int(value) for value in payload.get("supported_aspect_ratio_ids", [])]
    duration_ids = [int(value) for value in payload.get("supported_duration_ids", [])]
    await sync_model_specs(db, model_id, model.site_id, resolution_ids, aspect_ratio_ids, duration_ids)
    add_audit(db, current_admin, "update_model_specs", "image_models", model_id, "更新模型支持规格")
    await db.commit()
    return ApiResponse.ok(await model_out(db, model, provider))


@router.post("/models/{model_id}/test", response_model=ApiResponse[dict])
async def model_test(
    model_id: int,
    request: Request,
    payload: dict,
    db: AsyncSession = Depends(get_db),
    current_admin: AdminUser = Depends(require_admin_roles(AdminRole.super_admin, AdminRole.model_admin)),
) -> ApiResponse[dict]:
    site_id = await current_admin_config_site_id(db, request, current_admin)
    result = await db.execute(
        select(ImageModel, ImageModelProvider)
        .join(ImageModelProvider, ImageModel.provider_id == ImageModelProvider.id)
        .where(ImageModel.id == model_id, ImageModel.site_id == site_id, ImageModelProvider.site_id == site_id)
    )
    row = result.first()
    if row is None:
        raise AppException(code=40404, message="模型不存在", status_code=404)
    model, provider = row
    if not model.is_active:
        return ApiResponse.ok({"status": "failed", "duration_ms": 0, "summary": "模型未启用，无法测试"})
    if not provider.is_active:
        return ApiResponse.ok({"status": "failed", "duration_ms": 0, "summary": "供应商未启用，无法测试"})
    prompt = str(payload.get("prompt") or "").strip()
    started_at = time.perf_counter()
    test_result = await asyncio.to_thread(call_image_generation_test, model, provider, prompt)
    duration_ms = int((time.perf_counter() - started_at) * 1000)
    add_audit(db, current_admin, "test_model", "image_models", model_id, test_result["summary"])
    await db.commit()
    return ApiResponse.ok({"duration_ms": duration_ms, **test_result})


@router.patch("/models/{model_id}/status", response_model=ApiResponse[dict])
async def model_status(
    model_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_admin: AdminUser = Depends(require_admin_roles(AdminRole.super_admin, AdminRole.model_admin)),
) -> ApiResponse[dict]:
    site_id = await current_admin_config_site_id(db, request, current_admin)
    model = await db.scalar(select(ImageModel).where(ImageModel.id == model_id, ImageModel.site_id == site_id))
    if model is None:
        raise AppException(code=40404, message="模型不存在", status_code=404)
    next_active = not model.is_active
    if next_active:
        missing = await missing_price_combinations(db, model)
        if missing:
            raise AppException(
                code=40003,
                message=missing_price_message(missing),
                status_code=400,
                data={"missing_count": len(missing), "missing_combinations": missing[:50]},
            )
    model.is_active = next_active
    add_audit(db, current_admin, "toggle_model", "image_models", model_id, f"is_active={model.is_active}")
    await db.commit()
    return ApiResponse.ok({"id": model_id, "is_active": model.is_active})


@router.patch("/models/{model_id}/visibility", response_model=ApiResponse[dict])
async def model_visibility(
    model_id: int,
    request: Request,
    payload: dict,
    db: AsyncSession = Depends(get_db),
    current_admin: AdminUser = Depends(require_admin_roles(AdminRole.super_admin, AdminRole.model_admin)),
) -> ApiResponse[dict]:
    site_id = await current_admin_config_site_id(db, request, current_admin)
    model = await db.scalar(select(ImageModel).where(ImageModel.id == model_id, ImageModel.site_id == site_id))
    if model is None:
        raise AppException(code=40404, message="模型不存在", status_code=404)
    is_public = bool(payload.get("is_public"))
    model.is_public = is_public
    add_audit(db, current_admin, "update_model_visibility", "image_models", model_id, f"is_public={is_public}")
    await db.commit()
    return ApiResponse.ok({"id": model_id, "is_public": is_public})


@router.get("/model-prices", response_model=ApiResponse[dict])
async def model_prices(
    request: Request,
    keyword: str = "",
    model_id: int | None = Query(default=None, ge=1),
    active_only: bool = False,
    page_no: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_admin: AdminUser = Depends(require_admin_roles(AdminRole.super_admin, AdminRole.model_admin)),
) -> ApiResponse[dict]:
    site_id = await current_admin_config_site_id(db, request, current_admin)
    condition = and_(ModelPrice.site_id == site_id, ImageModel.site_id == site_id)
    if model_id is not None:
        condition = and_(condition, ModelPrice.model_id == model_id)
    if active_only:
        condition = and_(condition, ModelPrice.is_active.is_(True))
    if keyword:
        like = f"%{keyword.strip()}%"
        condition = and_(condition, or_(ImageModel.name.ilike(like), ModelPrice.work_type.ilike(like), ModelPrice.resolution.ilike(like), ModelPrice.aspect_ratio.ilike(like)))
    joined = ModelPrice.__table__.join(ImageModel.__table__, ModelPrice.model_id == ImageModel.id)
    total = await db.scalar(select(func.count()).select_from(joined).where(condition))
    result = await db.execute(
        select(ModelPrice, ImageModel)
        .join(ImageModel, ModelPrice.model_id == ImageModel.id)
        .where(condition)
        .order_by(desc(ModelPrice.is_active), desc(ModelPrice.version), desc(ModelPrice.id))
        .limit(page_size)
        .offset((page_no - 1) * page_size)
    )
    return ApiResponse.ok(
        {"items": [
            {
                "id": price.id,
                "model_id": price.model_id,
                "model_name": model.name,
                "work_type": price.work_type,
                "resolution": price.resolution,
                "aspect_ratio": price.aspect_ratio,
                "output_count": price.output_count,
                "credit_cost": price.credit_cost,
                "fixed_surcharge": price.fixed_surcharge,
                "version": price.version,
                "effective_at": iso(price.effective_at),
                "is_active": price.is_active,
                "change_reason": price.change_reason,
            }
            for price, model in result
        ], "total": total or 0, "page": page_no, "page_size": page_size}
    )


def parse_surcharge(value):
    if value is None:
        return None  # Existing clients changing only the base retain the surcharge.
    try:
        fee = Decimal(str(value))
        if not fee.is_finite() or fee < 0 or fee > 100000000 or fee != fee.quantize(Decimal("0.01")):
            raise ValueError()
        return fee
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise AppException(code=40001, message="固定加价须为 0 至 1 亿之间的数字，最多两位小数") from exc


def explicit_model_price_entries(payload: dict, output_count: int) -> list[dict] | None:
    raw_entries = payload.get("price_entries")
    if raw_entries is None:
        return None
    if not isinstance(raw_entries, list) or not raw_entries:
        raise AppException(code=40001, message="请至少提交一个价格变更")

    entries: list[dict] = []
    seen_keys: set[tuple[str, str, str, int]] = set()
    for raw_entry in raw_entries:
        if not isinstance(raw_entry, dict):
            raise AppException(code=40001, message="价格变更格式不正确")
        work_type = str(raw_entry.get("work_type") or "").strip()
        resolution = str(raw_entry.get("resolution") or "").strip()
        aspect_ratio = str(raw_entry.get("aspect_ratio") or "").strip()
        raw_credit_cost = raw_entry.get("credit_cost")
        if isinstance(raw_credit_cost, bool) or (
            isinstance(raw_credit_cost, float) and not raw_credit_cost.is_integer()
        ):
            raise AppException(code=40001, message="积分消耗必须是正整数")
        try:
            credit_cost = int(raw_credit_cost or 0)
        except (TypeError, ValueError) as exc:
            raise AppException(code=40001, message="积分消耗必须是正整数") from exc
        if not work_type or not resolution or not aspect_ratio:
            raise AppException(code=40001, message="价格变更缺少能力或规格")
        if credit_cost <= 0:
            raise AppException(code=40001, message="积分消耗必须大于 0")
        key = (work_type, resolution, aspect_ratio, output_count)
        if key in seen_keys:
            raise AppException(code=40001, message=f"价格变更包含重复规格：{work_type} / {resolution} / {aspect_ratio}")
        seen_keys.add(key)
        entries.append(
            {
                "work_type": work_type,
                "resolution": resolution,
                "aspect_ratio": aspect_ratio,
                "output_count": output_count,
                "credit_cost": credit_cost,
                **({"fixed_surcharge": parse_surcharge(raw_entry["fixed_surcharge"])} if "fixed_surcharge" in raw_entry else {}),
            }
        )
    return entries


def model_price_identity_condition(
    *,
    site_id: int,
    model_id: int,
    work_type: str,
    resolution: str,
    aspect_ratio: str,
    output_count: int,
):
    return and_(
        ModelPrice.site_id == site_id,
        ModelPrice.model_id == model_id,
        ModelPrice.work_type == work_type,
        ModelPrice.resolution == resolution,
        ModelPrice.aspect_ratio == aspect_ratio,
        ModelPrice.output_count == output_count,
    )


async def create_model_price_version(
    db: AsyncSession,
    *,
    site_id: int,
    model_id: int,
    work_type: str,
    resolution: str,
    aspect_ratio: str,
    output_count: int,
    credit_cost: int,
    reason: str,
    fixed_surcharge: Decimal | None = None,
) -> tuple[ModelPrice, list[int], bool]:
    identity_condition = model_price_identity_condition(
        site_id=site_id,
        model_id=model_id,
        work_type=work_type,
        resolution=resolution,
        aspect_ratio=aspect_ratio,
        output_count=output_count,
    )
    active_prices = list(
        (
            await db.scalars(
                select(ModelPrice)
                .where(identity_condition, ModelPrice.is_active.is_(True))
                .order_by(ModelPrice.version.desc(), ModelPrice.id.desc())
                .with_for_update()
            )
        ).all()
    )
    if fixed_surcharge is None:
        fixed_surcharge = active_prices[0].fixed_surcharge if active_prices else Decimal("0")
    if len(active_prices) == 1 and active_prices[0].credit_cost == credit_cost and active_prices[0].fixed_surcharge == fixed_surcharge:
        return active_prices[0], [], False

    replaced_ids = [price.id for price in active_prices]
    now = datetime.now(timezone.utc)
    for active_price in active_prices:
        active_price.is_active = False
        active_price.updated_at = now

    latest_version = int(
        await db.scalar(select(func.coalesce(func.max(ModelPrice.version), 0)).where(identity_condition)) or 0
    )
    price = ModelPrice(
        site_id=site_id,
        model_id=model_id,
        work_type=work_type,
        resolution=resolution,
        aspect_ratio=aspect_ratio,
        output_count=output_count,
        credit_cost=credit_cost,
        fixed_surcharge=fixed_surcharge,
        version=latest_version + 1,
        is_active=True,
        change_reason=reason,
    )
    db.add(price)
    await db.flush()
    return price, replaced_ids, True


@router.post("/model-prices", response_model=ApiResponse[dict])
async def create_model_price(
    request: Request,
    payload: dict,
    db: AsyncSession = Depends(get_db),
    current_admin: AdminUser = Depends(require_admin_roles(AdminRole.super_admin, AdminRole.model_admin)),
) -> ApiResponse[dict]:
    site_id = await current_admin_config_site_id(db, request, current_admin)
    reason = str(payload.get("change_reason") or "").strip()
    if not reason:
        raise AppException(code=40001, message="价格变更必须填写原因")
    model_id = int(payload.get("model_id") or 0)
    model = await db.scalar(select(ImageModel).where(ImageModel.id == model_id, ImageModel.site_id == site_id))
    if model is None:
        raise AppException(code=40404, message="模型不存在", status_code=404)
    filters = {
        "model_id": model_id,
        "work_type": str(payload.get("work_type") or model.work_type),
        "resolution": str(payload.get("resolution") or ""),
        "aspect_ratio": str(payload.get("aspect_ratio") or ""),
        "output_count": int(payload.get("output_count") or 1),
    }
    model_work_type_set = set(model_work_types(model))
    if filters["work_type"] not in model_work_type_set:
        raise AppException(code=40001, message="该模型不支持所选能力")
    supported_resolutions, supported_aspect_ratios, supported_durations = await model_supported_specs(db, model.id)
    if filters["resolution"] not in {spec["code"] for spec in supported_resolutions}:
        raise AppException(code=40001, message="该模型不支持所选分辨率")
    if is_video_model(model):
        if filters["aspect_ratio"] not in {spec["code"] for spec in supported_durations}:
            raise AppException(code=40001, message="该模型不支持所选时长")
        filters["output_count"] = 1
    elif filters["aspect_ratio"] not in {spec["code"] for spec in supported_aspect_ratios}:
        raise AppException(code=40001, message="该模型不支持所选尺寸")
    credit_cost = int(payload.get("credit_cost") or 0)
    if credit_cost <= 0:
        raise AppException(code=40001, message="积分消耗必须大于 0")
    price, replaced_ids, created = await create_model_price_version(
        db,
        site_id=site_id,
        model_id=filters["model_id"],
        work_type=filters["work_type"],
        resolution=filters["resolution"],
        aspect_ratio=filters["aspect_ratio"],
        output_count=filters["output_count"],
        credit_cost=credit_cost,
        fixed_surcharge=parse_surcharge(payload.get("fixed_surcharge")),
        reason=reason,
    )
    audit_reason = reason if created else f"{reason}；价格未变化"
    add_audit(
        db,
        current_admin,
        "create_model_price_version" if created else "keep_model_price",
        "image_model_prices",
        price.id,
        f"{audit_reason}；替换版本={','.join(str(item) for item in replaced_ids) or 'none'}",
    )
    await db.commit()
    return ApiResponse.ok({"id": price.id, "created": created, "replaced_ids": replaced_ids})


@router.post("/model-prices/batch", response_model=ApiResponse[dict])
async def create_model_prices_batch(
    request: Request,
    payload: dict,
    db: AsyncSession = Depends(get_db),
    current_admin: AdminUser = Depends(require_admin_roles(AdminRole.super_admin, AdminRole.model_admin)),
) -> ApiResponse[dict]:
    site_id = await current_admin_config_site_id(db, request, current_admin)
    reason = str(payload.get("change_reason") or "").strip()
    if not reason:
        raise AppException(code=40001, message="价格变更必须填写原因")
    model_id = int(payload.get("model_id") or 0)
    model = await db.scalar(select(ImageModel).where(ImageModel.id == model_id, ImageModel.site_id == site_id))
    if model is None:
        raise AppException(code=40404, message="模型不存在", status_code=404)

    work_types = [str(item).strip() for item in payload.get("work_types") or [] if str(item).strip()]
    resolutions = [str(item).strip() for item in payload.get("resolutions") or [] if str(item).strip()]
    aspect_ratios = [str(item).strip() for item in payload.get("aspect_ratios") or [] if str(item).strip()]
    output_count = int(payload.get("output_count") or 1)
    price_matrix = payload.get("price_matrix") or {}
    text_model = is_text_model(model)
    video_model = is_video_model(model)
    if text_model:
        if not work_types:
            work_types = ["text"]
        if not resolutions:
            resolutions = ["default"]
        if not aspect_ratios:
            aspect_ratios = ["default"]
        output_count = 1
    if video_model:
        # 视频价格矩阵：能力 × 分辨率 × 时长；时长写入 aspect_ratio 字段，output_count 固定为 1。
        output_count = 1
    explicit_entries = explicit_model_price_entries(payload, output_count)
    if explicit_entries is not None:
        work_types = list(dict.fromkeys(entry["work_type"] for entry in explicit_entries))
        resolutions = list(dict.fromkeys(entry["resolution"] for entry in explicit_entries))
        aspect_ratios = list(dict.fromkeys(entry["aspect_ratio"] for entry in explicit_entries))
    if not work_types or not resolutions or not aspect_ratios:
        raise AppException(
            code=40001,
            message="请至少选择一个能力、分辨率和时长" if video_model else "请至少选择一个能力、分辨率和尺寸",
        )
    if output_count <= 0:
        raise AppException(code=40001, message="输出张数必须大于 0")

    model_work_type_set = set(model_work_types(model))
    unsupported_work_types = [item for item in work_types if item not in model_work_type_set]
    if unsupported_work_types:
        raise AppException(code=40001, message=f"该模型不支持能力：{', '.join(unsupported_work_types)}")

    if not text_model:
        supported_resolutions, supported_aspect_ratios, supported_durations = await model_supported_specs(db, model.id)
        supported_resolution_codes = {spec["code"] for spec in supported_resolutions}
        unsupported_resolutions = [item for item in resolutions if item not in supported_resolution_codes]
        if unsupported_resolutions:
            raise AppException(code=40001, message=f"该模型不支持分辨率：{', '.join(unsupported_resolutions)}")
        if video_model:
            supported_duration_codes = {spec["code"] for spec in supported_durations}
            unsupported_durations = [item for item in aspect_ratios if item not in supported_duration_codes]
            if unsupported_durations:
                raise AppException(code=40001, message=f"该模型不支持时长：{', '.join(unsupported_durations)}")
        else:
            supported_aspect_ratio_codes = {spec["code"] for spec in supported_aspect_ratios}
            unsupported_aspect_ratios = [item for item in aspect_ratios if item not in supported_aspect_ratio_codes]
            if unsupported_aspect_ratios:
                raise AppException(code=40001, message=f"该模型不支持尺寸：{', '.join(unsupported_aspect_ratios)}")

    price_entries: list[dict] = []
    if explicit_entries is not None:
        price_entries = explicit_entries
    else:
        missing_prices: list[str] = []
        for work_type in work_types:
            work_type_prices = price_matrix.get(work_type) or {}
            for resolution in resolutions:
                credit_cost = int(work_type_prices.get(resolution) or 0)
                if credit_cost <= 0:
                    missing_prices.append(f"{work_type} / {resolution}")
                    continue
                for aspect_ratio in aspect_ratios:
                    price_entries.append(
                        {
                            "work_type": work_type,
                            "resolution": resolution,
                            "aspect_ratio": aspect_ratio,
                            "output_count": output_count,
                            "credit_cost": credit_cost,
                            "fixed_surcharge": parse_surcharge(payload.get("fixed_surcharge")),
                        }
                    )
        if missing_prices:
            raise AppException(code=40001, message=f"请填写有效积分：{'; '.join(missing_prices)}")

    created_ids: list[int] = []
    replaced_ids: list[int] = []
    created_count = 0
    unchanged_count = 0
    for entry in price_entries:
        price, entry_replaced_ids, created = await create_model_price_version(
            db,
            site_id=site_id,
            model_id=model_id,
            work_type=entry["work_type"],
            resolution=entry["resolution"],
            aspect_ratio=entry["aspect_ratio"],
            output_count=entry["output_count"],
            credit_cost=entry["credit_cost"],
            fixed_surcharge=entry.get("fixed_surcharge"),
            reason=reason,
        )
        if created:
            created_ids.append(price.id)
            created_count += 1
            replaced_ids.extend(entry_replaced_ids)
        else:
            unchanged_count += 1

    add_audit(
        db,
        current_admin,
        "create_model_price_versions_batch",
        "image_model_prices",
        str(model_id),
        f"{reason}；新增版本 {created_count} 条，替换 {len(replaced_ids)} 条，未变化 {unchanged_count} 条",
    )
    await db.commit()
    return ApiResponse.ok(
        {
            "created_count": created_count,
            "updated_count": len(replaced_ids),
            "unchanged_count": unchanged_count,
            "ids": created_ids,
            "updated_ids": replaced_ids,
        }
    )


@router.patch("/model-prices/batch-status", response_model=ApiResponse[dict])
async def model_prices_batch_status(
    request: Request,
    payload: dict,
    db: AsyncSession = Depends(get_db),
    current_admin: AdminUser = Depends(require_admin_roles(AdminRole.super_admin, AdminRole.model_admin)),
) -> ApiResponse[dict]:
    site_id = await current_admin_config_site_id(db, request, current_admin)
    all_active = bool(payload.get("all_active"))
    price_ids = [int(item) for item in payload.get("price_ids") or [] if int(item) > 0]
    if not all_active and not price_ids:
        raise AppException(code=40001, message="请选择要停用的价格")

    condition = and_(ModelPrice.site_id == site_id, ModelPrice.is_active.is_(True))
    action_target = "all_active"
    if not all_active:
        condition = and_(condition, ModelPrice.id.in_(price_ids))
        action_target = ",".join(str(item) for item in price_ids[:20])

    result = await db.execute(
        update(ModelPrice)
        .where(condition)
        .values(is_active=False, updated_at=datetime.now(timezone.utc))
        .returning(ModelPrice.id)
    )
    updated_ids = [row[0] for row in result.all()]
    add_audit(db, current_admin, "disable_model_prices_batch", "image_model_prices", action_target, f"disabled_count={len(updated_ids)}")
    await db.commit()
    return ApiResponse.ok({"updated_count": len(updated_ids), "ids": updated_ids})


@router.patch("/model-prices/{price_id}/status", response_model=ApiResponse[dict])
async def model_price_status(
    price_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_admin: AdminUser = Depends(require_admin_roles(AdminRole.super_admin, AdminRole.model_admin)),
) -> ApiResponse[dict]:
    site_id = await current_admin_config_site_id(db, request, current_admin)
    price = await db.scalar(select(ModelPrice).where(ModelPrice.id == price_id, ModelPrice.site_id == site_id))
    if price is None:
        raise AppException(code=40404, message="价格版本不存在", status_code=404)
    next_active = not price.is_active
    replaced_ids: list[int] = []
    if next_active:
        identity_condition = model_price_identity_condition(
            site_id=site_id,
            model_id=price.model_id,
            work_type=price.work_type,
            resolution=price.resolution,
            aspect_ratio=price.aspect_ratio,
            output_count=price.output_count,
        )
        result = await db.execute(
            update(ModelPrice)
            .where(identity_condition, ModelPrice.id != price.id, ModelPrice.is_active.is_(True))
            .values(is_active=False, updated_at=datetime.now(timezone.utc))
            .returning(ModelPrice.id)
        )
        replaced_ids = [row[0] for row in result.all()]
    price.is_active = next_active
    add_audit(
        db,
        current_admin,
        "toggle_model_price",
        "image_model_prices",
        price_id,
        f"is_active={price.is_active}；替换版本={','.join(str(item) for item in replaced_ids) or 'none'}",
    )
    await db.commit()
    return ApiResponse.ok({"id": price_id, "is_active": price.is_active, "replaced_ids": replaced_ids})


@router.get("/materials", response_model=ApiResponse[dict])
async def material_assets(
    request: Request,
    keyword: str = "",
    asset_type: str = "all",
    status: str = "all",
    page_no: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_admin: AdminUser = Depends(require_admin_roles(AdminRole.super_admin, AdminRole.operator)),
) -> ApiResponse[dict]:
    site_id = await current_admin_config_site_id(db, request, current_admin)
    condition = material_assets_table.c.site_id == site_id
    if asset_type != "all":
        condition = and_(condition, material_assets_table.c.asset_type == asset_type)
    if status == "active":
        condition = and_(condition, material_assets_table.c.is_active.is_(True))
    elif status == "inactive":
        condition = and_(condition, material_assets_table.c.is_active.is_(False))
    if keyword.strip():
        like = f"%{keyword.strip()}%"
        condition = and_(condition, or_(material_assets_table.c.title.ilike(like), material_assets_table.c.description.ilike(like), material_assets_table.c.file_url.ilike(like)))
    total = await db.scalar(select(func.count()).select_from(material_assets_table).where(condition))
    result = await db.execute(
        select(material_assets_table)
        .where(condition)
        .order_by(material_assets_table.c.sort_order.asc(), desc(material_assets_table.c.created_at), desc(material_assets_table.c.id))
        .offset((page_no - 1) * page_size)
        .limit(page_size)
    )
    return ApiResponse.ok({"items": [material_asset_out(row) for row in result.mappings().all()], "total": total or 0, "page": page_no, "page_size": page_size})


@router.post("/materials/upload-token", response_model=ApiResponse[dict])
async def material_upload_token(
    payload: MaterialUploadTokenRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_admin: AdminUser = Depends(require_admin_roles(AdminRole.super_admin, AdminRole.operator, AdminRole.finance, AdminRole.model_admin)),
) -> ApiResponse[dict]:
    site_id = await current_admin_config_site_id(db, request, current_admin)
    filename = normalize_material_filename(payload.filename)
    prefix = settings.material_asset_prefix.strip().strip("/") or "material-assets"
    key = f"{prefix}/site-{site_id}/{payload.asset_type}/{filename}"
    cdn_base = settings.qiniu_cdn_base_url.rstrip("/")
    return ApiResponse.ok({"upload_url": settings.qiniu_upload_host.rstrip("/"), "token": qiniu_upload_token(key), "key": key, "public_url": f"{cdn_base}/{key}"})


def _announcement_image_type(content: bytes, submitted_mime_type: str, filename: str) -> tuple[str, str]:
    normalized_type = (submitted_mime_type or "").split(";", 1)[0].strip().lower()
    detected_type = ""
    if content.startswith(b"\xff\xd8\xff"):
        detected_type = "image/jpeg"
    elif content.startswith(b"\x89PNG\r\n\x1a\n"):
        detected_type = "image/png"
    elif len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        detected_type = "image/webp"
    elif content.startswith((b"GIF87a", b"GIF89a")):
        detected_type = "image/gif"
    mime_type = detected_type or normalized_type
    extension = ANNOUNCEMENT_IMAGE_TYPES.get(mime_type)
    if not extension:
        raise AppException(code=40022, message="仅支持 JPG、PNG、WEBP、GIF 图片", status_code=400)
    submitted_extension = Path(filename or "").suffix.lower()
    if submitted_extension and submitted_extension not in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
        raise AppException(code=40023, message="图片扩展名不支持", status_code=400)
    return mime_type, extension


def _store_local_announcement_image(*, content: bytes, mime_type: str, extension: str, site_id: int) -> dict[str, str | int]:
    if not all((settings.minio_endpoint.strip(), settings.minio_access_key.strip(), settings.minio_secret_key.strip(), settings.minio_bucket.strip(), settings.minio_public_endpoint.strip())):
        raise AppException(code=50020, message="本地图片存储配置未完成", status_code=503)

    from minio import Minio

    prefix = settings.material_asset_prefix.strip().strip("/") or "material-assets"
    key = f"{prefix}/site-{site_id}/announcement/{uuid4().hex}{extension}"
    client = Minio(
        settings.minio_endpoint.strip(),
        access_key=settings.minio_access_key.strip(),
        secret_key=settings.minio_secret_key.strip(),
        secure=settings.minio_secure,
    )
    try:
        bucket = settings.minio_bucket.strip()
        if not client.bucket_exists(bucket):
            client.make_bucket(bucket)
        if settings.minio_public_read:
            policy = {
                "Version": "2012-10-17",
                "Statement": [{
                    "Effect": "Allow",
                    "Principal": {"AWS": ["*"]},
                    "Action": ["s3:GetObject"],
                    "Resource": [f"arn:aws:s3:::{bucket}/*"],
                }],
            }
            client.set_bucket_policy(bucket, json.dumps(policy))
        client.put_object(
            bucket,
            key,
            BytesIO(content),
            length=len(content),
            content_type=mime_type,
        )
    except Exception as exc:
        raise AppException(code=50020, message="本地图片存储服务暂不可用", status_code=503) from exc

    return {
        "public_url": f"{settings.minio_public_endpoint.rstrip('/')}/{bucket}/{urllib.parse.quote(key, safe='/')}",
        "key": key,
        "mime_type": mime_type,
        "file_size": len(content),
    }


@router.post("/materials/local-upload", response_model=ApiResponse[dict])
async def material_local_upload(
    request: Request,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_admin: AdminUser = Depends(require_admin_roles(AdminRole.super_admin, AdminRole.operator, AdminRole.finance, AdminRole.model_admin)),
) -> ApiResponse[dict]:
    site_id = await current_admin_config_site_id(db, request, current_admin)
    content = await file.read(ANNOUNCEMENT_IMAGE_MAX_BYTES + 1)
    if not content:
        raise AppException(code=40020, message="请选择要上传的图片", status_code=400)
    if len(content) > ANNOUNCEMENT_IMAGE_MAX_BYTES:
        raise AppException(code=40021, message="图片不能超过 10MB", status_code=400)
    mime_type, extension = _announcement_image_type(content, file.content_type or "", file.filename or "")
    result = await asyncio.to_thread(
        _store_local_announcement_image,
        content=content,
        mime_type=mime_type,
        extension=extension,
        site_id=site_id,
    )
    return ApiResponse.ok(result, "本地图片上传成功")


@router.post("/materials", response_model=ApiResponse[dict])
async def create_material_asset(
    request: Request,
    payload: MaterialAssetRequest,
    db: AsyncSession = Depends(get_db),
    current_admin: AdminUser = Depends(require_admin_roles(AdminRole.super_admin, AdminRole.operator)),
) -> ApiResponse[dict]:
    site_id = await current_admin_config_site_id(db, request, current_admin)
    values = {
        "site_id": site_id,
        "asset_type": payload.asset_type,
        "title": payload.title.strip(),
        "description": payload.description.strip(),
        "file_url": payload.file_url.strip(),
        "cover_url": payload.cover_url.strip(),
        "mime_type": payload.mime_type.strip(),
        "file_size": payload.file_size,
        "sort_order": payload.sort_order,
        "is_active": payload.is_active,
        "created_by": current_admin.id,
        "updated_by": current_admin.id,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }
    result = await db.execute(insert(material_assets_table).values(**values).returning(material_assets_table))
    add_audit(db, current_admin, "create_material_asset", "material_assets", "pending", values["title"])
    await db.commit()
    return ApiResponse.ok(material_asset_out(result.mappings().first()), "素材已保存")


@router.patch("/materials/{material_id}", response_model=ApiResponse[dict])
async def update_material_asset(
    material_id: int,
    request: Request,
    payload: MaterialAssetRequest,
    db: AsyncSession = Depends(get_db),
    current_admin: AdminUser = Depends(require_admin_roles(AdminRole.super_admin, AdminRole.operator)),
) -> ApiResponse[dict]:
    site_id = await current_admin_config_site_id(db, request, current_admin)
    existing_id = await db.scalar(select(material_assets_table.c.id).where(material_assets_table.c.id == material_id, material_assets_table.c.site_id == site_id))
    if existing_id is None:
        raise AppException(code=404, message="素材不存在", status_code=404)
    values = {
        "asset_type": payload.asset_type,
        "title": payload.title.strip(),
        "description": payload.description.strip(),
        "file_url": payload.file_url.strip(),
        "cover_url": payload.cover_url.strip(),
        "mime_type": payload.mime_type.strip(),
        "file_size": payload.file_size,
        "sort_order": payload.sort_order,
        "is_active": payload.is_active,
        "updated_by": current_admin.id,
        "updated_at": datetime.now(timezone.utc),
    }
    await db.execute(update(material_assets_table).where(material_assets_table.c.id == material_id, material_assets_table.c.site_id == site_id).values(**values))
    add_audit(db, current_admin, "update_material_asset", "material_assets", material_id, values["title"])
    await db.commit()
    row = (await db.execute(select(material_assets_table).where(material_assets_table.c.id == material_id, material_assets_table.c.site_id == site_id))).mappings().first()
    return ApiResponse.ok(material_asset_out(row), "素材已更新")


@router.patch("/materials/{material_id}/status", response_model=ApiResponse[dict])
async def toggle_material_asset(
    material_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_admin: AdminUser = Depends(require_admin_roles(AdminRole.super_admin, AdminRole.operator)),
) -> ApiResponse[dict]:
    site_id = await current_admin_config_site_id(db, request, current_admin)
    row = (await db.execute(select(material_assets_table).where(material_assets_table.c.id == material_id, material_assets_table.c.site_id == site_id))).mappings().first()
    if row is None:
        raise AppException(code=404, message="素材不存在", status_code=404)
    await db.execute(
        update(material_assets_table)
        .where(material_assets_table.c.id == material_id, material_assets_table.c.site_id == site_id)
        .values(is_active=not bool(row.is_active), updated_by=current_admin.id, updated_at=datetime.now(timezone.utc))
    )
    add_audit(db, current_admin, "toggle_material_asset", "material_assets", material_id, f"is_active={not bool(row.is_active)}")
    await db.commit()
    updated_row = (await db.execute(select(material_assets_table).where(material_assets_table.c.id == material_id, material_assets_table.c.site_id == site_id))).mappings().first()
    return ApiResponse.ok(material_asset_out(updated_row), "素材状态已更新")


@router.get("/image-tasks", response_model=ApiResponse[dict])
async def image_tasks(
    keyword: str = Query("", max_length=200),
    page_no: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: str | None = Query(None, pattern="^(pending|queued|running|succeeded|failed|refunded)$"),
    user_id: int | None = Query(None, ge=1, le=9223372036854775807),
    username: str = Query("", max_length=100),
    gallery_review_status: str | None = Query(None, pattern="^(pending|approved|rejected|none)$"),
    db: AsyncSession = Depends(get_db),
    current_admin: AdminUser = Depends(require_admin_roles(AdminRole.super_admin, AdminRole.operator, AdminRole.finance, AdminRole.model_admin)),
) -> ApiResponse[dict]:
    joined = outerjoin(image_tasks_table, users_table, image_tasks_table.c.user_id == users_table.c.id)
    joined = outerjoin(joined, ImageModel.__table__, image_tasks_table.c.model_id == ImageModel.id)
    condition = scoped_condition(current_admin, image_tasks_table.c.site_id)
    if gallery_review_status:
        requested = gallery_review_status in {"pending", "approved"}
        reviewed = gallery_review_status in {"approved", "rejected"}
        condition = and_(condition, image_tasks_table.c.deleted_at.is_(None),
                         image_tasks_table.c.is_gallery_featured.is_(requested),
                         image_tasks_table.c.gallery_featured_by.is_not(None) if reviewed else image_tasks_table.c.gallery_featured_by.is_(None))
        if gallery_review_status == "approved":
            condition = and_(condition, image_tasks_table.c.status == "succeeded", image_tasks_table.c.output_image_url.is_not(None))
    if status:
        statuses = ("failed", "refunded") if status == "failed" else (status,)
        condition = and_(condition, image_tasks_table.c.status.in_(statuses))
    if user_id is not None:
        condition = and_(condition, image_tasks_table.c.user_id == user_id)
    if username.strip():
        user_like = username.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        condition = and_(condition, users_table.c.username.ilike(f"%{user_like}%", escape="\\"))
    if keyword.strip():
        like = f"%{keyword.strip()}%"
        condition = and_(condition, or_(image_tasks_table.c.task_no.ilike(like), users_table.c.username.ilike(like), ImageModel.name.ilike(like), image_tasks_table.c.prompt.ilike(like)))
    try:
        total = await db.scalar(select(func.count()).select_from(joined).where(condition))
        result = await db.execute(
            select(
                image_tasks_table.c.id,
                image_tasks_table.c.task_no,
                image_tasks_table.c.user_id,
                users_table.c.username,
                ImageModel.name.label("model_name"),
                image_tasks_table.c.work_type,
                image_tasks_table.c.status,
                image_tasks_table.c.credit_cost,
                image_tasks_table.c.prompt,
                image_tasks_table.c.quality,
                image_tasks_table.c.failure_message,
                image_tasks_table.c.input_image_url,
                image_tasks_table.c.output_image_url,
                image_tasks_table.c.is_gallery_featured,
                image_tasks_table.c.gallery_featured_by,
                image_tasks_table.c.deleted_at,
                image_tasks_table.c.gallery_title,
                image_tasks_table.c.gallery_sort_order,
                image_tasks_table.c.gallery_featured_at,
                image_tasks_table.c.created_at,
                image_tasks_table.c.worker_started_at,
                image_tasks_table.c.finished_at,
            )
            .select_from(joined)
            .where(condition)
            .order_by(desc(image_tasks_table.c.created_at), desc(image_tasks_table.c.id))
            .limit(page_size)
            .offset((page_no - 1) * page_size)
        )
    except (OperationalError, ProgrammingError) as error:
        await db.rollback()
        if is_missing_shared_table_error(error, "image_tasks"):
            return ApiResponse.ok(page([], page_no, page_size))
        raise
    return ApiResponse.ok(
        {"items": [
            {
                "id": row.id,
                "task_no": row.task_no,
                "user_id": row.user_id,
                "username": row.username or "-",
                "model_name": row.model_name or "-",
                "work_type": row.work_type or "-",
                "status": row.status,
                "credit_cost": row.credit_cost,
                "prompt": row.prompt,
                "quality": row.quality or "auto",
                "failure_message": row.failure_message,
                "input_image_url": row.input_image_url,
                "output_image_url": row.output_image_url,
                "is_gallery_featured": bool(row.is_gallery_featured and row.gallery_featured_by is not None and row.deleted_at is None and row.status == "succeeded" and row.output_image_url),
                "gallery_review_status": ("approved" if row.gallery_featured_by is not None else "pending") if row.is_gallery_featured else ("rejected" if row.gallery_featured_by is not None else "none"),
                "deleted_at": iso(row.deleted_at),
                "gallery_title": row.gallery_title,
                "gallery_sort_order": row.gallery_sort_order or 0,
                "gallery_featured_at": iso(row.gallery_featured_at),
                "created_at": iso(row.created_at),
                "worker_started_at": iso(row.worker_started_at),
                "finished_at": iso(row.finished_at),
                "queue_duration_seconds": duration_seconds(row.created_at, row.worker_started_at),
                "generation_duration_seconds": duration_seconds(row.worker_started_at, row.finished_at),
                "total_duration_seconds": duration_seconds(row.created_at, row.finished_at),
            }
            for row in result
        ], "total": total or 0, "page": page_no, "page_size": page_size}
    )


@router.post("/image-tasks/{task_id}/refund", response_model=ApiResponse[dict])
async def refund_task(
    task_id: int,
    payload: dict,
    db: AsyncSession = Depends(get_db),
    current_admin: AdminUser = Depends(require_admin_roles(AdminRole.super_admin, AdminRole.operator, AdminRole.finance)),
) -> ApiResponse[dict]:
    reason = str(payload.get("reason") or "").strip()
    if not reason:
        raise AppException(code=40001, message="退款必须填写原因")
    task_exists = await db.scalar(select(image_tasks_table.c.id).where(image_tasks_table.c.id == task_id, scoped_condition(current_admin, image_tasks_table.c.site_id)))
    if task_exists is None:
        raise AppException(code=40430, message="任务不存在", status_code=404)
    add_audit(db, current_admin, "refund_image_task", "image_tasks", task_id, reason)
    await db.commit()
    return ApiResponse.ok({"id": task_id, "refunded": True, **payload})


@router.post("/image-tasks/{task_id}/retry", response_model=ApiResponse[dict])
async def retry_task(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    current_admin: AdminUser = Depends(require_admin_roles(AdminRole.super_admin, AdminRole.operator, AdminRole.model_admin)),
) -> ApiResponse[dict]:
    task_exists = await db.scalar(select(image_tasks_table.c.id).where(image_tasks_table.c.id == task_id, scoped_condition(current_admin, image_tasks_table.c.site_id)))
    if task_exists is None:
        raise AppException(code=40430, message="任务不存在", status_code=404)
    add_audit(db, current_admin, "retry_image_task", "image_tasks", task_id, "人工重试失败任务")
    await db.commit()
    return ApiResponse.ok({"id": task_id, "queued": True})


@router.patch("/image-tasks/{task_id}/gallery", response_model=ApiResponse[dict])
async def toggle_task_gallery(
    task_id: int,
    payload: dict,
    db: AsyncSession = Depends(get_db),
    current_admin: AdminUser = Depends(require_admin_roles(AdminRole.super_admin, AdminRole.operator, AdminRole.model_admin)),
) -> ApiResponse[dict]:
    task = (
        await db.execute(
            select(
                image_tasks_table.c.id,
                image_tasks_table.c.task_no,
                image_tasks_table.c.status,
                image_tasks_table.c.output_image_url,
                image_tasks_table.c.is_gallery_featured,
                image_tasks_table.c.gallery_featured_by,
            ).where(image_tasks_table.c.id == task_id, image_tasks_table.c.deleted_at.is_(None), scoped_condition(current_admin, image_tasks_table.c.site_id)).with_for_update()
        )
    ).first()
    if task is None:
        raise AppException(code=40430, message="任务不存在", status_code=404)
    featured = payload.get("featured")
    if not isinstance(featured, bool):
        raise AppException(code=40030, message="审核结果必须为布尔值")
    if featured and (task.status != "succeeded" or not task.output_image_url):
        raise AppException(code=40030, message="只有已成功且有结果图的任务才能加入创作广场")
    if featured and not task.is_gallery_featured:
        raise AppException(code=40030, message="作品尚未提交审核或已撤回，请刷新列表")
    reason = str(payload.get("reason") or "").strip()[:1000]
    if not featured and not reason:
        raise AppException(code=40030, message="驳回或下架必须填写原因")
    values = {
        "is_gallery_featured": featured,
        "gallery_title": str(payload.get("title") or "").strip()[:120] or None,
        "gallery_sort_order": int(payload.get("sort_order") or 0),
        "gallery_featured_by": current_admin.id,
        "gallery_featured_at": datetime.now(timezone.utc) if featured else None,
    }
    await db.execute(update(image_tasks_table).where(image_tasks_table.c.id == task_id, scoped_condition(current_admin, image_tasks_table.c.site_id)).values(**values))
    action = "feature_gallery_task" if featured else "unfeature_gallery_task"
    add_audit(db, current_admin, action, "image_tasks", task_id, f"{task.task_no}: {reason or '人工审核通过'}")
    await db.commit()
    return ApiResponse.ok({"id": task_id, "is_gallery_featured": featured})


@router.get("/openagent/releases", response_model=ApiResponse[dict])
async def openagent_releases(
    request: Request,
    keyword: str = "",
    channel: str = Query("all", pattern="^(all|prod|beta)$"),
    platform: str = Query("all", pattern="^(all|mac|windows|linux)$"),
    arch: str = Query("all", pattern="^(all|[a-z0-9-]{2,64})$"),
    status: str = Query("all", pattern="^(all|active|inactive)$"),
    page_no: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_admin: AdminUser = Depends(require_admin_roles(AdminRole.super_admin, AdminRole.operator, AdminRole.model_admin)),
) -> ApiResponse[dict]:
    site_id = await current_admin_config_site_id(db, request, current_admin)
    condition = OpenAgentRelease.site_id == site_id
    if keyword:
        like = f"%{keyword.strip()}%"
        condition = or_(OpenAgentRelease.version.ilike(like), OpenAgentRelease.file_url.ilike(like), OpenAgentRelease.release_notes.ilike(like))
    if channel != "all":
        condition = and_(condition, OpenAgentRelease.channel == channel)
    if platform != "all":
        condition = and_(condition, OpenAgentRelease.platform == platform)
    if arch != "all":
        condition = and_(condition, OpenAgentRelease.arch == arch)
    if status == "active":
        condition = and_(condition, OpenAgentRelease.is_active.is_(True))
    if status == "inactive":
        condition = and_(condition, OpenAgentRelease.is_active.is_(False))

    total = await db.scalar(select(func.count()).select_from(OpenAgentRelease).where(condition))
    result = await db.scalars(
        select(OpenAgentRelease)
        .where(condition)
        .order_by(desc(OpenAgentRelease.published_at), desc(OpenAgentRelease.created_at))
        .limit(page_size)
        .offset((page_no - 1) * page_size)
    )
    return ApiResponse.ok({"items": [openagent_release_out(release) for release in result], "total": total or 0, "page": page_no, "page_size": page_size})


@router.post("/openagent/upload-token", response_model=ApiResponse[dict])
async def openagent_upload_token(
    payload: OpenAgentUploadTokenRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_admin: AdminUser = Depends(require_admin_roles(AdminRole.super_admin, AdminRole.operator, AdminRole.model_admin)),
) -> ApiResponse[dict]:
    site_id = await current_admin_config_site_id(db, request, current_admin)
    filename = normalize_openagent_filename(payload.filename)
    key = f"{settings.openagent_release_prefix.strip().strip('/')}/site-{site_id}/{filename}"
    cdn_base = settings.qiniu_cdn_base_url.rstrip("/")
    return ApiResponse.ok(
        {
            "upload_url": settings.qiniu_upload_host.rstrip("/"),
            "token": qiniu_upload_token(key),
            "key": key,
            "public_url": f"{cdn_base}/{key}",
        }
    )


@router.post("/openagent/releases", response_model=ApiResponse[dict])
async def save_openagent_release(
    payload: OpenAgentReleaseRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_admin: AdminUser = Depends(require_admin_roles(AdminRole.super_admin, AdminRole.operator, AdminRole.model_admin)),
) -> ApiResponse[dict]:
    site_id = await current_admin_config_site_id(db, request, current_admin)
    release = await db.scalar(
        select(OpenAgentRelease).where(
            OpenAgentRelease.site_id == site_id,
            OpenAgentRelease.channel == payload.channel,
            OpenAgentRelease.version == payload.version.strip(),
            OpenAgentRelease.platform == payload.platform,
            OpenAgentRelease.arch == payload.arch,
        )
    )
    now = datetime.now(timezone.utc)
    if release is None:
        release = OpenAgentRelease(
            site_id=site_id,
            channel=payload.channel,
            version=payload.version.strip(),
            platform=payload.platform,
            arch=payload.arch,
            created_by=current_admin.id,
            published_at=now if payload.is_active else None,
        )
        db.add(release)
        action = "create_openagent_release"
    else:
        action = "update_openagent_release"
    release.file_url = payload.file_url.strip()
    release.file_sha512 = payload.file_sha512.strip()
    release.file_size = payload.file_size
    release.release_notes = payload.release_notes.strip() or None
    release.is_active = payload.is_active
    release.is_mandatory = payload.is_mandatory
    if payload.is_active and release.published_at is None:
        release.published_at = now
    release.updated_at = now
    await db.flush()
    add_audit(db, current_admin, action, "openagent_releases", release.id, f"{release.channel}/{release.arch} {release.version}")
    await db.commit()
    await db.refresh(release)
    return ApiResponse.ok(openagent_release_out(release), "OpenAgent 更新版本已保存")


@router.patch("/openagent/releases/{release_id}/status", response_model=ApiResponse[dict])
async def toggle_openagent_release(
    release_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_admin: AdminUser = Depends(require_admin_roles(AdminRole.super_admin, AdminRole.operator, AdminRole.model_admin)),
) -> ApiResponse[dict]:
    site_id = await current_admin_config_site_id(db, request, current_admin)
    release = await db.scalar(select(OpenAgentRelease).where(OpenAgentRelease.id == release_id, OpenAgentRelease.site_id == site_id))
    if release is None:
        raise AppException(code=40440, message="OpenAgent 更新版本不存在", status_code=404)
    release.is_active = not release.is_active
    now = datetime.now(timezone.utc)
    release.updated_at = now
    if release.is_active and release.published_at is None:
        release.published_at = now
    add_audit(db, current_admin, "toggle_openagent_release", "openagent_releases", release.id, f"{release.channel}/{release.arch} {release.version}")
    await db.commit()
    await db.refresh(release)
    return ApiResponse.ok(openagent_release_out(release), "OpenAgent 更新版本状态已更新")


@router.get("/audit-logs", response_model=ApiResponse[dict])
async def audit_logs(
    keyword: str = "",
    page_no: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_admin: AdminUser = Depends(get_current_admin),
) -> ApiResponse[dict]:
    condition = True
    source = AdminAuditLog.__table__.outerjoin(AdminUser.__table__, AdminAuditLog.admin_id == AdminUser.id)
    if not current_admin.system_super_admin:
        condition = AdminUser.site_id == admin_scope_site_id(current_admin)
    if keyword:
        like = f"%{keyword.strip()}%"
        keyword_condition = or_(AdminAuditLog.admin_username.ilike(like), AdminAuditLog.action.ilike(like), AdminAuditLog.resource_type.ilike(like), AdminAuditLog.reason.ilike(like))
        condition = keyword_condition if condition is True else and_(condition, keyword_condition)
    total = await db.scalar(select(func.count()).select_from(source).where(condition))
    result = await db.scalars(
        select(AdminAuditLog)
        .select_from(source)
        .where(condition)
        .order_by(desc(AdminAuditLog.created_at))
        .limit(page_size)
        .offset((page_no - 1) * page_size)
    )
    return ApiResponse.ok(
        {"items": [
            {
                "id": log.id,
                "admin_username": log.admin_username,
                "action": log.action,
                "resource_type": log.resource_type,
                "resource_id": log.resource_id,
                "reason": log.reason,
                "created_at": iso(log.created_at),
            }
            for log in result
        ], "total": total or 0, "page": page_no, "page_size": page_size}
    )
