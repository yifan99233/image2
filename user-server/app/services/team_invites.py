from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode, urlsplit

from jose import JWTError, jwt
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import BusinessError
from app.models.user import User
from app.services.site_scope import site_configs_table
from app.services.team_sharing import (
    can_manage_team_members,
    get_team_entitlement_summary,
    user_team_members_table,
    user_teams_table,
)

TEAM_INVITE_TOKEN_TYPE = "team_invite"


def create_team_invite_token(*, team_id: int, site_id: int, issuer_user_id: int) -> tuple[str, datetime]:
    issued_at = datetime.now(UTC)
    expires_at = issued_at + timedelta(days=settings.team_invite_token_expire_days)
    payload = {
        "typ": TEAM_INVITE_TOKEN_TYPE,
        "team_id": int(team_id),
        "site_id": int(site_id),
        "issuer_user_id": int(issuer_user_id),
        "iat": issued_at,
        "exp": expires_at,
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm), expires_at


def decode_team_invite_token(token: str) -> dict:
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
        if payload.get("typ") != TEAM_INVITE_TOKEN_TYPE:
            raise ValueError("unexpected token type")
        team_id = int(payload["team_id"])
        site_id = int(payload["site_id"])
        issuer_user_id = int(payload["issuer_user_id"])
        expires_at = datetime.fromtimestamp(int(payload["exp"]), tz=UTC)
        if min(team_id, site_id, issuer_user_id) <= 0:
            raise ValueError("invalid identifiers")
    except (JWTError, KeyError, TypeError, ValueError) as exc:
        raise BusinessError("团队邀请链接无效或已过期", code=40078) from exc
    return {
        "team_id": team_id,
        "site_id": site_id,
        "issuer_user_id": issuer_user_id,
        "expires_at": expires_at,
    }


async def _validated_team_invite_context(
    db: AsyncSession,
    *,
    token: str,
    current_site_id: int,
    lock_for_join: bool,
):
    claims = decode_team_invite_token(token)
    if claims["site_id"] != current_site_id:
        raise BusinessError("该团队邀请链接不适用于当前站点", code=40079)

    statement = (
        select(
            user_teams_table.c.id,
            user_teams_table.c.name,
            user_teams_table.c.owner_user_id,
            user_team_members_table.c.role.label("issuer_role"),
        )
        .select_from(
            user_teams_table.join(
                user_team_members_table,
                (user_team_members_table.c.team_id == user_teams_table.c.id)
                & (user_team_members_table.c.site_id == user_teams_table.c.site_id),
            )
        )
        .where(
            user_teams_table.c.id == claims["team_id"],
            user_teams_table.c.site_id == current_site_id,
            user_team_members_table.c.user_id == claims["issuer_user_id"],
        )
    )
    if lock_for_join:
        statement = statement.with_for_update()
    team = (await db.execute(statement)).first()
    if team is None or not can_manage_team_members(str(team.issuer_role)):
        raise BusinessError("团队邀请链接已失效", code=40080)

    entitlement = await get_team_entitlement_summary(
        db,
        site_id=current_site_id,
        owner_user_id=int(team.owner_user_id),
    )
    if not entitlement.collaboration_enabled:
        raise BusinessError("当前团队尚未开通团队版", code=40375, status_code=403)

    member_count = await db.scalar(
        select(func.count())
        .select_from(user_team_members_table)
        .where(
            user_team_members_table.c.team_id == team.id,
            user_team_members_table.c.site_id == current_site_id,
        )
    )
    if int(member_count or 0) >= entitlement.seat_limit:
        raise BusinessError("团队席位已用完，暂时无法通过链接加入", code=40974, status_code=409)
    return claims, team


async def get_team_invite_preview(db: AsyncSession, *, token: str, current_site_id: int) -> dict:
    claims, team = await _validated_team_invite_context(
        db,
        token=token,
        current_site_id=current_site_id,
        lock_for_join=False,
    )
    site_name = await db.scalar(
        select(site_configs_table.c.site_name).where(site_configs_table.c.id == current_site_id)
    )
    return {
        "team_name": str(team.name),
        "site_name": str(site_name or ""),
        "expires_at": claims["expires_at"].isoformat(),
    }


async def create_team_invite_link(db: AsyncSession, *, current_user: User, team_id: int) -> dict:
    frontend_url = await db.scalar(
        select(site_configs_table.c.frontend_url).where(
            site_configs_table.c.id == current_user.site_id,
            site_configs_table.c.is_enabled.is_(True),
        )
    )
    normalized_frontend_url = str(frontend_url or "").strip().rstrip("/")
    parsed_frontend_url = urlsplit(normalized_frontend_url)
    if parsed_frontend_url.scheme not in {"http", "https"} or not parsed_frontend_url.netloc:
        raise BusinessError("当前站点尚未配置可用的前台地址", code=50078, status_code=500)

    token, expires_at = create_team_invite_token(
        team_id=team_id,
        site_id=int(current_user.site_id),
        issuer_user_id=int(current_user.id),
    )
    query = urlencode({"team_invite_token": token})
    return {
        "invite_url": f"{normalized_frontend_url}/register?{query}",
        "expires_at": expires_at.isoformat(),
    }


async def join_team_from_invite(db: AsyncSession, *, invitee: User, token: str) -> int:
    _, team = await _validated_team_invite_context(
        db,
        token=token,
        current_site_id=int(invitee.site_id),
        lock_for_join=True,
    )
    await db.execute(
        user_team_members_table.insert().values(
            site_id=invitee.site_id,
            team_id=team.id,
            user_id=invitee.id,
            role="member",
        )
    )
    invitee.active_team_id = int(team.id)
    await db.execute(
        update(User)
        .where(User.id == invitee.id, User.site_id == invitee.site_id)
        .values(active_team_id=team.id)
    )
    return int(team.id)
