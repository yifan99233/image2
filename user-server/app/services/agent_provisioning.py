from __future__ import annotations

import asyncio
import logging
import secrets
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import AgentConfig, UserAgentAccount, UserAgentApiKey
from app.models.user import User
from app.services.agent_openapi import AgentAPIError, AgentAPIKey, AgentOpenAPIClient, AgentUser
from app.services.team_sharing import get_agent_billing_team, user_teams_table

logger = logging.getLogger(__name__)

AGENT_ACCOUNT_ALIAS_DOMAIN = "users.image2.invalid"
AGENT_ACCOUNT_CREATE_ATTEMPTS = 4


@dataclass(frozen=True)
class _LegacyAccount:
    default_key_ids: frozenset[int]
    mappings: tuple[UserAgentApiKey, ...]
    live_keys: tuple[AgentAPIKey, ...]
    token: str


@dataclass(frozen=True)
class _DeferredLegacyAccount:
    balance: Decimal
    team_id: int | None


def _failure_message(error: Exception) -> str:
    message = str(error).strip()
    return message[:1000] if message else "账户同步失败"


def agent_account_requires_sync(account: UserAgentAccount | None, billing_team_id: int) -> bool:
    return bool(
        account is None
        or account.status != "active"
        or account.agent_user_id is None
        or account.team_id != billing_team_id
        or not account.image_api_key
    )


def _configured_group_ids(config: AgentConfig) -> list[int]:
    return sorted({int(group_id) for group_id in (
        config.text_group_id, config.image_group_id, *(getattr(config, "key_group_whitelist", None) or [])
    ) if isinstance(group_id, int) and not isinstance(group_id, bool) and group_id > 0})


async def _sync_configured_allowed_groups(
    client: AgentOpenAPIClient,
    *,
    agent_user_id: int,
    config: AgentConfig,
) -> None:
    await asyncio.to_thread(
        client.update_user_allowed_groups,
        agent_user_id=agent_user_id,
        allowed_groups=_configured_group_ids(config),
    )


async def _account_row(db: AsyncSession, user: User, team_id: int) -> UserAgentAccount:
    account = await db.scalar(select(UserAgentAccount).where(UserAgentAccount.user_id == user.id))
    if account is None:
        account = UserAgentAccount(user_id=user.id, team_id=team_id, agent_email=user.email, status="pending")
        db.add(account)
        await db.flush()
    account.agent_email = account.agent_email or user.email
    return account


async def _record_key(
    db: AsyncSession,
    *,
    user: User,
    team_id: int,
    agent_user_id: int,
    key: AgentAPIKey,
    display_name: str,
) -> None:
    if key.id is None or not key.key:
        raise AgentAPIError("账户 Key 响应不完整")
    mapping = await db.scalar(
        select(UserAgentApiKey).where(
            UserAgentApiKey.agent_user_id == agent_user_id,
            UserAgentApiKey.agent_key_id == int(key.id),
        )
    )
    if mapping is None:
        mapping = UserAgentApiKey(
            site_id=user.site_id,
            team_id=team_id,
            user_id=user.id,
            agent_user_id=agent_user_id,
            agent_key_id=int(key.id),
            api_key=key.key,
            name=display_name,
            group_id=key.group_id,
        )
        db.add(mapping)
    else:
        mapping.site_id = user.site_id
        mapping.team_id = team_id
        mapping.user_id = user.id
        mapping.api_key = key.key or mapping.api_key
        mapping.name = display_name or mapping.name
        mapping.group_id = key.group_id
        mapping.is_deleted = False


async def _ensure_wallet(
    db: AsyncSession,
    *,
    client: AgentOpenAPIClient,
    config: AgentConfig,
    owner: User,
    team_id: int,
    password: str | None = None,
) -> UserAgentAccount:
    account = await _account_row(db, owner, team_id)
    allowed_groups = _configured_group_ids(config)
    if account.agent_user_id is None:
        agent_password = password or secrets.token_urlsafe(32)
        agent_user = await _create_wallet_user(
            client=client,
            owner=owner,
            password=agent_password,
            allowed_groups=allowed_groups,
        )
        account.agent_user_id = agent_user.id
        account.agent_email = agent_user.email
        account.agent_password = agent_password
    elif not account.agent_password:
        agent_password = secrets.token_urlsafe(32)
        agent_user = await asyncio.to_thread(
            client.reset_user_password,
            agent_user_id=int(account.agent_user_id),
            password=agent_password,
            allowed_groups=allowed_groups,
        )
        account.agent_user_id = agent_user.id
        account.agent_password = agent_password
    account.status = "active"
    account.failure_message = None
    return account


def _agent_email_conflict(error: AgentAPIError) -> bool:
    if error.reason == "EMAIL_EXISTS":
        return True
    message = str(error).casefold()
    return error.status_code == 409 and "email" in message and ("exist" in message or "重复" in message)


def _generated_agent_identity(user_id: int) -> tuple[str, str]:
    suffix = secrets.token_hex(6)
    identity = f"image2-u{user_id}-{suffix}"
    return identity, f"{identity}@{AGENT_ACCOUNT_ALIAS_DOMAIN}"


async def _create_wallet_user(
    *,
    client: AgentOpenAPIClient,
    owner: User,
    password: str,
    allowed_groups: list[int],
) -> AgentUser:
    user_id = int(owner.id)
    username = owner.username
    email = owner.email.strip().lower()
    try:
        duplicate = await asyncio.to_thread(client.user_email_exists, email)
    except AgentAPIError as error:
        duplicate = False
        logger.warning(
            "agent user preflight lookup failed; continuing with create "
            "site_id=%s user_id=%s requested_email=%s: %s",
            owner.site_id,
            user_id,
            email,
            error,
        )
    if duplicate:
        username, email = _generated_agent_identity(user_id)

    for attempt in range(1, AGENT_ACCOUNT_CREATE_ATTEMPTS + 1):
        try:
            agent_user = await asyncio.to_thread(
                client.create_user,
                user_id=user_id,
                username=username,
                email=email,
                password=password,
                allowed_groups=allowed_groups,
            )
            if email != owner.email.strip().lower():
                logger.info(
                    "created agent alias after email collision "
                    "site_id=%s user_id=%s agent_user_id=%s requested_email=%s agent_email=%s",
                    owner.site_id,
                    user_id,
                    agent_user.id,
                    owner.email,
                    agent_user.email,
                )
            return agent_user
        except AgentAPIError as error:
            if not _agent_email_conflict(error) or attempt >= AGENT_ACCOUNT_CREATE_ATTEMPTS:
                raise
            username, email = _generated_agent_identity(user_id)

    raise AgentAPIError("agent 账号创建重试次数已耗尽")


async def _ensure_default_key(
    db: AsyncSession,
    *,
    client: AgentOpenAPIClient,
    token: str,
    account: UserAgentAccount,
    user: User,
    team_id: int,
    group_id: int | None,
    kind: str,
    display_name: str,
    existing_keys: list[AgentAPIKey],
) -> AgentAPIKey:
    bound_id = account.text_api_key_id if kind == "text" else account.image_api_key_id
    key = next(
        (
            candidate
            for candidate in existing_keys
            if bound_id and candidate.id == int(bound_id) and candidate.status in {"", "active"}
        ),
        None,
    )
    if key is None:
        internal_name = f"image2-u{user.id}-{kind}"
        key = next(
            (
                candidate
                for candidate in existing_keys
                if candidate.name == internal_name
                and candidate.group_id == group_id
                and candidate.status in {"", "active"}
            ),
            None,
        )
    if key is None:
        previous_mapping_identity = (
            UserAgentApiKey.agent_key_id == int(bound_id)
            if bound_id is not None
            else UserAgentApiKey.name == display_name
        )
        previous_mapping = await db.scalar(
            select(UserAgentApiKey)
            .where(
                UserAgentApiKey.team_id == team_id,
                UserAgentApiKey.user_id == user.id,
                UserAgentApiKey.agent_user_id == int(account.agent_user_id),
                UserAgentApiKey.is_deleted.is_(True),
                previous_mapping_identity,
            )
            .order_by(UserAgentApiKey.id.desc())
            .limit(1)
        )
        replacement_key_id = int(previous_mapping.agent_key_id) if previous_mapping is not None else None
        if replacement_key_id is None and bound_id is not None:
            replacement_key_id = int(bound_id)
        key = await asyncio.to_thread(
            client.create_user_api_key,
            token=token,
            name=f"image2-u{user.id}-{kind}",
            group_id=group_id,
            idempotency_key=_default_key_idempotency_key(
                team_id=team_id,
                user_id=int(user.id),
                kind=kind,
                group_id=group_id,
                replacement_key_id=replacement_key_id,
            ),
        )
        existing_keys.append(key)
    await _record_key(
        db,
        user=user,
        team_id=team_id,
        agent_user_id=int(account.agent_user_id),
        key=key,
        display_name=display_name,
    )
    return key


def _default_key_idempotency_key(
    *,
    team_id: int,
    user_id: int,
    kind: str,
    group_id: int | None,
    replacement_key_id: int | None,
) -> str:
    group_token = int(group_id) if group_id is not None else 0
    generation_token = f"after-{int(replacement_key_id)}" if replacement_key_id is not None else "initial"
    return f"image2-agent-team-{team_id}-user-{user_id}-{kind}-group-{group_token}-{generation_token}"


def _remaining_quota(key: AgentAPIKey) -> Decimal:
    if key.quota <= 0:
        return Decimal("0")
    return max(Decimal("0"), key.quota - key.quota_used)


def _legacy_key_create_options(key: AgentAPIKey) -> dict[str, object]:
    return {
        "quota": float(_remaining_quota(key)),
        "rate_limit_5h": float(key.rate_limit_5h),
        "rate_limit_1d": float(key.rate_limit_1d),
        "rate_limit_7d": float(key.rate_limit_7d),
        "ip_whitelist": list(key.ip_whitelist),
        "ip_blacklist": list(key.ip_blacklist),
    }


async def _legacy_account(
    db: AsyncSession,
    *,
    client: AgentOpenAPIClient,
    member_account: UserAgentAccount,
    wallet: UserAgentAccount,
) -> _DeferredLegacyAccount | _LegacyAccount | None:
    if member_account.agent_user_id is None or member_account.agent_user_id == wallet.agent_user_id:
        return None
    legacy_user = await asyncio.to_thread(client.get_user, int(member_account.agent_user_id))
    if legacy_user.balance > 0:
        legacy_team_id = member_account.team_id
        if legacy_team_id == wallet.team_id:
            legacy_team_id = await db.scalar(
                select(UserAgentApiKey.team_id)
                .where(
                    UserAgentApiKey.user_id == member_account.user_id,
                    UserAgentApiKey.agent_user_id == int(member_account.agent_user_id),
                )
                .order_by(UserAgentApiKey.id.asc())
                .limit(1)
            )
            if legacy_team_id is None:
                legacy_team_id = await db.scalar(
                    select(user_teams_table.c.id)
                    .where(user_teams_table.c.owner_user_id == member_account.user_id)
                    .order_by(user_teams_table.c.created_at.asc(), user_teams_table.c.id.asc())
                    .limit(1)
                )
        return _DeferredLegacyAccount(
            balance=legacy_user.balance,
            team_id=int(legacy_team_id) if legacy_team_id is not None else None,
        )
    if not member_account.agent_password:
        raise AgentAPIError("旧版独立账户缺少迁移凭据")
    mappings = (
        await db.execute(
            select(UserAgentApiKey).where(
                UserAgentApiKey.user_id == member_account.user_id,
                UserAgentApiKey.agent_user_id == int(member_account.agent_user_id),
                UserAgentApiKey.is_deleted.is_(False),
            )
        )
    ).scalars().all()
    token, live_keys = await asyncio.gather(
        asyncio.to_thread(
            client.login_user,
            email=member_account.agent_email,
            password=str(member_account.agent_password),
        ),
        asyncio.to_thread(client.list_user_api_keys, int(member_account.agent_user_id)),
    )
    default_key_ids = frozenset(
        int(key_id)
        for key_id in (member_account.text_api_key_id, member_account.image_api_key_id)
        if key_id is not None
    )
    return _LegacyAccount(
        default_key_ids=default_key_ids,
        mappings=tuple(mappings),
        live_keys=tuple(live_keys),
        token=token,
    )


async def _ensure_deferred_legacy_credentials(
    *,
    client: AgentOpenAPIClient,
    config: AgentConfig,
    account: UserAgentAccount,
) -> None:
    """Repair server-owned login credentials while a funded legacy wallet stays in place."""
    if account.agent_user_id is None or account.agent_password:
        return
    password = secrets.token_urlsafe(32)
    updated = await asyncio.to_thread(
        client.reset_user_password,
        agent_user_id=int(account.agent_user_id),
        password=password,
        allowed_groups=_configured_group_ids(config),
    )
    if int(updated.id) != int(account.agent_user_id):
        raise AgentAPIError("旧版账户凭据修复返回了不匹配的用户 ID")
    account.agent_password = password


async def _migrate_legacy_custom_keys(
    db: AsyncSession,
    *,
    client: AgentOpenAPIClient,
    wallet_token: str,
    wallet: UserAgentAccount,
    user: User,
    team_id: int,
    legacy: _LegacyAccount | None,
) -> None:
    if legacy is None:
        return
    live_by_id = {int(key.id): key for key in legacy.live_keys if key.id is not None}
    for mapping in legacy.mappings:
        old_key_id = int(mapping.agent_key_id)
        old_key = live_by_id.get(old_key_id)
        if old_key is None or old_key_id in legacy.default_key_ids:
            continue
        migrated = await asyncio.to_thread(
            client.create_user_api_key,
            token=wallet_token,
            name=f"image2-u{user.id}-migrated-{old_key_id}",
            group_id=old_key.group_id,
            idempotency_key=f"image2-agent-team-{team_id}-user-{user.id}-legacy-key-{old_key_id}",
            **_legacy_key_create_options(old_key),
        )
        if migrated.id is None:
            raise AgentAPIError("迁移 Key 响应缺少 Key ID")
        remote_updates: dict[str, object] = {}
        if old_key.expires_at:
            remote_updates["expires_at"] = old_key.expires_at
        if old_key.status and old_key.status != "active":
            remote_updates["status"] = old_key.status
        if remote_updates:
            await asyncio.to_thread(
                client.update_user_api_key,
                token=wallet_token,
                key_id=int(migrated.id),
                payload=remote_updates,
            )
        await _record_key(
            db,
            user=user,
            team_id=team_id,
            agent_user_id=int(wallet.agent_user_id),
            key=migrated,
            display_name=mapping.name,
        )


async def _delete_legacy_keys(
    *,
    client: AgentOpenAPIClient,
    legacy: _LegacyAccount | None,
) -> None:
    if legacy is None:
        return
    live_ids = {int(key.id) for key in legacy.live_keys if key.id is not None}
    for mapping in legacy.mappings:
        key_id = int(mapping.agent_key_id)
        if key_id in live_ids:
            await asyncio.to_thread(
                client.delete_user_api_key,
                token=legacy.token,
                key_id=key_id,
            )
        mapping.is_deleted = True


async def sync_agent_account(db: AsyncSession, user: User, password: str | None = None) -> UserAgentAccount | None:
    config = await db.scalar(select(AgentConfig).where(AgentConfig.site_id == user.site_id))
    if config is None or not config.is_enabled:
        return None

    team = await get_agent_billing_team(db, user)
    team_id = int(team.id)
    owner = await db.scalar(
        select(User).where(
            User.id == int(team.owner_user_id),
            User.site_id == user.site_id,
            User.deleted_at.is_(None),
        )
    )
    if owner is None:
        return None

    member_account = await _account_row(db, user, team_id)
    try:
        client = AgentOpenAPIClient(config)
        wallet = await _ensure_wallet(
            db, client=client, config=config, owner=owner, team_id=team_id,
            password=password if user.id == owner.id else None,
        )
        legacy = await _legacy_account(db, client=client, member_account=member_account, wallet=wallet)
        if isinstance(legacy, _DeferredLegacyAccount):
            await _ensure_deferred_legacy_credentials(
                client=client,
                config=config,
                account=member_account,
            )
            member_account.team_id = legacy.team_id
            member_account.status = "active"
            member_account.failure_message = None
            logger.info(
                "deferred agent wallet migration while legacy balance remains "
                "site_id=%s user_id=%s source_team_id=%s target_team_id=%s "
                "source_agent_user_id=%s target_agent_user_id=%s balance=%s",
                user.site_id,
                user.id,
                legacy.team_id,
                team_id,
                member_account.agent_user_id,
                wallet.agent_user_id,
                legacy.balance,
            )
            return member_account

        was_active = member_account.status == "active"
        member_account.team_id = team_id
        member_account.agent_user_id = wallet.agent_user_id
        member_account.agent_email = wallet.agent_email
        member_account.agent_password = wallet.agent_password if member_account.user_id == owner.id else None
        member_account.status = "pending"
        member_account.failure_message = None
        await db.flush()

        mapped_key_count = await db.scalar(
            select(func.count())
            .select_from(UserAgentApiKey)
            .where(
                UserAgentApiKey.team_id == team_id,
                UserAgentApiKey.user_id == user.id,
                UserAgentApiKey.agent_user_id == int(wallet.agent_user_id),
                UserAgentApiKey.is_deleted.is_(False),
            )
        )
        if (
            was_active
            and int(mapped_key_count or 0) > 0
            and member_account.image_api_key
        ):
            member_account.status = "active"
            return member_account

        await _sync_configured_allowed_groups(
            client,
            agent_user_id=int(wallet.agent_user_id),
            config=config,
        )
        token = await asyncio.to_thread(
            client.login_user,
            email=wallet.agent_email,
            password=str(wallet.agent_password),
        )
        existing_keys = await asyncio.to_thread(client.list_user_api_keys, int(wallet.agent_user_id))
        await _migrate_legacy_custom_keys(
            db,
            client=client,
            wallet_token=token,
            wallet=wallet,
            user=user,
            team_id=team_id,
            legacy=legacy,
        )
        text_key = None
        if config.text_group_id:
            try:
                text_key = await _ensure_default_key(
                    db,
                    client=client,
                    token=token,
                    account=member_account,
                    user=user,
                    team_id=team_id,
                    group_id=int(config.text_group_id) if config.text_group_id else None,
                    kind="text",
                    display_name="Token Key",
                    existing_keys=existing_keys,
                )
            except AgentAPIError as error:
                if error.status_code != 404 or "group not found" not in str(error).casefold():
                    raise
                logger.warning(
                    "skipping missing text group site_id=%s user_id=%s text_group_id=%s",
                    user.site_id, user.id, config.text_group_id,
                )
        image_key = await _ensure_default_key(
            db,
            client=client,
            token=token,
            account=member_account,
            user=user,
            team_id=team_id,
            group_id=int(config.image_group_id) if config.image_group_id else None,
            kind="image",
            display_name="图片 / 视频 Key",
            existing_keys=existing_keys,
        )
        await _delete_legacy_keys(client=client, legacy=legacy)
    except AgentAPIError as error:
        logger.warning(
            "agent account sync failed site_id=%s user_id=%s team_id=%s agent_user_id=%s "
            "text_group_id=%s image_group_id=%s: %s",
            user.site_id,
            user.id,
            team_id,
            member_account.agent_user_id,
            config.text_group_id,
            config.image_group_id,
            error,
        )
        member_account.status = "failed"
        member_account.failure_message = _failure_message(error)
        return member_account

    member_account.text_api_key_id = text_key.id if text_key else None
    member_account.text_api_key = text_key.key if text_key else None
    member_account.image_api_key_id = image_key.id
    member_account.image_api_key = image_key.key
    member_account.status = "active"
    member_account.failure_message = None
    return member_account
