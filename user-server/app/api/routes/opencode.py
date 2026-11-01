import asyncio
import logging
import secrets
from datetime import UTC, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import desc, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import PlainTextResponse

from app.api.deps import get_current_user
from app.core.exceptions import BusinessError
from app.core.responses import StandardResponse, ok
from app.db.session import get_db
from app.models.agent import AgentConfig, TeamMemberUsageLimit, UserAgentAccount, UserAgentApiKey
from app.models.openagent_release import OpenAgentRelease
from app.models.user import User
from app.schemas.auth import LoginRequest
from app.services.rate_limit import login_rate_limit_key
from app.services.agent_openapi import AgentAPIError, AgentAPIGroup, AgentAPIKey, AgentAPIKeyUsage, AgentOpenAPIClient
from app.services.agent_usage import list_usage_for_api_keys, usage_record_out
from app.services.agent_provisioning import _configured_group_ids, agent_account_requires_sync, sync_agent_account
from app.services.gateway_proxy import GatewayRoutingError, public_gateway_base_url_for_site
from app.services.security import resolve_submitted_password, verify_password
from app.services.site_scope import current_site_id
from app.services.team_sharing import get_agent_billing_team, get_or_create_user_team, team_console_permissions, user_team_members_table

router = APIRouter(prefix="/opencode", tags=["opencode"])
logger = logging.getLogger(__name__)


class OpenCodeLoginResponse(BaseModel):
    status: str
    agent_user_id: int | None = None
    text_api_key: str | None = None
    image_api_key: str | None = None


class OpenCodeBalanceByKeyRequest(BaseModel):
    api_key: str = Field(min_length=1, max_length=2048)


class OpenCodeKeyCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    group_id: int = Field(gt=0)
    quota: Decimal = Field(default=Decimal("0"), ge=0, max_digits=18, decimal_places=4)
    expires_in_days: int | None = Field(default=None, ge=1, le=3650)
    rate_limit_5h: Decimal = Field(default=Decimal("0"), ge=0, max_digits=18, decimal_places=4)
    rate_limit_1d: Decimal = Field(default=Decimal("0"), ge=0, max_digits=18, decimal_places=4)
    rate_limit_7d: Decimal = Field(default=Decimal("0"), ge=0, max_digits=18, decimal_places=4)
    ip_whitelist: list[str] = Field(default_factory=list, max_length=100)
    ip_blacklist: list[str] = Field(default_factory=list, max_length=100)


class OpenCodeKeyUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    group_id: int | None = Field(default=None, gt=0)
    quota: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=4)
    expires_at: str | None = None
    status: str | None = Field(default=None, pattern="^(active|inactive)$")
    rate_limit_5h: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=4)
    rate_limit_1d: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=4)
    rate_limit_7d: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=4)
    ip_whitelist: list[str] | None = Field(default=None, max_length=100)
    ip_blacklist: list[str] | None = Field(default=None, max_length=100)


class OpenCodePublicBalanceResponse(BaseModel):
    status: str
    agent_user_id: int | None = None
    agent_balance: float | None = None
    balance_visible: bool = False
    credit_to_agent_rate: float = 1


OPENAGENT_DOWNLOAD_TARGETS = [
    {"key": "mac-arm64-dmg", "platform": "mac", "arch": "arm64-dmg", "label": "macOS M 系列 DMG（安装包）", "package_type": "installer"},
    {"key": "mac-arm64-zip", "platform": "mac", "arch": "arm64", "label": "macOS M 系列 ZIP（自动更新 / 免安装）", "package_type": "portable"},
    {"key": "mac-x64-dmg", "platform": "mac", "arch": "x64-dmg", "label": "macOS Intel DMG（安装包）", "package_type": "installer"},
    {"key": "mac-x64-zip", "platform": "mac", "arch": "x64", "label": "macOS Intel ZIP（自动更新 / 免安装）", "package_type": "portable"},
    {"key": "windows-universal-installer", "platform": "windows", "arch": "universal-installer", "label": "Windows 合并安装包（x64 + 32 位）", "package_type": "installer"},
    {"key": "windows-universal-portable", "platform": "windows", "arch": "universal-portable", "label": "Windows 合并免安装包（x64 + 32 位）", "package_type": "portable"},
]


def yaml_scalar(value: object) -> str:
    text = "" if value is None else str(value)
    return json_escape(text)


def json_escape(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    return f'"{escaped}"'


def latest_mac_yml(release: OpenAgentRelease) -> str:
    release_date = (release.published_at or release.created_at).isoformat()
    return "\n".join(
        [
            f"version: {yaml_scalar(release.version)}",
            "files:",
            f"  - url: {yaml_scalar(release.file_url)}",
            f"    sha512: {yaml_scalar(release.file_sha512)}",
            f"    size: {int(release.file_size)}",
            f"path: {yaml_scalar(release.file_url)}",
            f"sha512: {yaml_scalar(release.file_sha512)}",
            f"releaseDate: {yaml_scalar(release_date)}",
            "",
        ]
    )


def openagent_release_download_out(target: dict[str, str], release: OpenAgentRelease | None) -> dict:
    return {
        "key": target["key"],
        "platform": target["platform"],
        "arch": target["arch"],
        "label": target["label"],
        "package_type": target["package_type"],
        "version": release.version if release else None,
        "file_url": release.file_url if release else None,
        "file_size": int(release.file_size) if release else None,
        "release_notes": release.release_notes or "" if release else "",
        "published_at": (release.published_at or release.created_at).isoformat() if release else None,
    }


async def get_config(db: AsyncSession, site_id: int) -> AgentConfig:
    config = await db.scalar(select(AgentConfig).where(AgentConfig.site_id == site_id))
    if config is None or not config.is_enabled:
        raise BusinessError("OpenAgent 功能未开启", code=41001)
    return config


async def get_latest_openagent_release(db: AsyncSession, site_id: int, channel: str, arch: str) -> OpenAgentRelease:
    release = await db.scalar(
        select(OpenAgentRelease)
        .where(
            OpenAgentRelease.site_id == site_id,
            OpenAgentRelease.channel == channel,
            OpenAgentRelease.platform == "mac",
            OpenAgentRelease.arch == arch,
            OpenAgentRelease.is_active.is_(True),
        )
        .order_by(desc(OpenAgentRelease.published_at), desc(OpenAgentRelease.created_at))
        .limit(1)
    )
    if release is None and arch != "universal":
        release = await db.scalar(
            select(OpenAgentRelease)
            .where(
                OpenAgentRelease.site_id == site_id,
                OpenAgentRelease.channel == channel,
                OpenAgentRelease.platform == "mac",
                OpenAgentRelease.arch == "universal",
                OpenAgentRelease.is_active.is_(True),
            )
            .order_by(desc(OpenAgentRelease.published_at), desc(OpenAgentRelease.created_at))
            .limit(1)
        )
    if release is None:
        raise BusinessError("OpenAgent 暂无可用更新", code=40440, status_code=404)
    return release


async def find_latest_download_release(db: AsyncSession, site_id: int, channel: str, platform: str, arch: str) -> OpenAgentRelease | None:
    arch_candidates = [arch]
    if platform == "mac" and arch != "universal":
        arch_candidates.append("universal")
    for candidate in arch_candidates:
        release = await db.scalar(
            select(OpenAgentRelease)
            .where(
                OpenAgentRelease.site_id == site_id,
                OpenAgentRelease.channel == channel,
                OpenAgentRelease.platform == platform,
                OpenAgentRelease.arch == candidate,
                OpenAgentRelease.is_active.is_(True),
            )
            .order_by(desc(OpenAgentRelease.published_at), desc(OpenAgentRelease.created_at))
            .limit(1)
        )
        if release is not None:
            return release
    return None


async def get_agent_account(db: AsyncSession, user_id: int) -> UserAgentAccount:
    account = await db.scalar(select(UserAgentAccount).where(UserAgentAccount.user_id == user_id))
    if account is None or account.status != "active" or account.agent_user_id is None:
        raise BusinessError("OpenAgent 账号尚未完成初始化", code=41002)
    return account


async def authenticate_user_for_opencode(db: AsyncSession, data: LoginRequest, site_id: int) -> User:
    account = data.username.strip().lower()
    user = await db.scalar(select(User).where(User.site_id == site_id, or_(User.email == account, User.username == data.username.strip()), User.deleted_at.is_(None)))
    if user is None:
        raise BusinessError("用户名或密码错误", code=40003, status_code=401)
    if not user.is_active:
        raise BusinessError("账户已被禁用", code=40103, status_code=401)

    password = resolve_submitted_password(data.password)
    if not verify_password(password, user.password_hash):
        raise BusinessError("用户名或密码错误", code=40003, status_code=401)
    return user


async def public_api_base_url(db: AsyncSession, site_id: int) -> str:
    try:
        return await public_gateway_base_url_for_site(db, site_id)
    except GatewayRoutingError as error:
        raise BusinessError(
            error.message,
            code=50386,
            status_code=error.status_code,
        ) from error


def agent_account_out(
    account: UserAgentAccount | None,
    config: AgentConfig,
    *,
    api_base_url: str,
    agent_balance: Decimal | None = None,
) -> dict:
    return {
        "status": account.status if account else "missing",
        "failure_message": account.failure_message if account else None,
        "agent_user_id": account.agent_user_id if account else None,
        "agent_balance": float(agent_balance) if agent_balance is not None else None,
        "credit_to_agent_rate": float(config.credit_to_agent_rate),
        "image_billing_enabled": bool(config.image_billing_enabled),
        "text_api_key": account.text_api_key if account else None,
        "image_api_key": account.image_api_key if account else None,
        "api_base_url": api_base_url,
    }


def _allowed_groups(config: AgentConfig, groups: list[AgentAPIGroup]) -> list[dict]:
    allowed_ids = _configured_group_ids(config)
    by_id = {group.id: group for group in groups}
    return [
        {
            "id": group_id,
            "name": by_id[group_id].name,
            "platform": by_id[group_id].platform,
        }
        for group_id in allowed_ids if group_id in by_id
    ]


def _key_out(
    mapping: UserAgentApiKey,
    key: AgentAPIKey,
    groups: dict[int, dict],
    usage: AgentAPIKeyUsage | None = None,
) -> dict:
    group_id = key.group_id if key.group_id is not None else mapping.group_id
    group = (groups.get(int(group_id)) or {"id": int(group_id), "name": f"分组 {group_id}", "platform": ""}) if group_id is not None else None
    today_actual_cost = usage.today_actual_cost if usage is not None else key.today_actual_cost
    total_actual_cost = usage.total_actual_cost if usage is not None else key.total_actual_cost
    return {
        "id": int(mapping.id),
        "key": key.key or mapping.api_key,
        "name": mapping.name,
        "group": group,
        "quota": float(key.quota),
        "quota_used": float(total_actual_cost if usage is not None else key.quota_used),
        "rate_limit_5h": float(key.rate_limit_5h),
        "rate_limit_1d": float(key.rate_limit_1d),
        "rate_limit_7d": float(key.rate_limit_7d),
        "usage_5h": float(key.usage_5h),
        "usage_1d": float(key.usage_1d),
        "usage_7d": float(key.usage_7d),
        "reset_5h_at": key.reset_5h_at,
        "reset_1d_at": key.reset_1d_at,
        "reset_7d_at": key.reset_7d_at,
        "status": key.status or "active",
        "expires_at": key.expires_at,
        "created_at": key.created_at or mapping.created_at.isoformat(),
        "last_used_at": key.last_used_at,
        "last_used_ip": key.last_used_ip,
        "ip_whitelist": list(key.ip_whitelist),
        "ip_blacklist": list(key.ip_blacklist),
        "current_concurrency": key.current_concurrency,
        "max_concurrency": key.max_concurrency,
        "today_actual_cost": float(today_actual_cost),
        "total_actual_cost": float(total_actual_cost),
    }


def _mark_key_deleted(account: UserAgentAccount, mapping: UserAgentApiKey) -> None:
    mapping.is_deleted = True
    if account.text_api_key_id == mapping.agent_key_id:
        account.text_api_key = None
        account.status = "pending"
    if account.image_api_key_id == mapping.agent_key_id:
        account.image_api_key = None


async def _key_context(db: AsyncSession, current_user: User):
    config = await get_config(db, current_user.site_id)
    account = await sync_agent_account(db, current_user)
    await db.flush()
    if account is None or account.status != "active" or account.agent_user_id is None or account.team_id is None:
        message = account.failure_message if account and account.failure_message else "账户尚未准备完成"
        raise BusinessError(message, code=50382, status_code=503)
    wallet = await db.scalar(
        select(UserAgentAccount)
        .where(
            UserAgentAccount.team_id == int(account.team_id),
            UserAgentAccount.agent_user_id == int(account.agent_user_id),
            UserAgentAccount.agent_password.is_not(None),
        )
        .order_by(UserAgentAccount.user_id.asc())
        .limit(1)
    )
    if wallet is None or not wallet.agent_password:
        raise BusinessError("账户凭据尚未准备完成", code=50382, status_code=503)
    client = AgentOpenAPIClient(config)
    try:
        token, live_keys, live_groups, agent_user = await asyncio.gather(
            asyncio.to_thread(client.login_user, email=wallet.agent_email, password=wallet.agent_password),
            asyncio.to_thread(client.list_user_api_keys, int(account.agent_user_id)),
            asyncio.to_thread(client.list_groups),
            asyncio.to_thread(client.get_user, int(account.agent_user_id)),
        )
    except AgentAPIError as error:
        raise BusinessError("账户服务暂时不可用，请稍后重试", code=50282, status_code=502) from error
    mappings = (
        await db.execute(
            select(UserAgentApiKey).where(
                UserAgentApiKey.team_id == int(account.team_id),
                UserAgentApiKey.user_id == current_user.id,
            )
        )
    ).scalars().all()
    return config, account, client, token, live_keys, live_groups, agent_user, mappings


def _clean_ip_rules(values: list[str] | None) -> list[str] | None:
    if values is None:
        return None
    return list(dict.fromkeys(value.strip() for value in values if value.strip()))[:100]


def _validate_expiration(value: str | None) -> str | None:
    if value in {None, ""}:
        return value
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise BusinessError("有效期格式不正确", code=40084) from error
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    if parsed <= datetime.now(UTC):
        raise BusinessError("有效期必须晚于当前时间", code=40084)
    return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")


async def _validate_member_key_quota(
    db: AsyncSession,
    *,
    config: AgentConfig,
    account: UserAgentAccount,
    current_user: User,
    group_id: int,
    requested_quota: Decimal,
    mappings: list[UserAgentApiKey],
    live_keys: list[AgentAPIKey],
    exclude_mapping_id: int | None = None,
) -> None:
    limit = await db.scalar(
        select(TeamMemberUsageLimit).where(
            TeamMemberUsageLimit.team_id == int(account.team_id),
            TeamMemberUsageLimit.user_id == current_user.id,
        )
    )
    if limit is None:
        return
    category_limit = Decimal(str(limit.text_quota if group_id == config.text_group_id else limit.image_quota))
    if category_limit <= 0:
        return
    if requested_quota <= 0:
        raise BusinessError("团队管理员已设置成员总额度，此 Key 不能设为不限额", code=40086)
    live_by_id = {int(key.id): key for key in live_keys if key.id is not None}
    allocated = Decimal("0")
    for mapping in mappings:
        if exclude_mapping_id is not None and int(mapping.id) == exclude_mapping_id:
            continue
        # Extra groups must not each get a fresh copy of the member's category
        # allowance. Preserve the existing default-text / other-groups categories.
        if (mapping.group_id == config.text_group_id) != (group_id == config.text_group_id):
            continue
        key = live_by_id.get(int(mapping.agent_key_id))
        if key is None:
            continue
        if mapping.is_deleted:
            allocated += key.quota_used
            continue
        if key.quota <= 0:
            raise BusinessError("现有 Key 仍为不限额，请先调整其额度后再创建或修改", code=40086)
        allocated += key.quota
    if allocated + requested_quota > category_limit:
        remaining = max(Decimal("0"), category_limit - allocated)
        raise BusinessError(f"超出成员总额度，当前最多可分配 {remaining}", code=40086)


@router.post("/login", response_model=StandardResponse[OpenCodeLoginResponse])
async def opencode_login(
    data: LoginRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> StandardResponse[OpenCodeLoginResponse]:
    account = data.username.strip().lower()
    identifier = f"opencode:{request.client.host if request.client else 'unknown'}:{account}"
    if not await login_rate_limit_key(identifier):
        raise BusinessError("登录尝试过于频繁，请稍后再试", code=42901, status_code=429)

    site_id = await current_site_id(db, request)
    user = await authenticate_user_for_opencode(db, data, site_id)
    await get_config(db, user.site_id)
    billing_team = await get_agent_billing_team(db, user)
    account = await db.scalar(select(UserAgentAccount).where(UserAgentAccount.user_id == user.id))
    if agent_account_requires_sync(account, int(billing_team.id)):
        account = await sync_agent_account(db, user)
        await db.commit()
    if (
        account is None
        or account.status != "active"
        or account.agent_user_id is None
        or not account.image_api_key
    ):
        message = account.failure_message if account and account.failure_message else "OpenAgent 账号初始化失败"
        raise BusinessError(message, code=41005, status_code=503)
    return ok(
        OpenCodeLoginResponse(
            status=account.status,
            agent_user_id=account.agent_user_id,
            text_api_key=account.text_api_key,
            image_api_key=account.image_api_key,
        ),
        "OpenAgent 登录成功",
    )


@router.get("/updates/{channel}/{arch}/latest-mac.yml", response_class=PlainTextResponse)
async def openagent_latest_mac_yml(
    request: Request,
    channel: str,
    arch: str,
    db: AsyncSession = Depends(get_db),
) -> PlainTextResponse:
    if channel not in {"prod", "beta"} or arch not in {"arm64", "x64", "universal"}:
        raise BusinessError("OpenAgent 更新频道不存在", code=40441, status_code=404)
    site_id = await current_site_id(db, request)
    release = await get_latest_openagent_release(db, site_id, channel, arch)
    return PlainTextResponse(latest_mac_yml(release), media_type="text/yaml; charset=utf-8")


@router.get("/releases", response_model=StandardResponse[list[dict]])
async def openagent_releases(
    request: Request,
    channel: str = Query("prod", pattern="^(prod|beta)$"),
    db: AsyncSession = Depends(get_db),
) -> StandardResponse[list[dict]]:
    site_id = await current_site_id(db, request)
    items = []
    for target in OPENAGENT_DOWNLOAD_TARGETS:
        release = await find_latest_download_release(db, site_id, channel, target["platform"], target["arch"])
        items.append(openagent_release_download_out(target, release))
    return ok(items)


@router.get("/balance", response_model=StandardResponse[dict])
async def balance(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StandardResponse[dict]:
    config = await get_config(db, current_user.site_id)
    api_base_url = await public_api_base_url(db, current_user.site_id)
    account = await db.scalar(select(UserAgentAccount).where(UserAgentAccount.user_id == current_user.id))
    if account is None or account.status != "active" or account.agent_user_id is None:
        return ok(agent_account_out(account, config, api_base_url=api_base_url))
    team = await get_or_create_user_team(db, current_user)
    can_view_team_balance = "usage:view" in team_console_permissions(str(team.current_role))
    agent_balance = None
    if can_view_team_balance:
        try:
            agent_user = await asyncio.to_thread(AgentOpenAPIClient(config).get_user, int(account.agent_user_id))
            agent_balance = agent_user.balance
        except AgentAPIError:
            pass
    return ok(
        agent_account_out(
            account,
            config,
            api_base_url=api_base_url,
            agent_balance=agent_balance,
        )
    )


@router.post("/balance/by-key", response_model=StandardResponse[OpenCodePublicBalanceResponse])
async def balance_by_key(
    payload: OpenCodeBalanceByKeyRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> StandardResponse[OpenCodePublicBalanceResponse]:
    identifier = f"opencode-balance:{request.client.host if request.client else 'unknown'}"
    if not await login_rate_limit_key(identifier):
        raise BusinessError("请求过于频繁，请稍后再试", code=42901, status_code=429)

    api_key = payload.api_key.strip()
    site_id = await current_site_id(db, request)
    account = await db.scalar(
        select(UserAgentAccount)
        .join(User, User.id == UserAgentAccount.user_id)
        .where(
            User.site_id == site_id,
            UserAgentAccount.status == "active",
            (UserAgentAccount.text_api_key == api_key) | (UserAgentAccount.image_api_key == api_key),
        )
    )
    if account is None or account.agent_user_id is None:
        raise BusinessError("OpenAgent Key 无效", code=40003, status_code=401)
    config = await get_config(db, site_id)
    current_role = None
    if account.team_id is not None:
        current_role = await db.scalar(
            select(user_team_members_table.c.role).where(
                user_team_members_table.c.site_id == site_id,
                user_team_members_table.c.team_id == int(account.team_id),
                user_team_members_table.c.user_id == int(account.user_id),
            )
        )
    balance_visible = account.team_id is None or "usage:view" in team_console_permissions(str(current_role or "member"))
    agent_balance = None
    if balance_visible:
        try:
            agent_user = await asyncio.to_thread(AgentOpenAPIClient(config).get_user, int(account.agent_user_id))
            agent_balance = agent_user.balance
        except AgentAPIError:
            pass

    return ok(
        OpenCodePublicBalanceResponse(
            status=account.status,
            agent_user_id=account.agent_user_id,
            agent_balance=float(agent_balance) if agent_balance is not None else None,
            balance_visible=balance_visible,
            credit_to_agent_rate=float(config.credit_to_agent_rate),
        )
    )


@router.get("/keys", response_model=StandardResponse[dict])
async def opencode_keys(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StandardResponse[dict]:
    config, account, client, token, live_keys, live_groups, agent_user, mappings = await _key_context(db, current_user)
    api_base_url = await public_api_base_url(db, current_user.site_id)
    group_payload = _allowed_groups(config, live_groups)
    group_by_id = {group.id: {"id": group.id, "name": group.name, "platform": group.platform} for group in live_groups}
    live_by_id = {int(key.id): key for key in live_keys if key.id is not None}
    usage_key_ids = {
        int(mapping.agent_key_id)
        for mapping in mappings
        if mapping.agent_key_id is not None
    }
    usage_key_ids.update(
        int(key_id)
        for key_id in (account.text_api_key_id, account.image_api_key_id)
        if key_id is not None
    )
    try:
        usage_by_key_id = await asyncio.to_thread(
            client.get_api_keys_usage,
            token=token,
            api_key_ids=sorted(usage_key_ids),
        )
    except AgentAPIError as error:
        raise BusinessError("Key 用量查询失败，请稍后重试", code=50286, status_code=502) from error
    items = [
        _key_out(
            mapping,
            live_by_id[mapping.agent_key_id],
            group_by_id,
            usage_by_key_id.get(int(mapping.agent_key_id)),
        )
        for mapping in mappings
        if not mapping.is_deleted and mapping.agent_key_id in live_by_id
    ]
    today_used = sum(
        (
            usage_by_key_id[key_id].today_actual_cost
            for key_id in usage_key_ids
            if key_id in usage_by_key_id
        ),
        Decimal("0"),
    )
    total_used = sum(
        (
            usage_by_key_id[key_id].total_actual_cost
            for key_id in usage_key_ids
            if key_id in usage_by_key_id
        ),
        Decimal("0"),
    )
    team = await get_or_create_user_team(db, current_user)
    can_view_team_balance = "usage:view" in team_console_permissions(str(team.current_role))
    await db.commit()
    return ok(
        {
            "status": account.status,
            "failure_message": account.failure_message,
            "agent_user_id": account.agent_user_id,
            "agent_balance": float(agent_user.balance) if can_view_team_balance else None,
            "can_view_team_balance": can_view_team_balance,
            "api_base_url": api_base_url,
            "groups": group_payload,
            "items": items,
            "today_used": float(today_used),
            "total_used": float(total_used),
        }
    )


@router.post("/keys", response_model=StandardResponse[dict])
async def create_opencode_key(
    payload: OpenCodeKeyCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StandardResponse[dict]:
    config, account, client, token, _live_keys, live_groups, _agent_user, _mappings = await _key_context(db, current_user)
    allowed = {int(group["id"]): group for group in _allowed_groups(config, live_groups)}
    if payload.group_id not in allowed:
        raise BusinessError("该分组当前不可用", code=40085)
    await _validate_member_key_quota(
        db,
        config=config,
        account=account,
        current_user=current_user,
        group_id=payload.group_id,
        requested_quota=payload.quota,
        mappings=_mappings,
        live_keys=_live_keys,
    )
    options: dict[str, object] = {
        "quota": float(payload.quota) if payload.quota > 0 else None,
        "expires_in_days": payload.expires_in_days,
        "rate_limit_5h": float(payload.rate_limit_5h) if payload.rate_limit_5h > 0 else None,
        "rate_limit_1d": float(payload.rate_limit_1d) if payload.rate_limit_1d > 0 else None,
        "rate_limit_7d": float(payload.rate_limit_7d) if payload.rate_limit_7d > 0 else None,
        "ip_whitelist": _clean_ip_rules(payload.ip_whitelist),
        "ip_blacklist": _clean_ip_rules(payload.ip_blacklist),
    }
    try:
        await asyncio.to_thread(
            client.update_user_allowed_groups,
            agent_user_id=int(account.agent_user_id),
            allowed_groups=list(allowed),
        )
        key = await asyncio.to_thread(
            client.create_user_api_key,
            token=token,
            name=f"image2-u{current_user.id}-{secrets.token_hex(4)}",
            group_id=payload.group_id,
            idempotency_key=f"image2-user-key:{current_user.id}:{secrets.token_urlsafe(12)}",
            **options,
        )
    except AgentAPIError as error:
        logger.warning(
            "opencode key create failed site_id=%s user_id=%s team_id=%s agent_user_id=%s group_id=%s: %s",
            current_user.site_id,
            current_user.id,
            account.team_id,
            account.agent_user_id,
            payload.group_id,
            error,
        )
        raise BusinessError("Key 创建失败，请稍后重试", code=50283, status_code=502) from error
    if key.id is None:
        raise BusinessError("Key 创建响应不完整", code=50283, status_code=502)
    mapping = UserAgentApiKey(
        site_id=current_user.site_id,
        team_id=int(account.team_id),
        user_id=current_user.id,
        agent_user_id=int(account.agent_user_id),
        agent_key_id=int(key.id),
        api_key=key.key,
        name=payload.name.strip(),
        group_id=payload.group_id,
    )
    db.add(mapping)
    await db.flush()
    await db.commit()
    return ok(_key_out(mapping, key, allowed), "Key 已创建")


@router.patch("/keys/{key_id}", response_model=StandardResponse[dict])
async def update_opencode_key(
    key_id: int,
    payload: OpenCodeKeyUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StandardResponse[dict]:
    config, account, client, token, live_keys, live_groups, _agent_user, mappings = await _key_context(db, current_user)
    mapping = next((item for item in mappings if int(item.id) == key_id and not item.is_deleted), None)
    if mapping is None:
        raise BusinessError("Key 不存在", code=40484, status_code=404)
    allowed = {int(group["id"]): group for group in _allowed_groups(config, live_groups)}
    live_key = next((item for item in live_keys if item.id == mapping.agent_key_id), None)
    if live_key is None:
        raise BusinessError("Key 已不存在，请刷新后重试", code=40484, status_code=404)
    if payload.group_id is not None and payload.group_id != live_key.group_id and payload.group_id not in allowed:
        raise BusinessError("该分组当前不可用", code=40085)
    if payload.group_id is not None and payload.group_id != live_key.group_id and live_key.quota_used > 0:
        raise BusinessError("已有用量的 Key 不能更换分组，请新建 Key", code=40087)
    if payload.quota is not None or payload.group_id is not None:
        await _validate_member_key_quota(
            db,
            config=config,
            account=account,
            current_user=current_user,
            group_id=payload.group_id or int(live_key.group_id or mapping.group_id or 0),
            requested_quota=payload.quota if payload.quota is not None else live_key.quota,
            mappings=mappings,
            live_keys=live_keys,
            exclude_mapping_id=int(mapping.id),
        )
    remote_payload: dict[str, object] = {}
    if payload.group_id is not None and payload.group_id != live_key.group_id:
        remote_payload["group_id"] = payload.group_id
    if payload.quota is not None:
        remote_payload["quota"] = float(payload.quota)
    if payload.expires_at is not None:
        remote_payload["expires_at"] = _validate_expiration(payload.expires_at)
    for field in ("status", "rate_limit_5h", "rate_limit_1d", "rate_limit_7d"):
        value = getattr(payload, field)
        if value is not None:
            remote_payload[field] = float(value) if isinstance(value, Decimal) else value
    if payload.ip_whitelist is not None:
        remote_payload["ip_whitelist"] = _clean_ip_rules(payload.ip_whitelist)
    if payload.ip_blacklist is not None:
        remote_payload["ip_blacklist"] = _clean_ip_rules(payload.ip_blacklist)
    try:
        updated = await asyncio.to_thread(
            client.update_user_api_key,
            token=token,
            key_id=int(mapping.agent_key_id),
            payload=remote_payload,
        )
    except (AgentAPIError, ValueError) as error:
        raise BusinessError("Key 更新失败，请稍后重试", code=50284, status_code=502) from error
    if payload.name is not None:
        mapping.name = payload.name.strip()
    if payload.group_id is not None:
        mapping.group_id = payload.group_id
    mapping.api_key = updated.key or mapping.api_key
    await db.commit()
    return ok(_key_out(mapping, updated, allowed), "Key 已更新")


@router.delete("/keys/{key_id}", response_model=StandardResponse[None])
async def delete_opencode_key(
    key_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StandardResponse[None]:
    _config, account, client, token, _live_keys, _live_groups, _agent_user, mappings = await _key_context(db, current_user)
    mapping = next((item for item in mappings if int(item.id) == key_id and not item.is_deleted), None)
    if mapping is None:
        raise BusinessError("Key 不存在", code=40484, status_code=404)
    try:
        await asyncio.to_thread(
            client.update_user_api_key,
            token=token,
            key_id=int(mapping.agent_key_id),
            payload={"status": "inactive"},
        )
    except (AgentAPIError, ValueError) as error:
        raise BusinessError("Key 删除失败，请稍后重试", code=50285, status_code=502) from error
    _mark_key_deleted(account, mapping)
    await db.commit()
    return ok(None, "Key 已删除")


@router.post("/account/regenerate", response_model=StandardResponse[dict])
async def regenerate_account(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StandardResponse[dict]:
    config = await get_config(db, current_user.site_id)
    api_base_url = await public_api_base_url(db, current_user.site_id)
    account = await sync_agent_account(db, current_user)
    await db.commit()
    return ok(
        agent_account_out(account, config, api_base_url=api_base_url),
        "OpenAgent 账号同步已完成"
        if account and account.status == "active"
        else "OpenAgent 账号同步失败",
    )


@router.get("/usage", response_model=StandardResponse[dict])
async def usage_records(
    page: int = Query(1, ge=1, le=100),
    page_size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StandardResponse[dict]:
    config = await get_config(db, current_user.site_id)
    account = await get_agent_account(db, current_user.id)
    mapped_key_ids = (
        await db.execute(
            select(UserAgentApiKey.agent_key_id).where(
                UserAgentApiKey.user_id == current_user.id,
                UserAgentApiKey.agent_user_id == int(account.agent_user_id),
                UserAgentApiKey.is_deleted.is_(False),
            )
        )
    ).scalars().all()
    api_key_ids = [int(key_id) for key_id in mapped_key_ids]
    for legacy_key_id in (account.text_api_key_id, account.image_api_key_id):
        if legacy_key_id is not None:
            api_key_ids.append(int(legacy_key_id))
    try:
        result = await list_usage_for_api_keys(
            AgentOpenAPIClient(config),
            agent_user_id=int(account.agent_user_id),
            api_key_ids=api_key_ids,
            page=page,
            page_size=page_size,
        )
    except AgentAPIError as error:
        raise BusinessError(f"OpenAgent 使用记录查询失败：{error}", code=41006, status_code=502) from error
    return ok(
        {
            "items": [usage_record_out(row) for row in result["items"]],
            "total": result["total"],
            "page": result["page"],
            "page_size": result["page_size"],
        }
    )
