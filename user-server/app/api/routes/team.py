from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.exceptions import BusinessError
from app.core.responses import StandardResponse, ok
from app.db.session import get_db
from app.models.user import User
from app.services.team_sharing import (
    add_primary_team_member,
    get_primary_team_settings,
    list_primary_team_members,
    list_user_teams,
    remove_primary_team_member,
    set_primary_team,
    update_primary_team_member_role,
    update_primary_team_settings,
)

router = APIRouter(prefix="/team", tags=["team"])


@router.get("", response_model=StandardResponse[dict])
async def team_settings(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> StandardResponse[dict]:
    return ok(await get_primary_team_settings(db, current_user))


@router.patch("", response_model=StandardResponse[dict])
async def update_team_settings(payload: dict, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> StandardResponse[dict]:
    if "image_history_shared" in payload and not isinstance(payload["image_history_shared"], bool):
        raise BusinessError("image_history_shared 必须是布尔值", code=40074)
    return ok(
        await update_primary_team_settings(
            db,
            current_user,
            name=str(payload.get("name")) if "name" in payload else None,
            image_history_shared=bool(payload.get("image_history_shared")) if "image_history_shared" in payload else None,
        ),
        "团队设置已更新",
    )


@router.get("/teams", response_model=StandardResponse[list])
async def team_list(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> StandardResponse[list]:
    return ok(await list_user_teams(db, current_user))


@router.post("/active", response_model=StandardResponse[dict])
async def change_active_team(payload: dict, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> StandardResponse[dict]:
    try:
        team_id = int(payload.get("team_id"))
    except (TypeError, ValueError) as exc:
        raise BusinessError("team_id 无效", code=40075) from exc
    return ok(await set_primary_team(db, current_user, team_id), "已切换当前团队")


@router.get("/members", response_model=StandardResponse[list])
async def team_members(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> StandardResponse[list]:
    return ok(await list_primary_team_members(db, current_user))


@router.post("/members", response_model=StandardResponse[dict])
async def add_team_member(payload: dict, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> StandardResponse[dict]:
    return ok(
        await add_primary_team_member(
            db,
            current_user,
            identifier=str(payload.get("identifier") or ""),
            role=str(payload.get("role") or "member"),
        ),
        "成员已添加",
    )


@router.patch("/members/{membership_id}", response_model=StandardResponse[dict])
async def update_team_member(
    membership_id: int,
    payload: dict,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StandardResponse[dict]:
    return ok(
        await update_primary_team_member_role(
            db,
            current_user,
            membership_id=membership_id,
            role=str(payload.get("role") or ""),
        ),
        "成员角色已更新",
    )


@router.delete("/members/{membership_id}", response_model=StandardResponse[None])
async def remove_team_member(
    membership_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StandardResponse[None]:
    await remove_primary_team_member(db, current_user, membership_id=membership_id)
    return ok(None, "成员已移除")
