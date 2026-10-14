from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.exceptions import BusinessError
from app.core.responses import StandardResponse, ok
from app.db.session import get_db
from app.models.user import User
from app.services.team_sharing import (
    add_primary_team_member,
    can_access_team_console,
    get_primary_team_settings,
    list_primary_team_members,
    remove_primary_team_member,
    team_console_permissions,
    update_primary_team_member_role,
    update_primary_team_settings,
)
from app.services.team_invites import create_team_invite_link
from app.services.team_usage import get_my_usage, list_team_member_usage, update_team_member_quotas
from app.services.team_usage_records import list_team_usage_records

router = APIRouter(prefix="/team-console", tags=["team-console"])


class TeamConsoleSettingsRequest(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    image_history_shared: bool | None = None

    @model_validator(mode="after")
    def require_update(self):
        if self.name is None and self.image_history_shared is None:
            raise ValueError("至少提供一个待更新字段")
        return self


class TeamConsoleMemberCreateRequest(BaseModel):
    identifier: str = Field(min_length=1, max_length=255)
    role: str = Field(default="member", pattern="^(admin|member)$")


class TeamConsoleMemberRoleRequest(BaseModel):
    role: str = Field(pattern="^(admin|member)$")


class TeamMemberQuotaRequest(BaseModel):
    text_quota: Decimal = Field(ge=0, le=Decimal("99999999999999"), max_digits=18, decimal_places=4)
    image_quota: Decimal = Field(ge=0, le=Decimal("99999999999999"), max_digits=18, decimal_places=4)


async def require_team_console_access(db: AsyncSession, current_user: User) -> dict:
    settings = await get_primary_team_settings(db, current_user)
    current_role = settings.get("current_role")
    if not settings.get("collaboration_enabled"):
        raise BusinessError("当前团队尚未开通团队版", code=40375, status_code=403)
    if not can_access_team_console(current_role):
        raise BusinessError("你没有团队管理权限", code=40376, status_code=403)
    return settings


async def require_team_console_permission(db: AsyncSession, current_user: User, permission: str) -> dict:
    settings = await require_team_console_access(db, current_user)
    if permission not in team_console_permissions(settings.get("current_role")):
        raise BusinessError("你没有执行此操作的权限", code=40377, status_code=403)
    return settings


@router.get("/session", response_model=StandardResponse[dict])
async def team_console_session(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StandardResponse[dict]:
    settings = await require_team_console_access(db, current_user)
    return ok({"team": settings, "permissions": team_console_permissions(settings.get("current_role"))})


@router.get("/members", response_model=StandardResponse[list])
async def team_console_members(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StandardResponse[list]:
    await require_team_console_permission(db, current_user, "members:view")
    return ok(await list_primary_team_members(db, current_user))


@router.post("/invite-link", response_model=StandardResponse[dict])
async def create_team_console_invite_link(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StandardResponse[dict]:
    settings = await require_team_console_permission(db, current_user, "members:create")
    return ok(
        await create_team_invite_link(db, current_user=current_user, team_id=int(settings["id"])),
        "团队邀请链接已生成",
    )


@router.patch("/settings", response_model=StandardResponse[dict])
async def update_team_console_settings(
    payload: TeamConsoleSettingsRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StandardResponse[dict]:
    await require_team_console_permission(db, current_user, "team:settings:update")
    settings = await update_primary_team_settings(
        db,
        current_user,
        name=payload.name,
        image_history_shared=payload.image_history_shared,
    )
    return ok(settings, "团队设置已更新")


@router.post("/members", response_model=StandardResponse[dict])
async def add_team_console_member(
    payload: TeamConsoleMemberCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StandardResponse[dict]:
    await require_team_console_permission(db, current_user, "members:create")
    return ok(
        await add_primary_team_member(db, current_user, identifier=payload.identifier, role=payload.role),
        "成员已添加",
    )


@router.patch("/members/{membership_id}", response_model=StandardResponse[dict])
async def update_team_console_member_role(
    membership_id: int,
    payload: TeamConsoleMemberRoleRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StandardResponse[dict]:
    await require_team_console_permission(db, current_user, "members:role:update")
    return ok(
        await update_primary_team_member_role(db, current_user, membership_id=membership_id, role=payload.role),
        "成员角色已更新",
    )


@router.delete("/members/{membership_id}", response_model=StandardResponse[None])
async def remove_team_console_member(
    membership_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StandardResponse[None]:
    await require_team_console_permission(db, current_user, "members:remove")
    await remove_primary_team_member(db, current_user, membership_id=membership_id)
    return ok(None, "成员已移出团队")


@router.get("/usage/me", response_model=StandardResponse[dict])
async def my_team_console_usage(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StandardResponse[dict]:
    await require_team_console_permission(db, current_user, "usage:self:view")
    return ok(await get_my_usage(db, current_user))


@router.get("/usage/members", response_model=StandardResponse[dict])
async def team_console_member_usage(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: str = Query("", max_length=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StandardResponse[dict]:
    await require_team_console_permission(db, current_user, "usage:view")
    return ok(
        await list_team_member_usage(
            db,
            current_user,
            page=page,
            page_size=page_size,
            search=search,
        )
    )


@router.patch("/usage/members/{membership_id}", response_model=StandardResponse[dict])
async def update_team_console_member_quotas(
    membership_id: int,
    payload: TeamMemberQuotaRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StandardResponse[dict]:
    await require_team_console_permission(db, current_user, "budgets:manage")
    return ok(
        await update_team_member_quotas(
            db,
            current_user,
            membership_id=membership_id,
            text_quota=payload.text_quota,
            image_quota=payload.image_quota,
        ),
        "成员额度已更新",
    )


@router.get("/usage/records", response_model=StandardResponse[dict])
async def team_console_usage_records(
    page: int = Query(1, ge=1, le=100),
    page_size: int = Query(20, ge=1, le=100),
    member_user_id: int | None = Query(default=None, gt=0),
    start_date: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    end_date: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StandardResponse[dict]:
    await require_team_console_permission(db, current_user, "usage:view")
    if start_date and end_date and start_date > end_date:
        raise BusinessError("开始日期不能晚于结束日期", code=40088)
    return ok(
        await list_team_usage_records(
            db,
            current_user,
            page=page,
            page_size=page_size,
            member_user_id=member_user_id,
            start_date=start_date,
            end_date=end_date,
        )
    )
