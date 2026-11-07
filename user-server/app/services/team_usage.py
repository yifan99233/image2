from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, replace
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BusinessError
from app.models.agent import AgentConfig, TeamMemberUsageLimit, UserAgentAccount, UserAgentApiKey
from app.models.user import User
from app.services.agent_openapi import AgentAPIError, AgentAPIKey, AgentAPIKeyUsage, AgentOpenAPIClient
from app.services.team_sharing import get_or_create_user_team, user_team_members_table

logger = logging.getLogger(__name__)

QUOTA_PRECISION = Decimal("0.0001")
TEAM_USAGE_PAGE_SIZE_MAX = 100


@dataclass(frozen=True)
class _MemberKeyBindings:
    text_key_ids: tuple[int, ...] = ()
    image_key_ids: tuple[int, ...] = ()
    text_usage_key_ids: tuple[int, ...] = ()
    image_usage_key_ids: tuple[int, ...] = ()

    @property
    def all_usage_key_ids(self) -> tuple[int, ...]:
        return tuple(dict.fromkeys((*self.text_usage_key_ids, *self.image_usage_key_ids)))


@dataclass(frozen=True)
class _AgentSnapshot:
    balance: Decimal
    keys: tuple[AgentAPIKey, ...]
    usage_by_key_id: dict[int, AgentAPIKeyUsage]


def normalize_quota(value: Decimal) -> Decimal:
    if value < 0:
        raise BusinessError("额度不能小于 0", code=40082)
    return value.quantize(QUOTA_PRECISION, rounding=ROUND_HALF_UP)


def _quota_out(key: AgentAPIKey) -> dict:
    quota = max(Decimal("0"), key.quota)
    used = max(Decimal("0"), key.quota_used)
    unlimited = quota == 0
    return {
        "quota": float(quota),
        "used": float(used),
        "remaining": None if unlimited else float(max(Decimal("0"), quota - used)),
        "unlimited": unlimited,
        "status": key.status or "active",
    }


def _find_bound_key(keys: list[AgentAPIKey], key_id: int | None, label: str) -> AgentAPIKey:
    if key_id is None:
        raise AgentAPIError(f"{label} Key 尚未绑定")
    key = next((candidate for candidate in keys if candidate.id == int(key_id)), None)
    if key is None:
        raise AgentAPIError(f"{label} Key 不存在或不属于该账户")
    return key


def _quota_assignments(keys: list[AgentAPIKey], target: Decimal) -> dict[int, Decimal]:
    if not keys or any(key.id is None for key in keys):
        raise AgentAPIError("成员 Key 缺少 ID")
    used_total = sum((max(Decimal("0"), key.quota_used) for key in keys), Decimal("0"))
    if target > 0 and target < used_total:
        raise BusinessError("新额度不能低于成员已产生的用量", code=40083)
    if target == 0:
        return {int(key.id): Decimal("0") for key in keys}
    assignments = {int(key.id): max(Decimal("0"), key.quota_used) for key in keys}
    remaining = target - used_total
    available = {
        int(key.id): max(Decimal("0"), key.quota - key.quota_used)
        for key in keys
        if key.quota > 0 and key.status == "active"
    }
    total_available = sum(available.values(), Decimal("0"))
    if total_available > 0:
        for key_id, capacity in available.items():
            share = remaining * capacity / total_available
            assignments[key_id] += share
    else:
        active_key = next((key for key in keys if key.status == "active"), keys[0])
        assignments[int(active_key.id)] += remaining
    rounded = {key_id: value.quantize(QUOTA_PRECISION, rounding=ROUND_HALF_UP) for key_id, value in assignments.items()}
    delta = target - sum(rounded.values(), Decimal("0"))
    if delta:
        first_key_id = int(keys[0].id)
        rounded[first_key_id] += delta
    return rounded


async def _apply_key_quota_assignments(
    client: AgentOpenAPIClient,
    *,
    keys: list[AgentAPIKey],
    assignments: dict[int, Decimal],
) -> list[tuple[int, Decimal]]:
    changed: list[tuple[int, Decimal]] = []
    try:
        for key in keys:
            if key.id is None or assignments[int(key.id)] == key.quota:
                continue
            await asyncio.to_thread(client.update_api_key, int(key.id), quota=assignments[int(key.id)])
            changed.append((int(key.id), key.quota))
    except (AgentAPIError, ValueError) as error:
        compensation_failed = await _restore_quotas(client, changed)
        if compensation_failed:
            raise BusinessError("额度更新异常，请联系管理员核对", code=50287, status_code=502) from error
        raise BusinessError("额度更新失败，已恢复原额度", code=50287, status_code=502) from error
    return changed


def _fetch_agent_snapshot(
    client: AgentOpenAPIClient,
    *,
    agent_user_id: int,
    agent_email: str,
    agent_password: str,
    usage_key_ids: list[int],
) -> _AgentSnapshot:
    agent_user = client.get_user(agent_user_id)
    keys = client.list_user_api_keys(agent_user_id)
    token = client.login_user(email=agent_email, password=agent_password)
    usage_by_key_id = client.get_api_keys_usage(token=token, api_key_ids=usage_key_ids)
    return _AgentSnapshot(balance=agent_user.balance, keys=tuple(keys), usage_by_key_id=usage_by_key_id)


def _aggregate_keys(
    keys: tuple[AgentAPIKey, ...] | list[AgentAPIKey],
    key_ids: tuple[int, ...] | list[int],
    usage_key_ids: tuple[int, ...] | list[int],
    usage_by_key_id: dict[int, AgentAPIKeyUsage],
    label: str,
    quota_override: Decimal | None,
) -> AgentAPIKey:
    selected = [key for key in keys if key.id is not None and int(key.id) in key_ids]
    if not selected:
        raise AgentAPIError(f"{label} Key 尚未绑定")
    quota = quota_override if quota_override is not None else (
        Decimal("0") if any(key.quota == 0 for key in selected) else sum((key.quota for key in selected), Decimal("0"))
    )
    statuses = {key.status for key in selected}
    status = "active" if "active" in statuses else next(iter(statuses), "active")
    used = sum(
        (usage_by_key_id[key_id].total_actual_cost for key_id in usage_key_ids if key_id in usage_by_key_id),
        Decimal("0"),
    )
    return AgentAPIKey(
        id=selected[0].id,
        key="",
        quota=quota,
        quota_used=used,
        status=status,
    )


async def _member_key_state(
    db: AsyncSession,
    *,
    team_id: int,
    user_ids: list[int],
    config: AgentConfig,
) -> tuple[dict[int, _MemberKeyBindings], dict[int, tuple[Decimal, Decimal]]]:
    key_rows = (
        await db.execute(
            select(UserAgentApiKey).where(
                UserAgentApiKey.team_id == team_id,
                UserAgentApiKey.user_id.in_(user_ids),
            )
        )
    ).scalars().all()
    mutable_bindings: dict[int, dict[str, list[int]]] = {
        user_id: {"text": [], "image": [], "text_usage": [], "image_usage": []}
        for user_id in user_ids
    }
    for mapping in key_rows:
        binding = mutable_bindings.setdefault(
            int(mapping.user_id),
            {"text": [], "image": [], "text_usage": [], "image_usage": []},
        )
        if mapping.group_id == config.text_group_id:
            binding["text_usage"].append(int(mapping.agent_key_id))
            if not mapping.is_deleted:
                binding["text"].append(int(mapping.agent_key_id))
        if mapping.group_id is not None and (mapping.group_id == config.image_group_id or mapping.group_id != config.text_group_id):
            binding["image_usage"].append(int(mapping.agent_key_id))
            if not mapping.is_deleted:
                binding["image"].append(int(mapping.agent_key_id))
    legacy_accounts = (
        await db.execute(select(UserAgentAccount).where(UserAgentAccount.user_id.in_(user_ids)))
    ).scalars().all()
    for account in legacy_accounts:
        binding = mutable_bindings.setdefault(
            int(account.user_id),
            {"text": [], "image": [], "text_usage": [], "image_usage": []},
        )
        if account.text_api_key_id is not None:
            key_id = int(account.text_api_key_id)
            if not binding["text"]:
                binding["text"].append(key_id)
            binding["text_usage"].append(key_id)
        if account.image_api_key_id is not None:
            key_id = int(account.image_api_key_id)
            if not binding["image"]:
                binding["image"].append(key_id)
            binding["image_usage"].append(key_id)
    bindings = {
        user_id: _MemberKeyBindings(
            text_key_ids=tuple(dict.fromkeys(binding["text"])),
            image_key_ids=tuple(dict.fromkeys(binding["image"])),
            text_usage_key_ids=tuple(dict.fromkeys(binding["text_usage"])),
            image_usage_key_ids=tuple(dict.fromkeys(binding["image_usage"])),
        )
        for user_id, binding in mutable_bindings.items()
    }
    limit_rows = (
        await db.execute(
            select(TeamMemberUsageLimit).where(
                TeamMemberUsageLimit.team_id == team_id,
                TeamMemberUsageLimit.user_id.in_(user_ids),
            )
        )
    ).scalars().all()
    limits = {
        int(row.user_id): (Decimal(str(row.text_quota)), Decimal(str(row.image_quota)))
        for row in limit_rows
    }
    return bindings, limits


async def _wallet_credentials(
    db: AsyncSession,
    *,
    team_id: int,
    agent_user_ids: list[int],
) -> dict[int, tuple[str, str]]:
    if not agent_user_ids:
        return {}
    rows = (
        await db.execute(
            select(
                UserAgentAccount.agent_user_id,
                UserAgentAccount.agent_email,
                UserAgentAccount.agent_password,
            )
            .where(
                UserAgentAccount.team_id == team_id,
                UserAgentAccount.agent_user_id.in_(agent_user_ids),
                UserAgentAccount.agent_email.is_not(None),
                UserAgentAccount.agent_password.is_not(None),
            )
            .order_by(UserAgentAccount.user_id.asc())
        )
    ).all()
    credentials: dict[int, tuple[str, str]] = {}
    for row in rows:
        if row.agent_user_id is None or not row.agent_email or not row.agent_password:
            continue
        credentials.setdefault(int(row.agent_user_id), (str(row.agent_email), str(row.agent_password)))
    return credentials


async def _fetch_team_snapshots(
    db: AsyncSession,
    *,
    team_id: int,
    client: AgentOpenAPIClient,
    usage_key_ids_by_agent_user_id: dict[int, set[int]],
) -> dict[int, _AgentSnapshot]:
    agent_user_ids = sorted(usage_key_ids_by_agent_user_id)
    credentials = await _wallet_credentials(db, team_id=team_id, agent_user_ids=agent_user_ids)
    missing_credentials = [agent_user_id for agent_user_id in agent_user_ids if agent_user_id not in credentials]
    if missing_credentials:
        raise AgentAPIError("团队账户凭据尚未准备完成")
    fetched = await asyncio.gather(
        *(
            asyncio.to_thread(
                _fetch_agent_snapshot,
                client,
                agent_user_id=agent_user_id,
                agent_email=credentials[agent_user_id][0],
                agent_password=credentials[agent_user_id][1],
                usage_key_ids=sorted(usage_key_ids_by_agent_user_id[agent_user_id]),
            )
            for agent_user_id in agent_user_ids
        )
    )
    return dict(zip(agent_user_ids, fetched))


async def _apply_quota_updates(
    client: AgentOpenAPIClient,
    *,
    text_key: AgentAPIKey,
    image_key: AgentAPIKey,
    text_quota: Decimal,
    image_quota: Decimal,
) -> list[tuple[int, Decimal]]:
    if text_key.id is None or image_key.id is None:
        raise AgentAPIError("账户 Key 缺少 ID")
    changed: list[tuple[int, Decimal]] = []
    try:
        if text_key.quota != text_quota:
            await asyncio.to_thread(client.update_api_key, int(text_key.id), quota=text_quota)
            changed.append((int(text_key.id), text_key.quota))
        if image_key.quota != image_quota:
            await asyncio.to_thread(client.update_api_key, int(image_key.id), quota=image_quota)
            changed.append((int(image_key.id), image_key.quota))
    except (AgentAPIError, ValueError) as error:
        compensation_failed = await _restore_quotas(client, changed)
        if compensation_failed:
            raise BusinessError("额度更新异常，请联系管理员核对", code=50287, status_code=502) from error
        raise BusinessError("额度更新失败，已恢复原额度", code=50287, status_code=502) from error
    return changed


async def _get_agent_config(db: AsyncSession, site_id: int) -> AgentConfig:
    config = await db.scalar(
        select(AgentConfig).where(AgentConfig.site_id == site_id, AgentConfig.is_enabled.is_(True))
    )
    if config is None or not config.base_url or not config.admin_api_key:
        raise BusinessError("额度服务尚未配置", code=50385, status_code=503)
    return config


def _member_identity(row) -> dict:
    return {
        "membership_id": int(row.membership_id),
        "user_id": int(row.user_id),
        "username": row.username,
        "nickname": row.nickname,
        "email": row.email,
        "avatar_url": row.avatar_url,
        "role": row.role,
    }


def _usage_payload(
    row,
    balance: Decimal,
    text_key: AgentAPIKey,
    image_key: AgentAPIKey,
    *,
    include_balance: bool = False,
) -> dict:
    text_usage = _quota_out(text_key)
    image_usage = _quota_out(image_key)
    payload = {
        **_member_identity(row),
        "account_status": "active",
        "available": True,
        "text": text_usage,
        "image": image_usage,
        "total_used": text_usage["used"] + image_usage["used"],
    }
    if include_balance:
        payload["balance"] = float(balance)
    return payload


def _member_select():
    return (
        select(
            user_team_members_table.c.id.label("membership_id"),
            user_team_members_table.c.user_id,
            user_team_members_table.c.role,
            User.username,
            User.nickname,
            User.email,
            User.avatar_url,
            UserAgentAccount.agent_user_id,
            UserAgentAccount.text_api_key_id,
            UserAgentAccount.image_api_key_id,
            UserAgentAccount.status.label("agent_account_status"),
        )
        .select_from(
            user_team_members_table.join(User, User.id == user_team_members_table.c.user_id).outerjoin(
                UserAgentAccount, UserAgentAccount.user_id == User.id
            )
        )
    )


async def _live_member_usage(
    row,
    *,
    bindings: _MemberKeyBindings,
    limits: tuple[Decimal, Decimal] | None,
    snapshots: dict[int, _AgentSnapshot],
    tolerate_failure: bool,
    include_balance: bool = False,
) -> dict:
    identity = _member_identity(row)
    if (
        row.agent_account_status != "active"
        or row.agent_user_id is None
        or not bindings.text_key_ids
        or not bindings.image_key_ids
    ):
        payload = {**identity, "account_status": row.agent_account_status or "not_ready", "available": False}
        if tolerate_failure:
            return payload
        raise BusinessError("账户额度尚未准备完成", code=50386, status_code=503)

    try:
        snapshot = snapshots[int(row.agent_user_id)]
        text_key = _aggregate_keys(
            snapshot.keys,
            bindings.text_key_ids,
            bindings.text_usage_key_ids,
            snapshot.usage_by_key_id,
            "Token",
            limits[0] if limits else None,
        )
        image_key = _aggregate_keys(
            snapshot.keys,
            bindings.image_key_ids,
            bindings.image_usage_key_ids,
            snapshot.usage_by_key_id,
            "图片/视频",
            limits[1] if limits else None,
        )
    except (AgentAPIError, KeyError) as error:
        logger.warning("team usage snapshot failed user_id=%s: %s", row.user_id, error)
        if tolerate_failure:
            return {**identity, "account_status": "unavailable", "available": False}
        raise BusinessError("额度与用量查询失败，请稍后重试", code=50285, status_code=502) from error

    return _usage_payload(row, snapshot.balance, text_key, image_key, include_balance=include_balance)


async def get_my_usage(db: AsyncSession, current_user: User) -> dict:
    team = await get_or_create_user_team(db, current_user)
    row = (
        await db.execute(
            _member_select().where(
                user_team_members_table.c.site_id == current_user.site_id,
                user_team_members_table.c.team_id == int(team.id),
                user_team_members_table.c.user_id == current_user.id,
                User.site_id == current_user.site_id,
                User.deleted_at.is_(None),
            )
        )
    ).first()
    if row is None:
        raise BusinessError("你不是当前团队成员", code=40482, status_code=404)
    config = await _get_agent_config(db, current_user.site_id)
    bindings, limits = await _member_key_state(db, team_id=int(team.id), user_ids=[current_user.id], config=config)
    client = AgentOpenAPIClient(config)
    member_bindings = bindings[current_user.id]
    if row.agent_user_id is None:
        return await _live_member_usage(
            row,
            bindings=member_bindings,
            limits=limits.get(current_user.id),
            snapshots={},
            tolerate_failure=False,
        )
    try:
        snapshots = await _fetch_team_snapshots(
            db,
            team_id=int(team.id),
            client=client,
            usage_key_ids_by_agent_user_id={
                int(row.agent_user_id): set(member_bindings.all_usage_key_ids),
            },
        )
    except AgentAPIError as error:
        raise BusinessError("额度与用量查询失败，请稍后重试", code=50285, status_code=502) from error
    return await _live_member_usage(
        row,
        bindings=member_bindings,
        limits=limits.get(current_user.id),
        snapshots=snapshots,
        tolerate_failure=False,
        include_balance=row.role in {"owner", "admin"},
    )


async def list_team_member_usage(
    db: AsyncSession,
    current_user: User,
    *,
    page: int,
    page_size: int,
    search: str,
) -> dict:
    team = await get_or_create_user_team(db, current_user)
    normalized_page_size = min(TEAM_USAGE_PAGE_SIZE_MAX, max(1, page_size))
    normalized_page = max(1, page)
    conditions = [
        user_team_members_table.c.site_id == current_user.site_id,
        user_team_members_table.c.team_id == int(team.id),
        User.site_id == current_user.site_id,
        User.deleted_at.is_(None),
    ]
    query = search.strip()
    if query:
        pattern = f"%{query[:100]}%"
        conditions.append(
            or_(User.username.ilike(pattern), User.nickname.ilike(pattern), User.email.ilike(pattern))
        )

    total = await db.scalar(
        select(func.count())
        .select_from(user_team_members_table.join(User, User.id == user_team_members_table.c.user_id))
        .where(*conditions)
    )
    rows = (
        await db.execute(
            _member_select()
            .where(*conditions)
            .order_by(
                (user_team_members_table.c.role == "owner").desc(),
                user_team_members_table.c.created_at.asc(),
                user_team_members_table.c.id.asc(),
            )
            .offset((normalized_page - 1) * normalized_page_size)
            .limit(normalized_page_size)
        )
    ).all()
    config = await _get_agent_config(db, current_user.site_id)
    bindings, limits = await _member_key_state(db, team_id=int(team.id), user_ids=[int(row.user_id) for row in rows], config=config)
    client = AgentOpenAPIClient(config)
    usage_key_ids_by_agent_user_id: dict[int, set[int]] = {}
    for row in rows:
        if row.agent_user_id is None:
            continue
        member_bindings = bindings.get(int(row.user_id), _MemberKeyBindings())
        usage_key_ids_by_agent_user_id.setdefault(int(row.agent_user_id), set()).update(
            member_bindings.all_usage_key_ids
        )
    snapshots: dict[int, _AgentSnapshot] = {}
    try:
        snapshots = await _fetch_team_snapshots(
            db,
            team_id=int(team.id),
            client=client,
            usage_key_ids_by_agent_user_id=usage_key_ids_by_agent_user_id,
        )
    except AgentAPIError:
        logger.warning("team usage shared snapshot failed team_id=%s", team.id)
    items = await asyncio.gather(
        *(
            _live_member_usage(
                row,
                bindings=bindings.get(int(row.user_id), _MemberKeyBindings()),
                limits=limits.get(int(row.user_id)),
                snapshots=snapshots,
                tolerate_failure=True,
            )
            for row in rows
        )
    )
    return {
        "items": items,
        "total": int(total or 0),
        "page": normalized_page,
        "page_size": normalized_page_size,
    }


async def update_team_member_quotas(
    db: AsyncSession,
    current_user: User,
    *,
    membership_id: int,
    text_quota: Decimal,
    image_quota: Decimal,
) -> dict:
    team = await get_or_create_user_team(db, current_user)
    row = (
        await db.execute(
            _member_select().where(
                user_team_members_table.c.id == membership_id,
                user_team_members_table.c.site_id == current_user.site_id,
                user_team_members_table.c.team_id == int(team.id),
                User.site_id == current_user.site_id,
                User.deleted_at.is_(None),
            )
        )
    ).first()
    if row is None:
        raise BusinessError("团队成员不存在", code=40483, status_code=404)
    if (
        row.agent_account_status != "active"
        or row.agent_user_id is None
    ):
        raise BusinessError("该成员的额度账户尚未准备完成", code=40983, status_code=409)

    normalized_text_quota = normalize_quota(text_quota)
    normalized_image_quota = normalize_quota(image_quota)
    config = await _get_agent_config(db, current_user.site_id)
    client = AgentOpenAPIClient(config)
    try:
        bindings, _limits = await _member_key_state(
            db,
            team_id=int(team.id),
            user_ids=[int(row.user_id)],
            config=config,
        )
        member_bindings = bindings[int(row.user_id)]
        snapshots = await _fetch_team_snapshots(
            db,
            team_id=int(team.id),
            client=client,
            usage_key_ids_by_agent_user_id={
                int(row.agent_user_id): set(member_bindings.all_usage_key_ids),
            },
        )
    except AgentAPIError as error:
        raise BusinessError("该成员的额度信息读取失败", code=50286, status_code=502) from error
    snapshot = snapshots[int(row.agent_user_id)]
    keys = snapshot.keys
    text_ids = member_bindings.text_key_ids
    image_ids = member_bindings.image_key_ids
    text_keys = [key for key in keys if key.id is not None and int(key.id) in text_ids]
    image_keys = [key for key in keys if key.id is not None and int(key.id) in image_ids]
    if not text_keys or not image_keys:
        raise BusinessError("该成员的 Key 尚未准备完成", code=40983, status_code=409)
    text_assignments = _quota_assignments(text_keys, normalized_text_quota)
    image_assignments = _quota_assignments(image_keys, normalized_image_quota)
    changed = await _apply_key_quota_assignments(client, keys=[*text_keys, *image_keys], assignments={**text_assignments, **image_assignments})

    try:
        statement = pg_insert(TeamMemberUsageLimit).values(
            site_id=current_user.site_id,
            team_id=int(team.id),
            user_id=int(row.user_id),
            text_quota=normalized_text_quota,
            image_quota=normalized_image_quota,
            updated_by_user_id=current_user.id,
        )
        await db.execute(
            statement.on_conflict_do_update(
                constraint="uq_team_member_usage_limits_team_user",
                set_={
                    "site_id": current_user.site_id,
                    "text_quota": normalized_text_quota,
                    "image_quota": normalized_image_quota,
                    "updated_by_user_id": current_user.id,
                    "updated_at": func.now(),
                },
            )
        )
        await db.commit()
    except Exception as error:
        await db.rollback()
        compensation_failed = await _restore_quotas(client, changed)
        logger.exception("failed to persist quota audit membership_id=%s", membership_id)
        message = "额度保存失败，已恢复原额度" if not compensation_failed else "额度保存异常，请联系管理员核对"
        raise BusinessError(message, code=50387, status_code=503) from error

    return _usage_payload(
        row,
        snapshot.balance,
        replace(
            _aggregate_keys(
                keys,
                text_ids,
                member_bindings.text_usage_key_ids,
                snapshot.usage_by_key_id,
                "Token",
                normalized_text_quota,
            ),
            quota=normalized_text_quota,
        ),
        replace(
            _aggregate_keys(
                keys,
                image_ids,
                member_bindings.image_usage_key_ids,
                snapshot.usage_by_key_id,
                "图片/视频",
                normalized_image_quota,
            ),
            quota=normalized_image_quota,
        ),
    )


async def _restore_quotas(client: AgentOpenAPIClient, changed: list[tuple[int, Decimal]]) -> bool:
    failed = False
    for key_id, original_quota in reversed(changed):
        try:
            await asyncio.to_thread(client.update_api_key, key_id, quota=original_quota)
        except (AgentAPIError, ValueError):
            failed = True
            logger.exception("quota compensation failed key_id=%s", key_id)
    return failed
