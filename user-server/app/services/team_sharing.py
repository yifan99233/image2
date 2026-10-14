from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import BigInteger, Boolean, Column, DateTime, Integer, MetaData, String, Table, and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BusinessError
from app.models.user import User
from app.services.site_scope import site_configs_table

metadata = MetaData()

TEAM_MEMBER_ROLES = {"admin", "member"}
TEAM_MANAGER_ROLES = {"owner", "admin"}
TEAM_COLLABORATION_MIN_SEATS = 2

# Team-console permissions are deliberately independent from platform-admin roles.
# The console is scoped to one team in one site; it must never become a path to
# provider, gateway, or cross-customer administration.
TEAM_CONSOLE_ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    "owner": frozenset(
        {
            "team:view",
            "team:settings:update",
            "members:view",
            "members:create",
            "members:remove",
            "members:role:update",
            "departments:view",
            "departments:manage",
            "budgets:view",
            "budgets:manage",
            "budgets:self:view",
            "usage:view",
            "usage:self:view",
        }
    ),
    "admin": frozenset(
        {
            "team:view",
            "members:view",
            "members:create",
            "members:remove",
            "departments:view",
            "budgets:view",
            "budgets:manage",
            "budgets:self:view",
            "usage:view",
            "usage:self:view",
        }
    ),
    "member": frozenset(
        {
            "team:view",
            "budgets:self:view",
            "usage:self:view",
        }
    ),
}

user_teams_table = Table(
    "user_teams",
    metadata,
    Column("id", BigInteger),
    Column("site_id", BigInteger),
    Column("owner_user_id", BigInteger),
    Column("name", String),
    Column("material_library_shared", Boolean),
    Column("image_history_shared", Boolean),
    Column("created_at", DateTime(timezone=True)),
    Column("updated_at", DateTime(timezone=True)),
)

user_team_members_table = Table(
    "user_team_members",
    metadata,
    Column("id", BigInteger),
    Column("site_id", BigInteger),
    Column("team_id", BigInteger),
    Column("user_id", BigInteger),
    Column("role", String),
    Column("created_at", DateTime(timezone=True)),
    Column("updated_at", DateTime(timezone=True)),
)

team_entitlements_table = Table(
    "team_entitlements",
    metadata,
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


@dataclass(frozen=True)
class TeamEntitlementSummary:
    seat_limit: int = 0
    expires_at: datetime | None = None
    has_permanent_access: bool = False
    grant_count: int = 0

    @property
    def collaboration_enabled(self) -> bool:
        return self.seat_limit >= TEAM_COLLABORATION_MIN_SEATS


def team_entitlement_out(summary: TeamEntitlementSummary, member_count: int) -> dict:
    return {
        "collaboration_enabled": summary.collaboration_enabled,
        "seat_limit": summary.seat_limit,
        "seats_used": member_count,
        "seats_available": max(0, summary.seat_limit - member_count),
        "entitlement_expires_at": None if summary.has_permanent_access else (summary.expires_at.isoformat() if summary.expires_at else None),
    }


def team_out(
    row,
    member_count: int = 1,
    current_role: str | None = None,
    entitlement: TeamEntitlementSummary | None = None,
) -> dict:
    payload = {
        "id": row.id,
        "name": row.name,
        "owner_user_id": row.owner_user_id,
        "material_library_shared": bool(row.material_library_shared),
        "image_history_shared": bool(row.image_history_shared),
        "member_count": member_count,
        "current_role": current_role or getattr(row, "current_role", None),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }
    payload.update(team_entitlement_out(entitlement or TeamEntitlementSummary(), member_count))
    return payload


def team_member_out(row) -> dict:
    return {
        "membership_id": int(row.membership_id),
        "user_id": int(row.user_id),
        "username": row.username,
        "nickname": row.nickname,
        "email": row.email,
        "avatar_url": row.avatar_url,
        "role": row.role,
        "joined_at": row.joined_at.isoformat() if row.joined_at else None,
    }


def normalize_member_role(value: str | None) -> str:
    role = (value or "member").strip().lower()
    if role not in TEAM_MEMBER_ROLES:
        raise BusinessError("团队角色仅支持 admin 或 member", code=40070)
    return role


def can_manage_team_members(current_role: str | None) -> bool:
    return current_role in TEAM_MANAGER_ROLES


def team_console_permissions(current_role: str | None) -> list[str]:
    """Return the explicit capability set for the isolated customer console."""
    return sorted(TEAM_CONSOLE_ROLE_PERMISSIONS.get(current_role or "member", frozenset()))


def can_access_team_console(current_role: str | None) -> bool:
    return "team:view" in TEAM_CONSOLE_ROLE_PERMISSIONS.get(current_role or "member", frozenset())


def can_assign_team_member_role(current_role: str | None, member_role: str) -> bool:
    return current_role == "owner" or member_role == "member"


def can_remove_team_member(current_role: str | None, target_role: str) -> bool:
    if target_role == "owner":
        return False
    return current_role == "owner" or (current_role == "admin" and target_role == "member")


async def get_team_entitlement_summaries(
    db: AsyncSession,
    *,
    site_id: int,
    owner_user_ids: list[int],
) -> dict[int, TeamEntitlementSummary]:
    normalized_ids = sorted({int(owner_user_id) for owner_user_id in owner_user_ids if int(owner_user_id) > 0})
    if not normalized_ids:
        return {}
    now = datetime.now(UTC)
    rows = (
        await db.execute(
            select(
                team_entitlements_table.c.owner_user_id,
                team_entitlements_table.c.seat_count,
                team_entitlements_table.c.expires_at,
            ).where(
                team_entitlements_table.c.site_id == site_id,
                team_entitlements_table.c.owner_user_id.in_(normalized_ids),
                team_entitlements_table.c.status == "active",
                team_entitlements_table.c.starts_at <= now,
                or_(team_entitlements_table.c.expires_at.is_(None), team_entitlements_table.c.expires_at > now),
            )
        )
    ).all()
    grouped: dict[int, list] = {}
    for row in rows:
        grouped.setdefault(int(row.owner_user_id), []).append(row)
    summaries: dict[int, TeamEntitlementSummary] = {}
    for owner_user_id, grants in grouped.items():
        expires_at = [grant.expires_at for grant in grants if grant.expires_at is not None]
        summaries[owner_user_id] = TeamEntitlementSummary(
            seat_limit=sum(max(0, int(grant.seat_count or 0)) for grant in grants),
            expires_at=max(expires_at) if expires_at else None,
            has_permanent_access=any(grant.expires_at is None for grant in grants),
            grant_count=len(grants),
        )
    return summaries


async def get_team_entitlement_summary(db: AsyncSession, *, site_id: int, owner_user_id: int) -> TeamEntitlementSummary:
    summaries = await get_team_entitlement_summaries(db, site_id=site_id, owner_user_ids=[owner_user_id])
    return summaries.get(owner_user_id, TeamEntitlementSummary())


async def grant_team_entitlement(
    db: AsyncSession,
    *,
    site_id: int,
    owner_user_id: int,
    seat_count: int,
    source: str,
    source_reference: str,
    duration_days: int = 0,
    note: str = "",
    created_by_admin_id: int | None = None,
) -> None:
    normalized_seats = int(seat_count)
    normalized_duration = max(0, int(duration_days))
    if normalized_seats < TEAM_COLLABORATION_MIN_SEATS:
        raise BusinessError("团队席位数至少为 2（含所有者）", code=40076)
    if not source.strip() or not source_reference.strip():
        raise BusinessError("团队权益来源不能为空", code=40077)
    now = datetime.now(UTC)
    await db.execute(
        team_entitlements_table.insert().values(
            site_id=site_id,
            owner_user_id=owner_user_id,
            seat_count=normalized_seats,
            source=source.strip()[:32],
            source_reference=source_reference.strip()[:128],
            status="active",
            starts_at=now,
            expires_at=now + timedelta(days=normalized_duration) if normalized_duration else None,
            note=note.strip()[:255],
            created_by_admin_id=created_by_admin_id,
        )
    )


async def _team_membership_row(db: AsyncSession, current_user: User, team_id: int | None = None):
    statement = (
        select(user_teams_table, user_team_members_table.c.role.label("current_role"))
        .select_from(user_teams_table.join(user_team_members_table, user_teams_table.c.id == user_team_members_table.c.team_id))
        .where(
            user_teams_table.c.site_id == current_user.site_id,
            user_team_members_table.c.site_id == current_user.site_id,
            user_team_members_table.c.user_id == current_user.id,
        )
    )
    if team_id is not None:
        statement = statement.where(user_teams_table.c.id == team_id)
    return (await db.execute(statement.order_by(user_team_members_table.c.created_at.asc(), user_team_members_table.c.id.asc()).limit(1))).first()


async def _set_active_team(db: AsyncSession, current_user: User, team_id: int) -> None:
    current_user.active_team_id = team_id
    await db.execute(
        update(User)
        .where(User.id == current_user.id, User.site_id == current_user.site_id)
        .values(active_team_id=team_id)
    )


async def get_or_create_user_team(db: AsyncSession, current_user: User):
    # Team creation is lazy and this helper is called by several request
    # paths. Serialize the check-and-create section on the user row so two
    # concurrent first requests cannot create duplicate personal teams.
    await db.execute(
        select(User.id)
        .where(User.id == current_user.id, User.site_id == current_user.site_id)
        .with_for_update()
    )
    active_team_id = getattr(current_user, "active_team_id", None)
    if active_team_id is not None:
        active_row = await _team_membership_row(db, current_user, int(active_team_id))
        if active_row is not None:
            return active_row

    membership_rows = (
        await db.execute(
            select(user_teams_table, user_team_members_table.c.role.label("current_role"))
            .select_from(user_teams_table.join(user_team_members_table, user_teams_table.c.id == user_team_members_table.c.team_id))
            .where(
                user_teams_table.c.site_id == current_user.site_id,
                user_team_members_table.c.site_id == current_user.site_id,
                user_team_members_table.c.user_id == current_user.id,
            )
            .order_by(user_team_members_table.c.created_at.asc(), user_team_members_table.c.id.asc())
        )
    ).all()
    # A user who was invited into an organization should land in that shared
    # workspace by default. Their own workspace remains available as the
    # explicit personal-billing option in the workspace switcher.
    membership_row = next(
        (row for row in membership_rows if int(row.owner_user_id) != int(current_user.id)),
        membership_rows[0] if membership_rows else None,
    )
    if membership_row is not None:
        if getattr(current_user, "active_team_id", None) != membership_row.id:
            await _set_active_team(db, current_user, int(membership_row.id))
            await db.commit()
        return membership_row

    display_name = current_user.nickname or current_user.username or "我的团队"
    result = await db.execute(
        user_teams_table.insert()
        .values(
            site_id=current_user.site_id,
            owner_user_id=current_user.id,
            name=f"{display_name}的团队"[:120],
            material_library_shared=True,
            image_history_shared=False,
        )
        .returning(user_teams_table.c.id)
    )
    team_id = int(result.scalar_one())
    await db.execute(
        user_team_members_table.insert().values(
            site_id=current_user.site_id,
            team_id=team_id,
            user_id=current_user.id,
            role="owner",
        )
    )
    await _set_active_team(db, current_user, team_id)
    await db.commit()
    created = await _team_membership_row(db, current_user, team_id)
    if created is None:
        raise BusinessError("团队初始化失败", code=50070, status_code=500)
    return created


def select_agent_billing_team(current_user_id: int, active_membership, external_memberships: list):
    """Resolve the wallet scope from the user's explicit workspace selection.

    The active membership is the source of truth for billing: selecting the
    user's own workspace means personal billing, while selecting an external
    membership means shared team billing.  Older sessions without an active
    selection still default to a single external team for backwards
    compatibility; multiple external teams require an explicit choice.
    """
    if active_membership is not None:
        return active_membership
    if len(external_memberships) == 1:
        return external_memberships[0]
    if len(external_memberships) > 1:
        raise BusinessError("你加入了多个团队，请先选择用于计费的团队", code=40978, status_code=409)
    return None


async def get_agent_billing_team(db: AsyncSession, current_user: User):
    active_team_id = getattr(current_user, "active_team_id", None)
    active_membership = await _team_membership_row(db, current_user, int(active_team_id)) if active_team_id else None
    external_memberships = (
        await db.execute(
            select(user_teams_table, user_team_members_table.c.role.label("current_role"))
            .select_from(user_teams_table.join(user_team_members_table, user_teams_table.c.id == user_team_members_table.c.team_id))
            .where(
                user_teams_table.c.site_id == current_user.site_id,
                user_teams_table.c.owner_user_id != current_user.id,
                user_team_members_table.c.site_id == current_user.site_id,
                user_team_members_table.c.user_id == current_user.id,
            )
            .order_by(user_team_members_table.c.created_at.asc(), user_team_members_table.c.id.asc())
            .limit(2)
        )
    ).all()
    selected = select_agent_billing_team(int(current_user.id), active_membership, external_memberships)
    if selected is None:
        return await get_or_create_user_team(db, current_user)
    if active_team_id is None or int(active_team_id) != int(selected.id):
        await _set_active_team(db, current_user, int(selected.id))
    return selected


async def get_primary_team_id(db: AsyncSession, current_user: User) -> int:
    row = await get_or_create_user_team(db, current_user)
    return int(row.id)


async def get_primary_team_settings(db: AsyncSession, current_user: User) -> dict:
    row = await get_or_create_user_team(db, current_user)
    member_count = await db.scalar(
        select(func.count()).select_from(user_team_members_table).where(user_team_members_table.c.team_id == row.id)
    )
    entitlement = await get_team_entitlement_summary(
        db,
        site_id=current_user.site_id,
        owner_user_id=int(row.owner_user_id),
    )
    settings = team_out(row, int(member_count or 1), str(row.current_role), entitlement)
    site_result = await db.execute(
        select(site_configs_table.c.site_name, site_configs_table.c.site_icon_url).where(
            site_configs_table.c.id == current_user.site_id
        )
    )
    site = site_result.one_or_none()
    settings["site_name"] = str(site.site_name or "") if site else ""
    settings["site_icon_url"] = str(site.site_icon_url or "/image2ai-icon.svg") if site else "/image2ai-icon.svg"
    return settings


async def update_primary_team_settings(
    db: AsyncSession,
    current_user: User,
    *,
    name: str | None,
    image_history_shared: bool | None,
) -> dict:
    row, _ = await _require_team_owner(db, current_user)
    values = {"updated_at": func.now()}
    if name is not None:
        clean_name = name.strip()
        if clean_name:
            values["name"] = clean_name[:120]
    if image_history_shared is not None:
        values["image_history_shared"] = bool(image_history_shared)
    await db.execute(
        update(user_teams_table)
        .where(user_teams_table.c.id == row.id, user_teams_table.c.site_id == current_user.site_id)
        .values(**values)
    )
    await db.commit()
    return await get_primary_team_settings(db, current_user)


async def list_user_teams(db: AsyncSession, current_user: User) -> list[dict]:
    await get_or_create_user_team(db, current_user)
    member_counts = (
        select(
            user_team_members_table.c.team_id.label("team_id"),
            func.count().label("member_count"),
        )
        .where(user_team_members_table.c.site_id == current_user.site_id)
        .group_by(user_team_members_table.c.team_id)
        .subquery()
    )
    rows = (
        await db.execute(
            select(
                user_teams_table,
                user_team_members_table.c.role.label("current_role"),
                member_counts.c.member_count,
            )
            .select_from(
                user_teams_table.join(user_team_members_table, user_teams_table.c.id == user_team_members_table.c.team_id).outerjoin(
                    member_counts, member_counts.c.team_id == user_teams_table.c.id
                )
            )
            .where(
                user_teams_table.c.site_id == current_user.site_id,
                user_team_members_table.c.site_id == current_user.site_id,
                user_team_members_table.c.user_id == current_user.id,
            )
            .order_by(user_team_members_table.c.created_at.asc(), user_team_members_table.c.id.asc())
        )
    ).all()
    active_team_id = getattr(current_user, "active_team_id", None)
    summaries = await get_team_entitlement_summaries(
        db,
        site_id=current_user.site_id,
        owner_user_ids=[int(row.owner_user_id) for row in rows],
    )
    return [
        {
            **team_out(
                row,
                int(row.member_count or 1),
                str(row.current_role),
                summaries.get(int(row.owner_user_id), TeamEntitlementSummary()),
            ),
            "is_active": int(row.id) == int(active_team_id) if active_team_id is not None else False,
        }
        for row in rows
    ]


async def set_primary_team(db: AsyncSession, current_user: User, team_id: int) -> dict:
    row = await _team_membership_row(db, current_user, team_id)
    if row is None:
        raise BusinessError("你不是该团队成员", code=40470, status_code=404)
    await _set_active_team(db, current_user, int(team_id))
    await db.commit()
    return await get_primary_team_settings(db, current_user)


async def _require_team_owner(db: AsyncSession, current_user: User):
    row = await get_or_create_user_team(db, current_user)
    entitlement = await get_team_entitlement_summary(
        db,
        site_id=current_user.site_id,
        owner_user_id=int(row.owner_user_id),
    )
    if not entitlement.collaboration_enabled:
        raise BusinessError("当前工作区尚未开通团队版", code=40375, status_code=403)
    if row.current_role != "owner":
        raise BusinessError("只有团队所有者可以管理成员", code=40371, status_code=403)
    return row, entitlement


async def _require_team_manager(db: AsyncSession, current_user: User):
    row = await get_or_create_user_team(db, current_user)
    entitlement = await get_team_entitlement_summary(
        db,
        site_id=current_user.site_id,
        owner_user_id=int(row.owner_user_id),
    )
    if not entitlement.collaboration_enabled:
        raise BusinessError("当前工作区尚未开通团队版", code=40375, status_code=403)
    if not can_manage_team_members(row.current_role):
        raise BusinessError("只有团队所有者或管理员可以管理成员", code=40372, status_code=403)
    return row, entitlement


async def list_primary_team_members(db: AsyncSession, current_user: User) -> list[dict]:
    team = await get_or_create_user_team(db, current_user)
    rows = (
        await db.execute(
            select(
                user_team_members_table.c.id.label("membership_id"),
                user_team_members_table.c.user_id,
                user_team_members_table.c.role,
                user_team_members_table.c.created_at.label("joined_at"),
                User.username,
                User.nickname,
                User.email,
                User.avatar_url,
            )
            .select_from(user_team_members_table.join(User, User.id == user_team_members_table.c.user_id))
            .where(
                user_team_members_table.c.site_id == current_user.site_id,
                user_team_members_table.c.team_id == team.id,
                User.site_id == current_user.site_id,
                User.deleted_at.is_(None),
            )
            .order_by(
                (user_team_members_table.c.role == "owner").desc(),
                user_team_members_table.c.created_at.asc(),
                user_team_members_table.c.id.asc(),
            )
        )
    ).all()
    return [team_member_out(row) for row in rows]


async def add_primary_team_member(
    db: AsyncSession,
    current_user: User,
    *,
    identifier: str,
    role: str | None,
) -> dict:
    team, entitlement = await _require_team_manager(db, current_user)
    account = identifier.strip()
    if not account:
        raise BusinessError("请输入成员邮箱或用户名", code=40071)
    if "@" in account:
        candidates = (
            await db.execute(
                select(User).where(
                    User.site_id == current_user.site_id,
                    func.lower(User.email) == account.lower(),
                    User.is_active.is_(True),
                    User.deleted_at.is_(None),
                )
            )
        ).scalars().all()
    else:
        candidates = (
            await db.execute(
                select(User).where(
                    User.site_id == current_user.site_id,
                    User.username == account,
                    User.is_active.is_(True),
                    User.deleted_at.is_(None),
                )
            )
        ).scalars().all()
    if not candidates:
        raise BusinessError("未找到该成员，请确认邮箱或用户名", code=40471, status_code=404)
    if len(candidates) > 1:
        raise BusinessError("该用户名不唯一，请使用邮箱添加成员", code=40971, status_code=409)
    user = candidates[0]
    exists = await db.scalar(
        select(user_team_members_table.c.id).where(
            user_team_members_table.c.team_id == team.id,
            user_team_members_table.c.user_id == user.id,
        )
    )
    if exists is not None:
        raise BusinessError("该用户已经是团队成员", code=40972, status_code=409)
    member_role = normalize_member_role(role)
    if not can_assign_team_member_role(team.current_role, member_role):
        raise BusinessError("管理员只能添加普通成员", code=40373, status_code=403)
    await db.execute(
        select(user_teams_table.c.id)
        .where(user_teams_table.c.id == team.id, user_teams_table.c.site_id == current_user.site_id)
        .with_for_update()
    )
    member_count = await db.scalar(
        select(func.count())
        .select_from(user_team_members_table)
        .where(
            user_team_members_table.c.team_id == team.id,
            user_team_members_table.c.site_id == current_user.site_id,
        )
    )
    if int(member_count or 0) >= entitlement.seat_limit:
        raise BusinessError("团队席位已用完，请先扩容或移除成员", code=40973, status_code=409)
    result = await db.execute(
        user_team_members_table.insert()
        .values(
            site_id=current_user.site_id,
            team_id=team.id,
            user_id=user.id,
            role=member_role,
        )
        .returning(user_team_members_table.c.id)
    )
    membership_id = int(result.scalar_one())
    await _set_active_team(db, user, int(team.id))
    from app.services.agent_provisioning import sync_agent_account

    await sync_agent_account(db, user)
    await db.commit()
    row = (
        await db.execute(
            select(
                user_team_members_table.c.id.label("membership_id"),
                user_team_members_table.c.user_id,
                user_team_members_table.c.role,
                user_team_members_table.c.created_at.label("joined_at"),
                User.username,
                User.nickname,
                User.email,
                User.avatar_url,
            )
            .select_from(user_team_members_table.join(User, User.id == user_team_members_table.c.user_id))
            .where(user_team_members_table.c.id == membership_id)
        )
    ).first()
    if row is None:
        raise BusinessError("成员添加失败", code=50071, status_code=500)
    return team_member_out(row)


async def update_primary_team_member_role(
    db: AsyncSession,
    current_user: User,
    *,
    membership_id: int,
    role: str,
) -> dict:
    team, _ = await _require_team_owner(db, current_user)
    target = (
        await db.execute(
            select(user_team_members_table).where(
                user_team_members_table.c.id == membership_id,
                user_team_members_table.c.team_id == team.id,
                user_team_members_table.c.site_id == current_user.site_id,
            )
        )
    ).first()
    if target is None:
        raise BusinessError("团队成员不存在", code=40472, status_code=404)
    if target.role == "owner":
        raise BusinessError("不能修改团队所有者角色", code=40072)
    await db.execute(
        update(user_team_members_table)
        .where(user_team_members_table.c.id == membership_id)
        .values(role=normalize_member_role(role), updated_at=func.now())
    )
    await db.commit()
    rows = await list_primary_team_members(db, current_user)
    updated = next((item for item in rows if item["membership_id"] == membership_id), None)
    if updated is None:
        raise BusinessError("团队成员更新失败", code=50072, status_code=500)
    return updated


async def remove_primary_team_member(db: AsyncSession, current_user: User, *, membership_id: int) -> None:
    team, _ = await _require_team_manager(db, current_user)
    target = (
        await db.execute(
            select(user_team_members_table.c.role).where(
                user_team_members_table.c.id == membership_id,
                user_team_members_table.c.team_id == team.id,
                user_team_members_table.c.site_id == current_user.site_id,
            )
        )
    ).first()
    if target is None:
        raise BusinessError("团队成员不存在", code=40472, status_code=404)
    if target.role == "owner":
        raise BusinessError("不能移除团队所有者", code=40073)
    if not can_remove_team_member(team.current_role, target.role):
        raise BusinessError("管理员只能移除普通成员", code=40374, status_code=403)
    await db.execute(user_team_members_table.delete().where(user_team_members_table.c.id == membership_id))
    await db.commit()


async def image_history_is_shared(db: AsyncSession, current_user: User) -> bool:
    row = await get_or_create_user_team(db, current_user)
    entitlement = await get_team_entitlement_summary(
        db,
        site_id=current_user.site_id,
        owner_user_id=int(row.owner_user_id),
    )
    return entitlement.collaboration_enabled and bool(row.image_history_shared)


async def material_library_is_shared(db: AsyncSession, current_user: User) -> bool:
    row = await get_or_create_user_team(db, current_user)
    entitlement = await get_team_entitlement_summary(
        db,
        site_id=current_user.site_id,
        owner_user_id=int(row.owner_user_id),
    )
    return entitlement.collaboration_enabled and bool(row.material_library_shared)
