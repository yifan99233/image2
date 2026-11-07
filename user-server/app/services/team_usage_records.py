from __future__ import annotations

import asyncio

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BusinessError
from app.models.agent import AgentConfig, UserAgentAccount, UserAgentApiKey
from app.models.user import User
from app.services.agent_openapi import AgentAPIError, AgentOpenAPIClient
from app.services.agent_usage import list_usage_for_api_keys, usage_record_api_key_id, usage_record_out
from app.services.team_sharing import get_or_create_user_team, user_team_members_table


def _member_out(row) -> dict:
    return {
        "membership_id": int(row.membership_id),
        "user_id": int(row.user_id),
        "username": row.username,
        "nickname": row.nickname,
        "email": row.email,
        "role": row.role,
    }


async def list_team_usage_records(
    db: AsyncSession,
    current_user: User,
    *,
    page: int,
    page_size: int,
    member_user_id: int | None,
    start_date: str | None,
    end_date: str | None,
) -> dict:
    team = await get_or_create_user_team(db, current_user)
    members = (
        await db.execute(
            select(
                user_team_members_table.c.id.label("membership_id"),
                user_team_members_table.c.user_id,
                user_team_members_table.c.role,
                User.username,
                User.nickname,
                User.email,
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
            .where(
                user_team_members_table.c.site_id == current_user.site_id,
                user_team_members_table.c.team_id == int(team.id),
                User.site_id == current_user.site_id,
                User.deleted_at.is_(None),
            )
        )
    ).all()
    current_member = next((row for row in members if int(row.user_id) == current_user.id), None)
    if current_member is None or current_member.agent_account_status != "active" or current_member.agent_user_id is None:
        raise BusinessError("团队账户尚未准备完成", code=50388, status_code=503)
    agent_user_id = int(current_member.agent_user_id)

    member_by_user_id = {int(row.user_id): _member_out(row) for row in members}
    if member_user_id is not None and member_user_id not in member_by_user_id:
        raise BusinessError("团队成员不存在", code=40485, status_code=404)

    mappings = (
        await db.execute(
            select(UserAgentApiKey).where(
                UserAgentApiKey.site_id == current_user.site_id,
                UserAgentApiKey.team_id == int(team.id),
                UserAgentApiKey.agent_user_id == agent_user_id,
            )
        )
    ).scalars().all()
    member_by_key_id: dict[int, dict] = {}
    key_ids_by_user_id: dict[int, list[int]] = {user_id: [] for user_id in member_by_user_id}
    for mapping in mappings:
        user_id = int(mapping.user_id)
        member = member_by_user_id.get(user_id)
        if member is None:
            continue
        key_id = int(mapping.agent_key_id)
        member_by_key_id[key_id] = member
        key_ids_by_user_id[user_id].append(key_id)

    for row in members:
        if row.agent_user_id is None or int(row.agent_user_id) != agent_user_id:
            continue
        member = member_by_user_id[int(row.user_id)]
        for legacy_key_id in (row.text_api_key_id, row.image_api_key_id):
            if legacy_key_id is None:
                continue
            key_id = int(legacy_key_id)
            member_by_key_id.setdefault(key_id, member)
            key_ids_by_user_id[int(row.user_id)].append(key_id)

    config = await db.scalar(
        select(AgentConfig).where(AgentConfig.site_id == current_user.site_id, AgentConfig.is_enabled.is_(True))
    )
    if config is None or not config.base_url or not config.admin_api_key:
        raise BusinessError("使用记录服务尚未配置", code=50389, status_code=503)
    client = AgentOpenAPIClient(config)
    try:
        if member_user_id is not None:
            result = await list_usage_for_api_keys(
                client,
                agent_user_id=agent_user_id,
                api_key_ids=key_ids_by_user_id.get(member_user_id, []),
                page=page,
                page_size=page_size,
                start_date=start_date,
                end_date=end_date,
            )
        else:
            result = await asyncio.to_thread(
                client.list_user_usage,
                agent_user_id=agent_user_id,
                page=page,
                page_size=page_size,
                start_date=start_date,
                end_date=end_date,
            )
    except AgentAPIError as error:
        raise BusinessError("团队使用记录查询失败，请稍后重试", code=50288, status_code=502) from error

    unassigned_member = {
        "membership_id": None,
        "user_id": None,
        "username": "",
        "nickname": "未归属 Key",
        "email": "",
        "role": "",
    }
    return {
        "items": [
            usage_record_out(
                row,
                member=member_by_key_id.get(usage_record_api_key_id(row), unassigned_member),
            )
            for row in result["items"]
        ],
        "total": int(result["total"]),
        "page": int(result["page"]),
        "page_size": int(result["page_size"]),
    }
